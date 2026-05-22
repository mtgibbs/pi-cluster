# Dewey Model Evaluation — May 2026

Local-model recommendations for **Dewey**, the kids' (ages 11 + 14) study assistant
that answers questions via a **deterministic RAG flow** over an offline kiwix
encyclopedia (Wikipedia / Gutenberg). Two model roles: a tiny **keyword/query-rewrite**
model and a quality-critical **answer/summarizer** model. No tool-calling required.

**Box / serving (hard constraints):** AMD Strix Halo (Ryzen AI Max+ 395, Radeon 8060S
iGPU / gfx1151, RDNA 3.5), 128 GB unified LPDDR5X, ~96 GB carved as VRAM,
**~215 GB/s measured memory bandwidth**. Serving via **Ollama (Vulkan/RADV)** or
**llama.cpp `server-vulkan`**. ROCm OOMs on gfx1151 — not used. Inference is
**memory-bandwidth-bound**, so speed scales with *active* params: low-active MoE wins.

**Behavioral constraint that drives the whole selection:** hidden-reasoning ("thinking")
models are a trap here. `/no_think` and API thinking toggles do **not** survive our
Ollama + LiteLLM path (`drop_params:true` strips them; the Ollama OpenAI
`/v1/chat/completions` endpoint does not honor `think:false`). Hybrid-thinking models
also leak reasoning even with the toggle off. So we **require genuinely non-thinking
(dedicated Instruct) checkpoints** — not "hybrid models with thinking switched off."

---

## TL;DR

- **Answer model → `Qwen3-Next-80B-A3B-Instruct` (llama.cpp-vulkan, UD-Q4_K_XL ≈ 46 GB).**
  80B total / **~3B active** high-sparsity MoE, **dedicated non-thinking Instruct**
  (never emits `<think>`), Apache-2.0, ~**59 tok/s measured on this exact box**, and
  benchmarks on par with Qwen3-235B-A22B-Instruct-2507. This is a real quality jump over
  `gemma3:27b` while being ~2x faster. Needs llama.cpp (hybrid Gated-DeltaNet arch);
  Ollama support is still maturing.
- **Keyword model → `Qwen3-4B-Instruct-2507` (Q4_K_M ≈ 2.5 GB, or Q8_0 ≈ 4.3 GB).**
  Dedicated non-thinking Instruct checkpoint (no think tags, ever), markedly better
  terse-instruction-following than `gemma3:4b`, trivially fast, Apache-2.0, loads fine in
  Ollama 0.17.x. Use Q8_0 — the model is tiny so the quality gain is nearly free.

**Safer single-model fallback for the answer role if you want to stay on Ollama today:**
`Qwen3-30B-A3B-Instruct-2507` (UD-Q4_K_XL ≈ 17.7 GB, ~3.3B active, non-thinking,
~62–96 tok/s). Lower ceiling than Qwen3-Next but a clean Ollama load and already a
known-good family on this box.

---

## Answer model — ranked shortlist

Quality-first, must run fast (so MoE, low active params), must be non-thinking.

| Rank | Model | Total / Active | Arch | Thinking? | Quant / VRAM | Est. tok/s on this box | Serving | License |
|---|---|---|---|---|---|---|---|---|
| **1** | **Qwen3-Next-80B-A3B-Instruct** | 80B / **~3B** | MoE + Gated-DeltaNet hybrid attn | **No** (Instruct-only, no `<think>`) | UD-Q4_K_XL **46 GB**; Q8_0 84.8 GB | **~59 (measured, Vulkan)** | **llama.cpp-vulkan** (Ollama lib entry exists but arch support immature) | Apache-2.0 |
| 2 | Qwen3-30B-A3B-Instruct-2507 | 30.5B / 3.3B | MoE (128 experts, 8 active) | **No** (Instruct-only) | UD-Q4_K_XL 17.7 GB; Q8_0 32.5 GB | ~62–96 (MoE class) | Ollama **or** llama.cpp | Apache-2.0 |
| 3 | Qwen3.6-35B-A3B | 35B / ~3B | MoE | **Hybrid** (instruct mode exists but toggle-gated) | UD-Q4_K_M ~21 GB | ~62–81 (measured) | Ollama / llama.cpp | Apache-2.0 |
| 4 | IBM Granite-4.0-H-Small (Instruct) | 32B / **9B** | Hybrid Mamba-2 / Transformer MoE | **No** (separate Instruct vs Thinking checkpoints) | Q4_K_M 19.6 GB; Q8_0 34.3 GB | ~25–40 (9B active; slower) | llama.cpp (Mamba); Vulkan still rough | Apache-2.0 |
| 5 | gemma-4-26B-A4B-it | 25.2B / 3.8B | MoE | **Hybrid, default-ON; broken via our path** | Q4 18 GB; Q8 28 GB | ~48 (measured) | — **disqualified** | Apache-2.0 |

### Why #1 (Qwen3-Next-80B-A3B-Instruct)
- **Quality:** Qwen reports it performs **on par with Qwen3-235B-A22B-Instruct-2507** on
  many benchmarks — that's flagship-class synthesis/instruction-following in an
  80B/3B-active package. For Dewey's job (read one article, write a grounded kid-safe
  answer), this is comfortably above gemma3:27b.
- **Speed:** Only ~3B active params → measured **~59 tok/s on this exact GMKtec/Strix
  Halo class box** under Vulkan/RADV. That's faster than the current gemma3:27b dense
  (~12 tok/s class), turning ~25s answers into a few seconds.
- **Non-thinking:** Dedicated Instruct checkpoint, **never** emits `<think>` blocks — no
  toggle needed, so it sidesteps the entire LiteLLM/Ollama thinking-suppression problem.
- **Fits:** UD-Q4_K_XL is ~46 GB on disk/VRAM; reports show the hybrid+SWA KV cache fits
  in ~92 GB on 128 GB unified-memory boxes even at long context — well inside the 96 GB
  carve-out, with room for the keyword model alongside.
- **Caveat (the real cost):** the **Gated-DeltaNet hybrid attention is not a stock
  transformer**, so it needs **llama.cpp `server-vulkan`** (supported after PR #19408).
  An `ollama.com/library/qwen3-next:80b` entry exists, but treat Ollama support as
  not-yet-proven on gfx1151 — stand it up under llama.cpp-vulkan first. Recommend running
  it as a **second llama.cpp-server instance** behind LiteLLM, leaving Ollama for the
  keyword model and any other Ollama-native models.

### Why #2 is the pragmatic fallback (Qwen3-30B-A3B-Instruct-2507)
This is the lowest-risk upgrade path: it's a clean, **plain-transformer MoE** that Ollama
0.17.x loads natively, it's already a proven family on this box (~62–96 tok/s class), and
it's a dedicated non-thinking Instruct checkpoint. Its answer quality is very good but a
notch below Qwen3-Next/235B-class synthesis. Use this if you want the win **today**
without standing up a separate llama.cpp server; move to #1 when you want the quality
ceiling.

### Why gemma-4-26B-A4B is disqualified (important)
On paper it looks ideal (3.8B active MoE, ~48 tok/s, Apache-2.0). In practice it hits
**two documented Ollama bugs that map exactly onto Dewey's setup**:
1. **Ollama #15288** — via the OpenAI `/v1/chat/completions` endpoint (what LiteLLM
   calls), **content is always empty and all text lands in the `reasoning` field**;
   `think:false` is not honored on that endpoint.
2. **Ollama #15428** — the **26B MoE returns a completely empty response when the system
   prompt exceeds ~500 chars**. Dewey's RAG system prompt (article + instructions) is far
   over that.

Gemma 4 also has reasoning **on by default**. Net: it would reproduce the exact
"empty content, budget burned on hidden reasoning" failure already seen with
qwen3.5-9b / qwen3-0.6b. Avoid until those Ollama issues close.

### Note on Granite-4.0-H-Small
Genuinely attractive on the non-thinking axis — IBM ships **separate Instruct and
Thinking checkpoints**, so the Instruct variant truly never reasons, and it has a strong
instruction-following / RAG reputation. But (a) **9B active** makes it meaningfully
slower than the 3B-active Qwen MoEs on this bandwidth-bound box, and (b) the **hybrid
Mamba-2 arch on Vulkan is still rough** (e.g., llama.cpp #16684 reports Vulkan iGPU hangs
on granite-4.0-h-tiny). Keep it as a watch-item, not a primary.

---

## Keyword / query-rewrite model — ranked shortlist

Job: distill a kid's message into a 1–2 word kiwix search term, resolve pronouns from
chat context, output `NONE` for small talk. Needs reliable terse instruction-following,
must be non-thinking, must be tiny/instant.

| Rank | Model | Params | Thinking? | Quant / VRAM | Serving | License | Notes |
|---|---|---|---|---|---|---|---|
| **1** | **Qwen3-4B-Instruct-2507** | 4B dense | **No** (dedicated Instruct, no `<think>`) | Q4_K_M 2.5 GB; **Q8_0 4.3 GB** | Ollama / llama.cpp | Apache-2.0 | Strong IFEval; best terse-instruction follower in class |
| 2 | Qwen3-1.7B (use **non-thinking only with care**) | 1.7B | **Hybrid** — leaks reasoning even with toggle off | ~1.4 GB Q4 | Ollama | Apache-2.0 | Faster but risky given our toggle problem; not recommended |
| 3 | LFM2-2.6B (Instruct) | 2.6B dense-hybrid | **No** (use base Instruct, not -Thinking) | ~1.7 GB Q4 | Ollama / llama.cpp | LFM Open License | Beats gemma3:4b on IFEval (79.56), CPU/iGPU-efficient, good extraction |
| 4 | IBM Granite-4.0-h-tiny (Instruct) | 7B / 1B active MoE | **No** (separate Instruct ckpt) | ~4 GB Q4 | llama.cpp | Apache-2.0 | Clean non-thinking, but Mamba+Vulkan flaky (#16684) |
| 5 | gemma3:4b (**incumbent**) | 4B dense | No | ~3 GB Q4 | Ollama | Gemma | Works but "marginal at distillation" per current use |

### Why #1 (Qwen3-4B-Instruct-2507)
- **Dedicated non-thinking Instruct** — no `<think>`, no toggle, no leakage. Directly
  fixes the keyword-model failure mode.
- **Better instruction-following than gemma3:4b** at the same size: the 2507 Instruct
  refresh specifically improved instruction following / alignment, and it's well-regarded
  for terse, format-constrained outputs (ideal for "return one keyword or NONE").
- **Effectively free to run** at 2.5–4.3 GB; use **Q8_0** — at this size the quality
  delta over Q4 matters more than the trivial extra VRAM/bandwidth.
- Loads natively in Ollama 0.17.x — keep it on the Ollama instance.

**Avoid for this role:** Qwen3-1.7B / Qwen3-0.6B and SmolLM3-3B / LFM2.5-1.2B-Thinking —
all **hybrid or thinking** models. Research (arXiv 2510.12680) confirms hybrid models
"only partially suppress reasoning" and leak `wait`/`hmm` even with empty `<think>`
blocks — the same trap you already hit.

---

## Speed reality on this box

- **Measured bandwidth ~215 GB/s** (≈256 GB/s theoretical LPDDR5X-8000). Token generation
  is bound by how fast weights for the *active* params are read each token.
- **MoE with ~3B active is the sweet spot:** Qwen3-Coder-30B-A3B measured **~97–98 tok/s**
  (Vulkan/RADV, Q4_K_S/UD-Q4_K_XL); Qwen3.6-35B-A3B **~62–81 tok/s**; **Qwen3-Next-80B-A3B
  ~59 tok/s** (huge total params but still only 3B active); gemma-4-26B-A4B ~48 tok/s.
- **Dense scales badly:** dense ~27B is usable but ~12 tok/s class; dense 70B ≈ ~5 tok/s
  (Llama-3.1-70B measured ~4.8) — unusable. This is why the current dense `gemma3:27b`
  feels slow (~25 s/answer).
- **Active-param rule of thumb (estimate):** sustained tok/s ≈ (bandwidth ÷ active-param
  bytes) with overhead. ~3B-active Q4 models land in the ~55–98 tok/s band depending on
  total size / KV pressure; 9B-active (Granite-H-Small) drops to a ~25–40 tok/s estimate
  (not separately measured here — reasoned from active-param count + bandwidth).

---

## Explicit comparison vs current picks

**Answer: Qwen3-Next-80B-A3B-Instruct vs `gemma3:27b` — yes, clearly better.**
- *Quality:* gemma3:27b is a solid dense 27B; Qwen3-Next benchmarks on par with
  Qwen3-235B-A22B-Instruct-2507, a much higher tier of synthesis/instruction-following.
  Better for accurate, age-appropriate grounded summaries.
- *Speed:* gemma3:27b is dense (~12 tok/s class → ~25 s/answer). Qwen3-Next is 3B-active
  MoE at ~59 tok/s → roughly 2x faster, multi-second answers. **Better quality AND faster**
  — the explicit goal.
- *Behavior:* both are non-thinking in practice, but Qwen3-Next is non-thinking *by design*
  (no toggle dependency).
- *Cost:* requires a separate **llama.cpp-vulkan** server (the hybrid arch). If that's not
  worth the ops cost yet, **Qwen3-30B-A3B-Instruct-2507** on Ollama is still a clear
  upgrade over gemma3:27b on speed with comparable-or-better quality.

**Keyword: Qwen3-4B-Instruct-2507 vs `gemma3:4b` — better at the same size/speed.**
- Same ~4B class and Ollama-native, but the 2507 Instruct refresh is a stronger terse
  instruction-follower and more reliable at constrained outputs ("one keyword or NONE"),
  directly addressing the "marginal at distillation" complaint. No regression in speed.

---

## Standout mid-2026 releases worth knowing

- **Qwen3-Next-80B-A3B-Instruct** — high-sparsity MoE + Gated-DeltaNet hybrid attention;
  235B-class quality at 3B active. The headline pick. Needs llama.cpp (PR #19408+).
- **Qwen3.6-35B-A3B (Apr 2026)** — strong agentic/coding MoE, but hybrid-thinking;
  the toggle problem makes it second-tier for Dewey despite good speed (~62–81 tok/s).
- **Qwen3-30B-A3B-Instruct-2507** — the dependable non-thinking workhorse; best
  Ollama-native answer-model option.
- **Gemma 4 (E2B/E4B, 26B-A4B MoE, 31B dense)** — Google's MoE entry; attractive specs but
  default-on reasoning + the two Ollama bugs above make 26B-A4B unusable on our path today.
- **IBM Granite 4.0 / 4.1** — novel hybrid Mamba-2/Transformer MoE; *separate* Instruct vs
  Thinking checkpoints (a genuine non-thinking design). Held back only by Vulkan/Mamba
  maturity and higher active-param count.
- **LiquidAI LFM2 / LFM2.5** — efficient on-device hybrid family (incl. an 8.3B/1.5B-active
  MoE); LFM2-2.6B Instruct beats gemma3:4b on IFEval and is a good keyword-tier alternative.
- **GLM-4.7-Flash (Jan 2026)** — 30B/~3B-active MoE, but hybrid reasoning; same toggle
  caveat. Worth re-checking if/when a clean instruct checkpoint ships.

---

## Recommended rollout

1. Keyword model: pull `Qwen3-4B-Instruct-2507` **Q8_0** into Ollama, swap it in for
   `gemma3:4b` in `files/dewey-pipeline.py` (beelink-ansible). Low risk, immediate.
2. Answer model (fast path): pull `Qwen3-30B-A3B-Instruct-2507` UD-Q4_K_XL into Ollama,
   A/B against `gemma3:27b` on Dewey prompts. Likely ship this first.
3. Answer model (quality ceiling): stand up `ghcr.io/ggml-org/llama.cpp:server-vulkan`
   serving `unsloth/Qwen3-Next-80B-A3B-Instruct-GGUF:UD-Q4_K_XL` as a second LiteLLM
   backend; A/B vs #2. Adopt if the quality gain justifies the extra server.
4. Sampling for all three: `temp 0.7, top_p 0.8, top_k 20, min_p 0, presence_penalty 0–2`.

---

## Sources

- Qwen3-Next-80B-A3B-Instruct GGUF (params, non-thinking, quant sizes, llama.cpp): https://huggingface.co/unsloth/Qwen3-Next-80B-A3B-Instruct-GGUF , https://huggingface.co/Qwen/Qwen3-Next-80B-A3B-Instruct
- Qwen3-Next llama.cpp support (PR #19408) + 92 GB unified-memory fit: https://github.com/QwenLM/Qwen3.6/discussions/139 , https://unsloth.ai/docs/models/tutorials/qwen3-next
- Ollama qwen3-next library entry: https://ollama.com/library/qwen3-next
- Qwen3-30B-A3B-Instruct-2507 GGUF (3.3B active, non-thinking, quant/VRAM): https://huggingface.co/unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF
- Qwen3-4B-Instruct-2507 GGUF (non-thinking, quant sizes): https://huggingface.co/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF , https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507
- Qwen3.6-35B-A3B (Apr 2026 release, hybrid modes): https://huggingface.co/Qwen/Qwen3.6-35B-A3B , https://qwen.ai/blog?id=qwen3.6-35b-a3b
- Gemma 4 26B-A4B (specs, default-on thinking): https://huggingface.co/google/gemma-4-26B-A4B-it , https://ai.google.dev/gemma/docs/capabilities/thinking
- Gemma 4 Ollama bugs (empty content on OpenAI endpoint; MoE empty on long system prompts): https://github.com/ollama/ollama/issues/15288 , https://github.com/ollama/ollama/issues/15428
- IBM Granite 4.0 (hybrid Mamba MoE, separate Instruct/Thinking): https://www.ibm.com/new/announcements/ibm-granite-4-0-hyper-efficient-high-performance-hybrid-models , https://huggingface.co/unsloth/granite-4.0-h-small-GGUF , https://research.ibm.com/blog/granite-4-1-ai-foundation-models
- Granite Vulkan/Mamba issue: https://github.com/ggml-org/llama.cpp/issues/16684
- Strix Halo tok/s benchmarks (Vulkan/RADV, MoE vs dense, ~215 GB/s): https://github.com/hogeheer499-commits/strix-halo-guide , https://kyuz0.github.io/amd-strix-halo-toolboxes/ , https://llm-tracker.info/AMD-Strix-Halo-(Ryzen-AI-Max+-395)-GPU-Performance , https://akehir.com/blog/strix-halo-kubernetes-llm-qwen-3.6
- Hybrid-thinking suppression is unreliable (research) + Ollama `/set nothink` bug: https://arxiv.org/html/2510.12680v1 , https://github.com/ollama/ollama/issues/12907
- LFM2 / LFM2.5 (on-device, IFEval, instruct vs thinking): https://huggingface.co/LiquidAI/LFM2-2.6B , https://arxiv.org/html/2511.23404v1
- SmolLM3 (dual-mode reasoner): https://huggingface.co/blog/smollm3
