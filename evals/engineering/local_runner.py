#!/usr/bin/env python3
"""Live engineering evaluation through the user's installed OpenCode profile."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "evals/engineering"))

from engineering.repository import identity, no_symlinks  # noqa: E402
from harness import prepare_model  # noqa: E402
import run as _run  # noqa: E402

LIVE_FIXTURES = ("retry-policy", "refactor", "ingestion", "queue-preview", "long-horizon", "context-recovery", "fast-control")
FAST_FIXTURE = "fast-control"

TREATMENTS = ("native-opencode", "anvil-active")
DEFAULT_MODEL = "openai/gpt-6-luna"
DEFAULT_VARIANT = "high"
DEFAULT_BENCHMARKS = ROOT / "evals/engineering/benchmarks.json"
EVALUATION_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")
RESOURCE_BUDGET = {
    "max_challenge_sessions": 23,
    "max_resume_invocations": 3,
    "max_cli_invocations_including_resume": 26,
    "max_smoke_invocations": 1,
    "max_cli_invocations_total": 27,
    "concurrency": 1,
    "repetitions_per_treatment": 1,
    "max_agent_steps_per_invocation": 12,
    "max_context_tokens": 32768,
    "max_output_tokens_per_response": 2048,
    "max_wall_seconds_per_invocation": 600,
    "max_global_wall_seconds": 18000,
    "max_stdout_event_bytes_per_invocation": 10485760,
    "max_tool_output_bytes": 40000,
    "max_total_input_tokens": 10256384,
    "max_total_output_tokens": 641024,
}


class EvaluationBlocked(RuntimeError):
    pass


def new_evaluation_id() -> str:
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return f"anvil-engineering-{timestamp}-{uuid.uuid4().hex[:8]}"


def evaluation_data_directory(evaluation_id: str) -> pathlib.Path:
    if not EVALUATION_ID_PATTERN.fullmatch(evaluation_id) or evaluation_id in {".", ".."}:
        raise EvaluationBlocked("Evaluation ID must use only letters, digits, dots, underscores, and hyphens")
    state_home = pathlib.Path(os.environ.get("XDG_STATE_HOME") or
                              str(pathlib.Path.home() / ".local/state")).expanduser()
    if not state_home.is_absolute():
        raise EvaluationBlocked("XDG_STATE_HOME must be an absolute path for evaluation records")
    directory = state_home / "anvil" / "evaluations" / "engineering" / evaluation_id
    if directory.resolve().is_relative_to(ROOT):
        raise EvaluationBlocked("Evaluation budgets and results must remain outside the Anvil repository")
    if directory.is_symlink():
        raise EvaluationBlocked("Evaluation data directory cannot be a symbolic link")
    if directory.exists() and not directory.is_dir():
        raise EvaluationBlocked("Evaluation data path exists and is not a directory")
    return directory


def configure_evaluation_paths(args) -> pathlib.Path:
    if not args.evaluation_id:
        if args.mode != "smoke":
            raise EvaluationBlocked("Start with MODE=smoke to create an evaluation ID, then pass EVALUATION_ID to later runs")
        args.evaluation_id = new_evaluation_id()
    directory = evaluation_data_directory(args.evaluation_id)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    defaults = {"budget_config": directory / "budget.json",
                "budget_state": directory / "budget-state.json",
                "output": directory / "results.json"}
    for name, default in defaults.items():
        path = getattr(args, name) or default
        path = path.expanduser()
        resolved = path.resolve()
        if resolved.is_relative_to(ROOT):
            raise EvaluationBlocked("Evaluation budgets and results must remain outside the Anvil repository")
        setattr(args, name, path)
    args.benchmark_manifest = (args.benchmark_manifest or DEFAULT_BENCHMARKS).expanduser()
    return directory


def create_budget_config(path: pathlib.Path, evaluation_id: str, executable: pathlib.Path,
                         runtime: dict, model: str, variant: str, manifest: pathlib.Path) -> None:
    config = {
        "schema_version": 1,
        "evaluation_id": evaluation_id,
        "benchmarks_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "runtime": {"executable": str(executable), "version": runtime["version"], "major": 1,
                    "provider": model.split("/", 1)[0], "model": model, "variant": variant,
                    "fallback": False},
        "resource_budget": RESOURCE_BUDGET,
    }
    _run.write_json_atomic(path, config)


def child_env(**extra: str) -> dict[str, str]:
    """Keep the user's HOME/XDG/provider environment for OpenCode itself."""
    result = os.environ.copy()
    result["NO_COLOR"] = "1"
    result.update(extra)
    return result


def metadata_env(temp_root: pathlib.Path) -> dict[str, str]:
    """Use the real profile but keep auth, runtime data, and state out of metadata probes."""
    allowed = {
        "PATH", "HOME", "XDG_CONFIG_HOME", "XDG_CONFIG_DIRS", "LANG", "LC_ALL",
        "LC_MESSAGES", "TERM", "TMPDIR", "SHELL", "OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR",
    }
    result = {key: os.environ[key] for key in allowed if key in os.environ}
    result.update({
        "NO_COLOR": "1",
        "OPENCODE_DISABLE_AUTOUPDATE": "1",
        "XDG_DATA_HOME": str(temp_root / "data"),
        "XDG_STATE_HOME": str(temp_root / "state"),
        "XDG_CACHE_HOME": str(temp_root / "cache"),
    })
    for name in ("data", "state", "cache"):
        (temp_root / name).mkdir(mode=0o700)
    return result


def invoke_metadata(opencode: pathlib.Path, args: list[str], cwd: pathlib.Path,
                    timeout: int = 30, *, pure: bool = False) -> tuple[int, str]:
    try:
        with tempfile.TemporaryDirectory(prefix="anvil-opencode-metadata-") as raw:
            env = metadata_env(pathlib.Path(raw))
            result = subprocess.run([str(opencode), *( ["--pure"] if pure else []), *args], cwd=cwd, env=env,
                                    capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise EvaluationBlocked(f"OpenCode metadata command timed out: {args[0]}") from None
    except OSError as error:
        raise EvaluationBlocked(f"OpenCode metadata command could not start: {type(error).__name__}") from None
    return result.returncode, result.stdout


def _agent_instruction_digest(raw: str) -> str | None:
    """Fingerprint the resolved agent content without retaining user instruction text."""
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(value, dict):
        return None
    content = {key: item for key, item in value.items()
               if key not in {"permission", "steps", "tools", "disable"}}
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _agent_has_instruction_payload(raw: str) -> bool:
    try:
        value = json.loads(raw)
    except ValueError:
        return False
    instruction_keys = {"prompt", "instruction", "instructions", "system"}
    def visit(item) -> bool:
        if isinstance(item, dict):
            return any((str(key).lower() in instruction_keys and isinstance(child, str) and child.strip()) or visit(child)
                       for key, child in item.items())
        if isinstance(item, list):
            return any(visit(child) for child in item)
        return False
    return visit(value)


def _resolved_anvil_tools(raw: str) -> list[str]:
    try:
        value = json.loads(raw)
    except ValueError:
        return []
    tools = value.get("tools") if isinstance(value, dict) else None
    if not isinstance(tools, dict):
        return []
    return sorted(str(name) for name, enabled in tools.items()
                  if enabled is True and re.match(r"(?i)^anvil[_-]", str(name)))


def anvil_inventory(opencode: pathlib.Path, cwd: pathlib.Path) -> dict:
    """Verify components OpenCode resolves without requesting the full provider config."""
    agent_code, agent_output = invoke_metadata(opencode, ["debug", "agent", "anvil"], cwd)
    agent_definition_sha256 = _agent_instruction_digest(agent_output) if agent_code == 0 else None
    agent_has_instructions = agent_code == 0 and _agent_has_instruction_payload(agent_output)
    agent_plugin_tools = _resolved_anvil_tools(agent_output) if agent_code == 0 else []
    skill_code, skill_output = invoke_metadata(opencode, ["debug", "skill"], cwd)
    if skill_code != 0:
        skill_output = ""
    skills = sorted(set(re.findall(r"\banvil-[a-z0-9][a-z0-9-]{0,79}\b", skill_output.lower())))
    config_home = pathlib.Path(os.environ.get(
        "XDG_CONFIG_HOME", str(pathlib.Path.home() / ".config"))).expanduser() / "opencode"
    agents_file = config_home / "AGENTS.md"
    agents_file_mentions_anvil = False
    try:
        if agents_file.is_file() and agents_file.stat().st_size <= 1_048_576:
            agents_file_mentions_anvil = "anvil" in agents_file.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        pass
    agent_resolves = agent_code == 0 and bool(agent_output.strip())
    instruction_source_resolves = (agents_file_mentions_anvil or
                                   (agent_resolves and agent_has_instructions))
    anvil_plugin = bool(agent_plugin_tools)
    return {
        "anvil_agent_resolves": agent_resolves,
        "anvil_agent_definition_sha256": agent_definition_sha256,
        "anvil_instruction_source_resolves": instruction_source_resolves,
        "anvil_agent_instructions_present": agent_has_instructions,
        "anvil_plugin_configured": anvil_plugin,
        "anvil_plugin_tools_resolve": agent_plugin_tools,
        "anvil_skill_ids": skills,
        "anvil_instruction_reference_configured": False,
        "global_agents_file_present": agents_file.is_file(),
        "global_agents_mentions_anvil": agents_file_mentions_anvil,
        "agent_count": None,
        "plugin_count": 1 if anvil_plugin else 0,
        "skill_inspection_succeeded": skill_code == 0,
        "active_anvil_verified": bool(agent_resolves and anvil_plugin and agent_plugin_tools and skills and instruction_source_resolves),
    }


def local_runtime_preflight(opencode: pathlib.Path, cwd: pathlib.Path, model: str) -> dict:
    try:
        with tempfile.TemporaryDirectory(prefix="anvil-opencode-version-") as raw:
            version_result = subprocess.run([str(opencode), "--version"], cwd=cwd, env=metadata_env(pathlib.Path(raw)),
                                            capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise EvaluationBlocked(f"OpenCode executable preflight failed: {type(error).__name__}") from None
    version = version_result.stdout.strip().splitlines()[0] if version_result.stdout.strip() else None
    if version_result.returncode != 0 or not version:
        raise EvaluationBlocked("The OpenCode executable in the local environment is not usable")
    match = re.match(r"(?i)^(?:opencode\s+)?v?(\d+)\.", version)
    if not match or int(match.group(1)) != 1:
        raise EvaluationBlocked(f"The live Evaluation Lab supports OpenCode 1.x only; found {version}")
    return {"executable": opencode.name, "version": version, "model": model,
            "variant": "high", "path_source": "explicit path" if opencode != pathlib.Path(shutil.which("opencode") or "").resolve() else "PATH",
            "home_xdg_overridden": False, "credentials_read_or_copied": False,
            "model_confirmation": "The actual Luna 6 High smoke must succeed before any challenge is allowed."}


def _permissions(project: pathlib.Path, agent: str, shell: pathlib.Path | None,
                 allowed_external: list[pathlib.Path], state_root: pathlib.Path | None,
                 *, smoke: bool = False) -> dict:
    project = project.resolve()
    deny = {"*": "deny"}
    permission = dict(deny)
    if smoke:
        return {"permission": permission,
                "agent": {agent: {"disable": False, "steps": 1, "permission": dict(deny)}}}

    external = {"*": "deny"}
    for path in allowed_external:
        external[str(path.resolve()) + "/**"] = "allow"
        external[str(path.resolve())] = "allow"
    if state_root:
        external[str(state_root.resolve()) + "/**"] = "allow"

    # OpenCode V1's apply_patch permission check uses project-relative paths.
    # Allow those paths, explicitly deny edits to readable Anvil references,
    # then re-allow only the fixture and its isolated task-state subtree.
    scoped_write = {"*": "deny", "**": "allow"}
    for path in allowed_external:
        external_path = str(path.resolve())
        scoped_write[external_path] = "deny"
        scoped_write[external_path + "/**"] = "deny"
    if state_root:
        state_path = str(state_root.resolve())
        scoped_write[state_path] = "allow"
        scoped_write[state_path + "/**"] = "allow"
    project_path = str(project.resolve())
    scoped_write[project_path] = "allow"
    scoped_write[project_path + "/**"] = "allow"
    scoped_write[project_path + "/opencode.json"] = "deny"
    scoped_write["opencode.json"] = "deny"
    scoped_write[project_path + "/.git"] = "deny"
    scoped_write[project_path + "/.git/**"] = "deny"
    scoped_write[".git"] = "deny"
    scoped_write[".git/**"] = "deny"
    # apply_patch resolves paths relative to the OpenCode worktree. Every
    # target outside this project therefore begins with ../ after resolution.
    # Keep readable Anvil references immutable even though external_directory
    # allows the agent to read those specific roots.
    scoped_write["../**"] = "deny"

    permission.update({
        "read": "allow", "glob": "allow", "grep": "allow", "list": "allow",
        "write": dict(scoped_write), "edit": dict(scoped_write),
        "bash": "allow" if shell else "deny",
        "external_directory": external,
        "skill": {"*": "deny", "anvil-*": "allow"} if agent == "anvil" else "deny",
        "task": "deny", "question": "deny", "webfetch": "deny", "websearch": "deny",
        "todowrite": "deny", "todoread": "deny",
        "anvil_memory_search": "deny",
    })
    agent_permission = dict(permission)
    config = {"$schema": "https://opencode.ai/config.json", "permission": permission,
              "agent": {agent: {"disable": False, "steps": 12, "permission": agent_permission}}}
    if shell:
        config["shell"] = str(shell.resolve())
    return config


def _write_project_config(project: pathlib.Path, config: dict) -> pathlib.Path:
    path = project / "opencode.json"
    if path.exists() or path.is_symlink():
        raise EvaluationBlocked("The fixture already contains opencode.json; refusing to replace it")
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def _native_agent_baseline(opencode: pathlib.Path, run_root: pathlib.Path, agent: str) -> str:
    """Resolve the built-in agent with only its global disable flag overridden locally."""
    probe = run_root / "native-agent-baseline"
    probe.mkdir(mode=0o700)
    _write_project_config(probe, {"$schema": "https://opencode.ai/config.json",
                                  "agent": {agent: {"disable": False}}})
    code, output = invoke_metadata(opencode, ["debug", "agent", agent], probe, pure=True)
    digest = _agent_instruction_digest(output) if code == 0 else None
    if not digest:
        raise EvaluationBlocked("OpenCode's built-in native agent could not be resolved safely")
    return digest


def _agent_metadata(raw: str) -> dict:
    try:
        value = json.loads(raw)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _resolved_permission_rules(agent: dict) -> set[tuple[str, str, str]]:
    """Return only permission names, patterns, and actions from OpenCode metadata."""
    value = agent.get("permission")
    rules: set[tuple[str, str, str]] = set()
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            permission, pattern, action = (item.get("permission"), item.get("pattern"), item.get("action"))
            if all(isinstance(part, str) for part in (permission, pattern, action)):
                rules.add((permission, pattern, action))
    elif isinstance(value, dict):
        for permission, policy in value.items():
            if isinstance(policy, str):
                rules.add((str(permission), "*", policy))
            elif isinstance(policy, dict):
                for pattern, action in policy.items():
                    if isinstance(action, str):
                        rules.add((str(permission), str(pattern), action))
    return rules


def _configured_permission_rules(permission: dict) -> set[tuple[str, str, str]]:
    rules: set[tuple[str, str, str]] = set()
    for name, policy in permission.items():
        # Skill patterns can be expanded into individual skill IDs by V1 and
        # plugin tool globs can be expanded by either runtime. The local
        # project file is checked separately; active tool state is checked
        # from debug-agent metadata below.
        if name == "skill" or str(name).startswith("anvil_"):
            continue
        if isinstance(policy, str):
            rules.add((str(name), "*", policy))
        elif isinstance(policy, dict):
            for pattern, action in policy.items():
                if isinstance(action, str):
                    rules.add((str(name), str(pattern), action))
    return rules


def _verify_overlay(opencode: pathlib.Path, project: pathlib.Path, agent: str,
                    shell: pathlib.Path | None, baseline_agent_digest: str | None,
                    read_roots: list[pathlib.Path], state_root: pathlib.Path | None,
                    *, pure: bool = False) -> dict:
    overlay_path = project / "opencode.json"
    try:
        overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise EvaluationBlocked("The disposable project permission overlay could not be read") from None
    local_agent = overlay.get("agent", {}).get(agent, {}) if isinstance(overlay, dict) else {}
    permission = local_agent.get("permission") if isinstance(local_agent, dict) else None
    global_permission = overlay.get("permission") if isinstance(overlay, dict) else None
    if not isinstance(permission, dict) or not isinstance(global_permission, dict):
        raise EvaluationBlocked("The disposable project permission overlay has an unsupported shape")
    agent_code, agent_output = invoke_metadata(opencode, ["debug", "agent", agent], project, pure=pure)
    resolved_agent = _agent_metadata(agent_output) if agent_code == 0 else {}
    overlay_agent_digest = _agent_instruction_digest(agent_output) if agent_code == 0 else None
    resolved_rules = _resolved_permission_rules(resolved_agent)
    expected_rules = _configured_permission_rules(permission)
    external = permission.get("external_directory", {})
    edit = permission.get("edit", {}) if isinstance(permission.get("edit"), dict) else {}
    if not isinstance(edit, dict):
        edit = {}
    project_path = str(project.resolve())
    readable_edits_denied = all(
        edit.get(str(path.resolve())) == "deny" and edit.get(str(path.resolve()) + "/**") == "deny"
        for path in read_roots
    )
    resolved_tools = resolved_agent.get("tools") if isinstance(resolved_agent.get("tools"), dict) else {}
    active_anvil_tools = [name for name, enabled in resolved_tools.items()
                          if str(name).startswith("anvil_") and enabled is True]
    if ("provider" in overlay or global_permission.get("*") != "deny" or
            permission.get("bash") != ("allow" if shell else "deny") or
            permission.get("*") != "deny" or permission.get("task") != "deny" or
            permission.get("anvil_memory_search") != "deny" or
            not isinstance(external, dict) or external.get("*") != "deny" or
            not expected_rules.issubset(resolved_rules) or
            (agent == "anvil" and (not resolved_tools or active_anvil_tools)) or
            edit.get("*") != "deny" or edit.get("**") != "allow" or
            edit.get(project_path) != "allow" or edit.get(project_path + "/**") != "allow" or
            edit.get(project_path + "/opencode.json") != "deny" or edit.get("opencode.json") != "deny" or
            edit.get(project_path + "/.git/**") != "deny" or edit.get(".git/**") != "deny" or
            edit.get("../**") != "deny" or not readable_edits_denied or
            (state_root and (edit.get(str(state_root.resolve())) != "allow" or
                             edit.get(str(state_root.resolve()) + "/**") != "allow")) or
            local_agent.get("disable") is True or
            (shell and overlay.get("shell") != str(shell.resolve())) or
            not baseline_agent_digest or overlay_agent_digest != baseline_agent_digest):
        raise EvaluationBlocked("OpenCode did not resolve the fixture-only permission overlay")
    return {"project_overlay_resolved": True, "provider_config_overridden": False,
            "home_xdg_overridden": False, "external_directory_default": external.get("*"),
            "agent_instruction_digest_preserved": True,
            "project_relative_patch_allowed": edit.get("**") == "allow",
            "read_only_anvil_paths_remain_immutable": readable_edits_denied,
            "plugin_tools_allowed": False,
            "agent_definition_sha256": overlay_agent_digest}


def _local_paths(project: pathlib.Path, run_root: pathlib.Path, agent: str
                 ) -> tuple[pathlib.Path | None, list[pathlib.Path], pathlib.Path | None]:
    if agent != "anvil":
        return None, [], None
    home = pathlib.Path.home().resolve()
    config_value = os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))
    if not pathlib.Path(config_value).expanduser().is_absolute():
        raise EvaluationBlocked("The existing XDG config path must be absolute for a safely scoped Anvil run")
    config_home = pathlib.Path(config_value).expanduser().absolute()
    no_symlinks(config_home)
    anvil_config = config_home / "opencode"
    if anvil_config.exists():
        no_symlinks(anvil_config)
        anvil_config = anvil_config.absolute()
    script_root = anvil_config / "scripts"
    repo_id = identity(project)["id"]
    state_home = run_root / "anvil-state-home"
    state_root = state_home / "anvil" / "engineering" / repo_id
    no_symlinks(state_root)
    state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_home.chmod(0o700)
    state_root.chmod(0o700)
    readable = [path for path in (script_root / "engineering.py", script_root / "engineering") if path.exists()]
    skill_root = anvil_config / "skills"
    if skill_root.is_dir():
        readable.extend(path for path in sorted(skill_root.glob("anvil-*")) if path.is_dir())
    for path in readable:
        no_symlinks(path)
        if not path.resolve().is_relative_to(anvil_config):
            raise EvaluationBlocked("Anvil skill/helper path escaped the configured OpenCode directory")
    return state_root, readable, state_home


def _build_shell(args, run_root: pathlib.Path) -> pathlib.Path:
    tools = run_root / "tools"
    tools.mkdir(mode=0o700)
    shell = tools / "local-landlock-shell"
    compiler = shutil.which("cc") or shutil.which("gcc")
    if not compiler:
        raise EvaluationBlocked("A C compiler is needed for fixture-scoped shell permissions")
    try:
        subprocess.run([compiler, "-O2", "-Wall", "-Wextra", "-Werror",
                        str(ROOT / "evals/engineering/local_landlock_shell.c"), "-o", str(shell)],
                       capture_output=True, timeout=45, check=True)
    except (OSError, subprocess.SubprocessError) as error:
        raise EvaluationBlocked(f"The fixture-scoped shell could not be built: {type(error).__name__}") from None
    shell.chmod(0o500)
    return shell


def _ensure_temp_root(path: pathlib.Path) -> pathlib.Path:
    temp_root = pathlib.Path(tempfile.gettempdir()).resolve()
    absolute = path.absolute()
    if ".." in absolute.parts:
        raise EvaluationBlocked("Evaluation run directories cannot contain parent traversal")
    try:
        canonical = absolute.resolve()
        canonical.relative_to(temp_root)
    except ValueError:
        raise EvaluationBlocked("Evaluation run directories must remain under the system temporary directory") from None
    for item in (absolute, *absolute.parents):
        if item.is_symlink():
            raise EvaluationBlocked("Evaluation run directories must not traverse symlinks")
    if canonical.exists():
        raise EvaluationBlocked(f"Refusing to reuse an existing evaluation directory: {canonical}")
    if not canonical.parent.is_dir():
        raise EvaluationBlocked("The parent of an explicit evaluation directory must already exist")
    canonical.mkdir(mode=0o700)
    canonical.chmod(0o700)
    return canonical


def _require_smoke_passed(state_path: pathlib.Path) -> None:
    if not state_path.is_file():
        raise EvaluationBlocked("Run the local OpenCode smoke first; no successful smoke is recorded")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    smoke = [row for row in state.get("invocations", []) if row.get("kind") == "smoke"]
    if not smoke or smoke[-1].get("status") != "COMPLETED" or not smoke[-1].get("response_and_telemetry"):
        raise EvaluationBlocked("Local OpenCode smoke has not completed with response and telemetry; stop before benchmarks")


def _require_minimal_challenge_passed(results_path: pathlib.Path, treatment: str) -> None:
    if not results_path.is_file():
        raise EvaluationBlocked("Run and independently pass the disposable fast-control challenge before the full suite")
    report = json.loads(results_path.read_text(encoding="utf-8"))
    passed = any(row.get("fixture") == FAST_FIXTURE and row.get("treatment") == treatment and
                 row.get("execution_status") == "COMPLETED" and row.get("acceptance") == "PASS"
                 for row in report.get("results", []))
    if not passed:
        raise EvaluationBlocked("The fast-control challenge has not passed the independent grader for this treatment")


def _run_smoke(args, opencode: pathlib.Path) -> dict:
    run_root = args.workspace_root / "smoke" / "local-runtime"
    if run_root.exists():
        raise EvaluationBlocked(f"Refusing to reuse an existing smoke directory: {run_root}")
    run_root.mkdir(parents=True, mode=0o700)
    run_root.chmod(0o700)
    project = run_root / "project"
    project.mkdir(mode=0o700)
    agent = "build"
    _write_project_config(project, _permissions(project, agent, None, [], None, smoke=True))
    try:
        overlay = json.loads((project / "opencode.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise EvaluationBlocked("Smoke project permission overlay could not be read") from None
    agent_code, agent_output = invoke_metadata(opencode, ["debug", "agent", agent], project)
    resolved_agent = _agent_metadata(agent_output) if agent_code == 0 else {}
    if (overlay.get("permission", {}).get("*") != "deny" or
            overlay.get("agent", {}).get(agent, {}).get("permission", {}).get("*") != "deny" or
            ("*", "*", "deny") not in _resolved_permission_rules(resolved_agent)):
        raise EvaluationBlocked("Smoke project did not deny every OpenCode tool")
    prompt = "Reply with exactly READY. Do not call tools."
    argv = [str(opencode), "run", "--format", "json", "--agent", agent, "--model", args.model,
            "--variant", args.variant, "--title", f"{args.evaluation_id} local smoke", prompt]
    diagnostic_since = time.time()
    metrics, code, elapsed = _run.run_cli_invocation(
        args, argv, project, child_env(), min(args.timeout, 120), args.stdout_limit,
        run_root / "trace-metadata.jsonl", "local-runtime-smoke", "smoke")
    home = pathlib.Path(os.environ.get("HOME", pathlib.Path.home()))
    xdg_data = pathlib.Path(os.environ.get("XDG_DATA_HOME", home / ".local/share"))
    xdg_state = pathlib.Path(os.environ.get("XDG_STATE_HOME", home / ".local/state"))
    xdg_cache = pathlib.Path(os.environ.get("XDG_CACHE_HOME", home / ".cache"))
    _run.augment_runtime_diagnostics(metrics, home, xdg_data, xdg_state, xdg_cache,
                                     since_epoch=diagnostic_since)
    usage = metrics.get("token_usage") or {}
    telemetry = bool(usage or metrics.get("reported_cost_telemetry") is not None)
    response = bool(metrics.get("text_chars_observed"))
    passed = bool(code == 0 and response and telemetry and not metrics.get("failure_class") and not metrics.get("limit"))
    record = {"status": "COMPLETED" if passed else "START_OR_RUN_FAILED",
              "response_and_telemetry": passed, "response_received": response,
              "telemetry_available": telemetry, "exit_code": code, "elapsed_seconds": elapsed,
              "event_types": metrics.get("event_types"), "token_usage": usage or None,
              "reported_cost_telemetry": metrics.get("reported_cost_telemetry"),
              "failure_class": metrics.get("failure_class"), "failure_stage": metrics.get("failure_stage"),
              "provider_category": metrics.get("provider_category"), "error_type": metrics.get("error_type"),
              "error_code": metrics.get("error_code"), "http_status": metrics.get("http_status"),
              "retry_count": metrics.get("retry_count"), "safe_trace": str(run_root / "trace-metadata.jsonl"),
              "private_reasoning_logged": False, "credentials_read_or_copied": False}
    return record


def _record_smoke(args, result: dict) -> None:
    """Enrich the reserved call record without charging the invocation twice."""
    state = json.loads(args.budget_state.read_text(encoding="utf-8")) if args.budget_state.exists() else {
        "schema_version": 1, "invocations": [], "challenge_keys": [], "resume_keys": [],
        "actual_wall_seconds": 0, "reserved_wall_seconds": 0,
        "actual_input_tokens": 0, "actual_output_tokens": 0,
        "reserved_input_tokens": 0, "reserved_output_tokens": 0,
    }
    if state.get("evaluation_id") not in (None, args.evaluation_id):
        raise EvaluationBlocked("Evaluation ID does not match the smoke budget state")
    state["evaluation_id"] = args.evaluation_id
    row = next((item for item in state["invocations"] if item.get("key") == "local-runtime-smoke"), None)
    if row is None:
        row = {"index": len(state["invocations"]) + 1, "key": "local-runtime-smoke", "kind": "smoke"}
        state["invocations"].append(row)
        state["actual_wall_seconds"] = state.get("actual_wall_seconds", 0) + result["elapsed_seconds"]
        usage = result.get("token_usage") or {}
        state["actual_input_tokens"] = state.get("actual_input_tokens", 0) + (usage.get("input") or 0)
        state["actual_output_tokens"] = state.get("actual_output_tokens", 0) + (usage.get("output") or 0)
    row.update({"kind": "smoke", "status": result["status"],
                "elapsed_seconds": result["elapsed_seconds"],
                "observed_input_tokens": (result.get("token_usage") or {}).get("input"),
                "observed_output_tokens": (result.get("token_usage") or {}).get("output"),
                "response_and_telemetry": result["response_and_telemetry"],
                "response_received": result["response_received"],
                "token_telemetry_available": result["telemetry_available"],
                "reported_cost_telemetry": result.get("reported_cost_telemetry"),
                "failure_class": result.get("failure_class"), "exit_code": result.get("exit_code")})
    _run.write_json_atomic(args.budget_state, state)


def _grade(project: pathlib.Path, grader: pathlib.Path) -> dict:
    grader_env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(project), "PYTHONDONTWRITEBYTECODE": "1",
                  "HOME": str(project), "NO_COLOR": "1"}
    try:
        result = subprocess.run([sys.executable, str(grader), "all"], cwd=project, env=grader_env,
                                capture_output=True, timeout=60, check=False)
        output = result.stdout + b"\n" + result.stderr
        return {"status": "PASS" if result.returncode == 0 else "FAIL", "exit_code": result.returncode,
                "diagnostics_bytes": len(output), "diagnostics_sha256": hashlib.sha256(output).hexdigest(),
                "diagnostics_private": True, "raw_diagnostics_retained": False}
    except subprocess.TimeoutExpired:
        return {"status": "TIMEOUT", "exit_code": None, "raw_diagnostics_retained": False}


def _challenge(args, opencode: pathlib.Path, name: str, treatment: str) -> dict:
    run_root = args.workspace_root / treatment / f"{name}-01"
    if run_root.exists():
        raise EvaluationBlocked(f"Refusing to reuse an existing run directory: {run_root}")
    run_root.mkdir(parents=True, mode=0o700)
    run_root.chmod(0o700)
    project = prepare_model(run_root, name)
    initial_digest = _run.tree_digest(project)
    frozen = json.loads(args.benchmark_manifest.read_text(encoding="utf-8"))
    benchmark = next((item for item in frozen.get("scenarios", []) if item.get("fixture") == name), None)
    if not benchmark or initial_digest != benchmark.get("visible_fixture_sha256"):
        raise EvaluationBlocked(f"Visible fixture {name} does not match its frozen hash")
    grader = _run.private_grader(name)
    if not grader.is_file() or hashlib.sha256(grader.read_bytes()).hexdigest() != benchmark.get("private_grader_sha256"):
        raise EvaluationBlocked(f"Private grader for {name} does not match its frozen hash")

    profile = anvil_inventory(opencode, project)
    if treatment == "anvil-active" and not profile["active_anvil_verified"]:
        raise EvaluationBlocked("The installed OpenCode profile does not resolve the Anvil agent, plugin, skills, and instruction source")
    agent = "anvil" if treatment == "anvil-active" else "build"
    if agent == "anvil":
        baseline_agent_digest = profile.get("anvil_agent_definition_sha256")
    else:
        baseline_agent_digest = _native_agent_baseline(opencode, run_root, agent)

    shell = _build_shell(args, run_root)
    state_root, read_roots, state_home = _local_paths(
        project, run_root, "anvil" if treatment == "anvil-active" else "build")
    allowed_external = list(read_roots)
    if state_root:
        allowed_external.append(state_root)
    local_config = _permissions(project, agent, shell, allowed_external, state_root)
    local_config["agent"][agent]["steps"] = args.max_steps
    _write_project_config(project, local_config)

    roots = [str(path.resolve()) for path in read_roots]
    environment = child_env(ANVIL_EVAL_WORKSPACE=str(project.resolve()))
    if state_root:
        environment["ANVIL_EVAL_STATE_ROOT"] = str(state_root.resolve())
    if state_home:
        environment["ANVIL_EVAL_STATE_HOME"] = str(state_home.resolve())
    if roots:
        environment["ANVIL_EVAL_READ_ROOTS"] = ":".join(roots)
    overlay = _verify_overlay(opencode, project, agent, shell, baseline_agent_digest,
                              read_roots, state_root, pure=(treatment == "native-opencode"))
    prompt = challenge_prompt()
    argv = [str(opencode)]
    if treatment == "native-opencode":
        argv.append("--pure")
    argv.extend(["run", "--format", "json", "--agent", agent, "--model", args.model,
                 "--variant", args.variant, "--title", f"{args.evaluation_id} {name} {treatment}", prompt])
    trace_path = run_root / "trace-metadata.jsonl"
    interrupt_path = project if name == "context-recovery" else None
    metrics, code, elapsed = _run.run_cli_invocation(
        args, argv, project, environment, args.timeout, args.stdout_limit,
        trace_path, f"{treatment}:{name}:1", "challenge", interrupt_path)

    resume = {"status": "NOT_REQUIRED"}
    if name == "context-recovery" and metrics.get("controlled_interrupt"):
        session_id = next(iter(metrics.get("session_ids", [])), None)
        if session_id:
            resume_prompt = (
                "Continue the same task in this existing session. Inspect the current working tree and durable "
                "progress first, reconcile completed work and evidence, avoid repeating completed side effects, "
                "then finish the remaining requirements and public checks."
            )
            resume_argv = [str(opencode), "run", "--format", "json", "--session", session_id,
                           "--agent", agent, "--model", args.model, "--variant", args.variant, resume_prompt]
            resume_trace = run_root / "resume-trace-metadata.jsonl"
            resume_metrics, resume_code, resume_elapsed = _run.run_cli_invocation(
                args, resume_argv, project, environment, args.timeout, args.stdout_limit,
                resume_trace, f"{treatment}:{name}:1", "resume")
            resume = {"status": "COMPLETED" if resume_code == 0 and session_id in resume_metrics.get("session_ids", []) else "FAILED",
                      "session_id_sha256": hashlib.sha256(session_id.encode()).hexdigest(),
                      "elapsed_seconds": resume_elapsed}
            metrics = _run.merge_metrics(metrics, resume_metrics)
            code = resume_code
            elapsed += resume_elapsed
        else:
            resume = {"status": "BLOCKED", "reason": "No session identifier was returned"}

    grade = _grade(project, grader)
    changed = subprocess.run(["git", "-C", str(project), "ls-files", "--others", "--exclude-standard"],
                             capture_output=True, text=True, check=True).stdout.splitlines()
    diff = subprocess.run(["git", "-C", str(project), "diff", "--name-only"],
                          capture_output=True, text=True, check=True).stdout.splitlines()
    changed_files = sorted((set(changed) | set(diff)) - {"opencode.json"})
    session_hashes = [hashlib.sha256(value.encode()).hexdigest() for value in metrics.get("session_ids", [])]
    outcome = {"fixture": name, "treatment": treatment, "model": args.model, "variant": args.variant,
               "runtime_version": args.runtime_version, "fixture_initial_sha256": initial_digest,
               "acceptance": grade["status"], "grader": grade,
               "execution_status": "COMPLETED" if code == 0 and not metrics.get("failure_class") and not metrics.get("limit") else "BLOCKED",
               "failure_class": metrics.get("failure_class"), "exit_code": code, "latency_seconds": elapsed,
               "files_changed": changed_files, "tool_calls": metrics.get("tool_calls"),
               "tool_completed": metrics.get("tool_completed"), "tool_errors": metrics.get("tool_errors"),
               "limit_category": metrics.get("timeout_category"),
               "failure_stage": metrics.get("failure_stage"),
               "token_usage": metrics.get("token_usage"),
               "reported_cost_telemetry": metrics.get("reported_cost_telemetry"),
               "monetary_cost": None, "event_types": metrics.get("event_types"),
               "session_id_sha256": session_hashes, "text_chars_observed": metrics.get("text_chars_observed"),
               "loaded_anvil_skills": metrics.get("loaded_anvil_skills"),
               "public_test_commands": metrics.get("public_test_commands"),
               "safe_trace": str(trace_path), "permission_overlay": overlay,
               "active_profile_inventory": profile, "resume": resume,
               "native_control_caveat": ("Global Anvil instructions may remain in this native run; treat comparison as descriptive."
                                          if treatment == "native-opencode" and profile["active_anvil_verified"] else None),
               "workspace": str(project), "private_reasoning_logged": False,
               "private_grader_inside_workspace": False,
               "semantic_review": "REQUIRED; the deterministic grader does not establish design quality"}
    return outcome


def challenge_prompt() -> str:
    """Return identical user-task guidance for every evaluation treatment."""
    return (
        "Implement specification.md in this disposable fixture repository. Work only in the current project. "
        "Use repository-provided instructions and skills when applicable to this task. "
        "Do not inspect credentials, user memory, external repositories, hidden graders, or production services. "
        "Use the public checks when available, preserve existing behavior, and report evidence, limitations, "
        "and unfinished requirements."
    )


def _save_report(args, runtime: dict, results: list[dict], status: str) -> None:
    value = {"schema_version": 1, "evaluation_id": args.evaluation_id,
             "mode": args.mode, "status": status, "runtime": runtime,
             "results": results, "budget_config": str(args.budget_config),
             "security": {"real_home_xdg_and_auth": True, "credentials_read_or_copied": False,
                          "user_opencode_config_or_auth_modified": False,
                          "temporary_project_permission_overlay_created": True,
                          "fixture_repositories_only_in_temp": True,
                          "hidden_graders_outside_agent_workspace": True,
                          "shell_scope": "Landlock fixture/state roots; network syscalls denied",
                          "raw_prompts_responses_logs_or_grader_diagnostics_retained": False},
             "limitations": ["One run per treatment is descriptive, not statistically conclusive.",
                             "Anvil plugin tools remain denied in the fixture overlay to protect user memory and external state.",
                             "No monetary cost is reported unless provider telemetry has verified billing semantics."]}
    _run.write_json_atomic(args.output, value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("smoke", "challenge", "suite"), default="suite")
    parser.add_argument("--fixture", choices=(*LIVE_FIXTURES, "all"), default="all")
    parser.add_argument("--treatment", choices=TREATMENTS, default="anvil-active")
    parser.add_argument("--opencode", type=pathlib.Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--variant", default=DEFAULT_VARIANT)
    parser.add_argument("--runtime-version")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument("--context-limit", type=int, default=32768)
    parser.add_argument("--output-token-limit", type=int, default=2048)
    parser.add_argument("--stdout-limit", type=int, default=10_485_760)
    parser.add_argument("--evaluation-id")
    parser.add_argument("--workspace-root", type=pathlib.Path)
    parser.add_argument("--budget-config", type=pathlib.Path)
    parser.add_argument("--budget-state", type=pathlib.Path)
    parser.add_argument("--benchmark-manifest", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    try:
        if args.model != DEFAULT_MODEL or args.variant != DEFAULT_VARIANT:
            raise EvaluationBlocked("The live engineering comparison is frozen to Luna 6 High")
        evaluation_directory = configure_evaluation_paths(args)
        print(f"Evaluation ID: {args.evaluation_id}")
        print(f"Evaluation data: {evaluation_directory}")
        if not args.benchmark_manifest.is_file():
            raise EvaluationBlocked("The frozen engineering benchmark manifest is missing")
        frozen = json.loads(args.benchmark_manifest.read_text(encoding="utf-8"))
        if not args.budget_config.is_file() and args.mode != "smoke":
            raise EvaluationBlocked("Run MODE=smoke first to create this evaluation's external budget")
        path_executable = shutil.which("opencode")
        executable = args.opencode or (pathlib.Path(path_executable) if path_executable else None)
        if executable is None:
            raise EvaluationBlocked("OpenCode is not available on PATH and no local executable was supplied")
        executable = executable.expanduser().resolve(strict=True)
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise EvaluationBlocked("The selected local OpenCode executable is not executable")
        if args.workspace_root is None:
            args.workspace_root = pathlib.Path(tempfile.mkdtemp(prefix="anvil-engineering-local-"))
            args.workspace_root.chmod(0o700)
        else:
            args.workspace_root = _ensure_temp_root(args.workspace_root)
        runtime = local_runtime_preflight(executable, args.workspace_root, args.model)
        args.runtime_version = runtime["version"]

        if not args.budget_config.is_file():
            if args.mode != "smoke":
                raise EvaluationBlocked("Run MODE=smoke first to create this evaluation's external budget")
            create_budget_config(args.budget_config, args.evaluation_id, executable, runtime,
                                 args.model, args.variant, args.benchmark_manifest)
        config = json.loads(args.budget_config.read_text(encoding="utf-8"))
        if config.get("evaluation_id") != args.evaluation_id:
            raise EvaluationBlocked("Evaluation ID does not match the frozen budget configuration")
        if args.budget_state.exists():
            state_identity = json.loads(args.budget_state.read_text(encoding="utf-8"))
            if state_identity.get("evaluation_id") != args.evaluation_id:
                raise EvaluationBlocked("Evaluation ID does not match the existing budget state")
        if hashlib.sha256(args.benchmark_manifest.read_bytes()).hexdigest() != config.get("benchmarks_sha256"):
            raise EvaluationBlocked("Frozen challenge/grader manifest hash does not match the registered evaluation")
        runtime_config = config["runtime"]
        budget = config["resource_budget"]
        if args.model != runtime_config["model"] or args.variant != runtime_config["variant"]:
            raise EvaluationBlocked("Local model and variant must match the frozen Luna HIGH evaluation")
        for key, ceiling in RESOURCE_BUDGET.items():
            configured = budget.get(key)
            if not isinstance(configured, int) or configured > ceiling:
                raise EvaluationBlocked(f"Evaluation budget exceeds the supported ceiling for {key}")
        if (args.timeout > budget["max_wall_seconds_per_invocation"] or args.max_steps > budget["max_agent_steps_per_invocation"] or
                args.context_limit > budget["max_context_tokens"] or args.output_token_limit > budget["max_output_tokens_per_response"] or
                args.stdout_limit > budget["max_stdout_event_bytes_per_invocation"]):
            raise EvaluationBlocked("Requested limits exceed this evaluation's frozen budget")
        if args.output.exists():
            prior_report = json.loads(args.output.read_text(encoding="utf-8"))
            if prior_report.get("evaluation_id") != args.evaluation_id:
                raise EvaluationBlocked("Refusing to overwrite results belonging to another evaluation ID")
        expected_executable = runtime_config.get("executable", "PATH")
        if expected_executable != "PATH" and executable != pathlib.Path(expected_executable).expanduser().resolve():
            raise EvaluationBlocked("The OpenCode executable differs from the one frozen in this local evaluation")
        if args.runtime_version != runtime_config.get("version"):
            raise EvaluationBlocked("Installed OpenCode version differs from the frozen runtime version")
        if args.mode == "smoke":
            result = _run_smoke(args, executable)
            _record_smoke(args, result)
            _save_report(args, runtime, [result], "READY" if result["response_and_telemetry"] else "BLOCKED")
            return 0 if result["response_and_telemetry"] else 1

        _require_smoke_passed(args.budget_state)
        if args.mode == "challenge" and args.fixture == "all":
            raise EvaluationBlocked("A challenge run requires one named fixture")
        profile = anvil_inventory(executable, args.workspace_root)
        if args.treatment == "anvil-active" and not profile["active_anvil_verified"]:
            raise EvaluationBlocked("Anvil is not active in the local OpenCode profile; review `make inspect` and `make reforge DRY_RUN=1` first")
        if args.mode == "suite":
            _require_minimal_challenge_passed(args.output, args.treatment)

        if args.mode == "challenge":
            names = [args.fixture]
        else:
            names = list(LIVE_FIXTURES) if args.fixture == "all" else [args.fixture]
        results = []
        if args.output.exists():
            previous = json.loads(args.output.read_text(encoding="utf-8"))
            if previous.get("evaluation_id") == args.evaluation_id:
                results.extend(previous.get("results", []))
        if args.mode == "suite":
            names = [name for name in names if not any(
                row.get("fixture") == name and row.get("treatment") == args.treatment for row in results)]
        for name in names:
            if any(row.get("fixture") == name and row.get("treatment") == args.treatment for row in results):
                raise EvaluationBlocked(f"This evaluation already contains {args.treatment}/{name}; use a new evaluation ID to repeat")
            result = _challenge(args, executable, name, args.treatment)
            results.append(result)
            status = "BLOCKED" if result["execution_status"] == "BLOCKED" else "IN_PROGRESS"
            _save_report(args, runtime, results, status)
            if result["execution_status"] == "BLOCKED":
                break
        challenge_results = [row for row in results if isinstance(row, dict) and "execution_status" in row]
        status = ("COMPLETED" if challenge_results and all(
            row["execution_status"] == "COMPLETED" and row["acceptance"] == "PASS"
            for row in challenge_results) else "BLOCKED")
        _save_report(args, runtime, results, status)
        return 0 if status == "COMPLETED" else 1
    except (EvaluationBlocked, OSError, KeyError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"BLOCKED: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
