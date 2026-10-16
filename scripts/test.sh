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

resolved_v2="$tmp_root/opencode-v2-latest.json"
resolved_v1="$tmp_root/opencode-v1-latest.json"
python3 "$ROOT/scripts/opencode_release.py" resolve > "$resolved_v2"
bash "$ROOT/scripts/install-opencode.sh" resolve 1 > "$resolved_v1"
version_v2="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8"))["version"])' "$resolved_v2")"
version_v1="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8"))["version"])' "$resolved_v1")"
candidate_v2="$(bash "$ROOT/scripts/install-opencode.sh" stage "$version_v2" "$tmp_root/opencode-v2" 2)"
candidate_v1="$(bash "$ROOT/scripts/install-opencode.sh" stage "$version_v1" "$tmp_root/opencode-v1-latest" 1)"
version_v1_min="1.18.18"
candidate_v1_min="$(bash "$ROOT/scripts/install-opencode.sh" stage "$version_v1_min" "$tmp_root/opencode-v1-minimum" 1)"
release_date_v2="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8"))["published_at"])' "$resolved_v2")"
release_date_v1="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8"))["published_at"])' "$resolved_v1")"
printf 'Testing OpenCode 1 %s (%s), OpenCode 1 compatibility floor %s, and OpenCode 2 %s (%s)\n' \
  "$version_v1" "$release_date_v1" "$version_v1_min" "$version_v2" "$release_date_v2"

bash "$ROOT/tests/run.sh" "$candidate_v2" "$version_v2" "$candidate_v1" "$version_v1" \
  "$candidate_v1_min" "$version_v1_min" "$tmp_root"
