# Session recap — 2026-06-06 (full day)

Four threads, two repos, one very long day. The threads are ordered as they ran;
later sections of this doc contain the detailed metrics and config for threads 3–4.

## Session overview

| # | Thread | Outcome | Key artefacts |
|---|---|---|---|
| 1 | **Remote-ops over Tailscale** (spec resumed) | Beelink reachable off-LAN and over exit-node via Tailscale subnet route; `beelink-ansible` deploys via MagicDNS with no overrides | `beelink-ansible` `cec8440`, `546bcf4`; pi-cluster `47d1fba`, `29f4fb6`; `specs/remote-ops-access/` |
| 2 | **Model-landscape research triage** | §15 of the local-coding-agent research log: gpt-oss-120b, Qwen3.6, K8sGPT/HolmesGPT evaluated; Qwen3.6 confirmed real | pi-cluster `528d633`; `docs/research/local-coding-agent-sdd.md` §15 |
| 3 | **Kids' AI setup for summer school** | Ronin + Rory accounts on Dewey; Dewey rebuilt (Qwen3.6 answer model, query planning, parallel retrieval, schoolwork system prompt) | `beelink-ansible` `b2e8c78`–`998a19a`; see [Accounts](#accounts) and [Dewey pipeline behavior](#dewey-pipeline-behavior-as-built-today) below |
| 4 | **GPU wedge saga + true root cause** | Traced recurring iGPU hangs to Ollama 0.17.7 running concurrent requests on a Qwen MoE architecture; fixed by bumping to 0.30.6 + `OLLAMA_IGPU_ENABLE=1`; decode 44 → 65.6 tok/s | `beelink-ansible` `e4a7057`, `201b1ac`; `docs/beelink-ai-stack.md` wedge runbook |

Threads 3–4 are documented in full below (metrics baseline, stage breakdown, final numbers,
permanent-fix invariants). Threads 1–2 are summarised in their own sections immediately below;
for the deep detail see the linked artefacts.

---

## Thread 1 — Remote-ops over Tailscale (Phase 1–3)

This resumed the spec at `specs/remote-ops-access/`. Three phases shipped today.

**Phase 1 — beelink-ansible inventory fix** (`cec8440`, `546bcf4`, beelink-ansible)

`inventory.yml` was pointing at `192.168.1.70` — the Beelink's LAN IP, which is
unroutable from off-network even over the tailnet. Switched `ansible_host` to
`beelink-ai.tailf8d786.ts.net` (MagicDNS, resolves to Tailscale IP `100.123.94.31`).
Live-verified with `ansible -m ping beelink`. Deploys now work from anywhere without
an `-e ansible_host=` override.

**Phase 2 — subnet route advertisement** (`47d1fba`, pi-cluster)

Added `192.168.1.70/32` to the Tailscale connector's `advertiseRoutes` in
`clusters/pi-k3s/tailscale-config/connector.yaml` and approved the route. This makes
`chat.lab.mtgibbs.dev`, `dewey.lab.mtgibbs.dev`, `ai.lab.mtgibbs.dev`, and
`controlpanel.lab.mtgibbs.dev` reachable over the tailnet — including from a device
using the Pi cluster as an exit node.

**Phase 3 — documentation + OQ1 resolved** (`29f4fb6`, pi-cluster)

Captured the off-net gap and SSH break-glass procedure in `.claude/skills/tailscale-ops/SKILL.md`.
OQ1 (tailnet domain) resolved: `tailf8d786.ts.net`.

SSH break-glass: `ssh -i ~/.ssh/beelink-ai -o IdentitiesOnly=yes matt@beelink-ai.tailf8d786.ts.net`
(use `-o IdentitiesOnly=yes` when the 1Password SSH agent is locked, to prevent agent-negotiation
failures from blocking the on-disk key).

---

## Thread 2 — Model-landscape research triage (§15)

Commit `528d633` added §15 to `docs/research/local-coding-agent-sdd.md`. Three models evaluated:

- **gpt-oss-120b** — OpenAI's rumoured open-weight 120B model. Verified it does not yet exist
  as a publicly released artefact; watching but not planning around it.
- **Qwen3.6 (35B-A3B)** — verified real: `qwen3.6:35b-a3b-q4_K_M` exists on the Ollama registry;
  MoE, A3B active params, hybrid-thinking. Adopted same day as the Dewey answer model (thread 3).
- **K8sGPT / HolmesGPT** — AI-assisted Kubernetes diagnostics tools. Evaluated for the homelab.
  HolmesGPT in particular can analyse Flux/pod issues from natural-language queries. Noted as
  a candidate for the cluster; no deployment decision yet.

---

## Thread 3–4 — Kids' AI setup + GPU wedge (detailed)

The rest of this doc covers threads 3 and 4 in full. The original framing below
("metrics baseline") is preserved because the numbers are the durable record.

---

# Recap: Kids' AI Setup + Dewey rebuild + latency baseline (2026-06-06)

Stood up the kids' AI for summer school (accounts + a working, schoolwork-tuned Dewey),
fixed a GPU wedge, and rebuilt Dewey's retrieval.
**This section is the metrics baseline captured right before starting latency work** —
so the numbers survive context compaction and we can measure optimization against them.

Source of truth for config = `beelink-ansible` (commits below) + `docs/beelink-ai-stack.md`.

---

## Hardware / stack context

- **Beelink GTR9 Pro** — Ryzen AI Max+ 395 (Strix Halo), iGPU **RADV GFX1151**, Vulkan
  backend (ROCm broken for this iGPU), ~**111 GiB** GPU pool, ~**215 GB/s** bandwidth
  (bandwidth-bound → MoE-with-low-active-params wins; dense models are slow per token).
- Ollama + LiteLLM + Caddy + two Open WebUI instances (`open-webui` adults, `open-webui-dewey` kids) + pipelines sidecars, Docker Compose, Ansible-managed.
- Ollama env: `OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_CONTEXT_LENGTH=32768`,
  `OLLAMA_MAX_LOADED_MODELS=3`, `OLLAMA_NUM_PARALLEL=2`, `OLLAMA_FLASH_ATTENTION=1`.

## Model decode speeds (measured 2026-06-06, Vulkan, q8_0 KV, 32k ctx)

| Model | Type | Decode | Notes |
|---|---|---|---|
| `qwen3-coder:30b` | A3B MoE | **69.5 tok/s** | fastest; coder tier |
| `qwen3.6:35b-a3b-q4_K_M` | A3B MoE | **31 tok/s** | **Dewey answer model**; standard q4_K_M |
| `gemma3:27b` | dense 27B | **6.3 tok/s** | quality good, slow (dense); first-token 7.6s warm |
| `qwen3-4b-instruct` | small | ~instant warm | Dewey keyword/planner; ~6.7s if cold-loaded |
| `qwen3-30b-instruct` | A3B MoE (unsloth **UD-Q4_K_XL**) | **WEDGED** | 0 tok/300s, GPU pegged, `amdgpu Fence fallback timer expired on ring comp_1.1.0`. **Reboot did NOT clear it. Do NOT use this unsloth UD quant on Vulkan.** |

- Prefill rate (gemma3 reference): ~29 tok/s.
- Qwen3.6 is **hybrid-thinking**: `think:false` is mandatory (15.9s → **2.3s** for one
  sentence; ~1.6k hidden reasoning tokens otherwise). `/no_think` does NOT work for it;
  the Ollama `think:false` param does and survives LiteLLM `drop_params`.

## Dewey end-to-end latency (through the pipeline, qwen3.6 warm) — THE BASELINE

| Prompt | Lookups | First token | Total |
|---|---|---|---|
| "thanks!" (chit-chat) | 0 | 6s | 7s |
| "how does photosynthesis work?" | 1 | **17s** | 25s |
| "causes of WW1?" | 1 | 20.8s | 33.8s |
| "volcanoes and earthquakes?" | 2 | 21s | 29s |
| "healthier meal at Chick-fil-A AND Panera using MyPlate" (assignment) | 2 | **29s** | 67s |

### Stage breakdown (single-query, ~17s first token)

| Stage | Time | Note |
|---|---|---|
| Planner (qwen3-4b via LiteLLM) | **~6.7s** | 4b WAS resident — so this is LiteLLM/scheduler overhead or contention from the wedged 30B stuck in "Stopping…", NOT a cold load. **Investigate first.** |
| Retrieval (kiwix) | **~2.9s / lookup** | search 0.36s + get_article(4000 chars) 2.57s. **Sequential** across lookups (2 lookups ≈ 6s). |
| Answer prefill (qwen3.6 + system prompt + 4000-char article) | **~7s** | to first token |
| Answer decode | 31 tok/s | |

## Retrieval quality (article actually grounded on)

| Query | Article picked |
|---|---|
| causes of WW1 | **Causes of World War I** (was: *List of anti-aircraft guns*) |
| photosynthesis | Photosynthesis |
| fall of Roman Empire | Fall of the Western Roman Empire |
| types of volcanoes | Shield volcano (on-topic; "types of" overview slightly off) |
| volcanoes + earthquakes | Volcano + Earthquake |
| assignment (MyPlate) | MyPlate + Healthy diet (correctly did NOT chase restaurant menu data) |

## Dewey pipeline behavior (as-built today)

- **Query planning**: 0 lookups (chit-chat) / 1 (normal) / up to **3** (multi-part). Splits a
  `CONTEXT_CHAR_BUDGET=7000` across lookups; dedupes articles by URL; footer lists all sources.
- **Deterministic RAG** (pipeline drives kiwix, model never tool-calls — so the answer model
  needs no native tool support).
- **Schoolwork-tuned system prompt**: coaches source evaluation; critiques AI answers instead
  of rubber-stamping; **never volunteers an unsourced number** (calories/dates/stats) — redirects
  to the authoritative source. (Tuned against an FLVS DBA nutrition assignment.)
- Pipeline valves: `MODEL=qwen3.6-35b` (think:false), `KEYWORD_MODEL=qwen3-4b-instruct`,
  `ARTICLE_CHARS=4000`, `MAX_QUERIES=3`, `CONTEXT_CHAR_BUDGET=7000`, `MAX_HISTORY_MSGS=6`,
  `SEARCH_ZIM=wikipedia`.
- Dewey OWUI: `BYPASS_MODEL_ACCESS_CONTROL=true` (single-model surface; every kid sees the one
  model), `DEFAULT_USER_ROLE=user`, `ENABLE_SIGNUP` (runtime) = false.
- LiteLLM: `qwen3.6-35b` registered via `/model/new` (DB-backed → in nightly Postgres backup);
  Dewey key allowlist = `[qwen3.6-35b, gemma3-27b, qwen3-4b-instruct, qwen3-30b-instruct]`.

## Accounts

- **Dewey (kids):** Ronin `ronin@lab.mtgibbs.dev`, Rory `rory@lab.mtgibbs.dev`, role=user.
  Passwords in **`op://Ronin/dewey-ronin`** and **`op://Rory/dewey-rory`** (their own vaults).
  Login verified HTTP 200. (Stale dup `dewey-*` items in `pi-cluster` vault were deleted.)
- **Adults chat:** Matt (admin) + Julia already existed.

## Tailscale / remote ops

Covered in full in [Thread 1](#thread-1--remote-ops-over-tailscale-phase-13) above.
Summary: MagicDNS inventory + `192.168.1.70/32` subnet route + SSH break-glass documented.
Spec: `specs/remote-ops-access/`.

## Latency optimization plan (next — measure against the baseline above)

1. **Planner overhead (~6.7s)** — biggest, investigate first. 4b is resident, so suspect
   LiteLLM round-trip overhead and/or GPU contention from the wedged `qwen3-30b-instruct`
   stuck in "Stopping…". Clearing the stuck model (reboot) and/or calling Ollama directly for
   the planner may collapse this.
2. **Parallelize retrievals** — independent kiwix lookups run sequentially (~2.9s each);
   concurrency saves ~3s per extra lookup on multi-part prompts.
3. **Answer prefill (~7s)** — prefix-cache the constant system prompt (KV research §2: ~77×
   on prefix reuse), trim the system prompt, and/or lower `ARTICLE_CHARS`.

## UPDATE 2026-06-06 — the GPU wedge WAS the dominant latency cause (cleared)

Lever #1 turned out to be most of the problem. The idle GPU was **pegged at 100%** by the
wedged `qwen3-30b-instruct` (unsloth UD quant) stuck in `Stopping…` — it dragged every
inference. Removed it from LiteLLM, rebooted, `ollama rm`'d the quant (permanent — see the
wedge runbook in `beelink-ai-stack.md`). Re-measured on the clean GPU (idle now **0%**):

| Prompt | Before (pegged GPU) | After (clean GPU) |
|---|---|---|
| photosynthesis (1 lookup) | 17s first / 25s total | **~7s first / ~14s total** |
| assignment (2 lookups, 5.6k-char answer) | 29s first / 67s total | **8.5s first / 37s total** |
| qwen3.6 decode | 31 tok/s | **44 tok/s** |
| idle GPU | 100% | **0%** |

First-token roughly **halved** just from clearing the wedge. Levers #2 (parallel retrieval)
and #3 (prefix-cache / trim prompt) remain available to push first-token toward ~3-4s, but
are now optional rather than urgent.

## FINAL — latency work complete (2026-06-06)

Shipped lever #2 (parallel retrieval); stopped at lever #3 after probing showed
diminishing returns. Final state:

| Case | Session start | Final |
|---|---|---|
| Single-query first token | 17s | **~7s** |
| Multi-part, 3 lookups, first token | ~16s+ (est. sequential) | **~11s** (parallel retrieval) |
| 2-lookup first token | 29s | **~8s** |
| qwen3.6 decode | 31 tok/s | **44 tok/s** |
| idle GPU | 100% (wedged) | **0%** |

- **Parallel retrieval** (`998a19a`): independent kiwix lookups run in a ThreadPoolExecutor
  (order preserved, deduped by URL). Saves ~4s on 3-lookup prompts; scales with lookup count;
  single-query path unchanged.
- **Lever #3 NOT pursued** — diminishing returns. The residual single-query ~7s = planner
  ~2.5s (4B, already smallest) + kiwix `get_article` ~1–2.5s (render/network-bound inside
  kiwix-mcp, noisy; **not** proportional to `max_chars`, so lowering `ARTICLE_CHARS` doesn't
  help and only costs grounding) + prefill ~1.5s. Prefix-caching would shave a fraction and is
  Ollama-version-dependent. None is a clean, low-risk win. With streaming, ~7s-to-first-token
  is solid for a kids' study tool.
- **If revisited later:** the only real lever left is speeding kiwix `get_article` (in the
  kiwix-mcp service) or prefix-caching the constant system prompt.

## Commits today

**beelink-ansible** (local only, no remote):
- `cec8440` thread 1 — inventory: address beelink-ai over the tailnet (ansible_host)
- `546bcf4` thread 1 — inventory: use beelink-ai MagicDNS name
- `b2e8c78` thread 3 — dewey: gemma3-27b answer model + BYPASS_MODEL_ACCESS_CONTROL (interim)
- `071717d` thread 3 — dewey: Qwen3.6-35B-A3B answer model (think:false) + pre-warm
- `83763e9` thread 3 — dewey: source-evaluation + AI-answer-skepticism prompt tuning
- `e278ba9` thread 3 — dewey: retrieval relevance (keep qualifiers, roman numerals, best-result)
- `faa68e8` thread 3 — dewey: query planning (decompose multi-part prompts)
- `998a19a` thread 3 — dewey: parallel multi-query retrieval
- `e4a7057` thread 4 — dewey: pin WEBUI_SECRET_KEY + disable OWUI aux-generation
- `201b1ac` thread 4 — fix(ollama): bump 0.17.7 → 0.30.6 + OLLAMA_IGPU_ENABLE=1

**pi-cluster (origin/main @ `0e12ac1`):**
- `ef91ff3` thread 1 — spec(remote-ops-access): plan spec
- `29f4fb6` thread 1 — docs(remote-ops): off-net gap + break-glass; OQ1 resolved (Phase 3)
- `47d1fba` thread 1 — feat(tailscale): advertise 192.168.1.70/32 (Phase 2)
- `528d633` thread 2 — docs(research): §15 model-landscape triage
- `3d6142b` thread 3 — docs(recap): this file (metrics baseline)
- `48db335` thread 4 — docs: GPU wedge root cause (unsloth UD quant) + latency halved
- `3ddf7e4` thread 4 — docs(recap): final latency numbers + permanent-fix invariants
- `0e12ac1` thread 4 — docs: GPU wedge TRUE root cause (concurrent MoE + stale Ollama 0.17.7)

## UPDATE 2026-06-06 (final) — GPU wedge TRUE root cause + Ollama bump

The wedge wasn't really "physics" or a single bad quant — it was **Ollama 0.17.7 running
concurrent requests on a Qwen MoE architecture, which doesn't support them.** Confirmed by
bumping to **Ollama 0.30.6**, which logs `"model architecture does not currently support
parallel requests" architecture=qwen35moe` and serializes them. We were ~13 versions / 6
months behind. Fix = **bump Ollama (not the host — host was already current)**:

- Wedge eliminated (concurrency-safe). Decode **44 → 65.6 tok/s** (~50% faster).
- **`OLLAMA_IGPU_ENABLE=1` is now REQUIRED** — 0.30.x drops integrated GPUs by default (else
  the model runs 100% on CPU; `total_vram=0 B`).
- Full story + the "check Ollama version first" guidance is in `beelink-ai-stack.md` wedge runbook.

## Permanent-fix invariants (don't regress)

- **Keep Ollama current and `OLLAMA_IGPU_ENABLE=1` set.** The fragile Vulkan/llama.cpp+RADV
  stack is bundled *in the Ollama container*, not the host — a stale Ollama was the real wedge
  cause. On any future wedge, check `ollama --version` vs latest FIRST.
- **Do NOT pull unsloth `UD-*` dynamic quants for MoE models** on this box — a separate, worse
  trigger (wedged even single calls). Use standard `q4_K_M` / official Ollama tags. (The broken
  `qwen3-30b-instruct` is `ollama rm`'d + deregistered from LiteLLM.)
- Qwen3.6 needs `think:false` on every call (the pipeline sends it).
- Dewey OWUI: `BYPASS_MODEL_ACCESS_CONTROL=true` (kids must see the one model); `WEBUI_SECRET_KEY`
  pinned (sessions survive restarts); title/tag/autocomplete/follow-up generation DISABLED
  (one message = one pipeline request, not four — was a concurrency source).
- Pre-warm task pins `qwen3.6:35b-a3b-q4_K_M` (think:false) + `qwen3-4b-instruct`.

