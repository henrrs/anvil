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
  local base="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "${TMPDIR:-/tmp}")/anvil-tests."
  local canonical="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$tmp_root")"
  if [[ -d "$canonical" && "$canonical" == "$base"* && "$canonical" != / ]]; then rm -rf -- "$canonical"; fi
}
trap cleanup_temp EXIT
chmod 700 -- "$tmp_root"

resolved="$tmp_root/latest.json"
python3 "$ROOT/scripts/opencode_release.py" resolve > "$resolved"
version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8"))["version"])' "$resolved")"
candidate_dir="$tmp_root/candidate"
candidate="$(bash "$ROOT/scripts/install-opencode.sh" stage "$version" "$candidate_dir")"
release_date="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8"))["published_at"])' "$resolved")"
printf 'Testing official stable OpenCode %s (%s)\n' "$version" "$release_date"

bash "$ROOT/tests/run.sh" "$candidate" "$version" "$tmp_root"
