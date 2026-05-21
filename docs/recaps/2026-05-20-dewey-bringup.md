# Session Recap — 2026-05-20 (Ollama Tuning + Dewey)

This recap covers the two chunks of work that followed the Postgres + MCP servers session (documented in `docs/recaps/2026-05-20-mcp-servers-bringup.md`). Both chunks are about the Beelink AI stack: first, preparing Ollama for two Open WebUI instances sharing one backend; second, building Dewey — the kid-facing chat surface with offline reference grounding.

---

## What Was Built

### Ollama Tuning for Multi-User Concurrency (Phase 0.7)

The prompt was the right question: "If two Open WebUIs hit the same Ollama backend, what happens to model loading?"

Default Ollama behavior: one model loaded at a time, one concurrent request per model. In a family setting where adults use CARL/chat and kids hit a dedicated surface, that means LRU eviction every time someone switches models, and head-of-line blocking whenever two people hit the same model simultaneously.

Changes applied to `/opt/ai-stack/docker-compose.yml` via `playbooks/50-ai-stack.yml`:

| Setting | Old | New | Why |
|---|---|---|---|
| `OLLAMA_MAX_LOADED_MODELS` | default (1-3) | `5` | All five production models stay resident; no eviction churn when different users hit different models |
| `OLLAMA_NUM_PARALLEL` | `1` | `2` | Two concurrent requests on the same model. Two kids on the same model no longer head-of-line block each other. Throughput per stream is halved, but neither request waits |
| `OLLAMA_KEEP_ALIVE` | `-1` | `-1` | Unchanged — loaded models never auto-unload |

A pre-warm Ansible task was added to the post-deploy play: after `docker compose up`, it hits `POST /api/generate` with an empty prompt and `keep_alive=-1` for `gemma3:27b` (via `docker exec open-webui curl`, since the ollama container doesn't have curl). Verified working: `done_reason: "load"` in the response. The kids' model is now in VRAM before the first request.

**VRAM note:** `gemma3:27b` at the default 131K context window consumes ~42 GB VRAM — not just the 17 GB on-disk model weight. If eviction starts appearing under real load, the next lever is `OLLAMA_CONTEXT_LENGTH` to cap per-model context, or per-model `num_ctx` overrides via LiteLLM. Not done; revisit when metrics show contention.

---

### Dewey — Kid-Facing Chat with Offline Reference Grounding (Phase 0.8)

#### Naming

The user wanted a separate space for the kids to learn safely, distinct from the adults' Open WebUI. The label "kids" was rejected as degrading. The existing CARL (Canvas Assignment Reminder Liaison) already serves the kids' school workflow; the new surface needed a sibling "D" name that fit the purpose. Settled on **Dewey** — the library reference angle matches the kiwix tool layer underneath it. Lives at `https://dewey.lab.mtgibbs.dev`.

#### Stack Additions on the Beelink

Two new services added to the Compose stack:

**`pipelines` sidecar** — `ghcr.io/open-webui/pipelines:main`. Exposes an OpenAI-compatible API on `:9099`. Mounts `/srv/pipelines-data/` (host) as `/app/pipelines` (container). This is where the Dewey pipeline file lives.

**`open-webui-dewey`** — a second Open WebUI instance with its own SQLite at `/srv/dewey-data/`, its own auth, and `OPENAI_API_BASE_URL=http://pipelines:9099`. Dewey ONLY talks to Pipelines. `ENABLE_OLLAMA_API=false`. `WEBUI_NAME=Dewey`.

Caddy block added for `dewey.lab.mtgibbs.dev` — Let's Encrypt cert issued cleanly via DNS-01. Pi-hole DNS override committed via GitOps (`clusters/pi-k3s/pihole/pihole-custom-dns.yaml`, commit `8f3aa82`).

**Three secrets in 1Password** (`op://pi-cluster/dewey/...`):
- `litellm-key` — LiteLLM virtual key scoped to the Dewey model only
- `password` — bearer between OWUI Dewey and the Pipelines sidecar
- Pipeline → kiwix-mcp calls reuse the existing `op://pi-cluster/kiwix-mcp/password`

#### The Pipeline (`files/dewey-pipeline.py`)

A single "pipe" Python file that registers as the model "Dewey" in OWUI's model dropdown. What it does:

1. Takes the user message
2. Appends the Dewey system prompt
3. Calls LiteLLM with 3 hardcoded tool definitions (`kiwix_search`, `kiwix_get_article`, `kiwix_suggest`)
4. If the model emits `tool_calls`, executes them against `https://kiwix-mcp.lab.mtgibbs.dev/mcp` using the kiwix-mcp bearer
5. Loops up to `MAX_TOOL_ITERATIONS` times, feeding results back into the context
6. Falls back to `reasoning_content` if `content` is empty (qwen3 thinking-mode safety net)

Starts each turn with `/no_think` to disable qwen3's extended thinking mode — without this, the model burns tokens on internal monologue before any content appears, which compounds badly in tool-call loops.

---

## Architectural Pivots During the Build

### Pivot 1: Gemma3 → Qwen3.5-9b

The first end-to-end smoke test failed. Error: `"registry.ollama.ai/library/gemma3:27b does not support tools"`. Ollama's gemma3 template does not declare tool support; LiteLLM correctly refuses to send tool definitions to it. No workaround exists within LiteLLM — this is a model template limitation, not a config issue.

The replacement model is `qwen3.5:9b`. It was already in the production model set (Tier 2 / triage model) and supports tool calls correctly via the qwen3 template.

The safety tradeoff was discussed honestly: qwen3 is less aggressively aligned than gemma3. The conclusion was that the actual risk surface is unchanged — the model's job is summarizing kiwix source material it just fetched, not generating free-form content. The system prompt and kiwix grounding are the safety layers, not the base model's RLHF alignment.

The Dewey LiteLLM virtual key was updated to scope to `qwen3.5:9b` only.

**VRAM implication:** pre-warming was updated from `gemma3:27b` to `qwen3.5:9b`. The pre-warm call in the Ansible playbook was corrected to match.

### Pivot 2: The Pedagogical System Prompt

The user clarified what Dewey should be: "a safe space for them to learn anything... I don't want them to see a 'glossed over' history. History is messy, often sad, and they need to see that... As long as the models can't infer crazy conspiracy theories but always point them to learning then we're good."

The system prompt was written to:
- Name Ronin (14) and Rory (11) explicitly, so the model can adapt vocabulary and depth to who's asking
- Mandate kiwix tool grounding for any factual claim before responding
- Tell the truth about history — don't sanitize, don't moralize, don't smooth over what happened
- Distinguish actually-contested history from fringe-loud-but-wrong claims (anti-conspiracy framing)
- Frame "ask your dad" as group learning rather than refusal
- Match reading level to the likely questioner (Rory = simpler vocabulary; Ronin = can handle depth and nuance)

---

## Key Architectural Decisions

### Pipelines as an Isolation Layer

Dewey talks to Pipelines. Pipelines talks to LiteLLM. Dewey cannot reach LiteLLM or Ollama directly.

This is a deliberate isolation boundary. Changing Dewey's model, tool surface, system prompt, or safety behavior is one Python file edit — no config cascade across Caddy, LiteLLM, or OWUI. Any future kid-facing or public-facing surface built on this stack gets the same pattern: its own Pipelines pipe, its own OWUI instance, its own scoped virtual key.

### System Prompt as the Safety Layer

The kid-tailored guardrails live in the pipeline's system prompt — code owned and iterable by the user — rather than in base-model alignment, which is outside the user's control. The kiwix grounding is the second half: the model's primary job is summarizing source material it just fetched, not generating free-form content from training data. A model that always has to cite a source before speaking has a much smaller hallucination surface than one that's just talking.

---

## Verified End State

End-to-end test: asked Dewey "What city does the Tigris river run through?"

1. Pipeline received the message
2. First LLM turn emitted `kiwix_search(query="Tigris river")` as a proper JSON `tool_calls` object
3. Pipeline executed the search against `https://kiwix-mcp.lab.mtgibbs.dev/mcp` via HTTPS with bearer auth
4. Second LLM turn returned a grounded answer naming Mosul, Tikrit, Samarra, Baghdad, Nasiriyah, Kufa, plus noting origins in Turkey/Syria/Iran

Known quirk: qwen3 also emitted a text-format `<tool_call>` block in the content body for a follow-up `kiwix_get_article` — this is qwen3-specific behavior where it tries to emit a second tool call as text rather than as a structured `tool_calls` object. Not blocking; the answer is correct and sourced from the first loop iteration. Noted for a future pipeline iteration.

| Component | State |
|---|---|
| Pipelines sidecar | Running at `:9099` on Beelink |
| open-webui-dewey | Running at `https://dewey.lab.mtgibbs.dev` |
| dewey-pipeline.py | Registered in Pipelines; model "Dewey" visible in OWUI dropdown |
| kiwix tool loop | Verified end-to-end with real query |
| TLS cert | Issued via DNS-01; clean |
| Pi-hole DNS | `dewey.lab.mtgibbs.dev` → `192.168.1.70` committed |
| 1Password secrets | `dewey/litellm-key`, `dewey/password` created |
| LiteLLM virtual key | Scoped to `qwen3.5:9b`; Dewey cannot reach other models |
| Pre-warm | Updated to `qwen3.5:9b`; verified `done_reason: load` |

---

## Commits

### pi-cluster repo (pushed)

| Hash | Subject |
|---|---|
| `8f3aa82` | feat(dewey): add dewey.lab.mtgibbs.dev DNS |
| `a3b4a2b` | docs(beelink): Phase 0.7 Ollama tuning + Phase 0.8 pipelines/kids preview |

### beelink-ansible repo (pushed)

| Hash | Subject |
|---|---|
| `2886d5f` | feat(50-ai-stack): tune Ollama for multi-user + pre-warm gemma3 |
| `677ca5c` | feat(dewey): add Pipelines sidecar + Open WebUI Dewey instance |

Note: commit `2886d5f` references gemma3 in the message but the pre-warm was subsequently corrected to `qwen3.5:9b` after the model pivot.

---

## What Remains

- [ ] Open WebUI (adults, `chat.lab.mtgibbs.dev`) `OPENAI_API_KEY` is still the LiteLLM master key — migrate to a scoped virtual key
- [ ] CARL's Ollama URL still points at the in-cluster `ollama` namespace — evaluate migrating to the Beelink LiteLLM endpoint so all inference goes through one gateway
- [ ] qwen3 dual-emit quirk: second tool call emitted as text `<tool_call>` block rather than structured `tool_calls` — handle this in the pipeline loop (parse and execute text-format tool calls)
- [ ] Beelink observability: node_exporter + AMD GPU exporter + cAdvisor → scraped by Prometheus on Pi cluster (deferred from Phase 0)
- [ ] VRAM monitoring: `OLLAMA_MAX_LOADED_MODELS=5` is optimistic — verify in practice that five models fit simultaneously, or cap context length if contention appears
