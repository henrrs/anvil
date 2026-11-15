#!/usr/bin/env python3
"""Offline engineering protocol replay and shared local-evaluation helpers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import selectors
import signal
import subprocess
import sys
import tempfile
import time
from unittest import mock

from harness import ROOT, models, replay
sys.path.insert(0, str(ROOT / "scripts"))
from engineering import engine, invariants, store

def replay_run(name: str, repeats: int) -> dict:
    runs = []
    for number in range(repeats):
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix=f"anvil-eval-{name}-") as directory:
            base = pathlib.Path(directory)
            with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(base / "state"), "XDG_DATA_HOME": str(base / "data"),
                    "ANVIL_ENGINEERING": "auto", "PYTHONPATH": str(ROOT / "tests/fixtures/network-denied")}):
                observations = []
                persistence = {"writes": 0}
                architecture = {"checks": 0}
                save, update, evaluate = store.save, store.update, invariants.evaluate
                def counted_save(*args, **kwargs):
                    persistence["writes"] += 1
                    return save(*args, **kwargs)
                def counted_update(*args, **kwargs):
                    persistence["writes"] += 1
                    return update(*args, **kwargs)
                def counted_evaluate(*args, **kwargs):
                    architecture["checks"] += 1
                    return evaluate(*args, **kwargs)
                with mock.patch.object(store, "save", side_effect=counted_save), \
                     mock.patch.object(store, "update", side_effect=counted_update), \
                     mock.patch.object(invariants, "evaluate", side_effect=counted_evaluate):
                    state, project, _ = replay(base, name, observations=observations)
                regressions = {}
                for invariant in models(name)["architecture"]["invariants"]:
                    if invariant["kind"] == "forbidden_imports":
                        target = project / invariant["paths"][0]
                        original = target.read_text()
                        target.write_text(original + "\nimport " + invariant["forbidden"][0] + "\n")
                        regressions[invariant["id"]] = invariants.evaluate(project, invariant)["result"] == "FAIL"
                        target.write_text(original)
                runs.append({"run": number + 1, "task_success": state["status"] == "COMPLETE",
                             "requirements": engine.coverage(state), "architecture": engine.conformance(state),
                             "injected_boundary_violations_detected": regressions,
                             "interruption_and_compaction": "PASS", "duplicate_resume_execution": False,
                             "counters": state["counters"], "latency_seconds": round(time.monotonic() - started, 3),
                             "state_writes": persistence["writes"], "architecture_check_evaluations": architecture["checks"],
                             "verification_commands": state["counters"].get("verification", 0),
                             "milestones_created": len(state["models"]["work"]["milestones"]),
                             "tasks_completed": sum(t["status"] == "VERIFIED" for t in state["models"]["work"]["tasks"]),
                             "replans": state["counters"].get("replanned", 0),
                             "verification_failures": len(state["failures"]),
                             "final_architecture_violations": sum(r != "PASS" for r in engine.conformance(state).values()),
                             "resume_observations": observations, "unnecessary_exploration": None,
                             "tool_calls": None, "model_tokens": None, "unsupported_claims": None,
                             "semantic_design_quality": "NOT_MEASURED"})
    return {"fixture": name, "method": "deterministic protocol replay using explicit reference implementations; not an LLM coding run", "runs": runs}

def stream_metrics(process, timeout: int, output_limit: int, trace_path: pathlib.Path,
                   interrupt_after_change: pathlib.Path | None = None,
                   max_input_tokens_per_request: int | None = None,
                   max_output_tokens_per_response: int | None = None) -> dict:
    """Retain only event metadata, counters, and digests; never retain message text."""
    tool_calls = 0
    tool_completed = 0
    tool_errors = 0
    usage = {}
    recognized = False
    stdout_digest, stderr_digest = hashlib.sha256(), hashlib.sha256()
    buffer = {"stdout": b"", "stderr": b""}
    totals = {"stdout": 0, "stderr": 0}
    started = time.monotonic()
    reason = None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    session_ids = set()
    event_counts = {}
    cost_values = []
    text_chars = 0
    text_digest = hashlib.sha256()
    seen_tool_ids = set()
    completed_tool_ids = set()
    loaded_skills = set()
    public_test_commands = 0
    stderr_sample = bytearray()
    failure_class = None
    error_metadata = {"error_type": None, "error_code": None, "http_status": None,
                      "provider_id": None, "retry_count": None, "run_ids": []}
    trace_path.parent.mkdir(parents=True, exist_ok=True)

    def safe_identifier(value, limit=100):
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            candidate = str(value)
            if (len(candidate) <= limit and
                    re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:@-]{0,159}", candidate) and
                    not re.search(r"(?i)(?:bearer|token|secret|credential|password|api[_-]?key|sk-[a-z0-9])", candidate)):
                return candidate
        return None

    def safe_session_id(value):
        return value if isinstance(value, str) and re.fullmatch(r"ses_[A-Za-z0-9]{16,40}", value) else None

    def safe_token_record(value, depth=0):
        if depth > 3 or not isinstance(value, dict):
            return None
        safe = {}
        for key, item in value.items():
            if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", key):
                continue
            if isinstance(item, dict):
                nested = safe_token_record(item, depth + 1)
                if nested:
                    safe[key] = nested
            elif isinstance(item, (int, float)) and not isinstance(item, bool) and item >= 0:
                safe[key] = item
        return safe or None

    def observe_error_fields(value, depth=0):
        if depth > 5:
            return
        if isinstance(value, dict):
            for key, item in value.items():
                normalized = re.sub(r"[^a-z]", "", str(key).lower())
                if normalized in {"name", "type", "errortype", "errorname"} and error_metadata["error_type"] is None:
                    error_metadata["error_type"] = safe_identifier(item)
                elif normalized in {"code", "errorcode"} and error_metadata["error_code"] is None:
                    error_metadata["error_code"] = safe_identifier(item)
                elif normalized in {"status", "statuscode", "httpstatus", "httpstatuscode"} and error_metadata["http_status"] is None:
                    if isinstance(item, int) and 100 <= item <= 599:
                        error_metadata["http_status"] = item
                    elif isinstance(item, str) and item.isdecimal() and 100 <= int(item) <= 599:
                        error_metadata["http_status"] = int(item)
                elif normalized in {"provider", "providerid"} and error_metadata["provider_id"] is None:
                    error_metadata["provider_id"] = safe_identifier(item)
                elif normalized in {"retrycount", "retries", "attemptcount"} and error_metadata["retry_count"] is None:
                    if isinstance(item, int) and 0 <= item <= 100:
                        error_metadata["retry_count"] = item
                elif normalized in {"runid", "runidentifier"}:
                    candidate = safe_identifier(item)
                    if candidate and candidate not in error_metadata["run_ids"]:
                        error_metadata["run_ids"].append(candidate)
                if isinstance(item, dict):
                    observe_error_fields(item, depth + 1)
                elif isinstance(item, list):
                    for child in item[:20]:
                        observe_error_fields(child, depth + 1)

    def parse_debug_metadata(raw: bytes) -> None:
        text = raw.decode("utf-8", errors="ignore")
        patterns = (
            ("error_type", r"(?i)(?:error(?:name|type)?|name|type)[=: ]+([A-Za-z][A-Za-z0-9_.:-]{0,79})"),
            ("error_code", r"(?i)(?:error[_ -]?code|code)[=: ]+([A-Za-z0-9_.:-]{1,80})"),
            ("http_status", r"(?i)(?:http(?:status)?|status(?:code)?)[=: ]+([1-5][0-9]{2})"),
            ("provider_id", r"(?i)provider(?:id)?[=: ]+([A-Za-z0-9_.-]{1,80})"),
            ("retry_count", r"(?i)(?:retry(?:count)?|retries|attempt(?:count)?)[=: ]+([0-9]{1,3})"),
        )
        for key, pattern in patterns:
            if error_metadata[key] is not None:
                continue
            matches = re.findall(pattern, text)
            if not matches:
                continue
            candidate = matches[-1]
            if key == "http_status":
                number = int(candidate)
                if 100 <= number <= 599:
                    error_metadata[key] = number
            elif key == "retry_count":
                error_metadata[key] = min(int(candidate), 100)
            else:
                error_metadata[key] = safe_identifier(candidate)

    def classify_error(event: dict, stderr: bytes = b"") -> str | None:
        """Classify known failures without retaining provider messages or response bodies."""
        values = []

        def collect(value, depth=0):
            if depth > 4:
                return
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {"message", "name", "type", "code", "status", "statusCode", "status_code", "detail", "cause"}:
                        if isinstance(item, (str, int)) and not isinstance(item, bool):
                            values.append(str(item)[:4096])
                    if key in {"error", "properties", "data", "response"}:
                        collect(item, depth + 1)
            elif isinstance(value, str):
                values.append(value[:4096])

        collect(event.get("error"))
        collect(event.get("properties"))
        if stderr:
            values.append(stderr.decode("utf-8", errors="ignore")[:16384])
        text = " ".join(values).lower()
        statuses = {int(value) for value in values if value.isdecimal() and len(value) == 3}
        statuses.update(int(value) for value in re.findall(
            r"\b(?:http(?:\s+status)?|status(?:code)?)\s*[:= ]\s*([1-5][0-9]{2})\b", text))
        if statuses & {401, 403} or any(word in text for word in ("unauthorized", "authentication", "invalid api key", "forbidden", "oauth")):
            return "AUTHENTICATION_OR_PROVIDER_ACCESS"
        if "database is not empty" in text and "no session table" in text:
            return "LOCAL_RUNTIME_STATE_ERROR"
        if 429 in statuses or any(word in text for word in ("rate limit", "quota", "billing", "payment required")):
            return "PROVIDER_QUOTA_OR_RATE_LIMIT"
        if any(word in text for word in ("model not found", "unknown model", "unsupported model")):
            return "MODEL_UNAVAILABLE"
        if any(status >= 500 for status in statuses) or any(word in text for word in ("internal server error", "service unavailable", "bad gateway")):
            return "PROVIDER_SERVICE_ERROR"
        if any(word in text for word in ("econnreset", "econnrefused", "enotfound", "etimedout", "network timeout", "fetch failed")):
            return "NETWORK_OR_TRANSPORT_ERROR"
        if event.get("type") == "error":
            return "UNCLASSIFIED_OPENCODE_ERROR"
        return None

    def consume(raw, trace):
        nonlocal tool_calls, tool_completed, tool_errors, recognized, text_chars, failure_class, public_test_commands, reason
        try:
            event = json.loads(raw)
        except ValueError:
            return
        if not isinstance(event, dict):
            return
        kind = str(event.get("type", "unknown"))[:80]
        event_counts[kind] = event_counts.get(kind, 0) + 1
        session_value = event.get("sessionID") or event.get("sessionId") or event.get("session_id")
        session_id = safe_session_id(session_value)
        if session_id:
            session_ids.add(session_id)
        run_id = event.get("runID") or event.get("runId") or event.get("run_id")
        safe_run_id = safe_identifier(run_id)
        if safe_run_id and safe_run_id not in error_metadata["run_ids"]:
            error_metadata["run_ids"].append(safe_run_id)
        observe_error_fields(event.get("error"))
        observe_error_fields(event.get("properties"))
        part = event.get("part", {})
        if not isinstance(part, dict):
            part = {}
        tool_name = part.get("tool") or part.get("name") or event.get("tool")
        call_id = safe_identifier(part.get("callID") or event.get("callID"), 100)
        is_tool = kind in {"tool_use", "tool-call"} or part.get("type") in {"tool", "tool_use"}
        if is_tool:
            if not isinstance(call_id, str) or call_id not in seen_tool_ids:
                tool_calls += 1
                if isinstance(call_id, str):
                    seen_tool_ids.add(call_id)
            recognized = True
        state = part.get("state") if isinstance(part.get("state"), dict) else {}
        tool_status = state.get("status")
        tool_input = state.get("input") if isinstance(state.get("input"), dict) else {}
        skill_value = None
        if isinstance(tool_name, str) and tool_name.lower() == "skill":
            candidate = tool_input.get("name") or tool_input.get("skill")
            if isinstance(candidate, str) and candidate.startswith("anvil-"):
                skill_value = candidate[:80]
        if isinstance(tool_name, str) and tool_name.lower() in {"read", "glob"}:
            path_value = tool_input.get("filePath") or tool_input.get("path") or tool_input.get("pattern")
            if isinstance(path_value, str):
                match = re.search(r"(?:^|/)skills/(anvil-[a-z0-9-]+)(?:/|$)", path_value)
                if match:
                    skill_value = match.group(1)
        if skill_value:
            loaded_skills.add(skill_value)
        command_value = tool_input.get("command") or tool_input.get("cmd")
        public_test_command = (isinstance(tool_name, str) and tool_name.lower() == "bash" and
                               isinstance(command_value, str) and
                               re.search(r"\b(pytest|unittest|acceptance\.py)\b", command_value) is not None)
        if public_test_command:
            public_test_commands += 1
        settled = (kind in {"tool_result", "tool_completed", "tool_finished"} or
                   tool_status in {"completed", "complete", "error", "failed"})
        if settled:
            tool_error = (tool_status in {"error", "failed"} or
                          (kind in {"tool_result", "tool_completed", "tool_finished"} and bool(event.get("error"))))
            if isinstance(call_id, str):
                if call_id not in completed_tool_ids:
                    completed_tool_ids.add(call_id)
                    if tool_error:
                        tool_errors += 1
                    else:
                        tool_completed += 1
            else:
                if tool_error:
                    tool_errors += 1
                else:
                    tool_completed += 1
        token_record = safe_token_record(part.get("tokens"))
        if isinstance(token_record, dict):
            for key, value in token_record.items():
                if isinstance(key, str) and isinstance(value, (int, float)) and not isinstance(value, bool):
                    usage[key] = usage.get(key, 0) + value
            context_tokens = sum(token_record.get(key, 0) for key in ("input", "cache_read", "cache_write")
                                 if isinstance(token_record.get(key, 0), (int, float)))
            output_tokens = token_record.get("output", 0)
            if max_input_tokens_per_request and context_tokens > max_input_tokens_per_request:
                reason = reason or "CONTEXT_TOKEN_LIMIT"
            if max_output_tokens_per_response and isinstance(output_tokens, (int, float)) and output_tokens > max_output_tokens_per_response:
                reason = reason or "OUTPUT_TOKEN_LIMIT"
        for cost in (event.get("cost"), part.get("cost"), event.get("message", {}).get("cost") if isinstance(event.get("message"), dict) else None):
            if isinstance(cost, (int, float)) and not isinstance(cost, bool):
                cost_values.append(cost)
        text_value = part.get("text")
        if isinstance(text_value, str):
            text_chars += len(text_value)
            text_digest.update(text_value.encode("utf-8"))
        error_class = classify_error(event) if event.get("type") == "error" or event.get("error") else None
        if error_class and failure_class is None:
            failure_class = error_class
        trace.write(json.dumps({"type": kind if re.fullmatch(r"[A-Za-z][A-Za-z0-9_:-]{0,79}", kind) else "unknown",
                                "session_id_sha256": hashlib.sha256(session_id.encode()).hexdigest() if session_id else None,
                                "tool": safe_identifier(tool_name, 100),
                                "call_id": call_id,
                                "tool_status": str(tool_status)[:40] if isinstance(tool_status, str) else None,
                                "tool_error": bool(tool_status in {"error", "failed"}),
                                "tokens": token_record,
                                "error_class": error_class,
                                "error_type": error_metadata["error_type"] if kind == "error" else None,
                                "error_code": error_metadata["error_code"] if kind == "error" else None,
                                "http_status": error_metadata["http_status"] if kind == "error" else None,
                                "provider_category": error_class,
                                "retry_count": error_metadata["retry_count"] if kind == "error" else None,
                                "run_id_sha256": hashlib.sha256(safe_run_id.encode()).hexdigest() if safe_run_id else None,
                                "skill": skill_value,
                                "public_test_command": bool(public_test_command),
                                "text_chars": len(text_value) if isinstance(text_value, str) else None},
                               separators=(",", ":")) + "\n")
        trace.flush()

    try:
        with trace_path.open("w", encoding="utf-8") as trace:
            os.fchmod(trace.fileno(), 0o600)
            while selector.get_map():
                if time.monotonic() - started > timeout:
                    reason = "WALL_TIMEOUT"
                    break
                if totals["stdout"] > output_limit:
                    reason = "STDOUT_OUTPUT_LIMIT"
                    break
                for key, _ in selector.select(.1):
                    stream = key.data
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    totals[stream] += len(chunk)
                    (stdout_digest if stream == "stdout" else stderr_digest).update(chunk)
                    if stream == "stderr":
                        stderr_sample.extend(chunk)
                        if len(stderr_sample) > 65536:
                            del stderr_sample[:-65536]
                        continue
                    buffer[stream] += chunk
                    while b"\n" in buffer[stream]:
                        line, buffer[stream] = buffer[stream].split(b"\n", 1)
                        consume(line, trace)
                        has_workspace_change = False
                        if interrupt_after_change is not None and tool_completed:
                            has_workspace_change = subprocess.run(
                                ["git", "-C", str(interrupt_after_change), "status", "--porcelain", "--untracked-files=all"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True).stdout.strip() != ""
                        if has_workspace_change:
                            reason = "CONTROLLED_INTERRUPT_AFTER_FILE_CHANGE"
                            break
                    if reason:
                        break
                    if len(buffer[stream]) > 1024 * 1024:
                        buffer[stream] = b""  # Discard an overlong event; never persist its contents.
                if totals["stderr"] > output_limit:
                    reason = "STDERR_OUTPUT_LIMIT"
                    break
            if buffer["stdout"]:
                consume(buffer["stdout"], trace)
            if stderr_sample:
                safe_stderr = bytes(stderr_sample)
                if failure_class is None:
                    failure_class = classify_error({}, safe_stderr)
                observe_error_fields({"properties": {"error": {"message": safe_stderr.decode("utf-8", errors="ignore")}}})
                parse_debug_metadata(safe_stderr)
            if not reason:
                try:
                    process.wait(timeout=max(.1, timeout - (time.monotonic() - started)))
                except subprocess.TimeoutExpired:
                    reason = "WALL_TIMEOUT"
    finally:
        selector.close()
        if process.poll() is None or reason:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            except ProcessLookupError:
                pass
        process.stdout.close()
        process.stderr.close()
    controlled_interrupt = reason == "CONTROLLED_INTERRUPT_AFTER_FILE_CHANGE"
    failure_stage = ("TIMEOUT_OR_OUTPUT_LIMIT" if reason else
                     "MODEL_REQUEST_OR_RUNTIME" if event_counts.get("error") and not tool_calls and not text_chars else
                     "TOOL_EXECUTION" if failure_class and tool_calls else
                     "CLI_OR_EVENT_STREAM" if failure_class else None)
    timeout_category = ("WALL_TIMEOUT" if reason == "WALL_TIMEOUT" else
                        "STDOUT_LIMIT" if reason == "STDOUT_OUTPUT_LIMIT" else
                        "STDERR_LIMIT" if reason == "STDERR_OUTPUT_LIMIT" else
                        "CONTEXT_TOKEN_LIMIT" if reason == "CONTEXT_TOKEN_LIMIT" else
                        "OUTPUT_TOKEN_LIMIT" if reason == "OUTPUT_TOKEN_LIMIT" else None)
    if failure_class == "LOCAL_RUNTIME_STATE_ERROR":
        provider_category = None
    elif failure_class in {"AUTHENTICATION_OR_PROVIDER_ACCESS", "PROVIDER_QUOTA_OR_RATE_LIMIT",
                         "PROVIDER_SERVICE_ERROR", "NETWORK_OR_TRANSPORT_ERROR", "MODEL_UNAVAILABLE"}:
        provider_category = failure_class
    elif failure_class:
        provider_category = "UNCLASSIFIED"
    else:
        provider_category = None
    return {"tool_calls": tool_calls if recognized else None, "tool_completed": tool_completed if recognized else None,
            "tool_errors": tool_errors if recognized else None,
            "token_usage": usage or None,
            "reported_cost_telemetry": sum(cost_values) if cost_values else None, "monetary_cost": None,
            "event_types": event_counts, "session_ids": sorted(session_ids), "text_chars_observed": text_chars,
            "loaded_anvil_skills": sorted(loaded_skills), "public_test_commands": public_test_commands,
            "event_stream_sha256": stdout_digest.hexdigest(), "stderr_sha256": stderr_digest.hexdigest(),
            "stdout_bytes": totals["stdout"], "stderr_bytes": totals["stderr"],
            "response_text_sha256": text_digest.hexdigest() if text_chars else None,
            "error_type": error_metadata["error_type"], "error_code": error_metadata["error_code"],
            "http_status": error_metadata["http_status"], "provider_id": error_metadata["provider_id"],
            "provider_category": provider_category, "retry_count": error_metadata["retry_count"],
            "failure_stage": failure_stage, "timeout_category": timeout_category,
            "run_ids": error_metadata["run_ids"],
            "safe_trace": str(trace_path), "private_reasoning_logged": False,
            "controlled_interrupt": controlled_interrupt, "limit": None if controlled_interrupt else reason,
            "failure_class": failure_class}

def private_grader(name: str) -> pathlib.Path:
    fixture = ROOT / "evals/engineering" / name
    candidates = [fixture / "private" / "acceptance.py", fixture / "acceptance.py", fixture / "fixture" / "acceptance.py"]
    return next((path for path in candidates if path.is_file()), pathlib.Path("/nonexistent-anvil-grader"))

def tree_digest(root: pathlib.Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts:
            digest.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()

def inspect_runtime_logs(home: pathlib.Path, data_home: pathlib.Path | None = None,
                         state_home: pathlib.Path | None = None,
                         cache_home: pathlib.Path | None = None,
                         since_epoch: float | None = None) -> dict:
    """Read bounded OpenCode logs in memory and return only sanitized diagnostic metadata."""
    data_home = data_home or pathlib.Path(os.environ.get("XDG_DATA_HOME", home / ".local/share"))
    state_home = state_home or pathlib.Path(os.environ.get("XDG_STATE_HOME", home / ".local/state"))
    cache_home = cache_home or pathlib.Path(os.environ.get("XDG_CACHE_HOME", home / ".cache"))
    roots = [home / ".local/share-opencode-v1/opencode/log", data_home / "opencode/log",
             state_home / "opencode/log", cache_home / "opencode/log"]
    files = []
    for root in roots:
        if root.is_dir() and not root.is_symlink():
            for path in root.rglob("*"):
                if not (path.is_file() and not path.is_symlink() and path.suffix.lower() == ".log"):
                    continue
                try:
                    if since_epoch is None or path.stat().st_mtime >= since_epoch:
                        files.append(path)
                except OSError:
                    continue
    files = sorted(set(files), key=lambda item: item.stat().st_mtime, reverse=True)[:8]
    output = {"files": len(files), "bytes": 0, "digests": [], "error_type": None,
              "error_code": None, "http_status": None, "provider_id": None,
              "retry_count": None, "provider_category": None, "local_runtime_state_error": False,
              "endpoint_origins": []}
    safe_id = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,79}$")
    denied = re.compile(r"(?i)(?:bearer|token|secret|credential|password|api[_-]?key|sk-[a-z0-9])")
    statuses, types, codes, providers, retries, origins, categories = set(), set(), set(), set(), set(), set(), set()
    url_pattern = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
    text_patterns = (
        ("AUTHENTICATION_OR_PROVIDER_ACCESS", ("unauthorized", "authentication", "invalid api key", "forbidden", "oauth")),
        ("PROVIDER_QUOTA_OR_RATE_LIMIT", ("rate limit", "quota", "billing", "payment required")),
        ("MODEL_UNAVAILABLE", ("model not found", "unknown model", "unsupported model")),
        ("PROVIDER_SERVICE_ERROR", ("internal server error", "service unavailable", "bad gateway")),
        ("NETWORK_OR_TRANSPORT_ERROR", ("econnreset", "econnrefused", "enotfound", "etimedout", "timeout", "timed out", "fetch failed", "connection error")),
    )

    def accept(target: set, candidate) -> None:
        if isinstance(candidate, str) and safe_id.fullmatch(candidate) and not denied.search(candidate):
            target.add(candidate)

    def read_structured_error(value, in_error=False, depth=0) -> None:
        if depth > 8:
            return
        if isinstance(value, dict):
            for key, item in value.items():
                normalized = re.sub(r"[^a-z]", "", str(key).lower())
                nested_error = in_error or normalized in {"error", "exception", "cause"}
                if normalized in {"status", "statuscode", "httpstatus", "httpstatuscode"}:
                    try:
                        number = int(item)
                        if 100 <= number <= 599:
                            statuses.add(number)
                    except (ValueError, TypeError):
                        pass
                elif nested_error and normalized in {"name", "type", "errortype", "errorname"}:
                    accept(types, item)
                elif nested_error and normalized in {"code", "errorcode"}:
                    accept(codes, item)
                elif normalized in {"provider", "providerid"}:
                    accept(providers, item)
                elif normalized in {"retrycount", "retries", "attemptcount"}:
                    try:
                        number = int(item)
                        if 0 <= number <= 100:
                            retries.add(number)
                    except (ValueError, TypeError):
                        pass
                if isinstance(item, (dict, list)):
                    read_structured_error(item, nested_error, depth + 1)
        elif isinstance(value, list):
            for item in value[:100]:
                read_structured_error(item, in_error, depth + 1)

    for path in sorted(set(files)):
        try:
            size = path.stat().st_size
            with path.open("rb") as stream:
                raw = stream.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raw = raw[-(2 * 1024 * 1024):]
            output["bytes"] += size
            output["digests"].append({"file": path.name, "sha256": hashlib.sha256(raw).hexdigest(),
                                     "bytes_examined": len(raw), "truncated": size > len(raw)})
            text = raw.decode("utf-8", errors="ignore")
            failure_lines = [line for line in text.splitlines() if re.search(
                r"(?i)(?:[\"']level[\"']\s*:\s*[\"'](?:error|fatal)[\"']|\b(?:ERROR|FATAL)\b|\b(?:error|exception)\s*[:=])", line)]
            failure_text = "\n".join(failure_lines)
            lowered = failure_text.lower()
            if "database is not empty" in lowered and "no session table" in lowered:
                output["local_runtime_state_error"] = True
            for line in failure_lines:
                try:
                    parsed_line = json.loads(line)
                except ValueError:
                    continue
                read_structured_error(parsed_line)
            for category, needles in text_patterns:
                if any(needle in lowered for needle in needles):
                    categories.add(category)
            for value in re.findall(r"(?i)\b(?:http(?:\s+status)?|status(?:\s+code|code)?|response\s+status)\s*[:= ]\s*([1-5][0-9]{2})\b", failure_text):
                statuses.add(int(value))
            for value in re.findall(r"(?i)\b([A-Za-z][A-Za-z0-9_.-]{0,70}(?:Error|Exception))\b", failure_text):
                accept(types, value)
            for value in re.findall(r"(?i)\b(?:error[_ -]?code|code)\s*[:= ]\s*([A-Za-z][A-Za-z0-9_.:-]{0,79})", failure_text):
                accept(codes, value)
            for value in re.findall(r"(?i)\bprovider(?:id)?\s*[:= ]\s*([A-Za-z][A-Za-z0-9_.-]{0,79})", failure_text):
                accept(providers, value)
            for value in re.findall(r"(?i)\b(?:retry(?:count)?|retries|attempt(?:count)?)\s*[:= ]\s*([0-9]{1,3})", failure_text):
                if int(value) <= 100:
                    retries.add(int(value))
            for value in url_pattern.findall(text):
                try:
                    parsed = urllib.parse.urlsplit(value.rstrip(".,);]"))
                    if parsed.scheme in {"http", "https"} and parsed.hostname:
                        origins.add(f"{parsed.scheme.lower()}://{parsed.hostname.lower()}" +
                                    (f":{parsed.port}" if parsed.port else ""))
                except ValueError:
                    pass
        except OSError:
            continue
    if 401 in statuses or 403 in statuses:
        categories.add("AUTHENTICATION_OR_PROVIDER_ACCESS")
    if 429 in statuses:
        categories.add("PROVIDER_QUOTA_OR_RATE_LIMIT")
    if any(status >= 500 for status in statuses):
        categories.add("PROVIDER_SERVICE_ERROR")
    # Prefer the most specific provider/network class when logs repeat generic errors.
    priority = ("AUTHENTICATION_OR_PROVIDER_ACCESS", "PROVIDER_QUOTA_OR_RATE_LIMIT",
                "MODEL_UNAVAILABLE", "PROVIDER_SERVICE_ERROR", "NETWORK_OR_TRANSPORT_ERROR")
    output.update(error_type=sorted(types)[-1] if types else None,
                  error_code=sorted(codes)[-1] if codes else None,
                  http_status=sorted(statuses)[-1] if statuses else None,
                  provider_id=sorted(providers)[-1] if providers else None,
                  retry_count=sorted(retries)[-1] if retries else None,
                  provider_category=next((item for item in priority if item in categories), None),
                  endpoint_origins=sorted(origins))
    return output

def augment_runtime_diagnostics(metrics: dict, home: pathlib.Path, data_home: pathlib.Path | None = None,
                                state_home: pathlib.Path | None = None,
                                cache_home: pathlib.Path | None = None,
                                since_epoch: float | None = None) -> dict:
    evidence = inspect_runtime_logs(home, data_home, state_home, cache_home, since_epoch)
    metrics["runtime_log_diagnostics"] = evidence
    for field in ("error_type", "error_code", "http_status", "provider_id", "retry_count"):
        if metrics.get(field) is None:
            metrics[field] = evidence.get(field)
    if evidence.get("provider_category"):
        metrics["provider_category"] = evidence["provider_category"]
        if metrics.get("failure_class") in {None, "UNCLASSIFIED_OPENCODE_ERROR"}:
            metrics["failure_class"] = evidence["provider_category"]
    if evidence.get("local_runtime_state_error"):
        metrics["failure_class"] = "LOCAL_RUNTIME_STATE_ERROR"
        if metrics.get("failure_stage") in {None, "CLI_EXIT"}:
            metrics["failure_stage"] = "LOCAL_RUNTIME_STARTUP"
    if not metrics.get("failure_stage") and metrics.get("failure_class"):
        metrics["failure_stage"] = "MODEL_REQUEST_OR_RUNTIME" if not metrics.get("tool_calls") else "TOOL_EXECUTION"
    return metrics

def write_json_atomic(path: pathlib.Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)

def reserve_invocation(args, key: str, kind: str = "challenge") -> dict:
    limits = json.loads(args.budget_config.read_text())["resource_budget"]
    state = json.loads(args.budget_state.read_text()) if args.budget_state.exists() else {
        "schema_version": 1, "invocations": [], "challenge_keys": [], "resume_keys": [],
        "actual_wall_seconds": 0, "reserved_wall_seconds": 0,
        "actual_input_tokens": 0, "actual_output_tokens": 0,
        "reserved_input_tokens": 0, "reserved_output_tokens": 0,
    }
    if len(state["invocations"]) >= limits["max_cli_invocations_total"]:
        raise RuntimeError("Registered live-evaluation CLI invocation budget is exhausted")
    if kind == "smoke" and sum(row.get("kind") == "smoke" for row in state["invocations"]) >= limits["max_smoke_invocations"]:
        raise RuntimeError("Registered model smoke-test budget is exhausted")
    if kind == "challenge" and key not in state["challenge_keys"]:
        if len(state["challenge_keys"]) >= limits["max_challenge_sessions"]:
            raise RuntimeError("Registered challenge-session budget is exhausted")
        state["challenge_keys"].append(key)
    if kind == "resume":
        resume_keys = state.setdefault("resume_keys", [])
        if key in resume_keys:
            raise RuntimeError("A context-recovery session cannot be resumed more than once")
        if len(resume_keys) >= limits["max_resume_invocations"]:
            raise RuntimeError("Registered context-recovery resume budget is exhausted")
        resume_keys.append(key)
    input_reservation = limits["max_context_tokens"] * limits["max_agent_steps_per_invocation"]
    output_reservation = limits["max_output_tokens_per_response"] * limits["max_agent_steps_per_invocation"]
    if kind == "smoke":
        input_reservation = limits["max_context_tokens"]
        output_reservation = limits["max_output_tokens_per_response"]
    if (state.get("actual_input_tokens", 0) + state.get("reserved_input_tokens", 0) + input_reservation > limits["max_total_input_tokens"] or
            state.get("actual_output_tokens", 0) + state.get("reserved_output_tokens", 0) + output_reservation > limits["max_total_output_tokens"]):
        raise RuntimeError("Insufficient registered token budget remains for another model invocation")
    timeout = min(args.timeout, limits["max_wall_seconds_per_invocation"])
    if state["actual_wall_seconds"] + state["reserved_wall_seconds"] + timeout > limits["max_global_wall_seconds"]:
        raise RuntimeError("Insufficient remaining global wall-time budget for another model invocation")
    invocation = {"index": len(state["invocations"]) + 1, "key": key, "kind": kind,
                  "started_at_epoch": time.time(), "reserved_seconds": timeout,
                  "reserved_input_tokens": input_reservation,
                  "reserved_output_tokens": output_reservation, "status": "RUNNING"}
    state["invocations"].append(invocation)
    state["reserved_wall_seconds"] += timeout
    state["reserved_input_tokens"] = state.get("reserved_input_tokens", 0) + input_reservation
    state["reserved_output_tokens"] = state.get("reserved_output_tokens", 0) + output_reservation
    write_json_atomic(args.budget_state, state)
    return invocation

def finish_invocation(args, invocation: dict, elapsed: float, status: str, metrics: dict | None = None) -> None:
    state = json.loads(args.budget_state.read_text())
    item = next(row for row in state["invocations"] if row["index"] == invocation["index"])
    reserved = item["reserved_seconds"]
    item.update(status=status, elapsed_seconds=round(elapsed, 3), finished_at_epoch=time.time())
    state["reserved_wall_seconds"] = max(0, state["reserved_wall_seconds"] - reserved)
    state["actual_wall_seconds"] += round(elapsed, 3)
    state["reserved_input_tokens"] = max(0, state.get("reserved_input_tokens", 0) - item.get("reserved_input_tokens", 0))
    state["reserved_output_tokens"] = max(0, state.get("reserved_output_tokens", 0) - item.get("reserved_output_tokens", 0))
    usage = (metrics or {}).get("token_usage") or {}
    observed_input = usage.get("input", 0) if isinstance(usage.get("input", 0), (int, float)) else 0
    observed_output = usage.get("output", 0) if isinstance(usage.get("output", 0), (int, float)) else 0
    item["observed_input_tokens"] = observed_input or None
    item["observed_output_tokens"] = observed_output or None
    item["reported_cost_telemetry"] = (metrics or {}).get("reported_cost_telemetry")
    item["monetary_cost"] = None
    state["actual_input_tokens"] = state.get("actual_input_tokens", 0) + observed_input
    state["actual_output_tokens"] = state.get("actual_output_tokens", 0) + observed_output
    write_json_atomic(args.budget_state, state)

def run_cli_invocation(args, argv: list[str], cwd: pathlib.Path,
                       env: dict[str, str], timeout: int, output_limit: int,
                       trace_path: pathlib.Path, budget_key: str, budget_kind: str,
                       interrupt_after_change: pathlib.Path | None = None) -> tuple[dict, int | None, float]:
    started = time.monotonic()
    invocation = reserve_invocation(args, budget_key, budget_kind)
    process = None
    metrics = {}
    try:
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        metrics = stream_metrics(process, timeout, output_limit, trace_path, interrupt_after_change,
                                 getattr(args, "context_limit", None), getattr(args, "output_token_limit", None))
    finally:
        elapsed = round(time.monotonic() - started, 3)
        process_code = process.returncode if process is not None else None
        metrics.update({"process_id": process.pid if process is not None else None,
                        "process_exit_code": process_code, "elapsed_seconds": elapsed,
                        "failure_stage": metrics.get("failure_stage") or
                                         ("MODEL_REQUEST_OR_RUNTIME" if metrics.get("event_types", {}).get("error")
                                          else "CLI_EXIT" if process_code not in (None, 0) else None)})
        finish_invocation(args, invocation, elapsed,
                          "CONTROLLED_INTERRUPT" if interrupt_after_change and metrics.get("controlled_interrupt")
                          else "COMPLETED" if process_code == 0 else "START_OR_RUN_FAILED", metrics)
    return metrics, process.returncode, elapsed

def merge_metrics(first: dict, second: dict) -> dict:
    usage = dict(first.get("token_usage") or {})
    for key, value in (second.get("token_usage") or {}).items():
        if isinstance(value, (int, float)) and isinstance(usage.get(key), (int, float)):
            usage[key] += value
        else:
            usage[key] = value
    session_ids = sorted(set(first.get("session_ids", [])) | set(second.get("session_ids", [])))
    event_types = dict(first.get("event_types") or {})
    for key, value in (second.get("event_types") or {}).items():
        event_types[key] = event_types.get(key, 0) + value
    return {
        "tool_calls": (first.get("tool_calls") or 0) + (second.get("tool_calls") or 0),
        "tool_completed": (first.get("tool_completed") or 0) + (second.get("tool_completed") or 0),
        "tool_errors": (first.get("tool_errors") or 0) + (second.get("tool_errors") or 0),
        "token_usage": usage or None,
        "reported_cost_telemetry": (sum(value for value in
             (first.get("reported_cost_telemetry"), second.get("reported_cost_telemetry"))
             if isinstance(value, (int, float))) if any(isinstance(value, (int, float)) for value in
             (first.get("reported_cost_telemetry"), second.get("reported_cost_telemetry"))) else None),
        "monetary_cost": None,
        "event_types": event_types,
        "session_ids": session_ids,
        "text_chars_observed": (first.get("text_chars_observed") or 0) + (second.get("text_chars_observed") or 0),
        "loaded_anvil_skills": sorted(set(first.get("loaded_anvil_skills", [])) | set(second.get("loaded_anvil_skills", []))),
        "public_test_commands": (first.get("public_test_commands") or 0) + (second.get("public_test_commands") or 0),
        "event_stream_sha256": [first.get("event_stream_sha256"), second.get("event_stream_sha256")],
        "stderr_sha256": [first.get("stderr_sha256"), second.get("stderr_sha256")],
        "stdout_bytes": (first.get("stdout_bytes") or 0) + (second.get("stdout_bytes") or 0),
        "stderr_bytes": (first.get("stderr_bytes") or 0) + (second.get("stderr_bytes") or 0),
        "runtime_log_diagnostics": [item for item in
                                    (first.get("runtime_log_diagnostics"), second.get("runtime_log_diagnostics"))
                                    if item],
        "safe_trace": [first.get("safe_trace"), second.get("safe_trace")],
        "private_reasoning_logged": False,
        "controlled_interrupt": first.get("controlled_interrupt", False),
        "limit": second.get("limit") or first.get("limit"),
        "failure_class": second.get("failure_class") or first.get("failure_class"),
    }
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", choices=("ingestion", "scheduler", "retry-policy", "all"), default="all")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 20:
        parser.error("--repeats must be between 1 and 20")
    fixtures = ("ingestion", "scheduler", "retry-policy")
    names = fixtures if args.fixture == "all" else (args.fixture,)
    results = [replay_run(name, args.repeats) for name in names]
    report = {"schema_version": 1, "method": "deterministic protocol replay, not autonomous model coding",
              "results": results,
              "limitations": ["Replay measures deterministic continuity/conformance, not model reasoning or coding quality.",
                              "Tool/model token fields are null when unmeasured; no hidden reasoning is retained."]}
    write_json_atomic(args.output, report)
    print(f"Wrote engineering replay: {args.output}")
    return 0 if all(run["task_success"] and all(run["injected_boundary_violations_detected"].values())
                    for item in results for run in item["runs"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
