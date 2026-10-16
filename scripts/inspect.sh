#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/scripts/lib/common.sh"

runtime="$(anvil_runtime_json)"
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
installed_anvil="$(python3 - "$ANVIL_DATA_DIR/installation.json" <<'PY'
import json,sys
try: print(json.load(open(sys.argv[1],encoding="utf-8")).get("anvil_version") or "not recorded")
except (OSError,ValueError): print("not recorded")
PY
)"

printf '%s\n' 'Anvil Inspect (read-only)' '────────────────────────'
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
  --data "$ANVIL_DATA_HOME" --state "$ANVIL_STATE_HOME" --cwd "$PWD"
python3 "$ROOT/scripts/databricks.py" status --local --format text
