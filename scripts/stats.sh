#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/scripts/lib/common.sh"
anvil_need python3

days="${ANVIL_STATS_DAYS:-30}"
[[ "$days" =~ ^[0-9]{1,4}$ ]] || { anvil_error 'ANVIL_STATS_DAYS must be an integer from 0 to 9999.'; exit 2; }
binary=""
if [[ -x "$ANVIL_INSTALLED_BINARY" ]]; then
  binary="$ANVIL_INSTALLED_BINARY"
else
  binary="$(command -v opencode 2>/dev/null || true)"
fi
[[ -n "$binary" && -x "$binary" ]] || { anvil_error 'OpenCode executable not found.'; exit 1; }
version="$("$binary" --version 2>/dev/null | head -n 1)"
version="${version#opencode }"
version="${version#v}"
[[ "$version" =~ ^2\.[0-9]+\.[0-9]+$ ]] || {
  anvil_error "Native Anvil stats require OpenCode 2; found ${version:-unknown}."
  exit 1
}

tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/anvil-stats.XXXXXX")"
chmod 700 -- "$tmp_root"
cleanup() {
  local base canonical
  base="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "${TMPDIR:-/tmp}")/anvil-stats."
  canonical="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$tmp_root")"
  if [[ -d "$canonical" && "$canonical" == "$base"* && "$canonical" != / ]]; then rm -rf -- "$canonical"; fi
}
trap cleanup EXIT

"$binary" stats --standalone --days "$days" --models --cost --json > "$tmp_root/stats.json"
if [[ "${ANVIL_STATS_JSON:-0}" == 1 ]]; then
  python3 "$ROOT/scripts/stats.py" --days "$days" --json < "$tmp_root/stats.json"
else
  python3 "$ROOT/scripts/stats.py" --days "$days" < "$tmp_root/stats.json"
fi
