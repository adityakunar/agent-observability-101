"""Wire the configured model, MCP client and terminal into one conversation."""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx2 as httpx
from fastmcp import Client

from agent_observability.client import Agent
from agent_observability.config import describe_model, llm_api_key, settings
from agent_observability.keys import KeyExpiredError, KeyMissingError
from agent_observability.model import APIModel
from agent_observability.netpolicy import EgressDeniedError
from agent_observability.pizza.prompt import PROMPT
from agent_observability.record import Recorder
from agent_observability.terminal import Console


async def desk_snapshot() -> dict[str, Any]:
    """Read the business records from the server's own view, not from the model."""
    async with httpx.AsyncClient() as http:
        data: dict[str, Any] = (await http.get("http://localhost:8000/desk/snapshot")).json()
        return data


async def run() -> None:
    # One record for each chat. .run/ is not in Git: a record holds the full conversation.
    record = Path(".run/records") / f"{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    model = APIModel(
        settings.llm_base_url,
        settings.llm_model,
        api_key=llm_api_key(),
        temperature=settings.llm_temperature,
    )
    try:
        async with Client("http://localhost:8000/mcp") as client:
            agent = Agent(
                client,
                model,
                PROMPT,
                max_tool_iterations=settings.max_tool_iterations,
                max_tool_calls=settings.max_tool_calls,
                recorder=Recorder(record, desk_snapshot),
            )
            await agent.prepare()
            print(describe_model())
            print("Lantern Pizza — /quit to leave. Delivery desk: http://localhost:8000")
            print(f"record: {record} (read it with make inspect)")
            while True:
                try:
                    text = await asyncio.to_thread(input, "you> ")
                except EOFError:
                    return
                if text.strip() == "/quit":
                    return
                if not text.strip():
                    continue
                console = Console()
                model.on_metrics = console.metrics
                turn = await agent.send(text, on_text=console.text, on_tool=console.tool)
                console.finish(turn)
    finally:
        await model.client.close()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nGoodbye.")
    except (KeyExpiredError, KeyMissingError, EgressDeniedError) as exc:
        print(f"Cannot start chat: {exc}")
        raise SystemExit(1) from exc
    except (RuntimeError, ConnectionError, OSError) as exc:
        print(
            f"Cannot complete chat: {exc}\n"
            f"Is make server running? Does the model endpoint answer? ({describe_model()})"
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
