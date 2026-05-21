# Session Recap — 2026-05-20 (MCP Servers + Postgres)

This session extended the AI stack work documented in `docs/recaps/2026-05-20-beelink-ai-bringup.md`. That recap covers Phase 0 (model inference layer) and Phase 0.5 (Caddy + Open WebUI). This recap covers what was built immediately after: Postgres added to the Beelink Compose stack, and two new MCP servers deployed to the Pi cluster.

---

## What Was Built

### Postgres Added to Beelink Compose Stack

LiteLLM was running without a backing database, which blocked `/key/generate` — the endpoint for minting per-client virtual keys. Added `postgres:16-alpine` as a new service in the Compose stack at `/opt/ai-stack/`.

Changes:
- `DATABASE_URL=postgresql://litellm:...@postgres:5432/litellm` and `STORE_MODEL_IN_DB=True` added to LiteLLM env
- New `litellm_db` named Docker volume holds the database
- Postgres password generated locally with `openssl rand -hex 32`, stored in 1Password (`litellm-postgres/password` in the `pi-cluster` vault)

This unblocked per-client virtual keys with model allowlists, TPM/RPM limits, and request logging — the security-posture item the architecture doc has been promising since Phase 0.

### `local-llm-mcp` — Token-Saver MCP for Claude Code Sessions

**Source repo:** `github.com/mtgibbs/local-llm-mcp` (new public repo)

A TypeScript MCP server built on the same scaffold as `pi-cluster-mcp` (Express + `@modelcontextprotocol/sdk`, Streamable HTTP transport, bearer auth on `/mcp`, `/health` open). The purpose is to offload bulk summarization, classification, and explanation tasks from Claude Code sessions to local models, avoiding cloud token burn for high-volume rote work.

**Tools exposed (6):**
- `local_summarize` — routes to `qwen3.5:9b`
- `local_classify` — routes to `qwen3.5:9b`
- `local_extract_structured` — routes to `qwen3.5:9b`
- `local_explain_diff` — routes to `qwen3-coder:30b`
- `local_explain_command` — routes to `qwen3-coder:30b`
- `local_chat` — routes to `qwen3.5:35b`

Each tool calls LiteLLM via the OpenAI SDK with the model baked in. Callers do not choose the model; the tool encodes the routing decision.

**CI/Release pipeline:**
- `ci.yaml`: typechecks + builds on PR/push
- `release.yaml`: builds multi-arch (amd64 + arm64) and pushes `ghcr.io/mtgibbs/local-llm-mcp:<version>` on push to main

**Cluster deploy (`clusters/pi-k3s/local-llm-mcp/`):**
- Namespace + Deployment + Service + Ingress + ExternalSecret + image-automation
- Registered as entry #25 in `clusters/pi-k3s/flux-system/infrastructure.yaml`
- Bearer token and LiteLLM virtual key sourced from 1Password `local-llm-mcp` item (two fields: `password`, `litellm-key`)
- Nginx ingress at `https://local-llm-mcp.lab.mtgibbs.dev/mcp` with 600s proxy timeouts (required for Streamable HTTP transport)

**LiteLLM virtual key scope:**
- Allowlist: `qwen3.5:9b`, `qwen3.5:35b`, `qwen3-coder:30b`, `gemma3:27b`, `nomic-embed`
- Limits: `tpm_limit: 100000`, `rpm_limit: 60`
- Verified end-to-end: tool call → MCP server → LiteLLM virtual key → Ollama → GPU → response
- Verified deny path: request for a model outside the allowlist is rejected by LiteLLM

**Doc:** `docs/local-llm-mcp.md` — wiring instructions for `~/.claude.json` and per-project `.mcp.json`

---

### `kiwix-mcp` — Offline Reference Library MCP

**Source repo:** `github.com/mtgibbs/kiwix-mcp` (new public repo)

Same scaffold pattern as `local-llm-mcp`. Instead of the OpenAI client, uses `fast-xml-parser` (OPDS catalog + RSS search results) and `turndown` (HTML → markdown). Wraps the in-cluster `kiwix-serve` instance that has been running since Phase 1 (see `docs/recaps/2026-05-08-kiwix-phase1.md`).

**Tools exposed (5):**
- `kiwix_list_zims` — returns all 7 ZIMs with metadata
- `kiwix_search` — full-text search across a named ZIM
- `kiwix_get_article` — fetches a single article and converts to markdown
- `kiwix_suggest` — autocomplete suggestions for a ZIM
- `kiwix_search_books` — convenience wrapper scoped to Gutenberg only

**Backend URL:** `http://kiwix.kiwix.svc.cluster.local` — in-cluster service DNS, not the public ingress. This avoids a TLS handshake and public ingress round-trip on every query. All kiwix article content is internal-only; there is no reason to exit the cluster.

**Catalog cache (1h TTL):** maps friendly short names (`wikipedia`, `gutenberg`, `wiktionary`) and aliases (`books`, `dictionary`, `quotes`) to the current dated content paths (`wikipedia_en_all_nopic_2026-03`). Callers use short names; the MCP refreshes mappings from `/catalog/v2/entries` automatically on expiry. This insulates tool callers from the dated-filename format that kiwix-serve uses internally.

**Cluster deploy (`clusters/pi-k3s/kiwix-mcp/`):**
- Registered as entry #26 in `infrastructure.yaml`
- Depends on the existing `kiwix` Flux Kustomization so first-time bring-up serializes correctly
- Bearer from 1Password `kiwix-mcp/password`
- Ingress at `https://kiwix-mcp.lab.mtgibbs.dev/mcp`

**Verified end-to-end:** `kiwix_list_zims` returns all 7 ZIMs through the deployed pod via the public ingress.

**Doc:** `docs/kiwix-mcp.md` — same shape as `local-llm-mcp.md`

---

## Commits

### pi-cluster repo (main, pushed)

| Hash | Subject |
|---|---|
| `93363bb` | feat(beelink): add chat.lab.mtgibbs.dev DNS for Open WebUI |
| `10fcf5b` | feat(local-llm-mcp): deploy MCP delegation server to cluster |
| `a3f5c57` | docs: local-llm-mcp wiring instructions |
| `1ed9f7e` | feat(kiwix-mcp): deploy MCP server exposing home Kiwix library |
| `5dbb5bd` | docs: kiwix-mcp wiring + ops playbook |

### beelink-ansible repo

| Hash | Subject |
|---|---|
| `1d18f37` | feat(50-ai-stack): add Caddy + Open WebUI, rotate LiteLLM master key |
| (see repo) | feat(50-ai-stack): add Postgres to Compose stack |

### New public GitHub repos

- `mtgibbs/local-llm-mcp`
- `mtgibbs/kiwix-mcp`

---

## Architectural Shape That Emerged

The Beelink/Pi split that the architecture doc described as a plan is now actually load-bearing:

```
┌──────────────────────────────────┐     HTTPS (virtual key)
│  Beelink GTR9 Pro                │◄────────────────────────────────────┐
│  (inference plane)               │                                     │
│                                  │                                     │
│  ┌──────────┐  ┌───────────────┐ │     ┌─────────────────────────────┐ │
│  │  Ollama  │  │   LiteLLM     │ │     │  Pi K3s Cluster             │ │
│  │  Vulkan  │  │   + Postgres  │ │     │  (orchestration plane)      │ │
│  │  RADV    │◄─│   (virtual    │ │     │                             │ │
│  │  GFX1151 │  │    keys)      │ │     │  local-llm-mcp  ──────────► │─┘
│  └──────────┘  └───────────────┘ │     │  kiwix-mcp      ──────────► │─┘
│  ┌──────────┐  ┌───────────────┐ │     │  mcp-homelab    (cluster)   │
│  │  Open    │  │   Caddy TLS   │ │     │                             │
│  │  WebUI   │◄─│   DNS-01      │ │     │  kiwix-serve ◄── kiwix-mcp  │
│  └──────────┘  └───────────────┘ │     │  (in-cluster svc path)      │
└──────────────────────────────────┘     └─────────────────────────────┘
```

Contract: Pi cluster MCP servers call `https://ai.lab.mtgibbs.dev/v1/` with per-client LiteLLM virtual keys. MCP servers never call Ollama directly. `kiwix-mcp` calls `kiwix-serve` via in-cluster DNS, not through the public ingress.

---

## Key Decisions and Surprises

### GHCR package visibility must be flipped manually after first push

When a new repo pushes to GHCR for the first time, the package is created as private by default — even if the repo is public. The pod pull fails with `ImagePullBackOff` immediately. The fix:

```bash
gh auth refresh -s write:packages
gh api --method PATCH \
  /user/packages/container/local-llm-mcp \
  -f visibility=public
```

New MCP repos that follow this scaffold will hit the same friction. Run this step once after the first CI push before deploying to the cluster. No `imagePullSecret` is needed once the package is public.

### In-cluster service paths for MCP backends

`kiwix-mcp` calls `http://kiwix.kiwix.svc.cluster.local` rather than `https://kiwix.lab.mtgibbs.dev`. This saves a TLS handshake, an ingress hop, and a Pi-hole DNS lookup on every query. The same pattern should apply to any future MCP server that wraps another cluster service — always prefer the in-cluster DNS name over the public ingress for backend calls.

### No `imagePullSecret` needed for public GHCR packages

Pods pull `ghcr.io/mtgibbs/*` without any imagePullSecret as long as the package visibility is public. This was surprising mid-session but is correct — GHCR allows unauthenticated pulls for public packages. Keep package visibility public for all cluster-deployed MCP images.

### Postgres unblocks the security posture the architecture planned

LiteLLM without a database cannot store virtual keys — `/key/generate` returns a 500. With Postgres, virtual keys are stored and enforced per-request. The deny path (request rejected for an out-of-allowlist model) was verified manually. The remaining gap: Open WebUI's `OPENAI_API_KEY` is still the LiteLLM master key, not a scoped virtual key. Flag for follow-up; do not fix without also scoping the key's model allowlist to the models appropriate for the kids' UI.

---

## Verified End State

| Component | State | Notes |
|---|---|---|
| Postgres (Beelink) | Running | `litellm_db` named volume; password in 1Password |
| LiteLLM virtual keys | Enabled | DB-backed; per-client allowlists enforced |
| `local-llm-mcp` | Deployed + verified | 6 tools, ingress live, virtual key scoped |
| `kiwix-mcp` | Deployed + verified | 5 tools, ingress live, kiwix_list_zims tested |
| GHCR images | Public | Both repos; no imagePullSecret required |
| CI/CD | Active | Multi-arch builds on push to main for both repos |
| Flux image automation | Active | Both deployments tracked for auto-bump |

---

## What Remains

- [ ] Open WebUI `OPENAI_API_KEY` should become a scoped virtual key, not the master key — defer until kids' UI scope is defined so the allowlist can be set correctly at the same time
- [ ] Beelink observability: node_exporter + AMD GPU exporter + cAdvisor → scraped by Prometheus on Pi cluster
- [ ] `docs/local-llm-mcp.md` and `docs/kiwix-mcp.md` exist; register these in `CLAUDE.md` Service Index if MCP servers become first-class troubleshooting targets
- [ ] Kids' Open WebUI at `kids.lab.mtgibbs.dev` (Phase 1, separate auth, model locked to `gemma3:27b`)
- [ ] n8n / signal-cli / Home Assistant MCP servers (Phases 3–5 in `docs/beelink-ai-stack.md`)
