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
- **TL;DR / start here:** §9 *"Steal the principle, skip the framework"* — the one-table summary of every
  gated datacenter idea paired with the 80/20 that runs on our single iGPU today.

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

### Why it's *prefix* caching: the causal chain (the load-bearing intuition)

A token's KV is **not a standalone value you can pluck out.** K and V are vectors bound to a position in
a **causal chain**:

- A token's K/V is computed from its hidden state.
- That hidden state was built by **attending back over every prior token, at every layer.**
- So token *N* is, transitively, a function of tokens *0 … N−1*.

**Eviction damage is directional.** Evict a token at position *k*:
- Tokens *before* it (`0 … k−1`) stay valid — they never depended on *k*.
- Everything **from *k* onward is forfeit for reuse.** Regenerating *k*'s KV means re-running the forward
  pass over `0 … k`. So it's not "recompute everything" — it's **"recompute from the broken link forward."**

> **This is *the* reason caching is prefix-shaped, not "cache any token I like":** reuse is only a
> **contiguous run from token 0**, and the first hole ends it. A mid-prefix eviction doesn't cost you one
> token — it costs you **the entire tail behind it.** PagedAttention/blocks don't change this: pages can
> sit in non-contiguous *physical* memory, but the *logical* sequence is still one chain — a hole in the
> logical middle forfeits the logical tail.

Two later rules fall straight out of this:
- **§2 "stable-first, volatile-last":** a changed token high up isn't a 1-token miss — it *orphans
  everything below* (same chain, mutation instead of eviction).
- **§1/§3 "spill only helps if it survives churn":** eviction is a **cliff, not graceful degradation** —
  lose a mid-prefix block and the suffix re-prefills wholesale.

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

**"The ABCD exercise" (QCon) — the switch-tax analogy.** The speaker had the room read aloud: reciting
`A B C D` (or `1 2 3 4`) straight through is fast and effortless — but **interleaving** them, `A1 B2 C3
D4`, is slow and taxing *even though it's the same symbols*. The cost isn't the work; it's the **constant
context-switch between two kinds of work.** That's the human stand-in for **prefill (letters) vs decode
(numbers)**: each rips through fast *homogeneously*, but force one device to interleave them and you pay
the switch tax on every flip. The exercise is the intuition pump **for** disaggregation — split the
streams so each device runs its own easy `A B C D`, never `A1 B2 C3 D4`. (And it's why the single-box
mitigation is *chunked* prefill: chop the letters small so the switches are cheap, since we can't avoid
them on one GPU.)

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

## 9. Steal the principle, skip the framework

The whole talk describes a **datacenter** KV stack (vLLM, SGLang, LMCache, Dynamo, NIXL) — almost all of
it CUDA/ROCm-gated and built for fleets whose state exceeds one box. **The frameworks don't run on a
single Vulkan iGPU. The principles do.** Every gated idea has a hardware-agnostic 80/20 on our stack:

| § | Principle (the idea) | Framework / gated form | Why gated for us | Our 80/20 (runs today) | Status |
|---|---|---|---|---|---|
| §0 | **Minimize copies** | zero-copy / GDS / RDMA host→VRAM | needs discrete GPU + PCIe | **unified memory already kills the PCIe copy** — `mmap` weights in place | ✅ free by architecture |
| §1 | **Admit by projected KV footprint, not concurrency** | vLLM PagedAttention + token-budget admission + continuous batching + preempt | CUDA/ROCm | per-model `num_ctx` (static footprint) + **route-by-size at LiteLLM** + TPM caps | ⚠️ partial — `num_ctx` lever unused |
| §1 | **Shrink the KV itself** | — (just a knob) | not gated | **`q8_0`/`q4_0` KV-cache quant** (≈½/¼ KV) | 🔧 untouched lever |
| §2 | **Reuse the prefix** (cross-session) | vLLM Automatic Prefix Caching / SGLang RadixAttention | ROCm broken on gfx1151 | **within-session** reuse: llama-server slots + Ollama context-extend | ✅ the main win |
| §2 | **Stable-first, volatile-last** (incl. tool defs, §8) | — (the design rule) | not gated | the part we fully control — author prompts/tool sets for it | ✅ free, needs an audit |
| §3 | **Tiered / remote KV** (spill, survive churn) | LMCache + Valkey (CPU/disk/remote, 256-tok chunks) | overkill for one box; no second tier in unified RAM | **`--prompt-cache` to NVMe** for the fixed system prompt | 🔧 future, low effort |
| §6 | **Disaggregate prefill vs decode** | separate device pools + KV via NIXL/RDMA | needs ≥2 devices | **chunked prefill** (interleave on the one GPU) — *verify it fires* | ⚠️ verify |
| §6 | **Cache-aware routing** (don't scatter a session off its warm cache) | Dynamo Smart Router (overlap score) / vLLM consistent-hash | CUDA + KV-event plumbing | **consistent-hash-on-session at LiteLLM** (sticky → warm replica) | 🔮 when we fan out |
| §8 | **Don't bust the prefix** (cost) | Anthropic/OpenAI prompt caching (~10% per `cache_read`) | not gated — it's the *cloud* plane | stable system prompt + **stable MCP tool set**; same rule, billed | ✅ free discount, easy to forfeit |
| §8 | **Measure the hit rate** | — (observability) | not gated | **LiteLLM logs `cache_read`/`input`** = hit rate; one dashboard, both planes | 🔮 first cost-opt metric |

**The pattern in one line:** the gated stuff exists to *carry state across many boxes efficiently*. We
have one box and (for now) little enough state to fit it — so our wins are **(a) the copies we avoid for
free by unified-memory architecture, (b) creating less state in the first place (§7), and (c) the handful
of unused knobs — `num_ctx`, KV-quant, `--prompt-cache`, stable tool sets — that need no framework at
all.** When our state finally outgrows one box, the *same principles* tell us exactly which framework to
reach for and why.

> Litmus test for any future "should we adopt $FANCY_KV_THING?": **is it minimizing a copy we actually
> pay, or carrying state we actually have?** On one unified-memory box the answer is usually "neither yet"
> — revisit when §1's budget equation stops closing.

---

## 10. Quantization for our stack

Two **independent** axes, both under-used. On 128 GB unified RAM we're *not* bit-starved like a 24 GB
consumer GPU — so for us quantization is mostly about **fitting more models resident + leaving KV
headroom**, not desperately shrinking one model.

### Axis 1 — weight quantization (the model itself)

GGUF ladder, lowest-effort-to-highest-quality:

| Quant | ~bits | Use |
|---|---|---|
| `Q4_K_M` | ~4.5 | **sweet spot**; minimal loss. `qwen3-coder:30b` (25 GB) lives here. Family/multi-resident/speed. |
| `Q5_K_M` / `Q6_K` | 5–6 | closer to fp16; quality-sensitive work with budget to spare. |
| `Q8_0` | 8 | near-lossless. Q8 Qwen3-Coder-Next (85 GB) = work-mode flagship. |
| `IQ4_XS` / `IQ3_M` / `IQ2` | <4 | **importance-matrix** quants — better quality *per bit* at the low end. The lever to **fit a bigger model than would otherwise go** (e.g. a 70B-class at `IQ4` inside budget). |

- **Don't go below `Q4` for coding** — quality falls off a cliff at `Q3`/`Q2`; reserve those for
  "fit it at all" experiments.
- **`IQ` only to fit a *bigger* model** — otherwise K-quants are simpler and (often) faster on Vulkan.

### Axis 2 — KV-cache quantization (the §1 lever — our biggest unused win)

Shrinks the **cache**, not the weights — attacks the budget §1 says actually blows up
(`gemma3:27b @ 131K = 42 GB KV` vs 17 GB weights).

- **Ollama:** `OLLAMA_KV_CACHE_TYPE=q8_0` (or `q4_0`). **Requires flash attention — already on**
  (`OLLAMA_FLASH_ATTENTION=1`). One env-var change.
- **llama-server:** `--cache-type-k q8_0 --cache-type-v q8_0`.
- **Payoff:** `q8_0` KV ≈ **half** the bytes at near-zero quality cost → **double the context** *or*
  room for a 4th model. `q4_0` ≈ quarter, but measurable long-context quality risk — use sparingly.
- **Synergy with §2:** a quantized KV makes *cached prefixes* cheaper to hold too → more sessions stay
  warm in the same budget.

### Concrete moves (matched to our two modes)

1. **Turn on `OLLAMA_KV_CACHE_TYPE=q8_0` now** — prerequisite (FA) already met; loosens the §1 budget
   across every loaded model. **Cheapest move on the board.**
2. **Match weight quant to mode:** family/multi-resident → `Q4_K_M`; sole-tenant coder quality → `Q8`.
3. **`IQ4_XS`** only to fit a model bigger than the budget otherwise allows.

### Verify at the box (Vulkan-specific — ⚠️)

- **KV-quant rides the flash-attention kernel**, and Vulkan FA has historically lagged CUDA. Confirm
  `q8_0` KV actually loads (and doesn't silently fall to CPU) before trusting it.
- **`IQ` quants can be slower on Vulkan** (importance-matrix lookups add decode overhead). Benchmark
  tok/s before adopting `IQ` over `Q4_K_M`.

---

## 11. Optimizing agentic flows on our box

Agentic flows (OpenCode + `qwen3-coder`, Dewey, anything MCP-driven) are the **canonical "long stable
prefix + growing context + heavy tool use" workload** — so they're where every lever in this doc pays
off most. Ordered by leverage:

### 1. Prefix reuse is the whole game (§2)

Each turn re-sends a prompt **~95% identical** to last turn + a small delta. Without reuse we re-prefill
~30K tokens *every step* — seconds of dead time per turn on this iGPU.
- **`NUM_PARALLEL=1` in work-mode** → slot affinity (growing context pinned to one slot, only the delta
  prefills). `=2` round-robins slots and **breaks** affinity. Likely *why* work-mode is on llama-server.
- **Verify:** `prompt_eval_count` should crater on turn 2+. If it doesn't, the cache isn't reusing —
  that's the #1 fix.

### 2. Context-assembly discipline — don't sabotage the cache (§2, §8)

Reuse only survives to the **first changed token**:
- **No volatile content near the top** (timestamp, "current time", regenerated file-tree in the system
  prompt) — it orphans everything below. **Audit OpenCode + Dewey prompt assembly.**
- **Stable tool set** (§8) — don't add/remove MCP servers mid-session; the tool block is in the prefix.
  `go-unifi-mcp` lazy-mode (3 stable meta-tools) is the cache-kind shape.
- **Order:** system → tool defs → fixed context → conversation. Volatile last, always.

### 3. Manage context *growth* — every token is state you carry (§7)

Loops accumulate history until they hit the cap, then thrash:
- **Truncate/summarize tool outputs** before they enter context — don't leave 50 KB of file content as
  permanent KV weight on every later turn.
- **Compaction:** summarize old turns. Costs **one** cache-bust, then stable again — net win on long loops.
- **Fresh context for bounded sub-tasks** rather than dragging the whole history into a small job.

### 4. Tune the KV budget for the agentic *shape* (§1, §10)

Agentic wants **more context, less parallelism** (opposite of family chat):
- **Per-model `num_ctx` > 32K for the coder** — the global 32K cap actively hurts long loops.
- **`q8_0` KV-quant** (§10) buys that context for ~half the bytes.
- **`NUM_PARALLEL=1`** — less wasted KV *and* better prefix affinity.

### 5. Route by step type — footprint admission for sub-steps (§1)

Agentic flows are heterogeneous: planning needs the big model; tool-arg formatting, classification,
"is it done?" checks don't. **Route light steps to `qwen3.5:9b`** at LiteLLM; reserve the coder for
reasoning → frees its KV, runs cheap steps faster.

### 6. Reliability levers (correctness, not just speed)

- **Quant matters for agentic *specifically*:** our finding — **Q8 is meaningfully better for agentic
  ops** even though 30B-Q4 is ~95% on raw codegen. Tool-call discipline degrades faster under
  quantization than raw coding does. Keep work-mode on Q8.
- **Text-format tool-call fallback parser** — qwen3 sometimes emits tool calls as prose; our pipelines
  already handle it. Keep it.

### 7. Frontier (benchmark before adopting)

- **Speculative decoding** (`--model-draft`) — small draft proposes, coder verifies; speeds decode-bound
  generation. **But** on one shared iGPU the draft also eats memory/compute → win uncertain. Measure tok/s.
- **Chunked prefill** (§6) — keeps a big agent context from head-of-line-stalling other work in family mode.

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
- [ ] **Turn on `OLLAMA_KV_CACHE_TYPE=q8_0`** (§10) — FA prerequisite already met; ⚠️ verify it loads on RADV/Vulkan and doesn't fall to CPU. Cheapest single budget win.
- [ ] **Audit OpenCode + Dewey for agentic prefix-reuse** (§11) — `prompt_eval_count` drop on turn 2; volatile content near prompt top; tool-set stability within a session.
- [ ] **Route agentic light-steps to `qwen3.5:9b`** at LiteLLM (§11) — classification / tool-arg / "is it done?" off the coder.
