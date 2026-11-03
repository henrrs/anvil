"""Loopback-only HTTP server for the same-origin Analytics BFF and static UI."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .api import AnalyticsAPI
from .errors import AnalyticsError, ConflictError, NotFoundError, UnavailableError, ValidationError
from .paths import AnalyticsPaths
from .service import AnalyticsService, DEFAULT_HOST, DEFAULT_PORT

MAX_BODY_BYTES = 1_048_576
ALLOWED_ASSETS = {"index.html", "api.js", "app.js", "styles.css"}


class AnalyticsHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], service: AnalyticsService) -> None:
        self.analytics_service = service
        self.analytics_api = AnalyticsAPI(service)
        super().__init__(address, AnalyticsRequestHandler)


class AnalyticsRequestHandler(BaseHTTPRequestHandler):
    server: AnalyticsHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: Any) -> None:
        # Request URLs and chat SQL can contain user data; do not emit them to stdout.
        return

    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def do_HEAD(self) -> None:
        self._handle(head_only=True)

    def do_PUT(self) -> None:
        self._handle()

    def do_DELETE(self) -> None:
        self._handle()

    def do_PATCH(self) -> None:
        self._handle()

    def do_OPTIONS(self) -> None:
        self._handle()

    def _handle(self, *, head_only: bool = False) -> None:
        try:
            if len(self.path) > 8192:
                raise ValidationError("Request URL exceeds the supported size")
            self._validate_origin()
            parsed = urlsplit(self.path)
            if self.command not in {"GET", "POST", "HEAD", "DELETE"} or (self.command == "HEAD" and parsed.path.startswith("/api/")):
                self.send_response(405)
                self._security_headers()
                self.send_header("Allow", "GET, HEAD, POST, DELETE")
                payload = json.dumps({"error": {"code": "METHOD_NOT_ALLOWED",
                                                  "message": "This Analytics route does not accept that method."}},
                                     separators=(",", ":")).encode("utf-8")
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if not head_only:
                    self.wfile.write(payload)
                return
            if parsed.path == "/" or parsed.path == "/index.html":
                self._static("index.html", head_only=head_only)
                return
            if parsed.path in {"/api.js", "/app.js", "/styles.css"}:
                self._static(parsed.path.lstrip("/"), head_only=head_only)
                return
            if parsed.path == "/api/anvil/chat" and self.command == "POST":
                self._chat_stream()
                return
            if parsed.path.startswith("/api/"):
                allow_empty = self.command == "POST" and parsed.path.endswith(("/cancel", "/retry", "/refresh"))
                body = self._json_body(allow_empty=allow_empty) if self.command == "POST" else None
                status, value = self.server.analytics_api.handle(
                    self.command, parsed.path, parse_qs(parsed.query, keep_blank_values=True,
                                                        max_num_fields=100), body)
                self._json(status, value, head_only=head_only)
                return
            raise ValidationError("Analytics route was not found")
        except AnalyticsError as exc:
            self._error(self._status_for(exc), exc.code, str(exc), head_only=head_only)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            self._error(500, "INTERNAL_ERROR", "Analytics could not complete this request.", head_only=head_only)

    def _validate_origin(self) -> None:
        host = self.headers.get("Host", "")
        allowed = {"anvil.localhost", "localhost", "127.0.0.1"}
        try:
            parsed_host = urlsplit("//" + host)
            host_name = (parsed_host.hostname or "").casefold()
            host_port = parsed_host.port
        except ValueError as exc:
            raise ValidationError("Request host is invalid") from exc
        if parsed_host.username or parsed_host.password or host_name not in allowed:
            raise ValidationError("Analytics accepts requests for its local host only")
        if host_port not in {None, self.server.server_port}:
            raise ValidationError("Request host port does not match the Analytics service")
        if self.headers.get("Sec-Fetch-Site", "").casefold() in {"cross-site", "same-site"}:
            raise ValidationError("Cross-site requests are not allowed")
        origin = self.headers.get("Origin")
        if origin:
            self._validate_browser_origin(origin)
        referer = self.headers.get("Referer")
        if referer:
            self._validate_browser_origin(referer)

    def _validate_browser_origin(self, value: str) -> None:
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError as exc:
            raise ValidationError("Browser origin is invalid") from exc
        if (parsed.scheme != "http" or parsed.hostname not in {"anvil.localhost", "localhost", "127.0.0.1"}
                or port not in {None, self.server.server_port} or parsed.username or parsed.password):
            raise ValidationError("Analytics rejects cross-origin browser requests")

    def _json_body(self, *, allow_empty: bool = False) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            if allow_empty:
                return {}
            raise ValidationError("Request body size is required")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValidationError("Request body size is invalid") from exc
        if length < 0 or length > MAX_BODY_BYTES:
            raise ValidationError("Request body exceeds Analytics' 1 MiB limit")
        if length == 0 and allow_empty:
            return {}
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().casefold() != "application/json":
            raise ValidationError("Analytics API requests must use application/json")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValidationError("Request body must contain valid JSON") from exc
        if not isinstance(value, dict):
            raise ValidationError("Request body must be a JSON object")
        return value

    def _chat_stream(self) -> None:
        body = self._json_body()
        prompt = body.get("prompt")
        if not isinstance(prompt, str):
            raise ValidationError("Ask Anvil requires a text prompt")
        context = body.get("context")
        if context is not None and not isinstance(context, dict):
            raise ValidationError("Ask Anvil context must be a JSON object")
        deep = body.get("deep_investigation", False)
        if not isinstance(deep, bool):
            raise ValidationError("deep_investigation must be a boolean")
        raw_timeout = body.get("timeout", 300)
        if isinstance(raw_timeout, bool) or not isinstance(raw_timeout, int) or not 5 <= raw_timeout <= 900:
            raise ValidationError("Ask Anvil timeout must be between 5 and 900 seconds")
        self.send_response(200)
        self._security_headers()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def emit(name: str, data: dict[str, Any]) -> None:
            frame = f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'), default=str)}\n\n"
            self.wfile.write(frame.encode("utf-8"))
            self.wfile.flush()

        try:
            self.server.analytics_service.ask_anvil(
                prompt, context=context, deep_investigation=deep,
                timeout=raw_timeout, event=emit)
        except AnalyticsError as exc:
            emit("error", {"code": exc.code, "message": str(exc), "retryable": exc.retryable})
            emit("done", {"state": "failed"})
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            emit("error", {"code": "ASK_ANVIL_FAILED",
                           "message": "Anvil could not complete the Analytics chat request.",
                           "retryable": True})
            emit("done", {"state": "failed"})

    def _static(self, name: str, *, head_only: bool = False) -> None:
        if name not in ALLOWED_ASSETS:
            raise ValidationError("Requested Analytics asset was not found")
        root = self.server.analytics_service.web_root
        path = root / name
        if root.is_symlink() or path.is_symlink() or not path.is_file():
            raise UnavailableError("Analytics frontend assets are unavailable",
                                   code="FRONTEND_MISSING", retryable=False)
        payload = path.read_bytes()
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        self.send_response(200)
        self._security_headers()
        self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type.startswith("text/") or "javascript" in content_type else ""))
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if not head_only:
            self.wfile.write(payload)

    def _json(self, status: int, value: Any, *, head_only: bool = False) -> None:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head_only:
            self.wfile.write(payload)

    def _error(self, status: int, code: str, message: str, *, head_only: bool = False) -> None:
        self._json(status, {"error": {"code": code, "message": message[:1000]}}, head_only=head_only)

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
                         "base-uri 'none'; frame-ancestors 'none'")

    @staticmethod
    def _status_for(error: AnalyticsError) -> int:
        if isinstance(error, NotFoundError):
            return 404
        if isinstance(error, ValidationError):
            return 400
        if isinstance(error, ConflictError):
            return 409
        if isinstance(error, UnavailableError):
            return 503
        return 500


def make_server(service: AnalyticsService, *, host: str = DEFAULT_HOST,
                port: int = DEFAULT_PORT) -> AnalyticsHTTPServer:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValidationError("Analytics BFF must bind to loopback only")
    if not 0 <= port <= 65535:
        raise ValidationError("Analytics port must be between 0 and 65535")
    return AnalyticsHTTPServer(("127.0.0.1", port), service)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local Anvil Analytics Workspace")
    parser.add_argument("--host", default=os.environ.get("ANVIL_ANALYTICS_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.environ.get("ANVIL_ANALYTICS_PORT", DEFAULT_PORT)))
    parser.add_argument("--anvil-home", type=Path, default=None)
    parser.add_argument("--web-root", type=Path, default=None)
    args = parser.parse_args(argv)
    paths = AnalyticsPaths.from_root(args.anvil_home, create=True) if args.anvil_home else AnalyticsPaths.discover(create=True)
    service = AnalyticsService(paths=paths, host=args.host, port=args.port, web_root=args.web_root)
    server = make_server(service, host=args.host, port=args.port)
    service.port = server.server_port
    print(f"Anvil Analytics: {service.url}", flush=True)

    def initialize_services() -> None:
        service.initialize_runtime()
        # Warm the shared Databricks warehouse cache outside the browser request path.
        # Provider/auth failures are represented as DEGRADED and do not stop the UI.
        service.warehouses(refresh=True)
        service.hydrate_catalog_tree()

    if os.environ.get("ANVIL_ANALYTICS_NO_BOOTSTRAP") != "1":
        threading.Thread(target=initialize_services, name="anvil-analytics-runtime",
                         daemon=True).start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
