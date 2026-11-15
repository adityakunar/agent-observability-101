# Deep-dish: Gemma 4 E4B, the 4B model that weighs 7.5B

Chapter 1 serves Gemma 4 E4B at 4 bits. A rule of thumb says that a 4B model
at 4 bits needs 2 GB. Our model server held 5.15 GB before the first prompt.
Nothing leaked. The name counts what each token computes. The memory counts
what the model keeps.

## Where the 7.5B comes from

Each token ID picks one row from the token embedding table. It also picks one
row from a second, much larger table: the per-layer embedding (PLE) table,
which gives each of the 42 layers a small extra input. The safetensors header
of the checkpoint shows the split:

| Part | Parameters | Bytes at 4 bits |
|---|---|---|
| Per-layer embedding table | 2.82 B | 1.59 GB |
| Token embedding | 0.67 B | 0.38 GB |
| Attention, MLP and the rest | 3.97 B | 2.24 GB |
| **Text model** | **7.46 B** | **4.20 GB** |

The "E" is for *effective*. Each token runs through the 4B core and takes one
row from each table. But the next token can need any row, so every row stays
in memory. Google designed the PLE table so that a phone can keep it in flash.
On a Mac it sits in unified memory with everything else.

So two rules, and the rest of this page is their evidence:

- **Memory follows what the model stores.**
- **Speed follows what each token reads.**

We measured on one Mac: an M5 Pro with 24 GB, rapid-mlx 1.0.1, MLX 0.32.4,
temperature 0, prefix cache off, one run for each row. Memory is `metal` from
`GET /v1/status`, the same source as the MLX peak in Chapter 1's
[Measure](../article.md#3-measure-one-line-for-each-model-request) line.

## Memory: the lane, then the cache

**The lane.** At rest, the server held 5.15 GB, not 4.20. The checkpoint also
carries a vision tower and an audio tower, 0.95 GB in bf16. rapid-mlx serves
this model on its multimodal lane when `mlx-vlm` is installed, and our install
had it. The pizza agent only reads and writes text, so we turned the towers off:

```bash
make model MLX_ARGS="--text-only"
```

| Lane | Held at rest | Peak at 28K tokens | First token at 28K | Decode at 28K |
|---|---|---|---|---|
| multimodal (what we got) | 5.15 GB | 7.23 GB | 13.8 s | 34.1 tok/s |
| `--text-only` | 4.20 GB | 6.28 GB | 14.6 s | 33.0 tok/s |

That is 0.95 GB back. What is left, 4.20 GB, is the text weights and almost
nothing else.
You lose image and audio input. The speed barely moves; the lanes cut prompts
into different chunks, and one run each is too little to read more into it.

**The cache.** A general KV calculator multiplies
2 (K and V) × 42 layers × 2 KV heads × 256 values × 2 bytes = 84 KiB per token.
After three prompts, the server had freed this much KV:

| Prompt tokens | 3,520 | 14,020 | 28,020 |
|---|---|---|---|
| Freed KV cache | 0.08 GB | 0.26 GB | 0.49 GB |

That is a line of 16.3 KiB per token plus 20 MiB: five times less. Two design
choices cut it down. 35 of the 42 layers see only the last 512 tokens, so
their cache stops at 20 MiB. And the last 18 layers borrow the cache of an
earlier layer instead of keeping their own. Only 4 layers keep a cache that
grows: 4 × 2 heads × 512 values × 2 (K and V) × 2 bytes = 16 KiB per token.

A small cache leaves little to compress. `--kv-cache-dtype int8` saved 0.11 GB
of peak at 28K tokens and made decode 5% slower. The multimodal lane refuses
the flag.

## Speed: decode reads, it does not compute

Decode is limited by memory bandwidth. Each new token streams every weight it
uses from memory, once, and the GPU waits for the bytes. So the speed is set
by the bytes each token reads.

| Prompt tokens | 3,520 | 14,020 | 28,020 |
|---|---|---|---|
| Decode | 44.0 tok/s | 38.0 tok/s | 34.1 tok/s |

A bandwidth model fits these: each token reads about 2.3 GB of weights, plus
28 KiB for each token of context. Calibrated on the first run, it predicts the
other two within 3%. Two numbers in it are worth a look:

- **2.3 GB, not 4.2.** The PLE table is 1.59 GB of memory, and each token
  reads one row of it. It costs memory and almost no bandwidth.
- **28 KiB, not 16.** The 7 global layers all read the cache, even the 3 that
  borrow it. Sharing shrinks what is stored, not what is read.

The same rule, twice.

## The fine print on "4-bit"

MLX stores 4-bit weights in groups of 64. Each group keeps a bf16 scale and a
bf16 offset: 4 + 32 / 64 = **4.5 bits** per weight. Use 4.5 in every estimate.
The PLE table is 2,818,572,288 weights × 4.5 / 8 = 1,585,446,912 bytes, the
exact size in the file.

## Prefill step size: a trade we only half understand

rapid-mlx reads a prompt in chunks. The multimodal lane logged chunks of 8,192
tokens. With `--prefill-step-size 512`, the peak fell by 0.42 GB at 14K tokens
and 0.57 GB at 28K, and the first token came 5% to 6% later. A fair trade when
memory is tight.

The honest part: even with 512, the peak at 28K was 1.51 GB above rest. The
KV cache explains 0.49 GB of it. We cannot yet say where the other 1 GB goes.

## Take these home

- **Read the size from the file, not from the name.** Parameters × bits misses
  tables that the name leaves out. The safetensors header or the server's
  memory at rest gives the real number.
- **"4-bit" is 4.5 bits.** The scales and offsets add 12.5%.
- **Check which lane your server picked.** Here one flag gave back 0.95 GB.
- **Count the KV cache by layer type.** Sliding windows and shared layers made
  a general calculator five times too high.
- **Estimate decode from bytes read, not bytes stored.** Time three prompt
  lengths and fit a line: it gives your Mac's fixed cost and its cost per
  token of context.
- **Measure before you compress the cache.** On a model with a small cache,
  int8 KV saved 0.11 GB and cost 5% of decode speed.

One Mac, one checkpoint (`mlx-community/gemma-4-e4b-it-4bit`), one run for
each number. The shapes hold for the architecture. The exact values are ours,
not yours.
