#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/scripts/lib/common.sh"
source "$ROOT/scripts/lib/install.sh"
source "$ROOT/scripts/lib/backup.sh"
source "$ROOT/scripts/lib/lifecycle-operation.sh"
anvil_need python3 tar cp mv install chmod date

ANVIL_VERSION="$(cat "$ROOT/VERSION")"
[[ "${1:-}" == --update-runtime && $# == 1 ]] || {
  anvil_error 'Use make update-runtime to update within supported OpenCode 1.x releases.'
  exit 2
}
operation="update-runtime"
tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/anvil-upgrade.XXXXXX")"
chmod 700 -- "$tmp_root"
backup_dir=""
transaction_active=0
candidate=""
candidate_version=""
old_version=""
old_binary=""
old_anvil_version=""
target_major=1

cleanup_temp() {
  local base canonical
  base="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "${TMPDIR:-/tmp}")/anvil-upgrade."
  canonical="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$tmp_root")"
  if [[ -d "$canonical" && "$canonical" == "$base"* && "$canonical" != / ]]; then rm -rf -- "$canonical"; fi
}

on_error() {
  local status=$?
  trap - ERR INT TERM
  if (( transaction_active )) && [[ -n "$backup_dir" ]]; then
    anvil_error "Upgrade failed after the runtime update started (exit $status); restoring the verified pre-update runtime snapshot."
    if ANVIL_INTERNAL_MODE=1 bash "$ROOT/scripts/rollback.sh" --backup "$backup_dir" --internal; then
      python3 "$ROOT/scripts/lifecycle_transaction.py" clear || anvil_error 'Automatic rollback completed, but the recovery journal could not be cleared.'
      anvil_ok 'Automatic rollback completed; Anvil memory remains in place.'
    else
      anvil_error "Automatic rollback failed. The verified snapshot remains at $backup_dir"
    fi
  fi
  cleanup_temp
  exit "$status"
}
trap on_error ERR INT TERM
trap cleanup_temp EXIT

anvil_recover_pending
anvil_require_installed
plan_file="$tmp_root/change-plan.json"
if ! python3 "$ROOT/scripts/lifecycle_plan.py" "$operation" \
  --format json --json-output "$plan_file" >/dev/null; then
  python3 "$ROOT/scripts/lifecycle_plan.py" "$operation" --format text || true
  exit 2
fi
anvil_lifecycle_validate_plan "$operation" "$plan_file" >/dev/null
if [[ -L "$ANVIL_CONFIG_DIR" || -L "$ANVIL_INSTALL_ROOT" || -L "$ANVIL_INSTALL_BIN" ]]; then
  anvil_error 'Managed config/install paths must not be symlinks.'
  exit 1
fi
if ! anvil_safe_managed_path "$ANVIL_CONFIG_DIR" "$ANVIL_CONFIG_DIR" || \
   [[ "$ANVIL_INSTALL_ROOT" != "$ANVIL_HOME_DIR/.opencode" || "$ANVIL_INSTALL_ROOT" == / || "$ANVIL_INSTALL_ROOT" == "$ANVIL_HOME_DIR" ]]; then
  anvil_error 'Managed paths did not pass the safety check.'
  exit 1
fi

if ! python3 "$ROOT/scripts/active-opencode.py"; then
  anvil_error 'Upgrade stopped before touching live state so OpenCode data can be copied consistently.'
  exit 1
fi

old_config="$ANVIL_CONFIG_DIR/opencode.jsonc"
python3 "$ROOT/scripts/configure.py" audit-compatible "$old_config" || {
  anvil_error 'Current global config is not a supported Anvil OpenCode 1 profile.'
  exit 1
}
runtime_json="$(anvil_runtime_json)"
IFS=$'\t' read -r old_binary old_version old_major runtime_supported < <(python3 - "$runtime_json" <<'PY'
import json,sys
r=json.loads(sys.argv[1]).get("runtime") or {}
print("\t".join(str(r.get(k) or "") for k in ("executable","version","generation","supported")))
PY
)
if [[ -z "$old_binary" || ! -x "$old_binary" || "$old_major" != 1 || -z "$old_version" || "$runtime_supported" != True ]]; then
  anvil_error 'A usable, supported OpenCode 1 runtime is required; no runtime files were changed.'
  exit 1
fi
old_anvil_version="$(python3 - "$ANVIL_DATA_DIR/installation.json" <<'PY'
import json,sys
try:
    value=json.load(open(sys.argv[1],encoding="utf-8"))
except (OSError,ValueError):
    value={}
if not isinstance(value,dict): value={}
print(value.get("anvil_version") or "unknown")
PY
)"

printf '%s\n' 'OpenCode 1 Runtime Update' '──────────────────────────'
printf 'Anvil release             %s (preserved)\n' "${old_anvil_version:-unknown}"
printf 'Current OpenCode          %s\n' "$old_version"
printf 'OpenCode executable       %s\n' "$old_binary"
printf 'Target OpenCode           %s.x\n' "$target_major"
printf 'Managed configuration     %s\n' "$ANVIL_CONFIG_DIR"

if [[ "${DRY_RUN:-0}" == 1 ]]; then
  python3 "$ROOT/scripts/lifecycle_plan.py" --render-file "$plan_file"
  printf '\nOpenCode Runtime Plan\n────────────────────────────────\n'
  printf 'Anvil                    %s (preserved)\n' "${old_anvil_version:-unknown}"
  printf 'OpenCode                 %s → latest supported 1.x\n' "$old_version"
  printf 'Backup                   complete config/runtime/data/state snapshot before any live changes\n'
  printf 'Rehearsal                isolated copy of config, data, state and Markdown memory\n'
  printf '\nCurrent runtime capabilities\n'
  python3 "$ROOT/scripts/runtime.py" capabilities --binary "$old_binary" --format text
fi

release_json="$tmp_root/release.json"
if [[ "${ANVIL_TEST_MODE:-0}" == 1 ]]; then
  candidate="${ANVIL_TEST_CANDIDATE_BINARY:-}"
  [[ -n "$candidate" && -x "$candidate" ]] || { anvil_error 'Test mode requires ANVIL_TEST_CANDIDATE_BINARY.'; exit 2; }
  mkdir -p -- "$tmp_root/test-home" "$tmp_root/test-config" "$tmp_root/test-data" "$tmp_root/test-state"
  candidate_version="$(env -i PATH="${PATH:-/usr/bin:/bin}" HOME="$tmp_root/test-home" \
    XDG_CONFIG_HOME="$tmp_root/test-config" XDG_DATA_HOME="$tmp_root/test-data" \
    XDG_STATE_HOME="$tmp_root/test-state" "$candidate" --version 2>/dev/null | head -n 1)"
  candidate_version="${candidate_version#opencode }"
  candidate_version="${candidate_version#v}"
  python3 - "$release_json" "$candidate_version" <<'PY'
import json,sys
with open(sys.argv[1],"w",encoding="utf-8") as stream:
    json.dump({"version":sys.argv[2],"channel":"latest","published_at":None,"release_url":"isolated test candidate","asset":{"name":"fixture","integrity":"sha512-fixture"}},stream)
PY
else
  if ! bash "$ROOT/scripts/install-opencode.sh" resolve > "$release_json"; then
    anvil_error 'OpenCode runtime release lookup failed. Anvil and the installed OpenCode runtime remain unchanged; this affects only the explicitly requested runtime operation.'
    exit 1
  fi
  candidate_version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8"))["version"])' "$release_json")"
  if ! candidate="$(bash "$ROOT/scripts/install-opencode.sh" stage "$candidate_version" "$tmp_root/candidate")"; then
    anvil_error 'OpenCode runtime download/validation failed. Anvil and the installed runtime remain unchanged; retry when the release source is reachable.'
    exit 1
  fi
  cp -- "$tmp_root/candidate/release.json" "$release_json"
fi
[[ "$candidate_version" =~ ^${target_major}\.[0-9]+\.[0-9]+$ ]] || { anvil_error "Resolved candidate is not a stable OpenCode $target_major version: $candidate_version"; exit 1; }
if [[ "$operation" == update-runtime ]] && ! python3 - "$old_version" "$candidate_version" <<'PY'
import sys
def version(value): return tuple(int(part) for part in value.split("."))
raise SystemExit(0 if version(sys.argv[2]) >= version(sys.argv[1]) else 1)
PY
then
  anvil_error "Resolved OpenCode $candidate_version is older than installed $old_version. No files were changed; refusing a runtime downgrade."
  exit 1
fi
candidate_state="$(python3 "$ROOT/scripts/runtime_state.py" discover --binary "$candidate" --format json)"
if ! python3 - "$candidate_state" <<'PY'
import json,sys
runtime=json.loads(sys.argv[1]).get("runtime") or {}
raise SystemExit(0 if runtime.get("supported") else 1)
PY
then
  anvil_error "OpenCode $candidate_version does not meet Anvil's minimum supported runtime policy. No live files were changed."
  exit 1
fi
anvil_ok "Resolved and staged exact stable OpenCode $candidate_version"

ready_config="$tmp_root/staged-config"
cp -R -- "$ANVIL_CONFIG_DIR" "$ready_config"
python3 "$ROOT/scripts/configure.py" audit-compatible "$ready_config/opencode.jsonc"
bash "$ROOT/scripts/rehearse-upgrade.sh" "$candidate" "$candidate_version" yes

if [[ "${DRY_RUN:-0}" == 1 ]]; then
  printf '\nCandidate                OpenCode %s\n' "$candidate_version"
  printf 'Config                   %s runtime profile staged and audited\n' "opencode-v$target_major"
  printf 'Runtime rehearsal        passed with disposable OpenCode data/state\n'
  printf '\nDry run complete. No backup was created and no live files were changed.\n'
  exit 0
fi

path_plan="$(python3 "$ROOT/scripts/path_edit.py" plan \
  --home "$ANVIL_HOME_DIR" --xdg-config-home "$ANVIL_CONFIG_HOME" \
  --install-dir "$ANVIL_INSTALL_BIN" --shell "${SHELL:-bash}" --path "$PATH")"

if [[ "${ANVIL_YES:-0}" != 1 ]]; then
  if [[ ! -t 0 ]]; then
  anvil_error 'Runtime operation needs one confirmation in an interactive terminal; set ANVIL_YES=1 only after reviewing the plan.'
    exit 2
  fi
  printf '\nThe isolated runtime rehearsal passed. This operation will preserve a complete snapshot before changing the OpenCode runtime.\n'
  read -r -p 'Continue with Anvil operation? [y/N] ' answer
  [[ "$answer" == y || "$answer" == Y || "$answer" == yes || "$answer" == YES ]] || {
    anvil_log 'Runtime operation cancelled; no live files were changed.'
    exit 0
  }
fi

anvil_lifecycle_validate_plan "$operation" "$plan_file" "$target_major" >/dev/null
backup_dir="$(ANVIL_PREVIOUS_ANVIL_VERSION="$old_anvil_version" PATH="$ANVIL_INSTALL_BIN:$PATH" \
  anvil_backup_create "$candidate_version" "$path_plan" | tail -n 1)"
if [[ "${ANVIL_TEST_FAIL_AFTER_BACKUP:-0}" == 1 ]]; then
  anvil_error 'Injected failure after backup verification and before live mutation.'
  exit 1
fi

apply_runtime_change() {
  anvil_lifecycle_require_plan_operation InstallRuntimeArtifact || return $?
  bash "$ROOT/scripts/install-opencode.sh" install "$candidate" "$candidate_version" || return $?
  path_result="$(python3 "$ROOT/scripts/path_edit.py" apply \
    --home "$ANVIL_HOME_DIR" --xdg-config-home "$ANVIL_CONFIG_HOME" \
    --install-dir "$ANVIL_INSTALL_BIN" --shell "${SHELL:-bash}" --path "$PATH")" || return $?
  if [[ "${ANVIL_TEST_FAIL_AFTER_INSTALL:-0}" == 1 ]]; then
    anvil_error 'Injected failure after exact candidate installation.'
    return 1
  fi
  export PATH="$ANVIL_INSTALL_BIN:$PATH"
  if [[ "${ANVIL_TEST_FAIL_POSTFLIGHT:-0}" == 1 ]]; then
    anvil_error 'Injected postflight failure after the runtime upgrade.'
    return 1
  fi
}

verify_runtime_change() {
  if [[ "${ANVIL_TEST_FAIL_BEFORE_METADATA:-0}" == 1 ]]; then
    anvil_error 'Injected failure before installation metadata was written.'
    return 1
  fi
  if [[ "${ANVIL_TEST_FAIL_DOCTOR:-0}" == 1 ]]; then
    anvil_error 'Injected post-apply verification failure.'
    return 1
  fi
  verify_product_version="$old_anvil_version"
  python3 "$ROOT/scripts/lifecycle_verify.py" \
    --config "$ANVIL_CONFIG_DIR" --memory "$ANVIL_DATA_DIR/memory" --binary "$ANVIL_INSTALLED_BINARY" \
    --product-version "$verify_product_version" --runtime-version "$candidate_version" --runtime-major "$target_major"
}

commit_runtime_change() {
  installation_args=(
    --destination "$ANVIL_DATA_DIR/installation.json" \
    --config-dir "$ANVIL_CONFIG_DIR" \
    --opencode-version "$candidate_version" --anvil-version "$ANVIL_VERSION" \
    --opencode-major "$target_major" \
    --binary "$ANVIL_INSTALLED_BINARY" --release-json "$release_json" \
    --migration-status runtime-update \
    --previous-anvil-version "$old_anvil_version" \
    --previous-opencode-version "$old_version" --from-generation 1 \
    --backup "$backup_dir"
  )
  installation_args+=(--runtime-only)
  python3 "$ROOT/scripts/installation.py" "${installation_args[@]}" || return $?
  python3 "$ROOT/scripts/runtime_state.py" record --binary "$ANVIL_INSTALLED_BINARY" >/dev/null || return $?
}

rollback_runtime_change() {
  ANVIL_INTERNAL_MODE=1 bash "$ROOT/scripts/rollback.sh" --backup "$backup_dir" --internal
}

anvil_lifecycle_execute "$operation" "$backup_dir" "$old_anvil_version" "$ANVIL_VERSION" \
  apply_runtime_change verify_runtime_change commit_runtime_change rollback_runtime_change \
  'Automatic rollback completed; Anvil memory remains in place.' \
  'OpenCode runtime operation failed after live mutation' "$plan_file" "$target_major"
anvil_ok "OpenCode $candidate_version is installed; Anvil ${old_anvil_version:-unknown} was preserved."
anvil_ok "Rollback snapshot: $backup_dir"
if [[ "$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("added",False))' "$path_result")" == True ]]; then
  anvil_log "Added $ANVIL_INSTALL_BIN to the selected shell startup file; open a new shell to refresh PATH."
elif [[ "$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("manual_required",False))' "$path_result")" == True ]]; then
  anvil_warn "Could not safely edit $(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("file", "the shell startup file"))' "$path_result"). Add $ANVIL_INSTALL_BIN to PATH manually."
fi
anvil_offer_databricks_setup
