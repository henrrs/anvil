"""Block and record non-loopback network attempts in offline lifecycle tests."""

from __future__ import annotations

import ipaddress
import os
import socket


LOG = os.environ.get("ANVIL_NETWORK_GUARD_LOG")
HTTP_403 = os.environ.get("ANVIL_NETWORK_GUARD_HTTP_403") == "1"


def _local(host: object) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", errors="ignore")
    if not isinstance(host, str):
        return True
    if host.casefold() in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _deny(host: object) -> None:
    if _local(host):
        return
    if LOG:
        with open(LOG, "a", encoding="utf-8") as stream:
            stream.write(f"{host}\n")
    raise OSError(f"external network disabled by Anvil offline test fixture: {host}")


_getaddrinfo = socket.getaddrinfo


def _guarded_getaddrinfo(host: object, *args: object, **kwargs: object):
    _deny(host)
    return _getaddrinfo(host, *args, **kwargs)


socket.getaddrinfo = _guarded_getaddrinfo

_connect = socket.socket.connect


def _guarded_connect(self: socket.socket, address: object):
    if isinstance(address, tuple) and address:
        _deny(address[0])
    return _connect(self, address)


socket.socket.connect = _guarded_connect

_connect_ex = socket.socket.connect_ex


def _guarded_connect_ex(self: socket.socket, address: object):
    if isinstance(address, tuple) and address:
        _deny(address[0])
    return _connect_ex(self, address)


socket.socket.connect_ex = _guarded_connect_ex


if HTTP_403:
    import urllib.error
    import urllib.request

    def _github_403(url: object, *args: object, **kwargs: object):
        target = getattr(url, "full_url", str(url))
        if LOG:
            with open(LOG, "a", encoding="utf-8") as stream:
                stream.write(f"HTTP_403 {target}\n")
        raise urllib.error.HTTPError(target, 403, "Forbidden by offline lifecycle fixture", {}, None)

    urllib.request.urlopen = _github_403
