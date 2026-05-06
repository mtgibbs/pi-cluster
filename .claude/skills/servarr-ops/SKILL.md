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

**Permanent fix:** add a scene alias in Sonarr (Series → Edit → Tags / Alternative Titles) so future grabs auto-import. Otherwise this dance repeats every season.

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
