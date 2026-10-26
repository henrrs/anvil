#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/scripts/lib/common.sh"
source "$ROOT/scripts/lib/install.sh"

if [[ $# -lt 4 || $# -gt 5 ]]; then
  printf 'usage: rehearse-upgrade.sh CANDIDATE_BINARY EXACT_VERSION SOURCE_MAJOR TARGET_MAJOR [reuse-config]\n' >&2
  exit 2
fi
candidate="$1"
expected_version="${2#opencode }"
expected_version="${expected_version#v}"
source_major="$3"
target_major="$4"
reuse_config="${5:-no}"
[[ "$source_major" == 1 || "$source_major" == 2 ]] || { anvil_error "Unsupported source OpenCode major: $source_major"; exit 2; }
[[ "$target_major" == 1 || "$target_major" == 2 ]] || { anvil_error "Unsupported target OpenCode major: $target_major"; exit 2; }
tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/anvil-upgrade-rehearsal.XXXXXX")"
chmod 700 -- "$tmp_root"
cleanup() {
  local base canonical
  base="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "${TMPDIR:-/tmp}")/anvil-upgrade-rehearsal."
  canonical="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$tmp_root")"
  if [[ -d "$canonical" && "$canonical" == "$base"* && "$canonical" != / ]]; then rm -rf -- "$canonical"; fi
}
trap cleanup EXIT

mkdir -p -- "$tmp_root/version-home" "$tmp_root/version-config" "$tmp_root/version-data" "$tmp_root/version-state"
actual_version="$(env -i PATH="${PATH:-/usr/bin:/bin}" HOME="$tmp_root/version-home" \
  XDG_CONFIG_HOME="$tmp_root/version-config" XDG_DATA_HOME="$tmp_root/version-data" \
  XDG_STATE_HOME="$tmp_root/version-state" "$candidate" --version 2>/dev/null | head -n 1)"
actual_version="${actual_version#opencode }"
actual_version="${actual_version#v}"
[[ "$actual_version" == "$expected_version" && "${actual_version%%.*}" == "$target_major" && ( "$target_major" == 1 || "$target_major" == 2 ) ]] || {
  anvil_error "Rehearsal requires the exact staged OpenCode $target_major candidate; got ${actual_version:-unknown}."
  exit 1
}

test_home="$tmp_root/home"
test_config_home="$tmp_root/xdg-config"
test_data_home="$tmp_root/xdg-data"
test_state_home="$tmp_root/xdg-state"
mkdir -p -- "$test_home" "$test_config_home" "$test_data_home" "$test_state_home" "$tmp_root/v1-config"
if [[ -d "$ANVIL_CONFIG_DIR" ]]; then
  cp -a -- "$ANVIL_CONFIG_DIR/." "$tmp_root/v1-config/"
else
  anvil_error 'No global OpenCode config exists to rehearse.'
  exit 1
fi
if [[ "$source_major" == 1 ]]; then
  python3 "$ROOT/scripts/configure.py" audit-v1-compatible "$tmp_root/v1-config/opencode.jsonc"
else
  python3 "$ROOT/scripts/configure.py" audit-compatible "$tmp_root/v1-config/opencode.jsonc"
fi
if [[ -d "$ANVIL_DATA_HOME/opencode" ]]; then
  mkdir -p -- "$test_data_home/opencode"
  cp -a -- "$ANVIL_DATA_HOME/opencode/." "$test_data_home/opencode/"
fi
if [[ -d "$ANVIL_STATE_DIR" ]]; then
  mkdir -p -- "$test_state_home/opencode"
  cp -a -- "$ANVIL_STATE_DIR/." "$test_state_home/opencode/"
fi
if [[ -d "$ANVIL_MEMORY_DIR" ]]; then
  mkdir -p -- "$test_data_home/anvil/memory"
  cp -a -- "$ANVIL_MEMORY_DIR/." "$test_data_home/anvil/memory/"
fi

rehearsal_env=(env -i PATH="${PATH:-/usr/bin:/bin}" HOME="$test_home" \
  XDG_CONFIG_HOME="$test_config_home" XDG_DATA_HOME="$test_data_home" XDG_STATE_HOME="$test_state_home" \
  TMPDIR="${TMPDIR:-/tmp}" LANG="${LANG:-C.UTF-8}" OPENCODE_DISABLE_AUTOUPDATE=1 ANVIL_ROOT="$ROOT" \
  ANVIL_TEST_MODE="${ANVIL_TEST_MODE:-0}" \
  ANVIL_TEST_FAIL_CANDIDATE_VALIDATION="${ANVIL_TEST_FAIL_CANDIDATE_VALIDATION:-0}" \
  ANVIL_TEST_FAIL_REHEARSAL="${ANVIL_TEST_FAIL_REHEARSAL:-0}")
if [[ "$reuse_config" == yes ]]; then
  cp -a -- "$tmp_root/v1-config/." "$tmp_root/target-config/"
else
  "${rehearsal_env[@]}" bash -c '
    source "$ANVIL_ROOT/scripts/lib/common.sh"
    source "$ANVIL_ROOT/scripts/lib/install.sh"
    anvil_build_config "$1" "$2" yes "$3"
  ' _ "$tmp_root/target-config" "$tmp_root/v1-config" "$target_major"
fi
mkdir -p -- "$test_config_home/opencode"
cp -a -- "$tmp_root/target-config/." "$test_config_home/opencode/"
chmod 600 -- "$test_config_home/opencode/opencode.jsonc"
if [[ "$target_major" == 1 ]]; then
  if [[ "$reuse_config" == yes ]]; then
    python3 "$ROOT/scripts/configure.py" audit-v1-compatible "$test_config_home/opencode/opencode.jsonc"
  else
    python3 "$ROOT/scripts/configure.py" audit-v1 "$test_config_home/opencode/opencode.jsonc"
  fi
else
  if [[ "$reuse_config" == yes ]]; then
    python3 "$ROOT/scripts/configure.py" audit-compatible "$test_config_home/opencode/opencode.jsonc"
  else
    python3 "$ROOT/scripts/configure.py" audit "$test_config_home/opencode/opencode.jsonc"
  fi
fi

mkdir -p -- "$test_home/.opencode/bin"
install -m 0755 -- "$candidate" "$test_home/.opencode/bin/opencode"
test_binary="$test_home/.opencode/bin/opencode"
"${rehearsal_env[@]}" python3 "$ROOT/scripts/memory.py" init >/dev/null
source_anvil_version="$(python3 - "$ANVIL_DATA_DIR/installation.json" <<'PY'
import json,sys
try:
  value=json.load(open(sys.argv[1],encoding="utf-8"))
except (OSError,ValueError):
  value={}
print(value.get("anvil_version") or "")
PY
)"
if [[ "$reuse_config" != yes ]]; then
  source_anvil_version="$(cat "$ROOT/VERSION")"
fi
python3 - "$test_data_home/anvil/installation.json" "$expected_version" "$source_anvil_version" "$target_major" <<'PY'
import json,sys
from datetime import datetime,timezone
record={
  "version": sys.argv[2],
  "anvil_version": sys.argv[3],
  "runtime_major": int(sys.argv[4]),
  "migration": {"status":"rehearsal","from_anvil":"V1 fixture/state"},
  "installed_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
}
with open(sys.argv[1],"w",encoding="utf-8") as stream:
  json.dump(record,stream,indent=2); stream.write("\n")
PY
chmod 600 -- "$test_data_home/anvil/installation.json"

if [[ "${ANVIL_TEST_FAIL_REHEARSAL:-0}" == 1 ]]; then
  anvil_error 'Injected rehearsal failure before any live backup or mutation.'
  exit 1
fi

if [[ "$target_major" == 2 ]]; then
  # Native stats starts OpenCode 2 against copied user state.
  "${rehearsal_env[@]}" "$test_binary" stats --standalone --days 30 --models --cost --json > "$tmp_root/rehearsal-stats.json"
  python3 - "$tmp_root/rehearsal-stats.json" "$expected_version" <<'PY'
import json,sys
data=json.load(open(sys.argv[1],encoding="utf-8"))
assert isinstance(data,dict) and isinstance(data.get("range"),dict) and isinstance(data.get("tokens"),dict)
print(f"OpenCode {sys.argv[2]} read the copied state through native stats")
PY
else
  # OpenCode 1 exposes native text stats. Starting that command against the
  # copied data/state exercises the V1 reader without touching the live DB.
  "${rehearsal_env[@]}" "$test_binary" stats --days 30 > "$tmp_root/rehearsal-stats.txt"
  python3 - "$tmp_root/rehearsal-stats.txt" "$expected_version" <<'PY'
import sys
from pathlib import Path
text=Path(sys.argv[1]).read_text(encoding="utf-8")
assert "Sessions" in text and "Input" in text, "OpenCode 1 did not return its native stats summary"
print(f"OpenCode {sys.argv[2]} read the copied state through native text stats")
PY
fi

# Smoke-test the selected runtime adapter with the copied config.
"${rehearsal_env[@]}" bash "$ROOT/scripts/validate-candidate.sh" \
  "$test_binary" "$test_config_home/opencode" "$expected_version" "$target_major"
"${rehearsal_env[@]}" env PATH="$test_home/.opencode/bin:${PATH:-/usr/bin:/bin}" \
  ANVIL_SKIP_RUNTIME_PROBE=1 ANVIL_DOCTOR_LOCAL=1 bash "$ROOT/scripts/doctor.sh"
anvil_ok 'Migration rehearsal passed; the staged runtime/config and copied OpenCode data/state remained isolated.'
