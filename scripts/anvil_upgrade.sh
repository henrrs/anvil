#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/scripts/lib/common.sh"
source "$ROOT/scripts/lib/install.sh"
source "$ROOT/scripts/lib/backup.sh"
anvil_need python3 tar cp mv install chmod date

[[ $# == 0 ]] || { anvil_error 'make upgrade accepts DRY_RUN=1 only; use make update-runtime or make migrate-runtime for OpenCode changes.'; exit 2; }
ANVIL_VERSION="$(cat "$ROOT/VERSION")"

if [[ ! -f "$ANVIL_CONFIG_DIR/opencode.jsonc" ]]; then
  anvil_error 'No installed Anvil configuration found; use make reforge for a first installation.'
  exit 1
fi
if [[ -L "$ANVIL_CONFIG_DIR" || -L "$ANVIL_INSTALL_ROOT" || -L "$ANVIL_INSTALL_BIN" ]] || \
   ! anvil_safe_managed_path "$ANVIL_CONFIG_DIR" "$ANVIL_CONFIG_DIR" || \
   [[ "$ANVIL_INSTALL_ROOT" != "$ANVIL_HOME_DIR/.opencode" || "$ANVIL_INSTALL_ROOT" == / || "$ANVIL_INSTALL_ROOT" == "$ANVIL_HOME_DIR" ]]; then
  anvil_error 'Managed config/install paths did not pass the safety check.'
  exit 1
fi

runtime_json="$(anvil_runtime_json)"
read -r binary runtime_version major adapter supported < <(python3 - "$runtime_json" <<'PY'
import json,sys
r=json.loads(sys.argv[1]).get("runtime") or {}
print("\t".join(str(r.get(k) or "") for k in ("executable","version","generation","adapter","supported")))
PY
)
if [[ -z "$binary" || ! -x "$binary" ]]; then
  anvil_error 'A usable OpenCode runtime was not found. Install one with make reforge before upgrading Anvil.'
  exit 1
fi
if [[ "$supported" != True ]]; then
  anvil_error "OpenCode ${runtime_version:-unknown} is outside the supported runtime policy. Use make update-runtime for a supported version in the same major, or make migrate-runtime OPENCODE_MAJOR=N for a major change."
  exit 1
fi

if python3 "$ROOT/scripts/configure.py" audit-v1 "$ANVIL_CONFIG_DIR/opencode.jsonc" >/dev/null 2>&1; then
  from_generation=1
  python3 "$ROOT/scripts/configure.py" audit-v1 "$ANVIL_CONFIG_DIR/opencode.jsonc" >/dev/null
elif python3 "$ROOT/scripts/configure.py" audit "$ANVIL_CONFIG_DIR/opencode.jsonc" >/dev/null 2>&1; then
  from_generation=2
  python3 "$ROOT/scripts/configure.py" audit "$ANVIL_CONFIG_DIR/opencode.jsonc" >/dev/null
else
  anvil_error 'Current global config is not a supported Anvil OpenCode profile; use make reforge to rebuild it.'
  exit 1
fi
old_anvil_version="$(python3 - "$ANVIL_DATA_DIR/installation.json" <<'PY'
import json,sys
try: value=json.load(open(sys.argv[1],encoding="utf-8"))
except (OSError,ValueError): value={}
print(value.get("anvil_version") or "not recorded")
PY
)"
ready_config="$(mktemp -d "${TMPDIR:-/tmp}/anvil-config.XXXXXX")"
chmod 700 -- "$ready_config"
tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/anvil-anvil-upgrade.XXXXXX")"
chmod 700 -- "$tmp_root"
backup_dir=""
transaction_active=0
runtime_stopped=0

cleanup() {
  for target in "$ready_config" "$tmp_root"; do
    python3 - "$target" "${TMPDIR:-/tmp}" <<'PY'
import os,shutil,sys
path,base=map(os.path.abspath,sys.argv[1:])
if path != base and os.path.commonpath((path,base)) == base and os.path.basename(path).startswith(("anvil-config.","anvil-anvil-upgrade.")):
    shutil.rmtree(path,ignore_errors=True)
PY
  done
}
on_error() {
  local status=$?
  trap - ERR INT TERM
  if (( transaction_active )) && [[ -n "$backup_dir" ]]; then
    anvil_error "Anvil upgrade failed after config replacement (exit $status); restoring the Anvil-only snapshot."
    if ANVIL_INTERNAL_MODE=1 bash "$ROOT/scripts/rollback.sh" --backup "$backup_dir" --internal; then
      anvil_ok 'Automatic Anvil rollback completed; the OpenCode runtime and data were preserved.'
    else
      anvil_error "Automatic rollback failed. Verified snapshot remains at $backup_dir"
    fi
  fi
  if (( runtime_stopped )); then
    anvil_warn 'OpenCode remains stopped after the failed Anvil upgrade. Start it normally when ready.'
  fi
  cleanup
  exit "$status"
}
trap on_error ERR INT TERM
trap cleanup EXIT

anvil_build_config "$ready_config/generated" "$ANVIL_CONFIG_DIR" yes "$major"
if [[ "$major" == 1 ]]; then
  python3 "$ROOT/scripts/configure.py" audit-v1 "$ready_config/generated/opencode.jsonc" >/dev/null
else
  python3 "$ROOT/scripts/configure.py" audit "$ready_config/generated/opencode.jsonc" >/dev/null
fi
bash "$ROOT/scripts/rehearse-upgrade.sh" "$binary" "$runtime_version" "$major" "$major"

# Check backup prerequisites before interrupting the user's runtime. This is
# read-only: backup creation itself remains after quiescence and final approval.
if ! python3 "$ROOT/scripts/backup_preflight.py"; then
  anvil_error 'Upgrade preflight failed; OpenCode is still running and no live files were changed.'
  exit 1
fi
process_json="$(python3 "$ROOT/scripts/runtime_processes.py" --binary "$binary" --format json)"
read -r process_count process_uncertain self_ancestor < <(python3 - "$process_json" <<'PY'
import json,sys
value=json.loads(sys.argv[1])
print(value["count"], str(value["uncertain"]), str(value["self_ancestor"]))
PY
)
if [[ "$process_uncertain" == True && "${DRY_RUN:-0}" != 1 ]]; then
  anvil_error 'OpenCode process identity could not be fully verified; refusing to create a potentially inconsistent backup.'
  exit 1
fi

printf '%s\n' 'Anvil Upgrade Plan' '────────────────────────────────'
printf 'Anvil installed       %s\n' "$old_anvil_version"
printf 'Anvil repository      %s\n' "$ANVIL_VERSION"
printf 'Anvil action          %s\n' "$( [[ "$old_anvil_version" == "$ANVIL_VERSION" ]] && printf 'REINSTALL CURRENT RELEASE' || printf 'UPGRADE')"
printf '\nOpenCode\n'
printf '  executable          %s\n' "$binary"
printf '  installed           %s\n' "$runtime_version"
printf '  generation          %s\n' "$major"
printf '  action              PRESERVE EXACT VERSION\n'
printf '  active processes    %s running\n' "$process_count"
if [[ "$process_uncertain" == True ]]; then
  printf '  identity check      incomplete; a real upgrade will stop safely before signaling\n'
fi
if [[ "$self_ancestor" == True ]]; then
  printf '  process ancestry    upgrade is running inside OpenCode; a real upgrade will abort\n'
fi
printf '\nRuntime adapter\n'
printf '  current             %s\n' "$adapter"
printf '  target              %s\n' "$adapter"
printf '\nNetwork required      NO\n'
printf 'Databricks state      PRESERVE\n'
printf 'Rehearsal             passed using the exact local runtime and copied user state\n'
printf '\nUpgrade behavior\n'
printf '  countdown           %ss\n' "${ANVIL_UPGRADE_COUNTDOWN_SECONDS:-5}"
printf '  graceful shutdown   enabled (SIGTERM first)\n'
printf '  force termination   fallback only\n'

if [[ "${DRY_RUN:-0}" == 1 ]]; then
  printf '\nNo changes performed.\nNo processes stopped.\nNo files changed.\n'
  exit 0
fi
if [[ "$self_ancestor" == True ]]; then
  anvil_error 'This upgrade is running from inside OpenCode. Anvil cannot safely stop its own parent runtime; run the upgrade from an external terminal.'
  exit 1
fi
if [[ "${ANVIL_YES:-0}" != 1 ]]; then
  if [[ ! -t 0 ]]; then
    anvil_error 'Upgrade needs one confirmation in an interactive terminal; set ANVIL_YES=1 only after reviewing the local plan.'
    exit 2
  fi
  read -r -p 'Upgrade Anvil files while preserving OpenCode exactly? [y/N] ' answer
  [[ "$answer" == y || "$answer" == Y || "$answer" == yes || "$answer" == YES ]] || {
    anvil_log 'Upgrade cancelled; no live files were changed.'
    exit 0
  }
fi

path_plan='{"file":"","line":"","added":false,"file_preexisted":false}'
if ! python3 "$ROOT/scripts/runtime_quiesce.py" --binary "$binary" \
    --countdown "${ANVIL_UPGRADE_COUNTDOWN_SECONDS:-5}" \
    --grace-timeout "${ANVIL_OPEN_CODE_GRACE_SECONDS:-10}"; then
  exit 1
fi
if (( process_count > 0 )); then runtime_stopped=1; fi
post_quiesce="$(python3 "$ROOT/scripts/runtime_processes.py" --binary "$binary" --format json)"
read -r remaining_count remaining_uncertain < <(python3 - "$post_quiesce" <<'PY'
import json,sys
value=json.loads(sys.argv[1])
print(value["count"], str(value["uncertain"]))
PY
)
if [[ "$remaining_uncertain" == True || "$remaining_count" != 0 ]]; then
  anvil_error 'OpenCode could not be verified as fully stopped; no backup will be created.'
  exit 1
fi
backup_dir="$(ANVIL_PREVIOUS_ANVIL_VERSION="$old_anvil_version" anvil_backup_create "$runtime_version" "$path_plan" anvil | tail -n 1)"
python3 "$ROOT/scripts/state.py" verify "$backup_dir" >/dev/null
if [[ "${ANVIL_TEST_FAIL_AFTER_BACKUP:-0}" == 1 ]]; then
  anvil_error 'Injected failure after backup verification and before live mutation.'
  exit 1
fi

transaction_active=1
anvil_apply_config "$ready_config/generated"
if [[ "${ANVIL_TEST_FAIL_AFTER_CONFIG:-0}" == 1 ]]; then
  anvil_error 'Injected failure after Anvil config replacement.'
  false
fi
XDG_DATA_HOME="$ANVIL_DATA_HOME" python3 "$ANVIL_CONFIG_DIR/scripts/memory.py" init >/dev/null
python3 "$ROOT/scripts/installation.py" \
  --destination "$ANVIL_DATA_DIR/installation.json" \
  --opencode-version "$runtime_version" --anvil-version "$ANVIL_VERSION" \
  --opencode-major "$major" --binary "$binary" --anvil-only \
  --migration-status anvil-upgrade --previous-anvil-version "$old_anvil_version" --backup "$backup_dir"
python3 "$ROOT/scripts/runtime_state.py" record >/dev/null

doctor_status=0
if [[ "${ANVIL_TEST_FAIL_DOCTOR:-0}" == 1 ]]; then
  doctor_status=1
else
  ANVIL_DOCTOR_LOCAL=1 bash "$ROOT/scripts/doctor.sh" || doctor_status=$?
fi
if (( doctor_status == 1 || doctor_status > 2 )); then
  anvil_error 'Post-upgrade doctor reported a broken installation.'
  false
elif (( doctor_status == 2 )); then
  anvil_warn 'Upgrade completed with local project or source-drift warnings from doctor.'
fi

transaction_active=0
anvil_ok "Anvil $ANVIL_VERSION installed; OpenCode $runtime_version was preserved exactly."
anvil_ok "Anvil-only rollback snapshot: $backup_dir"
if (( runtime_stopped )); then
  anvil_log 'OpenCode was stopped during the upgrade. Start it normally when ready.'
fi
