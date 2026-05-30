# Incident: Jellyfin repeated streaming drops during movie playback (2026-05-29)

- **Date:** 2026-05-29, evening
- **Severity:** Medium — movie unwatchable; service itself stayed up; no data loss
- **Status:** Fix deployed (`cdb894b`). Verification still open — user stopped the movie before
  confirming a clean full playback with the new schedule in place.
- **Detected via:** user reported stream dropping at ~15-minute intervals, then a hard drop at ~7
  minutes.

---

## 1. TL;DR

Jellyfin's scheduled "Scan Media Library" task was configured to run **every 15 minutes** (set
2026-02-11 as a workaround for inotify not working over NFS). A scan does thousands of **random**
metadata reads across 1,100+ files. A movie stream is one **sequential** read. On the QNAP's
**3-disk spinning RAID5**, the two workloads contend for disk seeks. A scan that normally completes
in ~11 seconds ballooned to **10 minutes 49 seconds** and the stream starved.

The fix is to move the scan off the hot path: switched from a 15-minute interval to a **daily
4:00 AM trigger** via the Jellyfin API. Concurrent scans and evening streaming can no longer
collide.

---

## 2. Symptom

- Movie playback dropped at approximately 15-minute intervals ("hard crash" on one attempt after ~7
  minutes).
- Jellyfin pod stayed up throughout: `restartCount: 0` — this was **not** a crash, OOM kill, or
  probe-kill.
- The user had watched a full movie without issue earlier in the week (Tuesday) — the problem was
  intermittent, not constant.

---

## 3. Six theories ruled out (with evidence)

Ruling these out is as important as finding the root cause — don't re-chase them.

| # | Theory | Disproved by |
|---|---|---|
| 1 | Readiness/liveness probe killing the pod | `restartCount: 0` — pod was never killed |
| 2 | Heavy n8n pipeline testing causing contention | n8n runs on `worker-1`/`worker-2`; Jellyfin runs on `pi-k3s` master — different nodes |
| 3 | QNAP CPU overload | QNAP CPU idle (~0.1 load across 4 cores) throughout |
| 4 | Backup job running | All backups are weekly; last ran 2026-05-24 — none active |
| 5 | NFS network path degradation | 0.27 ms RTT, 0% packet loss confirmed |
| 6 | Failing disk or full pool | All disks Good (no SMART / RAID errors); "95% full" is thick-provisioning, not data — real data is ~5.58 TB (37%) |

---

## 4. Root cause

**Jellyfin's 15-minute library scan and the active movie stream contending for disk seeks on
spinning RAID5.**

Timeline during a stream drop:

1. Jellyfin scheduler fires the "Scan Media Library" task on its 15-minute interval.
2. The scan issues thousands of random metadata reads across 1,100+ media files.
3. The RAID5 array — 3 spinning disks — cannot service random and sequential I/O simultaneously
   without seek thrash.
4. Scan time balloons from the normal ~11 s to **10 minutes 49 seconds**.
5. The sequential movie-stream read starves during that window. Client sees a hard drop.

**Why this left no obvious signature:** seek latency is invisible to CPU monitors, network
monitors, and NAS-load graphs. Everything "looked fine" while the array was thrashing.

**Why it was intermittent this week:** the scan duration balloons only under some conditions
(possibly cache state, other concurrent I/O). When the scan finishes in ~11 s it causes no
perceptible blip. The Tuesday full-movie watch likely completed in a scan-quiet window.

---

## 5. Fix

**Immediate (`cdb894b`):** Changed the "Scan Media Library" trigger from
`IntervalTrigger` (900 s = 15 min) to `DailyTrigger` at **04:00** via the Jellyfin API. This
moves the scan entirely off the evening window. Jellyfin was also restarted in the same window,
picking up the `10.11.8 → 10.11.10` image update that had been pending a restart.

**Documentation:** `.claude/skills/media-services/SKILL.md` updated with:
- The 15-min interval history and why it was set (inotify over NFS doesn't work)
- The seek-contention failure mode
- The daily-4am fix and its trade-off
- The proper long-term fix (on-import-trigger + metadata-only scan)

**Trade-off:** a daily scan means newly downloaded media may not appear in the UI for up to 24
hours. The right fix is to trigger a targeted scan on import completion (e.g., via Sonarr/Radarr
post-processing webhook) rather than a full scheduled scan. That is a follow-up task.

---

## 6. Verification status

**Open.** The user stopped watching the movie before confirming clean playback under the new
schedule. To close this incident:

1. Watch a movie in the evening (after 5 PM, when no daily scan is running).
2. Confirm no drops for the full duration.

If drops still occur with **no scan running**, the seek-contention theory is wrong and the
investigation needs to resume — specifically: capture live NFS latency metrics during an actual
drop rather than relying on idle-state measurements.

---

## 7. Lessons

- **"Worked fine Tuesday" is a diagnostic signal, not noise.** The user's observation that a full
  movie played cleanly earlier in the week ruled out the NFS path, the disk health, and constant
  saturation. It narrowed the cause to something *intermittent* on a ~15-minute cycle — exactly
  what the scan timer is.
- **"Not actually full" stopped a wrong fix from shipping.** The QNAP's "95% full" pool reading
  looked alarming. Correcting that misread (`cdb894b`) prevented a capacity-remediation detour
  that would have changed nothing about the drops.
- **Seek latency is invisible to the usual dashboards.** No CPU spike, no network blip, no NAS
  load alarm. The only signal was the scan duration log inside Jellyfin and the 15-minute
  correlation with the drop cadence.
- **Rule out your own first plausible theory before acting.** Six theories were checked in order;
  each disproof narrowed the field. The scan timer was found only after ruling out the "simpler"
  explanations.

---

## Related

- Fix commit: `cdb894b` — `docs(media): correct QNAP usage reading + move Jellyfin scan to daily 4am`
- Knowledge base: `.claude/skills/media-services/SKILL.md` (Jellyfin scheduler section)
- Recap: `docs/recaps/2026-05-30-canvas-ingestion-and-jellyfin-incident.md`
- Prior Jellyfin scheduler entry: `docs/recaps/2026-02-11-memory-optimization-jellyfin-scheduler.md`
