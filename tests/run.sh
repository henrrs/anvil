#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/scripts/lib/common.sh"
source "$ROOT/scripts/lib/install.sh"
source "$ROOT/scripts/lib/backup.sh"
export ANVIL_ROOT="$ROOT"

if [[ $# -ne 3 ]]; then
  printf 'usage: tests/run.sh CANDIDATE VERSION TEMP_ROOT\n' >&2
  exit 2
fi
candidate="$1"
version="${2#v}"
tmp_root="$3"

pass() { printf 'PASS  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*" >&2; exit 1; }

# Static and syntax checks do not access the user's OpenCode paths.
while IFS= read -r -d '' file; do bash -n "$file" || fail "Bash syntax: $file"; done < <(find "$ROOT/scripts" "$ROOT/tests" -type f -name '*.sh' -print0)
python3 - "$ROOT" <<'PY'
import ast,sys
from pathlib import Path
root=Path(sys.argv[1])
for path in root.rglob("*.py"):
    if ".git" not in path.parts:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
PY
pass 'Bash syntax and Python source parsing'

python3 - "$ROOT" <<'PY'
import json,sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
from configure import parse_jsonc, audit
root=Path(sys.argv[1])
required=(root/"config/AGENTS.md", root/"config/opencode.jsonc", root/"config/commands/remember.md", root/"config/commands/recall.md")
assert all(p.is_file() and p.stat().st_size for p in required)
for name in ("anvil-memory","anvil-spark-performance","anvil-delta-lake","anvil-databricks","anvil-data-ingestion"):
    path=root/"config/skills"/name/"SKILL.md"
    assert path.is_file() and path.stat().st_size
config=parse_jsonc((root/"config/opencode.jsonc").read_text(encoding="utf-8"))
assert not config.get("model") and not config.get("small_model")
assert "model" not in config["agent"]["anvil"] and "variant" not in config["agent"]["anvil"]
assert audit(root/"config/opencode.jsonc") == []
assert len(config["agent"]["anvil"]["permission"]["skill"]) == 6
for path in root.rglob("*"):
    if path.is_file() and path.suffix not in {".pyc"}:
        content=path.read_bytes()
        assert b"-----BEGIN " + b"PRIVATE KEY-----" not in content, f"possible private key in {path}"
        assert b"gh" + b"p_" not in content, f"possible GitHub token in {path}"
PY
pass 'Templates, config schema shape, model neutrality, and secret scan'

# OpenCode's actual debug output loads the staged config, lazy skills, commands and agents.
bash "$ROOT/scripts/validate-candidate.sh" "$candidate" "$ROOT/config" "$version"
pass "Actual OpenCode $version isolated config/agent/skill/command smoke test"

# Every lifecycle test runs with an isolated HOME and XDG roots.
fixture_root="$tmp_root/fixture-home with spaces"
fixture_config="$tmp_root/fixture-config with spaces"
fixture_data="$tmp_root/fixture-data with spaces"
fixture_state="$tmp_root/fixture-state with spaces"
mkdir -p "$fixture_root/.config/opencode/agents" "$fixture_root/.config/opencode/skills/legacy" \
  "$fixture_root/.config/opencode/plugins" "$fixture_root/.config/opencode/commands" \
  "$fixture_root/.opencode/bin" "$fixture_data/anvil/memory/company"
printf '%s\n' '{"provider":{"custom":{"name":"fixture"}},"model":"old/provider","agent":{"legacy":{"mode":"primary"}},"mcp":{"old":{"type":"remote","url":"https://example.invalid/mcp"}},"plugin":["old-plugin"]}' > "$fixture_root/.config/opencode/opencode.jsonc"
printf '%s\n' 'old global rules' > "$fixture_root/.config/opencode/AGENTS.md"
printf '%s\n' '{"tabs":{"mode":"off"}}' > "$fixture_root/.config/opencode/cli.json"
printf '%s\n' 'legacy skill' > "$fixture_root/.config/opencode/skills/legacy/SKILL.md"
printf '%s\n' 'legacy agent' > "$fixture_root/.config/opencode/agents/legacy.md"
printf '%s\n' 'legacy plugin' > "$fixture_root/.config/opencode/plugins/legacy.ts"
printf '%s\n' 'legacy command' > "$fixture_root/.config/opencode/commands/legacy.md"
cat > "$fixture_root/.opencode/bin/opencode" <<'FAKE'
#!/usr/bin/env bash
if [[ "${1:-}" == --version ]]; then printf '0.8.0\n'; elif [[ "${1:-}" == debug && "${2:-}" == paths ]]; then printf 'config      fixture\ndata        fixture\n'; fi
FAKE
chmod 755 "$fixture_root/.opencode/bin/opencode"
printf '%s\n' 'preserved outside Anvil memory' > "$fixture_data/anvil/memory/company/keep.md"
printf '%s\n' '{"version":"0.8.0","fixture":true}' > "$fixture_data/anvil/installation.json"
mkdir -p "$fixture_root/.bash-home"
printf '%s\n' '# fixture startup' > "$fixture_root/.bashrc"

fixture_path="$fixture_root/.opencode/bin:$PATH"
fixture_plan="$(HOME="$fixture_root" XDG_CONFIG_HOME="$fixture_root/.config" XDG_DATA_HOME="$fixture_data" XDG_STATE_HOME="$fixture_state" PATH="$fixture_path" python3 "$ROOT/scripts/path_edit.py" plan --home "$fixture_root" --xdg-config-home "$fixture_root/.config" --install-dir "$fixture_root/.opencode/bin" --shell /bin/bash --path "$fixture_path")"
fixture_backup="$(HOME="$fixture_root" XDG_CONFIG_HOME="$fixture_root/.config" XDG_DATA_HOME="$fixture_data" XDG_STATE_HOME="$fixture_state" PATH="$fixture_path" bash -c '
  source "$ANVIL_ROOT/scripts/lib/common.sh"
  source "$ANVIL_ROOT/scripts/lib/backup.sh"
  anvil_backup_create 1.19.0 "$1" | tail -n 1
' _ "$fixture_plan")"
HOME="$fixture_root" XDG_CONFIG_HOME="$fixture_root/.config" XDG_DATA_HOME="$fixture_data" XDG_STATE_HOME="$fixture_state" \
  python3 "$ROOT/scripts/state.py" verify "$fixture_backup" >/dev/null || fail 'backup verification'
[[ -f "$fixture_backup/config.tar.gz" && -f "$fixture_backup/opencode-root.tar.gz" && -f "$fixture_backup/manifest.json" && -f "$fixture_backup/inspect.txt" ]] || fail 'backup artifacts'
pass 'Dirty global fixture backed up and checksums verified'

# Build and apply twice; the managed tree must stay byte-for-byte stable.
idempotent_home="$tmp_root/idempotent-home"
idempotent_config="$tmp_root/idempotent-config"
idempotent_data="$tmp_root/idempotent-data"
idempotent_state="$tmp_root/idempotent-state"
mkdir -p "$idempotent_home" "$idempotent_config/opencode"
printf '%s\n' '{"provider":{"custom":{"name":"fixture"}},"model":"discard/me","mcp":{"old":{"type":"local","command":["ignored"]}}}' > "$idempotent_config/opencode/opencode.jsonc"
HOME="$idempotent_home" XDG_CONFIG_HOME="$idempotent_config" XDG_DATA_HOME="$idempotent_data" XDG_STATE_HOME="$idempotent_state" \
  bash -c '
    source "$ANVIL_ROOT/scripts/lib/common.sh"
    source "$ANVIL_ROOT/scripts/lib/install.sh"
    anvil_build_config "$1/one" "$ANVIL_CONFIG_DIR"
    anvil_apply_config "$1/one"
    python3 "$ANVIL_ROOT/scripts/configure.py" audit "$ANVIL_CONFIG_DIR/opencode.jsonc" >/dev/null
    cp -R "$ANVIL_CONFIG_DIR" "$1/snapshot"
    anvil_build_config "$1/two" "$ANVIL_CONFIG_DIR"
    anvil_apply_config "$1/two"
    python3 - "$1/snapshot" "$ANVIL_CONFIG_DIR" <<"PY"
import hashlib,sys
from pathlib import Path
def tree(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
assert tree(Path(sys.argv[1])) == tree(Path(sys.argv[2]))
PY
  ' _ "$tmp_root/idempotent-work" || fail 'idempotent config application'
pass 'Repeated config installation is byte-for-byte stable'

run_fixture_reforge() {
  local log="$1"
  ANVIL_TEST_MODE=1 ANVIL_TEST_CANDIDATE_BINARY="$candidate" ANVIL_YES=1 \
  HOME="$idempotent_home" XDG_CONFIG_HOME="$idempotent_config" XDG_DATA_HOME="$idempotent_data" \
  XDG_STATE_HOME="$idempotent_state" SHELL=/bin/bash PATH="$PATH" \
    bash "$ROOT/scripts/reforge.sh" > "$log" 2>&1 || {
      cat "$log" >&2
      return 1
    }
}
run_fixture_reforge "$tmp_root/reforge-one.log" || fail 'first fixture reforge'
python3 - "$idempotent_config/opencode/opencode.jsonc" "$tmp_root/reforge-one-tree.json" <<'PY'
import hashlib,json,stat,sys
from pathlib import Path
root=Path(sys.argv[1]).parent
def tree():
    return {str(p.relative_to(root)):{"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"mode":stat.S_IMODE(p.stat().st_mode)} for p in root.rglob("*") if p.is_file()}
Path(sys.argv[2]).write_text(json.dumps(tree(),sort_keys=True),encoding="utf-8")
config=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert config["provider"]["custom"]["name"] == "fixture"
assert "model" not in config and not config.get("mcp")
PY
run_fixture_reforge "$tmp_root/reforge-two.log" || fail 'second fixture reforge'
python3 - "$idempotent_config/opencode" "$tmp_root/reforge-one-tree.json" "$idempotent_home" <<'PY'
import hashlib,json,stat,sys
from pathlib import Path
root=Path(sys.argv[1])
def tree():
    return {str(p.relative_to(root)):{"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"mode":stat.S_IMODE(p.stat().st_mode)} for p in root.rglob("*") if p.is_file()}
assert tree() == json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")), "full reforge changed managed config on repeat"
startup=Path(sys.argv[3]) / ".bashrc"
assert startup.read_text(encoding="utf-8").count("# Anvil: OpenCode install directory") == 1
assert (Path(sys.argv[3]) / ".opencode/bin/opencode").is_file()
PY
pass 'Full reforge twice leaves equivalent managed config and a single PATH entry'

# Memory is read/search only until write-json is explicitly invoked.
memory_home="$tmp_root/memory-home"
memory_data="$tmp_root/memory-data"
mkdir -p "$memory_home"
env HOME="$memory_home" XDG_DATA_HOME="$memory_data" python3 "$ROOT/scripts/memory.py" init >/dev/null
empty_before="$(find "$memory_data/anvil/memory" -type f -name '*.md' | wc -l)"
set +e
env HOME="$memory_home" XDG_DATA_HOME="$memory_data" python3 "$ROOT/scripts/memory.py" search "unknown phrase" > "$tmp_root/empty-recall.txt"
empty_status=$?
set -e
[[ "$empty_status" -eq 1 && "$empty_before" -eq 0 && "$(find "$memory_data/anvil/memory" -type f -name '*.md' | wc -l)" -eq 0 ]] || fail 'memory search must not write entries'
cat <<'JSON' | env HOME="$memory_home" XDG_DATA_HOME="$memory_data" python3 "$ROOT/scripts/memory.py" write-json > "$tmp_root/memory-write.txt"
{"id":"databricks-secret-policy","type":"fact","scope":"company","tags":["databricks","security","secrets"],"source":{"type":"user-explicit","note":"User invoked remember"},"confidence":"confirmed","body":"In this company, do not use dbutils secrets get for Databricks credentials."}
JSON
env HOME="$memory_home" XDG_DATA_HOME="$memory_data" python3 "$ROOT/scripts/memory.py" recall "Databricks secrets" > "$tmp_root/recall.txt" || fail 'memory recall'
rg -q 'user-explicit|User invoked remember' "$tmp_root/recall.txt" || fail 'memory source provenance'
set +e
cat <<'JSON' | env HOME="$memory_home" XDG_DATA_HOME="$memory_data" python3 "$ROOT/scripts/memory.py" write-json > "$tmp_root/duplicate.txt" 2>&1
{"id":"another-secret-policy","type":"fact","scope":"company","tags":["databricks","security","secrets"],"source":{"type":"user-explicit"},"confidence":"confirmed","body":"In this company, do not use dbutils secrets get for Databricks credentials."}
JSON
duplicate_status=$?
set -e
[[ "$duplicate_status" -ne 0 ]] && rg -q 'possible duplicate' "$tmp_root/duplicate.txt" || fail 'duplicate-aware memory write'
cat <<'JSON' | env HOME="$memory_home" XDG_DATA_HOME="$memory_data" python3 "$ROOT/scripts/memory.py" write-json >/dev/null
{"id":"databricks-secret-policy","type":"fact","scope":"company","tags":["databricks","security","secrets"],"source":{"type":"user-explicit","note":"Updated by user"},"confidence":"confirmed","body":"Updated policy: do not use dbutils secrets get for Databricks credentials."}
JSON
rg -q '^created: ' "$memory_data/anvil/memory/company/databricks-secret-policy.md" || fail 'memory metadata'
[[ "$(stat -c '%a' "$memory_data/anvil/memory/company/databricks-secret-policy.md" 2>/dev/null || stat -f '%Lp' "$memory_data/anvil/memory/company/databricks-secret-policy.md")" == 600 ]] || fail 'private memory file mode'
pass 'Memory init, narrow recall, provenance, duplicate protection, atomic update, and no automatic writes'

# Exercise the real reforge transaction's post-backup failure path on a disposable HOME.
failure_home="$tmp_root/failure-home"
failure_config="$tmp_root/failure-config"
failure_data="$tmp_root/failure-data"
failure_state="$tmp_root/failure-state"
mkdir -p "$failure_home/.config/opencode" "$failure_home" "$failure_config" "$failure_data"
printf '%s\n' '{"model":"old/model","mcp":{"old":{"type":"remote","url":"https://example.invalid"}}}' > "$failure_home/.config/opencode/opencode.jsonc"
printf '%s\n' '# original startup' > "$failure_home/.bashrc"
before_config="$(anvil_sha256 "$failure_home/.config/opencode/opencode.jsonc")"
before_shell="$(anvil_sha256 "$failure_home/.bashrc")"
set +e
ANVIL_TEST_MODE=1 ANVIL_TEST_CANDIDATE_BINARY="$candidate" ANVIL_TEST_FAIL_AFTER_CONFIG=1 ANVIL_YES=1 \
HOME="$failure_home" XDG_CONFIG_HOME="$failure_home/.config" XDG_DATA_HOME="$failure_data" \
XDG_STATE_HOME="$failure_state" SHELL=/bin/bash PATH="$PATH" \
bash "$ROOT/scripts/reforge.sh" > "$tmp_root/failure-reforge.log" 2>&1
failure_status=$?
set -e
[[ "$failure_status" -ne 0 ]] || fail 'failure injection should fail reforge'
[[ "$(anvil_sha256 "$failure_home/.config/opencode/opencode.jsonc")" == "$before_config" ]] || fail 'automatic rollback of global config'
[[ "$(anvil_sha256 "$failure_home/.bashrc")" == "$before_shell" ]] || fail 'automatic rollback of shell startup'
[[ ! -e "$failure_home/.opencode/bin/opencode" ]] || fail 'automatic rollback of staged executable'
rg -q 'Automatic rollback completed' "$tmp_root/failure-reforge.log" || fail 'automatic rollback report'
pass 'Injected post-backup failure automatically restored the dirty fixture'

# Verify manual rollback on the separate dirty fixture and memory retention.
fixture_current="$fixture_root/.config/opencode"
fixture_target="$tmp_root/manual-new-config"
HOME="$fixture_root" XDG_CONFIG_HOME="$fixture_root/.config" XDG_DATA_HOME="$fixture_data" XDG_STATE_HOME="$fixture_state" \
  bash -c '
    source "$ANVIL_ROOT/scripts/lib/common.sh"
    source "$ANVIL_ROOT/scripts/lib/install.sh"
    anvil_build_config "$1" "$ANVIL_CONFIG_DIR"
    anvil_apply_config "$1"
  ' _ "$fixture_target"
ANVIL_INTERNAL_MODE=1 HOME="$fixture_root" XDG_CONFIG_HOME="$fixture_root/.config" XDG_DATA_HOME="$fixture_data" \
XDG_STATE_HOME="$fixture_state" PATH="$fixture_path" bash "$ROOT/scripts/rollback.sh" --backup "$fixture_backup" --internal > "$tmp_root/manual-rollback.txt"
rg -q 'old global rules' "$fixture_current/AGENTS.md" || fail 'manual rollback restored config'
rg -q 'legacy' "$fixture_current/skills/legacy/SKILL.md" || fail 'manual rollback restored legacy skill'
rg -q 'preserved outside Anvil memory' "$fixture_data/anvil/memory/company/keep.md" || fail 'rollback preserves Anvil memory'
[[ -f "$fixture_current/cli.json" && -x "$fixture_root/.opencode/bin/opencode" ]] || fail 'rollback restored CLI and installer state'
pass 'Manual rollback restored config, CLI settings, prior executable, and retained memory'

printf '\nAll Anvil checks passed.\n'
printf 'Isolation: fixture OpenCode state used HOME=%s; real HOME=%s was not passed to lifecycle or smoke commands.\n' "$fixture_root" "${HOME:-unset}"
