# Jellyfin Streaming Crash — Investigation State & Plan Inputs (handoff 2026-06-22)

**Purpose:** single source of truth for the NEXT (fresh-context) planning session. Consolidates a
multi-day investigation. Companion docs: `docs/recaps/2026-06-22-jellyfin-streaming-drops-resolved-nconnect-and-sd-card.md`
(full arc + commit list) and `.claude/skills/media-services/SKILL.md` (the "PARTIAL" block at the top of the
streaming section).

---

## TL;DR — where it actually stands

Two problems were tangled together for days. Current honest status:

1. **STREAMING CRASHES → REDUCED by `nconnect=1`, NOT cured. ROOT CAUSE OPEN — now pointing CLIENT-SIDE.**
   The residual crash leaves **zero server-side trace** and is **very likely Infuse / Apple TV**, not the cluster.
2. **pi-k3s SD CARD → a real, chronic, SEPARATE issue. NVMe is the fix.** Firmware update did NOT help.
   The SD card does **NOT** kill streaming (proven — streams survive its stalls).
3. **QNAP → healthy the entire time. Fully exonerated.**

---

## The OPEN question (what the plan must target)

**Residual streaming crash:** ~75–110 min into long direct-play movies, **always `Infuse-Direct` on the Apple TV**,
logged only as "Playback stopped reported by app Infuse-Direct" — the server is often **completely unaware**
(the "Drive" crash at 17:48Z had nothing in the Jellyfin/NFS/SD/ingress logs at the crash moment).

- **Random position** (not file/offset-specific): observed at 1:16, 1:19/1:20, 1:32, 1:47.
- **Apple TV is on ETHERNET** (wired) → wifi-drop ruled out by the user.
- **MISSING — the keystone:** the exact **on-screen Infuse/Apple-TV error text** when it drops. Not yet obtained.
  User says "we always get that specific playback error." Getting that text (or a photo) is the #1 next action —
  it identifies the layer (network-to-server vs decode vs server-comms) far better than the clean server logs.

### Crash log (all observed)
| Movie | nconnect | Crash position | Notes |
|---|---|---|---|
| Bad Guys 2 | 4 | ~1:19:57 | original |
| Harvey | 4 | 1:16:54 | reliably died here |
| Harvey | **1** | **PASSED 1:16:54** | survived → nconnect=1 *reduced* it |
| Shawshank | 2/4 | 42 min + 1:47:53 | two drops one evening |
| Hundreds of Beavers | **1** | **1:32:21** | crashed on nconnect=1 (/health timeout aligned) |
| Drive | **1** | **1:20:53** | crashed on nconnect=1; **ZERO server trace** |

---

## RULED OUT (don't re-chase)
- **QNAP** — failing-disk, RAID5, thin-provisioning, SSD-cache, HDD-standby: all dead ends. Logs clean 7+ wk,
  disks healthy, CPU idle through every stall. Deep-research (wf_630caced, 107 agents): verdict TUNE-not-replace.
- **HDD-standby spin-down** — was overstated as "confirmed," dialed back, then REFUTED (recurred with standby off,
  during steady reads). Do not revisit.
- **SD card as the stream-killer** — REFUTED: streams survived SD stalls of `procs_blocked=8` and `=10` mid-playback
  (Harvey 16:21/16:36; Drive session 21:25/21:32). SD stalls are real but don't kill the stream.
- **Firmware (Nov-2025 EEPROM) as SD fix** — did NOT help: ~2 SD stalls/hr post-firmware = baseline rate.
- **wifi** — Apple TV is wired.
- **nginx ingress timeout / WebSocket drops** — the WS-drop log lines were NON-correlated (an hour+ before crashes);
  Infuse appears to connect ~directly (no jellyfin ingress access-log hits). Red herring.
- **iowait%/load as signals** — MISLEADING on a near-idle Pi (inflate from transient D-state churn). Use
  `node_procs_blocked` (0 baseline → 5–25 real hang) + **kernel stacks** as ground truth.

---

## Infrastructure changes made (all committed to main, this arc)
- **NFS mount (`jellyfin-video-nfs`):** `nconnect 4→2→1` (`9daa205`,`18de740`), `timeo 600→150` (`69181d4`).
  `mountOptions` are MUTABLE (patch in place + `rollout restart`); only `nfs.server`/`nfs.path` need the
  suspend→delete→recreate swap (corrected in `affe330`; flux-gitops.md updated). **NB: `nconnect` is fixed at the
  export's FIRST mount — a rolling restart reuses the old transport; must fully release the mount (scale to 0) to change it.**
- **kiwix-zim-nfs:** brought to read-only soft-mount standard (`b4e9d80`).
- **Immich:** PARKED (`53e5b34`) — server+valkey disabled, postgres replicas 0; PVCs retained.
- **Plex:** dead config removed (`73208f8`).
- **Monitoring:** Prometheus retention `7d/2GB→21d/7GB`, PVC `5Gi→10Gi` (`bba5481`); alerts rebuilt around
  `procs_blocked` — `MediaNFSReadHang` + `NodeIOWaitSustained` (`29ab46b`); `media-nfs-health` dashboard (`6f4e1af`).
- **EEPROM firmware:** all **3 Pi 5s updated Jun-2025 → Nov-2025** (pi-k3s `.55`, worker-1 `.56`, worker-2 `.57`).
  Pi 3 (`.51`) has no EEPROM. Done DNS-safe, one node at a time; pi-k3s's flaky SD survived the reboot.
- **Skill/recap:** corrected RESOLVED→PARTIAL (`1745d62`); recap `96ea0d2` (note: recap text still says "RESOLVED" — superseded).

---

## Live instrumentation (running now)
- **Recorder v2:** `/usr/local/bin/nfs-hang-recorder.sh`, systemd `nfs-hang-recorder.service` on pi-k3s,
  logs `/var/log/nfs-hang-recorder.log`. Triggers on `procs_blocked>=2` OR a `jellyfin/ffmpeg/dotnet` thread in
  D-state (v1's `>=4` MISSED few-process NFS stalls — that's why "classifier 0 NFS" was an artifact). Reboot-persistent.
  **Caveat: the `xgap` field in the log is BUGGY (computes the wrong xprt columns) — ignore it.**
  So far every captured event is the SD card (`jbd2/mmcblk0p2` + `mmc_blk_rw_wait` + `mmc_sd_detect`/`mmc_rescan`),
  `jf_dstate=0` — i.e. it catches SD stalls but the streaming crash itself has not produced a captured D-state event.
- Alerts: `MediaNFSReadHang`, `NodeIOWaitSustained` (monitoring ns). Dashboard: `media-nfs-health` (Grafana).

---

## Access notes (for the next session)
- **pi-k3s SSH:** `mtgibbs@192.168.1.55`, **passwordless sudo**, use `sudo k3s kubectl`. Master node.
- **Other nodes:** worker-1 `mtgibbs@192.168.1.56` (direct); worker-2 `192.168.1.57` is **SSH-blocked from the Mac**
  (fail2ban from earlier auth storms?) — reach via **ProxyJump:** `ssh -J mtgibbs@192.168.1.55 mtgibbs@192.168.1.57`;
  pi3 `.51` (no NVMe-capable, no EEPROM).
- **QNAP:** `mtgibbs@192.168.1.61`, password `op://pi-cluster/QNAP NAS/password`, **password-only auth, PTY needed for sudo** —
  but **also blocked from the Mac** (same fail2ban pattern). Healthy; reachable from the cluster.
- **Grafana/Prometheus:** `op://pi-cluster/grafana/password`, `https://grafana.lab.mtgibbs.dev`, datasource proxy uid `prometheus`.
- **GOTCHA — 1Password SSH agent locks intermittently** → Mac SSH fails with `agent refused operation / too many
  authentication failures`. Fix: unlock 1Password. Don't retry-spam (re-trips the lockout).
- **DNS layout (for any reboots):** pihole+unbound PRIMARY on pi-k3s `.55`, SECONDARY on worker-1 `.56`. Reboot order
  must never down both. Both verified serving. pi-k3s also has static fallback (1.1.1.1/8.8.8.8) for its own boot.

---

## NVMe migration — plan inputs (pi-k3s SD-card fix)
- **No SSD installed yet.** `lsblk` shows only the SD card (`mmcblk0`, 59.5G, ~36G used). No NVMe, no USB storage.
  PCIe shows only the Pi 5's own chips. `BOOT_ORDER=0xf461` (SD first).
- **Slot type UNKNOWN** — user has "a mount with a little SSD slot in the bottom," **no HAT**. Could be M.2-NVMe (PCIe)
  or 2.5" SATA (USB). **Action: ID via photo or the mount's product name** (software can't see an empty slot).
- **Drive to buy: 256 GB mainstream TLC.** If M.2: must be **M-key NVMe** (not M.2-SATA). If 2.5": any mainstream SATA SSD.
- **Migration shape (once installed + detected):** (M.2: enable PCIe in config.txt) → clone SD→SSD (whole disk, brings
  k3s datastore + `/config`) → set `BOOT_ORDER` to prefer NVMe/USB over SD → reboot, verify `/` on SSD → validate SD
  `jbd2/mmc` stalls drop to zero (recorder confirms) → **keep the SD card as instant fallback.**
- **Note:** firmware is already Nov-2025 (improves Pi 5 NVMe/USB boot) — prerequisite done.
- SD-speed-cap (the cheaper alt) is **NOT safely scriptable** for the Pi 5 boot device (legacy `sdtweak`/`overclock_50`
  overlays don't apply to the BCM2712 SD controller) — NVMe is the clean path.

---

## NEXT STEPS (for the plan)
1. **STREAMING CRASH (primary): chase it CLIENT-SIDE.**
   - **Get the exact on-screen Infuse error text** (the keystone — still missing).
   - **Test: Jellyfin app on the SAME Apple TV** for a long movie → isolates Infuse-the-app from device+network.
   - Check **Infuse settings** (streaming-cache/buffer size, background playback) and **Apple TV** memory/sleep.
   - The cluster is exonerated — do NOT keep digging server-side (it's clean at the real crash).
2. **SD CARD (separate, no urgency): NVMe migration** — ID slot, buy 256 GB SSD, clone+boot-order migrate.
3. **Keep the recorder running** as a host-side tripwire (it'll stay quiet, corroborating client-side).
4. **Confidence:** `nconnect=1` is a keeper (clear reduction) even though not a full cure — don't revert it.
