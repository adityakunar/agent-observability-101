"""Terminal input and display, separate from the agent's control flow."""

from agent_observability.client import Turn
from agent_observability.llm.metrics import Measurements


class Console:
    def __init__(self) -> None:
        self.line_open = False
        self.displayed = False

    def text(self, fragment: str) -> None:
        if not self.line_open:
            print("bot> ", end="", flush=True)
            self.line_open = True
        print(fragment, end="", flush=True)
        self.displayed = True

    def tool(self, name: str) -> None:
        if self.line_open:
            print()
            self.line_open = False
        print(f"tool> {name}", flush=True)

    def metrics(self, values: Measurements) -> None:
        if self.line_open:
            print()
            self.line_open = False
        first = f"{values.first_output_s:.2f}s" if values.first_output_s is not None else "n/a"
        rate = values.tokens_per_second
        throughput = f"{rate:.1f} output tok/s (request)" if rate is not None else "token rate n/a"
        peak = values.mlx_peak_gb
        memory = f"{peak:.2f} GB (server)" if peak is not None else "n/a"
        context = values.context_tokens
        prompt = f"{context:,} tok" if context is not None else "n/a"
        print(
            f"llm> context {prompt} | TTFT {first} | total {values.elapsed_s:.2f}s"
            f" | {throughput} | MLX peak {memory}"
        )

    def finish(self, turn: Turn) -> None:
        if self.line_open:
            print()
        if not self.displayed:
            print(f"bot> {turn.text}")
        print(f"tools: {', '.join(turn.calls) or 'none'}")
        notes = []
        if turn.exhausted:
            notes.append("turn budget reached; the reply above wraps up partial progress")
        if turn.coercions:
            notes.append(f"normalized {turn.coercions} mistyped argument(s)")
        if turn.duplicates:
            notes.append(f"suppressed {turn.duplicates} repeated business action(s)")
        if turn.reasks:
            notes.append("the model said nothing; the host asked again")
        if turn.fallback:
            notes.append("the reply above is from the host, not from the model")
        if notes:
            print(f"note: {'; '.join(notes)}")
