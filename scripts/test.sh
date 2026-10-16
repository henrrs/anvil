#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/scripts/lib/common.sh"
anvil_need python3 tar
python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("ERROR make test requires Python 3.11 or newer.")
PY

tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/anvil-tests.XXXXXX")"
cleanup_temp() {
  local base canonical
  base="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "${TMPDIR:-/tmp}")/anvil-tests."
  canonical="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$tmp_root")"
  if [[ -d "$canonical" && "$canonical" == "$base"* && "$canonical" != / ]]; then
    rm -rf -- "$canonical"
  fi
}
trap cleanup_temp EXIT
chmod 700 -- "$tmp_root"

fixture_bin="$ROOT/tests/fixtures/bin"
export ANVIL_DATABRICKS_CLI="$fixture_bin/databricks"
export ANVIL_DATABRICKS_SCENARIO=valid
printf 'Testing offline OpenCode 1 %s, OpenCode 1 compatibility floor %s, and OpenCode 2 %s\n' \
  "1.18.18" "1.18.18" "2.0.0"

bash "$ROOT/tests/run.sh" \
  "$fixture_bin/opencode-v2" "2.0.0" \
  "$fixture_bin/opencode-v1" "1.18.18" \
  "$fixture_bin/opencode-v1" "1.18.18" \
  "$tmp_root"
