# Recap — Immich un-park, v2.4.1 → v2.7.5 upgrade, OOM hotfix (2026-06-26)

Immich had been parked on 2026-06-17 (commit `53e5b34`) to stop wasting Pi resources while it was
unused: `server.enabled: false`, `valkey.enabled: false`, postgres `replicas: 0`. All PVCs were
retained (`prune: disabled`) so the photo library and database survived untouched. This session
reversed the park, upgraded through three minor versions, fixed an OOM regression introduced by
the upgrade, and documented the node placement. Five PRs (#33–#37), all merged to main.

---

## 1. Resume / un-park — PR #33

The qwen SDD loop was used for the first time in a homelab operation context. A new spec was
authored at `specs/immich-resume/` with a deterministic `verify.sh` static gate (checked for the
three key fields in the HelmRelease: `server.enabled: true`, `valkey.enabled: true`,
`replicas: 1`). qwen produced a byte-exact revert of `53e5b34` on attempt 1: server and valkey
re-enabled, postgres replicas back to 1, stale `# PARKED` comments removed.

Pre-flight via MCP confirmed both PVCs (`immich-library`, `immich-postgresql-data`) were still
`Bound` and `immich-secret` was synced. After Flux rolled the change, postgres, valkey, and the
server pod all reached `Ready`. The `immich-tls` certificate was reissued automatically.
`https://immich.lab.mtgibbs.dev/api/server/ping` → 200 on the pinned v2.4.1 image.

---

## 2. Doc: mark LIVE — PR #34

`.claude/skills/media-services/SKILL.md` was updated before touching the image tag:

- Added an Immich "Status: LIVE" block with the park/resume recipe (the exact three fields to
  flip, and the warning that a partial change gets re-rendered/undone by Helm).
- Marked the stale streaming-investigation hypothesis #3 (`replicas: 0`) as superseded, since that
  investigation pre-dated the park and the note was no longer accurate.

---

## 3. Upgrade v2.4.1 → v2.7.5 — PR #35

Research established that the latest stable release was **v2.7.5**. `v3.0.0-rc` was skipped
explicitly — it is a breaking pre-release and not appropriate for a production-adjacent home
install.

**The key finding was the DB image floor.** Upstream's compose file pins
`postgres:14-vectorchord0.4.3-pgvectors0.2.0` for every 2.x release — *including the v2.4.1 we
already ran on `vectorchord0.3.0`*. This means the upstream compose has always been ahead of what
we pin. The DB floor has not actually moved through v2.7.5; we keep the Pi-safe `vectorchord0.3.0`
image. `vectorchord0.4.x` is known to crash on the Pi 5's 16k memory-page kernel (jemalloc
alignment assumption). We use `pgvector 0.8.1`. The only v2.7.0 "breaking" change that could have
applied was "ML requires x86-64-v2 microarch" — arm64 is unaffected, and ML is disabled anyway.

The Immich Postgres database was backed up before touching the image tag: the `postgres-backup`
CronJob was triggered manually → NAS at `/share/cluster/backups/2026-06-26/postgres/immich-postgres.dump`
(26 MB). The backup completed cleanly before the upgrade proceeded.

The qwen loop (`specs/immich-upgrade-2.7.5/`) did the one-line image-tag bump on attempt 1.
Flux rolled it immediately.

---

## 4. OOM hotfix — PR #36

v2.7.5 went `CrashLoopBackOff` under the **768 Mi** memory limit. That limit had been tightened
in commit `a8b4d99` for the lighter v2.4.1 footprint. The server pod runs both the API worker and
the microservices worker in a single container. Logs reached `Immich Server is listening …[v2.7.5]`
then cut off with no error — the OOMKill signature.

Because the v2.7.5 schema migration had already applied before the pod was killed, rollback was
not safe. The only correct path was forward: raise the limit and let the new schema stay. Memory
was raised from `request: 256Mi / limit: 768Mi` to `request: 512Mi / limit: 2Gi`. The new pod
came up healthy: 0 restarts, ~486 MB RSS. No user-visible outage — the rolling update kept the
old v2.4.1 pod serving until the new one passed its readiness check.

---

## 5. Doc: node placement — PR #37

`ARCHITECTURE.md` Decision #13 was updated to reflect where Immich actually runs:

- Immich Postgres pinned to `pi-k3s` (master node) via its local-path PVC — the data is there,
  so the pod must be too.
- Immich server + valkey scheduled on `pi5-worker-1` (8 GB Pi 5, 4.8 GB free at session close).
- A clarifying note was added: most workload placement in this cluster is scheduler-driven and
  ephemeral; intentional pins exist only where a local-path PVC creates a data-locality requirement.

---

## 6. Verification

After the OOM fix settled, the library was confirmed intact at v2.7.5 via
`/api/server/statistics`:

| Metric | Count |
|---|---|
| Photos | 19,873 |
| Videos | 760 |
| Albums | 4 |
| Total size | ~111 GB |
| Users | 2 (Matt: 14,344 photos / 524 videos; Julia: 5,529 / 236) |

Every asset survived the one-way v2.7.5 schema migration.

---

## 7. Lessons / Gotchas

**Keep Immich Postgres at `vectorchord0.3.0` on Pi.**
`vectorchord0.4.x` crashes on the Pi 5's 16k-page kernel (jemalloc alignment). The upstream
compose has always listed `0.4.x` for 2.x releases — that is aspirational for x86. Our 0.3.0 pin
is correct and has not been invalidated by any release through v2.7.5.

**v2.7.5 requires > 768 Mi; use 2 Gi.**
The v2.7.5 server runs two workers (API + microservices) in one container. The 768 Mi limit that
was fine for v2.4.1 is fatal for v2.7.5. The pod reaches `Listening` and is then OOMKilled with
no logged error — the silence is the signal.

**The park/resume recipe is a three-field atomic change.**
`server.enabled`, `valkey.enabled`, and postgres `replicas` must all be flipped together. A partial
change (e.g., only re-enabling the server without postgres) gets rendered by Helm into a broken
state and then immediately reconciled back by Flux. All three fields or none.

**After a schema migration runs, you go forward, not back.**
v2.7.5's migration applied before the OOMKill was diagnosed. The only safe path was to fix the
resource limit and move forward — rolling back the image would have left an old server running
against a new schema.

**Back up Postgres before any image-tag upgrade, every time.**
26 MB, one CronJob trigger, 30 seconds. There is no good excuse not to.

---

## 8. SDD loop observation

The qwen executor (`scripts/ralph-qwen.sh`) was dogfooded twice in this session — resume and
upgrade — and passed `verify.sh` on attempt 1 both times (byte-exact revert; one-line tag bump).
Both specs used a deterministic static gate rather than a runtime health check, which is why the
loop could terminate quickly and confidently. The OOM hotfix was not looped: it required diagnosis
from runtime logs before the fix was obvious, which is exactly the class of work the loop is not
suited for. Claude orchestrated the diagnosis; the fix itself was a one-line manifest edit.

---

## 9. Other notes

- The homelab MCP server was down mid-session (OAuth `/register` returning 404) and recovered
  after a restart. No data loss; the outage meant a brief fallback to manual kubectl inspection
  before MCP came back.
- `pi5-worker-1` node memory check at close: 4.8 GB free on an 8 GB Pi 5. That node hosts Immich
  server + valkey, the *arr media stack (Sonarr, Radarr, etc.), the secondary Pi-hole + Unbound,
  and assorted infra. The new 2 Gi Immich limit fits; headroom remains.

---

## 10. Summary table

| Component | State at close | Notes |
|---|---|---|
| Immich | **LIVE** | v2.7.5, 0 restarts |
| Immich server memory | `request: 512Mi / limit: 2Gi` | Was 768Mi limit; OOMKill on v2.7.5 |
| Immich Postgres image | `vectorchord0.3.0` | Intentional Pi-safe pin; 0.4.x is unsafe |
| Immich library | 19,873 photos / 760 videos / ~111 GB | Fully intact post-migration |
| `https://immich.lab.mtgibbs.dev` | 200 OK | TLS cert reissued automatically |
| `specs/immich-resume/` | Committed | qwen loop spec + verify gate |
| `specs/immich-upgrade-2.7.5/` | Committed | qwen loop spec + verify gate |
| Postgres backup (pre-upgrade) | `/share/cluster/backups/2026-06-26/postgres/immich-postgres.dump` | 26 MB, on QNAP |
| `media-services` SKILL.md | Updated | LIVE status + park/resume recipe |
| `ARCHITECTURE.md` Decision #13 | Updated | Immich node placement documented |

---

## 11. Open items

- [ ] **Streaming fix confidence (from 2026-06-22):** 2–3 more 4K direct-play sessions to call
  `nconnect=1` bulletproof. Unrelated to this session but still open.
- [ ] **SD card / EEPROM (from 2026-06-22):** `rpi-eeprom-update -a` on all 3 Pi 5 nodes (Jun
  2025 → Nov 2025 target). Cluster health risk; the Immich work here is unrelated but the reminder
  stands.
- [ ] **Immich ML:** disabled on Pi (arm64 is supported but the ML container is a separate heavy
  pod not worth the RAM). Revisit if a worker node frees up significant capacity.
- [ ] **v3.0.0-rc tracking:** upstream's v3 is a breaking release. Watch for stable v3.0.0; it
  will require a separate upgrade path (schema changes, possible new Postgres image requirements).

---

## PRs and commits

| PR | Subject |
|---|---|
| #33 | feat(immich): resume from parked state — re-enable server/valkey, postgres replicas 1 |
| #34 | docs(media): mark Immich LIVE; add park/resume recipe; supersede stale hypothesis |
| #35 | feat(immich): upgrade v2.4.1 → v2.7.5; keep vectorchord0.3.0 DB pin |
| #36 | fix(immich): raise memory limit 768Mi → 2Gi — v2.7.5 OOMKills under old limit |
| #37 | docs(architecture): add Immich to Decision #13 node-placement table |
