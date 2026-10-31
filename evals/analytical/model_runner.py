"""Isolated adapter for repeated blind runs through the installed Anvil agent."""

from __future__ import annotations

import json
import hashlib
import os
import re
import selectors
import signal
import shlex
import shutil
import sys
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from . import PROMPT_VERSION
from .contracts import EvaluationContractError, validate_candidate
from .evaluator import FIXTURES

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from runtime_state import discover as discover_runtime  # noqa: E402

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "blind-analysis-v1.0.md"
MAX_MODEL_OUTPUT_BYTES = 2 * 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_optional_sha256(path: Path) -> str | None:
    candidate = Path(os.path.abspath(path.expanduser()))
    current = Path(candidate.anchor or "/")
    for part in candidate.parts[1:]:
        current = current / part
        if current.is_symlink():
            return None
    return _sha256(candidate) if candidate.is_file() else None


def installed_analysis_helper() -> Path | None:
    config_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")).expanduser()
    candidate = Path(os.path.abspath(config_root / "opencode" / "scripts" / "analyze.py"))
    current = Path(candidate.anchor or "/")
    for part in candidate.parts[1:]:
        current = current / part
        if current.is_symlink():
            return None
    return candidate if candidate.is_file() else None


def _project_permissions(runtime_major: int, workspace: Path, helper: Path) -> dict[str, Any]:
    workspace_pattern = str(workspace / "**")
    dataset_path = shlex.quote(str(workspace / "dataset.csv"))
    plan_path_resource = str(workspace / "analysis-plan.json")
    plan_path = shlex.quote(plan_path_resource)
    helper_command = f"python3 {shlex.quote(str(helper))}"
    command_patterns = (f"{helper_command} profile {dataset_path}",
                        f"{helper_command} execute {dataset_path} {plan_path}")
    helper_directory = str(helper.parent)
    helper_patterns = (helper_directory, helper_directory + "/*", helper_directory + "/**")
    if runtime_major == 1:
        external_rules = {"*": "deny", **{pattern: "allow" for pattern in helper_patterns}}
        read_rules = {"*": "deny", workspace_pattern: "allow",
                      **{pattern: "allow" for pattern in helper_patterns}}
        shell_rules = {"*": "deny", **{pattern: "allow" for pattern in command_patterns}}
        return {"$schema": "https://opencode.ai/config.json",
                "agent": {"anvil": {"permission": {
                    "*": "deny",
                    "external_directory": external_rules,
                    "read": read_rules,
                    "edit": {"*": "deny", plan_path_resource: "allow"},
                    "bash": shell_rules,
                    "skill": {"*": "deny", "anvil-communication": "allow"},
                }}}}
    if runtime_major == 2:
        permissions = [
            {"action": "*", "resource": "*", "effect": "deny"},
            {"action": "external_directory", "resource": "*", "effect": "deny"},
            {"action": "read", "resource": workspace_pattern, "effect": "allow"},
            {"action": "edit", "resource": plan_path_resource, "effect": "allow"},
            *({"action": "shell", "resource": pattern, "effect": "allow"} for pattern in command_patterns),
            {"action": "skill", "resource": "anvil-communication", "effect": "allow"},
        ]
        permissions.extend({"action": "external_directory", "resource": pattern, "effect": "allow"}
                           for pattern in helper_patterns)
        permissions.extend({"action": "read", "resource": pattern, "effect": "allow"}
                           for pattern in helper_patterns)
        return {"$schema": "https://opencode.ai/config.json", "agents": {"anvil": {"permissions": permissions}}}
    raise ValueError("only OpenCode runtime majors 1 and 2 are supported")


def prepare_blind_workspace(workspace: str | Path, source: str | Path, *, runtime_major: int = 2,
                            analysis_helper: str | Path | None = None) -> Path:
    """Populate a fresh model workspace with a public CSV and restrictive local policy."""
    root, source_path = Path(workspace), Path(os.path.abspath(Path(source).expanduser()))
    if not root.is_dir() or any(root.iterdir()):
        raise ValueError("blind model workspace must be an existing empty directory")
    current = Path(source_path.anchor or "/")
    for part in source_path.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise ValueError("blind evaluation input path cannot contain symbolic links")
    if not source_path.is_file():
        raise ValueError("blind evaluation input must be a regular file")
    helper = Path(analysis_helper).absolute() if analysis_helper else installed_analysis_helper()
    if helper is None or not helper.is_file() or helper.is_symlink():
        raise ValueError("the installed Anvil analytical helper is unavailable")
    os.chmod(root, 0o700)
    data_copy = root / "dataset.csv"
    data_copy.write_bytes(source_path.read_bytes())
    os.chmod(data_copy, 0o600)
    config = root / "opencode.json"
    config.write_text(json.dumps(_project_permissions(runtime_major, root, helper), ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
    os.chmod(config, 0o600)
    return data_copy


def _collect_text(value: Any, chunks: list[str]) -> None:
    if isinstance(value, list):
        for item in value:
            _collect_text(item, chunks)
    elif isinstance(value, dict):
        part = value.get("part")
        if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
            chunks.append(part["text"])
        elif value.get("type") in {"text", "message"} and isinstance(value.get("text"), str):
            chunks.append(value["text"])
        for key in ("events", "data", "content"):
            if key in value:
                _collect_text(value[key], chunks)


def _extract_response(stdout: str) -> tuple[str, dict[str, int] | None, int | None]:
    chunks: list[str] = []
    token_values: dict[str, int] = {}
    tool_calls = 0
    decoded_any = False
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        decoded_any = True
        _collect_text(event, chunks)
        if isinstance(event, dict):
            kind = str(event.get("type", "")).casefold()
            part_kind = str(event.get("part", {}).get("type", "")).casefold() if isinstance(event.get("part"), dict) else ""
            if kind in {"tool_use", "tool_call"} or part_kind in {"tool", "tool_use"}:
                tool_calls += 1
            usage = event.get("usage")
            if not isinstance(usage, dict) and isinstance(event.get("part"), dict):
                usage = event["part"].get("usage")
            if isinstance(usage, dict):
                for key, target in (("input_tokens", "input"), ("output_tokens", "output"),
                                    ("input", "input"), ("output", "output"), ("total_tokens", "total")):
                    number = usage.get(key)
                    if isinstance(number, int) and not isinstance(number, bool):
                        token_values[target] = max(token_values.get(target, 0), number)
    if not chunks and not decoded_any:
        chunks = [stdout]
    text = "\n".join(chunk for chunk in chunks if chunk.strip()).strip()
    if not text:
        text = stdout.strip()
    return text, token_values or None, tool_calls or None


def _json_object_from_text(text: str) -> dict[str, Any] | None:
    candidates = [text]
    for match in re.finditer(r"\{", text):
        start = match.start()
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            elif char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start:index + 1])
                    break
    for candidate in reversed(candidates):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return validate_candidate(parsed)
        except (json.JSONDecodeError, EvaluationContractError):
            continue
    return None


def _runtime_version(binary: str) -> str | None:
    try:
        result = subprocess.run([binary, "--version"], capture_output=True, text=True,
                                timeout=5, check=False, close_fds=True)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return (result.stdout or result.stderr).strip().splitlines()[0][:160] or None


def resolve_opencode_binary(binary: str | None = None) -> str | None:
    """Prefer an explicit path, then Anvil's validated runtime, then PATH."""
    selected = binary or os.environ.get("OPENCODE_BIN")
    if selected:
        return selected
    try:
        runtime = (discover_runtime().get("runtime") or {})
    except (OSError, ValueError, KeyError):
        runtime = {}
    if runtime.get("supported") and isinstance(runtime.get("executable"), str):
        return runtime["executable"]
    return shutil.which("opencode")


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except OSError:
        pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass


def _bounded_command(command: list[str], workspace: Path, timeout_seconds: int) -> tuple[int | None, bytes, str | None]:
    """Capture bounded stdout, discard stderr, and stop the full tool process group on timeout."""
    process = subprocess.Popen(command, cwd=workspace, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               close_fds=True, start_new_session=(os.name == "posix"))
    assert process.stdout is not None
    collected = bytearray()
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout_seconds
    status: str | None = None
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                status = "timeout"
                break
            ready = selector.select(remaining)
            if not ready:
                status = "timeout"
                break
            for key, _ in ready:
                chunk = os.read(key.fileobj.fileno(), min(65536, MAX_MODEL_OUTPUT_BYTES + 1 - len(collected)))
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                collected.extend(chunk)
                if len(collected) > MAX_MODEL_OUTPUT_BYTES:
                    status = "output_limit"
                    break
            if status:
                break
        if status:
            _terminate_process_group(process)
        else:
            try:
                process.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                status = "timeout"
                _terminate_process_group(process)
        return process.poll(), bytes(collected), status
    finally:
        selector.close()
        process.stdout.close()


def run_blind_once(fixture_id: str, model: str, *, dataset_path: str | Path | None = None,
                   timeout_seconds: int = 300, binary: str | None = None) -> dict[str, Any]:
    """Run Anvil in a fresh workspace containing only the named CSV and fixed prompt."""
    selected_binary = resolve_opencode_binary(binary)
    run_id = f"model-{fixture_id}-{uuid.uuid4().hex[:12]}"
    if not selected_binary:
        return {"run_id": run_id, "status": "BLOCKED", "blocker": "No supported OpenCode executable was found through Anvil runtime discovery or PATH.",
                "candidate": None, "model": model, "runtime": None, "duration_ms": 0,
                "tool_calls": None, "tokens": None, "prompt_version": PROMPT_VERSION}
    if not model.strip() or len(model) > 160 or model.lstrip().startswith("-") or "\x00" in model:
        return {"run_id": run_id, "status": "BLOCKED", "blocker": "Set MODEL to an explicit provider/model identifier.",
                "candidate": None, "model": model, "runtime": _runtime_version(selected_binary), "duration_ms": 0,
                "tool_calls": None, "tokens": None, "prompt_version": PROMPT_VERSION}
    source = Path(dataset_path) if dataset_path else FIXTURES / f"{fixture_id}.csv"
    if not source.is_file() or source.is_symlink():
        return {"run_id": run_id, "status": "BLOCKED", "blocker": "The explicitly selected public dataset is not a regular file.",
                "candidate": None, "model": model, "runtime": _runtime_version(selected_binary), "duration_ms": 0,
                "tool_calls": None, "tokens": None, "prompt_version": PROMPT_VERSION}
    if not 1 <= timeout_seconds <= 900:
        raise ValueError("timeout_seconds must be between 1 and 900")
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    runtime = _runtime_version(selected_binary)
    runtime_match = re.search(r"\b([12])\.\d+(?:\.\d+)?\b", runtime or "")
    if not runtime_match:
        return {"run_id": run_id, "status": "BLOCKED", "blocker": "Could not identify a supported OpenCode runtime major.",
                "candidate": None, "model": model, "runtime": runtime, "duration_ms": 0,
                "tool_calls": None, "tokens": None, "prompt_version": PROMPT_VERSION}
    runtime_major = int(runtime_match.group(1))
    helper = installed_analysis_helper()
    if helper is None:
        return {"run_id": run_id, "status": "BLOCKED", "blocker": "The installed Anvil deterministic analysis helper is unavailable.",
                "candidate": None, "model": model, "runtime": runtime, "duration_ms": 0,
                "tool_calls": None, "tokens": None, "prompt_version": PROMPT_VERSION}
    started = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="anvil-blind-eval-") as temporary:
            workspace = Path(temporary)
            data_copy = prepare_blind_workspace(workspace, source, runtime_major=runtime_major,
                                                analysis_helper=helper)
            project_config = workspace / "opencode.json"
            config_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")).expanduser() / "opencode"
            execution_context = {"agent": "anvil", "output_format": "json",
                                 "timeout_seconds": timeout_seconds,
                                 "runtime_major": runtime_major,
                                 "dataset_sha256": _sha256(data_copy),
                                 "project_policy_sha256": _sha256(project_config),
                                 "installed_analysis_helper_sha256": _sha256(helper),
                                 "installed_agents_md_sha256": _safe_optional_sha256(config_root / "AGENTS.md"),
                                 "installed_communication_skill_sha256": _safe_optional_sha256(
                                     config_root / "skills" / "anvil-communication" / "SKILL.md")}
            # The fixed prompt is sent as a user message; no ground-truth file,
            # evaluator module, result history, or repository checkout is present.
            command = [selected_binary, "run", "--agent", "anvil", "--model", model,
                       "--format", "json", "--dir", str(workspace), "--file", str(data_copy), prompt]
            returncode, stdout_bytes, process_status = _bounded_command(command, workspace, timeout_seconds)
            duration_ms = (time.perf_counter() - started) * 1000
            if process_status == "timeout":
                return {"run_id": run_id, "status": "BLOCKED", "blocker": f"Model run exceeded the {timeout_seconds}s evaluation timeout.",
                        "candidate": None, "model": model, "runtime": runtime, "duration_ms": round(duration_ms, 3),
                        "tool_calls": None, "tokens": None, "prompt_version": PROMPT_VERSION,
                        "execution_context": execution_context, "failure_code": "MODEL_TIMEOUT"}
            if process_status == "output_limit":
                return {"run_id": run_id, "status": "BLOCKED", "blocker": "Model output exceeded the 2 MiB evaluation limit.",
                        "candidate": None, "model": model, "runtime": runtime, "duration_ms": round(duration_ms, 3),
                        "tool_calls": None, "tokens": None, "prompt_version": PROMPT_VERSION,
                        "execution_context": execution_context, "failure_code": "MODEL_OUTPUT_LIMIT"}
            if returncode != 0:
                return {"run_id": run_id, "status": "BLOCKED", "blocker": "OpenCode could not complete the configured Anvil model run; check the installed Anvil agent and provider authentication.",
                        "candidate": None, "model": model, "runtime": runtime, "duration_ms": round(duration_ms, 3),
                        "tool_calls": None, "tokens": None, "prompt_version": PROMPT_VERSION,
                        "execution_context": execution_context, "failure_code": "MODEL_EXECUTION_FAILED"}
            response, tokens, tool_calls = _extract_response(stdout_bytes.decode("utf-8", errors="replace"))
            candidate = _json_object_from_text(response)
            return {"run_id": run_id, "status": "COMPLETE" if candidate else "UNSTRUCTURED_OUTPUT",
                    "blocker": None if candidate else "Model output did not satisfy the structured observable-result contract.",
                    "candidate": candidate, "model": model, "runtime": runtime,
                    "duration_ms": round(duration_ms, 3), "tool_calls": tool_calls,
                    "tokens": tokens, "prompt_version": PROMPT_VERSION,
                    "execution_context": execution_context}
    except OSError:
        duration_ms = (time.perf_counter() - started) * 1000
        return {"run_id": run_id, "status": "BLOCKED", "blocker": "OpenCode could not be started in the isolated evaluation workspace.",
                "candidate": None, "model": model, "runtime": runtime, "duration_ms": round(duration_ms, 3),
                "tool_calls": None, "tokens": None, "prompt_version": PROMPT_VERSION,
                "failure_code": "MODEL_RUNTIME_UNAVAILABLE"}
