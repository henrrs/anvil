#!/usr/bin/env bash

# This library assumes common.sh and paths.sh have already been sourced.

anvil_build_config() {
  local destination="$1" prior_config="${2:-}" preserve_cli="${3:-no}" major="${4:-2}" source_version="${5:-}" recover_managed="${6:-no}" source_manifest_sha256=""
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
  install -m 0600 -- "$ANVIL_ROOT/scripts/engineering.py" "$destination/scripts/engineering.py"
  install -m 0600 -- "$ANVIL_ROOT/scripts/public_errors.py" "$destination/scripts/public_errors.py"
  install -m 0700 -- "$ANVIL_ROOT/scripts/analyze.py" "$destination/scripts/analyze.py"
  rm -rf -- "$destination/scripts/engineering"
  cp -R -- "$ANVIL_ROOT/scripts/engineering" "$destination/scripts/engineering"
  find "$destination/scripts/engineering" -type d -name __pycache__ -prune -exec rm -rf -- {} +
  find "$destination/scripts/engineering" -type f -name '*.pyc' -delete
  find "$destination/scripts/engineering" -type f -exec chmod 600 -- {} +
  rm -rf -- "$destination/scripts/communication"
  cp -R -- "$ANVIL_ROOT/scripts/communication" "$destination/scripts/communication"
  find "$destination/scripts/communication" -type d -name __pycache__ -prune -exec rm -rf -- {} +
  find "$destination/scripts/communication" -type f -name '*.pyc' -delete
  find "$destination/scripts/communication" -type f -exec chmod 600 -- {} +
  rm -rf -- "$destination/scripts/databricks_providers"
  cp -R -- "$ANVIL_ROOT/scripts/databricks_providers" "$destination/scripts/databricks_providers"
  find "$destination/scripts/databricks_providers" -type d -name __pycache__ -prune -exec rm -rf -- {} +
  find "$destination/scripts/databricks_providers" -type f -name '*.pyc' -delete
  find "$destination/scripts/databricks_providers" -type f -exec chmod 600 -- {} +
  rm -rf -- "$destination/scripts/analysis"
  cp -R -- "$ANVIL_ROOT/scripts/analysis" "$destination/scripts/analysis"
  find "$destination/scripts/analysis" -type d -name __pycache__ -prune -exec rm -rf -- {} +
  find "$destination/scripts/analysis" -type f -name '*.pyc' -delete
  find "$destination/scripts/analysis" -type f -exec chmod 600 -- {} +
  if [[ -z "$source_version" && -f "$ANVIL_DATA_DIR/installation.json" ]]; then
    source_version="$(python3 - "$ANVIL_DATA_DIR/installation.json" <<'PY'
import json,sys
try: value=json.load(open(sys.argv[1],encoding="utf-8"))
except (OSError,ValueError): value={}
print(value.get("anvil_version") or "")
PY
)"
  fi
  if [[ -n "$prior_config" && -f "$ANVIL_DATA_DIR/installation.json" ]]; then
    source_manifest_sha256="$(python3 - "$ANVIL_DATA_DIR/installation.json" <<'PY'
import json,sys
try: value=json.load(open(sys.argv[1],encoding="utf-8"))
except (OSError,ValueError): value={}
print(value.get("managed_config_manifest_sha256") or "")
PY
)"
  fi
  local target_version
  target_version="$(cat "$ANVIL_ROOT/VERSION")"
  local prepare_args=(prepare --target "$destination" --target-version "$target_version")
  if [[ -n "$prior_config" && -d "$prior_config" ]]; then
    prepare_args+=(--source "$prior_config")
  fi
  if [[ -n "$source_version" ]]; then prepare_args+=(--source-version "$source_version"); fi
  if [[ -n "$source_manifest_sha256" ]]; then prepare_args+=(--source-manifest-sha256 "$source_manifest_sha256"); fi
  if [[ "$recover_managed" == yes ]]; then prepare_args+=(--recover-managed); fi
  python3 "$ANVIL_ROOT/scripts/managed_config.py" "${prepare_args[@]}"
}

anvil_print_config_plan() {
  local source_config="$1" target_config="$2" source_version="${3:-}" target_version="${4:-$(cat "$ANVIL_ROOT/VERSION")}" recover_managed="${5:-no}"
  local plan_args=(plan --source "$source_config" --target "$target_config" --target-version "$target_version")
  if [[ -n "$source_version" ]]; then plan_args+=(--source-version "$source_version"); fi
  if [[ "$recover_managed" == yes ]]; then plan_args+=(--recover-managed); fi
  (
    set -o pipefail
    python3 "$ANVIL_ROOT/scripts/managed_config.py" "${plan_args[@]}" | python3 -c '
import json
import sys

plan = json.load(sys.stdin)
changes = plan["changes"]
print("\nManaged configuration transition")
print("─────────────────────────────────")
print("  source release     " + plan["source_version"])
print("  target release     " + plan["target_version"])
for key, label in (("added", "add"), ("updated", "update"), ("removed", "remove"),
                   ("preserved_user_files", "preserved user files"), ("unchanged", "unchanged")):
    items = changes.get(key, [])
    print(f"  {label:18} {len(items)}")
    for item in items[:10]:
        print(f"    {item}")
    if len(items) > 10:
        print(f"    ... {len(items) - 10} more paths omitted from display")
print("  runtime action    " + plan["runtime_action"])
print("  shared config     merge Anvil-owned profile keys; preserve external providers, plugins, MCP, references and user preferences")
print("  local environment package, proxy, certificate, shell and credential-reference files outside OpenCode config remain untouched")
print("  snapshot          scoped Anvil files plus shared profile/preferences before mutation; config values are not displayed")
'
  )
}

anvil_apply_config() {
  local source_config="$1" allow_user_only="${2:-no}"
  [[ -d "$source_config" ]] || { anvil_error "Generated Anvil config is missing: $source_config"; return 1; }
  mkdir -p -- "$(dirname -- "$ANVIL_CONFIG_DIR")"
  local parent stage previous managed_script managed_tree
  parent="$(dirname -- "$ANVIL_CONFIG_DIR")"
  stage="$(mktemp -d "$parent/.anvil-config-stage.XXXXXX")"
  if ! cp -pR -- "$source_config"/. "$stage"/; then
    rm -rf -- "$stage"
    anvil_error 'Anvil global config staging copy failed.'
    return 1
  fi
  if [[ "$allow_user_only" != yes && ! -f "$stage/opencode.jsonc" ]]; then
    rm -rf -- "$stage"
    anvil_error 'Anvil global config staging copy is incomplete.'
    return 1
  fi
  previous="$parent/.anvil-config-previous-$$"
  [[ ! -e "$previous" && ! -L "$previous" ]] || { rm -rf -- "$stage"; anvil_error 'A prior config swap needs manual review.'; return 1; }
  if [[ -e "$ANVIL_CONFIG_DIR" || -L "$ANVIL_CONFIG_DIR" ]]; then
    mv -- "$ANVIL_CONFIG_DIR" "$previous"
  fi
  if [[ "${ANVIL_TEST_KILL_AFTER_CONFIG_RENAME:-0}" == 1 ]]; then kill -9 "$$"; fi
  if ! mv -- "$stage" "$ANVIL_CONFIG_DIR"; then
    if [[ -e "$previous" && ! -e "$ANVIL_CONFIG_DIR" ]]; then mv -- "$previous" "$ANVIL_CONFIG_DIR"; fi
    rm -rf -- "$stage"
    anvil_error 'Anvil global config activation failed.'
    return 1
  fi
  if [[ "${ANVIL_TEST_KILL_AFTER_CONFIG_PUBLISH:-0}" == 1 ]]; then kill -9 "$$"; fi
  rm -rf -- "$previous"
  [[ ! -f "$ANVIL_CONFIG_DIR/opencode.jsonc" ]] || chmod 600 -- "$ANVIL_CONFIG_DIR/opencode.jsonc"
  for managed_script in memory.py source_registry.py runtime.py runtime_state.py databricks.py databricks_finops.py artifacts.py engineering.py public_errors.py analyze.py; do
    [[ ! -f "$ANVIL_CONFIG_DIR/scripts/$managed_script" ]] || chmod 700 -- "$ANVIL_CONFIG_DIR/scripts/$managed_script"
  done
  for managed_tree in communication databricks_providers engineering analysis; do
    if [[ -d "$ANVIL_CONFIG_DIR/scripts/$managed_tree" ]]; then
      find "$ANVIL_CONFIG_DIR/scripts/$managed_tree" -type f -exec chmod 600 -- {} +
    fi
  done
}

anvil_offer_databricks_setup() {
  [[ "${ANVIL_TEST_MODE:-0}" != 1 ]] || return 0
  anvil_log "Databricks remains optional. Run 'make databricks-setup' when you want Anvil to attempt CLI installation and configure providers."
}
