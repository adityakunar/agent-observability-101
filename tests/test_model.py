"""The compatible endpoint returns structured tool requests."""

import json

import httpx2 as httpx
import pytest
from openai import AsyncOpenAI

from agent_observability.model import APIModel


@pytest.mark.parametrize(
    "base_url,api_key",
    [
        ("http://localhost:9000/v1", "not-needed"),
        ("https://model-provider.example/v1", "test-provider-key"),
    ],
)
async def test_model_wire_request_and_tool_arguments(base_url, api_key):
    def respond(request):
        assert str(request.url) == f"{base_url}/chat/completions"
        assert request.headers["authorization"] == f"Bearer {api_key}"
        payload = json.loads(request.content)
        assert payload["model"] == "local-model"
        assert payload["messages"][0]["content"] == "Order pizza."
        assert payload["tools"][0]["function"]["name"] == "browse_menu"
        return httpx.Response(
            200,
            json={
                "id": "reply",
                "object": "chat.completion",
                "created": 0,
                "model": "local-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "tool",
                                    "type": "function",
                                    "function": {
                                        "name": "browse_menu",
                                        "arguments": '{"category":"pizza"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
            },
        )

    model = APIModel(base_url, "local-model", api_key=api_key, streaming=False)
    configured_key = model.client.api_key
    await model.client.close()
    model.client = AsyncOpenAI(
        base_url=model.base_url,
        api_key=configured_key,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    try:
        reply = await model.complete(
            [{"role": "system", "content": "Order pizza."}],
            [
                {
                    "type": "function",
                    "function": {"name": "browse_menu", "parameters": {"type": "object"}},
                }
            ],
        )
        assert reply.tool_calls[0].arguments == {"category": "pizza"}
    finally:
        await model.client.close()


def frame(delta, finish_reason=None):
    return (
        "data: "
        + json.dumps(
            {
                "id": "reply",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "local-model",
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
            }
        )
        + "\n\n"
    )


async def connected_model(respond):
    model = APIModel("http://localhost:9000/v1", "local-model")
    await model.client.close()
    model.client = AsyncOpenAI(
        base_url=model.base_url,
        api_key="not-needed",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        max_retries=0,
    )
    return model


async def test_stream_text_is_emitted_before_completion_and_stream_is_closed():
    fragments = []
    closed = []

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield frame({"content": "Hello "}).encode()
            assert fragments == ["Hello "]
            yield frame({"content": "there."}).encode()
            assert fragments == ["Hello ", "there."]
            yield frame({}, "stop").encode()
            yield b"data: [DONE]\n\n"

        async def aclose(self):
            closed.append(True)

    def respond(request):
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Body())

    model = await connected_model(respond)
    try:
        reply = await model.complete(
            [{"role": "user", "content": "Hi"}], [], on_text=fragments.append
        )
        assert reply.text == "Hello there." and not reply.tool_calls and closed
    finally:
        await model.client.close()


async def test_interleaved_fragmented_tool_calls_are_assembled_by_index():
    chunks = [
        frame(
            {
                "tool_calls": [
                    {
                        "index": 1,
                        "id": "extra",
                        "type": "function",
                        "function": {"name": "add_extra", "arguments": '{"item_'},
                    },
                    {
                        "index": 0,
                        "id": "menu",
                        "type": "function",
                        "function": {"name": "browse_menu", "arguments": '{"cate'},
                    },
                ]
            }
        ),
        frame(
            {
                "tool_calls": [
                    {"index": 0, "function": {"arguments": 'gory":"pizza"}'}},
                    {"index": 1, "function": {"arguments": 'id":"coke"}'}},
                ]
            }
        ),
        frame({}, "tool_calls"),
        "data: [DONE]\n\n",
    ]
    model = await connected_model(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content="".join(chunks),
        )
    )
    try:
        reply = await model.complete([{"role": "user", "content": "Menu"}], [])
        assert [(c.id, c.name, c.arguments) for c in reply.tool_calls] == [
            ("menu", "browse_menu", {"category": "pizza"}),
            ("extra", "add_extra", {"item_id": "coke"}),
        ]
    finally:
        await model.client.close()


async def test_interrupted_stream_dispatches_nothing_and_next_turn_recovers():
    from fastmcp import Client

    from agent_observability.client import Agent
    from agent_observability.pizza import server, state

    state.sessions.clear()
    responses = iter(
        [
            frame(
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "add",
                            "type": "function",
                            "function": {
                                "name": "add_extra",
                                "arguments": '{"item_id":"coke"}',
                            },
                        }
                    ]
                }
            )
            + "data: [DONE]\n\n",
            frame({"content": "Please try again."}) + frame({}, "stop") + "data: [DONE]\n\n",
        ]
    )
    model = await connected_model(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=next(responses),
        )
    )
    try:
        async with Client(server.mcp) as client:
            agent = Agent(client, model, "Pizza")
            await agent.prepare()
            turn = await agent.send("One coke")
            assert turn.error and not turn.calls and not state.sessions
            second = await agent.send("Try again")
            assert second.text == "Please try again." and second.error is None
    finally:
        await model.client.close()


async def test_schema_rejection_keeps_prior_cart_changes_and_chat_alive():
    from fastmcp import Client

    from agent_observability.client import Agent
    from agent_observability.pizza import server, state

    state.sessions.clear()
    bodies = iter(
        [
            httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=(
                    frame(
                        {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "add",
                                    "type": "function",
                                    "function": {
                                        "name": "add_extra",
                                        "arguments": '{"item_id":"coke"}',
                                    },
                                }
                            ]
                        }
                    )
                    + frame({}, "tool_calls")
                    + "data: [DONE]\n\n"
                ),
            ),
            httpx.Response(400, json={"detail": "Generated tool arguments violate schema."}),
        ]
    )
    model = await connected_model(lambda request: next(bodies))
    try:
        async with Client(server.mcp) as client:
            agent = Agent(client, model, "Pizza")
            await agent.prepare()
            turn = await agent.send("One coke")
            assert turn.error and "HTTP 400" in turn.text and turn.calls == ["add_extra"]
            assert len(state.sessions[agent.session_id].items) == 1
    finally:
        await model.client.close()


async def test_error_event_after_partial_tools_executes_nothing():
    from fastmcp import Client

    from agent_observability.client import Agent
    from agent_observability.pizza import server, state

    state.sessions.clear()
    body = (
        frame(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "add",
                        "type": "function",
                        "function": {
                            "name": "add_extra",
                            "arguments": '{"item_id":"coke"}',
                        },
                    }
                ]
            }
        )
        + 'data: {"error": {"message": "inference failed"}}\n\n'
    )
    model = await connected_model(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=body,
        )
    )
    try:
        async with Client(server.mcp) as client:
            agent = Agent(client, model, "Pizza")
            await agent.prepare()
            turn = await agent.send("One coke")
        assert turn.error and "stream reported an error" in turn.text
        assert not state.sessions and not turn.calls
    finally:
        await model.client.close()


async def test_network_failure_mid_stream_keeps_chat_alive_and_closes_response():
    from fastmcp import Client

    from agent_observability.client import Agent
    from agent_observability.pizza import server, state

    state.sessions.clear()
    closed = []

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield frame(
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "add",
                            "type": "function",
                            "function": {
                                "name": "add_extra",
                                "arguments": '{"item_id":"coke"}',
                            },
                        }
                    ]
                }
            ).encode()
            raise httpx.ReadError("Connection dropped")

        async def aclose(self):
            closed.append(True)

    model = await connected_model(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=Body(),
        )
    )
    try:
        async with Client(server.mcp) as client:
            agent = Agent(client, model, "Pizza")
            await agent.prepare()
            turn = await agent.send("One coke")
        assert turn.error and "connection failed during streaming" in turn.text
        assert not state.sessions and not turn.calls and closed
    finally:
        await model.client.close()
