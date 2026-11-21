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
in memory. That, and one more design choice below, give the three rules
behind every number on this page:

- **Memory follows what the model stores.**
- **Speed follows what each token reads.**
- **Sharing shrinks what is stored, not what is read.**

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
nothing else. You lose image and audio input. The speed barely moves.

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
starts at about 20 MiB: five times less than the calculator. The architecture
predicts both numbers:

- **35 of the 42 layers see only the last 512 tokens.** Their cache stops
  growing at 512 tokens. That is the fixed 20 MiB.
- **The last 18 layers borrow the cache of an earlier layer.** So only 4
  layers keep a cache that grows. Each stores a key and a value for 2 heads of
  512 numbers, at 2 bytes: 4 × 2 × 2 × 512 × 2 = 16 KiB per token.

**Should you compress the cache?** `--kv-cache-dtype int8` stores the growing
cache in 8 bits instead of 16, so it halves it. But every decode step must
unpack it again, so you pay in speed. That trade pays when the cache is big:
a model that stores 128 KiB per token holds 3.4 GiB at 28K tokens, and int8
gives back about 1.7. Here the cache is only about 0.5 GB. On the text
lane at 28K tokens, int8 lowered the peak by 0.11 GB and made decode 5% slower.

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
three runs. It lands within 2% of each one. Read its slope as 28 KiB of cache
for each token of context, which is what the 7 global layers read. Then the
line says that our Mac delivers about 108 GB/s, and that each token reads a
fixed 2.4 GB. So at a short prompt: 108 ÷ 2.5 ≈ 43 tokens per second. We
measured 44.

**Why 2.4 GB, not 4.2?** The PLE table. It is 1.59 GB of memory, but each
token reads one row of it: 10,752 numbers at 4.5 bits, about 6 KB. It costs
memory and almost no bandwidth. What each token does read is the 4B core
(2.24 GB) and the output layer, which reuses the token embedding table
(0.38 GB): 2.6 GB on paper, close to the 2.4 the line gives.

**Why 28 KiB, not 16?** The 3 global layers that borrow a cache still read
it, at every token. Sharing saved the memory of 3 caches, but none of their
reads.

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
  lengths and fit a line through seconds per token. It gives your Mac's
  bandwidth and its cost per token of context.
- **Compress the cache only when it is big.** Here int8 KV saved 0.11 GB and
  cost 5% of decode speed.

One Mac, one checkpoint, one run for each number. The shapes hold for the
architecture. The exact values are ours, not yours.
