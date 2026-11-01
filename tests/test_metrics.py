"""Measurements distinguish output, transport chunks and server memory scope."""

import json

import httpx2 as httpx
import pytest
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionChunk
from test_model import connected_model, frame

from agent_observability.llm import memory, metrics
from agent_observability.llm.memory import read_mlx_peak
from agent_observability.llm.metrics import RequestTimer


def chunk(delta=None, usage=None):
    return ChatCompletionChunk.model_validate(
        {
            "id": "x",
            "created": 0,
            "object": "chat.completion.chunk",
            "model": "x",
            "choices": [] if delta is None else [{"index": 0, "delta": delta}],
            "usage": usage,
        }
    )


def test_first_output_ignores_role_and_usage_frames_and_counts_provider_tokens(monkeypatch):
    ticks = iter([10.0, 12.0, 15.0])
    monkeypatch.setattr(metrics, "perf_counter", lambda: next(ticks))
    timer = RequestTimer()
    timer.observe(chunk({"role": "assistant"}))
    timer.observe(chunk({"tool_calls": [{"index": 0, "id": "call-id"}]}))
    timer.observe(chunk({"tool_calls": [{"index": 0, "function": {"name": "menu"}}]}))
    timer.observe(chunk({"content": "many tokens in one chunk"}))
    timer.observe(chunk(usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}))
    result = timer.finish()
    assert result.first_output_s == 2.0
    assert result.elapsed_s == 5.0 and result.tokens_per_second == 4.0
    assert result.context_tokens == 100


def test_missing_usage_and_non_streamed_first_output_are_unknown(monkeypatch):
    ticks = iter([0.0, 2.0])
    monkeypatch.setattr(metrics, "perf_counter", lambda: next(ticks))
    result = RequestTimer().finish()
    assert result.first_output_s is None and result.tokens_per_second is None


async def test_stream_includes_usage_only_terminal_chunk_in_metrics(monkeypatch):
    records = []

    async def peak(client):
        return 5.25

    monkeypatch.setattr("agent_observability.model.read_mlx_peak", peak)

    def respond(request):
        assert json.loads(request.content)["stream_options"] == {"include_usage": True}
        usage = chunk(usage={"prompt_tokens": 10, "completion_tokens": 7, "total_tokens": 17})
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=(
                frame({"content": "Hello"})
                + frame({}, "stop")
                + "data: "
                + usage.model_dump_json()
                + "\n\ndata: [DONE]\n\n"
            ),
        )

    model = await connected_model(respond)
    model.on_metrics = records.append
    try:
        reply = await model.complete([{"role": "user", "content": "Hi"}], [])
        assert reply.text == "Hello"
        assert len(records) == 1 and records[0].output_tokens == 7
        assert records[0].first_output_s is not None and records[0].mlx_peak_gb == 5.25
    finally:
        await model.client.close()


@pytest.mark.parametrize(
    "body",
    [
        {"metal": {"peak_memory_gb": 5.25}},
        {"metal": None},
        {},
        {"metal": {"peak_memory_gb": -1}},
        {"metal": {"peak_memory_gb": True}},
        {"metal": {"peak_memory_gb": "5.25"}},
    ],
)
async def test_local_status_memory_validation(monkeypatch, body):
    original = httpx.AsyncClient
    client = AsyncOpenAI(base_url="http://localhost:9000/v1", api_key="local-key")

    def respond(request):
        assert str(request.url) == "http://localhost:9000/v1/status"
        assert request.headers["authorization"] == "Bearer local-key"
        return httpx.Response(200, json=body)

    monkeypatch.setattr(
        memory.httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(respond)),
    )
    try:
        assert await read_mlx_peak(client) == (
            5.25 if body == {"metal": {"peak_memory_gb": 5.25}} else None
        )
    finally:
        await client.close()


@pytest.mark.parametrize(
    "base_url,status",
    [
        ("https://provider.example/v1", 200),
        ("http://localhost:9000/v1", 404),
        ("http://localhost:9000/v1", 302),
    ],
)
async def test_status_optional_and_never_probes_remote_or_follows_redirect(
    monkeypatch, base_url, status
):
    original = httpx.AsyncClient
    client = AsyncOpenAI(base_url=base_url, api_key="key")
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, headers={"Location": "https://elsewhere.example"})

    monkeypatch.setattr(
        memory.httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(respond)),
    )
    try:
        assert await read_mlx_peak(client) is None
        assert len(requests) == (0 if "provider.example" in base_url else 1)
    finally:
        await client.close()


async def test_status_timeout_is_optional(monkeypatch):
    original = httpx.AsyncClient
    client = AsyncOpenAI(base_url="http://localhost:9000/v1", api_key="key")

    def respond(request):
        raise httpx.ReadTimeout("status timed out", request=request)

    monkeypatch.setattr(
        memory.httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(respond)),
    )
    try:
        assert await read_mlx_peak(client) is None
    finally:
        await client.close()


async def test_interrupted_reply_does_not_emit_success_metrics():
    from agent_observability.model import ModelError

    model = await connected_model(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=frame({"content": "Partial"}) + "data: [DONE]\n\n",
        )
    )
    records = []
    model.on_metrics = records.append
    try:
        with pytest.raises(ModelError):
            await model.complete([{"role": "user", "content": "Hi"}], [])
        assert not records
    finally:
        await model.client.close()


def test_console_metrics_close_streamed_line_and_label_scope(capsys):
    from agent_observability.llm.metrics import Measurements
    from agent_observability.terminal import Console

    console = Console()
    console.text("Hello")
    console.metrics(Measurements(2.0, 0.5, 20, 5.25, context_tokens=6120))
    output = capsys.readouterr().out
    assert "Hello\nllm> context 6,120 tok | TTFT 0.50s" in output
    assert "10.0 output tok/s (request)" in output
    assert "5.25 GB (server high-water)" in output
    console.metrics(Measurements(1.0, None, None))
    assert "context n/a | TTFT n/a" in capsys.readouterr().out
