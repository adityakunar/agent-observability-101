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

    def host(self, message: str) -> None:
        """A decision of the host that the customer should see, such as a caught claim."""
        if self.line_open:
            print()
            self.line_open = False
        print(f"host> {message}", flush=True)

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
        # Each note with the field of the turn that makes it apply.
        notes = [
            note
            for applies, note in (
                (turn.exhausted, "turn budget reached; the reply above wraps up partial progress"),
                (turn.coercions, f"normalized {turn.coercions} mistyped argument(s)"),
                (turn.duplicates, f"suppressed {turn.duplicates} repeated business action(s)"),
                (turn.reasks, "the model said nothing; the host asked again"),
                (turn.caught, "the host caught a claim with no change in the record"),
                (turn.warned, "the claim stayed, so the customer read a note"),
                (turn.fallback, "the reply above is from the host, not from the model"),
            )
            if applies
        ]
        if notes:
            print(f"note: {'; '.join(notes)}")
