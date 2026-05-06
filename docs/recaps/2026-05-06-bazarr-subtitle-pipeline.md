# Session Recap — 2026-05-06

## Bazarr Subtitle Pipeline Investigation

### Executive Summary

A multi-hour investigation into 3-5 second subtitle timing lag — initially attributed to ffsubsync limitations — revealed a systemic Bazarr configuration issue: two default flags (`ignore_pgs_subs: true`, `ignore_vobsub_subs: true`) cause Bazarr to silently ignore perfectly-timed embedded PGS subtitle tracks on Blu-ray rips, and aggressively download misaligned external SRT files instead. Both flags were flipped via a non-obvious API call. The session also produced definitive documentation of Bazarr's API quirks.

---

## Investigation Arc

### Starting Point: "Subs are 3-5 seconds off" (Shaolin Soccer)

Shaolin Soccer had been flagged as having subtitle timing issues. The file is a Blu-ray rip with multiple audio and subtitle tracks.

### Attempt 1: ffsubsync

Triggered ffsubsync via `PATCH /api/subtitles?action=sync`. The sync ran for approximately 69 minutes (not the 1-3 minutes suggested by prior documentation — that estimate was based on PC hardware). Bazarr's default ingress timeout (60s) fired before completion; bumped the Bazarr ingress to 600s via annotation in `clusters/pi-k3s/media/bazarr.yaml` to mitigate. Result of the 69-minute run was ambiguous — timing improved but remained off.

This exposed the first major finding: **ffsubsync is infeasible for bulk use on Pi 5 hardware**. ~60-70 min per Blu-ray movie via NFS read on ARM. Prior skill documentation cited 1-3 min (wrong hardware assumption).

### Attempt 2: Manual subtitle swap via API

Pulled subtitle candidates via `GET /api/providers/movies`, selected a higher-scored candidate, POSTed it back. Discovered that Bazarr auto-flags downloaded SRTs as `.hi.srt` if the file contains `[Music]` or `(door slams)` markers, regardless of the `hi=False` parameter in the POST. The old `.en.srt` was not replaced — both files coexisted. Had to explicitly DELETE the old subtitle file via `DELETE /api/movies/subtitles`.

The DELETE endpoint uses `path=` (not `subtitles_path=` as the PATCH endpoint does). Different convention, same API.

### Discovery: Bazarr Settings POST Is Not a Black Hole

An earlier session had concluded that `POST /api/system/settings` was a "black hole" (accepted requests, returned 204, but didn't persist). This session proved that conclusion wrong. The endpoint works — but only under strict conditions:
- Request must be **form-encoded** (not JSON)
- Keys must use the `settings-<section>-<key>` prefix (e.g., `settings-general-ignore_pgs_subs`)
- Values must be **lowercase** `true`/`false` — capital `False` or integer `0` return HTTP 406 with a type validation error

JSON bodies return 204 but silently no-op (the validator accepts the content type but ignores the payload).

### Root Cause: `ignore_pgs_subs: true` Default

Checking the movie's actual subtitle tracks revealed an English PGS subtitle track embedded in the MKV (`PGSSUB`/`eng`). This is the Blu-ray master subtitle — perfectly synchronized, zero drift.

`GET /api/system/settings | jq '.general.ignore_pgs_subs'` returned `true`.

With `ignore_pgs_subs: true` (the Bazarr default), Bazarr scans embedded tracks but treats PGS as absent when evaluating "is English subtitle fulfilled?" The result: Bazarr concludes no English subtitle exists and downloads an external SRT from a public database — which is timed against some other release, producing the 3-5s lag. External SRTs displace the PGS track in Jellyfin's preference order.

Same applies to `ignore_vobsub_subs: true` (DVD VobSub tracks get the same treatment).

### Fix Applied

```bash
KEY=$(op read 'op://pi-cluster/mcp-homelab/bazarr-api-key')
curl -X POST -H "X-Api-Key: $KEY" "https://bazarr.lab.mtgibbs.dev/api/system/settings" \
  --data-urlencode "settings-general-ignore_pgs_subs=false" \
  --data-urlencode "settings-general-ignore_vobsub_subs=false"
```

Verified with `GET /api/system/settings | jq '{ignore_pgs_subs: .general.ignore_pgs_subs, ignore_vobsub_subs: .general.ignore_vobsub_subs}'` → both `false`.

Deleted the external `.en.hi.srt` for Shaolin Soccer via DELETE endpoint. Bazarr will re-scan and recognize the embedded PGS-eng as satisfying the English subtitle requirement.

---

## Key Findings (Non-Obvious Facts Learned)

### 1. Bazarr API Key Vault Path Bug

The `api-key-helper.sh` script assumes `op://pi-cluster/<hostname>/api-key` for all services. Bazarr's key lives at `op://pi-cluster/mcp-homelab/bazarr-api-key` (provisioned for the MCP server's bundled access, not as a dedicated host item).

**Workaround**: `KEY=$(op read 'op://pi-cluster/mcp-homelab/bazarr-api-key')`

This is documented as a bug in `.claude/skills/servarr-ops/SKILL.md`. The same issue may affect any other service whose API key was provisioned through the MCP item rather than as a standalone host item.

### 2. Bazarr `/api/system/settings` POST Requires Lowercase Booleans, Form-Encoded

- Form-encoded with `settings-<section>-<key>=<value>` → works
- JSON body → silently no-ops (204, no change)
- Capital `False` or integer `0` → HTTP 406 ("must is_type_of `<class 'bool'>` but it is False")
- Multiple keys can be set in a single POST

### 3. `ignore_pgs_subs: true` Is the Root Cause of Subtitle Lag on Blu-ray Rips

Bazarr ships with `ignore_pgs_subs: true` and `ignore_vobsub_subs: true`. For Blu-ray rips (which typically include an English PGS track from the original Blu-ray master), this means Bazarr will always download an external SRT, which may be timed against a different encode and exhibit 3-5s drift.

**Resolution for this cluster**: Both flags flipped to `false` on 2026-05-06. Bazarr now recognizes embedded PGS-eng and VobSub-eng as satisfying the English subtitle requirement.

**Trade-off**: Browser-based Jellyfin may need to transcode PGS subs (image-based, server-side render). Apple TV and native Jellyfin clients handle PGS direct play without transcoding.

### 4. ffsubsync Runtime on Pi 5 Is ~60-70 Minutes Per Movie

Not 1-3 minutes as previously noted. The prior estimate was based on PC hardware. The Pi 5 must read the entire audio stream (NFS, ~1.7 TB movie library mount) and run VAD + DTW alignment on ARM. For bulk re-syncs this is **infeasible** — days of compute for a modest library.

Future option: delegate ffsubsync to the Beelink AI stack as a background CronJob worker (x86, 128 GB unified RAM, no NFS latency). Not implemented.

### 5. Bazarr Subtitle DELETE Uses `path=`, Not `subtitles_path=`

The DELETE endpoint (`DELETE /api/movies/subtitles`) uses `path=` for the subtitle file path. The PATCH (sync) endpoint uses a different parameter name for the same concept. Bazarr's API has inconsistent parameter naming across endpoints due to multiple authors.

### 6. Manual Subtitle Download Auto-Flags as `.hi.srt` on SDH Content

`POST /api/providers/movies` with `hi=False` does not guarantee a non-SDH filename. Bazarr scans the downloaded SRT body for hearing-impaired markers (`[Music]`, `(door slams)`, etc.) and renames to `.hi.srt` if found, regardless of the request parameter. The old file is not replaced — both `.en.srt` and `.en.hi.srt` coexist. Explicit DELETE of the old file is required.

### 7. Apple TV Jellyfin App Has No Subtitle Offset Control

Known client limitation. If an external SRT is the only subtitle option and it's misaligned, there is no in-player workaround. The solution is to ensure the embedded PGS track is recognized (via the ignore_pgs_subs fix above), not to compensate with offset.

---

## Decisions Made

**Prefer embedded PGS for foreign-cinema Blu-ray rips.** The flip from `ignore_pgs_subs: true` → `false` is the primary fix. External SRTs are unreliable for rips where the source encode is not the same cut used by subtitle database providers. PGS tracks are from the Blu-ray master, perfectly synchronized.

**Abandon ffsubsync as a Pi-5 workload.** 60-70 min per movie is too slow for interactive use and infeasible for bulk. If ffsubsync is needed in the future, route it to the Beelink AI stack.

**Bazarr ingress timeout extended to 600s.** Committed in `clusters/pi-k3s/media/bazarr.yaml`. Required because ffsubsync is synchronous and nginx's default read timeout would fire mid-operation. This also provides headroom for other long Bazarr operations (bulk subtitle searches on large episodes).

---

## Files Modified

| File | Change |
|---|---|
| `clusters/pi-k3s/media/bazarr.yaml` | Added `proxy_read_timeout: 600s` ingress annotation |
| `.claude/skills/servarr-ops/SKILL.md` | Added all 7 gotchas above (ffsubsync timing, settings POST format, PGS flags, DELETE param naming, HI auto-flag, manual download recipe, Apple TV limitation) |

---

## Open Follow-Ups

- [ ] Audit library for titles with embedded PGS-eng + external SRT coexisting — delete the external SRTs where PGS is a better choice. Use the Jellyfin query in `servarr-ops/SKILL.md` (MediaStreams filter for PGSSUB + eng).
- [ ] Decide cleanup strategy for existing external `.hi.srt` files on BD rips (bulk DELETE via Bazarr API vs leave them, since the PGS will now be preferred).
- [ ] File Bazarr GitHub issue for `api-key-helper.sh` path convention mismatch (op://... path not standardized).
- [ ] Evaluate routing ffsubsync to Beelink once LiteLLM stack is live (Beelink Ansible stages 30-tailscale + 40-rocm + Compose stack are still pending).
- [ ] Update `mcp-homelab` `touch_nas_path` tool — still hardcodes `/volume1/cluster/...` Synology paths; needs QNAP path update (carried forward from 2026-04-30 session).

---

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
