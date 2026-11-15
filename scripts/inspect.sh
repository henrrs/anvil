#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/scripts/lib/common.sh"

observation="$(python3 "$ROOT/scripts/lifecycle_resolver.py")"
python3 "$ROOT/scripts/inspect_data.py" \
  --home "$ANVIL_HOME_DIR" --config "$ANVIL_CONFIG_DIR" \
  --data "$ANVIL_DATA_HOME" --state "$ANVIL_STATE_HOME" --cwd "$PWD" \
  --observation-stdin <<<"$observation"
python3 -c 'import json,sys; sys.path.insert(0,sys.argv[1]); import databricks; state=json.load(sys.stdin)["current"]["databricks"]; print("Databricks\n  Overall              INVALID\n  Recovery             Review the Anvil-owned Databricks state before setup." if state.get("overall")=="INVALID" else databricks.status_text(state))' "$ROOT/scripts" <<<"$observation"
