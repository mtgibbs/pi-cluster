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
