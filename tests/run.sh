#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
if [[ $# -ne 3 ]]; then
  printf 'usage: tests/run.sh OPENCODE_1_CANDIDATE VERSION_1 TEMP_ROOT\n' >&2
  exit 2
fi
candidate_v1="$1"
version_v1="${2#opencode }"
version_v1="${version_v1#v}"
tmp_root="$3"
test_phase="${ANVIL_TEST_PHASE:-all}"
case "$test_phase" in
  all|core|lifecycle) ;;
  *) printf 'FAIL ANVIL_TEST_PHASE must be all, core, or lifecycle\n' >&2; exit 2 ;;
esac

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

if [[ "$test_phase" != lifecycle ]]; then
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

python3 - "$ROOT/scripts/version_docs.py" <<'PY' || fail 'release documentation contract'
import ast,sys
tree=ast.parse(open(sys.argv[1],encoding="utf-8").read())
docs=next(node.value for node in tree.body if isinstance(node,ast.Assign)
          and any(isinstance(target,ast.Name) and target.id=="DOCS" for target in node.targets))
assert len(docs.elts)==len({item.value for item in docs.elts})
PY
pass 'Core release documentation contract is unique'

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
assert "@bash scripts/upgrade.sh --update-runtime" in makefile, "OpenCode 1 runtime update target is missing"
for forbidden in ("install-opencode.sh", "opencode_release.py", "opencode_v1_release.py", "latest-version"):
    assert forbidden not in upgrade, f"Anvil-only upgrade imports runtime resolver/installer: {forbidden}"
doctor=(root/"scripts/doctor.sh").read_text(encoding="utf-8")
assert '"$ROOT/scripts/databricks.py" status' in doctor and "--format text" in doctor
assert "ANVIL_DOCTOR_LOCAL" in doctor, "doctor has no local-only mode for explicit local health checks"
for name in ("scripts/anvil_upgrade.sh", "scripts/reforge.sh", "scripts/upgrade.sh"):
    command=(root/name).read_text(encoding="utf-8")
    assert "lifecycle_verify.py" in command and 'bash "$ROOT/scripts/doctor.sh"' not in command, \
        f"{name} still uses human doctor as its transaction gate"
    assert "lifecycle_plan.py" in command and "anvil_lifecycle_execute" in command, \
        f"{name} bypasses the shared planning or transaction execution boundary"
    assert "anvil_lifecycle_validate_plan" in command and "change-plan.json" in command, \
        f"{name} does not hand its serialized ChangePlan to the lifecycle executor"
    assert "--render-file" in command, f"{name} does not render the accepted plan for dry-run UX"
runner=(root/"scripts/lib/lifecycle-operation.sh").read_text(encoding="utf-8")
assert "lifecycle_executor.py" in runner and '"$plan_file"' in runner, \
    "the shared transaction runner does not consume and validate the supplied ChangePlan"
rollback=(root/"scripts/rollback.sh").read_text(encoding="utf-8")
assert "lifecycle_plan.py" in rollback and "lifecycle_verify.py" in rollback, \
    "rollback does not plan the selected snapshot and structurally verify the restored state"
makefile=(root/"Makefile").read_text(encoding="utf-8")
for target in ("databricks-setup",):
    recipe=makefile.split(f"{target}:\n",1)[1].split("\n\n",1)[0]
    assert "lifecycle_plan.py" in recipe, f"{target} bypasses the lifecycle contributor planner"
assert "ANVIL_DOCTOR_LOCAL=1" in (root/"scripts/rehearse-upgrade.sh").read_text(encoding="utf-8"), \
    "isolated runtime rehearsal may contact a live Databricks workspace"
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

# The repository template contains a path placeholder; validate the generated
# native config so the audit sees the absolute knowledge Reference path used
# by an installation.
mkdir -p -- "$tmp_root/audit-home" "$tmp_root/audit-config" "$tmp_root/audit-data" "$tmp_root/audit-state"
env HOME="$tmp_root/audit-home" XDG_CONFIG_HOME="$tmp_root/audit-config" \
  XDG_DATA_HOME="$tmp_root/audit-data" XDG_STATE_HOME="$tmp_root/audit-state" ANVIL_ROOT="$ROOT" \
  bash -c 'source "$ANVIL_ROOT/scripts/lib/common.sh"; source "$ANVIL_ROOT/scripts/lib/install.sh"; anvil_build_config "$1" ""' \
  _ "$tmp_root/config-audit-ready" || fail 'build isolated config for audit'
python3 "$ROOT/scripts/configure.py" audit "$tmp_root/config-audit-ready/opencode.jsonc" || fail 'OpenCode 1 runtime config audit'
python3 "$ROOT/scripts/configure.py" audit "$ROOT/tests/fixtures/v1/opencode.jsonc" || fail 'V1 regression config fixture'
python3 "$ROOT/scripts/version_docs.py" || fail 'release documentation consistency'
python3 - "$ROOT/scripts/runtime.py" <<'PY' || fail 'runtime policy/capability adapters'
import importlib.util,sys
spec=importlib.util.spec_from_file_location("anvil_runtime",sys.argv[1])
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
policy=module.policy()["opencode"]
assert policy["supported_majors"]==[1] and policy["default_major"]==1
assert set(module.FEATURES)=={1}
PY
pass 'Runtime policy contains only the OpenCode 1 adapter'
python3 "$ROOT/tests/doctor_large_observation.py" || fail 'doctor must accept lifecycle observations larger than ARG_MAX'
python3 "$ROOT/tests/databricks.py" || fail 'Databricks offline integration and FinOps scenarios'
pass 'Databricks profiles, bounded execution, no-mutation policy, and FinOps evidence scenarios'
env ANVIL_DATABRICKS_CLI=/nonexistent/anvil-test-databricks \
  make --no-print-directory FORMAT=json capabilities > "$tmp_root/capabilities.json" || fail 'combined JSON capabilities'
python3 - "$tmp_root/capabilities.json" <<'PY' || fail 'capabilities output is not one valid runtime/Databricks JSON document'
import json,sys
data=json.load(open(sys.argv[1],encoding="utf-8"))
assert set(data) >= {"runtime","databricks","databricks_capabilities","communication","analysis"}
assert data["communication"]["status"] == "AVAILABLE"
assert "markdown_report" in data["communication"]["outputs"]["available"]
assert "pptx" in data["communication"]["outputs"]["unavailable"]
assert data["analysis"]["status"] == "AVAILABLE"
assert data["analysis"]["dependencies"] == {"required": [], "network": False, "persistent_state": False}
assert data["analysis"]["depths"]["FAST"]["max_operations"] == 4
assert data["databricks"]["overall"] == "NOT_CONFIGURED"
assert data["databricks"]["profile_configured"] is False
PY
pass 'make capabilities emits one combined machine-readable JSON document'
python3 - "$ROOT" "$tmp_root/config-audit-ready/opencode.jsonc" <<'PY' || fail 'OpenCode 1 profile invariants or secret scan'
import json,sys
from pathlib import Path
root=Path(sys.argv[1])
config=json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
agent=config["agent"]["anvil"]
assert config["default_agent"]=="anvil"
assert "model" not in agent and "small_model" not in agent
assert agent["mode"]=="primary" and agent["permission"]["*"]=="deny"
assert config["mcp"]=={} and config["plugin"]==[]
assert (Path(sys.argv[2]).parent/"plugins/anvil-core-v1.ts").is_file()
assert {p.stem for p in (root/"config/commands").glob("*.md")}=={"remember","recall","distill","review"}
assert {p.name for p in (root/"config/skills").iterdir()}=={"anvil-memory","anvil-spark-performance","anvil-delta-lake","anvil-databricks","anvil-data-ingestion","anvil-communication","anvil-engineering","anvil-system-design"}
plugin=(root/"config/plugins-v1/anvil-core.ts").read_text(encoding="utf-8")
assert "anvil_memory_search" in plugin and "ctx.tool.transform" not in plugin
assert "const optionalStr =" in plugin and "scope: optionalStr(100)" in plugin, \
    "Anvil memory search plugin references an undefined optional string schema helper"
for path in root.rglob("*"):
    if not path.is_file() or ".git" in path.parts or path.suffix in {".pyc", ".db", ".sqlite"}: continue
    content=path.read_bytes()
    assert b"-----BEGIN " + b"PRIVATE KEY-----" not in content, f"possible private key in {path}"
    assert b"gh" + b"p_" not in content, f"possible GitHub token in {path}"
PY
pass 'OpenCode 1 profile invariants, model neutrality, scoped plugin, and secret scan'

# Build the OpenCode 1 config and load the local runtime fixture under a clean
# HOME/XDG environment.
mkdir -p -- "$tmp_root/smoke-home" "$tmp_root/smoke-config" "$tmp_root/smoke-data" "$tmp_root/smoke-state"
env HOME="$tmp_root/smoke-home" XDG_CONFIG_HOME="$tmp_root/smoke-config" \
  XDG_DATA_HOME="$tmp_root/smoke-data" XDG_STATE_HOME="$tmp_root/smoke-state" ANVIL_ROOT="$ROOT" \
  bash -c 'source "$ANVIL_ROOT/scripts/lib/common.sh"; source "$ANVIL_ROOT/scripts/lib/install.sh"; anvil_build_config "$1" ""' \
  _ "$tmp_root/smoke-config-ready" || fail 'build isolated OpenCode config'
python3 "$ROOT/scripts/configure.py" audit "$tmp_root/smoke-config-ready/opencode.jsonc" || fail 'OpenCode 1 profile config smoke audit'
bash "$ROOT/scripts/validate-candidate.sh" "$candidate_v1" "$tmp_root/smoke-config-ready" "$version_v1" || fail 'OpenCode 1 candidate runtime smoke test'
pass "OpenCode 1 fixture $version_v1 loads Anvil config, agent, commands and skills"

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
python3 "$ROOT/tests/analysis.py" || fail 'intent and analytical intelligence offline contracts and regressions'
python3 "$ROOT/tests/communication.py" || fail 'communication/artifact intelligence offline contracts and regressions'
pass 'Communication and artifact intelligence runs deterministic offline regressions'
python3 "$ROOT/tests/engineering.py" || fail 'engineering state, interruption, stale evidence and direct-path regressions'
python3 "$ROOT/tests/local_evaluation.py" || fail 'local OpenCode evaluation policy and trace privacy regressions'
python3 "$ROOT/evals/engineering/run.py" --repeats 2 --output "$tmp_root/engineering-eval.json" || fail 'ingestion and unrelated scheduler engineering replays'
pass 'Engineering models, atomic recovery, conformance, compaction and unrelated-domain replays'
python3 "$ROOT/evals/engineering/adaptive.py" --output "$tmp_root/adaptive-eval.json" || fail 'task-local adaptive activation cases'
python3 - "$tmp_root/adaptive-eval.json" <<'PY' || fail 'adaptive execution route and selective architecture evidence comparison'
import json,sys
data=json.load(open(sys.argv[1],encoding="utf-8"))
metrics=data["metrics"]
assert metrics["adaptive_route_matches"] == metrics["cases"] == 18
assert metrics["direct_cases_false_expanded_after"] == 0
assert metrics["required_expansions_missed_after"] == 0
for result in data["long_horizon_replay_comparison"].values():
    assert result["adaptive"]["all_architecture_invariants_pass"]
    assert result["architecture_check_reduction_percent"] > 0
    assert result["state_write_delta"] == 0
PY
pass 'Adaptive activation separates task risk from project size and reuses valid scoped architecture evidence'
fi

if [[ "$test_phase" != core ]]; then
python3 "$ROOT/tests/lifecycle_model.py" || fail 'lifecycle state normalization'
python3 "$ROOT/tests/lifecycle_plan.py" || fail 'lifecycle planning'
python3 "$ROOT/tests/lifecycle_execution.py" || fail 'lifecycle plan execution contract'
python3 "$ROOT/tests/configure_first_install.py" || fail 'first-install configuration characterization'
python3 "$ROOT/tests/lifecycle.py" "$ROOT" "$ROOT/tests/fixtures/bin/opencode" "$version_v1" "$tmp_root" || fail 'OpenCode 1 upgrade/reforge/rollback lifecycle integration'
fi

if [[ "$test_phase" != lifecycle ]]; then
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
fi

python3 - "$ANVIL_NETWORK_GUARD_LOG" <<'PY' || fail 'unexpected external network attempt in offline suite'
import sys
from pathlib import Path
path=Path(sys.argv[1])
assert not path.exists() or not path.read_text(encoding="utf-8").strip(), "offline suite attempted an external network connection"
PY
printf '\nAll Anvil offline checks passed.\n'
printf 'Isolation: runtime and lifecycle fixture calls used temporary HOME and XDG roots; no external runtime, Databricks, or model service was used.\n'
