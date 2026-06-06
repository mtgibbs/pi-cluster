# Recap: Kids' AI Setup + Dewey rebuild + latency baseline (2026-06-06)

Big session. Stood up the kids' AI for summer school (accounts + a working,
schoolwork-tuned Dewey), fixed a GPU wedge, and rebuilt Dewey's retrieval.
**This doc is the metrics baseline captured right before starting latency work** —
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

## Tailscale / remote ops (earlier today)

- `beelink-ansible/inventory.yml` addresses the Beelink via MagicDNS
  **`beelink-ai.tailf8d786.ts.net`** (→ 100.123.94.31) — remote ansible deploys work with no
  `-e ansible_host=` override.
- Connector advertises **`192.168.1.70/32`** (approved, durable) so chat/Dewey/ai/controlpanel
  are reachable over the tailnet (incl. on the exit node). See `specs/remote-ops-access/`.
- SSH to the Beelink: on-disk key `~/.ssh/beelink-ai` (`-o IdentitiesOnly=yes`) when the
  1Password SSH agent is locked.

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

## Commits today

**beelink-ansible:**
- `cec8440` inventory: address beelink-ai over the tailnet (ansible_host)
- `546bcf4` inventory: use beelink-ai MagicDNS name
- `b2e8c78` dewey: gemma3-27b answer model + BYPASS_MODEL_ACCESS_CONTROL (interim wedge fix)
- `071717d` dewey: Qwen3.6-35B-A3B answer model (think:false) + pre-warm both models
- `83763e9` dewey: source-evaluation + AI-answer-skepticism prompt tuning
- `e278ba9` dewey: retrieval relevance (keep qualifiers, roman numerals, best-result picker)
- `faa68e8` dewey: query planning (decompose multi-part prompts)

**pi-cluster (origin/main):**
- `29f4fb6` docs(remote-ops): off-net gap + break-glass; OQ1 resolved (Phase 3)
- `528d633` docs(research): §15 model-landscape triage
- `47d1fba` feat(tailscale): advertise 192.168.1.70/32 (Phase 2)
