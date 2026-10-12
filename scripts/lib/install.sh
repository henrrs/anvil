#!/usr/bin/env bash

# This library assumes common.sh and paths.sh have already been sourced.

anvil_build_config() {
  local destination="$1" prior_config="${2:-}"
  [[ -n "$destination" && "$destination" != / ]] || { anvil_error 'Invalid generated config destination.'; return 1; }
  mkdir -p -- "$destination"
  cp -R -- "$ANVIL_ROOT/config/." "$destination/"
  local build_args=(build --source "$ANVIL_ROOT/config/opencode.jsonc" --destination "$destination/opencode.jsonc")
  if [[ -n "$prior_config" ]]; then
    build_args+=(--prior-config-dir "$prior_config")
  fi
  python3 "$ANVIL_ROOT/scripts/configure.py" "${build_args[@]}"
  mkdir -p -- "$destination/scripts"
  install -m 0600 -- "$ANVIL_ROOT/scripts/memory.py" "$destination/scripts/memory.py"
}

anvil_apply_config() {
  local source_config="$1"
  [[ -d "$source_config" ]] || { anvil_error "Generated Anvil config is missing: $source_config"; return 1; }
  anvil_remove_managed_tree "$ANVIL_CONFIG_DIR" "$ANVIL_CONFIG_DIR"
  mkdir -p -- "$(dirname -- "$ANVIL_CONFIG_DIR")"
  cp -R -- "$source_config" "$ANVIL_CONFIG_DIR"
  [[ -f "$ANVIL_CONFIG_DIR/opencode.jsonc" ]] || { anvil_error 'Anvil global config copy failed.'; return 1; }
  chmod 600 -- "$ANVIL_CONFIG_DIR/opencode.jsonc"
  chmod 700 -- "$ANVIL_CONFIG_DIR/scripts/memory.py"
}
