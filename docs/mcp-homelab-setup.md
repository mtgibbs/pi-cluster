# MCP Homelab - Client Setup & Key Rotation

## Overview

The MCP homelab server runs on the K3s cluster at `https://mcp.lab.mtgibbs.dev/mcp` and requires an API key for authentication. The key is stored in 1Password and injected into both the cluster (via ExternalSecret) and local dev tools.

## Architecture

```
1Password (pi-cluster vault)
    └── mcp-homelab/api-key
            │
            ├── ExternalSecret → K8s Secret → MCP pod (server-side)
            │
            └── op read → env var → claude mcp add (client-side)
```

## Initial Setup

### 1. Shell Environment

In `~/.zshrc`:
```bash
# Homelab MCP API key (1Password biometric prompt on first use per session)
export MCP_HOMELAB_API_KEY=$(op read "op://pi-cluster/mcp-homelab/api-key" --no-newline 2>/dev/null)
```

### 2. Register MCP Server with Claude Code

```bash
claude mcp add homelab https://mcp.lab.mtgibbs.dev/mcp \
  -s local -t http \
  -H "X-API-Key:${MCP_HOMELAB_API_KEY}"
```

This stores the config in `~/.claude.json` (local scope, not in any repo).

### 3. Verify

```bash
# Health check
curl -s https://mcp.lab.mtgibbs.dev/health

# MCP protocol test
curl -s -X POST https://mcp.lab.mtgibbs.dev/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-API-Key:${MCP_HOMELAB_API_KEY}" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0.0"}}}'
```

## API Key Rotation

When you need to rotate the API key (compromise, scheduled rotation, etc.):

### Step 1: Generate New Key

```bash
openssl rand -hex 32
```

### Step 2: Update 1Password

Update the `api-key` field in the `mcp-homelab` item in the `pi-cluster` vault with the new key.

### Step 3: Refresh Cluster Secret

The ExternalSecret refreshes every 24h automatically. To force immediate refresh:

```bash
KUBECONFIG=~/dev/pi-cluster/kubeconfig kubectl annotate externalsecret mcp-homelab-secrets \
  -n mcp-homelab force-sync=$(date +%s) --overwrite
```

Then restart the MCP pod to pick up the new secret:

```bash
KUBECONFIG=~/dev/pi-cluster/kubeconfig kubectl rollout restart deployment/mcp-homelab -n mcp-homelab
```

### Step 4: Update Local Client

Open a new terminal (to reload `MCP_HOMELAB_API_KEY` from 1Password), then re-register:

```bash
claude mcp remove homelab
claude mcp add homelab https://mcp.lab.mtgibbs.dev/mcp \
  -s local -t http \
  -H "X-API-Key:${MCP_HOMELAB_API_KEY}"
```

### Step 5: Verify

Restart Claude Code and confirm the MCP server connects.

## Troubleshooting

### "Failed to connect" in claude mcp list
- Check you're on the local network or Tailscale
- Verify DNS resolves: `dig mcp.lab.mtgibbs.dev`
- Check pod is running: `kubectl get pods -n mcp-homelab`

### 401 Unauthorized
- Key mismatch between client and server
- Run rotation steps above to resync

### Pod CrashLoopBackOff
- Check logs: `kubectl logs -n mcp-homelab -l app=mcp-homelab`
- Verify ExternalSecret synced: `kubectl get externalsecrets -n mcp-homelab`

## Security Notes

- API key is stored in plaintext in `~/.claude.json` (local scope only)
- Server access requires Tailscale network + valid API key (defense in depth)
- The K8s ServiceAccount has read-only access with limited write operations
- Pod exec is scoped to jellyfin namespace only
- No delete permissions on any resource

## Known MCP Tool Bugs

### `get_tailscale_status` reports `ready: false` on healthy Connector

`mcp__homelab__get_tailscale_status` returns `ready: false` for the `pi-cluster-exit` Connector even when the underlying Kubernetes resource is healthy. Verified 2026-04-19 (post UDM Pro Max cutover): MCP reports `ready: false`, but `kubectl describe connector.tailscale.com pi-cluster-exit` shows `ConnectorReady: True` with `ObservedGeneration` matching `Generation`, and the exit node is confirmed working.

**Do not treat this as a real problem without cross-checking the CR directly:**
```bash
kubectl describe connector.tailscale.com pi-cluster-exit
# Look for: Status.Conditions[type=ConnectorReady].Status = True
```

Root cause: the MCP tool is likely reading a printer column or stale field from the CRD status rather than `.status.conditions`. Filed as issue against `mtgibbs/pi-cluster-mcp`.

### `get_subtitle_history` returns HTML instead of JSON

The Bazarr subtitle history endpoint returns HTML rather than JSON when called via MCP. Use `get_subtitle_status` as the authoritative signal for subtitle state instead.

### `get_dns_status` stats — fixed 2026-08-02 (history worth keeping)

Stats were broken for months and the cause was misdiagnosed twice, so the trail matters more than
the verdict. Regardless, `diagnose_dns` remains the right tool for troubleshooting — it tests the
full path including both Unbound instances directly, cache-bypassing.

- **#17** — the original Pi-hole v6 API break. Closed/fixed.
- **#44** — the `401` that followed. Long recorded (here and in `cluster-diagnostics`) as a stale
  credential. It wasn't. `stats/summary` was fetched with `requiresAuth = false` — true in v5, not
  v6 — *and* `authenticate()` swallowed failures and silently degraded to an unauthenticated
  request, so a perfectly valid password produced a byte-identical `401`. Two defects, one
  symptom, each masking the other. Fixed in 0.1.25.
- **#48 / [#49](https://github.com/mtgibbs/pi-cluster-mcp/pull/49)** — 0.1.25 then surfaced a
  `429`: concurrent requests each fire their own `POST /api/auth` (nothing dedups in-flight
  logins), tripping FTL's login rate limiter, which every retry re-arms — so it never drains on
  its own. **A 429 here is throttling, not a bad credential. Do not rotate the password on it.**

The recurring lesson: an error message that names a cause is not evidence of that cause. Both
misdiagnoses came from believing the string instead of checking the Pi-hole side (`get_pod_logs`
on the pihole pod showed `API: Rate-limiting login attempts` outright).
