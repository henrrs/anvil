#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/scripts/lib/common.sh"
source "$ROOT/scripts/lib/install.sh"

backup=""
internal=0
rollback_stage=""
rollback_plan_dir=""
cleanup_rollback_stage() {
  [[ -z "$rollback_stage" || ! -d "$rollback_stage" ]] || rm -rf -- "$rollback_stage"
  [[ -z "$rollback_plan_dir" || ! -d "$rollback_plan_dir" ]] || rm -rf -- "$rollback_plan_dir"
}
trap cleanup_rollback_stage EXIT
while [[ $# -gt 0 ]]; do
  case "$1" in
    --backup)
      [[ ${2:-} ]] || { anvil_error '--backup requires a directory'; exit 2; }
      backup="$2"; shift 2 ;;
    --internal)
      internal=1; shift ;;
    *) anvil_error "Unknown rollback option: $1"; exit 2 ;;
  esac
done
if (( internal )) && [[ "${ANVIL_INTERNAL_MODE:-0}" != 1 ]]; then
  anvil_error 'Internal rollback options are reserved for Anvil lifecycle scripts and isolated tests.'
  exit 2
fi
if (( ! internal )); then
  anvil_recover_pending
  if [[ "${ANVIL_RECOVERED_PENDING:-0}" == 1 ]]; then exit 0; fi
fi

if [[ -z "$backup" ]]; then
  backup="$(anvil_lifecycle_state latest-backup)"
fi
if (( ! internal )); then
  rollback_plan_dir="$(mktemp -d "${TMPDIR:-/tmp}/anvil-rollback-plan.XXXXXX")"
  chmod 700 -- "$rollback_plan_dir"
  rollback_plan="$rollback_plan_dir/change-plan.json"
  python3 "$ROOT/scripts/lifecycle_plan.py" rollback --format text --json-output "$rollback_plan"
  python3 "$ROOT/scripts/lifecycle_executor.py" --operation rollback --plan-file "$rollback_plan" >/dev/null
fi
backup_real="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$backup")"
backup_root_real="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$ANVIL_BACKUP_ROOT")"
python3 - "$backup_real" "$backup_root_real" <<'PY'
import os, sys
backup, root = sys.argv[1:]
if os.path.commonpath([backup, root]) != root or backup == root:
    raise SystemExit("ERROR backup must be a child of the current Anvil backup root")
PY
manifest="$backup_real/manifest.json"
python3 "$ROOT/scripts/state.py" verify "$backup_real"

read_manifest() {
  python3 - "$manifest" "$1" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
value = data
for key in sys.argv[2].split("."):
    if not isinstance(value, dict) or key not in value:
        value = None
        break
    value = value[key]
print("" if value is None else ("yes" if value is True else "no" if value is False else value))
PY
}

saved_config_dir="$(read_manifest previous.config_dir)"
saved_install_dir="$(read_manifest previous.installer_dir)"
saved_executable_path="$(read_manifest previous.executable_path)"
backup_scope="$(read_manifest scope)"
[[ -n "$backup_scope" ]] || backup_scope=runtime
[[ "$backup_scope" == anvil || "$backup_scope" == runtime ]] || { anvil_error "Unknown rollback snapshot scope: $backup_scope"; exit 1; }
saved_data_dir="$(read_manifest previous.data_dir)"
saved_state_dir="$(read_manifest previous.state_dir)"
[[ "$saved_config_dir" == "$ANVIL_CONFIG_DIR" ]] || { anvil_error 'Backup belongs to a different OpenCode config path.'; exit 1; }
[[ "$saved_install_dir" == "$ANVIL_INSTALL_ROOT" ]] || { anvil_error 'Backup belongs to a different home directory.'; exit 1; }
if [[ -n "$saved_data_dir" && "$saved_data_dir" != "$ANVIL_DATA_HOME/opencode" ]]; then
  anvil_error 'Backup belongs to a different OpenCode data path.'; exit 1
fi
if [[ -n "$saved_state_dir" && "$saved_state_dir" != "$ANVIL_STATE_DIR" ]]; then
  anvil_error 'Backup belongs to a different OpenCode state path.'; exit 1
fi
if ! anvil_safe_managed_path "$ANVIL_CONFIG_DIR" "$ANVIL_CONFIG_DIR"; then
  anvil_error 'Current config path did not pass the managed-path check.'; exit 1
fi
if [[ -L "$ANVIL_CONFIG_DIR" || -L "$ANVIL_INSTALL_ROOT" || -L "$ANVIL_INSTALL_BIN" ]]; then
  anvil_error 'Managed config/install paths must not be symlinks during rollback.'; exit 1
fi
if [[ "$ANVIL_INSTALL_ROOT" != "$ANVIL_HOME_DIR/.opencode" || "$ANVIL_INSTALL_ROOT" == / || "$ANVIL_INSTALL_ROOT" == "$ANVIL_HOME_DIR" || "$(dirname -- "$ANVIL_INSTALL_ROOT")" == / ]]; then
  anvil_error 'Current installer path did not pass the managed-path check.'; exit 1
fi
prior_anvil_version="$(read_manifest previous.anvil_version)"
current_anvil_version="$(python3 - "$ANVIL_DATA_DIR/installation.json" <<'PY'
import json,sys
try: value=json.load(open(sys.argv[1],encoding="utf-8"))
except (OSError,ValueError): value={}
if not isinstance(value,dict): value={}
print(value.get("anvil_version") or "")
PY
)"
lifecycle_operation_id="${ANVIL_LIFECYCLE_OPERATION_ID:-}"
if [[ -z "$lifecycle_operation_id" ]]; then
  lifecycle_operation_id="$(python3 "$ROOT/scripts/lifecycle_transaction.py" inspect 2>/dev/null \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("operation_id") or "")' 2>/dev/null || true)"
fi
if (( ! internal )); then
  if ! python3 "$ROOT/scripts/active-opencode.py"; then
    anvil_error 'Close OpenCode before rollback so its data and state can be restored consistently.'
    exit 1
  fi
  python3 "$ROOT/scripts/lifecycle_transaction.py" begin --operation rollback \
    --backup "$backup_real" --source-version "$current_anvil_version" --target-version "$prior_anvil_version" --owner-pid "$$"
  python3 "$ROOT/scripts/lifecycle_transaction.py" phase restoring-snapshot
fi

config_present="$(read_manifest previous.config_present)"
installer_present="$(read_manifest previous.installer_present)"
data_present="$(read_manifest previous.data_present)"
state_present="$(read_manifest previous.state_present)"
old_version="$(read_manifest previous.executable_version)"
path_added="$(read_manifest previous.path_update.added)"
path_file="$(read_manifest previous.path_update.file)"
path_line="$(read_manifest previous.path_update.line)"
path_file_preexisted="$(read_manifest previous.path_update.file_preexisted)"
printf '%s\n' 'Anvil Rollback' '──────────────'
printf 'Backup                %s\n' "$backup_real"
printf 'Rollback scope        %s\n' "$backup_scope"
printf 'Prior OpenCode        %s\n' "${old_version:-not found}"
printf 'Restore global config %s\n' "$config_present"
printf '%s\n' '  Anvil-owned files are restored; current shared settings and user files are merged where paths do not conflict.'
printf '%s\n' '  Configuration outside the OpenCode config directory is left untouched.'
if [[ "$backup_scope" == runtime ]]; then
  printf 'Restore installer dir %s\n' "$installer_present"
  printf 'Restore OpenCode data %s\n' "${data_present:-not captured by this backup}"
  printf 'Restore OpenCode state %s\n' "${state_present:-not captured by this backup}"
else
  printf 'OpenCode runtime      PRESERVE EXACTLY\n'
  printf 'OpenCode data/state   PRESERVE EXACTLY\n'
fi

memory_backup=""
if [[ -d "$ANVIL_MEMORY_DIR" ]]; then
  umask 077
  mkdir -p -- "$ANVIL_DATA_DIR/memory-backups"
  chmod 700 -- "$ANVIL_DATA_DIR/memory-backups"
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  memory_backup="$ANVIL_DATA_DIR/memory-backups/memory-before-rollback-$stamp.tar.gz"
  suffix=0
  while [[ -e "$memory_backup" ]]; do
    suffix=$((suffix + 1))
    memory_backup="$ANVIL_DATA_DIR/memory-backups/memory-before-rollback-$stamp-$suffix.tar.gz"
  done
  python3 "$ROOT/scripts/archive.py" create "$ANVIL_MEMORY_DIR" "$memory_backup" memory
  printf '%s  %s\n' "$(anvil_sha256 "$memory_backup")" "$(basename -- "$memory_backup")" > "$memory_backup.sha256"
  chmod 600 -- "$memory_backup.sha256"
fi

config_archive="$backup_real/config.tar.gz"
if (( ! internal )); then python3 "$ROOT/scripts/lifecycle_transaction.py" phase restoring-config; fi
baseline_file="$backup_real/lifecycle-baseline/pre-operation-state.json"
if [[ -f "$baseline_file" ]]; then
  baseline_binary="$(python3 - "$baseline_file" <<'PY'
import json,sys
try: value=json.load(open(sys.argv[1],encoding="utf-8"))
except (OSError,ValueError): value={}
runtime=value.get("opencode_runtime") if isinstance(value,dict) else {}
print(runtime.get("executable") or "" if isinstance(runtime,dict) else "")
PY
)"
  python3 "$ROOT/scripts/analytics_service.py" stop --config-dir "$ANVIL_CONFIG_DIR" \
    --home "$ANVIL_HOME_DIR" --systemd-dir "${XDG_CONFIG_HOME:-$ANVIL_HOME_DIR/.config}/systemd/user" \
    --port "${ANVIL_ANALYTICS_PORT:-8765}" >/dev/null 2>&1 || true
  marker="$ANVIL_DATA_HOME/anvil/analytics/operations/$lifecycle_operation_id.json"
  if [[ -n "$lifecycle_operation_id" && -f "$marker" && ! -L "$marker" ]]; then
    python3 "$ROOT/scripts/analytics_dependencies.py" restore \
      --data-root "$ANVIL_DATA_HOME" --operation-id "$lifecycle_operation_id" >/dev/null
  fi
fi
umask 077
rollback_stage="$(mktemp -d "$(dirname -- "$ANVIL_CONFIG_DIR")/.anvil-config-rollback-stage.XXXXXX")"
rollback_config="$rollback_stage/$(basename -- "$ANVIL_CONFIG_DIR")"
python3 "$ROOT/scripts/archive.py" restore "$config_archive" "$rollback_config" "$config_present"
if [[ "$config_present" != yes ]]; then mkdir -m 700 -- "$rollback_config"; fi
python3 "$ROOT/scripts/managed_config.py" restore-merge --source "$ANVIL_CONFIG_DIR" --target "$rollback_config" >/dev/null
ANVIL_ROLLBACK_RESTORE=1 ANVIL_ANALYTICS_RUNTIME_STAGED=0 \
  anvil_apply_config "$rollback_config" yes yes
if [[ "$backup_scope" == runtime ]]; then
  installer_archive="$backup_real/opencode-root.tar.gz"
  python3 "$ROOT/scripts/archive.py" restore "$installer_archive" "$ANVIL_INSTALL_ROOT" "$installer_present"
  if [[ -n "$saved_data_dir" && "$data_present" != "" ]]; then
    python3 "$ROOT/scripts/archive.py" restore "$backup_real/opencode-data.tar.gz" "$saved_data_dir" "$data_present"
  fi
  if [[ -n "$saved_state_dir" && "$state_present" != "" ]]; then
    python3 "$ROOT/scripts/archive.py" restore "$backup_real/opencode-state.tar.gz" "$saved_state_dir" "$state_present"
  fi
fi

if [[ "$backup_scope" == runtime && "$path_added" == yes && -n "$path_file" && -n "$path_line" ]]; then
  safe_path="$(python3 - "$ANVIL_HOME_DIR" "$path_file" <<'PY'
import os, sys
home, path = map(os.path.abspath, sys.argv[1:])
print("yes" if path != home and os.path.commonpath((home, path)) == home else "no")
PY
)"
  if [[ "$safe_path" == yes ]]; then
    case "$path_line" in
      *"$ANVIL_INSTALL_BIN"*)
        python3 "$ROOT/scripts/path_edit.py" remove --file "$path_file" --line "$path_line" \
          --file-preexisted "$path_file_preexisted" ;;
      *) anvil_warn 'Skipped PATH cleanup because the manifest entry did not name Anvil’s installer directory.' ;;
    esac
  else
    anvil_warn 'Skipped PATH cleanup because the saved startup file is outside this home directory.'
  fi
fi

if [[ -f "$backup_real/previous-installation.json" ]]; then
  mkdir -p -- "$ANVIL_DATA_DIR"
  install -m 0600 -- "$backup_real/previous-installation.json" "$ANVIL_DATA_DIR/installation.json.tmp"
  mv -f -- "$ANVIL_DATA_DIR/installation.json.tmp" "$ANVIL_DATA_DIR/installation.json"
else
  rm -f -- "$ANVIL_DATA_DIR/installation.json"
fi
if (( ! internal )); then python3 "$ROOT/scripts/lifecycle_transaction.py" phase restoring-metadata; fi

runtime_state_file="$(read_manifest previous.runtime_state_file)"
runtime_state_present="$(read_manifest previous.runtime_state_present)"
if [[ -n "$runtime_state_file" && "$runtime_state_file" == "$ANVIL_DATA_DIR/runtime.json" ]]; then
  if [[ "$runtime_state_present" == yes && -f "$backup_real/previous-runtime.json" ]]; then
    mkdir -p -- "$ANVIL_DATA_DIR"
    install -m 0600 -- "$backup_real/previous-runtime.json" "$runtime_state_file.tmp"
    mv -f -- "$runtime_state_file.tmp" "$runtime_state_file"
  else
    rm -f -- "$runtime_state_file"
  fi
fi

if [[ -f "$baseline_file" ]]; then
  baseline_args=(restore --backup "$backup_real" --config-dir "$ANVIL_CONFIG_DIR" \
    --home "$ANVIL_HOME_DIR" --installation "$ANVIL_DATA_DIR/installation.json" \
    --analytics-runtime-state "${ANVIL_HOME:-$ANVIL_HOME_DIR/.anvil}/analytics/runtime.json" \
    --systemd-dir "${XDG_CONFIG_HOME:-$ANVIL_HOME_DIR/.config}/systemd/user" \
    --port "${ANVIL_ANALYTICS_PORT:-8765}")
  [[ -z "$baseline_binary" ]] || baseline_args+=(--binary "$baseline_binary")
  [[ -z "$lifecycle_operation_id" ]] || baseline_args+=(--operation-id "$lifecycle_operation_id")
  python3 "$ROOT/scripts/lifecycle_baseline.py" "${baseline_args[@]}" >/dev/null
fi

if [[ "$backup_scope" == runtime && -n "$old_version" ]]; then
  previous_path="$(read_manifest previous.executable_path)"
  if [[ -n "$previous_path" && -x "$previous_path" ]]; then
    restored_version="$("$previous_path" --version 2>/dev/null | head -n 1 || true)"
    [[ "$restored_version" == "$old_version" ]] || {
      anvil_error "Restored executable reports '$restored_version', expected '$old_version'."
      exit 1
    }
  fi
fi
if [[ -n "$memory_backup" ]]; then
  anvil_ok "Current Anvil memory was archived before rollback: $memory_backup"
fi
if [[ "$config_present" == no && -d "$ANVIL_CONFIG_DIR" ]]; then
  remaining_entries="$(python3 - "$ANVIL_CONFIG_DIR" <<'PY'
import sys
from pathlib import Path
print("yes" if any(Path(sys.argv[1]).iterdir()) else "no")
PY
)"
  if [[ "$remaining_entries" == no ]]; then rmdir -- "$ANVIL_CONFIG_DIR"; fi
fi
if (( ! internal )); then python3 "$ROOT/scripts/lifecycle_transaction.py" phase verifying-restored-state; fi
if [[ -f "$baseline_file" ]]; then
  verification_args=(verify --backup "$backup_real" --config-dir "$ANVIL_CONFIG_DIR" \
    --home "$ANVIL_HOME_DIR" --installation "$ANVIL_DATA_DIR/installation.json" \
    --analytics-runtime-state "${ANVIL_HOME:-$ANVIL_HOME_DIR/.anvil}/analytics/runtime.json" \
    --systemd-dir "${XDG_CONFIG_HOME:-$ANVIL_HOME_DIR/.config}/systemd/user" \
    --port "${ANVIL_ANALYTICS_PORT:-8765}")
  [[ -z "$baseline_binary" ]] || verification_args+=(--binary "$baseline_binary")
  verification="$(python3 "$ROOT/scripts/lifecycle_baseline.py" "${verification_args[@]}")" || {
    anvil_error "Baseline restoration verification failed. Primary lifecycle failure remains in effect. Verified snapshot: $backup_real"
    exit 1
  }
  verification_status="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("status", "RESTORATION_FAILED"))' "$verification")"
  printf 'Baseline restoration status  %s\n' "$verification_status"
  if [[ "$verification_status" == RESTORED_DEGRADED_BASELINE ]]; then
    anvil_ok 'Automatic restoration matched the pre-operation degraded baseline.'
  elif [[ "$verification_status" == RESTORED ]]; then
    anvil_ok 'Automatic restoration matched the pre-operation baseline.'
  else
    anvil_error 'Baseline restoration could not be verified against the captured state.'
    exit 1
  fi
elif [[ "$config_present" == yes && -f "$ANVIL_DATA_DIR/installation.json" ]]; then
  restored_product_version="$(python3 - "$ANVIL_DATA_DIR/installation.json" <<'PY'
import json,sys
try: value=json.load(open(sys.argv[1],encoding="utf-8"))
except (OSError,ValueError,json.JSONDecodeError): value={}
print(value.get("anvil_version", "") if isinstance(value,dict) else "")
PY
)"
  [[ -n "$restored_product_version" && "$restored_product_version" == "$prior_anvil_version" ]] || {
    anvil_error 'Rollback verification failed: restored installation metadata does not match the selected snapshot.'
    exit 1
  }
  runtime_args=(discover --format json)
  if [[ -n "$saved_executable_path" && -x "$saved_executable_path" ]]; then
    runtime_args+=(--binary "$saved_executable_path")
  fi
  restored_runtime="$(python3 "$ROOT/scripts/runtime_state.py" "${runtime_args[@]}")"
  IFS=$'\t' read -r restored_binary restored_version restored_major restored_supported < <(python3 - "$restored_runtime" <<'PY'
import json,sys
runtime=(json.loads(sys.argv[1]).get("runtime") or {})
print("\t".join(str(runtime.get(key) or "") for key in ("executable","version","generation","supported")))
PY
)
  [[ "$restored_supported" == True && -n "$restored_binary" && -n "$restored_version" && "$restored_major" =~ ^[12]$ ]] || {
    anvil_error 'Rollback verification failed: the restored OpenCode runtime is not usable under the current policy.'
    exit 1
  }
  if ! verification_output="$(python3 "$ROOT/scripts/lifecycle_verify.py" \
      --config "$ANVIL_CONFIG_DIR" --memory "$ANVIL_DATA_DIR/memory" --binary "$restored_binary" \
      --product-version "$restored_product_version" --runtime-version "$restored_version" \
      --runtime-major "$restored_major" --allow-repairable-drift 2>&1)"; then
    printf '%s\n' "$verification_output" >&2
    if (( ! internal )); then
      operation_id="$(python3 "$ROOT/scripts/lifecycle_transaction.py" inspect | python3 -c 'import json,sys; print(json.load(sys.stdin).get("operation_id") or "unknown")')"
      anvil_error "Rollback verification failed during postflight. Operation $operation_id and the verified snapshot are preserved at $backup_real. Review make inspect before retrying."
    else
      anvil_error "Automatic rollback verification failed; the parent operation journal and verified snapshot remain at $backup_real."
    fi
    exit 1
  fi
  printf '%s\n' "$verification_output"
elif [[ "$config_present" == no && ! -e "$ANVIL_DATA_DIR/installation.json" ]]; then
  anvil_ok 'Rollback verification passed: the selected pre-install state has no Anvil installation record.'
else
  anvil_warn 'Snapshot restored, but it has no Anvil release record for the current structured verifier; the verified archive remains available for manual review.'
fi
if (( ! internal )); then
  python3 "$ROOT/scripts/lifecycle_transaction.py" phase postflight-validated
  python3 "$ROOT/scripts/lifecycle_transaction.py" clear
fi
anvil_ok 'Rollback completed. Anvil memory remains at its data path and is inert without the Anvil harness.'
