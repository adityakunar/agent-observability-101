"""Terminal input and display, separate from the agent's control flow."""

import asyncio

from agent_observability.host.turn import Turn
from agent_observability.llm.metrics import Measurements


async def choose_address(candidates: list[dict[str, str]]) -> str | None:
    print("Did you mean one of these delivery addresses?")
    for index, candidate in enumerate(candidates, 1):
        print(f"  {index}. {candidate['address']}")
    while True:
        try:
            answer = await asyncio.to_thread(
                input, "Choose a number, or 0 to correct the address: "
            )
        except EOFError:
            return None
        if answer.strip() == "0":
            return None
        if answer.strip().isdigit() and 1 <= int(answer) <= len(candidates):
            return candidates[int(answer) - 1]["id"]
        print("Choose one of the listed numbers, or 0.")


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
        memory = f"{peak:.2f} GB (server high-water)" if peak is not None else "n/a"
        context = values.context_tokens
        prompt = f"{context:,} tok" if context is not None else "n/a"
        print(
            f"llm> context {prompt} | TTFT {first} | {values.elapsed_s:.2f}s"
            f" | {throughput} | MLX peak {memory}"
        )

    def finish(self, turn: Turn) -> None:
        if self.line_open:
            print()
        if not self.displayed:
            print(f"bot> {turn.text}")
        print(f"tools: {', '.join(turn.calls) or '—'}")
        notes = []
        if turn.exhausted:
            notes.append("turn budget reached; the reply above wraps up partial progress")
        if turn.coercions:
            notes.append(f"normalized {turn.coercions} mistyped argument(s)")
        if turn.duplicates:
            notes.append(f"suppressed {turn.duplicates} repeated business action(s)")
        if notes:
            print(f"note: {'; '.join(notes)}")
