"""One API call in, one parsed reply out. The host owns the conversation loop."""

from collections.abc import Callable
from dataclasses import replace
from typing import Any, cast

import httpx2 as httpx
from openai import APIError, AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from agent_observability.llm.contracts import Model, ModelError, Reply, TextCallback, ToolCall
from agent_observability.llm.memory import read_mlx_peak
from agent_observability.llm.metrics import Measurements, RequestTimer
from agent_observability.llm.responses import read_response, request_error
from agent_observability.llm.streaming import read_stream

__all__ = ["APIModel", "Model", "ModelError", "Reply", "TextCallback", "ToolCall"]


class APIModel:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str = "not-needed",
        streaming: bool = True,
        temperature: float | None = 0.2,
    ) -> None:
        self.base_url = base_url
        self.temperature = temperature
        self.model = model
        self.streaming = streaming
        self.on_metrics: Callable[[Measurements], None] | None = None
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key, max_retries=0)

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        on_text: TextCallback | None = None,
    ) -> Reply:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": cast(list[ChatCompletionMessageParam], messages),
            "max_tokens": 1024,
        }
        if self.temperature is not None:
            request["temperature"] = self.temperature
        if tools:
            request.update(tools=tools, tool_choice="auto")
        timer = RequestTimer()
        try:
            if self.streaming:
                stream = await self.client.chat.completions.create(
                    **request, stream=True, stream_options={"include_usage": True}
                )
                reply = await read_stream(stream, on_text, timer)
            else:
                response = await self.client.chat.completions.create(**request, stream=False)
                timer.observe(response)
                reply = read_response(response)
                if reply.text and on_text:
                    on_text(reply.text)
        except (APIError, httpx.HTTPError, ValueError) as exc:
            raise request_error(exc, self.base_url) from exc
        measurements = timer.finish()
        if self.on_metrics:
            peak = await read_mlx_peak(self.client)
            self.on_metrics(replace(measurements, mlx_peak_gb=peak))
        return reply
