# Heartbeat of the House — harness visualizer

A generative-art view of the coding-agent harness (and, eventually, the whole
house): each agent is a spinning 3D ball of dust that drifts and bonds like an
atom, brightening as it thinks and touching the others when they work together.

`index.html` is the **pinned art-direction baseline** (artifact version
`atom-baseline-v1`, locked 2026-07-21). It's a single self-contained file — no
build, no dependencies, Canvas 2D. Open it directly in a browser.

## Why this model (rejected alternatives)

Two earlier directions were tried and dropped, on purpose:

- **Glowing orbs + heartbeat rings** — read as "fire," too hot.
- **Shared 2D dust field with vortices at fixed anchors** — the mind centres
  acted as sinks ("black holes"); dust drained into them, which is the opposite
  of the swirling *exchange* we want.

The keeper is **discrete atoms**: self-contained 3D dust balls with no central
attractor (so nothing to fall into), moved by a simple physics where two
*thinking* minds bond and pull together until their surfaces touch, then a soft
repulsive core stops them merging. Idle minds drift back to their home spots and
glow as dim, slow-spinning embers. Three legible states — **rest / think /
flare** — drivable by hand via the control bar (`● live sim` ↔ `○ manual`).

## Status — what's real vs. mock

- **Real:** the visual model, the physics, the rest/think/flare states, the HUD
  telemetry *shape*.
- **Mock:** the *data*. A small in-file simulation drives the minds
  (pick up work → phases → pass/fail → idle). It is shaped deliberately to match
  the live collector so wiring is a swap, not a rewrite.

## Data contract (what the live feed must provide)

The simulation stands in for a JSON feed of per-agent status. Each agent needs:

| field | meaning | live source |
|---|---|---|
| `id` / `name` / `role` | identity | static |
| `state` | `idle` \| `running` | tmux `pane_current_command`; heartbeat `phase` |
| `phase` | picking up / thinking / verifying / passed / retry / stopped | ralph heartbeat (`scripts/ralph-status.sh`) |
| `task`, `task_index`, `total_tasks`, `attempt`, `max_attempts` | current work | ralph heartbeat |
| `tokens` | tokens this session | opencode.db (qwen) / Claude · Codex JSONL |
| `activity` (0..1) | drives brightness/spin/radius | derived: idle≈0.03, think≈0.5, flare≈0.95, or a real signal |

House aggregate (BPM, active count) is derived from the per-agent activity.

This is the **same collection** `scripts/harness status` already performs (health
+ per-agent activity + GPU lane) — the console just needs it as JSON over HTTP
instead of a terminal table.

## Implementation plan

1. **Art direction** — this prototype. ✅ pinned.
2. **Collector feed** — a small service on the Beelink that emits the contract
   above as JSON (reuses the `harness status` logic: heartbeat files + tmux +
   session DBs). Managed in `beelink-ansible`, everything-as-code.
3. **Wire** — swap the in-file simulation for `fetch()` polling of the feed;
   `activity` maps from real state; keep the mock as an offline fallback.
4. **Serve + widen** — self-host the page; then grow beyond agents to
   whole-house telemetry from Prometheus (Pi-hole query rate, backups completing,
   media streams, pod births/deaths, GPU load) — each its own atom or pulse.
5. **Density** — if Canvas 2D taps out, port the field to WebGL for the
   full "pixel cloud" density.

## Open decision

**Where it's hosted** — on the Beelink (static page + the collector next to the
harness containers it watches) vs. in-cluster (`clusters/pi-k3s/…`, Flux-managed,
behind the existing ingress). The collector reads the Beelink's Docker
containers, so the Beelink is the natural home for it; the page itself could live
either place. Decide before step 2.
