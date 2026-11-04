#!/usr/bin/env python3
"""Dependency-free Firefox smoke pass for the local Dexter frontend."""
from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = Path(tempfile.gettempdir()) / "dexter-smoke"
ELEMENT_KEY = "element-6066-11e4-a52e-4f735466cecf"


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class WebDriver:
    def __init__(self, base: str, session_id: str):
        self.base = base
        self.session_id = session_id

    def request(self, method: str, path: str, payload=None):
        body = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            self.base + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                result = json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            message = error.read().decode(errors="replace")
            raise RuntimeError(f"WebDriver {method} {path}: HTTP {error.code}: {message}") from error
        value=result.get("value")
        if isinstance(value,dict) and value.get("error"):
            raise RuntimeError(f"WebDriver {method} {path}: {value}")
        return value

    def command(self, method: str, path: str, payload=None):
        return self.request(method, f"/session/{self.session_id}{path}", payload)

    def script(self, source: str, args=None):
        return self.command("POST", "/execute/sync", {"script": source, "args": args or []})

    def click(self, selector: str, index: int = 0):
        result = self.script(
            "const els=[...document.querySelectorAll(arguments[0])].filter(e=>!e.disabled);"
            "if(!els[arguments[1]])return false;els[arguments[1]].click();return true;",
            [selector, index],
        )
        if result is not True:
            raise AssertionError(f"No enabled element matched: {selector} [{index}]")

    def wait_for(self, expression: str, timeout: float = 12):
        end = time.time() + timeout
        last = None
        while time.time() < end:
            last = self.script(f"return Boolean({expression});")
            if last:
                return
            time.sleep(0.15)
        raise AssertionError(f"Timed out waiting for browser condition: {expression}")

    def navigate(self, screen: str):
        self.script("location.hash=arguments[0];", [f"screen={screen}"])
        self.wait_for("document.querySelector('#view-root h1')")
        self.wait_for(
            "document.querySelector('#view-root').innerText.length > 0"
        )

    def text(self, selector: str) -> str:
        return self.script(
            "return document.querySelector(arguments[0])?.innerText || '';", [selector]
        )

    def type_value(self, selector: str, value: str):
        result = self.script(
            "const e=document.querySelector(arguments[0]);if(!e)return false;"
            "e.focus();e.value=arguments[1];e.dispatchEvent(new Event('input',{bubbles:true}));"
            "e.dispatchEvent(new Event('change',{bubbles:true}));return true;",
            [selector, value],
        )
        if result is not True:
            raise AssertionError(f"No input matched: {selector}")

    def screenshot(self, name: str):
        encoded = self.command("GET", "/screenshot")
        (ARTIFACTS / name).write_bytes(base64.b64decode(encoded))


def main():
    firefox = shutil.which("firefox")
    if not firefox:
        raise SystemExit("Firefox is required for this optional browser smoke test.")
    driver_url=os.environ.get("DEXTER_WEBDRIVER_URL","http://127.0.0.1:4444").rstrip("/")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    server_port = free_port()
    server = subprocess.Popen(
        ["python3", "-m", "http.server", str(server_port), "--bind", "127.0.0.1"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    client = None
    try:
        server_url=f"http://127.0.0.1:{server_port}/"
        for _ in range(100):
            try:
                urllib.request.urlopen(server_url, timeout=1).close()
                break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError(f"Local HTTP server did not start: {server_url}")
        try:
            urllib.request.urlopen(driver_url+"/status", timeout=2).close()
        except Exception as error:
            raise RuntimeError(f"Start geckodriver in another terminal before running this test: {error}") from error

        new_session = urllib.request.Request(
            driver_url+"/session",
            data=json.dumps({
                "capabilities": {
                    "alwaysMatch": {
                        "browserName": "firefox",
                        "moz:firefoxOptions": {
                            "args": ["-headless"],
                            "prefs": {"browser.shell.checkDefaultBrowser": False},
                        },
                    }
                }
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(new_session, timeout=45) as response:
            session = json.loads(response.read())["value"]
        client = WebDriver(driver_url, session["sessionId"])
        client.command("POST", "/window/rect", {"x": 0, "y": 0, "width": 1920, "height": 1080})
        client.command("POST", "/url", {"url": f"http://127.0.0.1:{server_port}/"})
        client.wait_for("document.querySelector('#view-root h1') && document.querySelector('#view-root h1').innerText.includes('Good morning')")
        client.wait_for("JSON.parse(localStorage.getItem('dexter.platform.demo.v1')).operations.every(op=>['Completed','Failed','Cancelled'].includes(op.state))", timeout=10)
        client.screenshot("home-1920x1080.png")

        # Journey A: a template Lab receives its service schema and lifecycle transition.
        client.click('[data-screen="lab-gallery"]')
        client.wait_for("document.querySelector('#view-root h1')?.innerText.includes('Development Labs')")
        client.click('[data-action="use-lab-template"][data-id="sqlserver"]')
        client.wait_for("document.querySelector('#view-root h1')?.innerText.includes('Lab Composer')")
        client.click('[data-screen="schema-designer"]')
        client.wait_for("document.querySelector('#view-root h1')?.innerText.includes('Schema & Contract Designer')")
        client.click('[data-action="import-schema"]')
        assert client.script("return [...document.querySelectorAll('[data-schema-field]')].some(input=>input.value==='customer_tier');"), "SQL Server demo schema should import"
        client.navigate("lab-composer")
        client.click('[data-action="save-lab"]')
        client.wait_for("document.querySelector('#view-root').innerText.includes('Service topology')")
        client.click('[data-action="lab-start"]')
        client.wait_for("document.querySelector('#view-root').innerText.includes('Running')", timeout=10)

        # Journey B: create a cross-technology Lab, connect services, configure Kafka and save.
        client.navigate("lab-gallery")
        client.click('[data-action="create-custom-lab"]')
        for service in ("Oracle", "Kafka", "REST API", "Filesystem", "PySpark"):
            client.click(f'[data-action="add-component"][data-name="{service}"]')
        client.click('[data-action="select-component"][data-index="0"]')
        client.click('[data-action="select-component"][data-index="1"]')
        client.click('[data-action="connect-components"]')
        assert "Oracle → Kafka" in client.text("#view-root"), "Lab service connection should be visible"
        client.click('[data-action="select-component"][data-index="1"]')
        client.click('[data-action="navigate-schema"]')
        client.click('[data-action="import-schema"]')
        assert "account_events" in client.text("#view-root"), "Kafka should import its event schema"
        client.navigate("mock-behavior")
        client.script("const e=document.querySelector('[data-model=mock-service]');e.value='Kafka';e.dispatchEvent(new Event('change',{bubbles:true}));")
        client.click('[data-action="preview-mock"]')
        client.click('[data-action="save-mock"]')
        client.navigate("lab-composer")
        client.click('[data-action="validate-lab"]')
        client.click('[data-action="save-lab"]')
        client.wait_for("document.querySelector('#view-root').innerText.includes('Oracle')")
        client.click('[data-action="lab-start"]')
        client.wait_for("document.querySelector('#view-root').innerText.includes('Running')", timeout=10)

        # Journey C: materialize an allowed PROD asset, then reuse its LOCAL copy in DuckDB.
        client.navigate("movement-wizard")
        for _ in range(6):
            client.click('[data-action="movement-next"]')
        client.click('[data-action="run-materialization"]')
        client.wait_for("JSON.parse(localStorage.getItem('dexter.platform.demo.v1')||'{}').operations?.[0]?.type==='Materialization' && JSON.parse(localStorage.getItem('dexter.platform.demo.v1')||'{}').operations[0].state==='Completed'", timeout=15)
        client.navigate("local-data")
        assert "local.sales.transactions" in client.text("#view-root"), "Materialization should register a LOCAL dataset"
        client.click('[data-action="open-sql"][data-id="local-transactions"]')
        client.click('[data-action="run-sql"]')
        client.wait_for("document.querySelector('#sql-result-body tbody tr')")
        assert "DuckDB Local" in client.text("#sql-result-body"), "LOCAL data should route to DuckDB Local"

        # Journey F: notebook cells read the same selected LOCAL asset and produce mock outputs.
        client.navigate("notebook-studio")
        client.script("const e=document.querySelector('[data-model=notebook-runtime]');e.value='PySpark Local';e.dispatchEvent(new Event('change',{bubbles:true}));")
        client.click('[data-action="insert-asset-notebook"]')
        client.click('[data-action="run-notebook"]')
        assert "local.sales.transactions" in client.text("#view-root"), "Notebook should retain the selected LOCAL data context"
        assert "No real kernel was started" in client.text("#view-root"), "Notebook execution should clearly identify its mock runtime"

        # Journey D: create, connect, validate and execute a visual pipeline.
        client.navigate("home")
        client.click('[data-action="create-quick"][data-kind="pipeline"]')
        client.wait_for("document.querySelector('#view-root h1')?.innerText.includes('untitled_pipeline')")
        for node_type in ("Source", "Transform", "Data Quality", "Destination"):
            client.click(f'[data-action="add-pipeline-node"][data-type="{node_type}"]')
        node_ids = client.script("return [...document.querySelectorAll('.pipeline-node')].map(node=>node.dataset.id);")
        for node_id in reversed(node_ids[1:]):
            client.click(f'.pipeline-node[data-id="{node_id}"]')
            client.click('[data-action="connect-pipeline-node"]')
        client.click('[data-action="validate-pipeline"]')
        client.click('[data-action="run-pipeline"]')
        client.wait_for("document.querySelector('#view-root').innerText.includes('Completed')", timeout=12)
        client.screenshot("pipeline-1920x1080.png")

        # Journey E: model dependencies and verify an adapter-specific artifact preview.
        client.navigate("orchestration")
        task_ids = client.script("return [...document.querySelectorAll('[data-action=select-task]')].map(task=>task.dataset.id);")
        client.click(f'[data-action="select-task"][data-id="{task_ids[0]}"]')
        client.click(f'[data-action="select-task"][data-id="{task_ids[2]}"]')
        client.click('[data-action="add-task-dependency"]')
        assert "Extract customers → Publish profile" in client.text("#view-root"), "Task dependency should be visible"
        client.navigate("artifact-preview")
        client.click('[data-action="set-adapter"][data-value="Azure Data Factory"]')
        assert '"activities"' in client.text("#view-root"), "ADF adapter should emit its own preview shape"

        # Journey G: compose and persist a Data Product from shared catalog objects.
        client.navigate("product-catalog")
        client.click('[data-action="create-product"]')
        client.type_value('[name="name"]', "Browser Smoke Product")
        client.type_value('[name="purpose"]', "Shared asset product smoke workflow")
        client.script("const f=document.querySelector('[data-form=new-product]');f.requestSubmit();")
        client.wait_for("document.querySelector('#view-root h1')?.innerText.includes('Browser Smoke Product')")
        client.click('[data-product-asset="transactions"]')
        client.click('[data-product-pipeline="customer-pipeline"]')
        client.click('[data-action="save-product"]')
        client.navigate("lineage")
        client.script("const e=document.querySelector('[data-model=lineage-asset]');e.value='transactions';e.dispatchEvent(new Event('change',{bubbles:true}));")
        assert "Browser Smoke Product" in client.text("#view-root"), "Product links should be visible in shared lineage"

        # Journey H: run certification and create a simulated PR record.
        client.navigate("test-center")
        client.click('[data-action="run-tests"]')
        assert "Ready" in client.text("#view-root"), "Passing certification should update review readiness"
        client.navigate("pr-wizard")
        for _ in range(7):
            client.click('[data-action="pr-next"]')
        client.wait_for("document.querySelector('#view-root h1')?.innerText.includes('Delivery Status')")
        assert "#285" in client.text("#view-root"), "Delivery Status should include the newly created simulated Pull Request"

        # Journey I: Ask Dexter retains a contextual exchange across module navigation.
        client.navigate("artifact-preview")
        client.click('[data-action="context-tab"][data-value="assistant"]')
        client.type_value('[name="prompt"]', "Explain this SQL query")
        client.script("document.querySelector('[data-form=chat]').requestSubmit();")
        client.wait_for("document.querySelector('#context-panel').innerText.includes('bounded local query')")
        client.navigate("home")
        client.navigate("artifact-preview")
        assert "Explain this SQL query" in client.text("#context-panel"), "Ask Dexter conversation should persist across navigation"

        # Return to a clean seeded session so captures are not covered by journey toasts.
        client.navigate("settings")
        client.click('[data-action="confirm-reset"]')
        client.click('[data-action="reset-demo"]')
        client.wait_for("document.querySelector('#view-root h1')?.innerText.includes('Good morning')")
        client.wait_for("JSON.parse(localStorage.getItem('dexter.platform.demo.v1')).operations.every(op=>['Completed','Failed','Cancelled'].includes(op.state))", timeout=10)
        client.script("document.querySelector('#toast-region')?.replaceChildren();")

        # Usable FHD/4K shells and screenshots for visual comparison.
        for width, height in ((1920, 1080), (3840, 2160)):
            client.command("POST", "/window/rect", {"x": 0, "y": 0, "width": width, "height": height})
            client.navigate("home")
            metrics = client.script("return {inner:innerWidth,outer:outerWidth,scroll:document.documentElement.scrollWidth,body:document.body.scrollWidth};")
            assert metrics["inner"] >= width - 40, f"Browser did not reach requested viewport {width}px: {metrics}"
            assert metrics["scroll"] <= metrics["inner"] + 2, f"Horizontal overflow at {width}px: {metrics}"
            client.screenshot(f"home-{width}x{height}.png")
            client.navigate("pipeline-studio")
            metrics = client.script("return {inner:innerWidth,scroll:document.documentElement.scrollWidth};")
            assert metrics["scroll"] <= metrics["inner"] + 2, f"Pipeline screen overflow at {width}px: {metrics}"
            geometry = client.script("const svg=document.querySelector('.pipeline-edges'),paths=[...svg.querySelectorAll('.pipeline-edge')].map(path=>{const b=path.getBBox();return {x:b.x,width:b.width};});return {coordinateWidth:Number(svg.getAttribute('width')),renderedWidth:svg.getBoundingClientRect().width,paths};")
            assert abs(geometry["coordinateWidth"] - geometry["renderedWidth"]) <= 1, f"Pipeline edge coordinate scale changed at {width}px: {geometry}"
            assert all(path["x"] >= 0 and path["x"] + path["width"] <= geometry["coordinateWidth"] + 1 for path in geometry["paths"]), f"Pipeline edge escapes its SVG coordinate bounds at {width}px: {geometry}"
            client.screenshot(f"pipeline-{width}x{height}.png")

        print(f"PASS Firefox browser journeys at 1920×1080 and 3840×2160; screenshots: {ARTIFACTS}")
    finally:
        if client:
            try:
                client.command("DELETE", "")
            except Exception:
                pass
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


if __name__ == "__main__":
    main()
