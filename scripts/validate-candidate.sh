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
temp_root="$(mktemp -d "${TMPDIR:-/tmp}/anvil-opencode-smoke.XXXXXX")"
cleanup_temp() {
  local base="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "${TMPDIR:-/tmp}")/anvil-opencode-smoke."
  local canonical="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$temp_root")"
  if [[ -d "$canonical" && "$canonical" == "$base"* && "$canonical" != / ]]; then rm -rf -- "$canonical"; fi
}
trap cleanup_temp EXIT
chmod 700 -- "$temp_root"
home="$temp_root/home"
config_home="$temp_root/xdg-config"
data_home="$temp_root/xdg-data"
state_home="$temp_root/xdg-state"
mkdir -p -- "$home" "$config_home/opencode" "$data_home" "$state_home" "$temp_root/project"
cp -R -- "$config_source/." "$config_home/opencode/"
chmod 600 -- "$config_home/opencode/opencode.jsonc"

actual_version="$("$candidate" --version 2>/dev/null | head -n 1)"
actual_version="${actual_version#v}"
[[ "$actual_version" == "$expected_version" ]] || {
  printf 'ERROR candidate version mismatch: got %s, expected %s\n' "$actual_version" "$expected_version" >&2
  exit 1
}

run_isolated() {
  (cd -- "$temp_root/project" && \
    env HOME="$home" XDG_CONFIG_HOME="$config_home" XDG_DATA_HOME="$data_home" \
      XDG_STATE_HOME="$state_home" OPENCODE_DISABLE_AUTOUPDATE=1 \
      "$candidate" "$@")
}

run_isolated debug config > "$temp_root/resolved.json"
run_isolated debug skill > "$temp_root/skills.json"
run_isolated agent list > "$temp_root/agents.txt"

python3 - "$temp_root/resolved.json" "$temp_root/skills.json" "$temp_root/agents.txt" "$expected_version" <<'PY'
import json, re, sys
config_path, skills_path, agents_path, version = sys.argv[1:]
with open(config_path, encoding="utf-8") as f:
    config = json.load(f)
with open(skills_path, encoding="utf-8") as f:
    skills_data = json.load(f)
with open(agents_path, encoding="utf-8") as f:
    agent_text = f.read()
assert config.get("default_agent") == "anvil", "resolved default agent is not anvil"
assert not any(key in config for key in ("model", "small_model")), "OpenCode global model defaults are pinned"
agent_config = config.get("agent", {})
for name in ("build", "plan", "general", "explore"):
    assert agent_config.get(name, {}).get("disable") is True, f"built-in {name} is not disabled"
anvil = agent_config.get("anvil", {})
assert anvil.get("mode") == "primary", "anvil is not a primary agent"
assert not any(key in anvil for key in ("model", "variant", "prompt")), "Anvil pins a model or replaces the provider prompt"
permissions = anvil.get("permission", {})
assert permissions.get("*") == "deny", "Anvil tools are not default-denied"
assert permissions.get("task") == "deny", "Anvil can spawn subagents"
assert permissions.get("read", {}).get("*.env") == "ask", "OpenCode sensitive-file prompt was weakened"
assert permissions.get("read", {}).get("*.env.example") == "allow", "OpenCode example env files were unexpectedly blocked"
assert permissions.get("bash", {}).get("*") == "allow", "shell tool is not allowed"
assert permissions.get("bash", {}).get("git reset --hard*") == "ask", "destructive Git command is not approval-gated"
for tool in ("glob", "grep", "list", "edit", "webfetch", "websearch", "lsp", "todowrite", "question"):
    assert permissions.get(tool) == "allow", f"core tool {tool} is not allowed"
skill_permissions = permissions.get("skill", {})
assert skill_permissions.get("*") == "deny", "arbitrary skills are not denied"
expected_skills = {
    "anvil-memory", "anvil-spark-performance", "anvil-delta-lake",
    "anvil-databricks", "anvil-data-ingestion",
}
assert {name for name, action in skill_permissions.items() if name != "*" and action == "allow"} == expected_skills
assert not config.get("mcp"), "Anvil candidate has global MCP servers"
assert not config.get("plugin"), "Anvil candidate has configured plugins"
assert set(agent_config) == {"build", "plan", "general", "explore", "anvil"}, "unexpected global agent definitions"
assert set(config.get("command", {})) >= {"remember", "recall"}, "slash commands were not loaded"
if isinstance(skills_data, dict):
    skill_values = list(skills_data.values())
elif isinstance(skills_data, list):
    skill_values = skills_data
else:
    raise AssertionError("OpenCode debug skill output had an unexpected shape")
discovered = {item.get("name") for item in skill_values if isinstance(item, dict) and item.get("name")}
assert expected_skills <= discovered, f"missing discovered skills: {sorted(expected_skills - discovered)}"
lines = [line.strip() for line in agent_text.splitlines() if re.match(r"^[A-Za-z0-9_-]+ \((primary|subagent)\)$", line.strip())]
primary = {line.split(" ", 1)[0] for line in lines if line.endswith("(primary)")}
primary -= {"compaction", "title", "summary"}  # OpenCode internal maintenance agents.
assert primary == {"anvil"}, f"visible primary agents are {sorted(primary)}"
print(f"OpenCode {version}: resolved config, agent, skills, and commands validated")
PY
