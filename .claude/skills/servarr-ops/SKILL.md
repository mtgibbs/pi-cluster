---
name: servarr-ops
description: Direct REST API patterns for Sonarr, Radarr, Prowlarr, Bazarr, SABnzbd. Use when MCP tools don't expose the operation needed (manual import, release grab, availability override, bulk wanted-search, etc.).
allowed-tools: Bash, Read, Grep, Edit, Write
---

# Servarr API Operations (Sonarr / Radarr / Prowlarr / Bazarr / SAB)

## When to use this skill

The `mcp__homelab__*` tools cover common reads (queue, history, status) and a few writes (search a single title, retry a SAB job). Reach for **this skill** when you need:

- Bulk operations across the wanted/missing list
- Manual import for grabs Sonarr won't auto-import (foreign-language anime, release-name mismatches)
- Per-title `minimumAvailability` overrides (in-cinemas movies)
- Picking and grabbing a *specific* release by guid (when Radarr's quality profile would auto-reject all candidates)
- Anything where the MCP tool surface lacks the operation

> If a recipe here gets used twice, file an MCP enhancement against `mtgibbs/pi-cluster-mcp` so the next caller doesn't have to drop down to curl.

## Auth + base URL convention

All Servarr services follow:

- **Hostname:** `<service>.lab.mtgibbs.dev` (https, valid LE cert)
- **API base:** `/api/v3` (Radarr/Sonarr/Prowlarr/Lidarr) or `/api` (Bazarr/SAB)
- **API key:** stored in 1Password vault `pi-cluster`, item title `<service>.lab.mtgibbs.dev`, field `api-key`
- **Header:** `X-Api-Key: <key>` (Sonarr/Radarr/Prowlarr) or query param `?apikey=<key>` (SAB)

> **Bazarr vault exception (current bug in helper):** Bazarr's API key actually lives at `op://pi-cluster/mcp-homelab/bazarr-api-key`, NOT at `op://pi-cluster/bazarr.lab.mtgibbs.dev/api-key` like the helper assumes. The helper currently fails for Bazarr — workaround: read the key directly via `BAZARR_KEY=$(op read 'op://pi-cluster/mcp-homelab/bazarr-api-key')`. Same will apply to any other service whose key was provisioned for the MCP server's bundled access rather than as a dedicated host-item.

Source the helper at `.claude/skills/servarr-ops/api-key-helper.sh` (sibling file) and use `servarr_call`:

```sh
source .claude/skills/servarr-ops/api-key-helper.sh
servarr_call radarr GET /api/v3/movie | jq '.[].title'
```

## Recipe: bulk wanted-missing search

### Radarr — search ALL wanted/missing movies

```sh
source .claude/skills/servarr-ops/api-key-helper.sh

# Inspect what's wanted (split into searchable vs gated)
servarr_call radarr GET /api/v3/movie | jq -r '
  .[] | select(.monitored and (.hasFile|not))
  | "\(if .isAvailable then "✓ search" else "✗ gated" end)  \(.title) (\(.year))  status=\(.status)"'

# Kick MissingMoviesSearch — covers everything Radarr considers searchable
servarr_call radarr POST /api/v3/command -d '{"name":"MissingMoviesSearch"}' \
  | jq '{id, name, status, queued}'
```

`isAvailable: false` means `minimumAvailability` is gating the search. See the availability-override recipe below.

### Sonarr — search specific episodes (by ID list)

```sh
# Enumerate wanted, group by series to scope the kick
servarr_call sonarr GET '/api/v3/wanted/missing?pageSize=200&includeSeries=true' \
  | jq '.records | group_by(.series.title) | map({series: .[0].series.title, count: length})'

# Pick a series (e.g. Frieren = seriesId 24), get its episode IDs, fire EpisodeSearch
EPS=$(servarr_call sonarr GET '/api/v3/wanted/missing?pageSize=200' \
  | jq '[.records[] | select(.series.title | startswith("Frieren")) | .id]')
servarr_call sonarr POST /api/v3/command \
  -d "{\"name\":\"EpisodeSearch\",\"episodeIds\":$EPS}" | jq '{id, status}'
```

> Don't fire `MissingEpisodeSearch` (the all-series equivalent) for a large library — it hammers indexers across long-tail content that probably won't yield hits anyway. Scope by series.

## Recipe: manual import for stuck releases

When Sonarr/Radarr grab a release matched by ID but not by title (foreign-language anime, scene release using a transliterated name like `Soso.no.Furiren` for Frieren), auto-import is blocked with:

> *"Found matching series via grab history, but release was matched to series by ID. Automatic import is not possible."*

**Fix via API:**

```sh
# 1. Find the queue items with state=importBlocked
servarr_call sonarr GET '/api/v3/queue?pageSize=50' | jq '
  .records[] | select(.trackedDownloadState == "importBlocked")
  | {id, title, downloadId, seriesId, episodeId}'

# 2. For each downloadId, get manualimport candidates and POST ManualImport
for DLID in <list-of-blocked-downloadIds>; do
  PAYLOAD=$(servarr_call sonarr GET "/api/v3/manualimport?downloadId=$DLID" \
    | jq --arg dlid "$DLID" '{
      name: "ManualImport",
      files: [.[] | {
        path: .path,
        seriesId: .series.id,
        episodeIds: [.episodes[].id],
        quality: .quality,
        languages: .languages,
        releaseGroup: .releaseGroup,
        downloadId: $dlid
      }],
      importMode: "auto"
    }')
  servarr_call sonarr POST /api/v3/command -d "$PAYLOAD" | jq '{id, status}'
done
```

> Same pattern works for Radarr. Replace `seriesId`/`episodeIds` with `movieId` and use `/api/v3/manualimport?downloadId=...`.

**Permanent fix: NOT scene aliases.** Tested 2026-05-13 on Sonarr v4.0.17 and Radarr v6.1.1 — `alternateTitles` is read-only TVDB/TMDB metadata. PUT with a user-added entry returns 200 OK but the value is silently dropped on persist. The UI shows the field but doesn't accept additions. Don't bother.

**Permanent fix (actual):** the `import-resolver` CronJob at `clusters/pi-k3s/media/import-resolver-cronjob.yaml`. Runs every 15 min, scans both queues for `trackedDownloadState == "importBlocked"`, builds the ManualImport payload (filtering rejections), and POSTs the ManualImport command. Same flow this skill documents, just automated. **You probably don't need to manually fire ManualImport anymore** — the CronJob should resolve any stuck queue item within 15 min. Use this recipe only when debugging why the CronJob isn't catching something (typically a release with non-empty `rejections` like quality mismatch).

### CRITICAL gotcha: never rename `_UNPACK_X` → `X` inside a Sonarr-monitored path

When SAB leaves an orphan `_UNPACK_*` dir, the obvious fix is `mv _UNPACK_X X` so Radarr/Sonarr stop rejecting with *"File is still being unpacked"*. **Don't do this for TV shows on a Sonarr-monitored download path.**

What happens (observed 2026-05-13 on Avatar TLA S03):

1. You rename `_UNPACK_Show.S03...` → `Show.S03...` in `/downloads/complete/usenet/`
2. Sonarr's filesystem watcher fires immediately on the new dir name and scans it
3. Sonarr parses the contents and decides the in-library files are upgradeable from this "new" release
4. Sonarr deletes the existing in-library files **before** any explicit ManualImport runs
5. If the renamed orphan's release is **incomplete** (missing some episodes the library had), those episodes are now permanently lost — no replacement gets imported, no recovery from the orphan

The specific failure mode that bit Avatar TLA: the WiRd0 BluRay season pack had `S03E14E15.combined.mkv` and `S03E18E19E20E21.combined.mkv` files (multi-episode releases). The library had a *different* multi-episode file `S03E10.E11.The.Day.of.Black.Sun.mkv` that the orphan **did not** contain a replacement for. Sonarr's watcher rescanned, deleted the existing E10E11 file (thinking it was about to be replaced), and the import only covered E14E15 + E18-E21. **Net: 2 episodes lost.**

**Safer pattern for orphan dirs containing TV content:**

```sh
# 1. Move to a path Sonarr is NOT watching
kubectl exec -n media deployment/sabnzbd -- mv \
  /downloads/complete/usenet/_UNPACK_Show.SeasonPack/ \
  /downloads/manual-import-staging/Show.SeasonPack/

# 2. Run manualimport + ManualImport command pointing at the staging path
#    (Sonarr won't touch the staging path until you explicitly tell it to)

# 3. After successful import, clean up the staging dir
```

If you have to operate on the in-place dir, **inspect the orphan's contents first** and confirm every episode the library already has is also present in the orphan. If not, abort.

Movies (Radarr) are less risky here because there's typically only one file per movie — no fan-out potential for multi-episode files.

## Recipe: per-movie availability override

Radarr won't search a movie until `isAvailable == true`, which is gated by `minimumAvailability` (`announced` < `inCinemas` < `released`). Default is `released` — keeps CAM/Telesync rips out for normal use.

Override per-title when you want to chase an in-theaters movie:

```sh
# Find the movie
servarr_call radarr GET /api/v3/movie \
  | jq '.[] | select(.title | test("Project Hail Mary"; "i")) | {id, title, minimumAvailability, isAvailable}'

# Flip via PUT (must send full body — modify minimumAvailability, PUT it back)
MOVIE_ID=94
FULL=$(servarr_call radarr GET /api/v3/movie/$MOVIE_ID)
PATCHED=$(echo "$FULL" | jq '.minimumAvailability = "announced"')
servarr_call radarr PUT /api/v3/movie/$MOVIE_ID -d "$PATCHED" \
  | jq '{id, title, minimumAvailability, isAvailable}'
```

Values: `tba`, `announced`, `inCinemas`, `released`, `predb`. `announced` is most permissive — Radarr will search the moment it sees the movie.

## Recipe: enumerate releases and grab a specific guid

When Radarr's quality profile rejects every candidate (e.g. an in-cinemas movie where all releases are TS/CAM), you can manually pick:

```sh
# 1. Fetch candidate releases — this also populates Radarr's release cache
servarr_call radarr GET '/api/v3/release?movieId=94' > /tmp/releases.json

# 2. Inspect; sort by quality weight and rejection reason
jq -r '. | sort_by(-.qualityWeight) | .[] | "[\(.qualityWeight)] \(.quality.quality.name) \(.size/1073741824|floor)GB rej=\(.rejections|join(";")|.[0:60]) | \(.title)"' /tmp/releases.json

# 3. Grab a specific release by guid + indexerId — IMMEDIATELY after step 1
PICK=$(jq '[.[] | select(.title | test("Multi.Line.Audio"; "i"))] | .[0]' /tmp/releases.json)
GUID=$(echo "$PICK" | jq -r '.guid')
IDX=$(echo "$PICK" | jq -r '.indexerId')
servarr_call radarr POST /api/v3/release -d "{\"guid\":\"$GUID\",\"indexerId\":$IDX}"
```

### Cache TTL gotcha (CRITICAL)

> Radarr's release cache lives ~5 min. If steps 1 and 3 are more than a few minutes apart, the grab returns:
>
> ```
> HTTP 404
> {"message":"Couldn't find requested release in cache, try searching again"}
> ```
>
> **Fix:** re-run the GET `/api/v3/release?movieId=...` to repopulate, then immediately POST the grab.

Sonarr has the same pattern with `/api/v3/release?episodeId=...` + manual ID-based grab.

## Recipe: subtitle pipeline order

Bazarr only sees files **after** Sonarr/Radarr import them. If subtitles aren't being downloaded:

1. Check `mcp__homelab__get_subtitle_status` — does Bazarr know about the episode/movie at all?
2. If `wantedEpisodes/Movies` shows zero for the title, Bazarr considers it satisfied (likely embedded subs in the MKV — common with Crunchyroll WEB-DL).
3. If item is missing entirely, the file probably hasn't been imported yet — check Sonarr/Radarr queue for `importBlocked`.

> The Bazarr `get_subtitle_history` MCP tool is currently broken (returns HTML, not JSON — see filed issue). Use `get_subtitle_status` as the authoritative signal.

## Recipe: re-sync mistimed external SRTs (ffsubsync)

When Bazarr-downloaded external SRTs are 3-5s off (foreign-language films are most common), trigger ffsubsync via `PATCH /api/subtitles?action=sync`:

```sh
KEY=$(op read 'op://pi-cluster/mcp-homelab/bazarr-api-key')
PATH_ENC=$(printf '%s' "/media/Movies/.../file.en.srt" | jq -sRr @uri)
curl -X PATCH -H "X-API-KEY: $KEY" \
  "https://bazarr.lab.mtgibbs.dev/api/subtitles?action=sync&type=movie&id=<radarrId>&language=en&path=$PATH_ENC&max_offset_seconds=60&no_fix_framerate=False&gss=True"
```

For episodes: `type=episode&id=<sonarrEpisodeId>`.

### CRITICAL gotchas

1. **ffsubsync is synchronous + extremely slow on Pi 5.** ~60-70 min per file (full Blu-ray movie via NFS read on ARM). Earlier "1-3 min" estimate was naive PC numbers — completely wrong for this cluster. Default nginx ingress timeout (60s) fires before completion. Bazarr's ingress now has `proxy_read_timeout: 600s` to mitigate (`clusters/pi-k3s/media/bazarr.yaml`). For bulk re-syncs (>3 titles), this is **infeasible** on Pi hardware — plan to migrate to the Beelink AI stack as a CronJob worker, OR avoid ffsubsync entirely by using embedded PGS subs (see "bypass external SRTs" recipe below).

2. **Bazarr can OOM under sync load.** Default 512Mi limit is borderline; ffsubsync's PCM audio buffer + VAD model peaks ~250-400 MB. Bump to 1Gi if Bazarr crashes mid-sync.

3. **Track running jobs via `/api/system/jobs` — NOT `/api/system/tasks`.**
   - `/api/system/tasks` = scheduled crons (every 60 min, etc.) — not on-demand work.
   - `/api/system/jobs` = interactive job queue, including in-flight syncs:
     ```sh
     curl -H "X-API-KEY: $KEY" 'https://bazarr.lab.mtgibbs.dev/api/system/jobs' \
       | jq '.data[] | select(.status == "running") | {job_id, job_name, last_run_time}'
     ```
   This is the single most useful endpoint for tracking async Bazarr operations.

4. **Settings POST requires lowercase `false`/`true`, form-encoded, with the `settings-<section>-<key>` prefix.** This is non-obvious and earlier sessions concluded the endpoint was a "black hole" — it isn't. The validator is just strict:

   ```sh
   # ✅ WORKS — form-encoded with lowercase false
   curl -X POST -H "X-Api-Key: $KEY" "https://bazarr.lab.mtgibbs.dev/api/system/settings" \
     --data-urlencode "settings-general-ignore_pgs_subs=false"
   # → HTTP 204, value persists

   # ❌ JSON body with real boolean → 204 returned, silently no-ops
   curl -X POST -H "X-Api-Key: $KEY" -H "Content-Type: application/json" \
     ".../api/system/settings" -d '{"general":{"ignore_pgs_subs":false}}'

   # ❌ Form-encoded with capital "False" or "0" → HTTP 406, validator rejects
   curl -X POST ... --data-urlencode "settings-general-ignore_pgs_subs=False"
   # → "general.ignore_pgs_subs must is_type_of <class 'bool'> but it is False"
   ```

   Verify with `GET /api/system/settings | jq '.general.ignore_pgs_subs'`. Multiple keys can be flipped in a single POST.

5. **The `subtitlesPath` from the movies/episodes API uses Bazarr's container path (`/media/Movies/...`), not Radarr's (`/movies/Movies/...`).** Always pass exactly what `GET /api/movies` returned in `subtitles[].path`.

6. **Subtitle DELETE wants `path=`, not `subtitles_path=`.** Exact endpoint signature:

   ```sh
   curl -X DELETE -H "X-Api-Key: $KEY" "https://bazarr.lab.mtgibbs.dev/api/movies/subtitles" \
     --data-urlencode "radarrid=$RID" \
     --data-urlencode "language=en" \
     --data-urlencode "forced=False" \
     --data-urlencode "hi=True" \
     --data-urlencode "path=/media/Movies/.../file.en.hi.srt" \
     --data-urlencode "type=movie"
   ```

   For episodes: replace `radarrid` with `sonarrEpisodeId` and `type=movie` with `type=episode`. Note: `forced=False`/`hi=True` here are CAPITAL — different convention from `settings-` POST. Yes, this is inconsistent. Bazarr's API has multiple authors.

7. **Manual subtitle download (replace a bad SRT with a specific candidate) — `POST /api/providers/movies`:**

   ```sh
   # 1. Pull all candidates for radarrId
   curl -H "X-Api-Key: $KEY" "https://bazarr.lab.mtgibbs.dev/api/providers/movies?radarrid=$RID" \
     | jq -r '.data | to_entries[] | "[\(.key)] score=\(.value.score) prov=\(.value.provider) release=\(.value.release_info)"'

   # 2. Save the chosen candidate's `subtitle` blob (encoded pickle b64)
   curl -H "X-Api-Key: $KEY" "...?radarrid=$RID" | jq -r '.data[<idx>].subtitle' > /tmp/sub.b64

   # 3. POST it back
   curl -X POST -H "X-Api-Key: $KEY" "https://bazarr.lab.mtgibbs.dev/api/providers/movies?radarrid=$RID" \
     --data-urlencode "hi=False" \
     --data-urlencode "forced=False" \
     --data-urlencode "original_format=False" \
     --data-urlencode "provider=<provider_name>" \
     --data-urlencode "language=en" \
     --data-urlencode "score=<score>" \
     --data-urlencode "subtitle@/tmp/sub.b64"
   ```

   Bazarr scans the downloaded SRT and **auto-flags it as `.hi.srt` if it contains `[Music]` / `(door slams)` markers**, even if you sent `hi=False`. Old `.en.srt` is NOT replaced — both files coexist. Delete the old one explicitly (recipe #6 above) so Jellyfin picks the new one.

## Recipe: bypass external SRTs — use embedded PGS subtitles

For foreign-language Blu-ray rips, the file usually ships with an English **PGS** (image-based) subtitle track from the original Blu-ray master — perfectly timed against the original audio. Bazarr-downloaded external SRTs are typically scraped from public databases and timed against *some* release that may not match your encode, leading to the classic 3-5s lag.

### The default that breaks this

Bazarr ships with these defaults in `general` settings:

| Key | Default | Effect |
|---|---|---|
| `use_embedded_subs` | `true` | Bazarr scans embedded subtitle tracks |
| `embedded_subs_show_desired` | `true` | Embedded subs count toward "language fulfilled" |
| `ignore_pgs_subs` | **`true`** | **PGS subs are skipped — treated as if absent** |
| `ignore_vobsub_subs` | **`true`** | DVD VobSub subs also skipped |
| `ignore_ass_subs` | `false` | ASS subs are counted (most BD-bundled ASS is fine) |

> The combination "use embedded + ignore PGS" means Bazarr will see "no English embedded subtitle" for any BD rip and aggressively download external SRTs that then displace the perfectly-timed PGS in Jellyfin's preference order. This is the silent root cause behind every "subs are 3-5s off" report.

### Fix — flip both ignore flags off

```sh
KEY=$(op read 'op://pi-cluster/mcp-homelab/bazarr-api-key')

curl -X POST -H "X-Api-Key: $KEY" "https://bazarr.lab.mtgibbs.dev/api/system/settings" \
  --data-urlencode "settings-general-ignore_pgs_subs=false" \
  --data-urlencode "settings-general-ignore_vobsub_subs=false"

# Verify
curl -H "X-Api-Key: $KEY" "https://bazarr.lab.mtgibbs.dev/api/system/settings" \
  | jq '{ignore_pgs_subs: .general.ignore_pgs_subs, ignore_vobsub_subs: .general.ignore_vobsub_subs}'
```

### Trade-offs

> **Apple TV / modern Jellyfin clients** support PGS direct play — flipping these flags is a clear win.
>
> **Browser-based Jellyfin** can struggle with PGS; the server may need to transcode them, costing CPU. If your primary client is the Jellyfin web UI, weigh accordingly.
>
> **Hardcoded language**: PGS subs are images — text cannot be edited, fonts cannot be changed, and translation is fixed at ripping time. If you want different translations, leave the flags as default and live with external SRTs.

### Auditing — which titles benefit

To find titles where this fix would help, query Jellyfin (PGS-eng presence) and cross-reference with Bazarr (external SRT exists):

```sh
JF_KEY=$(op read 'op://pi-cluster/JellyFin/api-key')
USER_ID=<your-user-id>

# List movies with embedded English PGS
curl -H "X-Emby-Token: $JF_KEY" \
  "https://jellyfin.lab.mtgibbs.dev/Users/$USER_ID/Items?IncludeItemTypes=Movie&Recursive=true&Fields=MediaStreams&Limit=2000" \
  | jq -r '.Items[] | select(.MediaStreams[]? | select(.Type=="Subtitle" and .Codec=="PGSSUB" and .Language=="eng")) | .Name'
```

Same query for series with `IncludeItemTypes=Episode`.

## Quality-profile rejection cheat sheet

Common rejection reasons seen in `/api/v3/release` output and what they mean:

| Rejection text | Meaning | Override path |
|---|---|---|
| `<quality> is not wanted in profile` | Quality not in the allowed list of the profile | Add quality tier to profile in Settings → Profiles |
| `X GB is larger than maximum allowed Y GB` | Size cap exceeded | Profile → Quality → max size |
| `Not a Custom Format upgrade` | Cutoff already met | Expected — already have a "good enough" copy |
| `Not an upgrade for existing` | New release not better than current | Expected |
| `Indexer flag is not in profile` | Custom format flag mismatch | Profile → custom formats |

For a one-off override, use the manual grab recipe above — POST `/api/v3/release` with a specific guid bypasses the quality profile check.

## Why some MCP tools don't exist for these (yet)

Filed under `mtgibbs/pi-cluster-mcp` issues:

- **#30** — bulk wanted enumeration + search (Radarr + Sonarr)
- See follow-on issue for: manual import, release grab, availability override, subtitle history bug

When adding these to MCP, the helper patterns in this skill are the reference implementation.

## Common gotchas

1. **Don't use `:released` minimum availability for movies you actually want sooner.** It silently blocks searches with no visible error in the UI.
2. **`MissingMoviesSearch` ≠ rescan.** It searches indexers; it does not re-check the filesystem. Use `RescanMovie` for filesystem state.
3. **PUT requires full body.** Sonarr/Radarr `PUT /movie/:id` rejects partial bodies. GET → modify → PUT.
4. **Release grab is a separate cache from the "Search Monitored" UI button.** Calling POST /command MoviesSearch goes through Radarr's normal pipeline (and respects rejection); POST /release with a specific guid bypasses it.
5. **Sonarr `EpisodeSearch` takes `episodeIds`, not series-level.** For whole-series, use `SeriesSearch` with `seriesId`.
6. **Sticky kubelet NFS mounts after Servarr config changes.** If you edit a PV mount path used by Servarr, force-recreate the pod (`kubectl delete pod`) — the running container keeps the old mount. (See `.claude/skills/media-services/SKILL.md`.)
