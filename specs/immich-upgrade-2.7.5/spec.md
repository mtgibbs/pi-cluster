# Spec: Immich Upgrade v2.4.1 → v2.7.5

- **Status:** Planned (one residual OQ, mitigated by backup — see §12)
- **Owner:** Matt
- **Constitution:** `specs/constitution.md` (+ `/CLAUDE.md` Core Mandates)
- **Touches:** `clusters/pi-k3s/immich/helmrelease.yaml`

---

## 1. Why · [R — Requirements]

Immich is LIVE again (resumed 2026-06-26, see `specs/immich-resume/`) but pinned to **v2.4.1**
(Dec 2025). Bring it to the **latest stable, v2.7.5** (Apr 2026) for fixes + features. This is an
app-image bump only — **not** a database-engine change and **not** the `v3.0.0` pre-release.

## 2. Outcomes (Definition of Done) · [R — Requirements]

1. The Immich server runs **v2.7.5**.
2. The change is a **single-line** image-tag bump — nothing else in the immich dir moves.
3. The Pi-safe Postgres image (`vectorchord0.3.0`) is **untouched** (the 0.4.x jemalloc landmine).
4. ML stays disabled; server + valkey stay enabled (no regression of the resume).
5. `verify.sh` (static gate) exits 0. LIVE migration + health verified post-merge (§11 LIVE tier).

## 3. Entities · [E — Entities]

Config keys only (no data model). Literal keys + target values in `helmrelease.yaml`:

- `spec.values.server.controllers.main.containers.main.image.tag: v2.7.5` (currently `v2.4.1`) ← THE change
- `spec.chart.spec.version: "0.10.3"` (UNCHANGED — chart stays)
- `spec.values.machine-learning.enabled: false` (UNCHANGED)
- `spec.values.server.enabled: true` / `spec.values.valkey.enabled: true` (UNCHANGED)
- `postgresql.yaml` image `…postgres:14-vectorchord0.3.0` (UNCHANGED — separate file, do not open)

## 4. Approach · [A — Approach]

Bump **only** the server container image tag `v2.4.1 → v2.7.5`. Keep the chart (`0.10.3`), the
Postgres image (`vectorchord0.3.0`), ML (off), and the server/valkey enabled flags exactly as-is.
Considered and rejected: bumping the chart to `0.12.0` (separate variable, later), moving to
`v3.0.0-rc` (pre-release + breaking), and bumping the Postgres image to upstream's `0.4.3`
(**the Pi landmine** — see §8). One variable at a time.

## 5. Scope · [S — Structure: boundary]

### In scope
- `clusters/pi-k3s/immich/helmrelease.yaml` — the **one** line `tag: v2.4.1` → `tag: v2.7.5`.

### Out of scope (do NOT touch)
- `postgresql.yaml` — the Postgres image stays `14-vectorchord0.3.0` (do not even open it).
- The chart version (`0.10.3`), ML (`false`), `server.enabled`/`valkey.enabled` (`true`).
- Every other file in `clusters/pi-k3s/immich/` and any other namespace/service.

## 6. Prior decisions / facts the implementer must know · [S — Structure: system fit & deps]

- **The DB floor did NOT move across 2.x.** Upstream's compose pins
  `postgres:14-vectorchord0.4.3-pgvectors0.2.0` for **every** version v2.4.1 → v2.7.5 — including
  the v2.4.1 we run **today on `0.3.0`**. So the minimum extension requirement is unchanged; our
  existing `0.3.0` DB that satisfies v2.4.1 also satisfies v2.7.5.
- We use the **`pgvector`** vector extension (`DB_VECTOR_EXTENSION: pgvector`, pgvector **0.8.1**
  installed) — comfortably above Immich's floor; the VectorChord *image flavour* is incidental.
- **Why NOT bump the Postgres image:** the `0.4.x` VectorChord image has **jemalloc issues with
  16k memory pages** on the Pi 5 (documented in `media-services` skill + `postgresql.yaml`). It is
  the reason we pin `0.3.0`. Leaving it pinned is the whole point — do not change it.
- **Only breaking change v2.4→v2.7 is `v2.7.0`'s** "ML on amd64 needs x86-64-v2 microarch" —
  **arm64 is unaffected** and ML is disabled here. No user intervention needed.
- **Migrations are one-way.** v2.5/2.6/2.7 carry schema migrations the server auto-runs on start.
  The Immich Postgres DB was **backed up 2026-06-26** → NAS `…/2026-06-26/postgres/immich-postgres.dump`
  (26 MB). Rollback = revert tag to `v2.4.1` + restore that dump.
- Exact change (literal — one line in `helmrelease.yaml`):

```yaml
              image:
                tag: v2.7.5        # was: v2.4.1
```

## 7. Norms · [N — Norms]

- Match existing YAML style (indent, no trailing whitespace). Change the **value only**.
- Keep the diff to exactly **one line**. No reflow, no reordering, no comment churn.

## 8. Safeguards · [S — Safeguards]

- **`postgresql.yaml` Postgres image MUST stay `14-vectorchord0.3.0`** — never `0.4.x` (Pi 16k-page
  jemalloc crash). Verify asserts both the 0.3.0 presence and the absence of any `0.4`.
- `machine-learning.enabled` stays `false`; `server.enabled` + `valkey.enabled` stay `true`.
- Chart version stays `0.10.3`.
- Secrets stay via `secretKeyRef` (no inline secret).
- Static gate only — this loop never touches the cluster (Flux applies on merge).

## 9. Task breakdown · [O — Operations]

Atomic (one-line bump), so ONE task:

- **T1:** Bump the Immich server image tag `v2.4.1 → v2.7.5` in `helmrelease.yaml`.

## 10. Acceptance criteria (EARS) · [O — Operations made testable]

- The system shall set the server image `tag: v2.7.5` in `helmrelease.yaml`.
- If `tag: v2.4.1` exists, then the system shall remove it (replaced by `v2.7.5`).
- The system shall keep the chart `version: "0.10.3"`.
- The system shall keep `postgresql.yaml`'s image at `14-vectorchord0.3.0` and free of any `0.4`.
- The system shall keep `machine-learning.enabled: false`, `server.enabled: true`, `valkey.enabled: true`.
- The system shall keep secrets via `secretKeyRef`.
- `helmrelease.yaml` and `postgresql.yaml` shall remain valid YAML.

## 11. Verification — SHIP A `verify.sh`

See `specs/immich-upgrade-2.7.5/verify.sh`. **STATIC tier** (gates the loop): YAML validity + the
tag / chart / Postgres-image / flag / secret assertions above.

**LIVE tier** (post-merge, Claude/MCP + Flux — NOT gated here):
1. New `immich-server` pod rolls out on `v2.7.5`; **DB migrations run clean** in the startup log.
2. The server does **not** reject the `0.3.0` DB (watch for any "extension version below minimum").
3. `https://immich.lab.mtgibbs.dev/api/server/ping` → 200; `/api/server/version` reports 2.7.5.
4. Library + DB intact (photo counts unchanged); Postgres pod still `vectorchord0.3.0`, 0 restarts.
5. **Rollback if migration fails:** revert tag → `v2.4.1`, restore `…/2026-06-26/…/immich-postgres.dump`.

## 11b. Loop execution (handing to qwen)

Run from a throwaway branch in a git worktree:

```bash
scripts/ralph-qwen.sh specs/immich-upgrade-2.7.5
```

One task, fresh context, watchdog-timed, gated on `verify.sh`. Output is a reviewed diff; Flux
applies on merge — never direct-to-cluster.

## 12. Open questions

- **OQ1 (mitigated):** Could v2.5–2.7 have *silently* raised the minimum pgvector/VectorChord
  version above what our `0.3.0` image provides, without a release-note or compose-pin change?
  Evidence says no (identical pin across all 2.x; pgvector 0.8.1 installed; our v2.4.1 already runs
  on it). **Mitigation:** the 2026-06-26 DB backup + the LIVE-tier log watch (§11) — if the server
  rejects the DB on boot, revert + restore. Not a static-gate concern.
