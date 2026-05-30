# Recap — Canvas Modular-Ingestion Pipeline + Jellyfin Streaming Incident (2026-05-29 → 2026-05-30)

Two parallel threads this session: shipping the Canvas → family-board data pipeline, and debugging
a movie-stopping Jellyfin streaming-drop incident. They overlapped in investigation time; both are
resolved (the streaming fix is deployed, verification still open — see the incident doc).

---

## 1. Canvas Modular-Ingestion Pipeline

**Status: Live.** 82 dated upcoming assignments and announcements are now flowing from Canvas into
the silver layer and on to the family board/digest, attributed to Ronin.

### What shipped

- **Spec first (`dd61cd9`)** — `specs/modular-ingestion/spec.md` + `verify.sh`: a REASONS Canvas
  capturing the problem, design options, acceptance criteria, and a deterministic verify gate.
  Written before any n8n workflow was touched.

- **`silver: intake-sink`** (n8n id `bcCwJeWqD61TpIW2`) — the shared write path for all sources.
  Contract: INSERT bronze `intake_raw_events` (md5 idempotency guard) → UPSERT silver
  `intake_items` → fire-and-forget digest rebuild ping. All sources funnel through this single
  node; source-specific pollers handle their own shape → 6-field envelope.

- **`bronze: canvas-poller`** (n8n id `NJV9pSpi4gerKqqx`) — 30-min schedule + manual webhook;
  per-observee fan-out. Ingests three record types per observee:
  - `calendar_events` — dated assignments per-course (the right source — see Canvas API journey below)
  - `missing_submissions` — "not turned in" nag per-observee
  - `announcements` — course announcements

  Attributes each record to a student slot (ronin/rory). Uses `canvas-api` cred id
  `1avasNB9qofVhAG0`, scoped to `fultonschools.instructure.com`.

- **Documentation (`9e080d9`)**
  - `docs/data-architecture.md` — bronze/silver/gold tiers, intake-sink contract, schemas, naming
    conventions, Mermaid flow diagram, live workflow-id inventory, "adding a new source" recipe.
  - `docs/canvas-ingestion.md` — operator runbook: what's ingested, creds, per-observee poller
    shape, manual-run commands, the six hard-won Canvas API gotchas, roster/enrollment reality,
    `.ics` alternative for phones, troubleshooting table.

### Canvas API journey (the hard-won lesson)

Three dead ends before the right source:

| Attempt | What happened |
|---|---|
| `planner/items` as observer | Empty response or 403 — wrong for observers |
| `activity_stream` | Returns stale, dateless noise — unusable for deadline tracking |
| **`calendar_events?type=assignment` per-course** | **Correct — dated, complete, scoped to course** |

Additional gotchas now documented in `docs/canvas-ingestion.md`:
- Must send `Accept: application/json+canvas-string-ids` header — otherwise Canvas silently
  truncates 18-digit IDs to lossy floats.
- `observed_users` on the API token is always null; fetch courses per-observee directly.
- `missing_submissions` is a separate per-observee endpoint, not embedded in courses.

### Enrollment reality

Only Ronin appears in the data today. Rory has no current Canvas enrollment (not yet fall
semester). He will appear automatically once enrolled — the poller fan-out is enrollment-driven, no
manual change needed.

### n8n workflows are not in git

The workflows live in n8n's Postgres DB. They are not Flux-managed or committed to the repo.
Backup coverage: the existing weekly `postgres-backup` CronJob covers them.

---

## 2. CARL Retirement (discovered mid-session)

While building the canvas-poller it became clear that `ARCHITECTURE.md §33` documented a prior
service — `CARL` (custom Node/Express + Ollama, `ghcr.io/mtgibbs/carl`) — that had been
decommissioned earlier. It was already removed from GitOps and scaled to zero (the `carl`
namespace exists but contains no pods, deployments, or PVCs).

- **Fix (`ce7b078`):** Added a RETIRED banner to `ARCHITECTURE.md §33`, flipped the deployment
  checklist item. The `n8n canvas-poller` is the documented successor.
- **Cleanup still pending (not git):** delete the empty `carl` namespace; archive the `CARL`
  1Password item.

**Lesson:** check `ARCHITECTURE.md` and `clusters/` for existing services before building. The
Canvas integration was rebuilt from scratch without realizing a prior attempt existed and had
already been retired.

---

## 3. QNAP Storage Reading Correction

During the Jellyfin investigation, the QNAP pool reported "95% full." This is a thick-provisioning
artifact, not a data-fullness problem:

- `DataVol1` reserves its full **15 TB** from the pool at creation (+1.8 TB snapshot reserve,
  0 snapshot bytes used).
- Real data usage: **~5.58 TB (37%)** — well within capacity.
- The "95%" figure is pool free-space consumed by the reservation, not by files.

**Rule:** judge QNAP usage by the volume's **Used Capacity** field, not pool free-space. Captured
in `.claude/skills/media-services/SKILL.md` (`cdb894b`). Do not use "95% full" as a cause for
slow reads or stream drops.

---

## Commit sequence

| Commit | Description |
|---|---|
| `dd61cd9` | spec(modular-ingestion): REASONS Canvas + verify gate |
| `cdb894b` | docs(media): correct QNAP usage reading + move Jellyfin scan to daily 4am |
| `9e080d9` | docs(modular-ingestion): data-architecture + canvas-ingestion runbook (spec §9.6) |
| `ce7b078` | docs(arch): mark CARL retired (§33) — superseded by n8n canvas-poller |

---

## Reference docs

- `docs/data-architecture.md` — modular ingestion tier model and contracts
- `docs/canvas-ingestion.md` — Canvas API runbook and gotchas
- `ARCHITECTURE.md §33` — CARL (retired) and successor
- `docs/incidents/2026-05-30-jellyfin-stream-drops.md` — the streaming incident

---

## Open items

- [ ] Delete the empty `carl` namespace (`kubectl delete namespace carl`)
- [ ] Archive the `CARL` 1Password item in the `pi-cluster` vault
- [ ] Verify clean Jellyfin playback with the daily-scan schedule in place (see incident doc)
- [ ] Canvas enrollment: Rory will appear automatically once enrolled in fall courses — no action needed
