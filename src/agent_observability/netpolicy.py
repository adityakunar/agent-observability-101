"""Network rules: where the API key may go, and who may talk to the local desk.

Two rules, both default-deny:

* Outbound: the model endpoint must be loopback, or an HTTPS host named in
  ``AGENT_OBSERVABILITY_ALLOWED_HOSTS``. Anything else is refused before the key is
  handed out, so a typo or a poisoned ``.env`` cannot ship the key elsewhere.
* Inbound: the MCP server and desk answer only requests whose ``Host`` is a loopback
  name and whose ``Origin``, when a browser sends one, is also loopback. Binding to
  127.0.0.1 stops other machines; this check stops other *websites* open in your
  browser, including DNS-rebinding tricks that point a domain at 127.0.0.1.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, MutableMapping
from typing import Any
from urllib.parse import urlsplit

LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class EgressDeniedError(RuntimeError):
    """The configured endpoint is not on the outbound allowlist."""


def parse_hosts(value: str | Iterable[str]) -> frozenset[str]:
    items = value.split(",") if isinstance(value, str) else value
    return frozenset(host.strip().lower() for host in items if host.strip())


def check_endpoint(url: str, allowed_hosts: Iterable[str]) -> str:
    """Return the host if ``url`` may receive the API key, else raise."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if not host or parts.scheme not in ("http", "https"):
        raise EgressDeniedError(f"Model endpoint {url!r} is not an http(s) URL.")
    if host in LOOPBACK:
        return host
    if parts.scheme != "https":
        raise EgressDeniedError(f"Refusing to send the API key to {host} over plain HTTP.")
    if host not in parse_hosts(allowed_hosts):
        raise EgressDeniedError(
            f"{host} is not in AGENT_OBSERVABILITY_ALLOWED_HOSTS; add it there if you trust it."
        )
    return host


def _host_name(value: str) -> str:
    """'localhost:8000' -> 'localhost'; '[::1]:8000' -> '::1'."""
    value = value.strip().lower()
    if value.startswith("["):
        return value[1 : value.find("]")] if "]" in value else ""
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def is_local_request(headers: Iterable[tuple[bytes, bytes]]) -> bool:
    found = {name.decode("latin-1").lower(): raw.decode("latin-1") for name, raw in headers}
    if _host_name(found.get("host", "")) not in LOOPBACK:
        return False
    origin = found.get("origin")
    if origin is None or origin == "null":
        return origin is None  # Sandboxed iframes and file:// pages send "null"; refuse them.
    return (urlsplit(origin).hostname or "").lower() in LOOPBACK


class LocalOnly:
    """ASGI wrapper: 403 for any HTTP or WebSocket request that is not from this machine's pages."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket") and not is_local_request(
            scope.get("headers", [])
        ):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            body = b"Forbidden: this server only answers pages served from localhost.\n"
            await send(
                {
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [
                        (b"content-type", b"text/plain"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)
