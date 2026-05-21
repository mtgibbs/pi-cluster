# kiwix-mcp — Offline Reference Library Tools For LLM Agents

MCP server exposing the home Kiwix library (Wikipedia, Project Gutenberg, Wiktionary, Wikibooks, Wikiquote, Wikisource — 278 GB across 7 ZIMs) as tools an LLM can call. Designed for the kids' AI agent (Phase 4) and any other agent that needs cite-able, offline-vetted reference content instead of the open web.

- **Source:** [`mtgibbs/kiwix-mcp`](https://github.com/mtgibbs/kiwix-mcp)
- **Manifests:** [`clusters/pi-k3s/kiwix-mcp/`](../clusters/pi-k3s/kiwix-mcp/)
- **Endpoint:** `https://kiwix-mcp.lab.mtgibbs.dev/mcp`
- **Backed by:** `kiwix-serve` at `kiwix.kiwix.svc.cluster.local` (in-cluster, no public round-trip)
- **Auth:** bearer token (`X-API-Key` header) from `op://pi-cluster/kiwix-mcp/password`

## Tools

| Tool | What it does |
|---|---|
| `kiwix_list_zims` | Discover available libraries + short names + sizes |
| `kiwix_search` | Full-text search across all ZIMs or scoped to one |
| `kiwix_search_books` | Convenience wrapper: search Project Gutenberg only |
| `kiwix_get_article` | Fetch an article as clean markdown (HTML stripped) |
| `kiwix_suggest` | Autocomplete-style title suggestions within a ZIM |

### Short-name aliases

The MCP accepts friendly short names for the `zim` argument, mapped to current dated ZIM filenames via the catalog cache (1 h TTL). No need to memorize `wikipedia_en_all_nopic_2026-03`.

| Alias | Resolves to |
|---|---|
| `wikipedia` | wikipedia_en_all_nopic_* |
| `wikipedia_simple` | wikipedia_en_simple_all_nopic_* |
| `gutenberg`, `books` | gutenberg_en_all_* |
| `wiktionary`, `dictionary` | wiktionary_en_all_nopic_* |
| `wikibooks` | wikibooks_en_all_nopic_* |
| `wikiquote`, `quotes` | wikiquote_en_all_nopic_* |
| `wikisource` | wikisource_en_all_nopic_* |

## Wiring Into Claude Code

Add to `~/.claude.json` (global) or per-project `.mcp.json`:

```json
{
  "mcpServers": {
    "kiwix": {
      "type": "http",
      "url": "https://kiwix-mcp.lab.mtgibbs.dev/mcp",
      "headers": {
        "X-API-Key": "<op://pi-cluster/kiwix-mcp/password>"
      }
    }
  }
}
```

Restart Claude Code. `/mcp` should list `kiwix` with its 5 tools.

## Wiring Into Open WebUI (Phase 4)

Open WebUI uses its **Pipelines** sidecar to bridge OpenAI tool_calls to external services. Forthcoming `kiwix_tools.py` pipeline will proxy tool_calls from gemma3:27b → this MCP server → kiwix-serve → response back to the model.

## Shell smoke test

```bash
BEARER=$(op read "op://pi-cluster/kiwix-mcp/password")

# Health
curl -s https://kiwix-mcp.lab.mtgibbs.dev/health

# Full session (init → notification → tools/call)
SID=$(curl -s -D /tmp/h -X POST https://kiwix-mcp.lab.mtgibbs.dev/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -H "X-API-Key: $BEARER" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"1"}}}' > /dev/null && \
  grep -i mcp-session-id /tmp/h | tr -d '\r' | awk '{print $2}')

curl -s -X POST https://kiwix-mcp.lab.mtgibbs.dev/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -H "X-API-Key: $BEARER" -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'

# Search Wikipedia for "Tigris River" — top 3 hits
curl -s -X POST https://kiwix-mcp.lab.mtgibbs.dev/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -H "X-API-Key: $BEARER" -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"kiwix_search","arguments":{"query":"Tigris River","zim":"wikipedia","limit":3}}}'
```

## Architecture

```
Claude Code (or Open WebUI Pipelines)
  ↓ HTTPS POST /mcp + X-API-Key bearer
[Pi cluster ingress :443]
  ↓ in-cluster
[kiwix-mcp pod — Node.js MCP server]
  ↓ HTTP, in-cluster
[kiwix.kiwix.svc.cluster.local — kiwix-serve]
  ↓ ZIM file reads
[QNAP NFS at /share/cluster/kiwix/zim, 278 GB]
```

All offline: no internet hop for any lookup.

## Operational

- **Health:** `https://kiwix-mcp.lab.mtgibbs.dev/health`
- **Logs:** `kubectl logs -n kiwix-mcp -l app=kiwix-mcp -f`
- **Restart:** `kubectl rollout restart -n kiwix-mcp deploy/kiwix-mcp`
- **Catalog refresh:** automatic every 1h; restart pod to force immediate refresh after adding new ZIMs
- **Bump version:** edit `package.json` in [`mtgibbs/kiwix-mcp`](https://github.com/mtgibbs/kiwix-mcp), push to main, CI builds, Flux image automation patches the deployment in this repo within 5 min
