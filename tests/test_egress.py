"""The egress proxy: allowlisted tunnels only, the key added on the way out, every request logged."""

import asyncio
import io
import json

import pytest

from agent_observability import egress
from agent_observability.netpolicy import EgressDeniedError


async def _exchange(policy: egress.Policy, raw: bytes) -> bytes:
    server = await asyncio.start_server(lambda r, w: egress.handle(policy, r, w), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(raw)
        await writer.drain()
        reply = await asyncio.wait_for(reader.read(), 5)
        writer.close()
    return reply


def _policy(upstream: str = "http://127.0.0.1:9/v1", key: str = "") -> egress.Policy:
    return egress.Policy(frozenset({"pypi.org", ".github.com"}), upstream, key, io.StringIO())


def _log(policy: egress.Policy) -> list[dict]:
    return [json.loads(line) for line in policy.log.getvalue().splitlines()]


def test_allowlist_matches_exact_hosts_and_dot_suffixes():
    policy = _policy()
    assert policy.allows("pypi.org") and policy.allows("api.github.com")
    assert not policy.allows("pypi.org.evil.test") and not policy.allows("github.com.evil.test")
    assert not policy.allows("example.com")


@pytest.mark.parametrize(
    "request_line",
    [
        b"CONNECT example.com:443 HTTP/1.1",  # not allowlisted
        b"CONNECT pypi.org:22 HTTP/1.1",  # allowlisted host, wrong port
        b"GET http://pypi.org/simple/ HTTP/1.1",  # plain-HTTP proxying
    ],
)
def test_everything_else_is_refused_and_logged(request_line):
    policy = _policy()
    reply = asyncio.run(_exchange(policy, request_line + b"\r\nHost: x\r\n\r\n"))
    assert reply.startswith(b"HTTP/1.1 403")
    assert _log(policy)[0]["status"] == 403


def test_model_requests_get_the_key_and_the_agent_never_sends_it():
    seen: dict[str, bytes] = {}

    async def run() -> bytes:
        async def upstream(reader, writer):
            seen["request"] = await reader.readuntil(b"\r\n\r\n")
            seen["body"] = await reader.readexactly(2)
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
            await writer.drain()
            writer.close()

        model = await asyncio.start_server(upstream, "127.0.0.1", 0)
        port = model.sockets[0].getsockname()[1]
        async with model:
            policy = _policy(f"http://127.0.0.1:{port}/api/v1", key="sk-host-only")
            seen["policy"] = policy  # type: ignore[assignment]
            return await _exchange(
                policy,
                b"POST /v1/chat/completions HTTP/1.1\r\nHost: proxy:8899\r\n"
                b"Authorization: Bearer agent-guess\r\nContent-Length: 2\r\n\r\n{}",
            )

    reply = asyncio.run(run())
    assert reply.endswith(b"ok")
    request = seen["request"].decode()
    assert request.startswith("POST /api/v1/chat/completions HTTP/1.1")
    assert "Authorization: Bearer sk-host-only" in request
    assert "agent-guess" not in request
    assert seen["body"] == b"{}"
    entry = _log(seen["policy"])[0]  # type: ignore[arg-type]
    assert (
        entry["status"] == 200 and entry["new"] is True and "sk-host-only" not in json.dumps(entry)
    )


def test_key_only_travels_over_https_to_allowlisted_hosts():
    egress.check_upstream("http://host.docker.internal:9000/v1", "", frozenset())
    egress.check_upstream("https://api.example.com/v1", "sk", frozenset({"api.example.com"}))
    with pytest.raises(EgressDeniedError):
        egress.check_upstream("http://api.example.com/v1", "sk", frozenset({"api.example.com"}))


def test_allowlist_file_ignores_comments(tmp_path):
    path = tmp_path / "allow.txt"
    path.write_text("# comment\npypi.org  # index\n\n.github.com\n")
    assert egress.load_allowlist(path) == frozenset({"pypi.org", ".github.com"})
