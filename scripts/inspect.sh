#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/scripts/lib/common.sh"

observation="$(python3 "$ROOT/scripts/lifecycle_resolver.py")"
runtime="$(python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["current"]["active_runtime"]))' <<<"$observation")"
runtime_value() { python3 -c 'import json,sys; d=json.loads(sys.argv[1]); r=d.get("runtime") or {}; v=r.get(sys.argv[2]); print("" if v is None else v)' "$runtime" "$1"; }
binary="$(runtime_value executable)"
version="$(runtime_value version)"
generation="$(runtime_value generation)"
adapter="$(runtime_value adapter)"
installed="$(runtime_value installed)"
usable="$(runtime_value usable)"
supported="$(runtime_value supported)"
path_ready="$(runtime_value path_ready)"
anvil_version="$(cat "$ROOT/VERSION")"
installed_anvil="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["current"]["persisted"]["installation"]["product_version"] or "not recorded")' <<<"$observation")"

printf '%s\n' 'Anvil Inspect (read-only)' '────────────────────────'
python3 -c 'import json,sys; sys.path.insert(0,sys.argv[1]); import lifecycle_state; print(lifecycle_state._human(json.load(sys.stdin)["current"]["lifecycle"]))' "$ROOT/scripts" <<<"$observation"
printf '\n'
printf 'Anvil repository       %s\n' "$anvil_version"
printf 'Anvil installed        %s\n' "$installed_anvil"
printf 'OpenCode installed     %s\n' "${installed:-False}"
printf 'OpenCode usable        %s\n' "${usable:-False}"
printf 'OpenCode executable    %s\n' "${binary:-not found}"
printf 'OpenCode version       %s\n' "${version:-unknown}"
printf 'OpenCode generation   %s\n' "${generation:-unknown}"
printf 'Runtime adapter       %s\n' "${adapter:-unavailable}"
printf 'Runtime compatibility %s\n' "${supported:-unknown}"
printf 'PATH integration      %s\n' "$( [[ "$path_ready" == True ]] && printf 'READY' || printf 'NOT READY')"
printf 'Network required      NO\n'
printf 'Global config          %s\n' "$ANVIL_CONFIG_DIR"
printf 'CLI config             %s\n' "$ANVIL_CLI_CONFIG"
printf 'Data directory         %s\n' "$ANVIL_DATA_HOME/opencode"
printf 'State directory        %s\n' "$ANVIL_STATE_DIR"
printf '\n'
python3 "$ROOT/scripts/inspect_data.py" \
  --home "$ANVIL_HOME_DIR" --config "$ANVIL_CONFIG_DIR" \
  --data "$ANVIL_DATA_HOME" --state "$ANVIL_STATE_HOME" --cwd "$PWD" \
  --observation-stdin <<<"$observation"
python3 -c 'import json,sys; sys.path.insert(0,sys.argv[1]); import databricks; state=json.load(sys.stdin)["current"]["databricks"]; print("Databricks\n  Overall              INVALID\n  Recovery             Review the Anvil-owned Databricks state before setup." if state.get("overall")=="INVALID" else databricks.status_text(state))' "$ROOT/scripts" <<<"$observation"
