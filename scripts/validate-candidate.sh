#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"

if [[ $# -ne 3 ]]; then
  printf 'usage: validate-candidate.sh CANDIDATE CONFIG_DIR VERSION\n' >&2
  exit 2
fi
candidate="$1"
config_source="$2"
expected_version="${3#v}"
expected_version="${expected_version#opencode }"
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
      python3 - "$candidate" "$home" "$config_home" "$data_home" "$state_home" <<'PY'
import os, signal, sys, time
candidate, home, config, data, state = map(os.path.realpath, sys.argv[1:])
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
            if os.path.realpath(os.path.join(root, "exe")) != candidate:
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
run_isolated() {
  (cd -- "$ROOT" && env -i PATH="${PATH:-/usr/bin:/bin}" HOME="$home" \
    XDG_CONFIG_HOME="$config_home" XDG_DATA_HOME="$data_home" XDG_STATE_HOME="$state_home" \
    TMPDIR="${TMPDIR:-/tmp}" LANG="${LANG:-C.UTF-8}" OPENCODE_DISABLE_AUTOUPDATE=1 \
    OPENCODE_PASSWORD=anvil-isolated-smoke-only "$candidate" "$@")
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

port="$(python3 - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
)"
service_url="http://127.0.0.1:$port"
(cd -- "$ROOT" && env -i PATH="${PATH:-/usr/bin:/bin}" HOME="$home" XDG_CONFIG_HOME="$config_home" XDG_DATA_HOME="$data_home" \
  XDG_STATE_HOME="$state_home" TMPDIR="${TMPDIR:-/tmp}" LANG="${LANG:-C.UTF-8}" \
  OPENCODE_DISABLE_AUTOUPDATE=1 OPENCODE_PASSWORD=anvil-isolated-smoke-only \
  "$candidate" serve --hostname 127.0.0.1 --port "$port" >"$temp_root/server.log" 2>&1) &
service_pid=$!
service_started=1
run_isolated debug config > "$temp_root/config-sources.json"
ready=0
for _ in $(seq 1 60); do
  if run_isolated api --server "$service_url" GET /api/command > "$temp_root/commands.json" 2>/dev/null && \
     run_isolated api --server "$service_url" GET /api/skill > "$temp_root/skills.json" 2>/dev/null && \
     run_isolated api --server "$service_url" GET /api/plugin > "$temp_root/plugins.json" 2>/dev/null && \
     run_isolated api --server "$service_url" GET /api/reference > "$temp_root/references.json" 2>/dev/null && \
     python3 - "$temp_root" <<'PY'
import json, sys
from pathlib import Path
root=Path(sys.argv[1])
def names(file, key):
    try:
        value=json.loads((root/file).read_text(encoding="utf-8"))
        return {item.get(key) for item in value.get("data", []) if isinstance(item, dict)}
    except (OSError, ValueError):
        return set()
raise SystemExit(0 if {"remember","recall","distill"} <= names("commands.json","name")
                 and {"anvil-memory","anvil-spark-performance","anvil-delta-lake","anvil-databricks","anvil-data-ingestion"} <= names("skills.json","id")
                 and "anvil-core" in names("plugins.json","id")
                 and "anvil-knowledge" in names("references.json","name") else 1)
PY
  then
    ready=1
    break
  fi
  kill -0 "$service_pid" 2>/dev/null || break
  sleep 0.2
done
[[ "$ready" == 1 ]] || {
  printf 'ERROR candidate did not register Anvil commands, skills, plugin and reference before the smoke-test timeout.\n' >&2
  exit 1
}

python3 - "$temp_root" "$expected_version" <<'PY'
import json, sys
from pathlib import Path
root=Path(sys.argv[1])
version=sys.argv[2]
def load(name):
    return json.loads((root/name).read_text(encoding="utf-8"))
sources=load("config-sources.json")
docs=[item.get("info") for item in sources if item.get("type")=="document" and isinstance(item.get("info"),dict)]
config=next((item for item in docs if item.get("default_agent")=="anvil"),None)
assert config, "candidate did not load the native Anvil config"
assert "model" not in config and "small_model" not in config
assert config["default_agent"]=="anvil"
assert config["agents"]["anvil"]["mode"]=="primary"
assert all(config["agents"][name].get("disabled") is True for name in ("build","plan","general","explore"))
assert config["compaction"].get("keep",{}).get("tokens")==8000
assert "prune" not in config["compaction"] and "tail_turns" not in config["compaction"]
commands=load("commands.json").get("data",[])
command_names={item.get("name") for item in commands}
assert {"remember","recall","distill"} <= command_names, f"missing commands: {command_names}"
skills=load("skills.json").get("data",[])
skill_ids={item.get("id") for item in skills}
expected={"anvil-memory","anvil-spark-performance","anvil-delta-lake","anvil-databricks","anvil-data-ingestion"}
assert expected <= skill_ids, f"missing skills: {sorted(expected-skill_ids)}"
plugins=load("plugins.json").get("data",[])
core=[item for item in plugins if item.get("id")=="anvil-core" and item.get("state",{}).get("status")=="active"]
assert len(core)==1, "anvil-core did not load as an active V2 plugin"
references=load("references.json").get("data",[])
assert any(item.get("name")=="anvil-knowledge" and item.get("path") for item in references), "anvil-knowledge reference was not loaded"
print(f"OpenCode {version}: native config, Anvil primary agent, commands, skills, plugin and knowledge reference validated")
PY
