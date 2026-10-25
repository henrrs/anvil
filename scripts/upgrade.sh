#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/scripts/lib/common.sh"
source "$ROOT/scripts/lib/install.sh"
source "$ROOT/scripts/lib/backup.sh"
anvil_need python3 tar cp mv install chmod date

ANVIL_VERSION="$(cat "$ROOT/VERSION")"
operation=""
if [[ "${1:-}" == --migrate-runtime ]]; then
  operation="migrate-runtime"
elif [[ "${1:-}" == --update-runtime ]]; then
  operation="update-runtime"
else
  anvil_error "Unknown upgrade operation: $1"
  exit 2
fi
[[ $# == 1 ]] || { anvil_error 'Specify only one runtime lifecycle operation.'; exit 2; }
tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/anvil-upgrade.XXXXXX")"
chmod 700 -- "$tmp_root"
backup_dir=""
transaction_active=0
candidate=""
candidate_version=""
old_version=""
old_binary=""
old_anvil_version=""
from_generation=0
target_major=""

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
    anvil_error "Upgrade failed after live migration started (exit $status); restoring the verified pre-upgrade runtime snapshot."
    if ANVIL_INTERNAL_MODE=1 bash "$ROOT/scripts/rollback.sh" --backup "$backup_dir" --internal; then
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

anvil_require_installed
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
if python3 "$ROOT/scripts/configure.py" audit-v1 "$old_config" >/dev/null 2>&1; then
  from_generation=1
  python3 "$ROOT/scripts/configure.py" audit-v1 "$old_config"
elif python3 "$ROOT/scripts/configure.py" audit "$old_config" >/dev/null 2>&1; then
  from_generation=2
  python3 "$ROOT/scripts/configure.py" audit "$old_config"
else
  anvil_error 'Current global config is neither the supported Anvil V1 baseline nor a valid Anvil V2 config.'
  exit 1
fi

runtime_json="$(anvil_runtime_json)"
read -r old_binary old_version old_major runtime_supported < <(python3 - "$runtime_json" <<'PY'
import json,sys
r=json.loads(sys.argv[1]).get("runtime") or {}
print("\t".join(str(r.get(k) or "") for k in ("executable","version","generation","supported")))
PY
)
if [[ -z "$old_binary" || ! -x "$old_binary" || ( "$old_major" != 1 && "$old_major" != 2 ) || -z "$old_version" ]]; then
  anvil_error 'A usable OpenCode executable with a known supported major was not found. Install one with make reforge before updating or migrating it.'
  exit 1
fi
if [[ "$from_generation" == 1 && "$old_major" != 1 ]]; then
  anvil_error "Anvil V1 config reports an OpenCode $old_major executable; refusing a mismatched migration."
  exit 1
elif [[ "$from_generation" == 2 && "$old_major" != 2 ]]; then
  anvil_error "Anvil V2 config reports an OpenCode $old_major executable; refusing a mismatched update."
  exit 1
fi
if [[ "$old_major" != 1 && "$old_major" != 2 ]]; then
  anvil_error "OpenCode $old_version is outside the supported 1.x/2.x runtime policy."
  exit 1
fi
if [[ "$operation" == migrate-runtime ]]; then
  target_major="${OPENCODE_MAJOR:-}"
  if [[ "$target_major" != 1 && "$target_major" != 2 ]]; then
    anvil_error 'Runtime migration requires OPENCODE_MAJOR=1 or OPENCODE_MAJOR=2.'
    exit 2
  fi
  if [[ "$target_major" == "$old_major" ]]; then
    anvil_error "OpenCode $old_major is already installed; use 'make update-runtime' to update it within the current major."
    exit 2
  fi
elif [[ "$operation" == update-runtime ]]; then
  target_major="$old_major"
fi
if ! python3 "$ROOT/scripts/runtime.py" capabilities --major "$target_major" | python3 -c 'import json,sys; raise SystemExit(0 if json.load(sys.stdin)["runtime"]["supported"] else 1)'; then
  anvil_error "OpenCode $target_major is not supported by this Anvil runtime policy."
  exit 1
fi
policy_major="$(python3 "$ROOT/scripts/runtime.py" policy | python3 -c 'import json,sys; print(json.load(sys.stdin)["opencode"]["default_major"])')"

old_anvil_version="$(python3 - "$ANVIL_DATA_DIR/installation.json" "$from_generation" <<'PY'
import json,sys
try:
    value=json.load(open(sys.argv[1],encoding="utf-8"))
except (OSError,ValueError):
    value={}
recorded=value.get("anvil_version")
print(recorded or ("version not recorded" if sys.argv[2] == "1" else "unknown"))
PY
)"

if [[ "$operation" == update-runtime ]]; then
  printf '%s\n' 'OpenCode Runtime Update' '───────────────────────'
else
  printf '%s\n' 'OpenCode Runtime Migration' '──────────────────────────'
fi
printf 'Anvil release             %s (preserved on same-major update)\n' "${old_anvil_version:-unknown}"
printf 'Current OpenCode          %s\n' "$old_version"
printf 'OpenCode executable       %s\n' "$old_binary"
printf 'Target OpenCode major     %s (%s)\n' "$target_major" "$([[ "$old_major" == "$target_major" ]] && printf 'same-major update' || printf 'explicit migration')"
printf 'Managed configuration     %s\n' "$ANVIL_CONFIG_DIR"

if [[ "${DRY_RUN:-0}" == 1 ]]; then
  printf '\nOpenCode Runtime Plan\n────────────────────────────────\n'
  printf 'Anvil                    %s (preserved on same-major update)\n' "${old_anvil_version:-unknown}"
  printf 'OpenCode                 %s → OpenCode %s.x\n' "$old_version" "$target_major"
  printf 'Current runtime major    %s\n' "$old_major"
  printf 'Policy default major     %s\n' "$policy_major"
  printf 'Major migration          %s\n' "$([[ "$old_major" == "$target_major" ]] && printf 'NO' || printf 'YES (explicit)')"
  printf 'Runtime adapter          opencode-v%s → opencode-v%s\n' "$old_major" "$target_major"
  printf 'Backup                   complete config/runtime/data/state snapshot before any live changes\n'
  printf 'Rehearsal                isolated copy of config, data, state and Markdown memory\n'
  printf '\nCurrent runtime capabilities\n'
  python3 "$ROOT/scripts/runtime.py" capabilities --binary "$old_binary" --format text
  printf '\nTarget runtime profile capabilities\n'
  python3 "$ROOT/scripts/runtime.py" capabilities --major "$target_major" --format text
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
  if ! bash "$ROOT/scripts/install-opencode.sh" resolve "$target_major" > "$release_json"; then
    anvil_error 'OpenCode runtime release lookup failed. Anvil and the installed OpenCode runtime remain unchanged; this affects only the explicitly requested runtime operation.'
    exit 1
  fi
  candidate_version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8"))["version"])' "$release_json")"
  if ! candidate="$(bash "$ROOT/scripts/install-opencode.sh" stage "$candidate_version" "$tmp_root/candidate" "$target_major")"; then
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
if [[ "$operation" == update-runtime ]]; then
  cp -R -- "$ANVIL_CONFIG_DIR" "$ready_config"
else
  anvil_build_config "$ready_config" "$ANVIL_CONFIG_DIR" yes "$target_major"
fi
if [[ "$target_major" == 1 ]]; then
  python3 "$ROOT/scripts/configure.py" audit-v1 "$ready_config/opencode.jsonc"
else
  python3 "$ROOT/scripts/configure.py" audit "$ready_config/opencode.jsonc"
fi
if [[ "$operation" == update-runtime ]]; then
  bash "$ROOT/scripts/rehearse-upgrade.sh" "$candidate" "$candidate_version" "$old_major" "$target_major" yes
else
  bash "$ROOT/scripts/rehearse-upgrade.sh" "$candidate" "$candidate_version" "$old_major" "$target_major"
fi

if [[ "${DRY_RUN:-0}" == 1 ]]; then
  printf '\nCandidate                OpenCode %s\n' "$candidate_version"
  printf 'Config                   %s runtime profile staged and audited\n' "opencode-v$target_major"
  printf 'Migration rehearsal      passed against copied user state\n'
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

backup_dir="$(ANVIL_PREVIOUS_ANVIL_VERSION="$old_anvil_version" PATH="$ANVIL_INSTALL_BIN:$PATH" \
  anvil_backup_create "$candidate_version" "$path_plan" | tail -n 1)"
python3 "$ROOT/scripts/state.py" verify "$backup_dir"
if [[ "${ANVIL_TEST_FAIL_AFTER_BACKUP:-0}" == 1 ]]; then
  anvil_error 'Injected failure after backup verification and before live mutation.'
  exit 1
fi

transaction_active=1
if [[ "$operation" == migrate-runtime ]]; then
  anvil_log "Applying the staged OpenCode $target_major Anvil profile and exact tested binary."
  anvil_apply_config "$ready_config"
  if [[ "${ANVIL_TEST_FAIL_AFTER_CONFIG:-0}" == 1 ]]; then
    anvil_error 'Injected failure after config replacement.'
    false
  fi
fi
bash "$ROOT/scripts/install-opencode.sh" install "$candidate" "$candidate_version" "$target_major"
path_result="$(python3 "$ROOT/scripts/path_edit.py" apply \
  --home "$ANVIL_HOME_DIR" --xdg-config-home "$ANVIL_CONFIG_HOME" \
  --install-dir "$ANVIL_INSTALL_BIN" --shell "${SHELL:-bash}" --path "$PATH")"
if [[ "${ANVIL_TEST_FAIL_AFTER_INSTALL:-0}" == 1 ]]; then
  anvil_error 'Injected failure after exact candidate installation.'
  false
fi

export PATH="$ANVIL_INSTALL_BIN:$PATH"
if [[ "$operation" == migrate-runtime ]]; then
  XDG_DATA_HOME="$ANVIL_DATA_HOME" python3 "$ANVIL_CONFIG_DIR/scripts/memory.py" init >/dev/null
fi
if [[ "${ANVIL_TEST_FAIL_POSTFLIGHT:-0}" == 1 ]]; then
  anvil_error 'Injected postflight failure after the runtime upgrade.'
  false
fi
installation_args=(
  --destination "$ANVIL_DATA_DIR/installation.json" \
  --opencode-version "$candidate_version" --anvil-version "$ANVIL_VERSION" \
  --opencode-major "$target_major" \
  --binary "$ANVIL_INSTALLED_BINARY" --release-json "$release_json" \
  --migration-status "$([[ "$operation" == update-runtime ]] && printf runtime-update || printf completed)" \
  --previous-anvil-version "$old_anvil_version" \
  --previous-opencode-version "$old_version" --from-generation "$from_generation" \
  --backup "$backup_dir"
)
if [[ "$operation" == update-runtime ]]; then installation_args+=(--runtime-only); fi
python3 "$ROOT/scripts/installation.py" "${installation_args[@]}"
python3 "$ROOT/scripts/runtime_state.py" record --binary "$ANVIL_INSTALLED_BINARY" >/dev/null

doctor_status=0
if [[ "${ANVIL_TEST_FAIL_DOCTOR:-0}" == 1 ]]; then
  anvil_error 'Injected post-upgrade doctor failure.'
  doctor_status=1
else
ANVIL_DOCTOR_LOCAL=1 bash "$ROOT/scripts/doctor.sh" || doctor_status=$?
fi
if (( doctor_status == 1 || doctor_status > 2 )); then
  anvil_error 'Post-upgrade doctor reported a broken installation.'
  false
elif (( doctor_status == 2 )); then
  anvil_warn 'Upgrade completed with project or source-drift warnings from doctor.'
fi

transaction_active=0
if [[ "$operation" == update-runtime ]]; then
  anvil_ok "OpenCode $candidate_version is installed; Anvil ${old_anvil_version:-unknown} was preserved."
else
  anvil_ok "Anvil $ANVIL_VERSION with OpenCode $candidate_version is installed."
fi
anvil_ok "Rollback snapshot: $backup_dir"
if [[ "$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("added",False))' "$path_result")" == True ]]; then
  anvil_log "Added $ANVIL_INSTALL_BIN to the selected shell startup file; open a new shell to refresh PATH."
elif [[ "$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("manual_required",False))' "$path_result")" == True ]]; then
  anvil_warn "Could not safely edit $(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("file", "the shell startup file"))' "$path_result"). Add $ANVIL_INSTALL_BIN to PATH manually."
fi
anvil_offer_databricks_setup
