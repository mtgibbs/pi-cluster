# 2026-11-07 — Jellyfin "locked up": NFSv4.1 session stall → thread-pool starvation

**Status:** self-recovered 22:34 EST; durable fix = pin `nfsvers=3` on `jellyfin-video-nfs` + new
`JellyfinThreadPileup` alert. Same family as the June streaming drops
(`2026-06-22-streaming-crash-handoff.md`), and this is the first capture with full evidence.

## Timeline (EST; Prometheus 2-min samples + pod logs + on-node recorder)

| Time | Event |
|---|---|
| 22:15 | Infuse-Direct (Apple TV) resumes *Exit 8*; NFS rx burst 23.6 MB/s at 22:19 |
| ~22:20 | NFS rx → 0.1 MB/s (flat). `/health` → "A task was canceled" at 22:20, 22:25, 22:30 |
| 22:17→22:33 | Jellyfin `container_threads` 22 → 28 → 40 → 55 → 73; node load1 4 → 51 |
| 22:30 | Infuse gives up: "Playback stopped … Exit 8 at 2884840 ms" |
| 22:31 | Readiness probe fails (`context deadline exceeded`) → pod pulled from the Service = UI gone |
| 22:34:01 | kernel: `NFS: 192.168.1.61: lost 1 locks` (NFSv4 lease expired → state recovery) |
| 22:34–35 | Everything unblocks: threads 24, load decays, new playback starts. No restart (count 3, last 10-12 node reboot) |

## Evidence

- **Not the SD card:** `mmcblk0` io_time ≈ 0 throughout; CPU 93% idle. The recorder's SD (`mmc_*`) events
  that evening were brief (8–9 s) and are the separate chronic issue.
- **Not CPU / memory / network:** pi-k3s → 192.168.1.61 ping 0.28 ms, `:2049` open, 3.5 GB available.
- **NFS transport:** recorder `xprt` line at 03:32Z shows `sends 822909 / recvs 822879` — **30 RPCs sent and
  never answered** on the single (`nconnect=1`) connection, while TCP stayed up.
- **v4 state, not a timeout:** the mount is `soft,timeo=150,retrans=2` — a v3-style per-RPC timeout should have
  returned EIO within ~45 s. It didn't: no "not responding / timed out" in dmesg; the stall ended only with v4
  lease recovery (`lost 1 locks`). NFSv4.1 operations ride a session (slot table + lease); when the server stops
  answering on the session, the client waits on session/state recovery, which `timeo` doesn't bound.
- **Why the whole server "locks up":** Jellyfin's media reads are synchronous; blocked reads pin .NET thread-pool
  threads, the pool slowly injects more (22 → 76), and every other request, `/health` included, queues behind them.
- **Why the alerts stayed silent:** `MediaNFSReadHang` needs `procs_blocked>=4` + iowait > 40%. Here
  `procs_blocked` was 1 (one process, many threads) and iowait was low. The alert couldn't see this failure mode.
- **Frequency:** over 21 days of `container_threads`, this was the only pile-up above 50; earlier "lockups" are in
  the June docs.

## Fix (PR)

1. `jellyfin-video-nfs`: `nfsvers=3`. Stateless means no session, lease or recovery, so `soft,timeo=150,retrans=2`
   bounds every READ and a QNAP hiccup becomes a short EIO and retry instead of a 16-min freeze. QNAP serves
   v3 (`rpcinfo`: nfs 2/3/4, mountd 1–3). A test mount from pi-k3s with the exact options read 300 MiB at
   113 MB/s. `nolock` is already set, so NLM isn't needed.
2. `JellyfinThreadPileup` alert: `min_over_time(container_threads{jellyfin}[5m]) > 50`. Positive control:
   true only at 11-07 22:31 in 21 days of history; the scheduled-task peaks (02:00–05:00) max at 44.

**Rollout:** the NFS version is fixed at first mount. After Flux applies the PV, `rollout restart` the
deployment (strategy `Recreate` releases the old mount) **when nobody is streaming**, then confirm
`vers=3` in `/proc/mounts` on pi-k3s.

## Open

- **QNAP side:** why its NFSv4.1 server stopped answering one session for ~16 min while serving TCP. Pull the
  QNAP NFS/system log for 2026-11-07 22:15–22:35 EST via the `qnap-ro` MCP. If v3 stalls too, the cause is
  server-side and protocol-independent.
- Rollback: drop `nfsvers=3` (back to auto-negotiated v4.1) and do the same restart.
