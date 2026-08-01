---
description: Quick cluster health check - nodes, pods, PVCs, secrets
allowed-tools: mcp__homelab__get_cluster_health, mcp__homelab__get_pvcs, mcp__homelab__get_secrets_status
---

# Cluster Health Check

Quick overview of K3s cluster health, via the homelab MCP (no kubectl needed).

## Checks to Run

Call these three in **one message** — they're independent:

1. `get_cluster_health` — nodes, resource usage, problem pods, and warning events in one shot.
   Covers what `kubectl get nodes` + `top nodes` + non-running pods + recent events used to.
2. `get_pvcs` — PVC status, capacity, storage class, bound volume. Omit `namespace` for all.
3. `get_secrets_status` — ExternalSecrets sync state.

## Output Format

| Component | Status | Details |
|-----------|--------|---------|
| Nodes | OK/WARN/CRIT | Memory %, CPU % |
| Pods | OK/WARN | X running, Y issues |
| PVCs | OK/WARN | X bound, Y pending |
| Secrets | OK/WARN | X synced, Y failed |
| Events | OK/WARN | Recent warnings |

**Overall**: GREEN / YELLOW / RED

**Action needed**: List any issues requiring attention.

## If something is broken

This command is a **Read** — a snapshot, nothing more. If it turns up an actual fault, don't
start troubleshooting inline: that's an **Investigate**, so fan out the `cluster-diagnostics`
agent one-per-layer (see `CLAUDE.md` → Route the work).
