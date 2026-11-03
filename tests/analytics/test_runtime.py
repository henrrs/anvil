from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from scripts.analytics.context import ContextResolver
from scripts.analytics.errors import ProviderError, UnavailableError, ValidationError
from scripts.analytics.models import KnowledgeItem
from scripts.analytics.opencode import create_adapter
from scripts.analytics.paths import AnalyticsPaths
from scripts.analytics.runtime import AnalyticsRuntimeManager
from scripts.analytics.sessions import AnalyticsSessionManager, CANONICAL_TITLE
from scripts.analytics.service import AnalyticsService
from scripts.analytics.store import ContextStore


class FakeOpenCode:
    def __init__(self):
        self.base_url = "http://127.0.0.1:41999"
        self.sessions = {}
        self.context = []
        self.prompts = []
        self.next_id = 0
        self.guard = threading.Lock()

    def health(self):
        return True

    def list_sessions(self):
        with self.guard:
            return [dict(v) for v in self.sessions.values()]

    def get_session(self, session_id):
        with self.guard:
            row = self.sessions.get(session_id)
            return dict(row) if row else None

    def create_session(self, title, parent_id=None):
        with self.guard:
            self.next_id += 1
            row = {"id": f"ses-{self.next_id}", "title": title,
                   "parentID": parent_id, "updatedAt": str(self.next_id)}
            self.sessions[row["id"]] = row
            return dict(row)

    def add_context(self, session_id, text):
        self.context.append((session_id, text))

    def prompt(self, session_id, text, *, model=None):
        self.prompts.append((session_id, text, model))
        return {"accepted": True}


class ChatFakeOpenCode(FakeOpenCode):
    generation = 1

    def providers(self):
        return {"connected": ["github-copilot"], "all": [{"id": "github-copilot",
            "name": "GitHub Copilot", "models": {"luna-6-verified": {
                "id": "luna-6-verified", "name": "Luna 6"}}}]}

    def prompt(self, session_id, text, *, model=None):
        self.prompts.append((session_id, text, model))
        return {"parts": [{"type": "text", "text": "Analytics answer from the shared Anvil runtime."}]}


class RuntimeHTTPHandler(BaseHTTPRequestHandler):
    generation = 1
    requests = []
    message_reads = 0
    provider_padding = ""

    def log_message(self, *_args):
        pass

    def _read(self):
        size = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(size)) if size else None

    def _reply(self, value, status=200):
        raw = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlsplit(self.path).path
        RuntimeHTTPHandler.requests.append(("GET", self.path, None))
        if path == "/global/health":
            self._reply({"healthy": True})
        elif path == "/provider" or path == "/api/provider":
            self._reply({"connected": ["github-copilot"], "all": [{"id": "github-copilot",
                "name": "GitHub Copilot", "models": {"luna-6-verified": {
                    "id": "luna-6-verified", "name": "Luna 6"}}}], "padding": self.provider_padding})
        elif path == "/oversized":
            self._reply({"padding": self.provider_padding})
        elif path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://example.com/collect")
            self.end_headers()
        elif path.endswith("/message"):
            RuntimeHTTPHandler.message_reads += 1
            message_id = "assistant-old" if RuntimeHTTPHandler.message_reads == 1 else "assistant-new"
            self._reply([{"info": {"id": message_id, "role": "assistant"},
                          "parts": [{"type": "text", "text": "response text"}]}])
        elif path.endswith("/session") or path == "/session":
            self._reply({"items": [{"id": "ses-existing", "title": "existing"}]}
                        if self.generation == 2 else [{"id": "ses-existing", "title": "existing"}])
        elif path.endswith("/ses-existing"):
            self._reply({"id": "ses-existing", "title": "existing"})
        else:
            self._reply({}, 404)

    def do_POST(self):
        body = self._read()
        RuntimeHTTPHandler.requests.append(("POST", self.path, body))
        path = urlsplit(self.path).path
        if path.endswith("/wait"):
            self.send_response(204)
            self.end_headers()
        elif path in {"/session", "/api" + "/session"}:
            created = {"id": "ses-created", "title": body.get("title"), "parentID": body.get("parentID")}
            self._reply({"data": created} if self.generation == 2 else created)
        elif path.endswith("/message") or path.endswith("/synthetic") or path.endswith("/prompt"):
            self._reply({"accepted": True})
        else:
            self._reply({}, 404)


class OpenCodeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.paths = AnalyticsPaths.from_root(Path(self.temp.name) / ".anvil", create=True)
        self.store = ContextStore(paths=self.paths)

    def test_databricks_cli_tls_errors_are_classified_without_echoing_provider_text(self):
        from scripts.databricks import _structured_cli_error
        self.assertEqual(_structured_cli_error("x509: certificate signed by unknown authority"),
                         "TLS_TRUST_FAILED")
        self.assertEqual(_structured_cli_error("certificate verify failed: unable to get local issuer certificate"),
                         "TLS_TRUST_FAILED")

    def test_analytics_model_policy_fails_closed_on_provider_discovery_or_model_miss(self):
        from scripts.analytics.service import _resolve_analytics_model
        class DiscoveryFailure:
            def providers(self):
                raise OSError("provider endpoint unavailable")
        with self.assertRaises(ProviderError) as discovery:
            _resolve_analytics_model(DiscoveryFailure())
        self.assertEqual(discovery.exception.code, "PROVIDER_DISCOVERY_FAILED")
        class MissingLuna:
            def providers(self):
                return {"connected": ["github-copilot"], "all": [{"id": "github-copilot",
                    "name": "GitHub Copilot", "models": {"other-model": {"id": "other-model", "name": "Other"}}}]}
        with self.assertRaises(ProviderError) as missing:
            _resolve_analytics_model(MissingLuna())
        self.assertEqual(missing.exception.code, "MODEL_UNAVAILABLE")

    def test_opencode_health_probe_is_short_and_runtime_retries_a_swallowed_startup_probe(self):
        adapter = create_adapter(1, "http://127.0.0.1:41999", self.paths.workspace)
        with patch("scripts.analytics.opencode._LOCAL_OPENER.open", side_effect=TimeoutError("first probe stalled")) as opened:
            self.assertFalse(adapter.health())
        self.assertEqual(opened.call_args.kwargs["timeout"], 0.5)


        executable = self.paths.root / "opencode"
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o700)

        class Process:
            def poll(self):
                return None
            def terminate(self):
                pass
            def wait(self, timeout=None):
                return 0
            def kill(self):
                pass

        class HealthAdapter:
            base_url = "http://127.0.0.1:41999"
            workspace = self.paths.workspace
            generation = 1

            def __init__(self):
                self.calls = 0

            def health(self):
                self.calls += 1
                return self.calls > 1

        health = HealthAdapter()
        manager = AnalyticsRuntimeManager(self.paths, process_factory=lambda *_a, **_k: Process(),
                                          startup_timeout=2)
        with patch("scripts.analytics.runtime.create_adapter", return_value=health), \
             patch("scripts.analytics.runtime.time.sleep", return_value=None):
            result = manager._start_runtime({"executable": str(executable), "generation": 1})
        self.assertTrue(result.startswith("http://127.0.0.1:"))
        self.assertEqual(health.calls, 2)

    def test_provider_discovery_uses_a_larger_route_specific_bounded_response(self):
        RuntimeHTTPHandler.provider_padding = "x" * (2 * 1024 * 1024 + 64)
        self.addCleanup(setattr, RuntimeHTTPHandler, "provider_padding", "")
        server = ThreadingHTTPServer(("127.0.0.1", 0), RuntimeHTTPHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            adapter = create_adapter(1, f"http://127.0.0.1:{server.server_port}", self.paths.workspace)
            catalog = adapter.providers()
            self.assertEqual(catalog["connected"], ["github-copilot"])
            with self.assertRaises(ProviderError):
                adapter._request("GET", "/oversized")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_dead_persisted_runtime_discards_adapter_and_starts_a_new_runtime(self):
        executable = self.paths.root / "opencode"
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o700)
        self.paths.runtime.write_text(json.dumps({
            "schema_version": 1,
            "base_url": "http://127.0.0.1:41999",
            "runtime_generation": 1,
            "executable": str(executable),
            "canonical_session_id": "session-kept",
        }), encoding="utf-8")

        class Adapter:
            def __init__(self, base_url, healthy):
                self.base_url = base_url
                self.healthy = healthy

            def health(self):
                return self.healthy

        dead = Adapter("http://127.0.0.1:41999", False)
        restarted = []
        created = []

        def create(_generation, base_url, _workspace):
            value = dead if base_url.endswith(":41999") else Adapter(base_url, True)
            if value is not dead:
                restarted.append(value)
            created.append(value)
            return value

        class Process:
            def poll(self):
                return None
            def terminate(self):
                pass
            def wait(self, timeout=None):
                return 0
            def kill(self):
                pass

        manager = AnalyticsRuntimeManager(
            self.paths,
            runtime={"supported": True, "generation": 1, "version": "1.19.0",
                     "executable": str(executable)},
            process_factory=lambda *_a, **_k: Process(), startup_timeout=2,
        )
        with patch("scripts.analytics.runtime.create_adapter", side_effect=create), \
             patch("scripts.analytics.runtime.time.sleep", return_value=None):
            result = manager.ensure()
        self.assertNotEqual(result["base_url"], "http://127.0.0.1:41999")
        self.assertEqual(created, [dead, restarted[0]])
        self.assertIs(manager.adapter, restarted[0])
        self.assertEqual(manager.adapter.base_url, result["base_url"])
        self.assertEqual(result["canonical_session_id"], "session-kept")

    def test_open_code_adapters_select_v1_and_v2_routes_and_payloads(self):
        for generation in (1, 2):
            with self.subTest(generation=generation):
                RuntimeHTTPHandler.generation = generation
                RuntimeHTTPHandler.requests = []
                RuntimeHTTPHandler.message_reads = 0
                server = ThreadingHTTPServer(("127.0.0.1", 0), RuntimeHTTPHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                adapter = create_adapter(generation, f"http://127.0.0.1:{server.server_port}",
                                         self.paths.workspace)
                try:
                    self.assertTrue(adapter.health())
                    self.assertEqual(adapter.list_sessions()[0]["id"], "ses-existing")
                    created = adapter.create_session("task", parent_id="ses-parent")
                    self.assertEqual(created["id"], "ses-created")
                    adapter.add_context("ses-created", "context")
                    selected_model = {"providerID": "opencode", "modelID": "gpt-6-luna"}
                    accepted = adapter.prompt("ses-created", "hello", model=selected_model)
                    if generation == 2:
                        self.assertTrue(accepted.get("accepted"))
                        answer = adapter.wait_for_response("ses-created", timeout=5)
                        self.assertEqual(answer["info"]["id"], "assistant-new")
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join()
                paths = [request[1] for request in RuntimeHTTPHandler.requests]
                prefix = "/api" if generation == 2 else ""
                self.assertIn(prefix + "/session", paths)
                self.assertTrue(any(path.endswith("/prompt") for path in paths) if generation == 2
                                else any(path.endswith("/message") for path in paths))
                if generation == 2:
                    self.assertIn("/api/session/ses-created/wait", paths)
                prompt_request = next(req for req in RuntimeHTTPHandler.requests
                                      if req[0] == "POST" and req[2] and req[2].get("model"))
                self.assertEqual(prompt_request[2]["model"], selected_model)
                creation = next(req for req in RuntimeHTTPHandler.requests
                                if req[0] == "POST" and urlsplit(req[1]).path == prefix + "/session")
                self.assertEqual(creation[2]["parentID"], "ses-parent")
                self.assertEqual(urlsplit(paths[0]).path, "/global/health")

    def test_adapter_is_loopback_only_and_does_not_follow_redirects(self):
        with self.assertRaises(ValidationError):
            create_adapter(1, "http://example.com:4096", self.paths.workspace)
        server = ThreadingHTTPServer(("127.0.0.1", 0), RuntimeHTTPHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            adapter = create_adapter(1, f"http://127.0.0.1:{server.server_port}", self.paths.workspace)
            with self.assertRaises(ProviderError) as raised:
                adapter._request("GET", "/redirect")
            self.assertIn("HTTP 302", str(raised.exception))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_ensure_canonical_is_idempotent_and_rehydrates_once(self):
        adapter = FakeOpenCode()
        runtime = AnalyticsRuntimeManager(self.paths,
            runtime={"supported": True, "generation": 1, "version": "1.19.0", "executable": "/fake/opencode"},
            base_url=adapter.base_url, adapter=adapter)
        sessions = AnalyticsSessionManager(runtime, self.store, paths=self.paths)
        first = sessions.ensure_canonical()
        second = sessions.ensure_canonical()
        self.assertTrue(first["created"])
        self.assertFalse(first["recovered"])
        self.assertEqual(first["session_id"], second["session_id"])
        self.assertFalse(second["created"])
        self.assertEqual(len(adapter.sessions), 1)
        self.assertEqual(len(adapter.context), 1)
        state = json.loads(self.paths.runtime.read_text())
        self.assertEqual(state["canonical_session_id"], first["session_id"])
        self.assertEqual(state["workspace"], str(self.paths.workspace))

    def test_crash_before_runtime_identity_persist_reconciles_by_title(self):
        adapter = FakeOpenCode()
        existing = adapter.create_session(CANONICAL_TITLE)
        runtime = AnalyticsRuntimeManager(self.paths,
            runtime={"supported": True, "generation": 2, "version": "2.0.0", "executable": "/fake/opencode"},
            base_url=adapter.base_url, adapter=adapter)
        result = AnalyticsSessionManager(runtime, self.store, paths=self.paths).ensure_canonical()
        self.assertEqual(result["session_id"], existing["id"])
        self.assertTrue(result["recovered"])
        self.assertFalse(result["created"])
        self.assertEqual(len(adapter.sessions), 1)
        self.assertEqual(len(adapter.context), 1)

    def test_lost_canonical_is_recreated_and_sqlite_context_survives(self):
        adapter = FakeOpenCode()
        self.store.knowledge_add(KnowledgeItem("finding", "table", "known behavior"))
        runtime = AnalyticsRuntimeManager(self.paths,
            runtime={"supported": True, "generation": 1, "version": "1.19.0", "executable": "/fake/opencode"},
            base_url=adapter.base_url, adapter=adapter)
        sessions = AnalyticsSessionManager(runtime, self.store, paths=self.paths,
                                           context=ContextResolver(self.store))
        first = sessions.ensure_canonical()
        adapter.sessions.pop(first["session_id"])
        second = sessions.recover_canonical()
        self.assertTrue(second["created"])
        self.assertNotEqual(first["session_id"], second["session_id"])
        self.assertIn("known behavior", adapter.context[-1][1])

    def test_task_sessions_are_children_and_distill_durable_findings(self):
        adapter = FakeOpenCode()
        runtime = AnalyticsRuntimeManager(self.paths,
            runtime={"supported": True, "generation": 2, "version": "2.0.0", "executable": "/fake/opencode"},
            base_url=adapter.base_url, adapter=adapter)
        sessions = AnalyticsSessionManager(runtime, self.store, paths=self.paths)
        task = sessions.create_task_session("Investigate revenue")
        self.assertEqual(adapter.sessions[task["session_id"]]["parentID"], task["parent_session_id"])
        result = sessions.finish_task_session(task["session_id"], summary="Revenue is booked in UTC.",
                                              findings=[KnowledgeItem("behavior", "revenue", "timezone is UTC")])
        self.assertEqual(result["distilled_items"], 2)
        self.assertEqual(len(self.store.knowledge_recent(limit=5)), 2)
        self.assertEqual(sessions.store_session(task["session_id"])["state"], "COMPLETED")
        with self.assertRaises(ValidationError):
            sessions.create_task_session(CANONICAL_TITLE)

    def test_ask_anvil_uses_global_context_canonical_session_and_distills_deep_work(self):
        adapter = ChatFakeOpenCode()
        runtime = AnalyticsRuntimeManager(self.paths,
            runtime={"supported": True, "generation": 1, "version": "1.19.0", "executable": "/fake/opencode"},
            base_url=adapter.base_url, adapter=adapter)
        sessions = AnalyticsSessionManager(runtime, self.store, paths=self.paths)
        self.store.knowledge_add(KnowledgeItem("finding", "orders", "failed orders cluster after midnight UTC"))
        service = AnalyticsService(paths=self.paths, store=self.store, runtime=runtime,
                                   sessions=sessions, identity=lambda: {"display_name": "Test"},
                                   web_root=Path(self.temp.name))
        try:
            result = service.ask_anvil("Explain the failures", context={
                "table": "main.ops.orders", "sql": "SELECT status FROM main.ops.orders LIMIT 10",
                "columns": ["status"], "preview": {"columns": ["status"], "rows": [["failed"]]},
            })
            self.assertIn("Analytics answer", result["text"])
            self.assertEqual(adapter.prompts[0][2], {"providerID": "github-copilot", "modelID": "luna-6-verified"})
            self.assertIn("failed orders cluster after midnight UTC", adapter.prompts[0][1])
            self.assertIn("main.ops.orders", adapter.prompts[0][1])
            canonical_id = adapter.prompts[0][0]
            deep = service.ask_anvil("Check the incident timeline", deep_investigation=True)
            self.assertEqual(deep["session"], "investigation")
            self.assertNotEqual(adapter.prompts[1][0], canonical_id)
            self.assertIn("incident timeline", adapter.prompts[1][1])
            self.assertEqual(self.store.knowledge_recent(limit=5)[0]["kind"], "investigation")
            state = json.loads(self.paths.runtime.read_text(encoding="utf-8"))
            self.assertEqual(state["canonical_session_id"], canonical_id)
            self.assertEqual(adapter.context[-1][0], canonical_id)
        finally:
            service.close()

    def test_ask_anvil_surfaces_provider_discovery_failure_before_creating_or_prompting_session(self):
        class NoProviderCatalog(ChatFakeOpenCode):
            def providers(self):
                raise OSError("private runtime detail")
        adapter = NoProviderCatalog()
        runtime = AnalyticsRuntimeManager(self.paths,
            runtime={"supported": True, "generation": 1, "version": "1.19.0", "executable": "/fake/opencode"},
            base_url=adapter.base_url, adapter=adapter)
        sessions = AnalyticsSessionManager(runtime, self.store, paths=self.paths)
        service = AnalyticsService(paths=self.paths, store=self.store, runtime=runtime,
                                   sessions=sessions, web_root=Path(self.temp.name))
        try:
            with self.assertRaises(ProviderError) as raised:
                service.ask_anvil("Explain this data")
            self.assertEqual(raised.exception.code, "PROVIDER_DISCOVERY_FAILED")
            self.assertEqual(adapter.prompts, [])
            self.assertEqual(adapter.sessions, {})
        finally:
            service.close()

    def test_service_startup_warms_canonical_session_and_keeps_ui_usable_when_runtime_is_missing(self):
        adapter = FakeOpenCode()
        runtime = AnalyticsRuntimeManager(self.paths,
            runtime={"supported": True, "generation": 1, "version": "1.19.0", "executable": "/fake/opencode"},
            base_url=adapter.base_url, adapter=adapter)
        sessions = AnalyticsSessionManager(runtime, self.store, paths=self.paths)
        service = AnalyticsService(paths=self.paths, store=self.store, runtime=runtime,
                                   sessions=sessions, web_root=Path(self.temp.name))
        self.addCleanup(service.close)
        with patch("scripts.analytics.service.create_adapter", return_value=adapter):
            ready = service.initialize_runtime()
        self.assertEqual(ready["runtime"]["status"], "READY")
        self.assertEqual(ready["runtime"]["canonical_session"], "READY")
        self.assertEqual(len(adapter.sessions), 1)

        degraded_service = AnalyticsService(paths=self.paths,
            store=ContextStore(paths=AnalyticsPaths.from_root(Path(self.temp.name) / "other", create=True)),
            web_root=Path(self.temp.name))
        self.addCleanup(degraded_service.close)
        degraded_service.sessions.ensure_canonical = lambda: (_ for _ in ()).throw(
            UnavailableError("OpenCode is unavailable", code="OPENCODE_UNAVAILABLE"))
        degraded = degraded_service.initialize_runtime()
        self.assertEqual(degraded["runtime"]["status"], "DEGRADED")
        self.assertEqual(degraded["runtime"]["error"]["code"], "OPENCODE_UNAVAILABLE")
        self.assertEqual(degraded_service.catalogs()["items"], [])

    def test_concurrent_ensure_creates_one_canonical_session(self):
        adapter = FakeOpenCode()
        runtime = AnalyticsRuntimeManager(self.paths,
            runtime={"supported": True, "generation": 1, "version": "1.19.0", "executable": "/fake/opencode"},
            base_url=adapter.base_url, adapter=adapter)
        managers = [AnalyticsSessionManager(runtime, self.store, paths=self.paths) for _ in range(2)]
        results = []
        errors = []

        def run(manager):
            try:
                results.append(manager.ensure_canonical())
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=run, args=(manager,)) for manager in managers]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(errors, [])
        self.assertEqual(len({row["session_id"] for row in results}), 1)
        self.assertEqual(len(adapter.sessions), 1)


if __name__ == "__main__":
    unittest.main()
