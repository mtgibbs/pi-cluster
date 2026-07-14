# Recap — Jellyseerr stuck-"Processing" root cause + fix: unsynced Jellyfin library (2026-07-13)

Matt reported: "jellyfin thinks we're still requesting [T]he [O]ther [B]ennet [S]ister but it's fully
in our library, what gives?" — Jellyseerr (the request manager) showed a TV show as still pending
even though it was fully downloaded and playable in Jellyfin. This session traced it to a
non-obvious, systemic root cause and fixed it live.

## 1. Investigation

Identified the title via the servarr-ops API helper: **"The Other Bennet Sister"** (one 't' in
"Bennet" — Matt's spelling had two), Sonarr series id 44, TVDB `455324`, TMDB `273866`. Sonarr
confirmed season 1 fully downloaded, 10/10 episodes `hasFile:true`.

First hypothesis was a red herring: season 0 ("Christmas Special" x3) is unmonitored with no file,
and the initial guess was that Jellyseerr counts unmonitored specials against completion status.
Refuted once the real cause surfaced — this had nothing to do with the specific title at all.

1Password CLI session had expired mid-task; the servarr helper couldn't read credentials until a
fresh `op signin` (Touch ID) was done.

### Delegated deep diagnosis to `cluster-ops`

The subagent (kubectl exec access the main session lacks for some ops) found:

- Jellyseerr's own API key is **not in 1Password** — unlike every other servarr-adjacent service,
  it's generated in-app and lives only in the running pod's `/app/config/settings.json`
  (`main.apiKey`). Had to `kubectl exec` in to extract it.
- Querying Jellyseerr's own API (`/api/v1/media`, `/api/v1/settings/jellyfin`) found the actual
  root cause: Jellyseerr's synced-library list only contained **Movies** and **Turbo Fire** — the
  real **Shows** library (Jellyfin ItemId `a656b907e...`) was completely absent from the sync list.
  Its scheduled scan jobs (`jellyfin-recently-added-scan` every 5 min, `jellyfin-full-scan` daily)
  had been running successfully on schedule the whole time — they just could never see anything in
  a library Jellyseerr wasn't configured to look at.
- Confirmed **systemic, not per-title**: all 17 TV requests Jellyseerr had ever tracked were stuck
  at `status:PROCESSING` with `jellyfinMediaId:null`. Movies were unaffected (75/83 correctly
  Available) because `Movies` was in the sync list.

## 2. The subagent got stuck applying the fix

`cluster-ops` hung for 10+ minutes on a single `kubectl exec ... wget .../api/v1/settings/jellyfin`
call with no forward progress, despite the pod itself being healthy and idle (1m CPU — not resource
starved). Used `TaskStop` to kill the wedged agent and took the fix over directly in the main
session rather than re-delegating.

## 3. Applying the fix (main session)

- Re-ran the same GET with an explicit `wget -T 10` timeout — worked instantly. The earlier hang was
  most likely a missing-timeout `wget` waiting indefinitely, not a real backend problem.
- The container has **no curl** (busybox `wget` only, which doesn't support PUT/custom methods) — so
  the rest of the diagnosis/fix went through Jellyseerr's public ingress
  (`https://requests.lab.mtgibbs.dev`) with local `curl` instead of `kubectl exec`.
- `PUT /api/v1/settings/jellyfin` → 405 Method Not Allowed.
- `POST /api/v1/settings/jellyfin` with the full settings body → 400; `libraries` and `name` are
  read-only on that endpoint.
- Found the real endpoint by testing: `GET /api/v1/settings/jellyfin/library?sync=true` lists every
  library Jellyfin has, including never-synced ones (`enabled:false`); `GET
  /api/v1/settings/jellyfin/library?enable=<comma-separated-ids>` — GET, not POST/PUT, despite being
  a mutation — is the endpoint that actually sets and persists which libraries are enabled.
- Enabled all three libraries (Movies, Shows, Turbo Fire); verified via `GET
  /api/v1/settings/jellyfin` that `Shows` now shows `enabled:true`.
- Triggered `POST /api/v1/settings/jobs/jellyfin-full-scan/run` instead of waiting for the next
  scheduled cron; polled `GET /api/v1/settings/jobs` until `running:false` (~50s).

## 4. Verification

- Media id 207 ("The Other Bennet Sister", tmdbId `273866`) now `status:5` (AVAILABLE) with
  `jellyfinMediaId` populated.
- Across all 17 TV records: **15 now AVAILABLE, 2 PARTIALLY_AVAILABLE** (legitimately still-airing
  shows — not a bug), **17/17 now have `jellyfinMediaId` populated** (was 0/17 before).

## 5. Documentation

Added a "GOTCHA" subsection to `.claude/skills/media-services/SKILL.md` (after the existing
Jellyseerr section, ~line 480) covering: the failure symptom, root cause, diagnostic commands
(pulling the API key from the pod; `settings/jellyfin` vs `settings/jellyfin/library?sync=true`),
the fix (`?enable=` GET endpoint — noting PUT/POST don't work), how to trigger an immediate scan
instead of waiting on cron, and a prevention note — newly added Jellyfin libraries are never
auto-synced to Jellyseerr and must be manually enabled each time one is added.

---

## State at close

| Item | State |
| :--- | :--- |
| Jellyseerr `Shows` library sync | **Fixed** — all three libraries (Movies, Shows, Turbo Fire) enabled |
| TV requests (17 total) | 15 AVAILABLE, 2 PARTIALLY_AVAILABLE (still airing), 0 stuck |
| "The Other Bennet Sister" | Confirmed AVAILABLE, `jellyfinMediaId` populated |
| Root cause | Library never synced to Jellyseerr on creation — not a Sonarr/Radarr/Jellyfin issue |
| Documentation | GOTCHA subsection added to `.claude/skills/media-services/SKILL.md` |

## Open items

- [ ] No code/manifest change needed — this was a runtime config fix via Jellyseerr's API, not a
  GitOps-managed setting. Nothing to redeploy.
- [ ] Watch for recurrence if/when another Jellyfin library is added in the future — per the new
  SKILL.md prevention note, it will need the same manual enable step.

---

## Commits

Not yet committed — main session will stage `.claude/skills/media-services/SKILL.md` and this recap
together.
