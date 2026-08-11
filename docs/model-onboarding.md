# Model Onboarding — How We Try Out a New Model

**Status:** Living runbook (started 2026-08-11)
**Applies to:** the Beelink inference plane (`docs/beelink-ai-stack.md`). Not the cluster.
**Why this exists:** models land faster than we evaluate them. `docs/model-eval-2026-05.md` was a
good one-off, but every candidate since has restarted from zero — re-deriving the same VRAM math,
re-discovering the same thinking-mode trap. This is that knowledge as a checklist, plus a
**decision log (§6)** so the next evaluation starts where the last one ended.

Six steps. Steps 1–2 are paper and cost nothing; **most candidates should die there.**

> **The box, in one line:** Ryzen AI Max+ 395 (gfx1151), 128 GB unified LPDDR5X @ ~215 GB/s,
> ~96 GB carved as VRAM, 2 TB NVMe. Inference is **memory-bandwidth-bound**, so *active* parameters
> set your speed, not total parameters. ROCm is broken on gfx1151 — everything serves over Vulkan/RADV.

---

## 0. How we hear about a candidate — `model-watch`

A monthly CronJob (`clusters/pi-k3s/model-watch/`) pushes a digest to the ntfy
**`model-watch`** topic on the 1st. It exists because the interesting question is never
"what is the best open model" — the frontier tier stopped fitting this box in mid-2026 —
but **"what is the best model that fits ~96 GB."** That's a filter, and a filter is worth
automating.

Two signals, separated by how far they can be trusted:

- **HuggingFace API → hard facts.** Trending text-generation models in the window, then
  the per-model endpoint for `safetensors.total`, `config.num_experts` /
  `num_experts_per_tok`, and licence. Parameter counts, MoE sparsity and the Q4 fit
  estimate are **computed**, so the digest can't invent a model or misreport its size.
- **Model cards → soft judgements.** Only candidates that clear the gates get their
  README fetched and handed to the Beelink, which judges what metadata can't express:
  dedicated Instruct vs hybrid thinker, tool support, what it is actually for. Cards are
  third-party text and the prompt treats them as untrusted.

Buckets: **test** (MoE, fits, permissive licence), **consider** (fits but dense — full
weight traffic per token on a bandwidth-bound box), **watch** (too big, or a licence that
needs reading), **skip** (derivative repo, or a licence we will not take).

Two filters that matter more than they look, both found by running it against live data:

- **Derivative repos are dropped via HF's `base_model:` relation tag** — otherwise GGUF
  repacks and abliterated finetunes bury the real releases. But a **vendor's own**
  instruct-tune of its **own** base is a real release, so the org is compared rather than
  dropping every `finetune` outright.
- **MoE config keys are not standardised** — `num_experts`, `n_routed_experts`,
  `moe_num_experts`, `num_experts_per_tok`, `n_activated_experts`… Checking only the Qwen
  spelling made a 35B-A3B model come back as "dense 7.3B".

Knobs are env vars on the CronJob (`WINDOW_DAYS`, `MIN_LIKES`, `VRAM_BUDGET_GB`); raise
`MIN_LIKES` if the push gets noisy. **Known gap:** open-ended web research (release blogs,
community signal such as the standing petition for a GLM-5.2-Air) needs either a
search-API credential or a Claude-side routine — the in-cluster job reads HF only, so it
will miss a model that matters but has not trended yet.

## 1. Intake — the gates a candidate must pass before anyone spends a weekend

Fail any of these and the answer is no, regardless of benchmark scores.

- **Non-thinking Instruct checkpoint** for anything behind a LiteLLM pipeline. Not "a hybrid model
  with thinking switched off" — a *dedicated* Instruct checkpoint. Our path cannot suppress
  reasoning: LiteLLM's `drop_params:true` strips the toggle, and Ollama's `/v1/chat/completions`
  ignores `think:false`. Hybrid models leak `<think>` blocks and burn the context before any content
  appears. This gate alone has killed more candidates than every other combined.
- **Tool support declared in the serving template**, if the consumer needs tools. LiteLLM correctly
  refuses to send tool definitions to a model whose template doesn't advertise them — this is why
  `gemma3:27b` was dropped for Dewey despite being the original pick. *(Exception: a deterministic-RAG
  pipeline drives retrieval itself and needs no tool support — that rearchitecture is what let Dewey
  move to Instruct-only models.)*
- **Low active parameters.** Sparse MoE beats dense at equal quality here, because we're bandwidth-bound.
  A 3B-active 80B model outruns a dense 30B on this box.
- **Licence:** Apache-2.0 or MIT. We have held this line; a permissive licence is part of the
  digital-homesteading point, not a legal formality.

## 2. Feasibility math — before you download anything

Everything shares **one ~96–111 GB budget**. Unified memory means there is no separate VRAM to spill
into: weights + KV cache + parallel slots all come out of the same pool. Compute all three before
pulling a single byte. Numbers and derivations live in `docs/research/kv-sizing-and-sessions.md`.

- **Weights** at your target quant. UD-Q4_K_XL is the house default; Q8 only for sole-tenant work mode.
- **KV cache — the term people forget, and it is architecture-dependent, not size-dependent.**
  Qwen3-Next's hybrid linear attention costs ~0.8 GiB per 32k, so 256k context fits in ~86 GiB total.
  A dense 30B's quadratic KV would balloon to ~71 GiB at the same context. *Check the attention
  architecture before you believe a context-length claim.*
- **Concurrency.** `OLLAMA_NUM_PARALLEL=2` and `OLLAMA_MAX_LOADED_MODELS=5` mean several models may be
  resident at once. Observed in production: `gemma3:27b` at its default 131k context took **~42 GB**,
  not the 17 GB on disk. Budget for loaded context, not file size.
- **Guardrail:** `OLLAMA_CONTEXT_LENGTH=32768` exists because unbounded context blew the KV cache.
  Don't raise it casually.

If the arithmetic doesn't close on paper, stop here. This step is why we knew Qwen3-Next-80B would fit
before downloading 46 GB.

## 3. Stand-up — pick the path by how novel the thing is

| What you're adding | Path |
|---|---|
| **Plain-transformer model Ollama already supports** | `ollama pull hf.co/<repo>:<quant>`, then `ollama cp` to a stable local name. The alias is what everything else references — never point consumers at the upstream tag. |
| **Novel architecture** (hybrid attention, Mamba, an MoE the runtime doesn't know) | A **second `llama-server` instance** behind LiteLLM. This is why Qwen3-Next-80B needed llama.cpp-vulkan: Gated-DeltaNet isn't a stock transformer. Leave Ollama serving everything else. |
| **A whole new engine** (Colibri, vLLM, anything with its own runtime) | Its own process, its own port, behind LiteLLM if it speaks OpenAI. **Never in-place, never replacing a working serving path.** Treat the engine itself as the thing under evaluation — see `docs/research/colibri-moe-disk-streaming.md`. |

Then register it: LiteLLM `/model/new` (DB-backed, so it persists in Postgres and lands in the nightly
backup), and add it to the **specific virtual-key allowlists** that should reach it. Keys are scoped
per consumer on purpose — Dewey's key reaches exactly two models. A new model reaches nobody until you
say so, which is the correct default.

## 4. Evaluate — what "tried it out" actually means

Measure at minimum, and write the numbers down:

- **Heat-up** — Ollama's `load_duration`. **Always label page-cache-warm vs true-cold.** Most timings
  we've recorded are warm and therefore optimistic; true-cold is disk-bound (~1.7 GB/s observed), so a
  25 GB model is ~15 s cold and the 85 GB Q8 runs to the 60–120 s budget.
- **Throughput** (tok/s) at a realistic context, not at zero context.
- **The behaviour gates from §1, verified rather than assumed** — actually check for leaked `<think>`
  blocks, actually send a tool definition through LiteLLM. Model cards lie by omission.
- **A fixed prompt set for the target role**, reused across candidates so results are comparable.

Two rules learned the expensive way during the token-bench campaign:

- **Cross-day numbers are invalid.** `aimode` drift changes what's resident underneath you. Always
  re-run an anchor arm in the same window as the thing you're comparing.
- **An optimization is a hypothesis until an A/B shows otherwise.** Attach the hardware and the
  configuration to every number you record, or it isn't a measurement.

`scripts/token-bench/` is the only measured harness we own (arms, regex grading, `results.jsonl`).
It currently varies *context strategy* with the model held fixed. Inverting that — hold the arm
fixed, vary the model — would turn it into a proper model-comparison rig. **Future work, deliberately
not built** (2026-08-11 scoping call); until then §4 is manual and that's fine.

## 5. Promote or shelf

- **Promote** = repoint a LiteLLM alias. `hot-coder` is the single knob that moves `oc`, the Ops
  pipeline, and MCP downstream together — that indirection is the whole point, so promotion is one
  change, not a hunt through consumers.
- **Shelf** = leave it registered but on no allowlist. Costs disk, reaches nobody, easy to revisit.
  `gemma3:27b` lives here.
- **Rollback** = repoint the alias back. Keep the previous model pulled until the new one has survived
  real use for a few days; deleting weights is the irreversible step, and it's never urgent.

Anything that changes the Beelink's *configuration* (not just its model registry) is an Ansible change
in `beelink-ansible` — authored via PR, applied from the laptop. Per `feedback_everything_as_code`,
nothing here is a one-time SSH edit.

## 6. Decision log

Append a row whenever a candidate is decided. Backfilled from `docs/model-eval-2026-05.md` and
`docs/beelink-ai-stack.md` so this starts with history rather than empty.

| Date | Candidate | Role | Arch / active | Verdict | Reason |
|---|---|---|---|---|---|
| 2026-05-20 | `qwen3.5:9b` | Dewey answer | dense 9B | **Adopted, later replaced** | Tool support worked where gemma3 didn't; replaced once RAG removed the tool requirement |
| 2026-05-20 | `gemma3:27b` | Dewey answer | dense 27B | **Shelved** | Ollama template doesn't declare tool support → LiteLLM refuses tool defs |
| 2026-05-22 | `Qwen3-4B-Instruct-2507` (Q8_0) | Dewey keyword | dense 4B | **Adopted** | Dedicated Instruct (never emits `<think>`), strong terse instruction-following, ~free at 4B |
| 2026-05-22 | `Qwen3-30B-A3B-Instruct-2507` | Dewey answer | MoE 30.5B / 3.3B | **Adopted** | Non-thinking Instruct, clean Ollama load, ~62–96 tok/s; the low-risk win |
| 2026-05 | `Qwen3-Next-80B-A3B-Instruct` | Answer, quality ceiling | MoE 80B / ~3B | **Recommended, llama.cpp path** | ~59 tok/s measured on this box, 235B-class quality; needs llama.cpp-vulkan (Gated-DeltaNet) |
| 2026-05 | `gemma-4-26B-A4B-it` | Answer | MoE 25.2B / 3.8B | **Rejected** | Hybrid thinking default-ON and unsuppressible through our path |
| 2026-05 | IBM Granite-4.0-H-Small | Answer | hybrid Mamba-2 MoE 32B / 9B | **Deferred** | Genuine non-thinking checkpoint, but Vulkan/Mamba maturity + 9B active |
| 2026-06-24 | Qwen3-Coder-Next Q8 | Work-mode coder | MoE, hybrid linear KV | **Adopted** | 256k native context at ~86/96 GiB; `hot-coder` alias flips to it via `aimode work` |
| 2026-08-11 | **Colibrì + GLM-5.2** (engine) | Frontier / async | 744B / 40B, disk-streamed experts | **Rejected — not now** | ~0.5 tok/s projected on our drive class; auto-pin wants 37–47 GB against a 96 GB VRAM carve. Triggers to revisit in `docs/research/colibri-moe-disk-streaming.md` |

---

**See also:** `docs/beelink-ai-stack.md` (the stack), `docs/model-eval-2026-05.md` (the worked example
this generalises), `docs/research/kv-sizing-and-sessions.md` (the math), `scripts/token-bench/README.md`
(the harness), `.claude/skills/coding-agent-ops/SKILL.md` (driving `oc` once a model is promoted).
