#!/usr/bin/env bash

# This library assumes common.sh and paths.sh have already been sourced.

anvil_build_config() {
  local destination="$1" prior_config="${2:-}" preserve_cli="${3:-no}" major="${4:-2}"
  [[ -n "$destination" && "$destination" != / ]] || { anvil_error 'Invalid generated config destination.'; return 1; }
  [[ "$major" == 1 || "$major" == 2 ]] || { anvil_error "Unsupported OpenCode runtime major: $major"; return 1; }
  mkdir -p -- "$destination"
  cp -R -- "$ANVIL_ROOT/config/AGENTS.md" "$destination/AGENTS.md"
  cp -R -- "$ANVIL_ROOT/config/commands" "$destination/commands"
  cp -R -- "$ANVIL_ROOT/config/skills" "$destination/skills"
  if [[ "$major" == 2 ]]; then
    cp -R -- "$ANVIL_ROOT/config/plugins" "$destination/plugins"
  fi
  local build_args=(build --source "$ANVIL_ROOT/config" --destination "$destination" --major "$major")
  if [[ -n "$prior_config" ]]; then
    build_args+=(--prior-config-dir "$prior_config")
  fi
  if [[ "$preserve_cli" == yes ]]; then build_args+=(--preserve-cli); fi
  python3 "$ANVIL_ROOT/scripts/configure.py" "${build_args[@]}"
  mkdir -p -- "$destination/scripts"
  install -m 0600 -- "$ANVIL_ROOT/scripts/memory.py" "$destination/scripts/memory.py"
  install -m 0600 -- "$ANVIL_ROOT/scripts/source_registry.py" "$destination/scripts/source_registry.py"
  install -m 0600 -- "$ANVIL_ROOT/scripts/runtime.py" "$destination/scripts/runtime.py"
  install -m 0600 -- "$ANVIL_ROOT/scripts/runtime_state.py" "$destination/scripts/runtime_state.py"
  install -m 0600 -- "$ANVIL_ROOT/scripts/databricks.py" "$destination/scripts/databricks.py"
  install -m 0600 -- "$ANVIL_ROOT/scripts/databricks_finops.py" "$destination/scripts/databricks_finops.py"
  install -m 0600 -- "$ANVIL_ROOT/scripts/artifacts.py" "$destination/scripts/artifacts.py"
  rm -rf -- "$destination/scripts/communication"
  cp -R -- "$ANVIL_ROOT/scripts/communication" "$destination/scripts/communication"
  find "$destination/scripts/communication" -type d -name __pycache__ -prune -exec rm -rf -- {} +
  find "$destination/scripts/communication" -type f -name '*.pyc' -delete
  find "$destination/scripts/communication" -type f -exec chmod 600 -- {} +
  rm -rf -- "$destination/scripts/databricks_providers"
  cp -R -- "$ANVIL_ROOT/scripts/databricks_providers" "$destination/scripts/databricks_providers"
  find "$destination/scripts/databricks_providers" -type f -exec chmod 600 -- {} +
}

anvil_apply_config() {
  local source_config="$1"
  [[ -d "$source_config" ]] || { anvil_error "Generated Anvil config is missing: $source_config"; return 1; }
  anvil_remove_managed_tree "$ANVIL_CONFIG_DIR" "$ANVIL_CONFIG_DIR"
  mkdir -p -- "$(dirname -- "$ANVIL_CONFIG_DIR")"
  cp -R -- "$source_config" "$ANVIL_CONFIG_DIR"
  [[ -f "$ANVIL_CONFIG_DIR/opencode.jsonc" ]] || { anvil_error 'Anvil global config copy failed.'; return 1; }
  chmod 600 -- "$ANVIL_CONFIG_DIR/opencode.jsonc"
  chmod 700 -- "$ANVIL_CONFIG_DIR/scripts/memory.py" "$ANVIL_CONFIG_DIR/scripts/source_registry.py" "$ANVIL_CONFIG_DIR/scripts/runtime.py" \
    "$ANVIL_CONFIG_DIR/scripts/runtime_state.py" \
    "$ANVIL_CONFIG_DIR/scripts/databricks.py" "$ANVIL_CONFIG_DIR/scripts/databricks_finops.py" \
    "$ANVIL_CONFIG_DIR/scripts/artifacts.py"
  find "$ANVIL_CONFIG_DIR/scripts/communication" -type f -exec chmod 600 -- {} +
  find "$ANVIL_CONFIG_DIR/scripts/databricks_providers" -type f -exec chmod 600 -- {} +
}

anvil_offer_databricks_setup() {
  [[ "${ANVIL_TEST_MODE:-0}" != 1 ]] || return 0
  anvil_log "Databricks remains optional. Run 'make databricks-setup' when you want Anvil to attempt CLI installation and configure providers."
}
