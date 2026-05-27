# Family Board — Frontend Workspace

> This is a **frontend/design workspace**, nested inside the pi-cluster GitOps repo.
> When you're working in this directory, **this context overrides the infra-focused
> root CLAUDE.md**. You are building a **renderer**, not operating a cluster.
> Full knowledge base: `.claude/skills/family-board-ui/SKILL.md`.

## What this is
A kiosk PWA (`board.lab.mtgibbs.dev`) that **reads one endpoint and renders it**. It
holds no business logic — the renderer is disposable, the backend (n8n intake feed) is
the product. If the display dies, redeploy and lose nothing.

## Run it locally (no cluster needed)
```bash
python3 dev/serve.py            # http://localhost:8000  — serves the board + mocks /api/feed
```
- Edit `dev/feed.sample.json` to design against different data (more items, edge cases,
  long titles, empty feed). `FEED=dev/empty.json python3 dev/serve.py` swaps fixtures.
- The data contract (every field, every `type`) is in `../../../docs/dashboard-feed-handoff.md`.

## Files you edit
- `index.html` — the entire app (inline CSS + vanilla JS, no build step). This is the design surface.
- `icon.svg`, `manifest.webmanifest` — PWA home-screen identity.
- `dev/` — local preview server + mock fixtures. **Dev-only; not deployed.**

## Files you DON'T touch (infra — leave to cluster-ops / the human)
- `deployment.yaml`, `service.yaml`, `ingress.yaml`, `namespace.yaml`, `kustomization.yaml`
- `nginx.conf.template` — serves the app **and proxies `/api/feed`, injecting the auth
  token server-side**. The token comes from a k8s secret; it must never appear in client JS.
- `external-secret.yaml`

## How a change ships (GitOps — important)
1. Edit `index.html` (or assets), commit, push to `main`.
2. The static files ship as a **hashed ConfigMap** (`configMapGenerator`). The hash changes
   on every edit, which **auto-rolls the pod** — no manual restart.
3. Flux reconciles within ~10 min, or an operator triggers it. Verify at `board.lab.mtgibbs.dev`.
   > You don't run kubectl/flux here. Hand deploy/verify to the operator (root context) or
   > the `cluster-ops` agent. Your job ends at "committed + pushed".

## Design constraints (the brief)
- **Target:** iPad in Safari → Add to Home Screen (fullscreen PWA); a wall-mounted Pi panel later.
- **Framework-light by mandate** — vanilla, no build, no npm. Keep it one file unless there's a
  strong reason. Resilience + zero-maintenance beats fanciness here.
- Large touch targets, readable from across a kitchen, landscape **and** portrait.
- Color/identity per student: ronin = blue, rory = purple, both = green, unknown = gray.
- Handle the data honestly: `student: unknown`, `due_at: null`, low `confidence`, and an
  **empty feed** must all look intentional.
- **All-day date trap:** items at `T00:00:00.000Z` are date-only — render them as that date,
  never time-zone-convert (that shifts them a day back). Timed items → America/New_York.

## Boundaries
- No secrets, ever. No cluster ops. No public exposure of the board (it's LAN-only, no client auth).
- Want a new field, a filter, write-back ("mark done"), or a `?from=` window? Those are
  **backend** changes — list them for the operator; don't fake them client-side.
