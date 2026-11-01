"""Egress proxy for a sandboxed agent: allowlist, key injection, request log.

The agent container has no route to the internet. Its only exit is this proxy.

* ``CONNECT host:443`` tunnels open only for hosts in the allowlist (PyPI, GitHub...).
* Requests to ``http://proxy:8899/v1/...`` go to the model API. The proxy adds the
  ``Authorization`` header, so the agent never sees the key.
* Plain-HTTP proxying and every other host get 403.
* Each request is one JSON line in the log: host, status, bytes, and ``new`` the
  first time a host appears.

Standard library only, so the proxy container needs no packages.

    python -m agent_observability.egress --allowlist security/egress-allowlist.txt \\
        --upstream https://api.provider.example/v1 --key-file /run/secrets/llm_api_key
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import ssl
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO
from urllib.parse import urlsplit

from agent_observability import netpolicy

MODEL_PREFIX = "/v1"
HOP_HEADERS = {"proxy-authorization", "proxy-connection", "authorization", "connection", "host"}
LIMIT = 64 * 1024


@dataclass
class Policy:
    allowed: frozenset[str]
    upstream: str
    key: str = ""
    log: TextIO = sys.stdout
    seen: set[str] = field(default_factory=set)

    def allows(self, host: str) -> bool:
        host = host.lower().rstrip(".")
        return any(
            host == rule or (rule.startswith(".") and host.endswith(rule)) for rule in self.allowed
        )

    def record(self, method: str, host: str, status: int, up: int = 0, down: int = 0) -> None:
        new = host not in self.seen
        self.seen.add(host)
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "method": method,
            "host": host,
            "status": status,
            "bytes_up": up,
            "bytes_down": down,
            "new": new,
        }
        self.log.write(json.dumps(entry) + "\n")
        self.log.flush()


def load_allowlist(path: Path) -> frozenset[str]:
    lines = (line.split("#", 1)[0].strip() for line in path.read_text().splitlines())
    return netpolicy.parse_hosts(line for line in lines if line)


def check_upstream(upstream: str, key: str, allowed: frozenset[str]) -> None:
    """The key may only travel over HTTPS to an allowlisted host (or stay on this machine)."""
    if key:
        netpolicy.check_endpoint(upstream, allowed)


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> int:
    total = 0
    try:
        while chunk := await reader.read(LIMIT):
            total += len(chunk)
            writer.write(chunk)
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        with contextlib.suppress(ConnectionError):
            writer.close()
    return total


async def _refuse(writer: asyncio.StreamWriter, status: int, reason: str) -> None:
    body = f"{status} {reason}: blocked by the agent egress proxy.\n".encode()
    writer.write(
        f"HTTP/1.1 {status} {reason}\r\nContent-Type: text/plain\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
        + body
    )
    await writer.drain()
    writer.close()


async def _read_head(reader: asyncio.StreamReader) -> tuple[str, str, list[tuple[str, str]]]:
    head = (await reader.readuntil(b"\r\n\r\n")).decode("latin-1")
    first, *lines = head.split("\r\n")
    method, target, _version = first.split(" ", 2)
    headers = [tuple(part.strip() for part in line.split(":", 1)) for line in lines if ":" in line]
    return method.upper(), target, [(name, value) for name, value in headers]


async def _tunnel(
    policy: Policy, target: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    host, _, port = target.rpartition(":")
    host = host.strip("[]")
    if port != "443" or not policy.allows(host):
        policy.record("CONNECT", host, 403)
        await _refuse(writer, 403, "Forbidden")
        return
    try:
        up_reader, up_writer = await asyncio.open_connection(host, 443)
    except OSError:
        policy.record("CONNECT", host, 502)
        await _refuse(writer, 502, "Bad Gateway")
        return
    writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
    await writer.drain()
    up, down = await asyncio.gather(_pipe(reader, up_writer), _pipe(up_reader, writer))
    policy.record("CONNECT", host, 200, up, down)


async def _model(
    policy: Policy,
    method: str,
    target: str,
    headers: list[tuple[str, str]],
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    base = urlsplit(policy.upstream)
    host = base.hostname or ""
    port = base.port or (443 if base.scheme == "https" else 80)
    path = base.path.rstrip("/") + target[len(MODEL_PREFIX) :]
    length = int(dict((k.lower(), v) for k, v in headers).get("content-length", "0") or 0)
    body = await reader.readexactly(length) if length else b""
    kept = [(k, v) for k, v in headers if k.lower() not in HOP_HEADERS]
    kept += [("Host", base.netloc), ("Connection", "close")]
    if policy.key:
        kept.append(("Authorization", f"Bearer {policy.key}"))
    request = f"{method} {path} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in kept) + "\r\n"
    context = ssl.create_default_context() if base.scheme == "https" else None
    try:
        up_reader, up_writer = await asyncio.open_connection(host, port, ssl=context)
    except OSError:
        policy.record(method, host, 502, len(body))
        await _refuse(writer, 502, "Bad Gateway")
        return
    up_writer.write(request.encode("latin-1") + body)
    await up_writer.drain()
    first = await up_reader.readline()
    status = int(first.split()[1]) if len(first.split()) > 1 else 502
    writer.write(first)
    down = len(first) + await _pipe(up_reader, writer)
    up_writer.close()
    policy.record(method, host, status, len(request) + len(body), down)


async def handle(
    policy: Policy, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    try:
        method, target, headers = await _read_head(reader)
    except (ValueError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
        writer.close()
        return
    if method == "CONNECT":
        await _tunnel(policy, target, reader, writer)
    elif target == MODEL_PREFIX or target.startswith(MODEL_PREFIX + "/"):
        await _model(policy, method, target, headers, reader, writer)
    else:
        # Absolute-form http://... (unencrypted proxying) or an unknown path.
        policy.record(method, urlsplit(target).hostname or target, 403)
        await _refuse(writer, 403, "Forbidden")


async def serve(policy: Policy, host: str, port: int) -> None:
    server = await asyncio.start_server(lambda r, w: handle(policy, r, w), host, port)
    async with server:
        await server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent_observability.egress")
    parser.add_argument("--allowlist", type=Path, required=True)
    parser.add_argument("--upstream", required=True, help="model API base URL, e.g. .../v1")
    parser.add_argument("--key-file", type=Path, help="file with the model API key (optional)")
    # 0.0.0.0 is safe here only because the proxy runs on an internal Docker network
    # with no published ports.
    parser.add_argument("--host", default="0.0.0.0", help="listen address (container network)")
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument("--log", type=Path, help="append JSON lines here (default: stdout)")
    args = parser.parse_args(argv)
    key = args.key_file.read_text().strip() if args.key_file and args.key_file.exists() else ""
    allowed = load_allowlist(args.allowlist)
    try:
        check_upstream(args.upstream, key, allowed)
    except netpolicy.EgressDeniedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    log = args.log.open("a") if args.log else sys.stdout
    policy = Policy(allowed, args.upstream, key, log)
    print(f"egress proxy on {args.host}:{args.port}; model -> {args.upstream}", file=sys.stderr)
    asyncio.run(serve(policy, args.host, args.port))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
