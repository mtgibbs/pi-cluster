# Recap — RomM dashboard integration + admin login gotcha resolved (2026-07-01 night / 2026-07-02)

Second half of tonight's Game Preservation / ROM Homestead session. Prior context:
`docs/recaps/2026-07-01-game-preservation-kickoff-romm-live.md` covers the plan authoring, the
dumper-hardware buy list, the initial RomM deploy (PR #41), and the `enableServiceLinks` crash-loop
fix — all assumed read, not repeated here. This recap picks up from RomM already live and verified
via `curl_ingress`, and covers only what happened after that: dashboard/monitoring integration, and
a login bug that turned out not to be a bug.

---

## 1. Homepage tile + AutoKuma monitor

RomM had no dashboard presence and no uptime monitoring yet — the prior session deliberately
deferred this to keep PR #41 small and reviewable. Closed out tonight in three commits:

- `450b0b5` — `feat(homepage,uptime-kuma): add RomM dashboard tile + uptime monitor`
- `073b6ad` — `chore(uptime-kuma): bump monitors-revision to roll in RomM monitor`
- `c4c63e3` — `docs(game-preservation): note Homepage tile + AutoKuma monitor done`

**Homepage:** RomM tile added to the **REC DECK** group in `clusters/pi-k3s/homepage/configmap.yaml`,
alongside Jellyfin/Immich/Jellyseerr — same category, library/playback services. That group's column
count was bumped 3 → 4 to fit the new tile without crowding. Icon `romm.png` was confirmed to exist on
the dashboard-icons CDN before wiring it in. RomM has no native Homepage widget, so — same pattern
already used for Jellyseerr/Kiwix — it's configured as a plain `siteMonitor` health check against
`/api/heartbeat`: a status dot, no live-stats widget.

**AutoKuma:** matching monitor (`romm.json`) added in `clusters/pi-k3s/uptime-kuma/autokuma-monitors.yaml`
on the project's standard pattern — 60s interval, Discord alert on failure — hitting the same
`/api/heartbeat` endpoint.

### The gotcha: ConfigMap edits alone don't restart either app

Both Homepage and AutoKuma copy their ConfigMap into an emptyDir via an initContainer that runs
exactly once, at pod startup. Editing the ConfigMap and letting Flux reconcile it does **nothing**
until the pod itself restarts — the running container never re-reads the mount.

- **AutoKuma** already has an established convention for this exact problem: a
  `mtgibbs.dev/monitors-revision` annotation on the pod template in
  `clusters/pi-k3s/uptime-kuma/autokuma-deployment.yaml`, bumped specifically to force a rolling
  restart so the initContainer re-runs and picks up new monitor files. Bumped "4" → "5" in `073b6ad`,
  following the existing convention rather than inventing a new one.
- **Homepage** has no equivalent annotation convention. Rather than add one or reach for raw
  `kubectl rollout restart`, used the MCP `restart_deployment` tool directly — Homepage's
  namespace/deployment is on that tool's whitelist — per the project's MCP-First Protocol.

### Verification (not just "pod restarted, assume it worked")

- `kubectl exec` into the running AutoKuma pod confirmed `romm.json` actually exists in `/monitors`
  inside the container (not just in the source ConfigMap).
- AutoKuma's own startup log showed the sync happening: `[autokuma::sync] INFO: Creating new http: romm`.
- `kubectl exec` into the Homepage pod confirmed the RomM block is present in the actually-rendered
  `/app/config/services.yaml` — the file the app process reads, not just the ConfigMap source.
- `https://home.lab.mtgibbs.dev` confirmed returning **200** through the real ingress path.

---

## 2. Admin login bug — diagnosed, resolved, no code change needed

After completing the RomM setup wizard (creating the first admin user), login failed repeatedly:
`POST /api/login` → 401, despite the account clearly having just been created.

**Diagnostic approach followed the project's Diagnostic Discipline mandate** — prove the server path
first, don't jump to client-side/user-error assumptions:

1. Pulled RomM's own container logs and saw the full request sequence: `POST /api/setup/platforms` →
   201, `POST /api/users` → 201 (account genuinely created), then multiple `POST /api/login` → 401.
2. Queried the MariaDB `romm.users` table directly (`kubectl exec` into the mariadb pod, `mariadb`
   client, root password pulled from the `romm-secret` k8s Secret). Found exactly one user row:
   `username=mtgibbs`, `enabled=1`, `role=ADMIN`, and a valid-looking 60-character bcrypt hash in
   `hashed_password`. Account was completely healthy server-side — nothing corrupted, nothing
   half-created.
3. Inspected RomM's own backend source (`kubectl exec` into the romm pod, grepped
   `/backend/handler/auth/base_handler.py`) and confirmed it uses standard
   `passlib.context.CryptContext(schemes=["bcrypt"])` for hashing/verification — no unusual or buggy
   hashing scheme in play, ruling out an app-level bcrypt bug.

With the account proven healthy on every axis checked, this stopped being a "guess and mutate the
database" situation — offered the user three options (retry carefully / force-reset the password
directly in the DB using RomM's own hash function / investigate further) rather than acting
unprompted on a database that showed no evidence of being broken.

**Root cause, confirmed by the user:** UX gotcha, not a bug. RomM's login form authenticates by
**username**, not email — even though email is a valid, visible field elsewhere in the app (e.g.
shown at signup). The user had been typing the email address into the login form. Login succeeded
immediately once told to use the username (`mtgibbs`) instead.

No backend or database mutation was made — the earlier `mariadb` query was read-only inspection.
Documented as a one-line gotcha on the Task 1 status line in `docs/game-preservation.md` (`6eb295f`)
for future reference, in case anyone else hits the same 401 confusion during a fresh setup.

---

## 3. State at close

| Component | State | Notes |
| :--- | :--- | :--- |
| RomM (`romm.lab.mtgibbs.dev`) | **LIVE, verified** | Dashboard tile + uptime monitor added, admin login confirmed working |
| Homepage REC DECK tile | **Live** | `siteMonitor` against `/api/heartbeat`; group bumped to 4 columns |
| AutoKuma monitor | **Live** | `romm.json`, 60s interval, Discord alert, confirmed created in startup log |
| Admin login | **Working** | Was never broken — login form wants username (`mtgibbs`), not email |
| Task 1 (RomM live) | **Done** | Deployed, dashboard-integrated, monitored, first login confirmed |
| Task 2 (dumper buy list) | **Done** | Covered in prior recap; ordering is the human step |
| Task 3 (ScreenScraper registration) | Open, not blocking | Hasheous already provides keyless day-one metadata scraping |
| Task 4 (NAS folder-structure spec + organizer script) | Open | Cheapest next unit of work — needs no physical hardware |
| Task 5 (backup wiring) | Open | Needs a node-independent `mariadb-dump` CronJob; cluster backups are per-node rsync-over-SSH, not restic |
| Task 6 (first real dump → scan → browser-play smoke test) | Blocked | Waiting on dumper hardware (ordered from Task 2 buy list) to physically arrive |

Cluster health checked at end of session: **103 pods, zero problem pods, all 4 nodes Ready** — clean
bill of health, nothing broken by tonight's changes. A few pre-existing/unrelated items were noted and
dismissed as not caused by this session's work: a transient Grafana readiness blip, node DNS config
warnings, and an unrelated media CronJob missed-schedule warning.

---

## 4. Open items

- [ ] **Task 3 — register ScreenScraper account.** Optional, not blocking.
- [ ] **Task 4 — NAS folder-structure spec + organizer script.** Cheapest next step; no hardware
  dependency.
- [ ] **Task 5 — backup wiring.** Node-independent `mariadb-dump` CronJob for RomM's MariaDB, plus a
  QNAP-side snapshot/2nd-copy decision for `/share/cluster/games`.
- [ ] **Task 6 — first real dump → RomM scan → EmulatorJS browser-play smoke test.** Blocked on dumper
  hardware arrival.
- [ ] **Steam Deck / EmuDeck setup.** Human task, once library has real content.
- [ ] **Whole Archival Sources track** (Internet Archive ingest, DAT-verification tooling, GOG buy
  list) — scoped in `docs/game-preservation.md` §3B, not started.

---

## Commits

| Hash | Subject |
| :--- | :--- |
| `450b0b5` | feat(homepage,uptime-kuma): add RomM dashboard tile + uptime monitor |
| `073b6ad` | chore(uptime-kuma): bump monitors-revision to roll in RomM monitor |
| `c4c63e3` | docs(game-preservation): note Homepage tile + AutoKuma monitor done |
| `6eb295f` | docs(game-preservation): confirm RomM admin login working (username, not email) |
