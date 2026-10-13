#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/scripts/lib/common.sh"
anvil_need python3

days="${ANVIL_STATS_DAYS:-30}"
[[ "$days" =~ ^[0-9]{1,4}$ ]] || { anvil_error 'ANVIL_STATS_DAYS must be an integer from 0 to 9999.'; exit 2; }
binary=""
binary="$(anvil_open_code_binary || true)"
if [[ -z "$binary" || ! -x "$binary" ]]; then
  anvil_warn "OpenCode is not installed, so there are no native stats to show. Run 'make reforge' for a first Anvil installation."
  exit 0
fi
version="$("$binary" --version 2>/dev/null | head -n 1)"
version="${version#opencode }"
version="${version#v}"
[[ "$version" =~ ^2\.[0-9]+\.[0-9]+$ ]] || {
  next_step="make reforge"
  if [[ "$version" =~ ^1\.[0-9]+\.[0-9]+$ ]] && \
     python3 "$ROOT/scripts/configure.py" audit-v1 "$ANVIL_CONFIG_DIR/opencode.jsonc" >/dev/null 2>&1; then
    next_step="make upgrade"
  fi
  anvil_warn "Native Anvil stats require OpenCode 2; found ${version:-unknown}. No stats are available yet. Run '$next_step' to install or migrate Anvil."
  exit 0
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
