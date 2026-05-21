# Session Recap — 2026-05-21 (Ops Pipeline + Q8 Coder + Model Comparison)

This recap covers a single session with three tightly coupled chapters: building the cluster ops agent pipeline, resolving the OLLAMA_CONTEXT_LENGTH crisis that blocked running large models, and a head-to-head benchmark of three model configurations — the centerpiece result that validates the two-tier model strategy going forward.

---

## What Was Built

### Ops Pipeline — Isolated Cluster Operator (Beelink)

A second Pipelines-sidecar instance (`pipelines-ops`) was added to the Beelink Compose stack, isolated from Dewey. The ops pipeline is not visible on the kids' surface; it is its own OWUI entry point intended for cluster operations from the `chat.lab.mtgibbs.dev` (adults) instance.

**Key characteristics:**

- Uses an mcp-homelab **29-tool readonly allowlist** — the same MCP homelab server that backs Claude Code, but constrained to read-only operations so the pipeline cannot mutate cluster state
- Includes a **text-format tool-call fallback parser**: qwen3-series models occasionally emit `<function=…>` as plain text rather than as structured `tool_calls` JSON (the dual-emit quirk first observed in Dewey). The fallback parser catches this and executes the call anyway, preventing silent tool-call drops in long agentic loops
- File: `beelink-ansible/files/ops-pipeline.py`

The isolation design follows the same pattern as Dewey: each surface gets its own Pipelines pipe, its own OWUI instance, and its own scoped virtual key. The ops pipeline uses `hot-coder` (see below) as its backend model.

---

### CONTEXT_LENGTH Crisis + Fix (`OLLAMA_CONTEXT_LENGTH=32768`)

The first attempt to run Qwen3-Coder-Next Q8 via llama-server failed to reproduce in Ollama 0.17.7 — not because llama-server was wrong, but because models were loading at their native context windows. Qwen3-Coder-Next advertises a 256K context; at that context length the KV cache for a 80B model balloons to ~71 GB. On the Beelink's 96 GB iGPU budget, this consumes most of available VRAM before any activations are computed. With multiple models or concurrent requests, Ollama was wedging.

**Fix:** set `OLLAMA_CONTEXT_LENGTH=32768` globally. This caps the KV cache at 32K tokens per loaded model regardless of what the model's native context claims.

32K is appropriate for the cluster ops use case (tool-calling loops, not book summarization). The fix is applied in `docker-compose.yml` via the Ansible playbook and is now part of the production Ollama env config.

---

### llama-server for Qwen3-Coder-Next Q8

Ollama 0.17.7 cannot run Qwen3-Coder-Next Q8 for two independent reasons:

1. It refuses sharded GGUF files (upstream issue ollama#5245 — not fixed in 0.17.7)
2. It does not support the hybrid attention architecture used by the Coder-Next series

The solution is to run `llama-server` directly: `ghcr.io/ggml-org/llama.cpp:server-vulkan`, passing `--jinja` for native OpenAI-compatible tool calling. llama-server loads the sharded GGUF cleanly and calls tools correctly. The Q8 model is ~85 GB across shards, sourced from unsloth's GGUF release.

llama-server is profile-gated to `work` mode in the Compose stack. It does not run alongside Ollama; it is the sole GPU tenant when active.

---

### `aimode` Toggle + `hot-coder` / `hot-reasoner` LiteLLM Aliases

A shell script `/usr/local/bin/aimode` on the Beelink manages the two operating modes:

| Mode | What Runs | GPU Tenant |
|---|---|---|
| `family` (default) | Ollama multi-model stack + all five production models | Shared; Dewey pre-warmed |
| `work` | llama-server with Qwen3-Coder-Next Q8 only | Sole tenant (~85 GB) |

`aimode work` stops Ollama, evicts all loaded models, then starts llama-server with the Q8 model. `aimode family` reverses the process and re-warms Dewey's model. `aimode status` reports current state.

**`hot-coder` and `hot-reasoner`** are LiteLLM DB-backed model aliases. They are the single runtime-swappable knobs:

- In `family` mode: `hot-coder` → `qwen3-coder:30b`
- In `work` mode: `hot-coder` → Qwen3-Coder-Next Q8 (via llama-server)

Any downstream consumer that routes through `hot-coder` automatically gets the right model for the current mode without reconfiguration. The ops pipeline and coding tools both route through `hot-coder`.

---

### `local-llm-mcp` Coding Tools Rewired + IUA Fix (v0.1.1)

`local_explain_diff` and `local_explain_command` were previously hard-coded to `qwen3-coder:30b`. Both were updated to route through `hot-coder` instead, so they automatically benefit from Q8 when work mode is active.

Released as `local-llm-mcp` v0.1.1.

**IUA fix (important):** both `local-llm-mcp` and `kiwix-mcp` were scaffolded without an `ImageUpdateAutomation` resource. Flux's image scanner was detecting new image tags but never writing them back to the manifests — image bumps were silently not deploying. An `ImageUpdateAutomation` was added to both Kustomizations. This is now a checklist item for any future MCP server scaffold.

---

## Hardware Framing (Why Models Were Chosen)

The Beelink GTR9-class machine has 128 GB unified memory, BIOS-split to **96 GB VRAM / 32 GB system** for the AMD Radeon 8060S (Strix Halo). The interconnect is memory-bandwidth-bound at approximately **215 GB/s**.

The architectural consequence: **model weights are read from unified memory on every token generation**. Tokens per second is approximately `bandwidth / bytes_of_active_weights_per_token`. This means:

- Dense 72B Q4 (~47 GB weights, all active per token) → ~5 tok/s — bandwidth-limited even at Q4
- MoE 80B-A3B Q8 (80B parameters, ~3B active per token, Q8 = 8 bits/weight) → bandwidth cost is for the active expert set, not the full parameter count
- MoE 30B-A3B Q4 (30B parameters, ~3B active per token, Q4 = 4 bits/weight) → lowest bandwidth demand, highest throughput

This drives the entire model tier strategy: **MoE with low active parameters, not dense large models**.

---

## The Comparison — Methodology

Three models were evaluated. All measurements are warm-cache (model already loaded in VRAM).

| Model | Architecture | Quantization | Backend |
|---|---|---|---|
| `qwen3-coder:30b` | MoE 30B-A3B | Q4 | Ollama / family mode |
| Qwen3-Coder-Next Q8 | MoE 80B-A3B | Q8 | llama-server / work mode |
| `qwen3.5:35b` | MoE 35B-A3B | Q4 | Ollama / family mode |

Note: Q8 is sole-tenant in work mode; 30B and 35B share GPU in family mode. Comparisons between Q8 and the others required an `aimode` flip between runs.

**Phase 1 — Raw coding quality (5 prompts via LiteLLM, max_tokens 600):**
1. Debug a buggy `second_largest` function
2. Write `merge_intervals`
3. Explain a password regex
4. Refactor `avg` to be robust
5. List-vs-set membership tradeoff

**Phase 2 — Agentic ops (2 scenarios via the Ops pipeline):**
1. "Is anything wrong with the cluster?" — open-ended diagnostic
2. "Is the download stack stuck? Fix it." — targeted, multi-step investigation

---

## Results — Speed

| Model | Speed (warm, tok/s) |
|---|---|
| `qwen3-coder:30b` (30B-A3B, Q4) | ~62 |
| Qwen3-Coder-Next Q8 (80B-A3B, Q8) | ~40 |
| `qwen3.5:35b` (35B-A3B, Q4) | ~40 |

The Q4 30B is approximately 1.5x faster than Q8. The reason is bandwidth arithmetic: Q8 weights are 2x the bytes per parameter vs Q4. Even though the active parameter count is similar (both are ~3B active per token), the per-token memory reads for Q8 are roughly twice as expensive on the 215 GB/s bus. The 35B at Q4 happens to land at the same throughput as Q8 despite the different parameter count — the numbers converge at this bandwidth.

---

## Results — Raw Coding Quality (Phase 1)

All three models were correct on all five prompts. Differences were at the margin:

| Dimension | Q8 (80B-A3B) | 30B (30B-A3B) | 35B (35B-A3B) |
|---|---|---|---|
| Correctness | All 5 correct | All 5 correct | All 5 correct |
| Edge cases | Best — caught `<2 unique elements` case explicitly | Correct, practical (added benchmark example) | Correct but thorough to a fault |
| Output quality | Cleanest; no reasoning leaks | Minor docstring self-contradiction on refactor prompt | Leaked thinking verbatim on regex prompt |
| Speed advantage | None (slowest tier) | Fastest by 1.5x | Same speed as Q8 |

The 35B's thinking-mode leak (raw internal monologue appearing in the response on the regex prompt) is a notable quality regression — the user sees the model's scratch work, which is not appropriate for most surfaces. The 30B's docstring inconsistency is minor. Q8 produced the most polished output on all five prompts, but the gap between Q8 and 30B on raw coding tasks is small.

**Takeaway for Phase 1:** the 30B is approximately 95% of Q8's raw coding quality at 1.5x the throughput. The 35B has no speed advantage over Q8 and leaks its reasoning. The 35B slot in the production model set should be reconsidered for work-mode use cases.

---

## Results — Agentic Ops Quality (Phase 2)

This is where the models separated meaningfully.

**Scenario: "Download stack stuck? Fix it."**

- **Q8**: Diagnosed the paused state, returned specific `curl` commands to resume the SABnzbd queue, listed likely root causes, and offered to pull logs for deeper investigation. The response was immediately actionable — a human operator could copy-paste the commands.
- **30B**: Returned generic advice ("check the queue status, resume paused downloads"). No specific commands, no root-cause enumeration, no offer to dig further. Technically correct but not operationally useful.

**Scenario: "Is anything wrong?"**

- Both models made real tool calls; neither hallucinated tool responses.
- Q8 produced a more comprehensive rollup: checked the SABnzbd queue state, certificate expiry, and overall health in a single coherent report.
- 30B zeroed in on a single pod anomaly and stopped, missing the broader picture.

The gap on multi-step, tool-driven, agentic work is meaningful and consistent across both scenarios. Q8 maintains context across tool-call iterations, synthesizes information from multiple tool responses into coherent actionable output, and knows when to keep going. The 30B tends to satisfy after the first reasonable answer.

---

## Verdict — Two-Tier Strategy Validated by Data

The benchmark result supports the two-tier architecture that was the design intent before the session started. The data now backs what was previously a hypothesis.

**Family mode / daily driver → `qwen3-coder:30b`**

Fast (~62 tok/s), ~95% of Q8's raw coding quality, keeps Dewey pre-warmed in VRAM, no context-length tension. For routine coding assistance, explanation, and summarization tasks, the 30B is the right model. There is no reason to pay the Q8 cost for work that 30B handles correctly.

**`aimode work` → Qwen3-Coder-Next Q8**

For agentic ops loops, gnarly multi-step debugging, and complex investigations where thoroughness and recovery matter more than raw latency, Q8 is meaningfully better. The `aimode work` toggle summons Q8 as the sole GPU tenant. The `hot-coder` alias makes the swap transparent to downstream consumers.

**Q8 is a deep-work upgrade, not a blanket one.** The toggle-based design is correct: cheap-fast 30B by default, summon Q8 when the problem is hard enough to warrant it.

---

## Commits

### pi-cluster repo

| Hash | Subject |
|---|---|
| `e6260fe` | docs: architectural snapshot of MCP layer + Postgres |
| `a3b4a2b` | docs(beelink): Phase 0.7 Ollama tuning + Phase 0.8 pipelines/kids preview |
| `8f3aa82` | feat(dewey): add dewey.lab.mtgibbs.dev DNS |
| `a16c916` | docs: snapshot Ollama tuning + Dewey kid-facing surface |
| `ab5e494` | docs: Q2 2026 AI stack roadmap |

### beelink-ansible repo

| Hash | Subject |
|---|---|
| (session) | feat(50-ai-stack): add OLLAMA_CONTEXT_LENGTH=32768 to prevent KV cache blowout |
| (session) | feat(ops-pipeline): add isolated cluster ops pipeline with 29-tool readonly allowlist |
| (session) | feat(aimode): add work/family toggle + llama-server profile for Q8 |

### local-llm-mcp repo

| Tag | Subject |
|---|---|
| `v0.1.1` | fix: rewire coding tools to hot-coder alias; add missing ImageUpdateAutomation |

---

## Key Technical Decisions

### `OLLAMA_CONTEXT_LENGTH=32768` is non-negotiable at this memory budget

Without this cap, each loaded model reserves KV cache for its native context window. A 256K-context 80B model reserves ~71 GB for KV cache alone — most of the 96 GB VRAM budget before a single activation is computed. With `OLLAMA_MAX_LOADED_MODELS=5` set from the Phase 0.7 tuning session, an uncapped context makes the stack impossible. 32K is sufficient for all current use cases and must be treated as a permanent production setting, not a temporary workaround.

### llama-server for sharded or non-standard-arch models

When Ollama refuses a model (sharded GGUF or unsupported architecture), the answer is `llama-server` directly via the `ghcr.io/ggml-org/llama.cpp:server-vulkan` image. The `--jinja` flag provides native OpenAI-compatible tool calling. This pattern is now proven; future models with the same constraints should follow it rather than attempting workarounds inside Ollama.

### IUA is required for every MCP server Kustomization

Both `local-llm-mcp` and `kiwix-mcp` were deployed without `ImageUpdateAutomation`. The image scanner was detecting new tags but never reconciling them to the manifests. Any future MCP server scaffold must include an IUA alongside the ImageRepository and ImagePolicy. This is now a checklist item.

### The text-format tool-call fallback parser is load-bearing

Qwen3-series models in long agentic loops occasionally emit a second tool call as `<function=…>` plain text rather than as a structured `tool_calls` JSON object. Without the fallback parser, that call is silently dropped and the loop terminates early with an incomplete result. The parser must be included in any pipeline that runs qwen3-family models in a tool-calling loop.

---

## Verified End State

| Component | State | Notes |
|---|---|---|
| `OLLAMA_CONTEXT_LENGTH` | `32768` | Permanent; in docker-compose.yml via Ansible |
| llama-server | Profile-gated to `work` mode | `ghcr.io/ggml-org/llama.cpp:server-vulkan`, `--jinja` |
| Qwen3-Coder-Next Q8 | Loads cleanly via llama-server | Ollama 0.17.7 cannot run it |
| `aimode` script | `/usr/local/bin/aimode` on Beelink | `work` / `family` / `status` |
| `hot-coder` alias | LiteLLM DB alias | `family` → 30B, `work` → Q8 |
| Ops pipeline | Running in `pipelines-ops` sidecar | 29-tool readonly allowlist + fallback parser |
| `local-llm-mcp` v0.1.1 | Deployed | Coding tools route through `hot-coder`; IUA added |
| `kiwix-mcp` | IUA added | Was missing; image bumps now deploy |
| Benchmark | Complete | All data above is measured, not estimated |

---

## What Remains

- [ ] Open WebUI (adults) `OPENAI_API_KEY` is still the LiteLLM master key — migrate to a scoped virtual key
- [ ] Beelink observability: node_exporter + AMD GPU exporter + cAdvisor → Prometheus on Pi cluster
- [ ] Evaluate whether `qwen3.5:35b` remains justified in the production model set — it has no speed advantage over Q8 and leaked reasoning in Phase 1 testing; candidate for replacement with a model that fills a distinct niche
- [ ] VRAM monitoring under real concurrent load (five loaded models + KV cache caps) — validate that the `OLLAMA_CONTEXT_LENGTH` cap is sufficient
- [ ] Phase 1: Authelia SSO, Open WebUI master-key → virtual-key migration, Beelink observability dashboards
