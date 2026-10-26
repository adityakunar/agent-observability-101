# Present Chapter 1: see what a local agent actually did

A 25-minute demo-led talk, followed by 5 minutes of questions. For intermediate
Python developers and data scientists building tool-using assistants. Assume
Python functions, dictionaries and basic HTTP; introduce MCP and asynchronous
calls as they appear. No prior Prefab or MLX experience is required.

The audience should leave able to build a Python operator view, observe MCP
retrieval through middleware, and interpret local-model measurements without
confusing a model request with a customer turn or server-wide activity.

Keep one customer journey throughout: a pizza order, a question about garlic
bread, and a missing delivery address. The central question is: **what evidence
shows what happened?** The model's words, tool results and business records each
answer a different part of that question. Chapter 1 establishes these boundaries;
full conversation tracing and evaluations come later.

## Before the talk

From the repository root, install the prerequisites in [README.md](README.md),
including its pinned rapid-mlx version on Apple silicon. Then run:

```bash
make setup
make verify
make up STARTUP_TIMEOUT=300
make status
make chat
```

Download the model and dependencies before the event. Rehearse on the actual
machine with the same model, quantization and settings. If memory pressure
requires a lower GPU memory limit, follow the README and rehearse again. Check
that `.env.local` selects the intended endpoint and model without displaying
credentials. Existing services can be reused, so confirm what is actually serving.

Open the [delivery desk](http://localhost:8000) beside the terminal. Increase the
terminal font and check that the cart, FAQ Sources and Model server panel are
readable. Use `make logs` if startup fails. A fresh managed server clears the
in-memory demo state: leave chat with `/quit`, then `make down` and `make up`.
Stop only the services this checkout started; manage any pre-existing service
separately. Keep the two bundled screenshots available as a final fallback.

The 26 October 2026 integration smoke check used Python 3.14.4, rapid-mlx 0.16.8,
Gemma 4 E4B 4-bit and a 0.5 GPU memory cap. The cached weights were revision
`475b9088d29754a3379866cf5aeb6b41acd313c2` of
`mlx-community/gemma-4-e4b-it-4bit`; the serving alias does not freeze that revision.
A scripted message driver with automatic address selection reached the €20.96
order and retained its cancellation; no order was created without an address.
It also encountered an empty model reply, handled by the host's fallback, and
an allergen answer that did not read the full source document. This verifies the
integration, not a reliable transcript or a human-driven live demonstration.
Use **Open source** to show the table if the model skips the full read.

## 0–9 minutes: Prefab basics — show the business outcome

**0–2:** Introduce the customer journey and show the desk before explaining its
implementation. Say: “A reply saying an order is confirmed is a claim. The saved
order is the business record.” This is a fictional service with in-memory state;
it takes no payment and performs no fulfillment.

**2–6:** In a fresh chat, send one request per message:

> One large pepperoni on thin crust, please.

> Add garlic bread and a Coke, then apply the meal deal if it qualifies.

Show **Active Carts**. The tools calculate prices and deal eligibility; the desk
reads their resulting state. A live model may ask a question or choose a different
valid sequence. Inspect the records rather than promising an exact transcript.

> Confirm my order.

Without a selected address, the assistant may ask for details. If it calls
`confirm_order`, the tool refuses and preserves the cart. There should be no
confirmed order. Do not claim that the model must make the rejected call.

**6–9:** Walk through [operator/app.py](src/agent_observability/pizza/operator/app.py),
[snapshot.py](src/agent_observability/pizza/operator/snapshot.py) and
[routes.py](src/agent_observability/pizza/operator/routes.py). Explain just the
Prefab basics: nested Python components form the view; initial `state` holds a
snapshot; `Fetch` requests `/desk/snapshot`; `SetState` replaces the browser state;
component bindings display it. `SetInterval` refreshes every three seconds, so
allow a refresh or choose **Refresh now** before judging the display.

The MCP server owns the tools, records and page. The bundled renderer makes the
desk work without a CDN. This is an operator view of business records, not yet
a trace viewer. Show one component and its data binding, rather than every tab.

## 9–16 minutes: MCP middleware — show where evidence came from

Ask the same customer question:

> Does the garlic bread contain milk? Where does it say that?

In **FAQ Sources**, inspect the lookup and choose **Open source**. The source's
`MI` column and key identify milk/dairy; the kitchen notice qualifies the answer.
A matching row without headings can lose meaning. A model can read the document
directly or search first; do not require one particular sequence in the live demo.

Open [faq/activity.py](src/agent_observability/faq/activity.py) and show registration
in [pizza/server.py](src/agent_observability/pizza/server.py):

```python
mcp.add_middleware(FaqActivityMiddleware())
```

Explain the wrapper: `on_call_tool` lets unrelated calls pass through, observes
`faq_*` calls, awaits `call_next(context)`, returns the same result, and records
the outcome in `finally`, including failures. The tool functions can stay focused
on reading Markdown. A no-match search and a failed read are distinct outcomes.
The feed is a bounded in-memory record of recent FAQ activity; it is not a durable
archive or a trace of every business call.

Opening a source in the operator page calls the reader directly, so the
operator's inspection does not appear as a new assistant lookup. Successful
retrieval also does not prove that the final answer preserved the facts. This
is the question later conversation evaluations will address.

## 16–23 minutes: rapid-mlx — distinguish request and server measurements

Return to chat and finish the same order:

> Deliver to Damrk 1, Amsterdam. Show me the delivery quote before confirming.

Choose `Damrak 1, 1012 LG Amsterdam` when the host presents the numbered address
choices. Inspect the selected address and quote. Then send a separate message:

> Yes, confirm this order.

For one large pepperoni, garlic bread and Coke with the standard deal, the
current tool contract totals **€20.96 including €1.99 delivery**. Check **Orders**
for the actual record. The tool enforces items and a selected address; separate
customer approval is prompt guidance in this demo, not an enforced tool condition.

Use the actual `llm>` lines from these requests to explain the measurements:

- **Context:** provider-reported prompt tokens, including the tool catalog and
  conversation sent with that request. Look at growth; do not count characters.
- **Client TTFT:** monotonic elapsed time until the first nonempty text,
  reasoning or tool-call delta. It includes queueing, transport and buffering;
  it is not the engine's exact first-token timestamp or necessarily visible text.
- **Elapsed and output tok/s (request):** completion tokens reported by the
  provider divided by the entire request duration, including the initial wait.
  This is not decode-only speed; stream chunks are not tokens.
- **MLX peak:** the serving process's allocator high-water mark, read from local
  `/v1/status`. Rapid-mlx 0.16.8 preserves this cumulative peak across internal
  sampling resets. It includes weights and other work in the serving process; it is
  not memory attributable to this request or total machine RAM. The client does
  not reset this shared counter.

One user turn can trigger several model requests. The request timer excludes
tool execution and waiting for the customer's address choice. Missing usage or
status support is reported as unavailable; non-streamed replies have no TTFT.
Show [llm/metrics.py](src/agent_observability/llm/metrics.py) for the timer and
[llm/memory.py](src/agent_observability/llm/memory.py) for the optional status lookup.

Compare this with the desk's **Model server** panel: rapid-mlx supplies generation
and prompt rates, requests processed and peak memory for the server. These are
not per-conversation measurements. Do not equate its generation rate with the
client's whole-request rate. For comparisons, hold hardware, model, quantization
and prompt fixed and separate cold from warm requests. Present observed values,
without claiming a benchmark or a model reliability rate.

Use the final minute of this arc to show
[`Model.complete`](src/agent_observability/llm/contracts.py) and the README's
[endpoint settings](README.md#swap-the-model-keep-the-agent). The adapter owns one
model request; the host owns the loop and business dispatch. Link to
[LiteLLM's completion interface](https://docs.litellm.ai/docs/completion) as an
extension for supporting more providers, translated into the same `Reply`
contract. Changing the model can change behavior, so repeat the journey after a
swap. The starter does not require LiteLLM or a hosted provider.

## 23–25 minutes: return to the evidence

Point at the three connected views: Prefab shows business state; middleware shows
retrieved evidence; rapid-mlx and the client report differently scoped costs of
inference. Explain what the audience can reuse in a different application.

Chapter 2 will connect requests, tool arguments/results, failures and state
changes in a conversation trace. Later chapters check business sequence and
answer quality, preserve runs, and support human review. Treat those as the
continuation, not content already delivered by this chapter. Take questions for
the remaining five minutes.

For the implementation handoff and release conditions for those chapters, use
[ROADMAP.md](ROADMAP.md).

## Backup when a live model is unavailable

The desktop UI and MCP tools work without model inference. Start only the server
in one terminal with `make server`, open the desk, and run this in another:

```bash
uv run --locked python - <<'PY'
import asyncio
from fastmcp import Client
from fastmcp.exceptions import ToolError

async def main():
    async with Client("http://localhost:8000/mcp") as client:
        await client.call_tool("customize_and_add", {
            "session_id": "presenter-backup", "pizza_id": "pepperoni",
            "size": "large", "crust": "thin",
        })
        for name, args in [
            ("faq_grep", {"query": "garlic bread", "filename": "allergen_info.md"}),
            ("faq_read", {"filename": "allergen_info.md"}),
        ]:
            print(name, (await client.call_tool(name, args)).data)
        try:
            await client.call_tool("confirm_order", {"session_id": "presenter-backup"})
        except ToolError as exc:
            print("Expected refusal:", exc)

asyncio.run(main())
PY
```

Run this once against fresh server state. The cart and FAQ activity should appear
after refresh; confirmation is refused because no address was selected. Say
explicitly that these are direct MCP calls, bypassing the model and chat host.
They demonstrate tool/UI contracts, not a successful live agent conversation.

Existing offline checks provide a second fallback, without a running server or
model:

```bash
uv run --locked pytest tests/test_tools.py tests/test_operator_view.py tests/test_metrics.py
```

These exercise real in-process MCP tools and UI responses, with scripted or
mocked inputs where needed. They verify contracts; mocked timing/status values
are not measured rapid-mlx performance. The bundled [desk screenshot](resources/screenshots/operator-desk.jpg)
and [order screenshot](resources/screenshots/confirmed-order.jpg) came from a
direct MCP walkthrough, not a live model transcript. Use them with that label.

For a mixed-hardware workshop, first verify a second complete model path and add
exercises. The primary live recipe is Apple silicon; the README's alternative
endpoint wiring has offline tests, but its Ollama/Linux conversation recipe has
not been verified live here. A rehearsed presenter demo is a different readiness
bar from attendees installing and completing the workflow themselves.
