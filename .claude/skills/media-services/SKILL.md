---
name: media-services
description: Expert knowledge for media applications (Jellyfin, Immich, Jellyseerr). Use when managing media storage, NFS mounts, or application-specific configurations.
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
- **Protocol**: auto-negotiated (no `nfsvers` pinned). Verified 2026-06-18 — `jellyfin-video` mounts as **NFSv4.1** with this QNAP. Do NOT explicitly set `nfsvers=4` — it broke immich mounts (remove if present).
- **DNS name**: Worker-node PVs use `storage.lab.mtgibbs.dev` (IP change = a Pi-hole DNS flip + pod restart). **Exception — `jellyfin-video-nfs` hardcodes `192.168.1.61`**: it mounts on **pi-k3s**, which uses *public* DNS (not Pi-hole) and resolves the hostname only via the `/etc/hosts` override DaemonSet (a single point of failure). Hardcoding removes that hop. (Trade-off: a future QNAP IP change must edit this PV directly, not just DNS.)
- **Mount resilience**: a plain `hard` mount turns a brief NAS stall into a *permanent* freeze (see recovery runbook below). The right fix differs by access mode:
  - **Read-only** PVs (`jellyfin-video-nfs`; also `kiwix-zim-nfs`): `soft,timeo=600,retrans=2,nconnect=4` — `soft` makes a stall **error-and-recover** instead of hang (safe — no writes to corrupt). Jellyfin: 2026-06-15.
  - **Read-write** PVs (`media-downloads/library/music/books`; also immich, calendar): **keep `hard`** (a `soft` write-timeout can corrupt) + add `timeo=600,retrans=2,nconnect=4` for throughput + resilience. The 4 media PVs: 2026-06-16.
  - **IP-hardcode** (`server: 192.168.1.61`) is ONLY on `jellyfin-video-nfs` — it mounts on pi-k3s (public DNS + `/etc/hosts` override SPOF). Worker-node PVs keep the hostname (Pi-hole resolves it; easy IP change).
- **Squash**: "No mapping" (preserves client UIDs; no all_squash)
- **nolock mountOption**: Required on QNAP — NLM (network lock manager) is unreachable on this QNAP config

### NFS Mount Troubleshooting

If pods are stuck in `ContainerCreating`:
1. Verify `showmount -e 192.168.1.61` from a worker node (confirms QNAP is exporting)
2. Check NFS export rules in QNAP QTS UI (IP allowlist for 192.168.1.55/56/57/51)
3. Verify `storage.lab.mtgibbs.dev` resolves correctly: `dig storage.lab.mtgibbs.dev @192.168.1.55`
4. After PV path/server changes, force-recreate the pod (`kubectl delete pod`) — running containers keep old mounts
5. Verify actual mount target via `kubectl exec -- mount | grep nfs` NOT `df` (df can show stale entries)

### NFS mount WEDGED ("server not responding, still trying") — recovery

**Symptom:** a pod (esp. **Jellyfin**, pinned to pi-k3s) hangs on every media read — `ls /media`
may still list (cached metadata) but `dd`/actual reads hang; the pod gets stuck `Terminating`.
`dmesg` on the node shows `nfs: server storage.lab.mtgibbs.dev not responding, still trying`.

**Root cause (confirmed 2026-06-15):** a brief NAS read-stall (spinning-RAID5 seek contention
under streaming load — see the disk-contention schedule below) on a **`hard`** mount → the kernel
retries *forever* instead of erroring, so a momentary hiccup becomes a permanent freeze. Everything
else was healthy — NAS up (worker-1 read at 89 MB/s), node Ready, **conntrack 3% full, 0 NIC
errors, DNS fine**. It is **array-stall × hard-mount**, not network/DNS/CPU. The
`soft,nconnect` mount options on the PV are the durable fix; `kubectl rollout restart` does NOT
clear it (a rolling restart never drops the wedged mount — you must fully release it).

**Fast recovery (~30 s):**
```sh
# 1. force-lazy-unmount the wedged NFS mount on the node it's pinned to (Jellyfin = pi-k3s / .55)
ssh mtgibbs@192.168.1.55 \
  "mount | grep jellyfin-video-nfs | awk '{print \$3}' | xargs -r sudo umount -f -l"
# 2. recreate the pod so it mounts a FRESH connection (force — the old one won't terminate)
kubectl delete pod -n jellyfin --all --force --grace-period=0
# 3. verify a real read is fast again (expect ~100 MB/s)
kubectl exec -n jellyfin deploy/jellyfin -- sh -c \
  'dd if="$(find /media/Movies -name "*.mkv" | head -1)" of=/dev/null bs=1M count=64'
```

### OPEN — streaming still drops early AFTER the 2026-06-15 soft-mount fix (tracking)

**The soft mount stopped the *permanent freeze* but did NOT stop the *stream drop*.** Post-fix, a NAS
read stall no longer wedges Jellyfin forever — instead the stream dies early and the pod self-heals.
This is a **new, still-open failure mode**; the soft mount changed the *symptom*, not the root cause.

**Incident 2026-06-16 (~20:01 & ~20:32 EDT / `00:32Z` 6/17):** "Kill Bill: Vol. 2" via **Infuse-Direct**
(direct play, Apple TV) dropped **early and repeatedly** — playback stopped at `108507 ms` (**1:48**) then
`172278 ms` (**2:52**). Recovered on its own (stream restartable; no pod restart).

Evidence captured:
- **I/O-starvation tell present:** `get_media_status` → `healthy: true`, `restarts: 0`; **simultaneously**
  `get_cluster_health` → `Liveness probe failed ... GET /health: context deadline exceeded` at `00:32:59Z`.
  Alive but I/O-blocked, not crashed (matches the segment-scan tell documented below).
- **Ruled OUT — scheduled scans:** every heavy Jellyfin task ran its off-hours slot (`02:00`–`06:00`);
  **zero** scan/task activity in the 19:xx–20:xx pod-log window. The Master Schedule is being honored.
- **Ruled OUT — competing downloads:** at recovery SABnzbd `Idle` (0 items), Sonarr & Radarr queues empty.
  (Caveat: snapshot was ~3 min post-recovery; a job finishing *exactly* at 20:32 can't be fully excluded.)
- Earlier 19:25–19:54 session was a *transcode* (Pride & Prejudice 2160p HEVC → libfdk_aac); Kill Bill
  attempts at 20:01/20:32 were **direct play** (source read straight off NFS, no transcode buffer).

**Update 2026-06-16 ~22:17 EDT (cluster-ops verified live during a 3rd drop):**
- **Mount IS `soft` — the fix is live** on the running pod (age 22h, 0 restarts, pinned pi-k3s):
  `192.168.1.61:/cluster/media/video ... nfs4 (ro,...,soft,proto=tcp,nconnect=4,timeo=600,retrans=2,addr=192.168.1.61)`.
  **The "still on old `hard` mount" sub-theory is DISPROVEN.**
- **No wedge present:** live read test ran **70 → 202 MB/s**, clean exit; `dmesg` on pi-k3s shows NO recent
  "not responding, still trying" (only old pre-fix entries from Jun 15 22:05). Destructive recovery was
  correctly **NOT** run — nothing to unwedge.
- **Drops hit at VARYING positions** → rules out file-specific corruption. Tonight: `1:48` (108507ms),
  `2:52` (172278ms), then a **clean ~96-min session**, then a deep stop at **1:36:40** (`5799856ms`). The
  `soft` mount is surfacing each transient QNAP hiccup as a stream-death-then-self-recover.
- **iowait smoking gun (Grafana replay, pi-k3s `192.168.1.55:9100`):** an active stream idles at **~5%**
  iowait; at the **20:32 drop iowait SLAMMED to 90% for ~6 min (20:30–20:36)** and at the **22:18 drop to
  50%**, CPU otherwise flat. The Pi's NFS reads were starved → **the QNAP could not serve reads** — not a
  cluster / network / CPU / mount fault. A *sustained 6-min* 90% stall reads more like a heavy QNAP-side
  job than a momentary disk hiccup. **Identifying which QNAP process/disk spiked at 20:32 & 22:18 is the
  open blocker** — pull it via the `qnap-ro` MCP (confirmed healthy; see hypothesis 1 + RESUME below).

**Leading hypotheses (updated 2026-06-17):**
1. **QNAP weak/failing disk — INVESTIGATED, NOT SUPPORTED (2026-06-17).** The promoted data-risk
   hypothesis was checked via `qnap-ro` and does **not** hold up:
   - **System log clean for 7 weeks.** `list_logs` (warning+error) returns only **15 entries total**,
     newest **2026-04-30** — ZERO disk / RAID / SMART / bad-sector / read-error / command-timeout events,
     and **nothing at the 06-16 stall times**. A drive in TLER deep-recovery or reallocating sectors would
     raise QTS System-Event warnings; there are none.
   - **All 3 disks healthy & cool:** WDC WD100EFGX (WD Red 10TB, CMR) at **48 / 49 / 46 °C**, no temp
     alerts; RAID5 intact (`pool_status:-1` / `usable:false` are the documented display quirks, not faults);
     volume 41% used (thick-provisioning confirmed again).
   - **Caveat — raw SMART sector counts are NOT MCP-reachable.** `qnap-ro` exposes disk *temperature +
     status flags* (`get_system_info`, `list_storages`) but NOT reallocated/pending/uncorrectable counts.
     To read those, use `smartctl -a /dev/sd[abc]` over SSH or the QTS UI (Storage & Snapshots → Disk →
     SMART). Given 7 weeks of clean logs + healthy temps + intact RAID, raw-SMART is belt-and-suspenders,
     not urgent.
   - **MCP access note:** `qnap-ro` did NOT auto-connect this session (Claude launched without `mcp-auth`
     in its env — the `claude()` zsh guard only fires on a terminal launch, not GUI/IDE). Reached it
     **directly via JSON-RPC over HTTP** with no Claude restart: `op read "op://pi-cluster/QNAP NAS/
     MCP_Token_ReadOnly"` → `POST http://qnap-mcp.lab.mtgibbs.dev:8442/mcp` (initialize → grab
     `Mcp-Session-Id` header → notifications/initialized → tools/list → tools/call). This is the reliable
     fallback when the in-process MCP client isn't connected.
2. **Soft-mount timeout AMPLIFIES a hung read — MITIGATED 2026-06-18.** `soft,timeo=600(=60s),retrans=2`
   turned a single slow QNAP read into a multi-minute freeze (~60s × retries before EIO). Shortened
   `timeo`→`150` (15s/attempt; commit `69181d4`, verified live) so a hang errors ~4× faster → blip, not
   freeze. Do NOT revert to bare `hard` (reintroduces the permanent wedge). `retrans=2` still multiplies
   before EIO — drop to 1 for a harder ceiling if 15s-class blips still drop Infuse.
3. **Immich on the same spindles — RULED OUT (2026-06-17).** `immich-server` is **replicas: 0** (scaled
   to zero) and ML is off (`machine-learning.enabled: false`); only `immich-postgresql` (idle) + `valkey`
   run. The server that does all photo I/O isn't running, so Immich **cannot** be driving the evening
   iowait (the pg/valkey restarts are incidental). **Config drift to note:** the HelmRelease declares
   `server.enabled: true` (wants 1 replica) but live is 0 — a manual scale-down not in Git, or Flux not
   reconciling immich. Worth a look, but a separate issue from the stream drops.

**▶ STATUS (2026-06-18) — ROOT CAUSE FOUND: QNAP HDD Standby spin-down. Two-layer fix in place.**
The drops are **HDD spin-up latency**, not a failing disk and not a "burst the array can't sustain."
QNAP **Disk Standby was enabled with a 30-min timer** (`Disk StandBy Timeout = 30`, confirmed via SSH).
Infuse front-loads a huge buffer then **coasts 30+ min with zero reads** (measured: QNAP idle during the
coast) → the 3 disks **spin down** → the next refill read hits **cold disks** → spin-up (~15–30 s, RAID5
staggered = longer) **hangs the NFS read** → pi-k3s iowait pins ~90%, RX collapses to 0 → on the old 60 s
mount timeout the freeze ran to minutes → drop. This fits **every** datapoint (healthy SMART, idle CPU,
no logged event, 0 TCP retransmits, intermittent, "fine on short movies"). **Fixes (2026-06-18):**
(1) **Disk Standby DISABLED** on the QNAP — removes the cause; (2) `timeo=600→150` on `jellyfin-video-nfs`
(commit `69181d4`) — backstop so any future read-stall errors in ~15 s, not 60 s. **Confirm:** watch a few
long movies that coast >30 min; expect zero drops + no `NodeIOWaitStall`. Full detail in the subsection below.

**Diagnostics status:**
- [x] **Fix is live** (2026-06-16, cluster-ops): mount confirmed `soft,nconnect=4,timeo=600,retrans=2` on
      the running pod; reads 70–202 MB/s; no wedge in dmesg. "Still on hard mount" disproven.
- [x] **iowait replay** (2026-06-16): I/O-bound fingerprint confirmed — 90% @ 20:30–20:36, 50% @ 22:18,
      CPU flat → QNAP-side read stall, not cluster/network/CPU/mount.
- [x] **`qnap-ro` MCP triaged** (2026-06-16): server healthy (HTTP 200); "offline" was `mcp-auth` not
      loaded into the launch shell. Fixed `~/.zshrc` (added `MCP_AUTH_LOADED` flag + `claude()` guard).
- [x] **QNAP disk health via `qnap-ro`** (2026-06-17, direct HTTP): logs clean 7 wk (no disk/RAID/SMART
      events), disks 46–49 °C no alerts, RAID5 intact, 41% used. **Disk-failure hypothesis NOT supported.**
      Raw sector counts not MCP-exposed (SSH/UI only); QPKG footprint minimal (no indexer/AV scan job).
- [x] **QNAP load correlation** (2026-06-17): CPU idle (~0.3 load / 4-core) through both stalls → pure
      iowait, not QNAP CPU/process. NOTE: `query_top_processes` returns empty even live — tool unusable here.
- [x] **Cluster-side iowait attribution (2026-06-17)** — chased every discrete competing-job candidate;
      ALL ruled out for the 06-16 20:32 / 22:18 EDT window:
      - **Downloads/imports** — Sonarr last import `06-15 14:30Z`; Radarr last `06-16 02:58Z` (=06-15
        22:58 EDT), nothing on 06-16 evening; backups weekly-Sunday (last 06-14); SAB idle at recovery. A
        download finishing "exactly at 20:32" would fire an *arr `downloadFolderImported` — none exists.
      - **Immich** — server scaled to 0. **QNAP** — disk healthy, CPU idle, no indexer job.
      - **Plex** — DEAD. `plex-external` endpoint `192.168.1.53:32400` (legacy "external Pi 3") does not
        respond (no ping, conn timeout). Plex was replaced by Jellyfin Dec 2025; Pi 3 decommissioned May
        2026. `clusters/pi-k3s/external-services/plex.yaml` is STALE config (Endpoint+Svc+Ingress+TLS for
        nothing) — candidate for deletion.
- [x] **Live capture + instrumentation (2026-06-17)** — deployed alert `NodeIOWaitStall` (>30% iowait 5m →
      Discord) + Grafana dashboard `media-nfs-health` pairing **iowait × NIC-RX** (commit `6f4e1af`, verified
      rendering). Captured the real crash in Prometheus → **mid-stream NFS read-hang** (RX collapses + iowait
      pins; NOT a "burst the array can't sustain").
- [x] **ROOT CAUSE + fix (2026-06-18):** QNAP **Disk Standby (30-min spin-down) DISABLED** — it spun the
      disks down during long Infuse coasts; the refill read then hung on spin-up. Backstop: `timeo=600→150`.
- [ ] **Confirm the fix:** watch a few long movies that coast >30 min — expect zero drops and no
      `NodeIOWaitStall`. If drops persist, re-open (drop `retrans` to 1; recheck for any other idle-spindown).

### Confirmed failure model — HDD-standby spin-up hang (root cause found 2026-06-18)

**Root cause:** QNAP **Disk Standby** was enabled with a **30-minute** spin-down timer
(`Disk StandBy Timeout = 30`, confirmed via SSH `getcfg`/`uLinux.conf`). The chain:

1. **Byte path:** `QNAP →(NFSv4.1)→ pi-k3s/Jellyfin →(HTTP)→ Apple TV` (no direct Apple TV↔QNAP path —
   only the 3 K3s nodes hold NFS/2049 connections). During an active read pi-k3s `eth0` RX ≈ TX (pure
   pass-through, no transcode).
2. **Infuse front-loads a huge buffer (~12 GB) then COASTS** — between bursts pi-k3s RX, QNAP TX *and*
   the QNAP disks all go idle (measured: QNAP `eth2` ~2 pkt/s during a 45-min coast).
3. **Coast > 30 min → the 3 disks spin DOWN** (standby timer fires).
4. Buffer drains → Infuse issues the next **refill read → it hits cold disks → the array spins them back
   up** (~15–30 s, RAID5 staggered = longer). The **NFS READ RPC hangs** during spin-up.
5. Jellyfin's read thread blocks **uninterruptible (D-state)** → pi-k3s **iowait pins ~90% while RX
   collapses to ~0** (iowait = *waiting*, not throughput) → the stream can't advance → Infuse's buffer
   drains → drop. The old `soft,timeo=600(60s),retrans=2` mount **amplified** the spin-up wait into a
   multi-minute freeze before EIO.

**Clean capture (Prometheus, "Bad Guys 2", 2026-06-17 13:12 EDT):** steady stream ~6% iowait /
~11.7 MB/s RX, then at 13:12 RX **collapsed** (11.7→0.06) while iowait **pinned ~92% for 8 min**; SD card
stayed 3%. Jellyfin logged `/health "task was canceled"` (alive but I/O-blocked) then `Playback stopped`.

**Why this matched every earlier dead end:** healthy SMART (spin-up isn't an error), idle QNAP CPU
(spin-up is mechanical), no logged event, **0 TCP retransmits / 0 NIC errors** (TCP delivered the request —
the QNAP just couldn't answer until the platters were up), and **intermittent** (only when a coast exceeds
30 min then needs a refill — so short / fully-buffered movies "work fine").

**Two-layer fix (2026-06-18):**
- **Removed the cause:** QNAP **Disk Standby DISABLED** (disks never spin down → no spin-up to hang on).
- **Backstop:** `timeo=600→150` on `jellyfin-video-nfs` (commit `69181d4`, live `vers=4.1,...,timeo=150`) —
  any future read-stall errors in ~15 s, a blip not an 8-min freeze.

**Status:** very high confidence (config-confirmed mechanism + textbook symptom), **pending post-fix
confirmation** — watch a few long, coast-prone movies; expect zero drops and no `NodeIOWaitStall`.

**Two instrumentation caveats (learned the hard way 2026-06-17):** (1) **pi-k3s iowait ALONE is noisy** —
brief 40–54% blips self-recover in ~1 min and are often local `/config` (SD-card) writes, not a stream
stall. The real signature is a **sustained (5-min+) iowait PIN with RX collapsing** — exactly what the
deployed `NodeIOWaitStall` (>30% for 5 min) keys on. (2) During **coast** there are no live reads, so a
movie plays fine with everything idle — "it's playing" ≠ "the read path is healthy."

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

### Library Scan Schedule — daily 2 AM (NOT a short interval; see history)

Jellyfin's "Scan Media Library" task (key `RefreshLibrary`, id `7738148ffcd07979c7ceb148e06b3aed`) is the only way to discover *new* titles on NFS (inotify can't). Set the trigger via the Jellyfin API:

```bash
JF_KEY=$(op read 'op://pi-cluster/JellyFin/api-key')
# Daily 2:00 AM. TimeOfDayTicks = 7200s * 1e7. DO NOT use a short IntervalTrigger — see below.
curl -X POST -H "X-Emby-Token: $JF_KEY" -H "Content-Type: application/json" \
  "https://jellyfin.lab.mtgibbs.dev/ScheduledTasks/7738148ffcd07979c7ceb148e06b3aed/Triggers" \
  -d '[{"Type":"DailyTrigger","TimeOfDayTicks":72000000000}]'
```

**History / why NOT a 15-minute interval:**
- 2026-02-11: set to a **15-min interval** (`IntervalTicks: 9000000000`) so new downloads appeared fast (inotify is dead over NFS).
- 2026-05-29: changed to **daily 4 AM** after the 15-min scan was traced to **hard streaming drops mid-movie**. A scan does thousands of *random* metadata reads across 1,100+ files; a movie is one *sequential* read; on the QNAP's 3-disk spinning RAID5 the two **contend for disk seeks** and thrash the heads → a scan that's normally ~11s balloons to **10+ minutes** AND the stream starves and dies. It does **not** show as CPU / network / NAS-CPU load — it's pure seek latency, so don't chase those. Off-hours scheduling removes the collision entirely.
- 2026-06-10: moved **4 AM → 2 AM** in the full media-stack re-stagger (it's only ~11s, so it leads the night and frees the old 4 AM slot). See **Master Schedule** below.

**Tradeoff:** new media now appears after the 2 AM scan, not within 15 min. The proper fix to keep fast discovery *without* the choke is on-import scan triggers from Sonarr/Radarr (host `jellyfin.jellyfin.svc.cluster.local:8096`, `/Library/Media/Updated` with `Updated` type to force a path scan) — once wired, the periodic scan can be dropped. Also enable "Automatically refresh metadata from the internet" in Jellyfin library settings.

### Media Segment Scan — ALSO must be off-hours (same seek-contention trap)

The **Library** scan is not the only seek-heavy scheduled task. The **Media Segment Scan** (`Key: TaskExtractMediaSegments`, `Id: f861734dd71b37f9482b52a820e39013`) — which analyzes files for intro/credit-skip markers — does the *same* random-read thrash across all media and triggers the *same* mid-stream drops on the RAID5.

- **2026-06-09:** found shipping on a **12-hour `IntervalTrigger`** (`IntervalTicks: 432000000000`), which roamed into prime-time evening and starved an active stream (Jellyfin's own `/health` endpoint timed out — `[ERR] A task was canceled. URL GET /health` — and the readiness/liveness probes failed while the 8m38s segment scan ran). Moved off the interval to a `DailyTrigger`; **currently 04:00** as part of the 2026-06-10 contention re-stagger (see **Master Schedule** below for the full, deconflicted picture).

```bash
JF_KEY=$(op read 'op://pi-cluster/JellyFin/api-key')
# Daily 4:00 AM. TimeOfDayTicks = 14400s * 1e7. NOT an IntervalTrigger — it roams into prime time.
curl -X POST -H "X-Emby-Token: $JF_KEY" -H "Content-Type: application/json" \
  "https://jellyfin.lab.mtgibbs.dev/ScheduledTasks/f861734dd71b37f9482b52a820e39013/Triggers" \
  -d '[{"Type":"DailyTrigger","TimeOfDayTicks":144000000000}]'
```

> **Diagnostic tell:** `get_media_status` reports `healthy: true` (pod Ready, 0 restarts) while `get_cluster_health` shows `Readiness/Liveness probe failed ... GET /health: context deadline exceeded`. That contradiction = Jellyfin alive but I/O-starved, not crashed. Check `get_pod_logs` for a long-running `... Scan Completed after N minute(s)` overlapping the `/health` cancellations. **General rule: any scheduled task that does broad random reads must be pinned to an off-hours `DailyTrigger`, never an `IntervalTrigger`.**

#### Measured proof it's disk-wait, not CPU/memory (2026-06-10)

The "pure seek latency" claim above is no longer folklore — it's measured. Replaying a `02:16–02:30 UTC` segment-scan window in Prometheus (node `pi-k3s` = `192.168.1.55:9100`), four signals side by side:

```
Time(UTC)  iowait   user+sys-CPU   load1     jellyfin-mem
           (0–1)    (0–1)          (4 cores) (limit 2560MB)
02:10      0.001    0.056          0.41      550 MB   ← idle baseline
02:16      0.221    0.054          10.7      550 MB   ← scan starts
02:22      0.223    0.051          36.1      574 MB
02:28      0.224    0.057          53.8      600 MB
02:30      0.227    0.056          59.6      707 MB   ← scan peak
02:40      0.001    0.055          1.12      660 MB   ← scan done
```

- **iowait `0.6% → 23%` (~38×)** while **user+system CPU stays flat at ~5%** → the CPU is *waiting on the QNAP*, not computing. Rules out "service slog / CPU-bound."
- **load1 `0.7 → 59.6` (~85×)** with CPU at 5% = the textbook **I/O-bound fingerprint** (load counts `D`-state threads blocked on NFS reads, ~59 of them queued behind the scan's random reads — the stream's sequential read is just one more in that line).
- **memory peaks `707 MB` vs the `2560 MB` limit, 0 OOMKills, 0 restarts** → memory starvation is *not* a factor; don't chase it.

**Replay query** (Grafana proxies PromQL; creds at `op://pi-cluster/grafana` user `admin`, datasource uid `prometheus`):
```bash
PW=$(op read 'op://pi-cluster/grafana/password')
BASE="https://grafana.lab.mtgibbs.dev/api/datasources/proxy/uid/prometheus/api/v1"
# iowait fraction on pi-k3s (avg across cores = 0–1). Swap mode= for user|system to see CPU stays flat.
curl -s -u "admin:$PW" --data-urlencode \
  'query=avg(rate(node_cpu_seconds_total{instance="192.168.1.55:9100",mode="iowait"}[2m]))' \
  --data-urlencode start=<epoch> --data-urlencode end=<epoch> --data-urlencode step=120 \
  "$BASE/query_range"
```

> **Open thread (diagnose later):** a *second* iowait spike with the same flat-CPU/high-load signature appears at `01:38–01:44 UTC` — some other broad-random-read job lands there too; identify it so it doesn't ambush a stream. QNAP-side per-disk queue depth / NFS op latency needs the `qnap-ro` MCP (was timing out 2026-06-10).

## QNAP NFS Disk-Contention — Master Schedule (whole media stack)

The QNAP is a **3-disk spinning RAID5 over NFS**. Random-read jobs (library / subtitle / trickplay / chapter scans) thrash disk seeks and starve sequential streams — see the measured proof above. **Governing rule: only one heavy NFS job starts at a time, never inside the Sunday backup window, never during streaming peak.** Every scheduler below runs `America/New_York`, so all times are local (EDT).

### Windows
- **Streaming peak — NO heavy jobs:** weekdays 17:00–02:00, **weekends all day** (household pattern, confirmed 2026-06-10).
- **Backup window — weekly, leave alone:** **Sunday 02:00–03:34**, the `backup-jobs` CronJob cascade (`pvc`→`postgres`→`worker2`→`media`→`git-mirror`→`unifi`) writing configs to `/share/cluster/backups`. Keep media scans out of it.
- **Dormant maintenance band:** weekday pre-dawn **02:00–06:30** (quiet even on weekend pre-dawn).

### Current staggered schedule (set 2026-06-10)
| Time (EDT) | Job | Service | Task id / settings key |
|---|---|---|---|
| 02:00 daily | Scan Media Library | Jellyfin | `7738148ffcd07979c7ceb148e06b3aed` |
| 04:00 daily | Media Segment Scan | Jellyfin | `f861734dd71b37f9482b52a820e39013` |
| 04:30 daily | Audio Normalization | Jellyfin | `ec2f221fd8e7706b3d3afd2c4591b4d7` |
| 05:00 daily | Extract Chapter Images | Jellyfin | `4e6637c832ed644d1af3370a2506e80a` |
| 06:00 daily | Generate Trickplay Images | Jellyfin | `64f5f44cd30dc273cb9890205473bbcc` |
| Tue 03:00 | Index All Movies Subtitles | Bazarr | `radarr.full_update` |
| Thu 03:00 | Index All Episodes Subtitles | Bazarr | `sonarr.full_update` |

Set any Jellyfin task time (`TimeOfDayTicks` = seconds-past-midnight × 1e7 → 02:00=`72000000000`, 04:00=`144000000000`, 04:30=`162000000000`, 05:00=`180000000000`, 06:00=`216000000000`):
```bash
JF_KEY=$(op read 'op://pi-cluster/JellyFin/api-key')
curl -X POST -H "X-Emby-Token: $JF_KEY" -H "Content-Type: application/json" \
  "https://jellyfin.lab.mtgibbs.dev/ScheduledTasks/<TASK_ID>/Triggers" \
  -d '[{"Type":"DailyTrigger","TimeOfDayTicks":<TICKS>}]'
```

Bazarr full-library subtitle indexes — `radarr`=movies, `sonarr`=episodes; daily→weekly (`_day`: 0=Mon … 6=Sun):
```bash
BZ=$(op read 'op://pi-cluster/mcp-homelab/bazarr-api-key')
curl -X POST -H "X-Api-Key: $BZ" "https://bazarr.lab.mtgibbs.dev/api/system/settings" \
  --data-urlencode "settings-radarr-full_update=Weekly" --data-urlencode "settings-radarr-full_update_day=1" --data-urlencode "settings-radarr-full_update_hour=3" \
  --data-urlencode "settings-sonarr-full_update=Weekly" --data-urlencode "settings-sonarr-full_update_day=3" --data-urlencode "settings-sonarr-full_update_hour=3"
```

### Lower-load / not-movable NFS touchers (know they exist)
- **Bazarr** "Search for Missing Movies/Series Subtitles" (every 6h, roams) + "Upgrade Previously Downloaded" (12h) — moderate, mostly network; left as-is.
- **Sonarr/Radarr** daily maintenance (Refresh Movie/Series, Housekeeping, Clean Recycle Bin) clusters **~00:00–00:40** — times are **app-fixed (not API-settable)**; metadata-only, low load, lives in the late-peak edge.
- **Jellyfin** light `Every24h` cleanups (Clean Cache/Log/Transcode, Update Plugins, Refresh Guide, Download missing subs/lyrics) still anchor to **pod-start (~22:15)** — complete in ~0s, harmless. Pin to a `DailyTrigger` if they ever grow teeth.
- **Immich** photo jobs hit `/cluster/photos` on the **same spindles** — upload-driven + a light nightly job, ML disabled. Low overnight load; verify its nightly time if the photo library grows.

### History
- **2026-06-10:** full media-stack re-stagger. Four collisions found, three fixed (the fourth is app-fixed): (1) **04:00 daily triple-book** — Jellyfin library scan + *both* Bazarr full indexes; (2) **Sunday 02:00–03:34** backups overlapping Jellyfin Chapter Images@02 + Trickplay@03; (3) **Audio Normalization at ~22:15 peak** (roaming `Every24h`); (4) `*arr` midnight metadata cluster (app-fixed, left in place). Backups untouched.

## Jellyfin: Media Not Appearing After Download

**Root Cause A** (new title): NFS inotify — see above. The daily 2 AM scan picks it up (or trigger a manual scan / on-import Sonarr-Radarr scan — see scan-schedule note above).

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

## Jellyseerr (Request Manager) — pinned 2.7.3; "update available" is a FALSE nag

- **URL**: `https://requests.lab.mtgibbs.dev`
- **Pinned**: `fallenbagel/jellyseerr:2.7.3` — the newest **stable** release (from **Aug 2025**).
- **The in-app amber "update available" arrow is a false positive — do NOT chase it.** Jellyseerr's updater counts *commits behind the branch HEAD*, not newer releases. 2.7.3 is the last stable; everything published since is `develop` / `preview-*`. The badge stays amber regardless of what we pin to; the only way to "satisfy" it is to run an unstable build. **Stay on stable.**

### WATCH ITEM: Jellyseerr → "Seerr" rebrand (no action yet)

The project is mid-rebrand from **Jellyseerr** to **Seerr** — see the `preview-seerr` / `preview-rename-tags` tags, and the ~10-month gap with no new stable since 2.7.3. When the successor ships its first **stable** release — possibly under a **new image name** (e.g. `seerr`) — *that* is the trigger to do a real migration (new manifest/image name, check for a config/data migration step). Until then, 2.7.3 is correct. **Treat the next *stable* release as the only real "update" — ignore the in-app nag in the meantime.**

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
