---
name: family-board-ui
description: Expert knowledge for the Family Board kiosk dashboard (board.lab.mtgibbs.dev) — a framework-light PWA that renders the n8n intake feed. Use when designing or changing the board UI, adding fixtures, or wiring the feed proxy. The deployable workspace is clusters/pi-k3s/family-board/.
allowed-tools: Bash, Read, Grep, Glob, Edit, Write
---

# Family Board UI

A kiosk PWA at **`board.lab.mtgibbs.dev`** that reads the n8n intake feed and displays
it for the family (deadlines, events, school notices, things to check). **The renderer is
disposable; the backend is the product.** All logic lives in n8n + Postgres; the board only
reads and renders.

## Where everything lives
- **Workspace:** `clusters/pi-k3s/family-board/` (has its own nested `CLAUDE.md` — read it).
- **The app:** `clusters/pi-k3s/family-board/index.html` — one file, inline CSS + vanilla JS, **no build step**.
- **Local preview:** `dev/serve.py` (serves the board + mocks `/api/feed`), `dev/feed.sample.json`, `dev/empty.json`.
- **Data contract:** `docs/dashboard-feed-handoff.md` — the canonical field-by-field spec.

## Architecture
```
board.lab.mtgibbs.dev  (nginx:alpine, this app)
  ├── GET /              -> index.html (the PWA)
  └── GET /api/feed      -> nginx proxy -> http://n8n.n8n.svc:5678/webhook/feed
                            injects header X-Feed-Token (from k8s secret family-board-feed)
n8n "Feed API" workflow (id XW6Ie2Ui3AOLkjSu)
  -> Header Auth (cred "Feed Token" dgqc6ZiNll2avwOb) -> SELECT * FROM intake_items
```
- The board fetches **same-origin `/api/feed`** — no CORS, no token in client JS.
- The token is injected by nginx via `envsubst` (`${FEED_TOKEN}`, `NGINX_ENVSUBST_FILTER=^FEED_TOKEN$`),
  sourced from 1Password `n8n-automation/feed-token` → ExternalSecret `family-board-feed` → pod env.
- A direct hit to `n8n.lab.mtgibbs.dev/webhook/feed` without the header → **403**.

## Deploy model (auto-roll, no publish dance)
Static files ship as **hashed ConfigMaps** via kustomize `configMapGenerator`. Editing
`index.html` changes the hash → the Deployment pod template changes → **pod auto-rolls**.
No annotation bump. Flux reconciles `family-board` (dependsOn external-secrets-config, ingress,
cert-manager-config). The Kustomization deliberately has **no `postBuild.substituteFrom`** —
the JS uses `${...}` template literals that envsubst would clobber.

## Item shape (summary — full contract in the handoff doc)
`id, received_at, type, title, due_at, student, action_required, amount, teacher, course,
source_hint, confidence, source_channel, source_subject, source_from`
- `type` ∈ `event | due | assignment | site-pointer | info` — drives rendering.
- `due_at` ISO-8601 or null. **All-day = stored at UTC midnight (`T00:00:00.000Z`)** — render
  as that calendar date, do NOT timezone-convert (shifts a day back). Timed → America/New_York.
- `student` ∈ `ronin | rory | both | unknown`. Colors: ronin=blue, rory=purple, both=green, unknown=gray.

## Common tasks
- **Iterate on layout:** `python3 dev/serve.py` → http://localhost:8000. Edit `index.html`, refresh.
- **Test edge cases:** edit `dev/feed.sample.json`; `FEED=dev/empty.json python3 dev/serve.py` for empty state.
- **Ship:** commit + push; pod auto-rolls; verify `curl_ingress https://board.lab.mtgibbs.dev/`.
- **Rotate the token:** update op `n8n-automation/feed-token` → patch the n8n cred value (API) →
  roll family-board. (Operator task, not a design task.)

## Gotchas
- **No build tooling** — framework-light is a mandate (resilience). Don't introduce npm/Vite without a decision.
- **`/api/feed` only exists behind nginx or `dev/serve.py`** — a plain `python3 -m http.server` returns 404 for it.
- **Token never in client JS.** If you find yourself putting a secret in `index.html`, stop — it's proxied for a reason.
- **Backend changes (new fields, write-back, filters) are n8n work** — see `docs/n8n-email-pipeline.md`, not here.
