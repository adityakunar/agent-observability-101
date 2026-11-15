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
- one flag that gave back 0.95 GB;
- a way to predict decode speed from three timed prompts;
- one setting that helped and that we cannot fully explain.

**The setup.** One Mac: an M5 Pro with 24 GB, rapid-mlx 1.0.1, MLX 0.32.4.
The checkpoint is `mlx-community/gemma-4-e4b-it-4bit`. Each test sends a
prompt of 10 to 28K tokens, at temperature 0, with the prefix cache off so
the server reads every prompt from the start. Memory is `metal` from
`GET /v1/status`, the same source as the MLX peak in Chapter 1's
[Measure](../article.md#3-measure-one-line-for-each-model-request) line.
One run for each number.

**Four words you will meet.**

- **Prefill**: the model reads your whole prompt, in chunks. It sets the time
  to the first token.
- **Decode**: the model writes its reply, one token at a time.
- **KV cache**: what the model keeps for each token it has read, so it never
  reads the prompt twice. It grows with the context.
- **4-bit**: MLX stores weights in groups of 64, and each group keeps a 16-bit
  scale and a 16-bit offset. So "4-bit" is really 4 + 32 / 64 = 4.5 bits per
  weight. Use 4.5 in every estimate.

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
in memory. That gives the two rules behind every number below:

- **Memory follows what the model stores.**
- **Speed follows what each token reads.**

## Memory: the lane, then the cache

**The lane.** At rest, the server held 5.15 GB, not 4.20. The checkpoint also
carries a vision tower and an audio tower, 0.95 GB of 16-bit weights.
rapid-mlx has two code paths, or lanes. When `mlx-vlm` is installed, as it was
for us, it picks the multimodal lane and loads the towers. The server log says
which: `mllm=True`. The pizza agent only reads and writes text, so we turned
the towers off:

```bash
make model MLX_ARGS="--text-only"
```

| Lane | Held at rest | Peak at 28K tokens | First token at 28K | Decode at 28K |
|---|---|---|---|---|
| multimodal (what we got) | 5.15 GB | 7.23 GB | 13.8 s | 34.1 tok/s |
| `--text-only` | 4.20 GB | 6.28 GB | 14.6 s | 33.0 tok/s |

That is 0.95 GB back. What is left, 4.20 GB, is the text weights and almost
nothing else. You lose image and audio input. The speed barely moves; the
lanes cut prompts into different chunks, and one run each is too little to
read more into it.

**The cache.** A general KV calculator counts every layer the same way and
gives 84 KiB per token for this model. After each request on the multimodal
lane, MLX kept the freed buffers in its pool (`cache_memory`):

| Prompt tokens | 3,520 | 14,020 | 28,020 |
|---|---|---|---|
| Freed buffers | 0.08 GB | 0.26 GB | 0.49 GB |

That is a line of 16.3 KiB per token plus 20 MiB: five times less. Two design
choices cut it down. 35 of the 42 layers see only the last 512 tokens, so
their cache stops at 20 MiB. And the last 18 layers borrow the cache of an
earlier layer instead of keeping their own. Only 4 layers keep a cache that
grows, and on paper they need 16 KiB per token.

A small cache leaves little to compress. On the text lane at 28K tokens,
`--kv-cache-dtype int8` lowered the peak by 0.11 GB and made decode 5% slower.

## Speed: decode reads, it does not compute

Decode is limited by memory bandwidth. Each new token streams every weight it
uses from memory, once, and the GPU waits for the bytes. So the speed is set
by the bytes each token reads.

| Prompt tokens | 3,520 | 14,020 | 28,020 |
|---|---|---|---|
| Decode | 44.0 tok/s | 38.0 tok/s | 34.1 tok/s |

Turn the speeds into seconds per token and fit a straight line through the
three runs. It lands within 2% of each one. Read its slope as 28 KiB of cache
for each token of context, which is what the 7 global layers read, and the
fixed part comes out at about 2.4 GB for every token.

- **2.4 GB, not 4.2.** On paper, each token reads the 4B core (2.24 GB) and the
  output layer, which reuses the token embedding table (0.38 GB): 2.6 GB. The
  PLE table is 1.59 GB of memory, and each token reads one row of it. It costs
  memory and almost no bandwidth.
- **28 KiB, not 16.** The 7 global layers all read the cache, even the 3 that
  borrow it. Sharing shrinks what is stored, not what is read.

The same rule, twice.

## Prefill step size: a trade we only half understand

The multimodal lane logged prefill chunks of 8,192 tokens. With
`--prefill-step-size 512`, the peak fell by 0.42 GB at 14K tokens and 0.57 GB
at 28K, and the first token came 5% to 6% later. A fair trade when memory is
tight.

The honest part: even with 512, the peak at 28K was 1.51 GB above rest. The
KV cache accounts for about 0.49 GB of that. We cannot yet say where the other
1 GB goes.

## Take these home

- **Read the size from the file, not from the name.** Parameters × bits misses
  tables that the name leaves out. The checkpoint header or the server's
  memory at rest gives the real number. And "4-bit" is 4.5 bits.
- **Check which lane your server picked.** Here one flag gave back 0.95 GB.
- **Count the KV cache by layer type.** Sliding windows and shared layers made
  a general calculator five times too high.
- **Estimate decode from bytes read, not bytes stored.** Time three prompt
  lengths and fit a line through seconds per token. It gives your Mac's fixed
  cost and its cost per token of context.
- **Measure before you compress the cache.** On a model with a small cache,
  int8 KV saved 0.11 GB and cost 5% of decode speed.

One Mac, one checkpoint, one run for each number. The shapes hold for the
architecture. The exact values are ours, not yours.
