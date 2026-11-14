"""Run a small, isolated OpenCode runtime diagnosis with safe event traces."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parents[3]
EVALUATION = pathlib.Path(__file__).resolve().parent
DURABLE = pathlib.Path.home() / ".local/share/anvil/evaluations/anvil-engineering-live-2026-11-14"
WORKSPACE_ROOT = pathlib.Path.home() / ".local/share/anvil/evaluations/anvil-engineering-runtime-diagnostic-2026-11-14/runs"
ID = "anvil-engineering-runtime-diagnostic-2026-11-14"
MODEL = "openai/gpt-6-luna"
VARIANT = "high"
PROMPT = os.environ.get("ANVIL_DIAGNOSTIC_SMOKE_PROMPT")
EXPECTED_TEXT_SHA256 = hashlib.sha256(b"READY").hexdigest()

sys.path.insert(0, str(ROOT / "evals/engineering"))
import run as runner  # noqa: E402


def write_json(path: pathlib.Path, value: dict) -> None:
    runner.write_json_atomic(path, value)


def save_results(results: list[dict], status: str) -> None:
    write_json(EVALUATION / "metrics.json", {
        "schema_version": 1,
        "evaluation_id": ID,
        "status": status,
        "runtime": {"version": "1.19.5", "model": MODEL, "variant": VARIANT,
                    "reasoning_effort": "high", "fallback": False},
        "baseline": {"commit": "b09d9651952aef9f6a296b559cf38c08c320ca74",
                     "durable_directory": str(DURABLE),
                     "archive_sha256": "aa40c198b23e128dca4e39cb0a62d41df6b0263ea5b82ba35ef12732025e0630",
                     "manifest_sha256": "591f414649029e6e219b4c2d5c3ae0b0926badaeddb76f526b5f5e4f295bf266",
                     "manifest_files": 713},
        "results": results,
        "privacy": {"raw_prompts_or_responses_persisted": False,
                    "reasoning_or_credentials_persisted": False,
                    "trace_content": "event metadata, counters, hashes, and sanitized failure metadata only"},
    })


def args_for(treatment: str) -> SimpleNamespace:
    cache = pathlib.Path("<temporary-evaluation-root>/plugin-dependency-cache")
    return SimpleNamespace(
        evaluation_id=ID,
        opencode=pathlib.Path(os.environ.get("OPENCODE") or shutil.which("opencode")
                              or pathlib.Path.home() / ".opencode/bin/opencode").expanduser(),
        runtime_version="1.19.5", model=MODEL, variant=VARIANT,
        auth_file=pathlib.Path.home() / ".local/share-opencode-v1/opencode/auth.json",
        profile_root=DURABLE / "baseline-worktree", plugin_dependency_cache=cache,
        plugin_dependency_cache_sha256="d472d4801e68cdec500dc7e6ca9987b859ef4715303ae1ee626eaa78a22c30e2",
        major=1, context_limit=32768, output_token_limit=2048, max_steps=12,
        tool_output_limit=40000, stdout_limit=10485760,
        timeout=300, workspace_root=WORKSPACE_ROOT,
        budget_config=EVALUATION / "config.json", budget_state=EVALUATION / "budget-state.json",
        benchmark_manifest=ROOT / "evals/engineering/live-2026-11-14/benchmarks.json",
        treatment=treatment,
    )


def preflight(args, sandbox: list[str], env: dict[str, str], agent: str) -> dict:
    result = subprocess.run(sandbox + [runner.CLI_SANDBOX_PATH, "debug", "config"], env=env,
                            capture_output=True, timeout=45, check=True, text=True)
    resolved = json.loads(result.stdout)
    model_config = resolved.get("provider", {}).get("openai", {}).get("models", {}).get("gpt-6-luna", {})
    agent_config = resolved.get("agent", {}).get(agent, {})
    if (resolved.get("model") != MODEL or
            model_config.get("variants", {}).get(VARIANT, {}).get("reasoningEffort") != VARIANT or
            model_config.get("limit", {}).get("context") != args.context_limit or
            model_config.get("limit", {}).get("output") != args.output_token_limit or
            agent_config.get("steps") != args.max_steps):
        raise RuntimeError("smoke profile did not resolve the frozen model, effort, or limits")
    plugins = resolved.get("plugin") or []
    expected = "file:///tmp/home/.config/opencode/plugins/anvil-core-v1.ts"
    if args.treatment == "native-opencode" and plugins:
        raise RuntimeError("native smoke unexpectedly resolved a plugin")
    if args.treatment != "native-opencode" and plugins != [expected]:
        raise RuntimeError("Anvil smoke did not resolve its managed V1 plugin")
    if resolved.get("mcp"):
        raise RuntimeError("smoke profile resolved an unexpected MCP server")
    return {"model": resolved.get("model"), "variant": VARIANT,
            "reasoning_effort": model_config.get("variants", {}).get(VARIANT, {}).get("reasoningEffort"),
            "context_limit": model_config.get("limit", {}).get("context"),
            "output_limit": model_config.get("limit", {}).get("output"),
            "agent_steps": agent_config.get("steps"), "plugins": plugins,
            "shell_configured": "shell" in resolved,
            "provider_endpoint": runner.safe_provider_endpoint(resolved)}


def smoke(treatment: str, attempt: int = 1) -> dict:
    if not PROMPT:
        raise RuntimeError("Set ANVIL_DIAGNOSTIC_SMOKE_PROMPT to a short no-tool smoke prompt")
    args = args_for(treatment)
    args.max_steps, args.output_token_limit, args.timeout = 1, 256, 90
    run_root = WORKSPACE_ROOT / treatment / f"smoke-{attempt:02d}"
    if run_root.exists():
        raise RuntimeError(f"Refusing to reuse smoke directory: {run_root}")
    run_root.mkdir(parents=True, mode=0o700)
    run_root.chmod(0o700)
    home, project, tools_dir = run_root / "home", run_root / "project", run_root / "tools"
    for directory in (home / ".config", home / ".local/share-opencode-v1/opencode", home / ".local/state",
                      home / ".cache", home / ".cache/tmp"):
        directory.mkdir(parents=True, exist_ok=True)
    project.mkdir()
    tools_dir.mkdir()
    if not args.auth_file.is_file():
        raise RuntimeError("OpenCode auth file is unavailable; contents were not read")
    agent = runner.build_runtime_config(home, args, treatment, "/tmp/tools/landlock-shell")
    config_path = home / ".config/opencode/opencode.jsonc"
    config = json.loads(config_path.read_text())
    config.pop("shell", None)  # Match the earlier smoke's lack of a custom shell launcher.
    config.setdefault("agent", {}).setdefault(agent, {})["permission"] = {"*": "deny"}
    config_path.chmod(0o600)
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    dependencies = runner.seed_plugin_dependencies(home, args, treatment)
    env = {"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
           "XDG_DATA_HOME": str(home / ".local/share-opencode-v1"),
           "XDG_STATE_HOME": str(home / ".local/state"), "XDG_CACHE_HOME": str(home / ".cache"),
           "PATH": "/tmp/tools:/usr/bin:/bin", "NO_COLOR": "1"}
    sandbox = runner.sandbox_argv(home, project, tools_dir, args, treatment)
    version = subprocess.run(sandbox + [runner.CLI_SANDBOX_PATH, "--version"], env=env,
                             capture_output=True, timeout=15, check=True, text=True).stdout.strip()
    if version != "1.19.5":
        raise RuntimeError("OpenCode version changed before smoke execution")
    observed_config = preflight(args, sandbox, env, agent)
    argv = [runner.CLI_SANDBOX_PATH, "--print-logs", "--log-level", "DEBUG", "run", "--format", "json",
            "--agent", agent, "--model", MODEL, "--variant", VARIANT,
            "--title", f"{ID} smoke {treatment}", PROMPT]
    trace_path = run_root / "trace-metadata.jsonl"
    metrics, exit_code, elapsed = runner.run_cli_invocation(
        args, sandbox, argv, project, env, args.timeout, args.stdout_limit,
        trace_path, f"{treatment}:smoke:{attempt}", "smoke")
    runner.augment_runtime_diagnostics(metrics, home)
    status = "PASS" if (exit_code == 0 and metrics["failure_class"] is None and metrics["limit"] is None and
                         metrics["tool_calls"] in (None, 0) and metrics["response_text_sha256"] == EXPECTED_TEXT_SHA256) else "FAIL"
    result = {"kind": "smoke", "attempt": attempt, "treatment": treatment, "status": status, "exit_code": exit_code,
              "elapsed_seconds": elapsed, "failure_class": metrics["failure_class"],
              "failure_stage": metrics["failure_stage"], "timeout_category": metrics["timeout_category"],
              "error_type": metrics["error_type"], "error_code": metrics["error_code"],
              "http_status": metrics["http_status"], "provider_id": metrics["provider_id"],
              "provider_category": metrics["provider_category"], "retry_count": metrics["retry_count"],
              "process_id": metrics["process_id"], "process_exit_code": metrics["process_exit_code"],
              "elapsed_from_runner_seconds": metrics["elapsed_seconds"], "run_ids": metrics["run_ids"],
              "session_ids": metrics["session_ids"], "event_types": metrics["event_types"],
              "token_usage": metrics["token_usage"], "reported_cost_telemetry": metrics["reported_cost_telemetry"],
              "text_chars_observed": metrics["text_chars_observed"],
              "response_text_sha256": metrics["response_text_sha256"],
              "runtime_log_diagnostics": metrics["runtime_log_diagnostics"],
              "tool_calls": metrics["tool_calls"], "safe_trace": str(trace_path),
              "resolved_config": observed_config, "plugin_dependencies": dependencies}
    runner.remove_runtime_transcripts(home)
    if home.exists():
        shutil.rmtree(home)
    return result


def main() -> int:
    EVALUATION.mkdir(parents=True, exist_ok=True)
    EVALUATION.chmod(0o700)
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    WORKSPACE_ROOT.chmod(0o700)
    config = {
        "schema_version": 1,
        "evaluation_id": ID,
        "runtime": {"version": "1.19.5", "executable": "$HOME/.opencode/bin/opencode",
                    "model": MODEL, "variant": VARIANT, "reasoning_effort": "high", "fallback": False},
        "sequence": ["native smoke", "Anvil smoke", "native fast-control", "Anvil fast-control",
                     "native retry-policy", "Anvil retry-policy", "one native smoke diagnostic repeat if logs were unavailable"],
        "resource_budget": {"max_cli_invocations_total": 7, "max_smoke_invocations": 3,
                            "max_challenge_sessions": 4, "concurrency": 1,
                            "max_agent_steps_per_invocation": 12, "max_context_tokens": 32768,
                            "max_output_tokens_per_response": 2048,
                            "max_wall_seconds_per_invocation": 300,
                            "max_global_wall_seconds": 1800,
                            "max_stdout_event_bytes_per_invocation": 10485760,
                            "max_tool_output_bytes": 40000,
                            "max_total_input_tokens": 1710000,
                            "max_total_output_tokens": 110000},
        "automatic_retries": 0,
        "stop_conditions": ["any failed smoke", "provider/auth/quota/rate-limit failure",
                             "unclassified terminal error before tools or token usage",
                             "runtime or sandbox preflight mismatch"],
    }
    write_json(EVALUATION / "config.json", config)
    budget_state = EVALUATION / "budget-state.json"
    if budget_state.exists():
        raise RuntimeError(f"Refusing to reuse diagnostic budget state: {budget_state}")
    results: list[dict] = []
    overall = "RUNNING"
    save_results(results, overall)
    for treatment in ("native-opencode", "anvil-2.20.0"):
        try:
            result = smoke(treatment)
        except Exception as exc:
            result = {"kind": "smoke", "treatment": treatment, "status": "BLOCKED",
                      "failure_stage": "PREFLIGHT_OR_SETUP", "error_type": type(exc).__name__}
        finally:
            smoke_home = WORKSPACE_ROOT / treatment / "smoke-01/home"
            if smoke_home.exists():
                shutil.rmtree(smoke_home)
        results.append(result)
        save_results(results, "RUNNING")
        if result.get("status") != "PASS":
            overall = "BLOCKED"
            break

    challenge_results = []
    if overall == "RUNNING":
        for treatment in ("native-opencode", "anvil-2.20.0"):
            args = args_for(treatment)
            run_root = args.workspace_root / treatment / "fast-control-01"
            try:
                result = runner.live_run(args, "fast-control", 1, treatment)
            except Exception as exc:
                result = {"fixture": "fast-control", "treatment": treatment,
                          "execution_status": "BLOCKED", "failure_stage": "PREFLIGHT_OR_SETUP",
                          "error_type": type(exc).__name__}
            finally:
                home = run_root / "home"
                if home.exists():
                    shutil.rmtree(home)
            challenge_results.append(result)
            results.append({"kind": "challenge", **result})
            save_results(results, "RUNNING")
            if result.get("execution_status") != "COMPLETED":
                overall = "BLOCKED"
                break

    if overall == "RUNNING" and len(challenge_results) == 2:
        for treatment in ("native-opencode", "anvil-2.20.0"):
            args = args_for(treatment)
            run_root = args.workspace_root / treatment / "retry-policy-01"
            try:
                result = runner.live_run(args, "retry-policy", 1, treatment)
            except Exception as exc:
                result = {"fixture": "retry-policy", "treatment": treatment,
                          "execution_status": "BLOCKED", "failure_stage": "PREFLIGHT_OR_SETUP",
                          "error_type": type(exc).__name__}
            finally:
                home = run_root / "home"
                if home.exists():
                    shutil.rmtree(home)
            results.append({"kind": "challenge", **result})
            save_results(results, "RUNNING")
            if result.get("execution_status") != "COMPLETED":
                overall = "BLOCKED"
                break

    if overall == "RUNNING":
        required = [item for item in results if item.get("kind") == "challenge"]
        overall = "READY" if len(required) >= 2 and all(
            item.get("execution_status") == "COMPLETED" and item.get("acceptance") == "PASS"
            for item in required[:2]) else "BLOCKED"
    save_results(results, overall)
    print(json.dumps({"evaluation_id": ID, "status": overall,
                      "results": [{"kind": row.get("kind"), "treatment": row.get("treatment"),
                                   "fixture": row.get("fixture"), "status": row.get("status"),
                                   "execution_status": row.get("execution_status"),
                                   "acceptance": row.get("acceptance"),
                                   "failure_class": row.get("failure_class"),
                                   "http_status": row.get("http_status"),
                                   "elapsed_seconds": row.get("elapsed_seconds", row.get("latency_seconds"))}
                                  for row in results]}, indent=2))
    return 0 if overall == "READY" else 1


def continue_after_observability_fix() -> int:
    """Make one logged native smoke repeat, then continue only if the path is healthy."""
    metrics_path = EVALUATION / "metrics.json"
    saved = json.loads(metrics_path.read_text())
    results = saved.get("results", [])
    initial_native = next((item for item in results if item.get("kind") == "smoke" and
                           item.get("treatment") == "native-opencode"), None)
    if (not initial_native or initial_native.get("status") != "FAIL" or
            initial_native.get("runtime_log_diagnostics")):
        raise RuntimeError("Refusing a blind repeat; expected only the prior unclassified smoke without log metadata")
    if (any(item.get("kind") == "smoke" and item.get("treatment") == "native-opencode" and
            item.get("attempt") == 2 for item in results) or
            (WORKSPACE_ROOT / "native-opencode/smoke-02").exists()):
        raise RuntimeError("The one bounded diagnostic repeat already exists; use a fresh evaluation ID")
    config_path = EVALUATION / "config.json"
    config = json.loads(config_path.read_text())
    config["sequence"] = ["native smoke diagnostic repeat", "Anvil smoke", "native fast-control",
                          "Anvil fast-control", "native retry-policy", "Anvil retry-policy"]
    config["resource_budget"].update(max_cli_invocations_total=7, max_smoke_invocations=3,
                                     max_total_input_tokens=1710000)
    write_json(config_path, config)

    def record(result: dict, status="RUNNING") -> None:
        results.append(result)
        save_results(results, status)

    try:
        result = smoke("native-opencode", attempt=2)
    except Exception as exc:
        result = {"kind": "smoke", "attempt": 2, "treatment": "native-opencode", "status": "BLOCKED",
                  "failure_stage": "PREFLIGHT_OR_SETUP", "error_type": type(exc).__name__}
    finally:
        home = WORKSPACE_ROOT / "native-opencode/smoke-02/home"
        if home.exists():
            shutil.rmtree(home)
    record(result, "RUNNING" if result.get("status") == "PASS" else "BLOCKED")
    if result.get("status") != "PASS":
        return 1

    try:
        result = smoke("anvil-2.20.0", attempt=1)
    except Exception as exc:
        result = {"kind": "smoke", "attempt": 1, "treatment": "anvil-2.20.0", "status": "BLOCKED",
                  "failure_stage": "PREFLIGHT_OR_SETUP", "error_type": type(exc).__name__}
    finally:
        home = WORKSPACE_ROOT / "anvil-2.20.0/smoke-01/home"
        if home.exists():
            shutil.rmtree(home)
    record(result, "RUNNING" if result.get("status") == "PASS" else "BLOCKED")
    if result.get("status") != "PASS":
        return 1

    challenge_results = []
    for fixture in ("fast-control", "retry-policy"):
        for treatment in ("native-opencode", "anvil-2.20.0"):
            args = args_for(treatment)
            run_root = args.workspace_root / treatment / f"{fixture}-01"
            try:
                result = runner.live_run(args, fixture, 1, treatment)
            except Exception as exc:
                result = {"fixture": fixture, "treatment": treatment, "execution_status": "BLOCKED",
                          "failure_stage": "PREFLIGHT_OR_SETUP", "error_type": type(exc).__name__}
            finally:
                home = run_root / "home"
                if home.exists():
                    shutil.rmtree(home)
            challenge_results.append(result)
            record({"kind": "challenge", **result})
            if result.get("execution_status") != "COMPLETED":
                save_results(results, "BLOCKED")
                return 1
        if fixture == "fast-control":
            successful = [item for item in challenge_results if item["fixture"] == "fast-control"]
            if len(successful) != 2:
                save_results(results, "BLOCKED")
                return 1

    fast_results = [item for item in challenge_results if item["fixture"] == "fast-control"]
    overall = "READY" if all(item.get("acceptance") == "PASS" for item in fast_results) else "BLOCKED"
    save_results(results, overall)
    return 0 if overall == "READY" else 1


if __name__ == "__main__":
    action = continue_after_observability_fix if sys.argv[1:] == ["--continue-after-log-capture"] else main
    raise SystemExit(action())
