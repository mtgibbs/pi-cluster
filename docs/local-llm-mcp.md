# local-llm-mcp — Token-Saving Delegation For Claude Code

MCP server that exposes a small set of tools for delegating routine LLM work to local models on the Beelink (via LiteLLM) instead of burning Anthropic tokens.

- **Source:** [`mtgibbs/local-llm-mcp`](https://github.com/mtgibbs/local-llm-mcp)
- **Manifests:** [`clusters/pi-k3s/local-llm-mcp/`](../clusters/pi-k3s/local-llm-mcp/)
- **Endpoint:** `https://local-llm-mcp.lab.mtgibbs.dev/mcp`
- **Auth:** bearer token (`X-API-Key` header) from `op://pi-cluster/local-llm-mcp/password`

## Tools

| Tool | Backing model | Use case |
|---|---|---|
| `local_summarize` | `qwen3.5-9b` | summarize logs, tool output, articles |
| `local_classify` | `qwen3.5-9b` | route into one of N categories |
| `local_extract_structured` | `qwen3.5-9b` (or `35b`) | JSON extraction from unstructured text |
| `local_explain_diff` | `qwen3-coder-30b` | commit/PR/review descriptions |
| `local_explain_command` | `qwen3-coder-30b` | explain shell pipelines |
| `local_chat` | choose any | generic escape hatch |

## Wiring Into Claude Code

The bearer token is in 1Password — don't paste it into the JSON file directly. Either inline-substitute at edit time or use a secret-injection wrapper if your Claude Code setup supports it.

### Option 1 — Global config (all Claude Code sessions)

Edit `~/.claude.json` (or `~/.config/claude/claude.json` depending on platform) and add to the `mcpServers` object:

```json
{
  "mcpServers": {
    "local-llm": {
      "type": "http",
      "url": "https://local-llm-mcp.lab.mtgibbs.dev/mcp",
      "headers": {
        "X-API-Key": "<paste op://pi-cluster/local-llm-mcp/password here>"
      }
    }
  }
}
```

### Option 2 — Per-project (`.mcp.json` at the project root)

Same JSON shape as above. Lets you scope which projects can delegate to local models.

### Activate

After editing, **restart your Claude Code session** — MCP servers are loaded at startup. Run `/mcp` inside Claude Code to verify the server appears and lists its tools.

## Smoke test from the shell

```bash
BEARER=$(op read "op://pi-cluster/local-llm-mcp/password")

# Health
curl -s https://local-llm-mcp.lab.mtgibbs.dev/health

# Init + tools/list (full session flow)
SID=$(curl -s -D /tmp/headers -X POST https://local-llm-mcp.lab.mtgibbs.dev/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -H "X-API-Key: $BEARER" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"1"}}}' > /dev/null && \
  grep -i mcp-session-id /tmp/headers | tr -d '\r' | awk '{print $2}')

curl -s -X POST https://local-llm-mcp.lab.mtgibbs.dev/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -H "X-API-Key: $BEARER" -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'

curl -s -X POST https://local-llm-mcp.lab.mtgibbs.dev/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -H "X-API-Key: $BEARER" -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
```

## Architecture

```
Claude Code (Mac)
  ↓ HTTPS POST /mcp + X-API-Key bearer
[Pi cluster ingress :443]
  ↓ in-cluster
[local-llm-mcp pod — Node.js MCP server]
  ↓ HTTPS POST /v1/chat/completions + LiteLLM virtual key
[Beelink — Caddy :443 → LiteLLM :4000]
  ↓ internal Docker network
[Ollama → Vulkan → Radeon 8060S GPU]
```

The MCP server's LiteLLM virtual key is scoped to ONLY the chat + embedding models — even if the MCP container is compromised, the key cannot reach the master LiteLLM API, cannot mint new keys, and cannot access any other models.

## Bumping versions

1. Edit `package.json` in `mtgibbs/local-llm-mcp` (bump `version`)
2. Commit + push to main
3. CI builds + pushes a new tagged image to ghcr.io
4. Flux image automation picks it up (5-min poll), patches the deployment manifest in this repo, and Flux applies
5. Pod rolls

No manual `kubectl` needed.

## Operational

- **Health:** `https://local-llm-mcp.lab.mtgibbs.dev/health` → `{"status":"ok"}`
- **Logs:** `kubectl logs -n local-llm-mcp -l app=local-llm-mcp -f`
- **Restart:** `kubectl rollout restart -n local-llm-mcp deploy/local-llm-mcp`
- **Rotate bearer token:** update `password` field on `op://pi-cluster/local-llm-mcp`, then `kubectl delete pod -n external-secrets-system ...` to force ExternalSecret refresh (or wait ≤24h for natural refresh)
- **Rotate LiteLLM virtual key:** mint a new one via `POST /key/generate` on LiteLLM, update `litellm-key` field in 1Password, refresh ExternalSecret
