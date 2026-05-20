# Session Recap — 2026-05-20

Phase 0 (model inference layer) and Phase 0.5 (user-facing layer) of the Beelink AI inference appliance both reached production state in a single session. The Beelink went from partially-Ansibeled hardware to a fully TLS-terminated, externally-accessible, GPU-backed AI serving node with five production models registered.

---

## What Was Completed

### Phase 0 — Model Inference Layer

- `lv-models` LV created: 1 TB ext4 at `/srv/models`. ~950 GB remains unallocated in `ubuntu-vg` for future extension or carving.
- Tailscale installed and joined as `tag:inference` at `100.123.94.31` via a dedicated single-tag OAuth client (`tailscale-beelink-device-auth`). See key surprise #2 below.
- ROCm host tools (`rocminfo`, `rocm-smi-lib`) installed for diagnostics. Not used for inference — see key surprise #1.
- Ollama + LiteLLM Compose stack deployed at `/opt/ai-stack/`, using `ollama/ollama:0.17.7` (standard image, NOT `-rocm`) with `OLLAMA_VULKAN=1`.
- Pi-hole DNS: `ai.lab.mtgibbs.dev` → `192.168.1.70` — committed to `pihole-custom-dns.yaml` via GitOps.

### Phase 0.5 — User-Facing Layer

- Caddy added to the Compose stack. Built locally via a 2-stage Dockerfile (`caddy:2-builder` + xcaddy with the Cloudflare DNS plugin). We do not use community-published Caddy+Cloudflare images — supply-chain hygiene matches the project's threat model.
- Caddy terminates TLS at `:443` for both `ai.lab.mtgibbs.dev` and `chat.lab.mtgibbs.dev` using Cloudflare DNS-01 ACME. Resolvers explicitly set to `1.1.1.1 8.8.8.8` — see key surprise #4.
- Open WebUI deployed behind Caddy at `https://chat.lab.mtgibbs.dev`. SQLite + uploads at `/srv/openwebui`. Pinned to LiteLLM API only (`ENABLE_OLLAMA_API=false`) — this enforces the single-API-contract architectural rule; no path to bypass LiteLLM from the UI.
- LiteLLM moved behind Caddy at `https://ai.lab.mtgibbs.dev`. Raw `:4000` is no longer published externally.
- `LITELLM_MASTER_KEY` rotated from placeholder `sk-litellm-smoke-2026` to a 64-char random hex value stored in 1Password (`litellm-master-key` in `pi-cluster` vault).
- `CLOUDFLARE_API_TOKEN` sourced from `op://pi-cluster/cloudflare/beelink-api-token` — not hardcoded in Compose env.
- Pi-hole DNS: `chat.lab.mtgibbs.dev` → `192.168.1.70` — committed via GitOps.

### Tailscale ACL GitOps

- `tailscale/policy.hujson` established as the source of truth for the Tailscale ACL policy.
- `.github/workflows/tailscale-acl.yml` added: validates on PR, applies on push to main via `gitops-acl-action`.
- Separate OAuth client `gitops-acl-pi-cluster-repo` scoped to `policy_file` only — not the same client used for device auth.

### Production Models

All models pulled and registered in LiteLLM config. All smoke-tested end-to-end via HTTPS over Vulkan.

| Model | Role |
|---|---|
| `qwen3:0.6b` | Kept as smoke-test / fast diagnostic probe |
| `qwen3.5:9b` | Triage — high-volume routing/classification |
| `gemma3:27b` | Kids-facing chat (safety-tuned) |
| `qwen3-coder:30b` | Coding work, OpenCode backend |
| `qwen3.5:35b` | Primary reasoning — n8n, Signal, IoT |
| `nomic-embed-text` | Embeddings / RAG pipelines |

---

## Commits

### pi-cluster repo (main, pushed)

| Hash | Subject |
|---|---|
| `0d71168` | feat(tailscale): GitOps for ACL policy via gitops-acl-action |
| `9e75090` | feat(beelink): add ai.lab.mtgibbs.dev DNS + commit AI stack plan |
| `96358d5` | docs(beelink): Phase 0 complete — record Vulkan workaround |
| `93363bb` | feat(beelink): add chat.lab.mtgibbs.dev DNS for Open WebUI |
| `5242acf` | feat(50-ai-stack): register 5 production models in LiteLLM |

### beelink-ansible repo

| Hash | Subject |
|---|---|
| `f406f4e` | feat: bring Beelink AI inference appliance online (25-lvm-models, 30-tailscale, 40-rocm, 50-ai-stack + site.yml) |
| `1d18f37` | feat(50-ai-stack): add Caddy + Open WebUI, rotate LiteLLM master key |
| (final) | feat(50-ai-stack): register 5 production models in LiteLLM |

---

## Key Technical Surprises

### 1. `ollama/ollama:0.17.7-rocm` is broken on Strix Halo (gfx1151)

The `-rocm` image's ROCm 6.x runtime crashes with an OOM in `hipStreamCreateWithFlags` during ggml-cuda init — even though `rocm-smi` reports 111 GB GPU memory available. This is a ROCm runtime bug specific to the gfx1151 architecture (Strix Halo iGPU), not a memory pressure issue.

**Workaround:** use the standard `ollama/ollama:0.17.7` image with `OLLAMA_VULKAN=1`. The Vulkan/RADV GFX1151 backend initializes cleanly. All six models were smoke-tested end-to-end via Vulkan.

**Prior pessimism proven wrong:** earlier research (and the Phase 0 doc) warned that Vulkan might hang above 30B parameters. In practice, `qwen3.5:35b` (dense, not MoE) served cleanly. The warning appears to have applied to specific quantization configs or older Ollama versions.

**Future path:** when a `-rocm` image ships with ROCm 7.x support for gfx1151, re-evaluate. Until then Vulkan is the production backend. Leave ROCm host tools installed — they remain useful for `rocm-smi` diagnostics even without container-side ROCm.

### 2. Tailscale OAuth multi-tag constraint

When a Tailscale OAuth client has N tags configured, every auth key it mints must include ALL N tags — you cannot mint a key for a subset. This means a shared multi-tag OAuth client cannot produce single-tag device keys.

**Solution:** create one OAuth client per device-tag scope. `tailscale-beelink-device-auth` is scoped to `tag:inference` only, so it mints `tag:inference`-only keys. The ACL GitOps client is a separate client with `policy_file` scope only. No cross-contamination.

**Rule to remember:** one OAuth client → one tag scope → one device class.

### 3. Ollama registry tag names differ from planned MoE variants

The architecture doc planned `qwen3.5:35b-a3b` and `qwen3-coder:30b-a3b` (MoE variants). These tags do not exist on the Ollama registry. The actual registry tags are `qwen3.5:35b` and `qwen3-coder:30b` (dense).

Dense `:35b` benchmarks confirm it fits comfortably in 96 GB GPU VRAM and performs at expectation. The MoE naming was an assumption from the architecture planning phase. Docs updated accordingly.

### 4. Caddy DNS-01 propagation check requires public resolvers

Without `resolvers 1.1.1.1 8.8.8.8` in the Caddy `tls` block, Caddy uses Docker's internal resolver (`127.0.0.11`), which cannot determine the authoritative nameservers for `mtgibbs.dev`. This produces: `"could not determine authoritative nameservers"` and the ACME challenge fails.

**Fix:** add `resolvers 1.1.1.1 8.8.8.8` to the `tls` block in the Caddyfile. One line; permanent config.

**Why this is not a security regression:** the resolver is only used to find the authoritative NS for the ACME propagation check, not for general DNS forwarding.

### 5. Pi-hole rolling restart must include both primary and secondary

After committing a Pi-hole `pihole-custom-dns.yaml` change and adding new DNS records for `ai.lab.mtgibbs.dev` / `chat.lab.mtgibbs.dev`, both the primary (pi-k3s) AND secondary (pi5-worker-1) Pi-hole pods need restart. Restarting only primary leaves secondary serving stale negative cache, and CoreDNS may round-robin to the secondary. CoreDNS also needs a bounce to flush any TTL-expired negative answers.

---

## Verified End State

| Component | State | Notes |
|---|---|---|
| Ollama | Running | `ollama/ollama:0.17.7`, `OLLAMA_VULKAN=1` |
| LiteLLM | Running | Behind Caddy at `https://ai.lab.mtgibbs.dev` |
| Open WebUI | Running | Behind Caddy at `https://chat.lab.mtgibbs.dev` |
| Caddy TLS | Valid LE cert | DNS-01 via Cloudflare, `resolvers 1.1.1.1 8.8.8.8` |
| Models (5) | Pulled + registered | `qwen3.5:9b`, `gemma3:27b`, `qwen3-coder:30b`, `qwen3.5:35b`, `nomic-embed-text` |
| Tailscale | `tag:inference` at `100.123.94.31` | Single-tag OAuth client |
| ACL GitOps | Active | Validates on PR, applies on push to main |
| DNS | Live | `ai.lab.mtgibbs.dev` + `chat.lab.mtgibbs.dev` → 192.168.1.70 |
| LiteLLM master key | Rotated | 64-char hex in 1Password (`litellm-master-key`) |
| Raw `:4000` | Not exposed | LiteLLM only reachable via Caddy HTTPS |

---

## What Remains (Next Phase)

### Phase 1 — Per-Client Keys + Authelia (deferred)

- [ ] Provision per-client LiteLLM API keys (n8n, future MCP callers) — replace master key with scoped keys
- [ ] Evaluate Authelia/SSO scope before kids' UI — currently deferred unless needed first
- [ ] Kids' Open WebUI at `kids.lab.mtgibbs.dev` (separate auth, model locked to `gemma3:27b`)

### Phase 2 — Observability

- [ ] node_exporter on Beelink → scraped by Prometheus on Pi cluster
- [ ] AMD GPU exporter (or `rocm-smi` scraper) for VRAM/utilization dashboards
- [ ] cAdvisor for container-level metrics
- [ ] Grafana dashboard for inference appliance

### Phase 3 onwards (unchanged from prior plan)

- n8n refinement (SQLite → Postgres migration if needed)
- signal-cli + Signal workflow
- Home Assistant + MCP servers
- Proactive flows

### Open Decisions

- Bot mailbox provider (Cloudflare Email Routing vs new domain)
- Signal phone number (new SIM, Google Voice, or other)
- VLAN segmentation (v2 project — deferred)
- Backup target for Beelink config + `/srv/openwebui` SQLite (likely QNAP once Ansible stage is written)
