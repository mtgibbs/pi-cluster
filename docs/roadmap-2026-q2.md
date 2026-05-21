# AI Stack Roadmap — Q2 2026

Living document. Pruning + reordering encouraged as priorities shift.

Built around the principle: **harden what exists before adding new things**, then **build workflows on the hardened foundation**, then **expand into proactive territory**.

Each horizon is sized to fit a single working session unless flagged otherwise.

> **✓ DONE (2026-05-21): Beelink backup coverage.** The Beelink AI stack's
> stateful data is now backed up nightly to QNAP `/share/cluster/backups/<date>/beelink`
> by a locked-down, profile-gated `beelink-backup` Compose container (systemd timer,
> 03:30 + jitter): **LiteLLM Postgres** via a SELECT-only `backup_ro` role,
> **`/srv/{openwebui,dewey-data,pipelines-data,ops-pipelines-data}`** via `:ro` mounts.
> On success it writes `beelink_backup_last_success_timestamp_seconds` to the
> node_exporter textfile collector; the **`BeelinkBackupStale`** alert (>36h) watches it
> — the Beelink analogue of `BackupCronJobStale` (which can't see a non-cluster job).
> Validated end-to-end on first run (1.69 GB to QNAP, metric scraped). Built in
> `beelink-ansible` (`50-ai-stack.yml` + `files/beelink-backup.sh`) +
> `pi-cluster` (`prometheusrule-beelink.yaml`, commit `0ff937a`).

---

## Horizon 1 — Cleanup + Foundation Hardening

*~45 min, next session*

> Bring the house in order before adding rooms.

| Item | Why | Effort |
|---|---|---|
| Adults' OWUI: master key → scoped virtual key | Least privilege; tiny risk reduction now, big help when we add more services | 30 min |
| Wire `local-llm-mcp` + `kiwix-mcp` into Claude Code (`.mcp.json`) | Token savings + cluster reference tools available in sessions | 15 min |

> **Deferred:**
> - `clusters/pi-k3s/ollama/` cleanup — needs verification that CARL doesn't depend on it before removing. User will revisit out-of-band.
> - **Network-wide SSO (Authelia or similar)** — pulled out into its own evaluation track. See "Strategic Decisions" section below.

**Outcome:** master key only used by Caddy/LiteLLM-internal; local models accessible from Claude Code sessions for token savings.

> Horizon 1 is now small enough to pair with Horizon 2 (observability) or Horizon 3 (pipeline polish) in a single session if you want.

---

## Horizon 2 — Observability

*~3 hrs, 1 session*

> Stop flying blind on the Beelink.

- `node_exporter` + `radeon_exporter` (AMD GPU) + `cAdvisor` as Compose sidecars on the Beelink
- Prometheus federated scrape from the cluster pulls Beelink metrics
- Grafana dashboards: GPU VRAM utilization, model load events, LiteLLM token spend per virtual key, Ollama request latency
- AutoKuma probes for Dewey, ai.lab, chat.lab, dewey.lab (+ existing services)

**Outcome:** when something feels slow, you have the answer in 30 seconds. When LiteLLM rate-limits start firing, you see them coming.

---

## Horizon 3 — Pipeline Polish + Personal Ops Pipeline

*~3-4 hrs, 1 session*

> Make Dewey nicer for daily use, and build a sibling pipeline for *you* — same pattern, different toolset.

### 3a — Dewey polish

- Parse text-format `<tool_call>` blocks as a fallback (qwen3 quirk)
- Multi-turn tool loop improvements
- Per-kid OWUI accounts in Dewey (Ronin + Rory separately, conversation history per kid)
- Add 1-2 more tools: `kiwix_random` for serendipity, maybe a `today_in_history` thin wrapper
- Light cosmetic: Dewey's WebUI theme/avatar/banner

### 3b — Personal Ops Pipeline (new)

> Same Dewey pattern. Different brain (qwen3-coder-30b). Different tools (mcp-homelab readonly).

- New pipeline file alongside `dewey-pipeline.py` — selectable as a model in `chat.lab.mtgibbs.dev`
- Model: `qwen3-coder-30b` (tool-capable, good at reasoning over structured cluster data)
- Tool catalog: **readonly subset of mcp-homelab** — `get_*`, `diagnose_*`, `describe_*`, status checks. NO mutations in v1.
- New scoped bearer token (`mcp-homelab-readonly`) so the pipeline can't restart pods or trigger backups
- System prompt: "you are a cluster operator's assistant — investigate, summarize, suggest. Never claim to have taken action."
- Use case examples: "what's the sonarr queue look like?", "any pods crashlooping?", "summarize today's pi-hole queries", "is the QNAP backup behind?"

**Pattern B (follow-on, not in this horizon):**

Once the pipeline proves which tool sequences are useful, add a `local_diagnose(question, scope)` tool to `local-llm-mcp`. Then Claude Code can delegate multi-step cluster investigation to the local agent (token savings + faster iteration). Sized separately — probably a new mini-horizon after 3.

**Outcome:** kids actually want to use Dewey, and you can ask your own personal LLM "is anything broken?" without opening a kubectl shell.

---

## Horizon 4 — First Real Workflow Surface: Email

*~4-5 hrs, 1 session — was Phase 3 in original architecture doc*

> Where the AI starts doing work, not just chatting.

**Prerequisites:**

- A bot mailbox provisioned — Cloudflare Email Routing on `lab.mtgibbs.dev` is the cheapest path (zone already owned)
- Decide which user-facing aliases to expose: `ai+summary@`, `ai+research@`, `ai+extract@`, `ai+draft-reply@`

**Build:**

- Verify n8n persistence is Postgres-backed; migrate from SQLite if needed
- Dedicated LiteLLM virtual key for n8n workflows
- IMAP trigger node with sender allowlist
- Prompt-injection delimiters in every workflow
- Quarantine attachments by default (opt-in for PDFs/Office)
- Audit log to Postgres
- First two workflows: `ai+summary` (reply via ntfy push), `ai+extract-receipt` (writes structured rows)

**Outcome:** you can email yourself "summarize this", get a ntfy notification 30 seconds later.

---

## Horizon 5 — Mobile AI: Signal

*~4-5 hrs, 1 session — was Phase 4 in original architecture doc*

> Dewey + adults' chat are LAN-only. Signal makes the AI reachable from anywhere.

**Prerequisites:**

- Dedicated phone number (Google Voice free, or cheap SIM ~$5/mo) — NOT your primary

**Build:**

- `signal-cli` in `automation` ns with PVC for registration state
- Register the new number
- n8n Signal workflow: incoming → sender allowlist → context-build → LiteLLM → optional tool calls → reply
- Conversation context in Postgres with auto-expire + `forget my history` command
- Wire to existing MCP layer (`local-llm-mcp`, `kiwix-mcp`)

**Outcome:** text the AI from anywhere; full tool access; persistent conversation context.

---

## Horizon 6 — Smart Home Tool Calling

*Multi-session, ~1-2 days total — was Phase 5 in original architecture doc*

> The "Hey Dewey, is the garage door closed?" capability.

### Phase 6a — HA deployment (1 session)

- HA in `home` namespace with z2m or Z-Wave depending on what hardware you have
- Hue bridge integration
- ConfigMaps for entity registry

### Phase 6b — MCP servers (1 session)

- `home-assistant-readonly` MCP — state queries, sensor reads
- `home-assistant-control` MCP — mutations with schema validation and "destructive action" confirmation pattern
- Wire to Signal workflow, Dewey pipeline

**Outcome:** Dewey can answer "what's the weather in Rory's room?", Signal can answer "did I leave the lights on?"

---

## Horizon 7 — Proactive Flows

*1-2 sessions, depends on Horizons 4+5+6 — was Phase 6 in original architecture doc*

> The AI starts initiating conversations.

- **Morning summary cron** at 7am: doors locked? weather? school-day check? push to Signal
- **Wake-up nudge for Ronin**: motion-aware, school-day aware, escalating intensity
- **Canvas integration into Signal**: nightly check of missing assignments, push to whoever it concerns (fresh Canvas client — CARL stays the museum exhibit)
- **Anomaly alerts**: motion at unexpected times, doors opening when nobody home — model summarizes camera frames (when vision model is ready)
- **Email-driven flows that emit into Signal**: link the two surfaces

**Outcome:** the AI knows your day better than you do, but only nudges when it matters.

---

## Always-On Maintenance

*Quarterly + as-needed*

| What | How often | Why |
|---|---|---|
| Backup verification (LiteLLM Postgres, Dewey OWUI DB, n8n DB, Authelia secrets) | Monthly | Real backups are the ones you've restored from |
| LiteLLM virtual key rotation | Quarterly | Limit blast radius if any leak |
| Master key rotation | Yearly + on-suspicion | Just in case |
| Ollama image bump (when ROCm 7.x lands) | When upstream ships | Replaces Vulkan fallback with proper ROCm |
| Model refresh (qwen, gemma, gutenberg ZIM updates) | Quarterly | Catch breaking changes early |
| Architectural recap | After every milestone | Recap-architect exists for this — use it |

---

## End-State Topology

After all seven horizons:

```
Beelink (inference + user-facing)
  ├── chat.lab.mtgibbs.dev    Adults' chat (Authelia SSO)
  ├── dewey.lab.mtgibbs.dev   Kids' chat (Authelia SSO, qwen3.5-9b + kiwix + maybe HA tools)
  ├── ai.lab.mtgibbs.dev      OpenAI-compatible API (DB-backed virtual keys)
  └── monitoring exporters    GPU/container/proc metrics scraped by cluster Prometheus

Pi cluster (orchestration)
  ├── automation/             n8n + signal-cli + audit DB
  ├── home/                   Home Assistant
  ├── mcp/                    local-llm-mcp, kiwix-mcp, ha-readonly-mcp, ha-control-mcp
  └── existing/               CARL (Canvas reminders), pi-hole, jellyfin, kiwix-serve, ...

External AI surfaces
  ├── Signal (phone)          Persistent chat with full tool access
  ├── Email (bot mailbox)     Async workflows: summarize, extract, research, draft
  └── ntfy push               Notification output for proactive flows
```

That's a real homelab AI platform.

---

## Suggested Cadence

- **Next session:** Horizon 1 (cleanup + Authelia) — frees up future work
- **Session after:** Horizon 2 OR Horizon 3 (your call — observability or pipeline polish)
- **Following month:** Horizons 4 + 5 (workflow surfaces — where the value compounds)
- **When you're ready for it:** Horizons 6 + 7 (smart home + proactive)

---

## Strategic Decisions (No Horizon Yet)

These deserve thought before they get sized into a horizon. Listed here so they don't get lost.

### Network-wide SSO

**Question:** do we want one identity provider in front of *everything* (Dewey, chat, Sonarr, Radarr, Bazarr, SABnzbd, Jellyfin admin, Pi-hole, n8n, future Home Assistant), or do we keep per-service accounts forever?

**Status quo works fine:** password manager handles separate accounts without friction. Pain is low.

**When this becomes worth doing:**

- When we expose anything beyond the LAN (email/Signal workflows in Horizons 4-5 force the question)
- When the family-sharing surface grows past 2-3 services
- When we want centralized audit logging across services
- When a new service ships that we'd rather *not* manage another account for

**Candidates to evaluate when the time comes:**

- **Authelia** — lightweight, forward-auth via Caddy, well-documented, no LDAP requirement
- **Authentik** — heavier but more featureful (OAuth/OIDC provider, more enterprise-y)
- **Pocket-ID** — newer, ultra-minimal, WebAuthn-only

**Scope when we tackle it:** must cover the *arr stack and Pi-hole, not just AI surfaces. That's the test that justifies the work.

---

## Cross-Cutting Concerns To Watch

These don't belong to a single horizon but should be revisited as we move:

- **Backup coverage** — Beelink data (LiteLLM Postgres, adults' + Dewey OWUI DBs, pipeline configs) is now covered by the nightly `beelink-backup` container → QNAP (done 2026-05-21). Authelia state is still NOT covered — add to the backup path when Authelia lands.
- **Family onboarding flow** — how do Ronin/Rory/spouse get accounts? Document once Authelia is in. Likely a Signal message with a magic link + first-login walkthrough.
- **Model evaluation** — qwen3.5-9b is the current Dewey base. If a better safety-tuned + tool-capable model ships (gemma3 with tool template, or something new), we should be able to swap in one Python file edit.
- **CARL's future** — museum exhibit. Stays as-is on his own tiny model. No-footprint when idle, so no reason to retire. If a Canvas-aware Dewey tool ever becomes interesting, build it fresh rather than re-plumbing CARL.

---

*Last updated: 2026-05-20. Next review: after Horizon 1 ships.*
