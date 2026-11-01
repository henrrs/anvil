#!/usr/bin/env python3
"""Serve isolated static Analytics UI assets for local visual development."""

from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

WEB_ROOT = Path(__file__).resolve().parents[1] / "web" / "analytics"
SCENARIOS = ("healthy", "home-populated", "table-remote", "table-local", "query-results",
             "ask-anvil", "active-operation", "offline", "degraded", "materializing",
             "large-catalog", "single-warehouse", "no-warehouses", "warehouse-disappeared")


class MockStaticHandler(SimpleHTTPRequestHandler):
    server_version = "AnvilAnalyticsMock/1"

    def __init__(self, *args, directory: str | None = None, **kwargs):
        super().__init__(*args, directory=directory or str(WEB_ROOT), **kwargs)

    def do_GET(self) -> None:
        if self.path == "/":
            self.send_response(302)
            self.send_header("Location", self.server.dev_url)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        if self.path.split("?", 1)[0].startswith("/api/"):
            self.send_error(404, "The static mock does not expose a production API")
            return
        super().do_GET()

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
                         "base-uri 'none'; frame-ancestors 'none'")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:
        # The mock loads many static files during visual checks; report only unexpected routes.
        if self.path.startswith("/api/"):
            super().log_message(format, *args)


def make_server(*, host: str = "127.0.0.1", port: int = 8766,
                scenario: str = "healthy") -> ThreadingHTTPServer:
    if host != "127.0.0.1":
        raise ValueError("Analytics UI mock must bind to 127.0.0.1")
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario: {scenario}")
    server = ThreadingHTTPServer((host, port), MockStaticHandler)
    server.daemon_threads = True
    server.dev_url = f"/dev/?scenario={quote(scenario)}"
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--scenario", choices=SCENARIOS, default="healthy")
    args = parser.parse_args(argv)
    try:
        server = make_server(host=args.host, port=args.port, scenario=args.scenario)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    url = f"http://127.0.0.1:{server.server_port}/dev/?scenario={quote(args.scenario)}"
    print(f"Anvil Analytics development mock ({args.scenario})")
    print(f"Open {url}")
    print("Static UI only · no OpenCode, Anvil service, Databricks, or credentials are used.")
    print("Press Ctrl-C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
