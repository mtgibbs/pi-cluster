# KV Sizing & Sessions — Local Model Serving Notes

> Living notes (started at QCon, 2026-06-01) on KV cache sizing and prefix caching for
> the Beelink local-model serving plane. The goal: get the most out of *very* constrained
> hardware (one unified-memory APU) by not wasting prefill. Append as we learn.

- **Box:** Beelink GTR9 Pro — Ryzen AI Max+ 395 (Strix Halo, gfx1151), **128 GB unified RAM**,
  Ollama + llama-server on **Vulkan/RADV** (ROCm broken for gfx1151 — see `docs/beelink-ai-stack.md`).
- **Serving constraint:** unified memory → **weights + KV + parallel slots all share one
  ~96–111 GB GPU budget.** No separate VRAM to spill into.
- **Related:** `docs/beelink-ai-stack.md` (stack + Ollama env), `docs/model-eval-2026-05.md`,
  `docs/recaps/2026-05-21-q8-coder-agent-comparison.md` (the `OLLAMA_CONTEXT_LENGTH=32768` fix).

---

## 0. Guiding principle (QCon, standout quote)

> **"Minimize copies whenever possible."**

Copies come in three flavors; the principle kills all three:

| Flavor | Example | Killed by |
|---|---|---|
| **Memory copy** | host RAM → VRAM over PCIe | zero-copy / DMA / **unified memory** |
| **Serialization copy** | (de)serialize across a network/proxy hop | shared memory, RDMA, fewer hops |
| **Compute "copy" (redo)** | re-prefilling the same prefix every turn | **prefix caching** |

**The twist for us:** on a discrete GPU the #1 copy is host RAM → VRAM over PCIe — the whole
zero-copy/GDS/RDMA industry exists to minimize *that*. **Strix Halo has no such copy** — the iGPU reads
the *same* unified RAM; weights are `mmap`'d from page cache and used in place. So we got the
foundational "minimize copies" win **for free, by architecture** — much of the fancy GPU-zero-copy KV
stack (§4) is clawing back a copy we never pay. The copies *we* can still hunt: the **compute redo**
(re-prefill → prefix caching, §2) and the **one serialization hop we own** (Pi → LiteLLM →
Ollama/llama-server; a copy per SSE chunk — negligible vs prefill/decode, but the only copy in our data
path worth a glance for tail latency).

---

## 1. KV cache sizing — the budget

Everything that must fit in ~100 GB:

```
Σ_models [ weights  +  (NUM_PARALLEL × CONTEXT × kv_bytes_per_token) ]   ≤  ~100 GB
```

- 30B-class GQA model: `kv_bytes_per_token` ≈ **~0.25 MB/tok** at fp16.
- Example: coder = 25 GB weights **+ 2 slots × 32K × 0.25 MB ≈ 16 GB KV = ~41 GB**.
- **KV, not weights, blows the budget** — observed: `gemma3:27b @ 131K ctx = 42 GB` (vs 17 GB weights).

**Current Ollama knobs (from the runbook):**

| Knob | Value | Effect on KV |
|---|---|---|
| `OLLAMA_CONTEXT_LENGTH` | `32768` | caps KV at 32K tok per model, **globally** |
| `OLLAMA_NUM_PARALLEL` | `2` | **2× KV** — each model reserves 2 slots |
| `OLLAMA_MAX_LOADED_MODELS` | `3` | up to 3 models resident (weights+KV) |
| `OLLAMA_FLASH_ATTENTION` | `1` | **non-negotiable** — FA=0 bloats KV → model falls to CPU |

**Sizing levers (not yet pulled):**
- **Per-model `num_ctx`** instead of the blunt global 32K (Dewey keyword model needs ~1K; coder
  wants *more* than 32K). Lever exists via LiteLLM per-model overrides; unused.
- **KV cache quantization** (`q8_0` ≈ ½ KV, `q4_0` ≈ ¼) — doubles context or model headroom for
  near-zero quality cost. Untouched. Synergistic with prefix caching (cached prefixes get cheaper too).
- **`NUM_PARALLEL` per-mode** — family wants 2 (two kids, no head-of-line block); sole-tenant coder
  wants 1 (less wasted KV *and* better prefix reuse — see §2).

### Admit by projected KV footprint, not concurrency (QCon)

Gate admission on **KV bytes**, not **request count** — per-request footprint varies wildly by
workflow (a 200-tok chat vs a 100K-tok agent are both "1 request" but one eats 500× the KV).
Concurrency is wrong both ways: cap at N and N long-context users blow the budget → eviction thrash;
N short ones waste capacity.

**Uncomfortable mirror: Ollama is the anti-pattern.** It admits by **count** (`NUM_PARALLEL`) and
reserves **worst-case footprint** (global `32K` × every slot, always — `2 × 32K` per model regardless
of actual request size). That's *why* family-mode hits eviction churn: it's the model, not mis-tuning.
The fix — **vLLM PagedAttention + token-budget admission + continuous batching** (pack many short OR
few long, dynamically, preempt on overrun) — is CUDA/ROCm-gated.

**Our partial approximations** (real dynamic admission is gated):
1. **Per-model `num_ctx`** — footprint-aware *statically* (9b reserves small KV; coder big). Stop the
   global 32K over-reserving light models.
2. **Route by workflow at LiteLLM** — light/classification → `qwen3.5:9b`; heavy/agentic → coder.
   Footprint-based admission *at the proxy*, before Ollama reserves KV.
3. **TPM limits** (already set per virtual key) — crude footprint proxy; not real-time KV admission.

> Nuance: you can project **prefill** footprint exactly (prompt length known); **decode** growth is
> open-ended. vLLM admits on prompt + reserves incrementally + **preempts** on overrun. Ollama can't
> preempt gracefully (it queues/evicts) → for us, footprint-admission = "bound worst case (ctx caps) +
> route by size (LiteLLM)", not true dynamic admission.

---

## 2. Prefix caching — the real lever for weak hardware

**Prefill vs decode:**
- **Prefill** = process the whole prompt at once to build its KV. Compute-heavy; it's your TTFT.
  On an iGPU, prefilling 32K can take *many seconds*.
- **Decode** = generate one token at a time. Bandwidth-bound.

In an **agentic loop**, each turn re-sends a prompt that's *mostly identical* to last turn. Without
caching you **re-prefill the same ~30K tokens every turn.** Prefix caching keeps the shared prefix's
KV and only prefills the *new* tokens (the delta). **The weaker the prefill, the bigger the win** —
which is exactly why this matters most on this box.

### Taxonomy (QCon notes) + what this box can actually do

| Category | What it is | On the Beelink? |
|---|---|---|
| **Cross-session** (system prompt identical for every user) | shared KV pool across different users/requests | **❌ Mostly no** — this is vLLM Automatic Prefix Caching / SGLang RadixAttention; needs CUDA/ROCm. gfx1151 ROCm broken. |
| **Within-session** (prior turns still in cache) | one conversation's growing prefix reused turn-to-turn | **✅ Yes — the main win.** llama-server slots (work-mode) + Ollama context reuse. |
| **Shared prefixes allow reuse** | the principle: longest *identical* leading prefix is reused | **✅ The design rule** behind both — the part we control. |

### The design rule (maximizes all three)

> **Reuse = longest *identical* prefix from token 0; any divergence ends it.**
> So: **stable & identical content FIRST, volatile content LAST.** System prompt → tool defs →
> fixed context up top; the new user turn at the bottom. One changing token near the top (timestamp,
> per-user value inlined into the system prompt) silently kills the whole downstream cache.
> *Watch-out:* Dewey's system prompt names the kids inline — keep it identical across kids so the
> (limited) reuse survives; don't fork it per-user.

### What each serving path does

| Path | Caching reality |
|---|---|
| **llama-server** (Q8 work-mode) | **slot-based prompt cache** — reuses longest common prefix in a slot. Agentic coder's growing context → only new tokens prefilled. Likely the real reason work-mode is on llama-server. |
| **Ollama** (family-mode, incl. `qwen3-coder:30b`) | keeps the *last* context per loaded model, reuses if the new prompt **extends** it. Coarser; `NUM_PARALLEL=2` works against it (round-robin slots break prefix affinity). |

### Verify it's working (do this at the box)

Ollama response JSON: `prompt_eval_count` (tokens prefilled) + `prompt_eval_duration`.
- Turn 1: `prompt_eval_count` ≈ whole prompt (full prefill).
- Turn 2 (cache hit): should **drop to just the new tokens.** If it stays high → caching NOT working,
  you're paying full prefill every turn.
- Bonus: `prompt_eval_count / prompt_eval_duration` = **real prefill tok/s on this iGPU** = the cost
  of a cache *miss*. (llama-server: `timings.prompt_n` / `prompt_ms`.)

### Hardware trick for the ❌ cross-session row

> **`llama.cpp --prompt-cache <file>`** can pre-bake a fixed system prompt's KV to disk and load it —
> a poor-man's cross-session cache for one stable prefix (prefill once ever, not per cold start). Not
> a dynamic shared pool like vLLM, but it's the lever that exists without ROCm. Integration with the
> LiteLLM→llama-server path needs thought (runtime slot cache already covers within-session).

---

## 3. Tiered & remote KV caching — and why our hardware collapses it

**The textbook hierarchy** `VRAM → DRAM → NVMe → Recompute` assumes a **discrete GPU**:
small-fast VRAM, big-slower DRAM across PCIe, then disk. Tiering there spills KV out of cramped
VRAM into roomy DRAM to gain capacity.

**We don't have that split.** Strix Halo is **unified memory** — the iGPU's "VRAM" is a carved-out
slice of the same 128 GB LPDDR5X the CPU uses. So our hierarchy collapses:

```
Discrete-GPU box:   VRAM ──PCIe──► DRAM ────► NVMe ──► Recompute
Our Beelink:        [ unified RAM ] ─────────► NVMe ──► Recompute
                      (VRAM ≡ DRAM, one pool)
```

- **VRAM→DRAM collapses to one tier.** "Offloading KV from GPU to CPU memory" moves it within the
  *same* DIMMs — no capacity gained, no PCIe penalty. The classic tiered-KV *capacity* win (relieve a
  24 GB card with 256 GB DRAM) **doesn't apply** — 128 GB is the whole pool, ceiling included.
  *Caveat:* memory tiers collapse, but **GPU-vs-CPU compute does not** — a model shoved to CPU compute
  is unusably slow even on the same RAM (the `FA=1` lesson).
- **NVMe tier** exists (2 TB P310) but llama.cpp/Ollama **don't auto-page KV to it.** Only handle:
  **`--prompt-cache <file>`** (manual, static save/load of one prefix). Decision rule:
  > **NVMe-load beats recompute when prefill is slow + prefix is big & stable.**
  > 32K KV from NVMe ≈ 2–5 s; re-prefilling 32K on the iGPU ≈ tens of seconds. → Pin the **fixed
  > system prompt** to NVMe — biggest win right after an `aimode` switch (currently reloads + re-prefills cold).
- **Recompute** = the default fallback prefix caching exists to avoid.

**Remote / distributed KV (vLLM LMCache, Mooncake)** shares a KV pool across **multiple inference
nodes**. We have **one serving box** → remote KV buys ~nothing (no peer to share with), and it's
CUDA/ROCm-gated anyway. The only "remote-ish" move is the NVMe `--prompt-cache` file as a crude
persistent store across restarts.

### Spill only helps when it survives churn (QCon)

Spilling KV to a lower tier costs a copy **now** and only pays back on a **hit later**:
> Spill is worth it **iff** `P(reused before evicted) × prefill_saved > spill_copy_cost`.
> **High churn → `P(reused before evicted) → 0`** → you paid the spill copy *and* recompute anyway. Worse than not spilling.

This is the exact line between our two cache tools:
- **RAM slot cache** (within-session) — **does NOT survive** model eviction / `aimode` switch (churn = the model swap). Helps only within a residency window.
- **NVMe `--prompt-cache`** (fixed system prompt) — **survives** (on disk, persists across reload/reboot). The one prefix worth spilling, because it must *outlive* the churn.

→ Pin the stable system prompt (survives + reused → spill pays); don't spill volatile conversation KV
(won't survive our `MAX_LOADED=3` + aimode eviction → pure loss, just recompute). And note: enterprise
tiered-spill wins because a **huge** CPU/disk/remote pool lets entries survive longer (more hits) —
**capacity buys churn-survival, and capacity is what we're short on.**

**Punchline:** tiered/remote KV is for split-memory rigs and multi-node clusters; we're neither.
Our actionable toolkit: **shrink KV** (quant + per-model ctx), **keep within-session prefixes warm in
RAM** (slot cache), **NVMe-pin the fixed system prompt** for aimode-switch cold starts.

## 4. LMCache + Valkey (QCon talk) — the "removes copy from KV hot path" pitch

**LMCache** = a KV cache *layer* for vLLM. Two corrected facts:
- **Chunk = 256 *tokens* (default, configurable)** — groups pages across layers. The *byte* size is
  model-derived; "4 MB" is a per-model figure, **not** a universal constant. Don't enshrine 4 MB.
- **NOT remote-only — it's tiered:** CPU DRAM (hot, pinned, ~5 GB default) → local disk/NVMe →
  remote (Redis / **Valkey** / Mooncake / InfiniStore / S3). CPU offload is the recommended baseline.
- Also does **prefill-decode disaggregation** (one GPU prefills, another decodes, KV transferred) —
  multi-node, irrelevant to a single box.

**The Valkey pitch ("removes copy work from the KV hot path"):** Valkey is one of LMCache's *remote*
backends. LMCache does **zero-copy** KV movement between tiers, and with **RDMA / GPUDirect Storage
(GDS)** the GPU↔store path skips the CPU bounce buffer — so offloading/reloading KV to Valkey doesn't
pay the serialization + memcpy tax that normally makes remote KV not worth it. Elegant: a fast,
persistent, shareable KV tier *without* the copy overhead.

**Reality check for our box:** the whole thing (zero-copy kernels, RDMA, GDS) is **vLLM + CUDA-coupled.**
Beelink is Vulkan/RADV, ROCm broken for gfx1151, no GDS → **can't run it.** Same gate as vLLM-APC /
SGLang. Single-node → cross-node sharing is moot anyway.

**Silver lining — pre-stocked:** we **already run Valkey** (n8n-valkey on the Pi + the Beelink stack).
The *store* half of the pitch is already deployed. The missing piece is the **GPU-side engine**
(vLLM + working ROCm/CUDA + GDS), not the KV store. So if Strix Halo gets working ROCm — or we add an
NVIDIA box / a second serving node — the Valkey-KV-backend path is unusually short to stand up. **File
as: frontier, gated, but pre-stocked.**

> Sources: LMCache [architecture](https://docs.lmcache.ai/developer_guide/architecture.html) /
> [CPU RAM backend](https://docs.lmcache.ai/kv_cache/storage_backends/cpu_ram.html) /
> [paper](https://arxiv.org/html/2510.09665v2); vLLM [KV offloading connector](https://blog.vllm.ai/2026/01/08/kv-offloading-connector.html).

## 5. The frontier (gated for us today)

- **vLLM Automatic Prefix Caching** (block-hash) + **SGLang RadixAttention** (radix tree) = shared
  cross-user prefix pool, the "identical system prompt prefilled once globally" win.
- **Gated:** both want CUDA/ROCm; gfx1151 ROCm is broken. We're on the **llama.cpp slot-cache tier** —
  squeeze it dry (verify it's on, `parallel=1` for solo, stable-prefix prompts, KV-quant for headroom).
- Revisit if AMD fixes ROCm for Strix Halo (then: vLLM + LMCache + Valkey backend — see §4).

## 6. Scaling out (multi-GPU) — where it all composes, and our fan-out path

Multi-GPU is where the gated building blocks (remote KV, zero-copy/RDMA, footprint admission) assemble
into a distributed KV fabric. Parallelism taxonomy + interconnect needs:

| Parallelism | What's split | KV implication | Interconnect |
|---|---|---|---|
| **Tensor (TP)** | each layer's weights | KV sharded per-GPU | **tight** — NVLink/PCIe (100s GB/s), per-layer all-reduce |
| **Pipeline (PP)** | layers across GPUs | KV per-GPU for its layers | medium — activations at boundaries |
| **Replica / data** | full copies, load-balanced | own KV + **shared pool reuses prefixes across replicas** | **loose** — network speed |
| **Prefill–decode disagg** | prefill pool ↔ decode pool | **KV transferred between them** (the zero-copy/RDMA hot path) | loose-ish, bandwidth-sensitive |

This is where remote KV (Valkey/LMCache) and "minimize copies" earn their keep: a prefix prefilled on
replica A is reused on B; prefill GPUs hand KV to decode GPUs without recompute.

**Our position: single GPU today → not live (doubly gated: no 2nd GPU + ROCm broken). BUT our realistic
fan-out is the *loose-coupling* path, and the scaffolding already stands:**
- **Tensor parallelism is out** — needs NVLink-class bandwidth; our **dual 10 GbE (1.25 GB/s)** would
  bottleneck per-layer all-reduce. ❌
- **Replica parallel + shared KV + PD-disaggregation suit 10 GbE** (move whole requests + KV *chunks*,
  not per-token activations): **Valkey** (deployed) = shared KV store ✅; **dual 10 GbE** = fabric ✅;
  **LiteLLM** (already routing/load-balancing per key) = request distributor ✅.

> We have the entire fan-out **scaffolding** standing; what's missing is **GPUs + a working framework**
> (a 2nd serving box + vLLM-on-ROCm, which doesn't exist for gfx1151). The day either lands, we plug
> GPUs into a fabric already shaped like a multi-GPU serving cluster. **The consistent gate across this
> whole doc is GPUs + ROCm/CUDA — never the surrounding system.**

### Prefill/decode (P/D) disaggregation

Rests on one fact: **prefill and decode are opposite workloads.**

| | Prefill | Decode |
|---|---|---|
| Pattern | whole prompt in one parallel pass | one token at a time |
| Bottleneck | **compute-bound** (FLOPs) | **memory-bandwidth-bound** (reads all weights+KV per token) |
| Wants | compute throughput | bandwidth + big batches to amortize weight reads |
| Latency role | TTFT (bursty) | inter-token latency (steady) |

On shared hardware they fight: a long prefill stalls the steady decode stream (head-of-line) and breaks
decode batching. **Disaggregation = separate device pools** (prefill compute-optimal; decode
bandwidth-optimal with big batches), **KV shipped between them** (NVLink/RDMA/**NIXL** = the zero-copy
hot path). Payoff: scale prefill vs decode pools **independently** + kill interference.

**"The ABCD exercise" (QCon) — TODO:** speaker's worked scheduling example; A/B/C/D labeling not yet
captured (likely 4 prefill/decode jobs placed across devices). *Fill in from notes.*

**For us:** full disaggregation is gated (needs multiple devices + NIXL/RDMA). One iGPU does both. **But
the interference is real on one GPU too — esp. family mode** (one kid's long prefill freezes another's
decode). Single-device mitigation = **chunked prefill** (interleave prefill chunks with ongoing decode).
⚠️ *Verify:* vLLM chunks prefill by default; whether our **Ollama/llama.cpp** build interleaves (vs
prefill-then-decode) is unconfirmed — it's the difference between smooth concurrent family use and
head-of-line stalls. → measurement list.

### Cache-aware routing — §2 slot-affinity at fleet scale

Route a request to the worker that already has most of its prefix cached, balanced against load:
- **vLLM-style:** consistent hashing on prefix (affinity) + load metrics (avoid hot spots).
- **NVIDIA Dynamo Smart Router:** computes a KV-**overlap score** between the request and KV blocks live
  across *every GPU* (tracked in a **RadixTree** fed by KV-cache events), weighted against load — and
  **the cache-vs-load balance is the tunable knob** (ships an A/B tuning guide). `--router-track-output-blocks`
  accounts for the *un-projectable decode-side KV growth* (callback to §1 admission).

This is the **§2 slot-affinity insight at a different altitude**: single server → `NUM_PARALLEL=1` keeps
the slot warm; fleet → cache-aware routing keeps the session on the replica that holds its prefix. Same
rule: *don't scatter a session off its warm cache.*

**For us:** LiteLLM is **KV-blind** — it routes by load/latency/cost/usage (the load half), with zero
visibility into backend KV state (no overlap score). Full Dynamo/vLLM routers are CUDA-gated (Dynamo
uses NIXL for KV transfer). **Hardware-agnostic poor-man's version when we fan out: consistent-hash-on-
session at LiteLLM** → sticky sessions → warm-replica affinity, works on Ollama/llama.cpp with no
KV-event plumbing. Gets most of the cache-hit win; misses Dynamo's precise overlap scoring + tunable
load-rebalance (blind affinity can hot-spot). The 80/20 that *isn't* gated.

> Sources: Dynamo [KV Router](https://docs.nvidia.com/dynamo/latest/router/README.html),
> [routing guide](https://docs.nvidia.com/dynamo/latest/user-guides/kv-cache-aware-routing),
> [smart-router blog](https://developer.nvidia.com/blog/introducing-nvidia-dynamo-a-low-latency-distributed-inference-framework-for-scaling-reasoning-ai-models/),
> [A/B tuning](https://docs.nvidia.com/dynamo/latest/benchmarks/kv-router-ab-testing.html).

---

## 7. The talk's close — three pillars + the philosophy

The speaker's closing slide reduced the whole thing to **three pillars**, then a set of
"mechanical empathy" reminders. Mapped to our box:

| Closing pillar | The talk's point | Our reality |
|---|---|---|
| **Cache-aware placement** | put the request where its KV already lives (§6 routing) | LiteLLM is KV-blind today; the gated-free 80/20 is **consistent-hash-on-session** when we fan out. |
| **Disaggregation** | split prefill vs decode onto device pools (§6) | one iGPU does both → gated; the single-box echo is **chunked prefill** (verify it fires). |
| **KV state** | the KV cache *is* state — size it, place it, own it (§1) | **admit by projected KV footprint, not concurrency** — our partial fix is per-model `num_ctx` + LiteLLM route-by-size. |

### The reminders (mechanical empathy)

> **Every token becomes state that someone has to carry.**

That's the thesis of the whole doc. A token isn't free once generated — it lives in the KV cache,
occupies budget, must be placed, may be evicted, may be shipped. **Generating context is taking out a
loan against the KV budget.**

- **As users:** long context is powerful — **use it deliberately.** Don't pad prompts; every padded
  token is KV someone carries. (Our lever: trim OpenCode/Dewey system prompts; route light work to a
  small-`num_ctx` model.)
- **As capacity planners:** **plan the KV, not just the QPS.** Request *count* is a lie — footprint
  varies 500× by workflow (§1). Size the box by Σ KV-bytes, not requests/sec.
- **As designers:** **locality is not an optimization, it is respect for the work already done.** Don't
  scatter a session off its warm cache; don't bust the prefix with a volatile token up top (§2). The
  prefill already happened — honor it.

> **Design for the state you create.** The single sentence that ties §0 ("minimize copies") to §1–§6:
> the copies, the evictions, the routing, the disaggregation — all of it is *managing state you chose
> to bring into existence by accepting a token.* The cheapest KV is the token you didn't generate; the
> second-cheapest is the one you never moved.

**For us, concretely:** we are a *very* small shop, so "design for the state you create" mostly means
**don't create state we then have to carry on one iGPU** — short stable-first prompts (§2), per-model
`num_ctx` instead of a blanket 32K (§1), and route-by-size at LiteLLM (§1). The fancy carrying
machinery (remote KV, disaggregation, overlap-score routing) is for shops whose state already exceeds
one box. Ours doesn't yet — so the win is *creating less state*, not *carrying it better*.

---

## 8. Tool definitions live in the prefix — MCP churn busts the cache (+ the cost angle)

The §2 "stable-first, volatile-last" rule has a sharp, under-appreciated edge: **tool / function
definitions are part of the prefix.** Chat-with-tools prompts are laid out:

```
[ system prompt ]  →  [ tool / function definitions ]  →  [ conversation messages ]
```

Tools sit high — right after the system prompt, before the conversation. So **changing the tool set
(add/remove an MCP server, reorder tools, edit one description) breaks the cache at the tool block and
re-prefills everything after it.** Tool churn = cache miss.

> **Live irony:** dynamic tool loading (Claude Code's `ToolSearch` / deferred tools) loads schemas
> *on demand* to save context — but each mid-session load *changes the tool block*, so the next call
> can't reuse the prefix from that point down. It's a **context-size ↔ cache-stability trade.** Most
> tuning only sees the context-size half.

**Design implication for our MCP stack:** a request's reachable tool set should be **stable within a
session.** If `mcp-homelab` + `local-llm-mcp` + `kiwix-mcp` are all always-present, the tool block is
constant and caches. If we lazy-attach/detach MCP servers per task, we pay a re-prefill each time the
set flips. (Same reason `go-unifi-mcp` "lazy mode" — `tool_index`/`execute`/`batch` — is *cache-kind*:
3 stable meta-tools instead of a churning list of N concrete ones.)

### The cost angle — same idea, billed (future cost-optimization work)

This is where local prefix caching and **cloud API cost** are literally the same mechanism:

- **Anthropic / OpenAI prompt caching** = prefix caching with a price tag: a **`cache_read` token costs
  ~10% of a normal input token.** Stable prefix → ~90% off those tokens.
- The rules are *identical* to our local ones: **stable system prompt, stable tool set, volatile last.**
  A churny MCP tool list silently forfeits the discount on every call.
- Other "cheaper large-model" levers, all mirroring local §1: **route-by-size** (small model for light
  work), **Batch API** (50% off non-interactive), **shorter stable prompts** (fewer tokens to cache *or*
  carry).

### Proxy = the measurement that makes it real (you can't optimize what you can't see)

A proxy in the path exposes the **cache-hit telemetry** that turns this from vibe to KPI:

- The response usage carries `cache_read_input_tokens` vs `cache_creation_input_tokens` vs plain
  `input_tokens`. **`cache_read / (cache_read + input)` _is_ the cache hit rate.**
- **LiteLLM already sits in our local path** — it can log/aggregate these per virtual key. If we ever
  proxy Anthropic-API traffic the same way, we get one dashboard for both planes.
- Once it's a tracked number, "keep the tool set stable" becomes a **regression-testable metric**: a
  cache-hit-rate drop after a prompt/tool change is a measurable cost regression, not a guess.

**→ Future thread:** stand up cache-hit-rate observability at LiteLLM (local) — candidate first metric
for a "model cost optimization" pass. Mirrors §1's "measure before you tune."

---

## Open questions / next measurements

- [ ] Measure real **prefill tok/s** on the iGPU (`prompt_eval`) — quantify what a cache miss costs.
- [ ] Confirm **within-session caching is actually firing** in (a) llama-server work-mode, (b) the
      Ollama family-mode coder. (`prompt_eval_count` drop on turn 2.)
- [ ] Decide **`NUM_PARALLEL` per-mode** (family=2, coder=1) — is that worth the aimode complexity?
- [ ] Try **`q8_0` KV cache quant** — does it let the coder run >32K, or keep a 4th model resident?
- [ ] Audit OpenCode + Dewey **prompt assembly** for volatile content near the top (cache-busters).
- [ ] Evaluate **`--prompt-cache` to disk** for the fixed system prompts (worth the wiring?).
- [ ] **Chunked prefill?** Confirm whether our Ollama/llama.cpp interleaves prefill with decode (vs prefill-then-decode) — the family head-of-line-stall question.
- [ ] **NVMe-pin the fixed system prompt** (`--prompt-cache`) to skip cold re-prefill after an `aimode` switch — measure load-from-NVMe vs recompute on this iGPU.
- [ ] **Cache-hit-rate observability at LiteLLM** (§8) — log `cache_read` vs `input` tokens per key; first metric for a model-cost-optimization pass. Audit whether MCP tool sets stay stable within a session (tool churn = cache miss).
