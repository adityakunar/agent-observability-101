"""Wire the configured model, MCP client and terminal into one conversation."""

import asyncio

from fastmcp import Client

from agent_observability.client import Agent
from agent_observability.config import llm_api_key, settings
from agent_observability.keys import KeyExpiredError, KeyMissingError
from agent_observability.model import APIModel
from agent_observability.netpolicy import EgressDeniedError
from agent_observability.pizza.prompt import PROMPT
from agent_observability.terminal import Console, choose_address


async def run() -> None:
    model = APIModel(
        settings.llm_base_url,
        settings.llm_model,
        api_key=llm_api_key(),
        streaming=settings.streaming,
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
                choose_address=choose_address,
            )
            await agent.prepare()
            print("Lantern Pizza — /quit to leave. Delivery desk: http://localhost:8000")
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
        print(f"Cannot complete chat: {exc}\nCheck make server and your model endpoint.")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
