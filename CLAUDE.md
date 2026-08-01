# Pi K3s Cluster Project

## Project Goal
Build a learning Kubernetes cluster on a Raspberry Pi 5 to run Pi-hole + Unbound, with observability (Grafana/Prometheus), using proper IaC practices. Managed via GitOps (Flux) with secrets from 1Password.

## Operating context

You run as the **coding-harness** (a container), not the laptop. You reach the cluster through the
**homelab MCP** (`mcp__homelab__*`) — full reads plus bounded mutations — and can drive the local
**qwen / Beelink** model via `mcp__local-llm__*` and `oc`. You do **not** have `kubectl`, `op`/1Password,
`ssh`, or `docker` in-container: anything needing those is either a manifest change (PR-gated, via
`cluster-ops`) or a laptop/base-image change (report it, don't self-patch). Everything reaches the cluster
through **Git — PR-gated**, never a direct hand edit. If an MCP call errors, check the tool name
(`mcp__homelab__<tool>`, not the bare name) before concluding the server is down.

## How to work here

Four principles, in priority order — guidance for judgment, not a script. Apply them; don't recite them.

### 1. Security first
- **Never request or paste secrets in conversation.** Source of truth is 1Password (`pi-cluster` vault);
  only `op://` paths live in Git, delivered by ExternalSecrets.
- **Reuse before mint.** Before adding any credential, load the **`secrets-graph`** skill / read
  `docs/secrets-map.md` and walk the graph (1Password item → ExternalSecret → k8s Secret → workload).
  Shared identities are one-per-role: private-image pulls reuse `ghcr-read-token` → `ghcr-pull-secret`,
  alerts reuse the ntfy/Discord identity. Only genuinely per-workload creds (a service's own DB password,
  its scoped LiteLLM key) get a new item.

### 2. Route the work — Read · Investigate · Change
The skills hold cluster-specific truth that generic knowledge gets wrong. Reach for the expert instead of
winging it — *which* expert depends on the verb:
- **Read** — a one-off status/log/queue check: call the `mcp__homelab__*` tool **directly**. No skill, no agent.
- **Investigate** — anything multi-layer ("X is broken/slow/down"): fan out the **`cluster-diagnostics`**
  agent, **one per layer, in parallel**, then synthesize their verdicts. Don't walk the layers serially in
  the main thread. It carries the Diagnostic Discipline, the MCP gotchas, and pre-built layer-sets
  (`.claude/skills/cluster-diagnostics/`).
- **Change** — manifests, deploys, git, `kubectl apply/scale/exec`: load the service's skill for context,
  then hand the edit/deploy to **`cluster-ops`** (the mutation executor). PR-gated.

When a task needs a service's architecture (how it's wired, its gotchas), load that service's skill from
the [Service Index](#service-index) first, and prefer the loaded skill over your priors when they conflict.

### 3. Diagnostic discipline
Prove the server path first (pod → logs → upstream) before blaming the client. **Cached success ≠ proof** —
use cache-bypassing tools (`diagnose_dns`, not `test_dns_query`). One green light doesn't prove the layers
behind it. A clean server trace is a *finding* that points elsewhere, not a dead end. Full discipline + the
non-obvious tool traps live in the `cluster-diagnostics` skill.

### 4. MCP over kubectl
Prefer `mcp__homelab__*` (structured, safe) over shell/kubectl whenever a tool exists; fall back to
`cluster-ops` + kubectl only for operations with **no** MCP equivalent (`scale`, `exec`, `apply`). The tool
set is self-documenting — list it via the MCP; this file no longer carries a catalog. The traps that aren't
obvious (`get_dns_status` stats broken, `get_tailscale_status` false-negative, `test_dns_query` stale cache)
live in the `cluster-diagnostics` skill.

## Service Index

Load the skill when a task needs a service's architecture. The **"Change agent"** column is who executes
*mutations* (`cluster-ops` unless noted); for *investigation* ("X is broken"), fan out `cluster-diagnostics`
regardless of service (see [Route the work](#2-route-the-work--read--investigate--change)).

| Service | Expert Skill (READ THIS FIRST) | Change agent |
| :--- | :--- | :--- |
| **Cluster diagnostics (any "X is broken")** | `.claude/skills/cluster-diagnostics/SKILL.md` | `cluster-diagnostics` (fan-out, read-only) |
| **Pi-hole / DNS** | `.claude/skills/dns-ops/SKILL.md` | `cluster-ops` |
| **Tailscale / VPN** | `.claude/skills/tailscale-ops/SKILL.md` | `cluster-ops` |
| **Prometheus / Grafana** | `.claude/skills/monitoring-ops/SKILL.md` | `cluster-ops` |
| **Jellyfin / Immich** | `.claude/skills/media-services/SKILL.md` | `cluster-ops` |
| **Sonarr / Radarr / Bazarr / SAB API** | `.claude/skills/servarr-ops/SKILL.md` | direct API via helper |
| **Backups** | `.claude/skills/backup-ops/SKILL.md` | `cluster-ops` |
| **Certificates** | `.claude/skills/cert-tls/SKILL.md` | `cluster-ops` |
| **Mealie / Recipes** | `docs/recipecate.md` (build plan + AI-provider mechanics) | MCP direct; `cluster-ops` for manifests |
| **Flux / GitOps** | `docs/flux-gitops.md` | `cluster-ops` |
| **Domain map / topology** | `docs/domain-map.md` (service→image→creds→storage→ingress→calls + Flux deploy-order DAG; auto-derived) | `cluster-ops` |
| **UniFi / Network** | `.claude/skills/unifi-ops/SKILL.md` | MCP direct (local stdio) |
| **Secrets / credentials** | `.claude/skills/secrets-graph/SKILL.md` (graph + reuse-before-mint) | `cluster-ops` |
| **MCP Homelab** | `docs/mcp-homelab-setup.md` | `cluster-ops` |
| **Local Coding Agent (qwen / opencode)** | `.claude/skills/coding-agent-ops/SKILL.md` | `oc` (local) — Claude orchestrates |
| **n8n Email Ingestion Pipeline** | `docs/n8n-email-pipeline.md` (incl. manual/Cloudflare runbook) | `cluster-ops` (in-cluster) + manual edge |
| **Family Board (dashboard UI)** | **self-contained subtree** `clusters/pi-k3s/family-board/` (own `CLAUDE.md` + `.claude/skills/family-board-ui` + `.claude/agents/board-designer`; slated to spin off) | `cluster-ops` (deploy/verify) |
| **review-hub (PR-review gates)** | `docs/adr/008-review-hub-framework-seam.md` (framework/instance seam; `scripts/reviewhub/` + `specs/validators/`; slated to spin off when a second consumer exists) | `cluster-ops` (deploy/verify) |
| **Agent Bus (Matrix chat)** | `docs/agent-bus.md` (Synapse+Element+Postgres; `scripts/agent-bus` CLI; `clusters/pi-k3s/matrix/`) | `cluster-ops` (deploy/verify); MCP for status |

## Hardware Overview
-   **Master**: `pi-k3s` (Pi 5, 8GB)
-   **Workers**: `pi5-worker-1/2` (Pi 5, 8GB), `pi3-worker-2` (Pi 3, 1GB)

## Repository Structure
```
pi-cluster/
├── ARCHITECTURE.md          # Topology & Design Decisions
├── CLAUDE.md                # This file (Router)
├── docs/                    # Reference Docs
├── clusters/pi-k3s/         # Flux manifests
└── .claude/
    ├── skills/              # Knowledge Bases (Load these!)
    └── agents/              # Sub-agent prompts
```

## Agents & Commands

### Sub-Agents
*   **`cluster-diagnostics`**: The Investigator (read-only). Fans out one-per-layer to diagnose
    "X is broken/slow" via the homelab MCP; returns verdicts, never mutates. Can offload heavy log
    reasoning to the Beelink qwen. Loads `.claude/skills/cluster-diagnostics/`.
*   **`cluster-ops`**: The Engineer (mutations). Executes manifest edits, deploys, git, and
    kubectl-with-no-MCP-equivalent (`scale`/`exec`/`apply`). Sequential, PR-gated. Not for diagnosis.
*   **`recap-architect`**: The Historian. Summarizes sessions and updates docs.

> **Project-local agent:** `board-designer` (Family Board frontend) lives *inside* its
> project at `clusters/pi-k3s/family-board/.claude/agents/` so the subtree stays portable.
> Because it's not in the repo-root `.claude/`, Claude Code does **not** auto-register it
> while it lives here — it activates once the board spins off into its own repo. Until then,
> the nested `clusters/pi-k3s/family-board/CLAUDE.md` auto-loads when working in that dir.

### Slash Commands
*   `/deploy` - Commit, push, and reconcile.
*   `/flux-status` - Check GitOps sync state.
*   `/cluster-health` - Quick pod/node check.
*   `/test-dns` - Verify resolution.
*   `/fix-jellyfin <name>` - Fix media not appearing in Jellyfin after download.
