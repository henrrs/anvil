#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/scripts/lib/common.sh"
source "$ROOT/scripts/lib/install.sh"
source "$ROOT/scripts/lib/backup.sh"
anvil_need python3 tar cp mv install chmod date

ANVIL_VERSION="$(cat "$ROOT/VERSION")"
operation="upgrade"
if [[ "${1:-}" == --migrate-runtime ]]; then
  operation="migrate-runtime"
elif [[ $# -gt 0 ]]; then
  anvil_error "Unknown upgrade operation: $1"
  exit 2
fi
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

if [[ ! -f "$ANVIL_CONFIG_DIR/opencode.jsonc" ]]; then
  anvil_error 'No installed Anvil configuration found; use make reforge for a clean installation.'
  exit 1
fi
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

old_binary="$ANVIL_INSTALLED_BINARY"
if [[ ! -x "$old_binary" ]]; then
  old_binary="$(type -P opencode 2>/dev/null || true)"
fi
if [[ -z "$old_binary" || ! -x "$old_binary" ]]; then
  anvil_error "OpenCode executable not found at $ANVIL_INSTALLED_BINARY or on PATH; install or restore the V1 OpenCode executable before upgrading."
  exit 1
fi
old_version="$("$old_binary" --version 2>/dev/null | head -n 1)"
old_version="${old_version#opencode }"
old_version="${old_version#v}"
old_major="${old_version%%.*}"
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
    anvil_error "OpenCode $old_major is already installed; use 'make upgrade' to update Anvil and that runtime."
    exit 2
  fi
else
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

printf '%s\n' 'Anvil Upgrade' '─────────────'
printf 'Anvil release             %s → %s\n' "${old_anvil_version:-unknown}" "$ANVIL_VERSION"
printf 'Current OpenCode          %s\n' "$old_version"
printf 'OpenCode executable       %s\n' "$old_binary"
printf 'Target OpenCode major     %s (%s)\n' "$target_major" "$([[ "$old_major" == "$target_major" ]] && printf 'preserved' || printf 'explicit migration')"
printf 'Managed configuration     %s\n' "$ANVIL_CONFIG_DIR"

if [[ "${DRY_RUN:-0}" == 1 ]]; then
  printf '\nAnvil Upgrade Plan\n────────────────────────────────\n'
  printf 'Anvil                    %s → %s\n' "${old_anvil_version:-unknown}" "$ANVIL_VERSION"
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
  bash "$ROOT/scripts/install-opencode.sh" resolve "$target_major" > "$release_json"
  candidate_version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8"))["version"])' "$release_json")"
  candidate="$(bash "$ROOT/scripts/install-opencode.sh" stage "$candidate_version" "$tmp_root/candidate" "$target_major")"
  cp -- "$tmp_root/candidate/release.json" "$release_json"
fi
[[ "$candidate_version" =~ ^${target_major}\.[0-9]+\.[0-9]+$ ]] || { anvil_error "Resolved candidate is not a stable OpenCode $target_major version: $candidate_version"; exit 1; }
anvil_ok "Resolved and staged exact stable OpenCode $candidate_version"

ready_config="$tmp_root/staged-config"
anvil_build_config "$ready_config" "$ANVIL_CONFIG_DIR" yes "$target_major"
if [[ "$target_major" == 1 ]]; then
  python3 "$ROOT/scripts/configure.py" audit-v1 "$ready_config/opencode.jsonc"
else
  python3 "$ROOT/scripts/configure.py" audit "$ready_config/opencode.jsonc"
fi
bash "$ROOT/scripts/rehearse-upgrade.sh" "$candidate" "$candidate_version" "$old_major" "$target_major"

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
    anvil_error 'Upgrade needs one confirmation in an interactive terminal; set ANVIL_YES=1 only after reviewing the migration plan.'
    exit 2
  fi
  printf '\nThe isolated runtime rehearsal passed. This operation will apply the OpenCode %s Anvil profile and preserve a complete snapshot before changing live files.\n' "$target_major"
  read -r -p 'Continue with Anvil operation? [y/N] ' answer
  [[ "$answer" == y || "$answer" == Y || "$answer" == yes || "$answer" == YES ]] || {
    anvil_log 'Upgrade cancelled; no live config, binary, OpenCode data or OpenCode state was changed.'
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
anvil_log "Applying the staged OpenCode $target_major config and exact tested binary."
anvil_apply_config "$ready_config"
if [[ "${ANVIL_TEST_FAIL_AFTER_CONFIG:-0}" == 1 ]]; then
  anvil_error 'Injected failure after config replacement.'
  false
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
XDG_DATA_HOME="$ANVIL_DATA_HOME" python3 "$ANVIL_CONFIG_DIR/scripts/memory.py" init >/dev/null
if [[ "${ANVIL_TEST_FAIL_POSTFLIGHT:-0}" == 1 ]]; then
  anvil_error 'Injected postflight failure after the runtime upgrade.'
  false
fi
python3 "$ROOT/scripts/installation.py" \
  --destination "$ANVIL_DATA_DIR/installation.json" \
  --opencode-version "$candidate_version" --anvil-version "$ANVIL_VERSION" \
  --opencode-major "$target_major" \
  --binary "$ANVIL_INSTALLED_BINARY" --release-json "$release_json" \
  --migration-status completed --previous-anvil-version "$old_anvil_version" \
  --previous-opencode-version "$old_version" --from-generation "$from_generation" \
  --backup "$backup_dir"

doctor_status=0
if [[ "${ANVIL_TEST_FAIL_DOCTOR:-0}" == 1 ]]; then
  anvil_error 'Injected post-upgrade doctor failure.'
  doctor_status=1
else
  bash "$ROOT/scripts/doctor.sh" || doctor_status=$?
fi
if (( doctor_status == 1 || doctor_status > 2 )); then
  anvil_error 'Post-upgrade doctor reported a broken installation.'
  false
elif (( doctor_status == 2 )); then
  anvil_warn 'Upgrade completed with project or source-drift warnings from doctor.'
fi

transaction_active=0
anvil_ok "Anvil $ANVIL_VERSION with OpenCode $candidate_version is installed."
anvil_ok "Rollback snapshot: $backup_dir"
if [[ "$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("added",False))' "$path_result")" == True ]]; then
  anvil_log "Added $ANVIL_INSTALL_BIN to the selected shell startup file; open a new shell to refresh PATH."
elif [[ "$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("manual_required",False))' "$path_result")" == True ]]; then
  anvil_warn "Could not safely edit $(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("file", "the shell startup file"))' "$path_result"). Add $ANVIL_INSTALL_BIN to PATH manually."
fi
