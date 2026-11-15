# Deep-dish: the fallback, four fixes and four new behaviours

Chapter 1's host has two small rules about a model that says nothing. It keeps
its own words out of the history, and it asks a silent model again with a
message that has no words. Two lines in a table. They took four rounds to find,
and each fix made the model do something new.

| Round | What the host did | What the model did next |
|---|---|---|
| 1 | wrote a fallback into the history | the echo |
| 2 | asked again: “Reply to the customer…” | the false claim |
| 3 | asked again: “Continue: call the next tool, or reply…” | the unapproved order |
| 4 | hid `confirm_order` during the re-ask | the broken cache |
| Out | asked again with no words at all | nothing new |

## The silence

A small local model sometimes answers a tool result with nothing: no text, no
tool call, no error. To see why, render the prompt with the model's own chat
template. This is the end of a real request, right after the order was
confirmed:

```text
<|turn>user
yes<turn|>
<|turn>model
<|tool_call>call:confirm_order{}<tool_call|><|tool_response>response:confirm_order{…}<tool_response|>
```

There is no new `<|turn>model` after the tool result. The template does this on
purpose: the model is still inside its own turn. Its next token can be more
text, another tool call, or end-of-turn. At some moments it picks end-of-turn,
and that one token is the whole reply.

The original host answered for it: “The model returned no answer. Completed
actions: … review the cart or orders before continuing.” It showed the
customer that text, and it saved it in the history as the assistant's message.

## Round 1: the echo

A history is not a log for the model. It is a set of examples. After two or
three fallbacks, the model learned what comes after a tool result, and wrote
the fallback itself.

We replayed 8 recorded silent moments 10 times each, with the app's settings:

| | Silent | Copied the fallback (1 moment × 10) |
|---|---|---|
| Nemotron 3.5 Bolt E4B (built on Gemma 4) | 78 of 80 | 10 of 10 |
| Gemma 4 E4B | 17 of 80 | 0 of 10 |
| either model, with a user message at the end | 0 of 80 | 0 of 10 |

Remove the old fallbacks from that history and the copies drop to 0. The
silence does not: 10 of 10. So there were two bugs. The fix in
[#6](https://github.com/adityakunar/agent-observability-101/pull/6) handles
both: the fallback goes to the customer only, and a silent model gets one
re-ask with “Reply to the customer about the result above.” on a copy of the
history.

A hosted model with native tool calling went silent 0 times in 310 of the same
requests. Its API always starts a new turn after a tool result.

## Round 2: the false claim

We ran 30 new chats with the fix. No fallbacks at all, and 12 re-asks. Eleven
gave a correct answer. One did not:

> **Customer:** normal garlic bread, normal cokes. just add them
>
> *(the model reads the sides menu, then the drinks menu, and goes silent)*
>
> **Assistant, after the re-ask:** I have added one Garlic Bread for 3.99 EUR
> and two Cokes for 1.99 EUR each to your cart.

Nothing was added. The order went out with the pizza alone. The model had
stopped in the middle of the task, after two reads, and the host told it to
*reply*. So it reported the work it had not done yet. Replayed, that moment
gave the same false claim 10 times out of 10.

A small model follows the host's words literally. “Reply” means “report”.

## Round 3: the unapproved order

So we tried a cue that allows more: “Continue: call the next tool, or reply to
the customer about the result above.” On 20 recorded silent moments it fixed
the read: 10 of 10 resumed the adds that the customer asked for.

It also found a new way to fail. Right after a delivery address was saved, it
called `confirm_order` 10 times out of 10. The customer had said “confirm it”
two turns earlier, but had never seen the delivery fee. The host's word
“continue” stood in for the customer's yes.

[#11](https://github.com/adityakunar/agent-observability-101/pull/11) chose the
cue by the last tool, which the host already knows from `readOnlyHint`:
“reply” after an action, “continue” after a read. And the re-ask request was
sent without `confirm_order` in its tool list, so a re-ask could never place an
order.

## Round 4: the broken cache

That guard had a cost that no answer showed. The tool list sits near the top
of the prompt. Change it and the prompt differs from almost the first token, so
the model server cannot reuse what it had cached and reads the whole
conversation again.

| Re-ask request | Prompt cached (median) | No cache hit | Time (median) |
|---|---|---|---|
| tool list without `confirm_order` | 50% | 20 of 40 | 1.01 s |
| full tool list | 99% | 0 of 200 | 0.68 s |

So #11 kept the full list and had the host refuse `confirm_order` in the re-ask
step instead. Same answers, cache kept.

## The way out: say nothing

Three rounds of fixes were three rounds of choosing words. The words were the
cause. The model never needed an instruction. It needed a new turn.

[#13](https://github.com/adityakunar/agent-observability-101/pull/13) re-asks
with a user message that has no content. The template closes the model's turn
and opens a fresh one, and there is nothing in it to obey, to report, or to
mistake for consent.

| Re-ask, same 20 moments × 10 | After an action | After a read | Order attempts | False claims | Silent | Cached |
|---|---|---|---|---|---|---|
| a cue in words, chosen by the last tool | 160 of 160 | 40 of 40 | 0 | 0 | 0 | 99% |
| an empty user message | 160 of 160 | 40 of 40 | 0 | 0 | 0 | 99% |

Same result, no words to choose, and the re-ask adds 8 tokens to the request.
The two cues and the code that picked between them went away.

With no words in the cue, the order guard from round 4 had no reason left, so
[#14](https://github.com/adityakunar/agent-observability-101/pull/14) removed
it. Real approval belongs on the server, and Chapter 1 lists it under
[What is still broken](../article.md#what-is-still-broken).

## Take these home

- **The history is a set of examples.** Anything your host writes there comes
  back as the model's own words. Show host messages to the user, not to the
  model.
- **A silent model needs a turn, not a sentence.** If your template leaves the
  model inside its turn after a tool result, open a new one.
- **Every word your host sends is an instruction.** A small model will follow
  it, including the parts you did not mean.
- **The tool list is part of your cache key.** Gate a tool in code, not by
  taking it out of the request.
- **Replay before you trust a fix.** Save the request, send it 10 times, change
  one thing. One live chat showed the false claim. The replay turned it into
  10 out of 10, and into a test for every cue that followed.

Round 1 used two small local models; the later rounds used Gemma 4 E4B only.
Each cell is 10 replays at temperature 0.2, and only one of the 20 moments is
in the middle of a task. They show the
mechanism. They are not a rate for your model.
