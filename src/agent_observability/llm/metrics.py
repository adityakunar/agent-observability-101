"""Client timings and provider token counts for one model request, not a whole turn."""

from dataclasses import dataclass
from time import perf_counter

from openai.types.chat import ChatCompletion, ChatCompletionChunk


@dataclass(frozen=True)
class Measurements:
    elapsed_s: float
    first_output_s: float | None
    output_tokens: int | None
    mlx_peak_gb: float | None = None
    # Prompt tokens: the whole conversation so far, re-sent with every request.
    context_tokens: int | None = None

    @property
    def tokens_per_second(self) -> float | None:
        if self.output_tokens is None or self.elapsed_s <= 0:
            return None
        return self.output_tokens / self.elapsed_s


class RequestTimer:
    def __init__(self) -> None:
        self.started = perf_counter()
        self.first_output: float | None = None
        self.output_tokens: int | None = None
        self.context_tokens: int | None = None

    def observe(self, response: ChatCompletion | ChatCompletionChunk) -> None:
        if response.usage is not None:
            self.output_tokens = response.usage.completion_tokens
            self.context_tokens = response.usage.prompt_tokens
        if isinstance(response, ChatCompletionChunk) and self.first_output is None:
            for choice in response.choices:
                delta = choice.delta
                tool_output = any(
                    call.function and (call.function.name or call.function.arguments)
                    for call in delta.tool_calls or []
                )
                if delta.content or tool_output or getattr(delta, "reasoning_content", None):
                    self.first_output = perf_counter() - self.started
                    break

    def finish(self) -> Measurements:
        return Measurements(
            perf_counter() - self.started,
            self.first_output,
            self.output_tokens,
            context_tokens=self.context_tokens,
        )
