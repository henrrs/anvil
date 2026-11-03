from __future__ import annotations

import shutil
import subprocess
import re
import sys
import threading
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from scripts.analytics.server import ALLOWED_ASSETS
from scripts.analytics_ui_mock import SCENARIOS, make_server

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from managed_config import _analytics_workspace_files  # noqa: E402


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "a":
            self.links.append((tag, dict(attrs)))


class AnalyticsUIMockTests(unittest.TestCase):
    def test_materialization_validation_is_inline_and_all_columns_has_no_extra_gate(self):
        html = (ROOT / "web/analytics/index.html").read_text(encoding="utf-8")
        app = (ROOT / "web/analytics/app.js").read_text(encoding="utf-8")
        self.assertIn('id="materialize-feedback"', html)
        self.assertNotIn("confirm-full-table", html + app)
        self.assertIn('Please select at least one column.', app)
        self.assertIn('Enter a filter for filtered rows.', app)
        start = app.split("async function startMaterialization()", 1)[1].split("async function pollMaterialization", 1)[0]
        self.assertNotIn("toast(", start)

    def test_local_operation_only_disables_conflicting_materialization_action(self):
        app = (ROOT / "web/analytics/app.js").read_text(encoding="utf-8")
        render = app.split("function renderTableWorkspace(workspace)", 1)[1].split("function renderTableOverview", 1)[0]
        self.assertIn('localAction.disabled = Boolean(workspace.activeOperation)', render)
        self.assertNotIn("tab.disabled", render)
        self.assertIn('operation.resume_available ? "Resume" : "Retry"', app)

    def test_ask_anvil_badge_shows_resolved_model_and_provider_without_scattered_model_ids(self):
        html = (ROOT / "web/analytics/index.html").read_text(encoding="utf-8")
        app = (ROOT / "web/analytics/app.js").read_text(encoding="utf-8")
        service = (ROOT / "scripts/analytics/service.py").read_text(encoding="utf-8")
        self.assertIn("Luna 6 · GitHub Copilot", html)
        self.assertIn('payload.model.provider_name', app)
        self.assertIn('modelPolicy.provider_preference', app)
        self.assertIn('preferred_provider_name: str = "GitHub Copilot"', service)
        self.assertNotIn('model_id: str = "gpt-6-luna"', service)

    def test_production_ui_uses_http_adapter_and_has_no_external_brand_link(self) -> None:
        html = (ROOT / "web/analytics/index.html").read_text(encoding="utf-8")
        parser = LinkParser()
        parser.feed(html)
        self.assertNotIn("github.com", html.casefold())
        self.assertFalse(any("github.com" in str(attrs.get("href", "")).casefold()
                             for _, attrs in parser.links))
        self.assertNotIn("href=\"#\"", html)
        self.assertIn("/api.js", html)
        self.assertNotIn("/dev/", html)
        footer = html.split("<footer", 1)[1].split("</footer>", 1)[0]
        self.assertIn('id="health-summary-label"', footer)
        self.assertIn('id="health-menu"', footer)
        self.assertNotIn('id="status-catalog-count"', footer)
        self.assertIn('id="operations-label"', footer)
        self.assertNotIn("<a", footer)

    def test_final_polish_keeps_clear_action_scoped_and_context_compact(self) -> None:
        html = (ROOT / "web/analytics/index.html").read_text(encoding="utf-8")
        app = (ROOT / "web/analytics/app.js").read_text(encoding="utf-8")
        css = (ROOT / "web/analytics/styles.css").read_text(encoding="utf-8")

        self.assertIn('id="clear-chat"', html)
        self.assertIn('title="Clear conversation"', html)
        self.assertIn('aria-label="Clear conversation"', html)
        self.assertIn('aria-controls="clear-chat-confirm"', html)
        self.assertIn('id="cancel-clear-chat"', html)
        self.assertIn('id="confirm-clear-chat"', html)
        self.assertIn("This starts a new Ask Anvil conversation", html)
        self.assertIn('class="context-heading-label"', html)
        self.assertNotIn('id="context-source"', html)
        self.assertNotIn('id="status-catalog-count"', html)
        self.assertIn('id="catalog-count"', html)

        self.assertIn('TRASH: "M4 7h16', app)
        self.assertIn('close.append(icon("CLOSE"))', app)
        self.assertIn('event?.stopPropagation()', app)
        clear_action = app.split('$("confirm-clear-chat").addEventListener("click", async () => {', 1)[1].split('});', 1)[0]
        self.assertIn('post("/api/anvil/chat/clear")', clear_action)
        self.assertIn('$("chat-thread").replaceChildren()', clear_action)

        self.assertIn(".workspace-tab.active .workspace-tab-content::after", css)
        self.assertIn(".table-tab.active .table-tab-content::after", css)
        self.assertIn(".workspace-tab-close:hover", css)
        self.assertIn(".workspace-tab-close:focus-visible", css)
        self.assertIn(".table-tab:active", css)
        self.assertIn(".favorite-button:hover", css)
        self.assertIn(".clear-chat-confirm[hidden]", css)
        self.assertIn("var(--space-3) 0 var(--space-1)", css)

    def test_active_indicator_is_bound_to_inner_tab_content(self) -> None:
        html = (ROOT / "web/analytics/index.html").read_text(encoding="utf-8")
        mock_html = (ROOT / "web/analytics/dev/index.html").read_text(encoding="utf-8")
        app = (ROOT / "web/analytics/app.js").read_text(encoding="utf-8")
        css = (ROOT / "web/analytics/styles.css").read_text(encoding="utf-8")

        self.assertEqual(html.count('class="table-tab-content"'), 5)
        self.assertEqual(mock_html.count('class="table-tab-content"'), 5)
        self.assertIn('node("span", "workspace-tab-content")', app)
        self.assertIn("home.append(homeContent)", app)
        self.assertIn("tab.append(content)", app)
        self.assertIn(".workspace-tab.active .workspace-tab-content::after", css)
        self.assertIn(".table-tab.active .table-tab-content::after", css)
        self.assertNotIn(".workspace-tab.active::after", css)
        self.assertNotIn(".table-tab.active::after", css)
        self.assertIn("align-self: stretch", css.split(".workspace-tab-content {", 1)[1].split("}", 1)[0])
        self.assertIn("height: 100%", css.split(".workspace-tab {", 1)[1].split("}", 1)[0])

    def test_query_editor_results_splitter_is_accessible_bounded_and_persistent(self) -> None:
        app = (ROOT / "web/analytics/app.js").read_text(encoding="utf-8")
        css = (ROOT / "web/analytics/styles.css").read_text(encoding="utf-8")
        for relative in ("web/analytics/index.html", "web/analytics/dev/index.html"):
            html = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn('id="query-split"', html)
            self.assertIn('id="query-editor-panel"', html)
            self.assertIn('id="query-results-panel"', html)
            self.assertIn('id="query-splitter" role="separator"', html)
            self.assertIn('aria-orientation="horizontal"', html)
            self.assertIn('tabindex="0"', html)
        self.assertIn('"analytics.query.splitRatio"', app)
        self.assertIn('"ArrowUp", "ArrowDown"', app)
        self.assertIn('"pointerdown"', app)
        self.assertIn('"pointermove"', app)
        self.assertIn('"pointerup"', app)
        self.assertIn('Math.max(0.25, 132 / height)', app)
        self.assertIn('1 - 116 / height', app)
        self.assertIn('dispatchEvent(new Event("anvil:analytics-editor-resize"))', app)
        self.assertIn('overflow: auto', css.split(".results-area {", 1)[1].split("}", 1)[0])

    def test_warehouse_is_a_select_and_never_a_manual_identifier_field(self) -> None:
        html = (ROOT / "web/analytics/index.html").read_text(encoding="utf-8")
        self.assertIn('<select id="warehouse-select"', html)
        self.assertNotIn('id="warehouse-id"', html)
        self.assertNotIn('id="warehouse-name"', html)
        self.assertNotIn('placeholder="Warehouse ID"', html)

    def test_readability_structure_and_progressive_disclosure(self) -> None:
        html = (ROOT / "web/analytics/index.html").read_text(encoding="utf-8")
        css = (ROOT / "web/analytics/styles.css").read_text(encoding="utf-8")
        self.assertIn('id="home-continue-section"', html)
        self.assertIn('id="home-pinned-section"', html)
        self.assertIn('id="home-local-section"', html)
        self.assertIn('id="home-operations-section"', html)
        self.assertNotIn('class="health-strip"', html)
        self.assertNotIn('class="quick-sections"', html)
        self.assertEqual(html.count('data-catalog-filter='), 3)
        self.assertIn('<details class="chat-options">', html)
        self.assertIn('--type-body: .875rem', css)
        self.assertIn('@media (min-width: 3600px)', css)
        self.assertIn('max-width: var(--reading-width)', css)
        self.assertNotIn('transform: scale(', css)
        self.assertNotIn('zoom:', css)

    def test_catalog_icons_have_no_image_placeholders_or_unstyled_star_buttons(self) -> None:
        html = (ROOT / "web/analytics/index.html").read_text(encoding="utf-8")
        app = (ROOT / "web/analytics/app.js").read_text(encoding="utf-8")
        css = (ROOT / "web/analytics/styles.css").read_text(encoding="utf-8")
        self.assertNotIn('<img', html)
        self.assertIn('document.createElementNS("http://www.w3.org/2000/svg", "svg")', app)
        self.assertIn('svg.setAttribute("stroke", "currentColor")', app)
        self.assertIn('paths.TABLE', app)  # unknown object types get a safe fallback
        self.assertIn('star.append(icon(favorite ? "STAR_FILLED" : "STAR"))', app)
        self.assertIn('.tree-star { display: grid;', css)
        self.assertIn('color: var(--muted); background: transparent; cursor: pointer;', css)
        for scenario in ("home-populated", "table-remote", "table-local", "query-results",
                         "ask-anvil", "large-catalog", "active-operation", "degraded"):
            self.assertIn(scenario, SCENARIOS)

    def test_production_assets_and_lifecycle_manifest_exclude_dev_mock(self) -> None:
        self.assertEqual(ALLOWED_ASSETS, {"index.html", "api.js", "app.js", "styles.css"})
        self.assertFalse(any("dev/" in item for item in ALLOWED_ASSETS))
        files = _analytics_workspace_files()
        self.assertIn("web/analytics/api.js", files)
        self.assertFalse(any(item.startswith("web/analytics/dev/") for item in files))

    def test_production_and_mock_pages_provide_every_application_mount(self) -> None:
        app = (ROOT / "web/analytics/app.js").read_text(encoding="utf-8")
        references = set(re.findall(r'\$\("([^"]+)"\)', app))
        for relative in ("web/analytics/index.html", "web/analytics/dev/index.html"):
            html = (ROOT / relative).read_text(encoding="utf-8")
            ids = set(re.findall(r'\bid="([^"]+)"', html))
            self.assertFalse(references - ids, f"{relative} is missing app mounts: {sorted(references - ids)}")

    def test_mock_scenarios_and_large_catalog_are_deterministic_and_paginated(self) -> None:
        if not shutil.which("node"):
            self.skipTest("Node.js is not installed; mock behavior is covered by the browser manually")
        mock_path = ROOT / "web/analytics/dev/mock-api.js"
        for script in (ROOT / "web/analytics/api.js", ROOT / "web/analytics/app.js",
                       ROOT / "web/analytics/dev/mock-api.js", ROOT / "web/analytics/dev/mock-entry.js"):
            checked = subprocess.run(["node", "--check", str(script)], cwd=ROOT,
                                     text=True, capture_output=True, check=False)
            self.assertEqual(checked.returncode, 0, f"{script}: {checked.stderr}")
        program = r"""
const fs = require('fs');
const vm = require('vm');
const window = { location: { origin: 'http://127.0.0.1:8766', search: '' }, setTimeout };
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), { window, URL, URLSearchParams, Date, Map, setTimeout });
(async () => {
  const healthy = new window.MockAnalyticsApi('healthy');
  const inventory = await healthy.request('/api/warehouses');
  if (inventory.warehouses.length !== 4 || inventory.warehouses.filter(x => x.state === 'RUNNING').length !== 2) throw Error('warehouse fixture mismatch');
  const page = await new window.MockAnalyticsApi('large-catalog').request('/api/catalog?limit=100&offset=100');
  if (page.items.length !== 100 || !page.has_more || page.next_offset !== 200) throw Error('catalog pagination mismatch');
  const offline = await new window.MockAnalyticsApi('offline').request('/api/warehouses');
  if (offline.status !== 'STALE' || !offline.error) throw Error('offline scenario mismatch');
  const noWarehouses = await new window.MockAnalyticsApi('no-warehouses').request('/api/warehouses');
  if (noWarehouses.status !== 'EMPTY' || noWarehouses.warehouses.length) throw Error('empty warehouse mismatch');
  const refresh = await healthy.request('/api/warehouses/refresh', { method: 'POST', body: '{}' });
  if (refresh.status !== 'READY') throw Error('warehouse refresh mismatch');
  let chunks = 0;
  await healthy.streamChat({ prompt: 'How do I explore?' }, (event) => { if (event === 'chunk') chunks += 1; });
  if (!chunks) throw Error('chat fixture did not stream');
  let degraded = false;
  try { await new window.MockAnalyticsApi('degraded').streamChat({ prompt: 'Explain' }, () => {}); }
  catch (error) { degraded = error.code === 'RUNTIME_UNAVAILABLE'; }
  if (!degraded) throw Error('degraded chat did not report runtime status');
  const operation = await healthy.request('/api/materializations', { method: 'POST', body: JSON.stringify({ source_name: 'main.finance.transactions' }) });
  if (!operation.operation_id || operation.state !== 'RUNNING') throw Error('materialization scenario mismatch');
  process.stdout.write('mock scenario contracts pass');
})().catch((error) => { console.error(error); process.exitCode = 1; });
"""
        result = subprocess.run(["node", "-e", program, str(mock_path)], cwd=ROOT,
                                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("mock scenario contracts pass", result.stdout)

    def test_static_mock_server_is_loopback_only_and_has_no_backend_api(self) -> None:
        with self.assertRaises(ValueError):
            make_server(host="0.0.0.0", port=0)
        self.assertIn("large-catalog", SCENARIOS)
        server = make_server(port=0, scenario="healthy")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        root = f"http://127.0.0.1:{server.server_port}"
        with urlopen(root + "/dev/") as response:
            page = response.read().decode("utf-8")
        self.assertIn("Development Mock", page)
        self.assertIn("/dev/mock-api.js", page)
        with self.assertRaises(HTTPError) as missing_api:
            urlopen(root + "/api/me")
        self.assertEqual(missing_api.exception.code, 404)
        missing_api.exception.close()


if __name__ == "__main__":
    unittest.main()
