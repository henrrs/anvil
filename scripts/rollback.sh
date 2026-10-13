#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/scripts/lib/common.sh"

backup=""
internal=0
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

if [[ -z "$backup" ]]; then
  backup="$(python3 "$ROOT/scripts/state.py" latest "$ANVIL_BACKUP_ROOT")"
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
if [[ "$ANVIL_INSTALL_ROOT" != "$ANVIL_HOME_DIR/.opencode" || "$ANVIL_INSTALL_ROOT" == / || "$ANVIL_INSTALL_ROOT" == "$ANVIL_HOME_DIR" || "$(dirname -- "$ANVIL_INSTALL_ROOT")" == / ]]; then
  anvil_error 'Current installer path did not pass the managed-path check.'; exit 1
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
printf 'Prior OpenCode        %s\n' "${old_version:-not found}"
printf 'Restore global config %s\n' "$config_present"
printf 'Restore installer dir %s\n' "$installer_present"
printf 'Restore OpenCode data %s\n' "${data_present:-not captured by this backup}"
printf 'Restore OpenCode state %s\n' "${state_present:-not captured by this backup}"

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
installer_archive="$backup_real/opencode-root.tar.gz"
python3 "$ROOT/scripts/archive.py" restore "$config_archive" "$ANVIL_CONFIG_DIR" "$config_present"
python3 "$ROOT/scripts/archive.py" restore "$installer_archive" "$ANVIL_INSTALL_ROOT" "$installer_present"
if [[ -n "$saved_data_dir" && "$data_present" != "" ]]; then
  python3 "$ROOT/scripts/archive.py" restore "$backup_real/opencode-data.tar.gz" "$saved_data_dir" "$data_present"
fi
if [[ -n "$saved_state_dir" && "$state_present" != "" ]]; then
  python3 "$ROOT/scripts/archive.py" restore "$backup_real/opencode-state.tar.gz" "$saved_state_dir" "$state_present"
fi

if [[ "$path_added" == yes && -n "$path_file" && -n "$path_line" ]]; then
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

if [[ -n "$old_version" ]]; then
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
anvil_ok 'Rollback completed. Anvil memory remains at its data path and is inert without the Anvil harness.'
