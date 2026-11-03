#!/usr/bin/env python3
"""Certify the development mock UI in Firefox and save review screenshots.

This script uses only the local static mock and a local WebDriver. It never calls
the Analytics service or Databricks. Run it separately from the offline make test
suite when Firefox and geckodriver are available.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from analytics_ui_mock import make_server


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "analytics-local-reliability" / "ui" / "final"
SPLITTER_OUTPUT = OUTPUT / "query-splitter"
SIZES = ((1366, 768), (1920, 1080), (2560, 1440), (3840, 2160))
VIEWS = {
    "healthy": "home",
    "home-populated": "home",
    "table-remote": "table-overview",
    "table-local": "local-copy",
    "query-results": "query-results",
    "ask-anvil": "ask-anvil",
}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Browser:
    def __init__(self, *, scale: float = 1.0):
        self.scale = scale
        existing = os.environ.get("ANVIL_UI_WEBDRIVER_PORT")
        self.port = int(existing) if existing else free_port()
        self.process = None if existing else subprocess.Popen(["geckodriver", "--port", str(self.port)],
                                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.session = ""
        try:
            for _ in range(50):
                try:
                    self.call("GET", "/status")
                    break
                except (URLError, ConnectionError):
                    time.sleep(.1)
            else:
                raise RuntimeError("geckodriver did not start")
            options: dict[str, object] = {"args": ["-headless"]}
            if scale != 1.0:
                options["prefs"] = {"layout.css.devPixelsPerPx": str(scale)}
            value = self.call("POST", "/session", {"capabilities": {"alwaysMatch": {
                "browserName": "firefox", "moz:firefoxOptions": options}}})
            self.session = value["sessionId"]
        except Exception:
            self.close()
            raise

    def call(self, method: str, path: str, payload: dict | None = None):
        data = json.dumps(payload).encode() if payload is not None else None
        request = Request(f"http://127.0.0.1:{self.port}{path}", data=data,
                          headers={"Content-Type": "application/json"}, method=method)
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
        if "value" not in result:
            raise RuntimeError(f"WebDriver response has no value: {result}")
        return result["value"]

    def command(self, method: str, path: str, payload: dict | None = None):
        return self.call(method, f"/session/{self.session}{path}", payload)

    def load(self, url: str, width: int = 1920, height: int = 1080):
        self.command("POST", "/window/rect", {"width": width, "height": height})
        if self.scale == 1.0:
            for _ in range(3):
                viewport = self.js("return {width: innerWidth, height: innerHeight};")
                if viewport == {"width": width, "height": height}:
                    break
                outer = self.command("GET", "/window/rect")
                self.command("POST", "/window/rect", {
                    "width": outer["width"] + width - viewport["width"],
                    "height": outer["height"] + height - viewport["height"],
                })
            else:
                raise AssertionError(f"could not set exact viewport {width}x{height}: {viewport}")
        self.command("POST", "/url", {"url": url})
        for _ in range(100):
            if self.js("return document.documentElement.dataset.mockReady === 'true';"):
                return
            time.sleep(.05)
        raise AssertionError(f"mock scenario did not finish: {url}")

    def js(self, script: str):
        return self.command("POST", "/execute/sync", {"script": script, "args": []})

    def screenshot(self, name: str, output: Path = OUTPUT) -> None:
        output.mkdir(parents=True, exist_ok=True)
        image = base64.b64decode(self.command("GET", "/screenshot"))
        if image[:8] != b"\x89PNG\r\n\x1a\n":
            raise AssertionError(f"{name}: browser did not return PNG")
        if self.scale == 1.0:
            expected = tuple(map(int, name.rsplit("-", 1)[-1].removesuffix(".png").split("x")))
            actual = (int.from_bytes(image[16:20], "big"), int.from_bytes(image[20:24], "big"))
            if actual != expected:
                raise AssertionError(f"{name}: screenshot is {actual}, expected {expected}")
        (output / name).write_bytes(image)

    def close(self) -> None:
        if self.session:
            try:
                self.command("DELETE", "")
            except Exception:
                pass
        if self.process is not None:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except PermissionError:
                # Snap-packaged geckodriver can outlive its launcher in a restricted namespace.
                pass
            except subprocess.TimeoutExpired:
                try:
                    self.process.kill()
                    self.process.wait()
                except PermissionError:
                    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def certify_active_indicator(browser: Browser, selector: str, content_selector: str, scroller_selector: str, label: str) -> None:
    result = browser.js(f"""
      const tab = document.querySelector({json.dumps(selector)});
      const content = tab?.querySelector({json.dumps(content_selector)});
      const scroller = document.querySelector({json.dumps(scroller_selector)});
      if (!tab || !content || !scroller) return null;
      const before = tab.getBoundingClientRect();
      const wasActive = tab.classList.contains('active');
      tab.classList.toggle('active', !wasActive);
      const during = tab.getBoundingClientRect();
      tab.classList.toggle('active', wasActive);
      const after = tab.getBoundingClientRect();
      const contentRect = content.getBoundingClientRect();
      const line = getComputedStyle(content, '::after');
      const lineHeight = parseFloat(line.height);
      const lineLeft = parseFloat(line.left);
      const lineRight = parseFloat(line.right);
      const lineBottom = parseFloat(line.bottom);
      const computedLineWidth = parseFloat(line.width);
      const lineWidth = Number.isFinite(computedLineWidth) ? computedLineWidth : contentRect.width - lineLeft - lineRight;
      const scrollRect = scroller.getBoundingClientRect();
      const trackLeft = contentRect.left + lineLeft;
      const trackRight = contentRect.right - lineRight;
      const trackBottom = contentRect.bottom - lineBottom;
      const trackTop = trackBottom - lineHeight;
      const close = tab.closest('.workspace-tab-wrap')?.querySelector('.workspace-tab-close');
      const closeRect = close?.getBoundingClientRect();
      return {{content: line.content, height: lineHeight, left: lineLeft, right: lineRight,
        bottom: lineBottom, width: lineWidth, contentWidth: contentRect.width, tabWidth: after.width,
        contentAligned: Math.abs(trackLeft - contentRect.left) <= 4 && Math.abs(trackRight - contentRect.right) <= 4
          && Math.abs(lineWidth - contentRect.width) <= 6,
        closeExcluded: !closeRect || trackRight < closeRect.left,
        trackVisible: trackLeft >= scrollRect.left - 1
          && trackRight <= scrollRect.right + 1 && trackTop >= scrollRect.top - 1
          && trackBottom <= scrollRect.bottom + 1 && trackTop >= after.top && trackBottom <= after.bottom,
        noShift: Math.abs(before.width - during.width) < .1 && Math.abs(before.height - during.height) < .1
          && Math.abs(before.width - after.width) < .1 && Math.abs(before.height - after.height) < .1
          && Math.abs(before.left - after.left) < .1 && Math.abs(before.top - after.top) < .1}};
    """)
    require(result is not None, f"{label}: active tab, content group, or scroll container is missing")
    require(result["content"] != "none" and 1.5 <= result["height"] <= 2.5 and abs(result["left"]) <= 4
            and abs(result["right"]) <= 4 and result["bottom"] >= 0 and result["width"] > 24,
            f"{label}: active underline has invalid geometry: {result}")
    require(result["contentAligned"], f"{label}: underline does not follow the icon-and-label group: {result}")
    require(result["closeExcluded"], f"{label}: underline includes the close-button area: {result}")
    require(result["trackVisible"], f"{label}: active underline is clipped: {result}")
    require(result["noShift"], f"{label}: active state changed tab geometry: {result}")
    print(f"PASS {label}: underline {result['width']:.1f}px, content {result['contentWidth']:.1f}px, tab {result['tabWidth']:.1f}px")


def certify_clear_conversation(browser: Browser, base: str) -> None:
    browser.load(f"{base}/dev/?scenario=ask-anvil", 1920, 1080)
    result = browser.js("""
      const trigger = document.querySelector('#clear-chat');
      const panel = document.querySelector('#clear-chat-confirm');
      const thread = document.querySelector('#chat-thread');
      const context = document.querySelector('#context-card').textContent;
      const messages = thread.querySelectorAll('.chat-message').length;
      const keys = ['anvil:analytics:recent-tables:v1', 'anvil:analytics:favorites:v1'];
      const stored = keys.map((key) => localStorage.getItem(key));
      trigger.click();
      const opened = !panel.hidden && trigger.getAttribute('aria-expanded') === 'true'
        && thread.querySelectorAll('.chat-message').length === messages;
      document.querySelector('#cancel-clear-chat').click();
      const cancelled = panel.hidden && thread.querySelectorAll('.chat-message').length === messages;
      trigger.click();
      document.querySelector('#confirm-clear-chat').click();
      return {opened, cancelled,
        stillContextual: document.querySelector('#context-card').textContent === context,
        persistentStatePreserved: keys.every((key, index) => localStorage.getItem(key) === stored[index]),
        icon: trigger.querySelector('svg path')?.getAttribute('d')?.startsWith('M4 7h16'),
        label: trigger.getAttribute('aria-label') === 'Clear conversation',
        tooltip: trigger.title === 'Clear conversation'};
    """)
    require(all(result.values()), f"clear conversation behavior regressed: {result}")
    for _ in range(40):
        cleared = browser.js("return document.querySelector('#chat-thread').textContent.includes('Start a new Ask Anvil conversation.') && document.querySelectorAll('#chat-thread .chat-message').length === 0;")
        if cleared:
            break
        time.sleep(.05)
    require(cleared, "clearing chat did not replace the visible canonical conversation")
    for width, height in ((1366, 768), (1920, 1080), (3840, 2160)):
        browser.load(f"{base}/dev/?scenario=ask-anvil", width, height)
        fits = browser.js("""
          document.querySelector('#clear-chat').click();
          const popover = document.querySelector('#clear-chat-confirm').getBoundingClientRect();
          const panel = document.querySelector('#assistant-panel').getBoundingClientRect();
          return popover.left >= panel.left - 1 && popover.right <= panel.right + 1
            && popover.left >= 0 && popover.right <= innerWidth;
        """)
        require(fits, f"clear confirmation is clipped at {width}x{height}")
    browser.load(f"{base}/dev/?scenario=ask-anvil", 1920, 1080)
    require(browser.js("document.querySelector('#clear-chat').click(); return !document.querySelector('#clear-chat-confirm').hidden;"),
            "clear conversation confirmation did not open")
    browser.screenshot("ask-clear-confirm-1920x1080.png")


def certify_tab_close(browser: Browser, base: str) -> None:
    browser.load(f"{base}/dev/?scenario=home-populated&tabs=many", 1920, 1080)
    result = browser.js("""
      const buttons = [...document.querySelectorAll('.workspace-tab-close')];
      const valid = buttons.length === 9 && buttons.every((button) => {
        const label = button.closest('.workspace-tab-wrap').querySelector('.workspace-tab-label').textContent;
        const rect = button.getBoundingClientRect();
        return button.getAttribute('aria-label') === `Close ${label}` && button.title === `Close ${label}`
          && rect.width >= 36 && rect.height >= 36 && button.querySelector('svg') !== null;
      });
      const before = document.querySelector('.workspace-tab.active .workspace-tab-label')?.textContent;
      document.querySelector('[aria-label="Close Query 1"]').click();
      const after = document.querySelector('.workspace-tab.active .workspace-tab-label')?.textContent;
      return {valid, activeUnchanged: before === 'Query 9' && after === before,
        closedCorrectTab: ![...document.querySelectorAll('.workspace-tab-label')].some((label) => label.textContent === 'Query 1'),
        activeVisible: (() => { const tab = document.querySelector('.workspace-tab.active').getBoundingClientRect();
          const viewport = document.querySelector('#workspace-tabs').getBoundingClientRect();
          return tab.left >= viewport.left - 1 && tab.right <= viewport.right + 1; })()};
    """)
    require(all(result.values()), f"workspace tab close or visibility failed: {result}")


def certify_query_splitter(browser: Browser, base: str) -> None:
    for width, height in SIZES:
        browser.load(f"{base}/dev/?scenario=query-results", width, height)
        geometry = browser.js("""
          const split = document.querySelector('#query-split');
          const editor = document.querySelector('#query-editor-panel');
          const divider = document.querySelector('#query-splitter');
          const results = document.querySelector('#query-results-panel');
          if (!split || !editor || !divider || !results) return null;
          const s = split.getBoundingClientRect(), e = editor.getBoundingClientRect();
          const d = divider.getBoundingClientRect(), r = results.getBoundingClientRect();
          return {split: {top:s.top,bottom:s.bottom}, editor:{top:e.top,bottom:e.bottom,height:e.height},
            divider:{top:d.top,bottom:d.bottom,height:d.height}, results:{top:r.top,bottom:r.bottom,height:r.height},
            ratio: parseFloat(getComputedStyle(split).getPropertyValue('--query-editor-ratio')),
            globalOverflow: document.documentElement.scrollWidth > innerWidth + 1};
        """)
        require(geometry is not None, f"query splitter mounts missing at {width}x{height}")
        require(geometry["editor"]["height"] >= 132 and geometry["results"]["height"] >= 116,
                f"query panes violate minimum heights at {width}x{height}: {geometry}")
        require(geometry["split"]["top"] <= geometry["editor"]["top"] + 1
                and geometry["editor"]["bottom"] <= geometry["divider"]["top"] + 1
                and geometry["divider"]["bottom"] <= geometry["results"]["top"] + 1
                and geometry["results"]["bottom"] <= geometry["split"]["bottom"] + 1
                and geometry["divider"]["height"] > 0 and not geometry["globalOverflow"],
                f"query splitter escapes its layout bounds at {width}x{height}: {geometry}")
        require(browser.js("""
          const split = document.querySelector('#query-split');
          const divider = document.querySelector('#query-splitter');
          const available = split.clientHeight - divider.offsetHeight;
          const ratio = parseFloat(getComputedStyle(split).getPropertyValue('--query-editor-ratio')) / 100;
          return ratio * available >= 132 - 1 && (1 - ratio) * available >= 116 - 1;
        """), f"query ratio does not honor both pane minima at {width}x{height}")

        interaction = browser.js("""
          const split = document.querySelector('#query-split');
          const divider = document.querySelector('#query-splitter');
          const rect = split.getBoundingClientRect();
          const before = parseFloat(getComputedStyle(split).getPropertyValue('--query-editor-ratio'));
          divider.setPointerCapture = () => {};
          const event = (type, y) => divider.dispatchEvent(new PointerEvent(type, {
            bubbles:true, pointerId:7, pointerType:'mouse', clientY:y, clientX:rect.left+4
          }));
          event('pointerdown', rect.top + rect.height * .62);
          event('pointermove', rect.top + rect.height * .43);
          event('pointerup', rect.top + rect.height * .43);
          const after = parseFloat(getComputedStyle(split).getPropertyValue('--query-editor-ratio'));
          return {before, after, stored: Number(localStorage.getItem('analytics.query.splitRatio')),
            aria: Number(divider.getAttribute('aria-valuenow'))};
        """)
        require(abs(interaction["after"] - interaction["before"]) >= 2
                and abs(interaction["stored"] * 100 - interaction["after"]) < 1
                and abs(interaction["aria"] - interaction["after"]) <= 1,
                f"pointer drag or persistence failed at {width}x{height}: {interaction}")
        require(browser.js("""
          const split = document.querySelector('#query-split');
          const divider = document.querySelector('#query-splitter');
          const editor = document.querySelector('#query-editor-panel').getBoundingClientRect();
          const results = document.querySelector('#query-results-panel').getBoundingClientRect();
          const storedBefore = Number(localStorage.getItem('analytics.query.splitRatio')) * 100;
          divider.focus(); divider.dispatchEvent(new KeyboardEvent('keydown', {key:'ArrowDown', bubbles:true}));
          const updated = parseFloat(getComputedStyle(split).getPropertyValue('--query-editor-ratio'));
          return document.activeElement === divider && updated > storedBefore
            && editor.height >= 132 && results.height >= 116;
        """), f"keyboard resizing failed at {width}x{height}")

        browser.load(f"{base}/dev/?scenario=query-results", width, height)
        persisted = browser.js("return Math.abs(parseFloat(getComputedStyle(document.querySelector('#query-split')).getPropertyValue('--query-editor-ratio')) / 100 - Number(localStorage.getItem('analytics.query.splitRatio'))) < .01;")
        require(persisted, f"saved splitter ratio did not survive reload at {width}x{height}")
        browser.screenshot(f"query-splitter-{width}x{height}.png", SPLITTER_OUTPUT)
        print(f"PASS query splitter drag, keyboard, persistence, bounds and pane minima {width}x{height}")


def capture_tab_indicator_review(browser: Browser, base: str) -> None:
    cases = (
        ("home-active", "healthy", None),
        ("transactions-active", "ask-anvil", None),
        ("query-1-active", "home-populated&tabs=many", "Query 1"),
        ("multiple-tabs", "home-populated&tabs=many", None),
    )
    for width, height in ((1920, 1080), (3840, 2160)):
        for name, scenario, activate in cases:
            browser.load(f"{base}/dev/?scenario={scenario}", width, height)
            if activate:
                browser.js("""
                  [...document.querySelectorAll('.workspace-tab')]
                    .find((tab) => tab.querySelector('.workspace-tab-label')?.textContent === 'Query 1')?.click();
                """)
            label = browser.js("return document.querySelector('.workspace-tab.active .workspace-tab-label')?.textContent;")
            expected = "Query 1" if activate else ("Query 9" if name == "multiple-tabs" else "Home" if name == "home-active" else "transactions")
            require(label == expected, f"{name} selected {label!r} instead of {expected!r} at {width}")
            certify_active_indicator(browser, ".workspace-tab.active", ".workspace-tab-content", "#workspace-tabs",
                                     f"{name} {width}")
            if name == "home-active":
                require(browser.js("return !document.querySelector('.workspace-tab.active').closest('.workspace-tab-wrap').querySelector('.workspace-tab-close');"),
                        "Home unexpectedly has a close button")
            else:
                require(browser.js("return Boolean(document.querySelector('.workspace-tab.active').closest('.workspace-tab-wrap').querySelector('.workspace-tab-close'));"),
                        f"{name} lost its close button")
            if name == "transactions-active":
                require(browser.js("return document.querySelector('.table-tab.active .table-tab-content')?.textContent === 'Overview' && !document.querySelector('.table-tab.active .workspace-tab-close');"),
                        "table section tab content wrapper or close-free state is missing")
                certify_active_indicator(browser, ".table-tab.active", ".table-tab-content", ".table-tabs",
                                         f"transactions table section {width}")
            if name == "multiple-tabs" and width == 1920:
                require(browser.js("return document.querySelector('#workspace-tabs').scrollWidth > document.querySelector('#workspace-tabs').clientWidth;"),
                        "multiple tabs do not exercise horizontal overflow at 1920px")
            require(browser.js("const tab=document.querySelector('.workspace-tab.active'); const content=tab.querySelector('.workspace-tab-content'); return content.querySelector('.workspace-tab-label') && content.children.length === 2;"),
                    f"{name} icon and label are not grouped together")
            browser.screenshot(f"{name}-{width}x{height}.png")


def metrics(browser: Browser) -> dict:
    return browser.js("""
      const width = (selector) => document.querySelector(selector).getBoundingClientRect().width;
      const font = (selector) => { const element = document.querySelector(selector); return element ? parseFloat(getComputedStyle(element).fontSize) : 0; };
      return { viewport: innerWidth, scroll: document.documentElement.scrollWidth,
        catalog: width('#catalog-panel'), assistant: width('#assistant-panel'), center: width('.center-column'),
        rootFont: font(':root'), catalogFont: font('.tree-group summary'), bodyFont: font('.home-intro p'),
        askFont: font('.chat-compose textarea'), statusFont: font('#health-summary-label'),
        editorFont: font('#sql-editor'), gridFont: font('td'), ratio: devicePixelRatio };
    """)


def certify_local_intelligence(browser: Browser, base: str) -> None:
    browser.load(f"{base}/dev/?scenario=ask-anvil", 1920, 1080)
    browser.js("window.sendChat('Summarize the table grain and freshness.'); return true;")
    for _ in range(40):
        if browser.js("const answer=document.querySelector('.chat-message.assistant:last-child .message-text'); return Boolean(answer && answer.textContent.includes('does not call a model.'));"):
            break
        time.sleep(.1)
    markdown = browser.js("""
      const answer = document.querySelector('.chat-message.assistant:last-child .message-text');
      const scroller = answer?.querySelector('.markdown-table-scroll');
      const unsafe = document.createElement('div');
      renderSafeMarkdown(unsafe, '<img src=x onerror=alert(1)>');
      return {table: Boolean(scroller && scroller.querySelectorAll('thead th').length === 2
          && scroller.querySelectorAll('tbody tr').length === 2),
        accessible: scroller?.getAttribute('role') === 'region' && scroller.tabIndex === 0,
        activityFinished: !document.querySelector('.assistant-activity'),
        completeResponse: answer?.textContent.includes('does not call a model.'),
        model: document.querySelector('#analytics-model-label').textContent === 'Luna 6 · GitHub Copilot'
          && document.querySelector('#analytics-model-label').title.includes('Fallback: NONE'),
        safe: !unsafe.querySelector('img') && unsafe.textContent.includes('<img')};
    """)
    require(all(markdown.values()), f"Ask Anvil Markdown, activity, completion, model policy, or HTML safety failed: {markdown}")
    browser.screenshot("ask-anvil-markdown-table-1920x1080.png")

    browser.load(f"{base}/dev/?scenario=table-local", 1920, 1080)
    browser.js("document.querySelector('.table-tab[data-section=local]').click(); return true;")
    certify_active_indicator(browser, ".table-tab.active", ".table-tab-content", ".table-tabs",
                             "local data tab 1920")
    state = browser.js("""
      const action = document.querySelector('#table-make-local');
      const originalConfirm = window.confirm;
      let removalMessage = '';
      window.confirm = (message) => { removalMessage = message; return false; };
      document.querySelector('.table-tab[data-section=local]').click();
      document.querySelector('.local-data-actions button').click();
      window.confirm = originalConfirm;
      action.click();
      const dialog = document.querySelector('#materialize-dialog');
      const allRows = document.querySelector('#materialize-all-rows');
      const filter = document.querySelector('#materialize-filter');
      document.querySelector('#materialize-all-columns').click();
      return {button: action.textContent === 'Local ✓', title: document.querySelector('#materialize-title').textContent === 'Update local copy',
        removal: removalMessage.includes('remote Databricks table will not be changed'),
        noTechnicalBounds: !document.querySelector('#materialize-rows') && !document.querySelector('#materialize-mib'),
        allRowsDefault: allRows.checked && filter.disabled,
        noRedundantConfirmation: !document.querySelector('#confirm-full-table-row'),
        noGenerationId: !document.querySelector('#table-section-content').textContent.includes('snapshot-'),
        dialog: dialog.open};
    """)
    require(all(state.values()), f"local-copy lifecycle controls are incomplete: {state}")
    browser.screenshot("local-copy-acquisition-dialog-1920x1080.png")

    payload = browser.js("""
      const client = window.anvilAnalyticsApi;
      const request = client.request.bind(client);
      client.request = (path, options = {}) => {
        if (path === '/api/materializations') {
          window.__capturedMaterialization = JSON.parse(options.body);
          return Promise.resolve({operation_id:'mock-materialize-captured', phase:'DOWNLOADING_ARROW', state:'RUNNING'});
        }
        if (path === '/api/materializations/mock-materialize-captured') {
          return Promise.resolve({operation_id:'mock-materialize-captured', phase:'WRITING_PARQUET', state:'RUNNING'});
        }
        return request(path, options);
      };
      const nativeTimeout = window.setTimeout.bind(window);
      window.setTimeout = (callback, delay) => delay === 1800 ? 0 : nativeTimeout(callback, delay);
      document.querySelector('#confirm-materialize').click();
      return window.__capturedMaterialization;
    """)
    require(payload and payload["columns"] == ["*"]
            and payload["predicate"] == "" and "max_rows" not in payload
            and "max_bytes" not in payload,
            f"all-column/all-row acquisition request contains hidden limits: {payload}")
    for _ in range(20):
        progress = browser.js("return document.querySelector('#materialize-feedback').textContent;")
        if "Writing local Parquet files" in progress:
            break
        time.sleep(.05)
    require("Writing local Parquet files" in progress,
            f"materialization phase was not shown in the dialog: {progress}")
    require(browser.js("return document.querySelector('#table-make-local').disabled && document.querySelector('#table-make-local').textContent === 'Updating…';"),
            "table action did not show the active local-copy update")

    browser.load(f"{base}/dev/?scenario=table-local", 1920, 1080)
    browser.js("document.querySelector('#table-make-local').click(); document.querySelector('#materialize-filtered-rows').click(); document.querySelector('#materialize-filter').value = \"status = 'SETTLED'\"; return true;")
    filtered = browser.js("""
      const filter = document.querySelector('#materialize-filter');
      return filter.disabled === false && document.querySelector('#materialize-filtered-rows').checked
        && !document.querySelector('#materialize-all-rows').checked;
    """)
    require(filtered, "filtered-row selection did not enable its predicate field independently")
    browser.screenshot("local-copy-filtered-rows-1920x1080.png")

    browser.load(f"{base}/dev/?scenario=query-results", 1920, 1080)
    browser.js("""
      const client = window.anvilAnalyticsApi;
      const request = client.request.bind(client);
      client.request = (path, options = {}) => path === '/api/query'
        ? new Promise((resolve) => window.setTimeout(() => request(path, options).then(resolve), 900))
        : request(path, options);
      window.runQuery();
      return true;
    """)
    for _ in range(30):
        if browser.js("return Boolean(document.querySelector('#query-results .query-progress'));"):
            break
        time.sleep(.05)
    query_progress = browser.js("""
      const progress = document.querySelector('#query-results .query-progress');
      return {visible: Boolean(progress), role: progress?.getAttribute('role'),
        message: progress?.textContent || '', hasTechnicalId: /operation[_ -]?id|snapshot[_ -]?id/i.test(progress?.textContent || '')};
    """)
    require(query_progress["visible"] and query_progress["role"] == "status"
            and "Executing query" in query_progress["message"] and not query_progress["hasTechnicalId"],
            f"query progress is not visible and user-readable in Results: {query_progress}")
    browser.screenshot("query-progress-1920x1080.png")


def certify_home_reliability(browser: Browser, base: str) -> None:
    scenarios = (
        "healthy", "home-populated", "parallel-materializations", "half-progress",
        "resumable-transfer", "local-needs-update", "legacy-migrating",
        "many-local", "many-recent", "persistent-chat", "identity-degraded",
    )
    for width, height in ((1920, 1080), (3840, 2160)):
        for scenario in scenarios:
            browser.load(f"{base}/dev/?scenario={scenario}", width, height)
            state = browser.js("""
              const operation = document.querySelector('#home-operations');
              const content = document.querySelector('#analytics-home').textContent;
              return {overflow: document.documentElement.scrollWidth > innerWidth + 1,
                operations: operation.querySelectorAll('.operation-row').length,
                progress: [...operation.querySelectorAll('[role=progressbar]')].map(item =>
                  item.getAttribute('aria-valuenow')),
                hasLegacyStatus: content.includes('NEEDS_RECONCILIATION'),
                local: document.querySelectorAll('#home-local-datasets .local-dataset-row').length,
                chat: document.querySelectorAll('#chat-thread .chat-message').length,
                header: document.querySelector('#user-name').textContent};
            """)
            require(not state["overflow"] and not state["hasLegacyStatus"],
                    f"Home overflow or internal state leaked: {scenario} {width}: {state}")
            if scenario == "parallel-materializations":
                require(state["operations"] == 3 and "50" in state["progress"] and
                        None in state["progress"], f"parallel progress absent: {state}")
            if scenario == "half-progress":
                require(state["operations"] == 1 and state["progress"] == ["50"],
                        f"halfway percentage absent: {state}")
            if scenario == "resumable-transfer":
                require(state["operations"] == 1 and "13.4" in state["progress"] and
                        browser.js("return document.querySelector('#home-operations').textContent.includes('Resume');"),
                        f"resumable failure not actionable: {state}")
            if scenario in {"legacy-migrating", "many-local"}:
                require(state["local"] >= 2, f"legacy/local data not visible: {state}")
            if scenario == "persistent-chat":
                require(state["chat"] >= 4, f"chat was not rehydrated: {state}")
            if scenario == "identity-degraded":
                require("Henrique" in state["header"], f"cached Databricks identity absent: {state}")
            browser.screenshot(f"home-{scenario}-{width}x{height}.png")
            print(f"PASS Home reliability {scenario} {width}x{height}")


def certify_chat_reload(browser: Browser, base: str) -> None:
    url = f"{base}/dev/?scenario=persistent-chat"
    browser.load(url, 1920, 1080)
    require(browser.js("return document.querySelectorAll('#chat-thread .chat-message').length === 4;"),
            "existing Ask Anvil conversation was not shown")
    browser.load(url, 1920, 1080)
    require(browser.js("return document.querySelectorAll('#chat-thread .chat-message').length === 4;"),
            "Ask Anvil conversation disappeared after page reload")
    browser.js("document.querySelector('#clear-chat').click(); document.querySelector('#confirm-clear-chat').click(); return true;")
    for _ in range(40):
        if browser.js("return document.querySelector('#chat-thread').textContent.includes('Start a new Ask Anvil conversation.');"):
            break
        time.sleep(.05)
    else:
        raise AssertionError("confirmed Clear conversation did not reset the visible thread")
    browser.load(url, 1920, 1080)
    require(browser.js("return document.querySelectorAll('#chat-thread .chat-message').length === 0;"),
            "cleared Ask Anvil conversation reappeared after reload")
    print("PASS Ask Anvil reload and confirmed clear persistence")


def certify(browser: Browser, base: str) -> None:
    for scenario, name in VIEWS.items():
        for width, height in SIZES:
            browser.load(f"{base}/dev/?scenario={scenario}", width, height)
            if scenario == "table-local":
                browser.js("document.querySelector('[data-section=local]').click(); return true;")
            m = metrics(browser)
            certify_active_indicator(browser, ".workspace-tab.active", ".workspace-tab-content", "#workspace-tabs",
                                     f"{scenario} workspace tab {width}")
            if scenario in ("table-remote", "ask-anvil"):
                certify_active_indicator(browser, ".table-tab.active", ".table-tab-content", ".table-tabs",
                                         f"{scenario} table tab {width}")
            require(m["scroll"] <= m["viewport"] + 1, f"global overflow: {scenario} {width}: {m}")
            require(m["center"] >= (600 if width >= 1366 else 0), f"workspace too narrow: {scenario} {width}")
            require(m["catalogFont"] >= 14 and m["askFont"] >= 14 and m["statusFont"] >= 12,
                    f"text too small: {scenario} {width}: {m}")
            if width == 1920:
                require(275 <= m["catalog"] <= 330 and 340 <= m["assistant"] <= 410,
                        f"Full HD panels too narrow: {m}")
            if width == 2560:
                require(300 <= m["catalog"] <= 335 and 370 <= m["assistant"] <= 420,
                        f"QHD panels too narrow: {m}")
            if width == 3840:
                require(m["rootFont"] >= 19 and 340 <= m["catalog"] <= 385 and 420 <= m["assistant"] <= 465,
                        f"4K scale too small: {m}")
            if scenario == "table-remote":
                require(browser.js("return document.querySelector('.table-summary-main')?.textContent.includes('6 columns') && document.querySelector('.table-local-state')?.textContent === 'Remote only' && !document.querySelector('.table-facts');"),
                        f"remote overview contains unavailable metrics: {width}")
            if scenario == "table-local":
                local_details = browser.js("const text=document.querySelector('#table-section-content').textContent; return {hasCoverage:text.includes('Local copy covers this table'),facts:document.querySelectorAll('.fact-card').length,hasSnapshotId:text.includes('snapshot-'),hasGenerationId:text.includes('generation')};")
                require(local_details["hasCoverage"] and local_details["facts"] == 5
                        and not local_details["hasSnapshotId"] and not local_details["hasGenerationId"],
                        f"local copy details expose internal IDs or omit coverage facts: {width}: {local_details}")
            if scenario == "query-results":
                require(m["editorFont"] >= 14 and m["gridFont"] >= 13,
                        f"SQL workspace text too small: {width}: {m}")
                require(browser.js("return document.querySelectorAll('#query-results tbody tr').length > 0;"),
                        f"query results missing: {width}")
            if scenario == "ask-anvil":
                require(browser.js("return document.querySelector('#context-card').textContent.includes('transactions') && document.querySelector('#context-card').textContent.includes('6 columns') && document.querySelector('.context-heading-label').textContent === 'Context' && !document.querySelector('#context-source') && document.querySelectorAll('.chat-message').length === 2;"),
                        f"Ask Anvil context or messages missing: {width}")
                require(browser.js("return document.querySelector('#clear-chat').title === 'Clear conversation' && document.querySelector('#clear-chat').getAttribute('aria-label') === 'Clear conversation' && document.querySelector('#clear-chat svg path')?.getAttribute('d')?.startsWith('M4 7h16');"),
                        f"clear conversation control is not semantic: {width}")
            require(browser.js("return !document.querySelector('#status-catalog-count') && document.querySelector('#catalog-count').textContent.includes('catalog');"),
                    f"persistent footer contains catalog debug metadata or catalog count disappeared: {width}")
            browser.screenshot(f"{name}-{width}x{height}.png")
            print(f"PASS {name} {width}x{height}")

    browser.load(f"{base}/dev/?scenario=healthy")
    require(browser.js("return document.querySelector('#home-pinned-section').classList.contains('hidden') && document.querySelector('#home-operations-section').classList.contains('hidden') && !document.querySelector('.health-strip');"),
            "empty Home sections are visible")
    browser.load(f"{base}/dev/?scenario=table-local&filter=local")
    require(browser.js("return document.querySelectorAll('#catalog-tree .tree-table-row').length >= 2;"),
            "Local Catalog filter returned no datasets")
    require(browser.js("document.querySelector('#catalog-tree .tree-star').click(); document.querySelector('[data-catalog-filter=favorites]').click(); return document.querySelectorAll('#catalog-tree .tree-table-row').length === 2 && [...document.querySelectorAll('#catalog-tree .tree-star')].every(star => star.getAttribute('aria-pressed') === 'true');"),
            "favorite action or filter failed")
    browser.screenshot("catalog-favorites-1920x1080.png")
    browser.load(f"{base}/dev/?scenario=table-local")
    require(browser.js("document.querySelector('[data-section=local]').click(); return document.querySelector('.coverage-card')?.textContent.includes('Local copy covers this table') && document.querySelectorAll('.fact-card').length === 5;"),
            "local data details are missing from their tab")
    browser.screenshot("table-local-data-1920x1080.png")
    browser.load(f"{base}/dev/?scenario=large-catalog&expand=first")
    require(browser.js("return [...document.querySelectorAll('#catalog-tree .tree-table-row')].length > 0 && [...document.querySelectorAll('#catalog-tree .tree-table-row')].every(row => !row.querySelector('img') && row.querySelector('.tree-icon svg') && row.querySelector('.tree-star svg') && getComputedStyle(row.querySelector('.tree-star')).backgroundColor === 'rgba(0, 0, 0, 0)');"),
            "Catalog row icon or favorite background regressed")
    browser.screenshot("catalog-large-1920x1080.png")
    browser.load(f"{base}/dev/?scenario=healthy")
    require(browser.js("document.querySelector('#health-summary').click(); return document.querySelector('#health-menu').open && document.querySelectorAll('.health-details .status-item').length === 4;"),
            "health details are inaccessible")
    browser.screenshot("health-details-1920x1080.png")
    browser.load(f"{base}/dev/?scenario=active-operation")
    require(browser.js("return !document.querySelector('#home-operations-section').classList.contains('hidden') && !document.querySelector('#operations-label').classList.contains('hidden');"),
            "active operations are hidden")
    browser.screenshot("active-operation-1920x1080.png")
    browser.load(f"{base}/dev/?scenario=degraded")
    require(browser.js("return document.querySelector('#health-summary-label').textContent === 'Systems need attention';"),
            "degraded systems are reported as healthy")
    browser.screenshot("degraded-1920x1080.png")
    browser.load(f"{base}/dev/?scenario=healthy&collapse=catalog")
    require(browser.js("return document.querySelector('#workspace-grid').classList.contains('catalog-collapsed') && document.querySelector('#collapse-catalog').getAttribute('aria-expanded') === 'false';"),
            "Catalog collapse failed")
    browser.load(f"{base}/dev/?scenario=healthy&collapse=assistant")
    require(browser.js("return document.querySelector('#workspace-grid').classList.contains('assistant-collapsed') && document.querySelector('#collapse-assistant').getAttribute('aria-expanded') === 'false';"),
            "Ask Anvil collapse failed")
    certify_clear_conversation(browser, base)
    certify_tab_close(browser, base)
    certify_query_splitter(browser, base)
    certify_local_intelligence(browser, base)
    certify_home_reliability(browser, base)
    certify_chat_reload(browser, base)
    for width, height in ((1920, 1080), (3840, 2160)):
        browser.load(f"{base}/dev/?scenario=home-populated&tabs=many", width, height)
        require(browser.js("return document.querySelector('#workspace-tabs').scrollWidth >= document.querySelector('#workspace-tabs').clientWidth && document.querySelector('.workspace-tab.active .workspace-tab-label')?.textContent === 'Query 9';"),
                f"multiple workspace tabs are missing at {width}")
        browser.screenshot(f"multiple-tabs-{width}x{height}.png")
    browser.load(f"{base}/dev/?scenario=home-populated&tabs=many", 1366, 768)
    require(browser.js("return document.querySelector('#workspace-tabs').scrollWidth > document.querySelector('#workspace-tabs').clientWidth && parseFloat(getComputedStyle(document.querySelector('.workspace-tab')).fontSize) >= 14;"),
            "workspace tabs shrink instead of scrolling")
    capture_tab_indicator_review(browser, base)
    print("PASS catalog filters, favorite interaction, icon fallback, health, operations, panels, tabs, and final polish")


def main() -> int:
    if not shutil.which("firefox") or not shutil.which("geckodriver"):
        print("Firefox and geckodriver are required for the visual check", file=sys.stderr)
        return 2
    server = make_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        browser = Browser()
        try:
            certify(browser, base)
        finally:
            browser.close()
        for scale in (1.25, 1.5):
            browser = Browser(scale=scale)
            try:
                for width, height in ((1366, 768), (1920, 1080)):
                    browser.load(f"{base}/dev/?scenario=table-remote", width, height)
                    m = metrics(browser)
                    require(m["ratio"] >= scale - .05 and m["scroll"] <= m["viewport"] + 1 and m["center"] > 0,
                            f"scale {scale} overflow or preference ignored at {width}: {m}")
                    browser.screenshot(f"table-remote-{width}x{height}-scale-{int(scale * 100)}.png")
                    print(f"PASS effective browser scale {int(scale * 100)}% at {width}x{height}")
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
    print(f"Screenshots: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
