"""Read the record of a chat (record.py) and find the step where its layers disagree.

    python -m agent_observability.inspector show [file]    the three layers of each step
    python -m agent_observability.inspector check [file]   only the steps to look at

With no file, it reads the newest record in .run/records/.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from agent_observability.catch import CLAIM_WORDS
from agent_observability.config import llm_api_key, settings
from agent_observability.model import APIModel, ModelError
from agent_observability.record import Step, load

RECORDS = Path(".run/records")


def changes(step: Step) -> list[str]:
    """The fields of the business record that this step changed."""
    before, after = step["record"]["before"], step["record"]["after"]
    return [f"{key}: {before[key]} -> {after[key]}" for key in after if before[key] != after[key]]


def findings(session: dict[str, Any], steps: list[Step]) -> list[str]:
    """One line for each place where two layers disagree."""
    found = []
    for step in steps:
        where = f"turn {step['turn']} step {step['step']}"
        calls = step["model"]["calls"]
        ran = []
        # The host answers each call of the model in order, so the two lists line up.
        for number, act in enumerate(step["host"]):
            tool, decision = act.get("tool"), act["decision"]
            if decision == "ran":
                ran.append(tool)
                # Model and host disagree: the host repaired an argument before the call.
                sent = calls[number]["arguments"]
                repaired = [key for key in sent if sent[key] != act["arguments"].get(key)]
                if repaired:
                    found.append(
                        f"{where}  model/host   host repaired {tool}: {', '.join(repaired)}"
                    )
            else:
                # Model and host disagree: the host did not do what the model asked.
                # A decision with no tool is about a silent reply: asked again, or fallback.
                what = f"{decision} {tool}: {act['result']}" if tool else decision
                found.append(f"{where}  model/host   host {what}")
        # Host and record disagree: a business tool ran, and the record is the same.
        business = [tool for tool in ran if tool in session["business_tools"]]
        if business and not changes(step):
            found.append(
                f"{where}  host/record  ran {', '.join(business)}; the record did not change"
            )
    # Words and record disagree: the answer reports an action, and the record is the
    # same as before the customer's message. The words cannot judge a sentence: they
    # tell you which one to read.
    for turn in sorted({step["turn"] for step in steps}):
        of_turn = [step for step in steps if step["turn"] == turn]
        last = of_turn[-1]
        words = sorted({w.lower() for w in CLAIM_WORDS.findall(last["model"]["text"] or "")})
        if words and of_turn[0]["record"]["before"] == last["record"]["after"]:
            said = ", ".join(words)
            found.append(
                f"turn {turn} step {last['step']}  words/record the answer says '{said}';"
                " the record did not change in this turn"
            )
    return found


def show(steps: list[Step]) -> None:
    for step in steps:
        if step["step"] == 1:
            print(f"\nturn {step['turn']}  you> {step['customer']}")
        tokens = step["context_tokens"]
        print(f"  step {step['step']}  context {f'{tokens:,}' if tokens else 'n/a'} tok")
        for call in step["model"]["calls"]:
            print(f"    model   asked {call['tool']} {json.dumps(call['arguments'])}")
        if step["model"]["text"]:
            print(f"    model   said  {' '.join(step['model']['text'].split())}")  # one line
        for act in step["host"]:
            print(f"    host    {act['decision']} {act.get('tool', '')}".rstrip())
        for change in changes(step) or ["no change"]:
            print(f"    record  {change}")


async def faithful(session: dict[str, Any], steps: list[Step]) -> str:
    """Send each recorded request again and compare the server's token counts.

    The same count means that the record holds what the model received.
    """
    model = APIModel(settings.llm_base_url, settings.llm_model, api_key=llm_api_key())
    counted = [step for step in steps if step["request"] and step["context_tokens"]]
    if not counted:
        return "faithful: not checked. This record has no token counts."
    differ = []
    try:
        for step in counted:
            tools = session["tools"] if step["with_tools"] else []
            again = await model.count_context(step["request"], tools)
            if again != step["context_tokens"]:
                differ.append(
                    f"turn {step['turn']} step {step['step']}: recorded"
                    f" {step['context_tokens']}, counted again {again}"
                )
    except ModelError as exc:
        return f"faithful: not checked. {exc}"
    finally:
        await model.client.close()
    if differ:
        return "faithful: NO. " + "; ".join(differ)
    return f"faithful: yes. {len(counted)} of {len(counted)} recorded requests have the token count that the server gave in the chat."


def main() -> None:
    verb = sys.argv[1] if len(sys.argv) > 1 else "check"
    records = sorted(RECORDS.glob("*.jsonl"))
    if len(sys.argv) > 2:
        path = Path(sys.argv[2])
    elif records:
        path = records[-1]
    else:
        raise SystemExit(f"No record in {RECORDS}/. Run make chat first.")
    if verb not in ("show", "check"):
        raise SystemExit(__doc__)
    session, steps = load(path)
    print(f"record: {path}")
    if verb == "show":
        show(steps)
        return
    found = findings(session, steps)
    print("\n".join(found) if found else "No step where two layers disagree.")
    print(asyncio.run(faithful(session, steps)))


if __name__ == "__main__":
    main()
