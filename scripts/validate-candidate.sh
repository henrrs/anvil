#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"

if [[ $# != 3 ]]; then
  printf 'usage: validate-candidate.sh CANDIDATE CONFIG_DIR VERSION\n' >&2
  exit 2
fi
candidate="$1"
config_source="$2"
expected_version="${3#v}"
expected_version="${expected_version#opencode }"
runtime_major="${expected_version%%.*}"
[[ "$runtime_major" == 1 ]] || { printf 'ERROR Anvil supports only OpenCode 1.x.\n' >&2; exit 2; }
temp_root="$(mktemp -d "${TMPDIR:-/tmp}/anvil-opencode-smoke.XXXXXX")"
service_started=0
service_pid=""
home=""
config_home=""
data_home=""
state_home=""

cleanup_temp() {
  if (( service_started )); then
    if [[ -n "$home" ]]; then
      env -i PATH="${PATH:-/usr/bin:/bin}" HOME="$home" XDG_CONFIG_HOME="$config_home" \
        XDG_DATA_HOME="$data_home" XDG_STATE_HOME="$state_home" \
        OPENCODE_DISABLE_AUTOUPDATE=1 "$candidate" service stop >/dev/null 2>&1 || true
      python3 - "$home" "$config_home" "$data_home" "$state_home" <<'PY'
import os, signal, sys, time
home, config, data, state = map(os.path.realpath, sys.argv[1:])
if not os.path.isdir("/proc"):
    raise SystemExit(0)

def matching():
    result = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        root = os.path.join("/proc", name)
        try:
            if os.stat(root).st_uid != os.geteuid():
                continue
            env = {}
            with open(os.path.join(root, "environ"), "rb") as stream:
                for item in stream.read().split(bytes([0])):
                    key, separator, value = item.partition(b"=")
                    if separator:
                        env[key.decode(errors="ignore")] = value.decode(errors="ignore")
            paths = tuple(os.path.realpath(env.get(key, "")) for key in (
                "HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"))
            if paths == (home, config, data, state):
                result.append(int(name))
        except (OSError, ValueError, ProcessLookupError):
            continue
    return result

for pid in matching():
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
deadline = time.monotonic() + 2
while time.monotonic() < deadline and matching():
    time.sleep(0.05)
for pid in matching():
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
PY
    fi
    if [[ -n "$service_pid" ]]; then
      kill "$service_pid" >/dev/null 2>&1 || true
      wait "$service_pid" >/dev/null 2>&1 || true
    fi
  fi
  local base canonical
  base="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "${TMPDIR:-/tmp}")/anvil-opencode-smoke."
  canonical="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$temp_root")"
  if [[ -d "$canonical" && "$canonical" == "$base"* && "$canonical" != / ]]; then rm -rf -- "$canonical"; fi
}
trap cleanup_temp EXIT
chmod 700 -- "$temp_root"
home="$temp_root/home"
config_home="$temp_root/xdg-config"
data_home="$temp_root/xdg-data"
state_home="$temp_root/xdg-state"
global_config="$config_home/opencode"
mkdir -p -- "$home" "$global_config" "$data_home" "$state_home"
cp -R -- "$config_source/." "$global_config/"
chmod 600 -- "$global_config/opencode.jsonc"

normalize_version() {
  local value="$1"
  value="${value#opencode }"
  value="${value#v}"
  printf '%s\n' "$value"
}
actual_version="$(normalize_version "$(env -i PATH="${PATH:-/usr/bin:/bin}" HOME="$home" \
  XDG_CONFIG_HOME="$config_home" XDG_DATA_HOME="$data_home" XDG_STATE_HOME="$state_home" \
  "$candidate" --version 2>/dev/null | head -n 1)")"
[[ "$actual_version" == "$expected_version" ]] || {
  printf 'ERROR candidate version mismatch: got %s, expected %s\n' "$actual_version" "$expected_version" >&2
  exit 1
}
if [[ "${ANVIL_TEST_MODE:-0}" == 1 && "${ANVIL_TEST_FAIL_CANDIDATE_VALIDATION:-0}" == 1 ]]; then
  printf 'ERROR injected candidate runtime validation failure.\n' >&2
  exit 1
fi

run_isolated() {
  (cd -- "$ROOT" && env -i PATH="${PATH:-/usr/bin:/bin}" HOME="$home" \
    XDG_CONFIG_HOME="$config_home" XDG_DATA_HOME="$data_home" XDG_STATE_HOME="$state_home" \
    TMPDIR="${TMPDIR:-/tmp}" LANG="${LANG:-C.UTF-8}" OPENCODE_DISABLE_AUTOUPDATE=1 \
    "$candidate" "$@")
}
run_isolated debug config > "$temp_root/config.json"
run_isolated debug skill > "$temp_root/skills.json"
python3 - "$temp_root" "$expected_version" "$config_source" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1])
config_root=Path(sys.argv[3])
config=json.loads((root/"config.json").read_text(encoding="utf-8"))
skills=json.loads((root/"skills.json").read_text(encoding="utf-8"))
assert config.get("default_agent")=="anvil", "OpenCode 1 did not load the Anvil default agent"
agent=config.get("agent",{}).get("anvil",{})
assert agent.get("mode")=="primary", "OpenCode 1 did not load the Anvil primary agent"
assert not ({"model", "variant", "prompt"} & set(agent)), "Anvil pins a model or replaces the provider prompt"
expected_commands={path.stem for path in (config_root/"commands").glob("*.md")}
assert expected_commands <= set(config.get("command",{})), f"OpenCode 1 did not load configured Markdown commands: {sorted(expected_commands-set(config.get('command',{})))}"
permission=agent.get("permission",{})
assert permission.get("*")=="deny" and permission.get("task")=="deny", "V1 deny-by-default/subagent policy did not load"
items=skills if isinstance(skills,list) else skills.get("data",[])
names={item.get("name") for item in items if isinstance(item,dict)}
expected={path.name for path in (config_root/"skills").iterdir() if path.is_dir() and (path/"SKILL.md").is_file()} if (config_root/"skills").is_dir() else set()
assert expected <= names, f"OpenCode 1 did not load configured skills: {sorted(expected-names)}"
print(f"OpenCode {sys.argv[2]}: V1 config, agent, commands and skills validated")
PY
exit 0
