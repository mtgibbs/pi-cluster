# Colibrì — Disk-Streaming MoE Inference, and Whether It Belongs on the Beelink

**Date:** 2026-08-11
**Status:** Paper research complete — **verdict: not now**, with named triggers to revisit (§6)
**Method:** Primary sources only (engine README, `docs/tuning.md`, `docs/benchmarks.md`, issue #124);
secondary coverage used for framing, not for numbers. **Nothing was run on our hardware** — Matt
scoped this paper-only, so every figure below is someone else's measurement and is labelled with
whose box it came from.
**Related:** `docs/beelink-ai-stack.md` (the box), `docs/model-eval-2026-05.md` (how we pick models),
`docs/research/kv-sizing-and-sessions.md` (KV math), `docs/model-onboarding.md` (the process this fed)

## Question

Colibrì claims to run **GLM-5.2 — 744B parameters — on 25 GB of RAM**, and the claim is true. Should
we run it on the Beelink, and what do we learn from it either way?

## TL;DR

**No, not today — and unusually, we can say that with real confidence instead of hand-waving, because
somebody already ran it on our exact CPU.**

Colibrì is a genuinely clever ~2,400-line pure-C engine. It keeps GLM-5.2's dense trunk (~9.9 GB in
int4) resident and streams the model's **21,504 experts** off NVMe on demand. Only ~40B params are
active per token and only ~11 GB of them change token-to-token, so the working set fits a laptop.
The catch is not subtle and the project does not hide it: **capacity comes from disk, and latency is
paid in disk reads.**

The decisive evidence is [issue #124](https://github.com/JustVugg/colibri/issues/124) — a **Ryzen AI
Max+ 395 with 128 GB unified LPDDR5x**, i.e. the same silicon and same memory as our Beelink. Tuned,
CPU-only, on a *good* SSD it sustained **1.10 tok/s**. Three things in that thread rule us out for now:

1. **Our drive is the wrong half of that test.** The tester benchmarked two SSDs on identical silicon:
   a DRAM-less Kingston managed **0.55 tok/s**, an SK hynix P41 (with DRAM) **0.81–1.24**. The binding
   constraint was **random-read latency at low queue depth, not bandwidth**. Our Crucial P310 is
   Phison E27T, **DRAM-less/HMB, 232-layer QLC** — structurally the Kingston end of that split.
2. **The RAM isn't free on our box.** Colibrì's auto-pin claimed **37–47 GB** for expert caching. The
   #124 tester had all 128 GB available because they left the iGPU unused. We carve **~96 GB as VRAM**,
   and work-mode Q8 already holds ~85 GB. The warm numbers depend on precisely the page cache we
   don't have spare.
3. **Thermals bit them in an ordinary desktop.** The SSD controller climbed **56 °C → 84 °C** (throttle)
   during a 128-token run, producing 0.58–1.35 tok/s run-to-run variance from heat soak alone. The
   GTR9 Pro is a small-form-factor chassis.

Best-case honest projection for the Beelink as configured: **~0.5 tok/s**, i.e. a 500-token answer in
roughly **15 minutes**. That is not a latency problem to be tuned away; it is the architecture working
as designed.

What we *should* take from it is in §7 — the persisted compressed KV idea and the measurement posture
are worth more to us than the engine is.

---

## 1. What it actually is

| | |
|---|---|
| **Repo** | [JustVugg/colibri](https://github.com/JustVugg/colibri) — Apache-2.0, ~24.1k stars, ~1,194 commits, active |
| **Implementation** | Pure C + OpenMP, zero runtime dependencies, ~2,400 lines. GCC/Clang; Linux, macOS, native Windows via MinGW-w64 |
| **Serving** | `coli serve` / `coli web` — OpenAI-compatible API, streaming, KV slots, batching via the gateway, web dashboard with live expert visualisation |
| **GPU** | Optional, not required. README lists **CUDA**, **Vulkan 1.2 (incl. AMD via RADV)**, **Metal**. "Speed is set by your disk." |

Supported model families and what they cost on disk:

| Model | Total / active | Disk | RAM (min / comfortable) |
|---|---|---|---|
| OLMoE | 7B / 1B | ~4 GB | 8 GB |
| DeepSeek V4 Flash | 284B / 13B | ~167 GB | 16 / 22 GB |
| GLM-5.2 | 744B / 40B | ~372 GB | 16 / 24 GB |
| Inkling | 975B / 41B | ~469 GB | 25 GB (int4 dense) |
| Kimi K3 | 2.8T / 104B | ~1.6 TB | 32 GB+ |

GLM-5.2 itself is worth a line of context: Z.ai released it **2026-06-16** under MIT, 744B total with
~40B active, and it was the strongest open-weight model at release — NIST's CAISI assessment put its
overall capability near GPT-5.2. So the prize on offer is real; only the delivery mechanism is in question.

## 2. The mechanism, honestly

- **Dense trunk resident, experts streamed.** ~9.9 GB int4 dense container stays in RAM; the 21,504
  experts live on disk and are read per token. ~11 GB of expert traffic per generated token *is* the
  latency budget. Everything else is an attempt to avoid paying it twice.
- **Learning LRU cache.** Recently-used experts are pinned up to a `--ram` budget; the cache now raises
  its cap to fill the budget rather than only shrinking, so older published benchmarks under-report.
- **Router-lookahead prefetch** (`PILOT=1`, experimental) predicts next-layer routing at **71.6%**
  accuracy and issues readahead during the current layer. Explicitly warned to backfire on a saturated
  disk — and it did in #124 (see §3).
- **MLA-compressed KV**, ~**182 KB/token**, persisted to `.coli_kv` so context survives across
  sessions and restarts at zero re-prefill cost. This is the single most interesting idea in the
  engine for us (§7).
- **MTP speculative decoding.** Draft head must be **int8** — at int4 acceptance collapses to 0–4%.
  Measured acceptance elsewhere: 52% on Ryzen AI 9 HX 370 (2.59 tokens/forward), 57% on an i5-12600K.
- **gs64 group-scaled int4.** The older per-row int4 container measured **~9pp worse** on quality and
  was the root cause of think-mode loops and never-terminating generations
  ([#455](https://github.com/JustVugg/colibri/issues/455)); grouped scales recovered ~63% of the loss.
  If anyone ever runs this, **the container format is a correctness setting, not a size setting.**

## 3. Measured throughput — every number with its hardware attached

From the project's own `docs/benchmarks.md`, which states "everything on this page is a measurement,
not a promise":

| Hardware | Disk read | Config | tok/s |
|---|---|---|---|
| 6× RTX 5090, dual Xeon Silver 4510 | NVMe | full residency | **5.8–6.8** (TTFT ~13 s) |
| Apple M5 Max (Metal) | ~4 GB/s | 39.7 GB warm + pinning | **1.83** |
| **Ryzen AI Max+ 395 (Framework)** | 3.27 GB/s | 47.6 GB pin | **0.40** |
| Core Ultra 9 185H, native Windows | — | warm + GPU pipe | **1.07** |
| Ryzen 9 9950X, PCIe 5.0 | 8.81 GB/s | learned pin | **0.28** |
| 25 GB dev box | — | cold baseline | **0.05–0.1** |

Note the shape of that table: a PCIe 5.0 9950X reading at 8.81 GB/s lands at 0.28 tok/s while an M5
Max at 4 GB/s hits 1.83. **Sequential bandwidth is not the variable.** Cache residency and random-read
latency are.

### 3.1 The same-hardware thread (issue #124)

A tester ran `GLM-5.2-colibri-int4-with-int8-mtp` on a **Ryzen AI Max+ 395, 128 GB unified LPDDR5x,
Arch Linux, CPU-only (gfx1151 present but unused)**, across two SSDs:

| Configuration | tok/s |
|---|---|
| Cold start | 0.06 |
| Warm default (auto-pin) | 0.23–0.26 |
| `DIRECT=1 PIPE=1 --topp 0.7`, DRAM-less Kingston | **0.55** |
| `DIRECT=1 PIPE=1 --topp 0.7`, SK hynix P41 | **0.81–1.24** |
| 128-token sustained, P41, best | **1.10** (best 32-token burst: 1.35) |
| `DRAFT=0 DIRECT=1 PIPE=1` — recommended clean baseline | **1.01** |
| `DRAFT=0 --topp 0.7` | 1.60 — *with acknowledged coherence loss* |

Findings that matter more than the headline number:

- **`O_DIRECT` is the single biggest lever**: `DIRECT=1 PIPE=1` cut expert-disk time from 122.7 s to
  45.9 s (2.4×) on the Kingston. The engine's `tuning.md` separately reports O_DIRECT alone worth
  **+65%** on a Strix Halo box. Both point the same direction.
- **Drive class was worth ~1.5×** on identical silicon, and the tester attributes it to **random-read
  latency at low queue depth**, not throughput. The Kingston sustained only ~1 GB/s at low QD.
- **`PILOT=1` was net negative** — 0.71–0.89 tok/s against 1.19–1.35 for paired runs, because 28%
  wasted speculative reads competed for an already-saturated drive.
- **Thermal throttling explained the variance.** SSD controller 56 °C → 84 °C during a single
  128-token run; back-to-back runs hit a heat-soaked drive and ran ~2× slower than the same config
  after a pause. CPU stayed under 70 °C the whole time — **the SSD is the thermal bottleneck, not the APU.**
- **`--topp 0.7` buys speed by degrading output** — coherence loss and premature stop-token firing,
  with factual correctness reportedly intact. Treat the 1.60–1.85 numbers as a different quality tier,
  not a free win.

## 4. Does it produce the right tokens?

The semantics claims and the speed claims deserve different confidence, and conflating them is the
main error in the popular coverage.

**Semantics: credible.** The engine does token-exact forward validation against a transformers oracle
(typically 30–32/32 tokens matching), and the architecture supports the claim — expert *placement*
(VRAM, page cache, or disk) cannot change the router's decisions or the weights' precision. Where the
math *does* change is quantisation, and that is measured rather than assumed: an OLMoE fp16-vs-int4
A/B under one harness put the pure quantisation cost at **−8.2pp**, concentrated on the hardest task
([#225](https://github.com/JustVugg/colibri/issues/225)), with the int4 container scoring 62.5% mean
across hellaswag/arc/mmlu (n=40 each, 0-shot). That is a real quality haircut, honestly reported.

**Speed: treat with more caution.** The project's *stated* posture is good — an optimization is a
hypothesis until a controlled end-to-end A/B says otherwise. But a third party
(@ThefloorMiner) reproduced a performance claim rigorously — `.coli_usage` snapshotted between runs,
three runs per side, byte-for-byte output diffs — and reported numbers that **contradicted the original
framing**. The project's response was to endorse that as the standard it wants, which is the right
answer, but the episode is the reason §3 lists hardware next to every figure.

## 5. Feasibility on *our* box

Beelink GTR9 Pro: Ryzen AI Max+ 395 (gfx1151), 128 GB unified LPDDR5X @ ~215 GB/s, ~96 GB carved as
VRAM, 2 TB Crucial P310 on LVM (`lv-models` 1 TB, ~950 GB unallocated), Ubuntu 26.04.

| Factor | Assessment |
|---|---|
| **Disk capacity** | ✅ Fine. GLM-5.2's 372 GB fits in the ~950 GB unallocated headroom without touching `lv-models`. One-time cost is hundreds of GB *written* (download + convert) against a 440 TBW endurance budget — a few percent, acceptable. Steady-state inference is read-heavy and costs ~no TBW. |
| **Disk performance** | ❌ **The blocker.** Phison E27T, **DRAM-less/HMB, 232-layer QLC**. `tuning.md` explicitly warns O_DIRECT is "drive-dependent: QLC/DRAM-less or virtualised disks can be neutral to negative," and #124 measured that exact split as a ~1.5× penalty. We would land near the Kingston's **0.55 tok/s**, not the P41's 1.10. |
| **GPU backend** | ⚠️ Vulkan/RADV is listed as supported, and gfx1151 already serves Ollama and llama.cpp under RADV — so the **ROCm trap from `docs/beelink-ai-stack.md` does not apply here**. But #124 ran CPU-only, and no Strix Halo *Vulkan* Colibrì datapoint exists. Unproven, not impossible. |
| **RAM** | ❌ Auto-pin wants **37–47 GB** of page cache. With ~96 GB carved as VRAM and work-mode Q8 at ~85 GB, there is no room for a co-tenant. This would need a dedicated mode that evicts the stack — which is exactly the decision Matt deferred. |
| **Thermals** | ⚠️ #124 hit SSD throttle in a conventional desktop. SFF chassis, sustained multi-GB/s reads. SMART + swap monitoring would be a precondition, not a nicety. |
| **Serving integration** | ✅ `coli serve` is OpenAI-compatible, so it *would* drop in behind LiteLLM as another backend with no new contract. Not the hard part. |

**Net:** the two hard blockers are the drive class and the RAM carve, and neither is tunable. A
different SSD would move the first; only a dedicated mode moves the second.

## 6. Verdict, and what would change it

**Not now.** At ~0.5 tok/s projected, a single 500-token answer takes ~15 minutes. Matt's instinct in
scoping this — that tokens this slow are hard to value — is borne out by the numbers, and the
"async batch tier" idea it invites needs a job queue we have not built. Spending a weekend and 372 GB
to confirm a number we can already bracket from same-silicon evidence is not a good trade.

Revisit if **any** of these become true:

1. **A Strix Halo Vulkan datapoint lands above ~3 tok/s.** The GPU path on gfx1151 is genuinely
   unmeasured; if offload changes the shape rather than shaving a percentage, the calculus changes.
2. **A DRAM'd or TLC NVMe joins the box.** #124 shows drive class is worth ~1.5× on identical
   silicon, and it is the cheapest variable to change.
3. **A genuinely async workload appears** where minutes-per-answer is fine — overnight second-opinion
   judging, deep analysis, batch enrichment — **and** we have built the queue to feed it. Both halves
   required; the queue is the missing half today.
4. **The technique gets absorbed into llama.cpp.** Disk-streamed experts behind our existing serving
   path would cost us nothing to try, and is the outcome most likely to actually happen.

What we explicitly did **not** decide: where a slow tier would live if we ever wanted one. Deferred by
Matt, on purpose. This document exists to inform that call later, not to pre-empt it.

## 7. What we'd steal even if we never run it

Three ideas that transfer to the stack we actually operate:

1. **Persisted compressed KV across sessions.** Colibrì writes MLA-compressed KV (~182 KB/token) to
   disk so a conversation resumes with zero re-prefill, surviving restarts. Our
   `docs/research/kv-sizing-and-sessions.md` names the "compute redo" — re-prefilling the same prefix
   every turn — as the one copy we can still hunt on unified memory. In-memory prefix caching already
   helps within a session; *persisting* it across restarts is the version we don't have, and it is
   most valuable exactly where we hurt most (long-context `oc`/ralph runs where uncached prefill at
   58k measured ~10 min).
2. **Prefetch is only a win when the resource is idle.** `PILOT` went net-negative on a saturated
   drive because speculative work competes with real work. Same lesson our own `OLLAMA_NUM_PARALLEL`
   and warm-set tuning keeps teaching: on a single contended box, speculative anything needs headroom
   to be free.
3. **The measurement posture.** "Everything on this page is a measurement, not a promise," hardware
   attached to every number, and a third party's contradicting reproduction accepted as the standard.
   That is the same discipline `scripts/token-bench` encodes — and the same trap we fell into
   ourselves with cross-day token numbers drifting under `aimode`. Worth restating in
   `docs/model-onboarding.md`, which it now is.

---

## Sources

- Engine, README, model/hardware tables, backend support: https://github.com/JustVugg/colibri
- Tuning guidance (O_DIRECT, `RAM_GB`, PILOT, MTP, `.coli_kv`): https://github.com/JustVugg/colibri/blob/main/docs/tuning.md
- Benchmarks (throughput by hardware, MTP acceptance, quantisation cost): https://github.com/JustVugg/colibri/blob/main/docs/benchmarks.md
- **Ryzen AI Max+ 395 / Strix Halo thread (the decisive source):** https://github.com/JustVugg/colibri/issues/124
- OLMoE fp16-vs-int4 quantisation A/B (−8.2pp): https://github.com/JustVugg/colibri/issues/225
- Per-row vs gs64 int4 container, never-terminating generations: https://github.com/JustVugg/colibri/issues/455
- Crucial P310 2TB — Phison E27T, DRAM-less/HMB, 232-layer QLC, 220 TBW/TB: https://www.storagereview.com/review/crucial-p310-2tb-review , https://www.tomshardware.com/pc-components/ssds/crucial-p310-2280-ssd-review/2
- GLM-5.2 release, licence, parameters: https://simonwillison.net/2026/jun/17/glm-52/ , https://www.together.ai/models/glm-52
- NIST CAISI assessment of GLM-5.2: https://www.nist.gov/news-events/news/2026/07/caisi-assessment-zais-glm-52
- Critical secondary coverage (framing only, no numbers taken): https://wavect.io/blog/colibri-glm-5-2-consumer-hardware/
