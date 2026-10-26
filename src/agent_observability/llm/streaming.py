"""Buffer streamed tool fragments; return them only after a complete reply."""

from openai import AsyncStream
from openai.types.chat import ChatCompletionChunk

from .contracts import ModelError, Reply, TextCallback
from .metrics import RequestTimer
from .responses import parse_call


async def read_stream(
    stream: AsyncStream[ChatCompletionChunk],
    on_text: TextCallback | None,
    timer: RequestTimer | None = None,
) -> Reply:
    text: list[str] = []
    partial: dict[int, dict[str, str]] = {}
    finish_reason: str | None = None
    async with stream:
        async for chunk in stream:
            if timer is not None:
                timer.observe(chunk)
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if choice.finish_reason is not None:
                finish_reason = choice.finish_reason
            delta = choice.delta
            if delta.content:
                text.append(delta.content)
                if on_text is not None:
                    on_text(delta.content)
            for call in delta.tool_calls or []:
                item = partial.setdefault(call.index, {"call_id": "", "name": "", "arguments": ""})
                if call.id:
                    item["call_id"] += call.id
                if call.function:
                    item["name"] += call.function.name or ""
                    item["arguments"] += call.function.arguments or ""
    if finish_reason not in {"stop", "tool_calls"}:
        raise ModelError(
            "The model stream ended without a complete reply. No pending tools were executed."
        )
    calls = [parse_call(**partial[index]) for index in sorted(partial)]
    return Reply("".join(text) or None, calls)
