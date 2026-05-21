# AI Stack Roadmap — Q2 2026

Living document. Pruning + reordering encouraged as priorities shift.

Built around the principle: **harden what exists before adding new things**, then **build workflows on the hardened foundation**, then **expand into proactive territory**.

Each horizon is sized to fit a single working session unless flagged otherwise.

> **▶ NEXT SESSION (picked 2026-05-21): Horizon 3a — Dewey polish.** Kid-facing
> improvements to the Dewey chat surface (`dewey.lab.mtgibbs.dev`, gemma3-27b +
> kiwix via `files/dewey-pipeline.py` in `beelink-ansible`). Scope:
> - **Per-kid OWUI accounts** — Ronin + Rory as separate users with their own
>   conversation history (the Dewey OWUI already has `WEBUI_AUTH: true`,
>   `DEFAULT_USER_ROLE: user`; decide signup flow, then disable open signup).
> - **1–2 more kiwix tools** — `kiwix_random` (serendipity) and a `today_in_history`
>   thin wrapper, added to the Dewey pipeline's tool catalog.
> - **Text-format `<tool_call>` fallback parser** — port the qwen3 text-format
>   tool-call parser (already in `files/ops-pipeline.py`) into the Dewey pipeline.
> - **Light cosmetics** — Dewey theme / avatar / banner.
>
> All Beelink-side (`beelink-ansible`), re-deployed via the `50-ai-stack.yml` play.
> Context: backup coverage completed 2026-05-21 — see
> `docs/recaps/2026-05-21-beelink-backup-coverage.md`.

---

## Horizon 1 — Cleanup + Foundation Hardening ✓ COMPLETE (2026-05-21)

> Bring the house in order before adding rooms.

| Item | Why | Status |
|---|---|---|
| Adults' OWUI: master key → scoped virtual key | Least privilege; tiny risk reduction now, big help when we add more services | ✅ Done 2026-05-21 (`op://pi-cluster/openwebui/litellm-key`, alias `openwebui-adults`; all models, no admin). Master key now only used by litellm-internal + ops sidecar. |
| Wire `local-llm-mcp` into Claude Code (`.mcp.json`) | Token savings + cluster reference tools available in sessions | ✅ Done (kiwix-mcp intentionally NOT wired — context cost) |

> **Deferred:**
> - `clusters/pi-k3s/ollama/` cleanup — needs verification that CARL doesn't depend on it before removing. User will revisit out-of-band.
> - **Network-wide SSO (Authelia or similar)** — pulled out into its own evaluation track. See "Strategic Decisions" section below.

**Outcome:** master key only used by Caddy/LiteLLM-internal; local models accessible from Claude Code sessions for token savings.

> Horizon 1 is now small enough to pair with Horizon 2 (observability) or Horizon 3 (pipeline polish) in a single session if you want.

---

## Horizon 1.5 — Make the Beelink GitOps-ready

*~2-3 hrs, 1 session — an enabler, not an urgent op*

> **Why this exists.** The Beelink is the one piece of the homelab *outside* GitOps —
> it's an imperative `ansible`-push box. That's the root cause of the `op`-unlock
> friction that bit us twice on 2026-05-21 (a background deploy aborted when the laptop's
> `op` session lapsed and `$(op read …)` returned empty), and it's why an agent would
> otherwise need to *hold secrets* to change it. The cluster already does this right:
> Flux + the `onepassword` ClusterSecretStore resolve secrets **in-cluster**, so the
> agent's only cluster action is *edit YAML + commit*. We want the same property for the
> Beelink.
>
> Not urgent (the stack is set up and rarely re-runs) — but it's the gate on letting an
> agent safely operate the Beelink, so it belongs on the near horizon.

**The principle:** the agent acts on the **desired-state repo**; the *systems* (Flux,
ESO, a box-local reconciler) enact that state with **their own** scoped identities. The
agent proposes; the infrastructure enacts. The only credential the agent ever holds is
**scoped git-write** — never a secret value.

**The spine (three pieces):**

1. **Box-local 1Password identity** — a service account scoped to **only the Beelink's
   ~11 secrets** (carve them into a narrow `beelink` vault — a mini "split the vault" so
   the box-local token can NOT read the crown jewels: NAS admin, `hetzner`, `unifi`,
   `flux-github-pat`, `litellm-postgres` superuser, `K3s Node Token`). Token stored on
   the box (systemd `LoadCredential` or root `0600`). This is the ESO-analogue for the box.
2. **Secrets rendered on the box** — `.env`/configs built by reading 1Password *locally*
   via the SA token (`op read` / the `op` lookup, or `op inject`). Nothing is passed in
   from a laptop or agent.
3. **A reconciler watching git** — **`ansible-pull`** on a systemd timer runs the existing
   `50-ai-stack.yml` *on the box* from a git checkout. Reuses the playbook as-is; we just
   flip push → pull and move the secret reads onto the box. (Box needs `ansible` installed.)

**Repo:** publish `beelink-ansible` to a **public GitHub repo** (currently local-only),
matching `pi-cluster` (also public) and the rest of the homelab stack, and add it to the
nightly **git-mirror** job. No secrets are committed (verified clean; `.gitignore` covers
`secrets/`/`*.vault`) — `op://` *paths* are fine to expose, values never. Visibility is a
recon/consistency question, not an exploitation one (Kerckhoffs: the design is public, the
secrets are the secret).

**Decisions / to verify when we build:**

- **ESO auth mechanism** — confirm whether the cluster's `onepassword` ClusterSecretStore
  uses 1Password **Connect** vs a **service account**, and mirror the right one on the box.
- **Trigger cadence** — timer-only (applies on a delay) vs. timer + a manual/agent
  "reconcile now" trigger.
- **Exact `beelink` vault contents** — the ~11 secrets `50-ai-stack.yml` reads, and nothing more.

**Pairs with (broader autonomy-safe posture — track separately, see Strategic Decisions):**
the data backstops GitOps can't restore — PVC `reclaimPolicy: Retain`, immutable/retained
NAS backup snapshots, scoped DB roles (the `backup_ro` SELECT-only pattern), and
branch protection on the Flux branch. These bound *destructive data actions*, which remain
the only real risk once the agent holds nothing but git-write.

**Outcome:** changing the Beelink = committing to its repo; the box self-applies and pulls
its own secrets. The laptop/agent `op` token becomes **unnecessary, not just scoped**, and
the Touch ID gate is replaced by **separation of identity** (agent holds only git-write) +
**GitOps reversibility** + **data-backstop irreversibility**. This is the "I build the
rails, the local AI runs the trains" enabler — for the last non-GitOps box.

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
