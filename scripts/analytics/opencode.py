"""Version-specific OpenCode HTTP adapters behind one local-only port."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Protocol

from .errors import ProviderError, UnavailableError, ValidationError


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_LOCAL_OPENER = urllib.request.build_opener(_NoRedirect)


class OpenCodeRuntimePort(Protocol):
    """The narrow runtime surface used by Analytics session management."""

    generation: int
    workspace: Path

    def health(self) -> bool: ...
    def list_sessions(self) -> list[dict[str, Any]]: ...
    def get_session(self, session_id: str) -> dict[str, Any] | None: ...
    def create_session(self, title: str, parent_id: str | None = None) -> dict[str, Any]: ...
    def add_context(self, session_id: str, text: str) -> None: ...
    def prompt(self, session_id: str, text: str, *, model: dict[str, str] | None = None) -> dict[str, Any]: ...
    def wait_for_response(self, session_id: str, *, timeout: float = 300.0) -> dict[str, Any]: ...
    def providers(self) -> Any: ...


class _HttpAdapter:
    generation = 0
    api_prefix = ""

    def __init__(self, base_url: str, workspace: Path | str,
                 *, timeout: float = 30.0) -> None:
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}:
            raise ValidationError("OpenCode must be reached through its local HTTP listener")
        if parsed.path not in {"", "/"} or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValidationError("OpenCode URL must not contain credentials or query data")
        self.base_url = base_url.rstrip("/")
        self.workspace = Path(workspace).expanduser().absolute()
        self.timeout = timeout

    def _request(self, method: str, path: str,
                 body: dict[str, Any] | None = None, *, timeout: float | None = None,
                 max_bytes: int = 2 * 1024 * 1024) -> Any:
        payload = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        prefix = "" if path.startswith("/global/") else self.api_prefix
        request = urllib.request.Request(
            self.base_url + prefix + path,
            data=payload,
            headers={"Accept": "application/json", **({"Content-Type": "application/json"} if payload else {})},
            method=method,
        )
        try:
            with _LOCAL_OPENER.open(request, timeout=timeout or self.timeout) as response:
                raw = response.read(max_bytes + 1)
                if len(raw) > max_bytes:
                    raise ProviderError("OpenCode response exceeded the configured limit")
                if not raw:
                    return None
                try:
                    return json.loads(raw.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise ProviderError("OpenCode returned an invalid response") from exc
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code == 404:
                return None
            raise ProviderError(f"OpenCode request failed with HTTP {exc.code}",
                                code="OPENCODE_HTTP_ERROR", retryable=exc.code >= 500) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise UnavailableError("The local OpenCode runtime is not responding") from exc

    def providers(self) -> Any:
        """Return the bounded runtime catalog used to validate explicit model policy."""
        return self._request("GET", "/provider", max_bytes=16 * 1024 * 1024)

    @staticmethod
    def _object(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            nested = value.get("data")
            return nested if isinstance(nested, dict) else value
        return {}

    def health(self) -> bool:
        try:
            # OpenCode can accept TCP before its HTTP handlers are ready. Keep
            # any one probe short so retries stay inside the manager deadline.
            result = self._request("GET", self._health_path(), timeout=min(0.5, self.timeout))
            return isinstance(result, dict) and result.get("healthy", True) is True
        except (ProviderError, UnavailableError):
            return False

    def list_sessions(self) -> list[dict[str, Any]]:
        result = self._request("GET", self._session_list_path())
        if isinstance(result, list):
            return [row for row in result if isinstance(row, dict)]
        candidate = result
        for _depth in range(3):
            if isinstance(candidate, list):
                return [row for row in candidate if isinstance(row, dict)]
            if not isinstance(candidate, dict):
                break
            candidate = next((candidate[key] for key in ("items", "sessions", "data")
                              if key in candidate), None)
        return []

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        result = self._request("GET", self._session_item_path(session_id))
        value = self._object(result)
        return value or None

    def create_session(self, title: str, parent_id: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"title": title}
        if parent_id:
            body["parentID"] = parent_id
        result = self._request("POST", self._session_create_path(), body)
        value = self._object(result)
        if not value.get("id"):
            raise ProviderError("OpenCode did not return a session identifier")
        return value

    def add_context(self, session_id: str, text: str) -> None:
        self._add_context(session_id, text)

    def prompt(self, session_id: str, text: str, *, model: dict[str, str] | None = None) -> dict[str, Any]:
        if model is not None and (set(model) != {"providerID", "modelID"} or
                                  any(not isinstance(value, str) or not value for value in model.values())):
            raise ValidationError("OpenCode model selection is invalid")
        result = self._prompt(session_id, text, model=model)
        return self._object(result)

    def _session_list_path(self) -> str:
        raise NotImplementedError

    def _health_path(self) -> str:
        return "/global/health"

    def _session_create_path(self) -> str:
        raise NotImplementedError

    def _session_item_path(self, session_id: str) -> str:
        raise NotImplementedError

    def _add_context(self, session_id: str, text: str) -> None:
        raise NotImplementedError

    def _prompt(self, session_id: str, text: str, *, model: dict[str, str] | None = None) -> Any:
        raise NotImplementedError


class OpenCode1xRuntimeAdapter(_HttpAdapter):
    generation = 1

    def _session_list_path(self) -> str:
        return "/session"

    def _session_create_path(self) -> str:
        return "/session"

    def _session_item_path(self, session_id: str) -> str:
        return "/session/" + urllib.parse.quote(session_id, safe="")

    def _add_context(self, session_id: str, text: str) -> None:
        self._request("POST", self._session_item_path(session_id) + "/message",
                      {"noReply": True, "parts": [{"type": "text", "text": text}]})

    def _prompt(self, session_id: str, text: str, *, model: dict[str, str] | None = None) -> Any:
        body: dict[str, Any] = {"parts": [{"type": "text", "text": text}]}
        if model:
            body["model"] = model
        return self._request("POST", self._session_item_path(session_id) + "/message",
                             body, timeout=300.0)

    def wait_for_response(self, session_id: str, *, timeout: float = 300.0) -> dict[str, Any]:
        del session_id, timeout
        return {}


class OpenCode2xRuntimeAdapter(_HttpAdapter):
    generation = 2
    api_prefix = "/api"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._prompt_baselines: dict[str, str] = {}

    def _session_list_path(self) -> str:
        query = urllib.parse.urlencode({"directory": str(self.workspace), "limit": "200", "order": "desc"})
        return "/session?" + query

    def _session_create_path(self) -> str:
        return "/session"

    def _session_item_path(self, session_id: str) -> str:
        return "/session/" + urllib.parse.quote(session_id, safe="")

    def _add_context(self, session_id: str, text: str) -> None:
        self._request("POST", self._session_item_path(session_id) + "/synthetic",
                      {"text": text, "description": "Rehydrate persistent Analytics context", "resume": False})

    def _prompt(self, session_id: str, text: str, *, model: dict[str, str] | None = None) -> Any:
        previous = self.list_messages(session_id, limit=1)
        previous_info = (previous[0].get("info") if previous and isinstance(previous[0].get("info"), dict)
                         else previous[0] if previous else {})
        previous_id = str(previous_info.get("id") or "")
        body: dict[str, Any] = {"text": text, "resume": True}
        if model:
            body["model"] = model
        result = self._request("POST", self._session_item_path(session_id) + "/prompt", body)
        self._prompt_baselines[session_id] = previous_id
        return self._object(result)

    def list_messages(self, session_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 100))
        query = urllib.parse.urlencode({"limit": str(bounded), "order": "desc"})
        result = self._request("GET", self._session_item_path(session_id) + "/message?" + query)
        if isinstance(result, list):
            return [item for item in result if isinstance(item, dict)]
        if isinstance(result, dict):
            data = result.get("data")
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
        return []

    def wait_for_response(self, session_id: str, *, timeout: float = 300.0) -> dict[str, Any]:
        if timeout < 1 or timeout > 1800:
            raise ValidationError("OpenCode response wait must be between 1 second and 30 minutes")
        self._request("POST", self._session_item_path(session_id) + "/wait", timeout=timeout)
        baseline = self._prompt_baselines.pop(session_id, "")
        for message in self.list_messages(session_id, limit=100):
            info = message.get("info") if isinstance(message.get("info"), dict) else message
            message_id = str(info.get("id") or "")
            if message_id == baseline:
                break
            if str(info.get("role") or "").casefold() == "assistant":
                return message
        raise ProviderError("OpenCode completed without returning an assistant response",
                            code="OPENCODE_RESPONSE_MISSING", retryable=True)


def create_adapter(generation: int, base_url: str, workspace: Path | str,
                   *, timeout: float = 30.0) -> OpenCodeRuntimePort:
    adapters = {1: OpenCode1xRuntimeAdapter, 2: OpenCode2xRuntimeAdapter}
    adapter = adapters.get(generation)
    if adapter is None:
        raise ValidationError(f"OpenCode major {generation} is not supported by Analytics")
    return adapter(base_url, workspace, timeout=timeout)
