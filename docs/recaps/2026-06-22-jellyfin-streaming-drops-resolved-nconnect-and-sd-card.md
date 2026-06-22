# Recap — Jellyfin streaming drops resolved: NFS `nconnect` stuck-connection + SD card separated (2026-06-18 → 2026-06-22)

Picks up from the 2026-06-18 recap, which closed with a "leading hypothesis" of QNAP HDD Standby
spin-up as the cause of streaming drops. That hypothesis was wrong. This session ran through another
four days of wrong turns before a continuous on-node recorder finally separated two independent
problems that had been tangled together the whole time. It is a candid account; that's the point.

---

## 1. The resolution (read this first)

Two independent problems were tangled together. Untangling them required separating what was causing
the stream drop from what was just confounding the signal.

### Problem 1 — streaming drops: NFS `nconnect` stuck-secondary-socket (FIXED, commit `18de740`)

On `nconnect=4` and `nconnect=2`, one of the parallel NFS TCP connections intermittently wedged —
RPCs being sent but never answered, piling up on connection #2 while connection #1 served reads at
90–107 MB/s. This matches the NFS-Ganesha #1374 pattern: a single stale/stuck connection in a
multi-connection NFS session blocks reads that land on it, starving the stream while the underlying
array is completely healthy.

The fix was `nconnect=4 → 2 → 1` across two commits (`9daa205`, `18de740`). A single NFS TCP
connection cannot have a stuck secondary — the failure mode no longer exists.

**Proof (2026-06-22):** "Harvey" (4K remux, ~70 Mbps direct-play) was the historical test case —
it had reliably dropped at the 1:16:54 mark on `nconnect=4`. On `nconnect=1` it sailed past
1:16:54 and kept streaming. n=1, but against a movie with a documented crash point, that's
strong evidence.

### Problem 2 — pi-k3s SD card: real and chronic, but does NOT kill the stream

A continuous on-node recorder running on pi-k3s on 2026-06-22 caught 7 hang events with kernel
stacks. Every single one traced to the local SD card:

- `jbd2/mmcblk0p2` (ext4 journal flush) blocking on `mmc_blk_rw_wait`
- `mmc_sd_detect` / `mmc_rescan` — the card was dropping off the MMC bus and forcing a
  re-detection, stalling all local writes (k3s datastore, pihole state, `/config` volume)
  for approximately 9 seconds before silently recovering

Classifier across all 7 events: jbd2/mmc = 37, NFS/rpc = 0.

Crucially: Harvey survived TWO of these SD stalls mid-stream (at 16:21 and 16:36, NFS rx at 8.94
and 7.08 MB/s respectively). The SD card stalls are not stream-killers; they were a confounding
signal that inflated iowait% and D-state counts on the same node we were watching for NFS hangs.

**Likely cause:** healthy SanDisk high-endurance card (under 6 months old) running at SDR104/200
MHz on a Pi 5 with a stale EEPROM (Jun 2025 bootloader). Marginal high-speed MMC signaling, not
wear — there are no logged mmc errors, and the card hangs ~9 seconds then silently recovers without
a CRC complaint. The Nov 2025 EEPROM firmware tightens the SD interface timing.

**Fix (cluster health, not streaming):** EEPROM firmware update on all 3 Pi 5 nodes (currently
Jun 2025, target Nov 2025), then cap SD speed or move pi-k3s (and ideally the workers) to NVMe
boot. All 3 Pi 5s are on the same stale bootloader, all boot from SD. The SD card backs the k3s
datastore, pihole, and `/config` — cluster health at risk even though streams survive for now.

---

## 2. The wrong turns (in order)

The prior recap closed with the QNAP HDD Standby hypothesis as "leading, not confirmed." That was
already an improvement over the initial "ROOT CAUSE CONFIRMED" overclaim that had been walked back.
What followed was a further four days of wrong-but-reasonable turns.

### 2a. "Confirm by absence" strategy fails silently

After the 06-18 recap, the plan was to watch a few coast-prone movies and see if drops recurred —
confirm by absence, or catch a recurrence. Drops did recur. The HDD Standby hypothesis was already
dead at that point, but the absence signal was ambiguous long enough to delay the pivot.

### 2b. deep-research workflow on QNAP architecture (wf_630caced, ~107 agents)

A deep-research run on QNAP NFS-Ganesha architecture came back with verdict TUNE-not-replace:
the QNAP was not the problem; the cluster configuration was. This was correct. It also flagged two
specific things that turned out to be exactly right:

- NFS-Ganesha #1374 — parallel `nconnect` connections can get stuck/stale on a marginal server,
  and for single-threaded sequential reads (Jellyfin direct-play), `nconnect` gives no throughput
  benefit anyway (Azure NFS guidance). The analog to the Jellyfin hang was nearly exact.
- jbd2 hung-task signatures as a possible Pi-side confound.

The research run correctly identified the `nconnect` risk. The mistake was not immediately treating
it as the primary suspect — instead it was staged as a "low-cost reversible experiment" alongside
the iowait investigation.

### 2c. `timeo=600 → 150` (commit `69181d4`)

Already applied in the 06-18 session. A backstop that made hangs fail faster, but did not fix them.

### 2d. "Burst-buffer the RAID5 can't sustain" failure model

An early hypothesis from the 06-17 live capture (The Bad Guys 2) described the failure as the array
being unable to sustain a burst read. This was wrong. The commit `ce31465` recorded it; the
subsequent investigation corrected it. The array was healthy throughout; the read-hang was a stuck
NFS connection, not a throughput ceiling.

### 2e. HDD Standby spin-down (commits `e06047b`, `3440169`)

Documented fully in the 06-18 recap. Commit `e06047b` used "ROOT CAUSE CONFIRMED"; commit
`3440169` dialed it back to "leading hypothesis" after the user pushed back. The hypothesis was
then REFUTED: drops recurred during steady reads (The Shawshank Redemption, 2026-06-21, two hangs
at 8:25 PM and 9:40 PM), which keep platters spun up. A disk that's actively being read cannot be
in standby. Standby was wrong.

### 2f. Two explicit self-corrections

**"Infuse reads directly from QNAP"** — wrong. pi-k3s eth0 RX ≈ TX during active reads proves
Jellyfin is a pure pass-through proxy. Corrected in `ce31465`.

**"iowait is just an artifact"** — stated after misreading a `ps` output caught at the recovery
edge (everything looked healthy because the hang had just cleared). Refuted within minutes when
`node_procs_blocked` data showed genuine D-state pileups (5–25 blocked processes) during every
real hang — D-state threads don't lie. Corrected in commit `29ab46b` and in the alert rebuild.

### 2g. Mac-to-QNAP SSH reachability rabbit hole

A Mac→QNAP SSH session got stuck in an ARP-resolves-but-IP-drops failure mode. Unrelated to the
investigation; diagnostically a dead end. Too much time was spent on it before pivoting back to
pi-k3s SSH, which worked fine.

### 2h. Prometheus retention too short (commit `bba5481`)

The 2 GB size cap was pruning Prometheus to ~3 days — too short to look back far enough at the
01:38–01:44 UTC mystery iowait spike or to compare across multiple hang events. Bumped to 21d/7GB,
PVC from 5Gi to 10Gi (2026-06-19). local-path storage has no in-place expansion, so this required
an Operator StatefulSet + PVC recreate with a brief Prometheus restart and ~3 days of metrics lost.
Necessary and worth it.

### 2i. iowait% as the primary hang signal

Throughout this investigation, `node_cpu_seconds_total{mode="iowait"}` was the main hang
indicator. It is a misleading metric on a near-idle Pi: on a 4-core node with only 1–2 active CPUs,
a single blocked thread can inflate iowait% substantially. Brief 40–54% blips self-recovered in
under a minute and were often local SD-card write flushes rather than NFS stalls. Chasing every
iowait spike cost significant time.

---

## 3. The instrument that cracked it

All of the above wrong turns shared a common failure mode: every manual SSH probe was a
point-in-time snapshot. These hangs cleared in 1–18 minutes. Every hand-timed probe caught the
recovery edge, not the hang itself. Things looked healthy because they had just recovered.

What finally worked was a continuous on-node recorder: `/tmp/hang-recorder.sh`, running on pi-k3s
at 8-second sampling. On every sample, it checks `node_procs_blocked`. If it reaches 4 or more, it
immediately dumps:

- `procs_blocked` count
- live `mountstats xprt` for the NFS connection (bytes sent/received per TCP slot, retransmit counts)
- D-state kernel stacks for all blocked processes (`/proc/PID/stack` for anything in D state)

The 2026-06-22 run caught 7 events with kernel stacks. The D-state stacks all showed
`jbd2/mmcblk0p2` / `mmc_blk_rw_wait` — the SD card journal, not NFS. The NFS xprt in the same
window showed `connection #2: sent=N, received=N-2` on `nconnect=2` — confirming the stuck-secondary
pattern that commit `18de740` fixed based on the 2026-06-21 Shawshank captures (which had caught
the xprt fingerprint before the recorder was built).

**The key methodological lesson:** self-clearing ~1–18 minute events are invisible to manual SSH.
Only a continuous recorder that triggers on the condition and captures immediately can separate two
overlapping problems on the same node. Point-in-time looks at an already-recovered system.

---

## 4. Alert and monitoring changes (commits `6f4e1af`, `57a3851`, `29ab46b`, `bba5481`)

The monitoring stack evolved significantly across this arc:

**`NodeIOWaitStall` → `NodeIOWaitSustained` + `MediaNFSReadHang` (commits `6f4e1af`, `57a3851`, `29ab46b`):**

The initial alert (`NodeIOWaitStall`, commit `6f4e1af`) was iowait-only — >30% for 5 minutes.
This was too noisy (SD-card flushes can inflate iowait on a near-idle Pi) and too slow for live
capture during a hang that clears in ~9 seconds.

Rebuilt (commit `29ab46b`) around `node_procs_blocked`:

- `MediaNFSReadHang`: gates on `max_over_time(node_procs_blocked[2m]) >= 4` AND iowait; fires in
  ~1 minute. Much faster, much more specific. Annotation lists exactly what to capture: xprt data,
  `/proc/PID/stack`, `dmesg`, `mountstats`.
- `NodeIOWaitSustained`: replaced the old `NodeIOWaitStall`; now also requires `procs_blocked >= 1`
  as corroboration so it cannot fire on a pure per-CPU iowait accounting artifact. Informational.

The `procs_blocked` signal is ground truth: 0 baseline for 30 hours of monitoring, then 5–25
during every real hang. It cannot be faked by per-CPU accounting inflation.

**Prometheus retention bump (`bba5481`):** 7d/2GB → 21d/7GB, PVC 5Gi → 10Gi. See 2h above.

---

## 5. Other housekeeping (commits `b4e9d80`, `affe330`, `17179a0`)

**kiwix-zim-nfs brought to the read-only soft-mount standard (commit `b4e9d80`, 2026-06-18):**
The kiwix PV had only `nolock` — effectively a `hard` mount that would wedge "server not
responding, still trying" forever on a NAS stall, the same failure class the jellyfin soft-mount
fixed in June 2026-06-15. Added `soft,timeo=150,retrans=2,nconnect=4` to match the read-only
standard. Applied in place (mountOptions is mutable; Flux patched the bound PV; `rollout restart`
remounted; verified via `mount` in the running pod).

**`mountOptions` mutability doc (commit `affe330`):** confirmed and documented that `mountOptions`
can be patched on a bound PV. Only `nfs.server` and `nfs.path` are truly immutable. This avoids
unnecessary PV-delete surgery on future option changes.

---

## 6. Summary table — state at close (2026-06-22)

| Component | State | Notes |
|---|---|---|
| Jellyfin streaming drops | **RESOLVED** | NFS `nconnect` stuck-secondary fixed by `nconnect=1` (`18de740`) |
| `jellyfin-video-nfs` mount options | `soft,timeo=150,retrans=2,nconnect=1` | In place; verified via `mount` in pod |
| pi-k3s SD card | Chronic, separate issue | Does NOT kill stream; Harvey survived 2 mid-stream SD stalls |
| Harvey crash-point test | PASSED at 1:16:54 on `nconnect=1` | n=1; worth 2–3 more 4K runs to call bulletproof |
| QNAP health | Clean throughout | All QNAP hypotheses were dead ends; the QNAP was healthy the entire time |
| QNAP Disk Standby | Disabled (06-18) | Low-risk change; made no difference to the drops |
| `MediaNFSReadHang` alert | Live | `procs_blocked >= 4` + iowait; fires ~1 min |
| `NodeIOWaitSustained` alert | Live | Replaced `NodeIOWaitStall`; gated by `procs_blocked >= 1` |
| `media-nfs-health` Grafana dashboard | Live | iowait × NIC-RX discriminator |
| Prometheus retention | 21d/7GB, PVC 10Gi | Was 7d/2GB (~3d actual); bumped 2026-06-19 |
| `kiwix-zim-nfs` mount | `soft,timeo=150,retrans=2,nconnect=4` | Brought to standard from bare `nolock` |
| `/tmp/hang-recorder.sh` | Running on pi-k3s (ephemeral) | Will not survive a reboot — the EEPROM update will clear it |

---

## 7. Open items

- [ ] **Streaming fix confidence:** worth 2–3 more 4K direct-play sessions (long films, various titles)
  to call `nconnect=1` bulletproof. The Harvey n=1 result is strong but not conclusive.
- [ ] **SD card — EEPROM firmware update on all 3 Pi 5 nodes:** currently Jun 2025, target Nov 2025.
  Run `rpi-eeprom-update -a` on pi-k3s, pi5-worker-1, pi5-worker-2. After update, cap SD clock speed
  or plan NVMe boot migration. The SD card backs the k3s datastore + pihole; cluster health risk.
- [ ] **kiwix `nconnect=4`:** once `nconnect=1` is confirmed on jellyfin, consider whether kiwix
  (worker-node PV) should follow. kiwix is read-only reference traffic, not streaming — the
  stuck-secondary pattern matters more for long-lived sequential reads.
- [ ] **01:38–01:44 UTC mystery iowait spike:** a second broad-random-read job lands in that window
  every night; has not been identified. Now that Prometheus has 21-day retention this can be
  replayed and attributed. Identify before it ambushes a stream.
- [ ] **`/tmp/hang-recorder.sh` ephemeral:** the recorder that cracked this is in `/tmp` and will not
  survive a reboot (and the EEPROM update requires a reboot). Document or persist the script before
  the firmware update if continuous SD monitoring is wanted post-update.

---

## Commits

| Hash | Subject |
|---|---|
| `b4e9d80` | fix(kiwix): bring kiwix-zim-nfs to the read-only soft-mount standard |
| `affe330` | docs(flux,media): mountOptions is mutable; NFS mount is v4.1 not v3 |
| `bba5481` | feat(monitoring): bump Prometheus retention 7d/2GB → 21d/7GB, PVC 5Gi → 10Gi |
| `57a3851` | feat(monitoring): add MediaNFSReadHang alert |
| `9daa205` | fix(jellyfin): NFS nconnect 4→2 — deep-research flags parallel TCP as a single-stream read-hang risk |
| `29ab46b` | fix(monitoring): rebuild NFS-hang alerts around node_procs_blocked |
| `18de740` | fix(jellyfin): NFS nconnect 2→1 — two live captures pin stuck secondary connection |
| `2dc1bdf` | docs(media): RESOLVED — streaming drops were NFS nconnect, SD card is a separate chronic issue |
