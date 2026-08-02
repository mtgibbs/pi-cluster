---
description: Fix media not appearing in Jellyfin after download
allowed-tools: mcp__homelab__fix_jellyfin_metadata, mcp__homelab__get_media_status, mcp__homelab__touch_nas_path
argument-hint: [show or movie name]
---

# Fix Jellyfin Media

Media was downloaded but isn't appearing in Jellyfin (or shows with missing artwork/metadata).

**Usage**: `/fix-jellyfin <show or movie name>`

## Steps

1. **Search + refresh in one call**: `fix_jellyfin_metadata(name="$ARGUMENTS")`.
   It searches Jellyfin for the item and triggers a metadata refresh. If the item is found but
   metadata is still wrong afterwards, re-run with `replaceAll=true` to discard and re-fetch
   existing metadata and images. If you already know the ID, pass `itemId` to skip the search.

2. **If the item isn't found at all**, the problem is upstream of metadata — the file isn't in
   the library yet. Check, in this order:
   - `get_media_status` — is Jellyfin itself healthy, and do the library counts look right?
   - `touch_nas_path(path)` — bump the mtime on the media directory. **inotify does not work over
     NFS**, so Jellyfin never sees new files by itself; the library scan is what picks them up.
   - The scan runs **daily at 04:00** (moved off the old 15-minute schedule on 2026-05-29 —
     frequent scans caused disk-seek contention that dropped streams mid-playback). So a fresh
     download legitimately may not appear until the next scan. Don't "fix" this by making the
     scan frequent again.

3. **If the file isn't where it should be**, this is an import problem, not a Jellyfin problem —
   check the *arr side (`get_sonarr_queue` / `get_radarr_queue` / `get_sabnzbd_history`) and see
   the orphaned-download recipe in the `media-services` skill.

## Output

Report:
- Whether the item was found in Jellyfin
- What the issue was (missing metadata / not imported / not scanned yet)
- What was done and whether it worked
- If a scan is pending, say when it will run rather than implying it's broken

## Depth

For anything beyond a single refresh — playback stalls, mid-stream drops, library-wide gaps —
stop and load the `media-services` skill, and treat it as an **Investigate** (fan out
`cluster-diagnostics` with `patterns/streaming.md`).
