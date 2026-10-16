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
capabilities="$(python3 "$ROOT/scripts/runtime.py" capabilities --binary "$binary")"
structured_stats="$(python3 -c 'import json,sys; print(str(json.load(sys.stdin)["stats"]["structured_native_stats"]))' <<<"$capabilities")"
native_stats="$(python3 -c 'import json,sys; print(str(json.load(sys.stdin)["stats"]["native_stats"]))' <<<"$capabilities")"
version="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["runtime"]["version"] or "unknown")' <<<"$capabilities")"
if [[ "$native_stats" != True ]]; then
  anvil_warn "Native stats are unavailable on OpenCode $version; no token or cost values were inferred."
  exit 0
fi

tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/anvil-stats.XXXXXX")"
chmod 700 -- "$tmp_root"
cleanup() {
  local base canonical
  base="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "${TMPDIR:-/tmp}")/anvil-stats."
  canonical="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$tmp_root")"
  if [[ -d "$canonical" && "$canonical" == "$base"* && "$canonical" != / ]]; then rm -rf -- "$canonical"; fi
}
trap cleanup EXIT

if [[ "$structured_stats" == True ]]; then
  if ! OPENCODE_DISABLE_AUTOUPDATE=1 "$binary" stats --standalone --days "$days" --models --cost --json > "$tmp_root/stats.json" 2>"$tmp_root/stats.stderr"; then
    anvil_warn "OpenCode $version could not provide structured stats; no data was changed."
    exit 0
  fi
  if [[ "${ANVIL_STATS_JSON:-0}" == 1 ]]; then
    python3 "$ROOT/scripts/stats.py" --days "$days" --json < "$tmp_root/stats.json"
  else
    python3 "$ROOT/scripts/stats.py" --days "$days" < "$tmp_root/stats.json"
  fi
else
  # OpenCode 1 exposes native terminal stats, but not the structured JSON
  # interface Anvil uses for its normalized report.
  if ! OPENCODE_DISABLE_AUTOUPDATE=1 "$binary" stats --days "$days" > "$tmp_root/stats.txt" 2>"$tmp_root/stats.stderr"; then
    anvil_warn "OpenCode $version could not provide its native stats report; no values were inferred."
    exit 0
  fi
  cat -- "$tmp_root/stats.txt"
fi
