# Deep-dish: why a "4B" model needs 5 GB

You want an agent that runs on your own laptop, so you pick a small model.
Gemma 4 E4B: 4B parameters, 4-bit weights. Four billion half-bytes is 2 GB,
so it should fit next to your editor and your browser with room to spare.

That is what we expected when we built the pizza-ordering agent in
[Chapter 1](../article.md). The model server held 5.15 GB before it read a
single word. And the longer the prompt got, the slower each reply came out.

Two surprises, and both matter for an agent. Memory decides whether the model
fits beside everything else you run. Speed decides how long your customer
waits, and an agent's prompt only grows: every turn sends the whole chat, the
tool definitions and the tool results again.

So we asked two questions. Where do the 5 GB go? And what sets the speed? This
page gives you:

- why the name gives the wrong size, and where to read the right one;
- one flag that gave back 0.95 GB, and a default that makes later turns about
  16 times faster;
- a way to predict decode speed from three timed prompts;
- where the extra memory of a long prompt goes, and how much of it you can save.

**The setup.** One Mac: an M5 Pro with 24 GB, rapid-mlx 1.0.1, MLX 0.32.4.
The checkpoint is `mlx-community/gemma-4-e4b-it-4bit`. Each test sends a
prompt of 10 to 28K tokens at temperature 0. Memory is `metal` from
`GET /v1/status`, the same source as the MLX peak in Chapter 1's
[Measure](../article.md#3-measure-one-line-for-each-model-request) line.
One run for each number.

**Five words you will meet.**

- **Prefill**: the model reads your whole prompt, in chunks. It sets the time
  to the first token.
- **Decode**: the model writes its reply, one token at a time.
- **KV cache**: what the model keeps for each token it has read, so it never
  reads the prompt twice. It grows with the context.
- **Prefix cache**: the server keeps the KV cache of earlier requests. When a
  new prompt starts the same way, it skips that part of the prefill. Most of
  our tests turn it off, so that every prompt is read in full and we time the
  model, not the cache.
- **4-bit**: really 4.5 bits per weight, because each group of 64 weights
  also keeps a 16-bit scale and a 16-bit offset. Use 4.5 in every estimate.

## Where the 7.5B comes from

Each token ID picks one row from the token embedding table. It also picks one
row from a second, much larger table: the per-layer embedding (PLE) table,
which gives each of the 42 layers a small extra input. The header of the
checkpoint file lists every tensor and its size:

| Part | Parameters | Bytes at 4.5 bits |
|---|---|---|
| Per-layer embedding table | 2.82 B | 1.59 GB |
| Token embedding | 0.67 B | 0.38 GB |
| Attention, MLP and the rest | 3.97 B | 2.24 GB |
| **Text model** | **7.46 B** | **4.20 GB** |

The "E" is for *effective*. Each token runs through the 4B core and takes one
row from each table. But the next token can need any row, so every row stays
in memory. That, and one more design choice below, give the three rules
behind every number on this page:

- **Memory follows what the model stores.**
- **Speed follows what each token reads.**
- **Sharing shrinks what is stored, not what is read.**

## Memory: the lane, then the cache

**The lane.** At rest, the server held 5.15 GB, not 4.20. The checkpoint also
carries a vision tower and an audio tower, 0.95 GB of 16-bit weights.
rapid-mlx can serve a model on a text-only lane or on a multimodal lane that
also takes images and audio. When `mlx-vlm` is installed, as it was for us, it
picks the multimodal lane and loads the towers. The server log says
which: `mllm=True`. The pizza agent only reads and writes text, so we turned
the towers off:

```bash
make model MLX_ARGS="--text-only"
```

| Lane | Held at rest | Peak at 28K tokens |
|---|---|---|
| multimodal (what we got) | 5.15 GB | 7.23 GB |
| `--text-only` | 4.20 GB | 6.28 GB |

That is 0.95 GB back. What is left, 4.20 GB, is the text weights and almost
nothing else. You lose image and audio input. The speed barely moves: at 28K
tokens, decode ran at 33.0 against 34.1 tokens per second, and the first token
came at 14.6 against 13.8 s, one run each.

**The cache.** A general KV calculator counts every layer the same way and
gives 84 KiB per token for this model. To see the real size, we read MLX's
pool of freed buffers. When a request ends, its KV cache is no longer needed,
but MLX does not hand that memory back to macOS. It keeps it in a pool for the
next request, and `/v1/status` reports the pool as `cache_memory`. Right after
a request, the pool is about the size of that request's KV cache. (On the
text lane the pool always read 0, so this works on the multimodal lane only.)

| Prompt tokens | 3,520 | 14,020 | 28,020 |
|---|---|---|---|
| Freed buffers | 0.08 GB | 0.26 GB | 0.49 GB |

Draw a line through those three points. It climbs 16.3 KiB for each token and
starts at about 20 MiB: five times less than the calculator. Two design
choices predict both numbers:

- **The last 18 layers borrow the cache of an earlier layer.** So only 24 of
  the 42 layers keep a cache at all.
- **Of those 24, 20 see only the last 512 tokens.** Their cache stops growing
  there: 20 layers × 2 heads × 256 numbers × 2 (key and value) × 2 bytes ×
  512 tokens = 20 MiB. The other 4 see everything and grow by 4 × 2 × 512 × 2
  × 2 bytes = 16 KiB per token.

**Should you compress the cache?** `--kv-cache-dtype int8` stores the growing
cache in 8 bits instead of 16, so it halves it. But every decode step must
unpack it again, so you pay in speed. That trade pays when the cache is big.
Here it is about 0.5 GB at 28K tokens. On the text lane, int8 lowered the peak
by only 0.11 GB, half of what halving the cache predicts, and decode was 5%
slower in one run, which is within our run-to-run noise. Not worth it here.

## Speed: decode reads, it does not compute

Decode is limited by memory bandwidth. Each new token streams every weight it
uses from memory, once, and the GPU waits for the bytes:

> tokens per second ≈ memory bandwidth ÷ bytes read per token

For most models, the bytes read per token are about the model's size in
memory, plus the KV cache. For E4B that guess is wrong, and the decode speeds
show by how much:

| Prompt tokens | 3,520 | 14,020 | 28,020 |
|---|---|---|---|
| Decode | 44.0 tok/s | 38.0 tok/s | 34.1 tok/s |

Turn the speeds into seconds per token and fit a straight line through the
three runs. It lands within 2% of each one. Now assume the slope is 28 KiB of
cache for each token of context, which is what the 7 global layers read. Then
the line says that our Mac's effective bandwidth is about 108 GB/s, and that
each token reads a fixed 2.4 GB. At 3.5K tokens, the cache adds 0.1 GB: 108 ÷
2.5 ≈ 43 tokens per second. We measured 44.

**Why 2.4 GB, not 4.2?** The PLE table. It is 1.59 GB of memory, but each
token reads one row of it: 10,752 numbers at 4.5 bits, about 6 KB. It costs
memory and almost no bandwidth. What each token does read is the 4B core
(2.24 GB) and the output layer, which reuses the token embedding table
(0.38 GB): 2.6 GB on paper, close to the 2.4 the line gives.

**Why 28 KiB, not 16?** The 3 global layers that borrow a cache still read
it, at every token. Sharing saved the memory of 3 caches, but none of their
reads.

## Prefill: where the extra memory goes

Reading a long prompt needs more memory than the KV cache it leaves behind.
On the text lane at 28K tokens, the peak rose 2.08 GB above the memory at
rest, and the KV cache is about 0.48 GB of that. The rest is working memory
for the prompt chunks. rapid-mlx uses chunks of 2,048 tokens unless you set
`--prefill-step-size`. We tried four sizes on the text lane, with the prefix
cache off:

| Chunk size | Peak above rest, 28K | of which KV cache (predicted) | First token, 28K |
|---|---|---|---|
| 256 | 1.09 GB | 0.48 GB | 16.2 s |
| 512 | 1.52 GB | 0.48 GB | 14.3 s |
| 2,048 (default) | 2.08 GB | 0.48 GB | 14.5 s |
| 8,192 | 3.04 GB | 0.48 GB | 16.9 s |

The working memory has two parts:

- **A part that grows with chunk × prompt length.** A global layer scores
  every token of the chunk against every token before it: 8 heads × chunk ×
  context × 2 bytes, one layer at a time. With chunks of 2,048, going from 7K
  to 28K tokens should add 0.69 GB. The working memory grew by 0.66 GB. At
  8,192 the formula asks for more than the whole working memory, so MLX's
  attention kernel likely does not keep all the scores at once there.
- **About 0.6 GB that does not move.** With chunks of 256, the working memory
  was 0.58 to 0.61 GB at 7K, 14K and 28K. We have not found what holds it.

So 512 is the sweet spot here: 0.56 GB less than the default, for about the
same first-token time (0.3 s sooner here, 0.7 s later in an earlier run on
the multimodal lane). Smaller chunks start to cost time, and bigger ones cost both
memory and time.

## Prefix cache: the agent's best friend

An agent sends the whole chat again on every turn, so turn 2 starts with all
of turn 1. The tests above turned the prefix cache off so that each one timed
a full prefill. Here we turned it back on (the default) for a 4-turn chat that
starts with a 7K-token message:

| Turn | First token, cache off | First token, cache on | Prompt tokens reused |
|---|---|---|---|
| 1 | 3.1 s | 3.3 s | 4 of 7,017 |
| 2 | 3.1 s | 0.18 s | 7,025 of 7,222 |
| 3 | 3.5 s | 0.22 s | 7,233 of 7,430 |
| 4 | 3.5 s | 0.21 s | 7,441 of 7,638 |

From turn 2, the server reads only the ~200 new tokens. The cost is memory:
the server held 0.3 GB more after each turn, because it keeps two saved
copies of the KV cache per request, about 150 MB each at 7K tokens. It caps
them at 4 GB here. It also writes them to disk when it stops, 1.1 GB after
this chat, and loads them at the next start. `--disable-disk-caches` turns
that off.

## Take these home

- **Read the size from the file, not from the name.** Parameters × bits misses
  tables that the name leaves out. The checkpoint header or the server's
  memory at rest gives the real number. And "4-bit" is 4.5 bits.
- **Check which lane your server picked.** Here one flag gave back 0.95 GB.
- **Count the KV cache by layer type.** Sliding windows and shared layers made
  a general calculator five times too high.
- **Estimate decode from bytes read, not bytes stored.** Time three prompt
  lengths and fit a line through seconds per token. It gives your Mac's
  bandwidth and its cost per token of context.
- **Compress the cache only when it is big.** Here int8 KV saved 0.11 GB and
  cost 5% of decode speed.
- **Try a smaller prefill chunk.** 512 saved 0.56 GB on this model, at about
  the same speed.
- **Keep the prefix cache on for an agent.** It holds memory, and it keeps
  the chat's cache on disk unless you add `--disable-disk-caches`.

One Mac, one checkpoint, one run for each number. The shapes hold for the
architecture. The exact values are ours, not yours.
