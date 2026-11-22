"""Time a local model the way the E4B deep-dish does, against a server you already started.

Start the server with the setting you want to test, then run this script:

    make model MLX_ARGS="--text-only --disable-prefix-cache"
    uv run python deep-dish/gemma-4-e4b/measure.py           # prompts of about 7K, 14K and 28K tokens
    uv run python deep-dish/gemma-4-e4b/measure.py --turns 4 # one chat: is turn 2 served from the prefix cache?

For --turns with the prefix cache on, drop --disable-prefix-cache and add
--disable-disk-caches, so the server does not save the chat to disk when it stops.

Each run prints one line: prompt tokens, time to first token, decode speed and the
server's memory from /v1/status. Restart the server between settings, and run each
setting three times: a difference smaller than the spread between runs is not real.
Only the standard library is used.
"""

import argparse
import json
import time
import urllib.request

# A filler paragraph: the text does not matter, only the prompt length.
PARAGRAPH = (
    "The pizzeria opens at five. Orders arrive by phone and by chat. The oven holds twelve "
    "pizzas, and each pizza bakes for ninety seconds. Drivers leave every ten minutes. "
)
TOKENS_PER_PARAGRAPH = 35  # for Gemma; the server reports the true count


def ask(base: str, model: str, messages: list, max_tokens: int) -> tuple[str, dict]:
    """Send one streamed request; return the reply and its timings."""
    body = json.dumps(
        {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
    ).encode()
    request = urllib.request.Request(
        f"{base}/v1/chat/completions", body, {"Content-Type": "application/json"}
    )
    start = time.time()
    first = None
    usage = {}
    text = []
    with urllib.request.urlopen(request, timeout=900) as response:
        for line in response:
            line = line.decode().strip()
            if not line.startswith("data:") or line.endswith("[DONE]"):
                continue
            chunk = json.loads(line[5:])
            usage = chunk.get("usage") or usage
            for choice in chunk.get("choices", []):
                if piece := (choice.get("delta") or {}).get("content"):
                    first = first or time.time()
                    text.append(piece)
    end = time.time()
    out = usage.get("completion_tokens", len(text))
    return "".join(text), {
        "prompt_tokens": usage.get("prompt_tokens"),
        "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
        "ttft_s": round(first - start, 2) if first else None,
        # Decode speed counts the tokens after the first, so prefill time stays out of it.
        "decode_tok_s": round((out - 1) / (end - first), 1) if first and out > 1 else None,
    }


def memory(base: str) -> dict:
    """The server's own memory numbers: peak, in use, and freed buffers kept for reuse."""
    with urllib.request.urlopen(f"{base}/v1/status", timeout=10) as response:
        return json.load(response).get("metal") or {}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=9000, help="the port of `make model`")
    parser.add_argument("--model", default="gemma-4-e4b-4bit", help="the name the server serves")
    parser.add_argument(
        "--tokens",
        type=int,
        nargs="+",
        default=[7000, 14000, 28000],
        help="approximate prompt lengths to time",
    )
    parser.add_argument(
        "--turns",
        type=int,
        default=0,
        help="instead, run one chat of this many turns on a 7K-token start",
    )
    parser.add_argument("--max-tokens", type=int, default=64, help="reply length per request")
    args = parser.parse_args()
    base = f"http://localhost:{args.port}"

    def report(label: str, timings: dict) -> None:
        print(json.dumps({"run": label, **timings, "metal": memory(base)}))

    report("rest", ask(base, args.model, [{"role": "user", "content": "Hi"}], 1)[1])
    if args.turns:
        # The real replies go back into the history, so each turn starts with the one before.
        messages = [
            {
                "role": "user",
                "content": PARAGRAPH * (7000 // TOKENS_PER_PARAGRAPH)
                + "\nWhen does the pizzeria open?",
            }
        ]
        for turn in range(1, args.turns + 1):
            reply, timings = ask(base, args.model, messages, args.max_tokens)
            report(f"turn {turn}", timings)
            messages += [
                {"role": "assistant", "content": reply},
                {"role": "user", "content": PARAGRAPH * 5 + "\nHow long does a pizza bake?"},
            ]
    else:
        for n in args.tokens:
            prompt = (
                PARAGRAPH * (n // TOKENS_PER_PARAGRAPH)
                + "\nSummarise the text above in one sentence."
            )
            report(
                f"{n} tokens",
                ask(base, args.model, [{"role": "user", "content": prompt}], args.max_tokens)[1],
            )


if __name__ == "__main__":
    main()
