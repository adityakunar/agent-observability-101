"""The key only goes to allowlisted HTTPS hosts; the desk only answers this machine's pages."""

import asyncio

import pytest

from agent_observability.netpolicy import EgressDeniedError, LocalOnly, check_endpoint


@pytest.mark.parametrize(
    "url", ["http://localhost:9000/v1", "http://127.0.0.1:9000/v1", "http://[::1]:9000/v1"]
)
def test_loopback_model_needs_no_allowlist(url):
    check_endpoint(url, [])


def test_hosted_model_must_be_https_and_allowlisted():
    assert check_endpoint("https://api.example.com/v1", ["API.example.com"]) == "api.example.com"
    for url, allowed in [
        ("https://api.example.com/v1", []),
        ("http://api.example.com/v1", ["api.example.com"]),
        ("https://api.example.com.evil.test/v1", ["api.example.com"]),
        ("ftp://localhost/v1", []),
        ("not a url", []),
    ]:
        with pytest.raises(EgressDeniedError):
            check_endpoint(url, allowed)


def _request(headers: dict[str, str], kind: str = "http") -> list[dict]:
    sent: list[dict] = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request"}

    scope = {
        "type": kind,
        "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
    }
    asyncio.run(LocalOnly(app)(scope, receive, send))
    return sent


@pytest.mark.parametrize(
    "headers",
    [
        {"host": "localhost:8000"},
        {"host": "127.0.0.1:8000", "origin": "http://localhost:8000"},
        {"host": "[::1]:8000", "origin": "http://127.0.0.1:8000"},
    ],
)
def test_local_requests_pass(headers):
    assert _request(headers)[0]["status"] == 200


@pytest.mark.parametrize(
    "headers",
    [
        {"host": "evil.example:8000"},  # DNS rebinding: a public name resolving to 127.0.0.1
        {"host": "localhost:8000", "origin": "https://evil.example"},
        {"host": "localhost:8000", "origin": "null"},
        {},
    ],
)
def test_other_sites_are_refused(headers):
    assert _request(headers)[0]["status"] == 403


def test_foreign_websocket_is_closed():
    assert _request({"host": "evil.example"}, "websocket")[0] == {
        "type": "websocket.close",
        "code": 1008,
    }


def test_lifespan_passes_through():
    assert _request({}, "lifespan")[0]["status"] == 200
