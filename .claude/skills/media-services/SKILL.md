---
name: media-services
description: Expert knowledge for media applications (Jellyfin, Immich). Use when managing media storage, NFS mounts, or application-specific configurations.
allowed-tools: Bash, Read, Grep, Glob, Edit, Write
---

# Media Services (Jellyfin + Immich)

## MCP Quick Actions (USE FIRST)

| Operation | MCP Tool |
| :--- | :--- |
| Media services health + library stats | `get_media_status` |
| Fix missing/broken metadata | `fix_jellyfin_metadata(name="TITLE")` |
| Touch NFS path (trigger inotify) | `touch_nas_path(path="/cluster/media/...")` |
| Subtitle status (wanted/missing) | `get_subtitle_status` |
| Subtitle download history | `get_subtitle_history` |
| Trigger subtitle search | `search_subtitles(type, id)` |

## Storage Architecture

All media is stored on the QNAP NAS (`storage.lab.mtgibbs.dev` → `192.168.1.61`) and mounted via NFS. PV paths use `/cluster/...` (QNAP export root), not `/volume1/cluster/...` (old Synology path).

Migration history: Originally Synology DS420 (192.168.1.60). QNAP TS-435XeU brought up 2026-04-20. All PVs cutover to QNAP 2026-04-30. Synology retained read-only briefly; status TBD.

### Reading QNAP storage usage correctly (do NOT trust "pool % full")

The QNAP **Storage Pool** view (and MCP `list_storages` / `get_system_info`) shows Pool 1 at **~95% used / ~1.1 TB free** — **this is reservation, not data.** `DataVol1` is **thick-provisioned**: it reserves its full **15 TB** from the pool whether used or not, plus a **1.8 TB snapshot reserve** (0 actually used) + 0.2 TB system. So the pool *looks* ~95% "full" while **real data is only ~5.58 TB (≈37%)**.

- **Judge real usage by the Volume's "Used Capacity"** (`5.58 / 14.88 TB`), NOT the pool free-space.
- **"Pool 95% full" is normal here and is NOT a capacity OR performance problem.** Do not blame storage-full for slow reads. (Verified 2026-05-29: all 3 HDDs Good, no disk/RAID errors, pool status fine; `pool_status:-1` / `usable:false` in the API are display quirks, not faults.)
- Real free space inside the volume is ~9 TB. The 80% pool *alert* is just the thick reservation crossing the threshold — cosmetic.

### Common NFS Settings
- **Protocol**: NFSv3 (negotiated by default; NFSv4 explicitly set on any PV caused mount failures for immich — remove `nfsvers=4` if present)
- **DNS name**: All PVs use `storage.lab.mtgibbs.dev` — IP change requires only a Pi-hole DNS flip + pod restart
- **Squash**: "No mapping" (preserves client UIDs; no all_squash)
- **nolock mountOption**: Required on QNAP — NLM (network lock manager) is unreachable on this QNAP config

### NFS Mount Troubleshooting

If pods are stuck in `ContainerCreating`:
1. Verify `showmount -e 192.168.1.61` from a worker node (confirms QNAP is exporting)
2. Check NFS export rules in QNAP QTS UI (IP allowlist for 192.168.1.55/56/57/51)
3. Verify `storage.lab.mtgibbs.dev` resolves correctly: `dig storage.lab.mtgibbs.dev @192.168.1.55`
4. After PV path/server changes, force-recreate the pod (`kubectl delete pod`) — running containers keep old mounts
5. Verify actual mount target via `kubectl exec -- mount | grep nfs` NOT `df` (df can show stale entries)

## Immich (Photos)
- **URL**: `https://immich.lab.mtgibbs.dev`
- **Version**: v2.4.x (PostgreSQL with pgvector)
- **Storage**:
    - `pv.yaml`: Mounts `/cluster/photos` to `/data`.
    - Env Var: `IMMICH_MEDIA_LOCATION=/data`
- **Hardware**: High CPU usage on Pi 5 is known (ML job retry loop). ML features are disabled but jobs still queue.
- **Monitoring**: Metrics on ports 8081/8082, scraped by Prometheus.

## Jellyfin (Video)
- **URL**: `https://jellyfin.lab.mtgibbs.dev`
- **Storage**:
    - `pv.yaml`: Mounts `/cluster/media/video`.
    - Jellyfin media volume is mounted **read-only** (`readOnly: true`)
- **Ingress**: TLS via Let's Encrypt.

## Jellyfin: NFS + inotify Incompatibility (CRITICAL — root cause of "media not appearing")

Jellyfin's `LibraryMonitor` uses Linux `inotify` to watch for new files. **inotify does not work across NFS.** Files written by Radarr/Sonarr to the NFS share are invisible to Jellyfin's file watcher.

### Sonarr/Radarr "Jellyfin Connect" Notifications Are Not Sufficient

The Sonarr/Radarr Emby/Jellyfin notifications ARE configured and working (host: `jellyfin.jellyfin.svc.cluster.local`, port: 8096, API keys valid, HTTP 200 on test). However, these send **targeted updates** (`/emby/Library/Series/Updated`, `/emby/Library/Movies/Updated`) which only refresh metadata for **existing** items in Jellyfin's database. They cannot discover **new** titles on NFS. Keep the notifications (they help with metadata refresh) but they do not solve discovery.

### Library Scan Schedule — daily 4 AM (NOT a short interval; see history)

Jellyfin's "Scan Media Library" task (key `RefreshLibrary`, id `7738148ffcd07979c7ceb148e06b3aed`) is the only way to discover *new* titles on NFS (inotify can't). Set the trigger via the Jellyfin API:

```bash
JF_KEY=$(op read 'op://pi-cluster/JellyFin/api-key')
# Daily 4:00 AM. TimeOfDayTicks = 14400s * 1e7. DO NOT use a short IntervalTrigger — see below.
curl -X POST -H "X-Emby-Token: $JF_KEY" -H "Content-Type: application/json" \
  "https://jellyfin.lab.mtgibbs.dev/ScheduledTasks/7738148ffcd07979c7ceb148e06b3aed/Triggers" \
  -d '[{"Type":"DailyTrigger","TimeOfDayTicks":144000000000}]'
```

**History / why NOT a 15-minute interval:**
- 2026-02-11: set to a **15-min interval** (`IntervalTicks: 9000000000`) so new downloads appeared fast (inotify is dead over NFS).
- 2026-05-29: changed to **daily 4 AM** after the 15-min scan was traced to **hard streaming drops mid-movie**. A scan does thousands of *random* metadata reads across 1,100+ files; a movie is one *sequential* read; on the QNAP's 3-disk spinning RAID5 the two **contend for disk seeks** and thrash the heads → a scan that's normally ~11s balloons to **10+ minutes** AND the stream starves and dies. It does **not** show as CPU / network / NAS-CPU load — it's pure seek latency, so don't chase those. Off-hours scheduling removes the collision entirely.

**Tradeoff:** new media now appears after the 4 AM scan, not within 15 min. The proper fix to keep fast discovery *without* the choke is on-import scan triggers from Sonarr/Radarr (host `jellyfin.jellyfin.svc.cluster.local:8096`, `/Library/Media/Updated` with `Updated` type to force a path scan) — once wired, the periodic scan can be dropped. Also enable "Automatically refresh metadata from the internet" in Jellyfin library settings.

## Jellyfin: Media Not Appearing After Download

**Root Cause A** (new title): NFS inotify — see above. The daily 4 AM scan picks it up (or trigger a manual scan / on-import Sonarr-Radarr scan — see scan-schedule note above).

**Root Cause B** (title visible but wrong/missing metadata): Item exists in database with incomplete metadata (`NULL DateLastRefreshed`). Jellyfin won't display items with failed/interrupted metadata fetches.

**Solution 0 - MCP (TRY FIRST):**
Use `fix_jellyfin_metadata(name="SHOW_NAME")` — searches Jellyfin library and triggers a full metadata refresh via API. No kubectl or API keys needed.

**Solution 1 - UI (if item is visible):**
1. Click the item → three dots → "Refresh Metadata"
2. Check "Replace all metadata" → Save

**Solution 2 - API (if item is NOT visible):**
```bash
# First, find the item ID in the database
kubectl -n jellyfin exec -it deploy/jellyfin -- sqlite3 /config/data/library.db \
  "SELECT Id, Name FROM TypedBaseItems WHERE Name LIKE '%SHOW_NAME%' AND Type LIKE '%Series%';"

# Then trigger a full metadata refresh
JF_KEY=$(op read 'op://pi-cluster/JellyFin/api-key')
curl -X POST "https://jellyfin.lab.mtgibbs.dev/Items/ITEM_ID_HERE/Refresh?metadataRefreshMode=FullRefresh&imageRefreshMode=FullRefresh" \
  -H "X-Emby-Token: $JF_KEY"
```

## Known Jellyfin Issues

- **Galavant S01E02-E08**: Corrupt MKV files (EBML header parsing errors, 0x00 as first byte)
- **PLUR1BUS**: Read-only filesystem errors saving `.nfo` to NFS — cosmetic only. The media mount is `readOnly: true`; metadata is stored in the DB, not on disk.
- **Apple TV Jellyfin app**: No subtitle offset control. PGS direct play works fine. If stuck with a misaligned external SRT and no embedded track, there is no in-player workaround for Apple TV.

## Radarr SQLite Lock Recovery

Stale `radarr.db-wal` and `radarr.db-shm` files from an unclean shutdown persist on local-path storage and cause startup failures.

**Fix:**
```bash
# Scale to 0 — graceful shutdown checkpoints the WAL
kubectl -n media scale deployment radarr --replicas=0
# Wait for termination, then scale back up
kubectl -n media scale deployment radarr --replicas=1
```
Always back up the DB files before attempting recovery. WAL file disappears after a clean shutdown.

## Immich Database
To connect to the database for debugging:
```bash
kubectl -n immich exec -it deploy/immich-postgresql -- psql -U immich -d immich
```
