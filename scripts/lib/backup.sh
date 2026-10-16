#!/usr/bin/env bash

# This library assumes common.sh and paths.sh have already been sourced.

anvil_backup_create() {
  local candidate_version="$1" path_plan_json="$2"
  local backup_dir stamp suffix executable executable_resolved executable_version
  local config_present=no installer_present=no path_file path_line path_added=no path_file_preexisted=no
  local data_dir="$ANVIL_DATA_HOME/opencode" state_dir="$ANVIL_STATE_DIR" data_present=no state_present=no previous_anvil_version=""

  if [[ "${ANVIL_TEST_MODE:-0}" == 1 && "${ANVIL_TEST_FAIL_BACKUP:-0}" == 1 ]]; then
    anvil_error 'Injected backup creation failure before archive creation.'
    return 1
  fi

  umask 077
  mkdir -p -- "$ANVIL_BACKUP_ROOT"
  chmod 700 -- "$ANVIL_DATA_DIR" "$ANVIL_BACKUP_ROOT" 2>/dev/null || true
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  backup_dir="$ANVIL_BACKUP_ROOT/$stamp"
  suffix=0
  while [[ -e "$backup_dir" ]]; do
    suffix=$((suffix + 1))
    backup_dir="$ANVIL_BACKUP_ROOT/$stamp-$suffix"
  done
  mkdir -m 700 -- "$backup_dir"

  if [[ -e "$ANVIL_CONFIG_DIR" || -L "$ANVIL_CONFIG_DIR" ]]; then
    config_present=yes
    python3 "$ANVIL_ROOT/scripts/archive.py" create "$ANVIL_CONFIG_DIR" "$backup_dir/config.tar.gz" "$(basename -- "$ANVIL_CONFIG_DIR")"
  fi
  if [[ -e "$ANVIL_INSTALL_ROOT" || -L "$ANVIL_INSTALL_ROOT" ]]; then
    installer_present=yes
    python3 "$ANVIL_ROOT/scripts/archive.py" create "$ANVIL_INSTALL_ROOT" "$backup_dir/opencode-root.tar.gz" "$(basename -- "$ANVIL_INSTALL_ROOT")"
  fi
  if [[ -e "$data_dir" || -L "$data_dir" ]]; then
    data_present=yes
    python3 "$ANVIL_ROOT/scripts/archive.py" create "$data_dir" "$backup_dir/opencode-data.tar.gz" "$(basename -- "$data_dir")"
  fi
  if [[ -e "$state_dir" || -L "$state_dir" ]]; then
    state_present=yes
    python3 "$ANVIL_ROOT/scripts/archive.py" create "$state_dir" "$backup_dir/opencode-state.tar.gz" "$(basename -- "$state_dir")"
  fi

  executable="$(type -P opencode 2>/dev/null || true)"
  if [[ -z "$executable" && -x "$ANVIL_INSTALLED_BINARY" ]]; then
    executable="$ANVIL_INSTALLED_BINARY"
  fi
  executable_resolved=""
  executable_version=""
  if [[ -n "$executable" && -f "$executable" ]]; then
    executable_resolved="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$executable")"
    if [[ -r "$executable_resolved" ]]; then
      cp -- "$executable_resolved" "$backup_dir/previous-opencode-binary"
      chmod 700 -- "$backup_dir/previous-opencode-binary"
      executable_version="$("$executable" --version 2>/dev/null | head -n 1 || true)"
    fi
  fi

  if [[ -f "$ANVIL_DATA_DIR/installation.json" ]]; then
    cp -- "$ANVIL_DATA_DIR/installation.json" "$backup_dir/previous-installation.json"
    chmod 600 -- "$backup_dir/previous-installation.json"
    previous_anvil_version="$(python3 - "$backup_dir/previous-installation.json" <<'PY'
import json,sys
try:
    value=json.load(open(sys.argv[1],encoding="utf-8"))
    print(value.get("anvil_version") or value.get("previous_anvil_version") or "")
except (OSError,ValueError):
    print("")
PY
)"
  fi
  if [[ -n "${ANVIL_PREVIOUS_ANVIL_VERSION:-}" ]]; then
    previous_anvil_version="$ANVIL_PREVIOUS_ANVIL_VERSION"
  fi

  bash "$ANVIL_ROOT/scripts/inspect.sh" > "$backup_dir/inspect.txt"
  chmod 600 -- "$backup_dir/inspect.txt"

  path_file="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("file", ""))' "$path_plan_json")"
  path_line="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("line", ""))' "$path_plan_json")"
  if [[ "$(python3 -c 'import json,sys; print("yes" if json.loads(sys.argv[1]).get("added") else "no")' "$path_plan_json")" == yes ]]; then path_added=yes; fi
  if [[ "$(python3 -c 'import json,sys; print("yes" if json.loads(sys.argv[1]).get("file_preexisted") else "no")' "$path_plan_json")" == yes ]]; then path_file_preexisted=yes; fi

  python3 "$ANVIL_ROOT/scripts/state.py" create "$backup_dir" \
    --config-dir "$ANVIL_CONFIG_DIR" --config-present "$config_present" \
    --installer-dir "$ANVIL_INSTALL_ROOT" --installer-present "$installer_present" \
    --data-dir "$data_dir" --data-present "$data_present" \
    --state-dir "$state_dir" --state-present "$state_present" \
    --previous-anvil-version "$previous_anvil_version" \
    --candidate-version "$candidate_version" \
    --executable-path "$executable" --executable-resolved "$executable_resolved" \
    --executable-version "$executable_version" \
    --path-file "$path_file" --path-line "$path_line" --path-added "$path_added" \
    --path-file-preexisted "$path_file_preexisted"
  python3 "$ANVIL_ROOT/scripts/state.py" verify "$backup_dir" >/dev/null
  chmod 700 -- "$backup_dir"
  anvil_ok "Backup created and verified: $backup_dir"
  printf '%s\n' "$backup_dir"
}
