#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/scripts/lib/common.sh"
source "$ROOT/scripts/lib/install.sh"
source "$ROOT/scripts/lib/backup.sh"
ANVIL_VERSION="$(cat "$ROOT/VERSION")"

anvil_need python3 tar cp mv install chmod date ps
python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("ERROR Anvil requires Python 3.11 or newer.")
PY

if ! anvil_safe_managed_path "$ANVIL_CONFIG_DIR" "$ANVIL_CONFIG_DIR"; then
  anvil_error 'Global config path did not pass the managed-path check.'
  exit 1
fi
if [[ "$ANVIL_INSTALL_ROOT" != "$ANVIL_HOME_DIR/.opencode" || "$ANVIL_INSTALL_ROOT" == / || "$ANVIL_INSTALL_ROOT" == "$ANVIL_HOME_DIR" ]]; then
  anvil_error 'OpenCode installer directory did not pass the managed-path check.'
  exit 1
fi
if [[ -L "$ANVIL_INSTALL_ROOT" || -L "$ANVIL_INSTALL_BIN" ]]; then
  anvil_error 'The OpenCode installer directory or bin directory is a symlink; refusing to install through it.'
  exit 1
fi
python3 "$ROOT/scripts/active-opencode.py" || {
  anvil_error 'Close OpenCode before reforge so its database can be backed up consistently.'
  exit 1
}

tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/anvil-reforge.XXXXXX")"
backup_dir=""
transaction_active=0
candidate=""
candidate_version=""
previous_anvil_version=""
previous_opencode_version=""
from_generation=0

if [[ -f "$ANVIL_DATA_DIR/installation.json" ]]; then
  IFS=$'\t' read -r previous_anvil_version previous_opencode_version < <(python3 - "$ANVIL_DATA_DIR/installation.json" <<'PY'
import json,sys
try: value=json.load(open(sys.argv[1],encoding="utf-8"))
except (OSError,ValueError): value={}
print(f"{value.get('anvil_version','')}\t{value.get('version','')}")
PY
)
fi
if python3 "$ROOT/scripts/configure.py" audit-v1 "$ANVIL_CONFIG_DIR/opencode.jsonc" >/dev/null 2>&1; then
  from_generation=1
  [[ -n "$previous_anvil_version" ]] || previous_anvil_version='V1 (version not recorded)'
elif python3 "$ROOT/scripts/configure.py" audit "$ANVIL_CONFIG_DIR/opencode.jsonc" >/dev/null 2>&1; then
  from_generation=2
fi

cleanup_temp() {
  local base="${TMPDIR:-/tmp}/anvil-reforge."
  if [[ -n "$tmp_root" && -d "$tmp_root" && "$tmp_root" == "$base"* && "$tmp_root" != / ]]; then
    local canonical
    canonical="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$tmp_root")"
    if [[ "$canonical" == "$tmp_root" ]]; then rm -rf -- "$tmp_root"; fi
  fi
}

on_error() {
  local status=$?
  trap - ERR INT TERM
  if (( transaction_active )) && [[ -n "$backup_dir" ]]; then
    anvil_error "Reforge failed after the reset began (exit $status); attempting rollback."
    if ANVIL_INTERNAL_MODE=1 bash "$ROOT/scripts/rollback.sh" --backup "$backup_dir" --internal; then
      anvil_ok 'Automatic rollback completed.'
    else
      anvil_error "Automatic rollback failed. Verified backup remains at $backup_dir"
    fi
  fi
  cleanup_temp
  exit "$status"
}
trap on_error ERR INT TERM
trap cleanup_temp EXIT

printf '%s\n' 'Anvil Reforge' '─────────────'
printf 'Global config: %s\n' "$ANVIL_CONFIG_DIR"
printf 'Installer dir: %s\n' "$ANVIL_INSTALL_ROOT"
bash "$ROOT/scripts/inspect.sh"

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
  json.dump({"version":sys.argv[2],"channel":"latest","published_at":None,"release_url":"isolated fixture","asset":{"name":"fixture","integrity":"sha512-fixture"}},stream)
PY
else
  anvil_need python3
  resolved="$tmp_root/resolved.json"
  bash "$ROOT/scripts/install-opencode.sh" resolve > "$resolved"
  candidate_version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8"))["version"])' "$resolved")"
  candidate="$(bash "$ROOT/scripts/install-opencode.sh" stage "$candidate_version" "$tmp_root/candidate")"
  cp -- "$tmp_root/candidate/release.json" "$release_json"
fi

[[ "$candidate_version" =~ ^2\.[0-9]+\.[0-9]+$ ]] || { anvil_error "Invalid stable OpenCode 2 version: $candidate_version"; exit 1; }
anvil_ok "Staged official OpenCode $candidate_version"

ready_config="$tmp_root/global-config"
anvil_build_config "$ready_config" "$ANVIL_CONFIG_DIR"
python3 "$ROOT/scripts/configure.py" audit "$ready_config/opencode.jsonc"
bash "$ROOT/scripts/validate-candidate.sh" "$candidate" "$ready_config" "$candidate_version"

path_plan="$(python3 "$ROOT/scripts/path_edit.py" plan \
  --home "$ANVIL_HOME_DIR" --xdg-config-home "$ANVIL_CONFIG_HOME" \
  --install-dir "$ANVIL_INSTALL_BIN" --shell "${SHELL:-bash}" --path "$PATH")"
backup_dir="$(anvil_backup_create "$candidate_version" "$path_plan" | tail -n 1)"
python3 "$ROOT/scripts/state.py" verify "$backup_dir"

if [[ "${ANVIL_YES:-0}" != 1 ]]; then
  if [[ ! -t 0 ]]; then
    anvil_error 'Reforge needs one confirmation in an interactive terminal; set ANVIL_YES=1 to confirm automation runs.'
    exit 2
  fi
  printf '\nThis will replace the active global OpenCode harness. A verified rollback is available at:\n%s\n' "$backup_dir"
  read -r -p 'Continue with Anvil reforge? [y/N] ' answer
  [[ "$answer" == y || "$answer" == Y || "$answer" == yes || "$answer" == YES ]] || {
    anvil_log 'Reforge cancelled; no global OpenCode state was changed.'
    exit 0
  }
fi

transaction_active=1
anvil_log 'Replacing the active global OpenCode config with the staged Anvil config.'
anvil_apply_config "$ready_config"
if [[ "${ANVIL_TEST_MODE:-0}" == 1 && "${ANVIL_TEST_FAIL_AFTER_CONFIG:-0}" == 1 ]]; then
  anvil_error 'Injected fixture failure after global config replacement.'
  false
fi

bash "$ROOT/scripts/install-opencode.sh" install "$candidate" "$candidate_version"
path_result="$(python3 "$ROOT/scripts/path_edit.py" apply \
  --home "$ANVIL_HOME_DIR" --xdg-config-home "$ANVIL_CONFIG_HOME" \
  --install-dir "$ANVIL_INSTALL_BIN" --shell "${SHELL:-bash}" --path "$PATH")"
export PATH="$ANVIL_INSTALL_BIN:$PATH"
XDG_DATA_HOME="$ANVIL_DATA_HOME" python3 "$ANVIL_CONFIG_DIR/scripts/memory.py" init >/dev/null

python3 "$ROOT/scripts/installation.py" \
  --destination "$ANVIL_DATA_DIR/installation.json" \
  --opencode-version "$candidate_version" --anvil-version "$ANVIL_VERSION" \
  --binary "$ANVIL_INSTALLED_BINARY" --release-json "$release_json" \
  --migration-status reforge --previous-anvil-version "$previous_anvil_version" \
  --previous-opencode-version "$previous_opencode_version" --from-generation "$from_generation" \
  --backup "$backup_dir"

doctor_status=0
bash "$ROOT/scripts/doctor.sh" || doctor_status=$?
if (( doctor_status == 1 )); then
  anvil_error 'Postflight doctor reported a broken installation.'
  false
elif (( doctor_status > 2 )); then
  anvil_error "Postflight doctor failed with unexpected status $doctor_status."
  false
elif (( doctor_status == 2 )); then
  anvil_warn 'Reforge completed with project or environment override warnings.'
fi

transaction_active=0
anvil_ok "Anvil $ANVIL_VERSION installed with OpenCode $candidate_version."
anvil_ok "Verified backup: $backup_dir"
if [[ "$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("added",False))' "$path_result")" == True ]]; then
  anvil_log "Added $ANVIL_INSTALL_BIN to the selected shell startup file; open a new shell to refresh PATH."
elif [[ "$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("manual_required",False))' "$path_result")" == True ]]; then
  anvil_warn "Could not safely edit $(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("file", "the shell startup file"))' "$path_result"). Add $ANVIL_INSTALL_BIN to PATH manually."
fi
