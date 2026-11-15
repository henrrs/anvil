#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/scripts/lib/common.sh"
source "$ROOT/scripts/lib/install.sh"

if [[ $# -lt 2 || $# -gt 5 ]]; then
  printf 'usage: rehearse-upgrade.sh CANDIDATE_BINARY EXACT_VERSION [reuse-config] [prepared-config] [anvil-only]\n' >&2
  exit 2
fi
candidate="$1"
expected_version="${2#opencode }"
expected_version="${expected_version#v}"
reuse_config="${3:-no}"
prepared_config="${4:-}"
anvil_only="${5:-no}"
[[ "$anvil_only" == yes || "$anvil_only" == no ]] || { anvil_error 'Invalid Anvil-only rehearsal mode.'; exit 2; }
if [[ "$anvil_only" == yes && -z "$prepared_config" ]]; then
  anvil_error 'An Anvil-only rehearsal requires the audited prepared profile.'
  exit 2
fi
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
[[ "$actual_version" == "$expected_version" && "${actual_version%%.*}" == 1 ]] || {
  anvil_error "Rehearsal requires the exact staged OpenCode 1 candidate; got ${actual_version:-unknown}."
  exit 1
}

test_home="$tmp_root/home"
test_config_home="$tmp_root/xdg-config"
test_data_home="$tmp_root/xdg-data"
test_state_home="$tmp_root/xdg-state"
mkdir -p -- "$test_home" "$test_config_home" "$test_data_home" "$test_state_home" "$tmp_root/v1-config"
if [[ "$anvil_only" == no ]]; then
  if [[ -d "$ANVIL_CONFIG_DIR" ]]; then
    cp -a -- "$ANVIL_CONFIG_DIR/." "$tmp_root/v1-config/"
  else
    anvil_error 'No global OpenCode config exists to rehearse.'
    exit 1
  fi
  python3 "$ROOT/scripts/configure.py" audit-compatible "$tmp_root/v1-config/opencode.jsonc"
else
  # make upgrade only changes Anvil-owned profile files; the caller has
  # already audited both installed and staged profiles. Do not copy a global
  # OpenCode profile that may contain provider credentials into the rehearsal.
  [[ -d "$prepared_config" && ! -L "$prepared_config" ]] || {
    anvil_error 'The prepared target config is missing or unsafe for Anvil-only rehearsal.'
    exit 1
  }
  python3 "$ROOT/scripts/configure.py" audit "$prepared_config/opencode.jsonc"
fi
rehearsal_probe=off
if [[ "${ANVIL_TEST_MODE:-0}" == 1 ]]; then
  rehearsal_probe=full
  [[ "$anvil_only" == yes ]] && rehearsal_probe=anvil-only
fi
rehearsal_env=(env -i PATH="${PATH:-/usr/bin:/bin}" HOME="$test_home" \
  XDG_CONFIG_HOME="$test_config_home" XDG_DATA_HOME="$test_data_home" XDG_STATE_HOME="$test_state_home" \
  TMPDIR="${TMPDIR:-/tmp}" LANG="${LANG:-C.UTF-8}" OPENCODE_DISABLE_AUTOUPDATE=1 ANVIL_ROOT="$ROOT" \
  ANVIL_TEST_MODE="${ANVIL_TEST_MODE:-0}" \
  ANVIL_REHEARSAL_PROBE="$rehearsal_probe" \
  ANVIL_TEST_FAIL_CANDIDATE_VALIDATION="${ANVIL_TEST_FAIL_CANDIDATE_VALIDATION:-0}" \
  ANVIL_TEST_FAIL_REHEARSAL="${ANVIL_TEST_FAIL_REHEARSAL:-0}")
if [[ -n "$prepared_config" ]]; then
  [[ -d "$prepared_config" && ! -L "$prepared_config" ]] || {
    anvil_error 'The prepared target config is missing or unsafe for lifecycle rehearsal.'
    exit 1
  }
  if [[ "$anvil_only" == no ]]; then cp -a -- "$prepared_config/." "$tmp_root/target-config/"; fi
elif [[ "$reuse_config" == yes ]]; then
  cp -a -- "$tmp_root/v1-config/." "$tmp_root/target-config/"
else
  "${rehearsal_env[@]}" bash -c '
    source "$ANVIL_ROOT/scripts/lib/common.sh"
    source "$ANVIL_ROOT/scripts/lib/install.sh"
    anvil_build_config "$1" "$2" yes
  ' _ "$tmp_root/target-config" "$tmp_root/v1-config"
fi
if [[ "$anvil_only" == no ]]; then
  mkdir -p -- "$test_config_home/opencode"
  cp -a -- "$tmp_root/target-config/." "$test_config_home/opencode/"
  chmod 600 -- "$test_config_home/opencode/opencode.jsonc"
fi
if [[ "$anvil_only" == no ]]; then
  if [[ "$reuse_config" == yes && -z "$prepared_config" ]]; then
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
if not isinstance(value,dict): value={}
print(value.get("anvil_version") or "")
PY
)"
if [[ "$reuse_config" != yes || -n "$prepared_config" ]]; then
  source_anvil_version="$(cat "$ROOT/VERSION")"
fi
python3 - "$test_data_home/anvil/installation.json" "$expected_version" "$source_anvil_version" <<'PY'
import json,sys
from datetime import datetime,timezone
record={
  "version": sys.argv[2],
  "anvil_version": sys.argv[3],
  "runtime_major": 1,
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

 # OpenCode 1 exposes native text stats. Run it only against disposable
 # empty XDG directories; do not copy or inspect a user's database.
"${rehearsal_env[@]}" "$test_binary" stats --days 30 > "$tmp_root/rehearsal-stats.txt"
python3 - "$tmp_root/rehearsal-stats.txt" "$expected_version" <<'PY'
import sys
from pathlib import Path
text=Path(sys.argv[1]).read_text(encoding="utf-8")
assert "Sessions" in text and "Input" in text, "OpenCode 1 did not return its native stats summary"
print(f"OpenCode {sys.argv[2]} stats passed against the isolated empty data store")
PY

if [[ "$anvil_only" == no ]]; then
  # Runtime operations must validate the staged profile. The Anvil-only path
  # leaves the exact runtime and profile parsing boundary unchanged; its target
  # managed profile was audited above without copying user configuration.
  "${rehearsal_env[@]}" bash "$ROOT/scripts/validate-candidate.sh" \
    "$test_binary" "$test_config_home/opencode" "$expected_version"
  "${rehearsal_env[@]}" env PATH="$test_home/.opencode/bin:${PATH:-/usr/bin:/bin}" \
    ANVIL_SKIP_RUNTIME_PROBE=1 ANVIL_DOCTOR_LOCAL=1 ANVIL_REHEARSAL=1 bash "$ROOT/scripts/doctor.sh"
  anvil_ok 'Runtime migration rehearsal passed with isolated empty OpenCode data/state; user databases and memory were not copied.'
else
  anvil_ok 'Anvil-only rehearsal passed with the existing OpenCode executable and isolated empty data/state; user config and memory were not copied.'
fi
