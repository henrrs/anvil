#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
if [[ $# -ne 7 ]]; then
  printf 'usage: tests/run.sh OPENCODE_2_CANDIDATE VERSION_2 OPENCODE_1_CANDIDATE VERSION_1 OPENCODE_1_MINIMUM VERSION_1_MINIMUM TEMP_ROOT\n' >&2
  exit 2
fi
candidate_v2="$1"
version_v2="${2#opencode }"
version_v2="${version_v2#v}"
candidate_v1="$3"
version_v1="${4#opencode }"
version_v1="${version_v1#v}"
candidate_v1_min="$5"
version_v1_min="${6#opencode }"
version_v1_min="${version_v1_min#v}"
tmp_root="$7"

# Every test subprocess gets a clean user and XDG namespace. Keep only the
# selected Python runtime plus standard system tools on PATH; developer tools,
# Databricks profiles, and user-site packages must not influence the suite.
mkdir -p -- "$tmp_root/test-home" "$tmp_root/test-config" "$tmp_root/test-data" \
  "$tmp_root/test-cache" "$tmp_root/test-state"
python3_dir="$(python3 -c 'import pathlib,sys; print(pathlib.Path(sys.executable).parent)')"
export PATH="$python3_dir:/usr/bin:/bin"
export HOME="$tmp_root/test-home"
export XDG_CONFIG_HOME="$tmp_root/test-config"
export XDG_DATA_HOME="$tmp_root/test-data"
export XDG_CACHE_HOME="$tmp_root/test-cache"
export XDG_STATE_HOME="$tmp_root/test-state"
export PYTHONNOUSERSITE=1
unset PYTHONHOME PYTHONPATH VIRTUAL_ENV CONDA_PREFIX
for variable_name in ${!DATABRICKS_@}; do unset "$variable_name"; done
export PYTHONPATH="$ROOT/tests/fixtures/network-denied"
export ANVIL_NETWORK_GUARD_LOG="$tmp_root/test-network-attempts.log"
python3 - "$tmp_root" <<'PY' || { printf 'FAIL test HOME/XDG isolation\n' >&2; exit 1; }
import os,sys
from pathlib import Path
root=Path(sys.argv[1])
assert Path(os.environ["HOME"]) == root / "test-home"
for key, name in (("XDG_CONFIG_HOME","test-config"),("XDG_DATA_HOME","test-data"),
                  ("XDG_CACHE_HOME","test-cache"),("XDG_STATE_HOME","test-state")):
    assert Path(os.environ[key]) == root / name
assert not any(key.startswith("DATABRICKS_") for key in os.environ)
PY

pass() { printf 'PASS %s\n' "$*"; }
fail() { printf 'FAIL %s\n' "$*" >&2; exit 1; }

command -v python3 >/dev/null || fail 'python3 is required'
python3 - <<'PY' || fail 'Python 3.11 or newer is required'
import sys
if sys.version_info < (3, 11): raise SystemExit(1)
PY

while IFS= read -r -d '' script; do
  bash -n "$script" || fail "shell syntax: $script"
done < <(find "$ROOT/scripts" "$ROOT/tests" -type f -name '*.sh' -print0)
python3 - "$ROOT" <<'PY' || fail 'Python syntax'
import ast,sys
from pathlib import Path
root=Path(sys.argv[1])
for folder in (root/"scripts",root/"tests"):
    for path in folder.rglob("*.py"):
        if "__pycache__" not in path.parts:
            ast.parse(path.read_text(encoding="utf-8"),filename=str(path))
PY
pass 'Shell and Python syntax'

python3 - "$ROOT" <<'PY' || fail 'runtime independence boundary or repository identifier hygiene'
import re,subprocess,sys
from pathlib import Path
root=Path(sys.argv[1])
tracked=subprocess.run(["git","-C",str(root),"ls-files","-z"],capture_output=True,check=True).stdout.split(bytes([0]))
for relative in filter(None,tracked):
    path=root / relative.decode("utf-8",errors="strict")
    try: text=path.read_text(encoding="utf-8")
    except (UnicodeDecodeError,OSError): continue
    assert not re.search(r"\b[x][p]\b",text,re.IGNORECASE), f"retired standalone identifier in tracked file: {path.relative_to(root)}"

makefile=(root/"Makefile").read_text(encoding="utf-8")
upgrade=(root/"scripts/anvil_upgrade.sh").read_text(encoding="utf-8")
assert "@bash scripts/anvil_upgrade.sh" in makefile, "make upgrade does not use the Anvil-only lifecycle"
assert "@bash scripts/upgrade.sh --update-runtime" in makefile, "same-major runtime update target is missing"
for forbidden in ("install-opencode.sh", "opencode_release.py", "opencode_v1_release.py", "latest-version"):
    assert forbidden not in upgrade, f"Anvil-only upgrade imports runtime resolver/installer: {forbidden}"
doctor=(root/"scripts/doctor.sh").read_text(encoding="utf-8")
assert '"$ROOT/scripts/databricks.py" status' in doctor and "--format text" in doctor
assert "ANVIL_DOCTOR_LOCAL" in doctor, "doctor has no local-only mode for lifecycle postflight"
for name in ("scripts/anvil_upgrade.sh", "scripts/reforge.sh", "scripts/upgrade.sh", "scripts/rehearse-upgrade.sh"):
    assert "ANVIL_DOCTOR_LOCAL=1" in (root/name).read_text(encoding="utf-8"), f"{name} may contact Databricks during lifecycle validation"
assert "local_status()" in (root/"scripts/databricks.py").read_text(encoding="utf-8")
print("OK local Anvil-upgrade dependency boundary and tracked-file hygiene")
PY
pass 'Anvil upgrade cannot call runtime release resolution and the retired identifier stays absent'

python3 - "$ROOT" <<'PY' || fail 'external network guard fixture'
import importlib.util,os,sys
from pathlib import Path
path=Path(sys.argv[1])/"tests/fixtures/network-denied/sitecustomize.py"
spec=importlib.util.spec_from_file_location("anvil_network_guard_fixture",path)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module._local("127.0.0.1") and module._local("::1")
assert not module._local("api.github.com") and not module._local("203.0.113.1")
PY
pass 'Offline lifecycle guard blocks external endpoints and permits loopback fixtures'

python3 - "$ROOT" <<'PY' || fail 'npm registry error diagnostics'
import importlib.util,sys,urllib.error
from pathlib import Path
path=Path(sys.argv[1]) / "scripts" / "opencode_release.py"
spec=importlib.util.spec_from_file_location("anvil_opencode_release",path)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
original=module.urllib.request.urlopen
def forbidden(request,timeout):
    raise urllib.error.HTTPError(request.full_url,403,"Forbidden",None,None)
module.urllib.request.urlopen=forbidden
try:
    try:
        module.request_json("https://registry.npmjs.org/@opencode%2fcli")
    except RuntimeError as exc:
        message=str(exc)
        assert "HTTP 403" in message
        assert "https://registry.npmjs.org/@opencode%2fcli" in message
        assert "proxy/firewall" in message
    else:
        raise AssertionError("HTTP 403 was not reported")
finally:
    module.urllib.request.urlopen=original
PY
pass 'npm registry HTTP errors include the endpoint and network guidance'

# The repository template contains a path placeholder; validate the generated
# native config so the audit sees the absolute knowledge Reference path used
# by an installation.
mkdir -p -- "$tmp_root/audit-home" "$tmp_root/audit-config" "$tmp_root/audit-data" "$tmp_root/audit-state"
env HOME="$tmp_root/audit-home" XDG_CONFIG_HOME="$tmp_root/audit-config" \
  XDG_DATA_HOME="$tmp_root/audit-data" XDG_STATE_HOME="$tmp_root/audit-state" ANVIL_ROOT="$ROOT" \
  bash -c 'source "$ANVIL_ROOT/scripts/lib/common.sh"; source "$ANVIL_ROOT/scripts/lib/install.sh"; anvil_build_config "$1" ""' \
  _ "$tmp_root/config-audit-ready" || fail 'build isolated config for audit'
python3 "$ROOT/scripts/configure.py" audit "$tmp_root/config-audit-ready/opencode.jsonc" || fail 'V2 native config audit'
env HOME="$tmp_root/audit-home" XDG_CONFIG_HOME="$tmp_root/audit-config" \
  XDG_DATA_HOME="$tmp_root/audit-data" XDG_STATE_HOME="$tmp_root/audit-state" ANVIL_ROOT="$ROOT" \
  bash -c 'source "$ANVIL_ROOT/scripts/lib/common.sh"; source "$ANVIL_ROOT/scripts/lib/install.sh"; anvil_build_config "$1" "" no 1' \
  _ "$tmp_root/config-audit-v1-ready" || fail 'build isolated OpenCode 1 config'
python3 "$ROOT/scripts/configure.py" audit-v1 "$tmp_root/config-audit-v1-ready/opencode.jsonc" || fail 'OpenCode 1 runtime config audit'
python3 "$ROOT/scripts/configure.py" audit-v1 "$ROOT/tests/fixtures/v1/opencode.jsonc" || fail 'V1 regression config fixture'
python3 "$ROOT/scripts/version_docs.py" || fail 'release documentation consistency'
python3 - "$ROOT/scripts/runtime.py" <<'PY' || fail 'runtime policy/capability adapters'
import importlib.util,sys
spec=importlib.util.spec_from_file_location("anvil_runtime",sys.argv[1])
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
policy=module.policy()["opencode"]
assert policy["supported_majors"]==[1,2] and policy["default_major"]==1
v1=module.capabilities(requested_major=1)
v2=module.capabilities(requested_major=2)
assert v1["core"]["distill"] and v1["memory"]["source_registry"] and not v1["memory"]["native_search_tool"]
assert not v1["knowledge"]["native_references"] and v1["stats"]["native_stats"] and not v1["stats"]["structured_native_stats"]
assert v1["runtime_features"]["native_plugins"] and not v1["runtime_features"]["anvil_core_plugin"]
assert v2["memory"]["native_search_tool"] and v2["knowledge"]["native_references"] and v2["stats"]["structured_native_stats"]
assert v2["runtime_features"]["native_plugins"] and v2["runtime_features"]["anvil_core_plugin"]
PY
pass 'Runtime policy exposes independent OpenCode 1/2 adapters and capability profiles'
python3 "$ROOT/tests/databricks.py" || fail 'Databricks offline integration and FinOps scenarios'
pass 'Databricks profiles, bounded execution, no-mutation policy, and FinOps evidence scenarios'
env ANVIL_DATABRICKS_CLI=/nonexistent/anvil-test-databricks \
  make --no-print-directory FORMAT=json capabilities > "$tmp_root/capabilities.json" || fail 'combined JSON capabilities'
python3 - "$tmp_root/capabilities.json" <<'PY' || fail 'capabilities output is not one valid runtime/Databricks JSON document'
import json,sys
data=json.load(open(sys.argv[1],encoding="utf-8"))
assert set(data) >= {"runtime","databricks","databricks_capabilities","communication"}
assert data["communication"]["status"] == "AVAILABLE"
assert "markdown_report" in data["communication"]["outputs"]["available"]
assert "pptx" in data["communication"]["outputs"]["unavailable"]
assert data["databricks"]["cli_installed"] is False
PY
pass 'make capabilities emits one combined machine-readable JSON document'
python3 - "$ROOT" <<'PY' || fail 'V1/V2 baseline, model neutrality, plugin scope, or secret scan'
import json,sys
from pathlib import Path
root=Path(sys.argv[1])
config=json.loads((root/"config/opencode.jsonc").read_text(encoding="utf-8"))
assert config["default_agent"]=="anvil"
assert "model" not in config and "small_model" not in config
assert config["agents"]["anvil"]["mode"]=="primary"
assert all(config["agents"][name]["disabled"] is True for name in ("build","plan","general","explore"))
assert config["agents"]["anvil"]["permissions"][-2]["action"]=="subagent"
assert config["mcp"]["servers"]=={}
assert config["plugins"]==["./plugins/anvil-core"]
assert {p.stem for p in (root/"config/commands").glob("*.md")}=={"remember","recall","distill","review"}
assert {p.name for p in (root/"config/skills").iterdir()}=={"anvil-memory","anvil-spark-performance","anvil-delta-lake","anvil-databricks","anvil-data-ingestion","anvil-communication","anvil-engineering","anvil-system-design"}
plugin=(root/"config/plugins/anvil-core/index.ts").read_text(encoding="utf-8")
assert "anvil_memory_search" in plugin and "ctx.tool.transform" in plugin
for forbidden in ("chat.message", "session.created", "tool.execute", "provider.transform", "system.prompt", "session.compacting"):
    assert forbidden not in plugin, f"unexpected hook/routing behavior {forbidden}"
for path in root.rglob("*"):
    if not path.is_file() or ".git" in path.parts or path.suffix in {".pyc", ".db", ".sqlite"}: continue
    content=path.read_bytes()
    assert b"-----BEGIN " + b"PRIVATE KEY-----" not in content, f"possible private key in {path}"
    assert b"gh" + b"p_" not in content, f"possible GitHub token in {path}"
PY
pass 'V1 invariants, V2 model-neutral config, single plugin/tool scope, and secret scan'

# Construct the native config with a temporary data root, then load the local
# OpenCode contract fixture under a clean HOME/XDG environment.
mkdir -p -- "$tmp_root/smoke-home" "$tmp_root/smoke-config" "$tmp_root/smoke-data" "$tmp_root/smoke-state"
env HOME="$tmp_root/smoke-home" XDG_CONFIG_HOME="$tmp_root/smoke-config" \
  XDG_DATA_HOME="$tmp_root/smoke-data" XDG_STATE_HOME="$tmp_root/smoke-state" ANVIL_ROOT="$ROOT" \
  bash -c 'source "$ANVIL_ROOT/scripts/lib/common.sh"; source "$ANVIL_ROOT/scripts/lib/install.sh"; anvil_build_config "$1" ""' \
  _ "$tmp_root/smoke-config-ready" || fail 'build isolated OpenCode config'
bash "$ROOT/scripts/validate-candidate.sh" "$candidate_v2" "$tmp_root/smoke-config-ready" "$version_v2" 2 || fail 'exact OpenCode 2 candidate runtime smoke test'
pass "Offline OpenCode 2 profile fixture $version_v2 loads Anvil config, agent, commands, skills, plugin and knowledge reference"
env HOME="$tmp_root/smoke-home" XDG_CONFIG_HOME="$tmp_root/smoke-config" \
  XDG_DATA_HOME="$tmp_root/smoke-data" XDG_STATE_HOME="$tmp_root/smoke-state" ANVIL_ROOT="$ROOT" \
  bash -c 'source "$ANVIL_ROOT/scripts/lib/common.sh"; source "$ANVIL_ROOT/scripts/lib/install.sh"; anvil_build_config "$1" "" no 1' \
  _ "$tmp_root/smoke-config-v1-ready" || fail 'build isolated OpenCode 1 config'
bash "$ROOT/scripts/validate-candidate.sh" "$candidate_v1" "$tmp_root/smoke-config-v1-ready" "$version_v1" 1 || fail 'OpenCode 1 candidate runtime smoke test'
pass "Offline OpenCode 1 profile fixture $version_v1 loads Anvil config, agent, commands and skills"
bash "$ROOT/scripts/validate-candidate.sh" "$candidate_v1_min" "$tmp_root/smoke-config-v1-ready" "$version_v1_min" 1 || fail 'minimum supported OpenCode 1 runtime smoke test'
pass "OpenCode 1 compatibility floor profile fixture $version_v1_min loads Anvil config, agent, commands and skills"

# V1 Markdown remains readable/searchable and search remains a no-write operation.
memory_home="$tmp_root/memory-home"
memory_data="$tmp_root/memory-data"
mkdir -p -- "$memory_home" "$memory_data/anvil/memory/company"
cp -- "$ROOT/tests/fixtures/v1/memory/company/databricks-secret-policy.md" "$memory_data/anvil/memory/company/"
before_memory="$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$memory_data/anvil/memory/company/databricks-secret-policy.md")"
python3_binary="$(command -v python3)"
env HOME="$memory_home" XDG_DATA_HOME="$memory_data" PATH=/nonexistent \
  "$python3_binary" "$ROOT/scripts/memory.py" search "dbutils secrets" > "$tmp_root/v1-memory-search.txt" || fail 'V1 Markdown memory search'
python3 - "$memory_data/anvil/memory/company/databricks-secret-policy.md" "$before_memory" <<'PY' || fail 'V1 memory search wrote or changed the fixture'
import hashlib,sys
assert hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest()==sys.argv[2]
PY
audit_json="$(env HOME="$memory_home" XDG_DATA_HOME="$memory_data" python3 "$ROOT/scripts/memory.py" audit)"
python3 -c 'import json,sys; d=json.loads(sys.argv[1]); assert d=={"valid":1,"invalid":0,"files":1}' "$audit_json" || fail 'memory audit counts'
pass 'V1 memory reads without rewrites; Python search works with ripgrep unavailable'

python3 "$ROOT/tests/distill.py" || fail '/distill fixture, provenance, drift and idempotency checks'
python3 "$ROOT/tests/communication.py" || fail 'communication/artifact intelligence offline contracts and regressions'
pass 'Communication and artifact intelligence runs deterministic offline regressions'
python3 "$ROOT/tests/engineering.py" || fail 'engineering state, interruption, stale evidence and direct-path regressions'
python3 "$ROOT/evals/engineering/run.py" --mode replay --repeats 2 --output "$tmp_root/engineering-eval.json" || fail 'ingestion and unrelated scheduler engineering replays'
pass 'Engineering models, atomic recovery, conformance, compaction and unrelated-domain replays'
python3 "$ROOT/tests/lifecycle.py" "$ROOT" "$candidate_v2" "$version_v2" "$candidate_v1" "$version_v1" "$tmp_root" || fail 'upgrade/reforge/migrate-runtime/rollback lifecycle integration'

python3 - "$ROOT" "$tmp_root/stats-sample.json" <<'PY' || fail 'native stats formatter'
import json,sys
from pathlib import Path
data={"range":{"from":1790000000000,"to":1791000000000},"sessions":2,"tokens":{"input":100,"output":30,"reasoning":5,"cache":{"read":10,"write":4}},"cost":0.25,"models":[{"model":{"providerID":"test","modelID":"fixture"},"steps":3,"tokens":{"input":100,"output":30,"reasoning":5,"cache":{"read":10,"write":4}},"cost":0.25}]}
Path(sys.argv[2]).write_text(json.dumps(data),encoding="utf-8")
PY
stats_output="$(python3 "$ROOT/scripts/stats.py" --days 7 < "$tmp_root/stats-sample.json")" || fail 'stats JSON formatter execution'
contains_stats="$(python3 -c 'import sys; print(int("total tokens    135" in sys.argv[1] and "test/fixture" in sys.argv[1]))' "$stats_output")"
[[ "$contains_stats" == 1 ]] || fail 'stats summary fields'
pass 'Native OpenCode statistics are rendered from structured JSON'

python3 - "$ANVIL_NETWORK_GUARD_LOG" <<'PY' || fail 'unexpected external network attempt in offline suite'
import sys
from pathlib import Path
path=Path(sys.argv[1])
assert not path.exists() or not path.read_text(encoding="utf-8").strip(), "offline suite attempted an external network connection"
PY
printf '\nAll Anvil offline checks passed.\n'
printf 'Isolation: runtime and lifecycle fixture calls used temporary HOME and XDG roots; no external runtime, Databricks, or model service was used.\n'
