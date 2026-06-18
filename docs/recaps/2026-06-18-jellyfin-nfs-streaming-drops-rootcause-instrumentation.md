# Recap — Jellyfin NFS streaming drops: root-cause hunt, instrumentation, timeo fix, HDD standby hypothesis (2026-06-17 → 2026-06-18)

Picks up where the NFS wedge fix left off (PR #16–#18). The 2026-06-15 `soft` mount stopped the
*permanent freeze* but did not stop the *stream drop*. This session investigated why drops were still
happening — in a multi-thread, investigation-heavy arc with several wrong turns and two explicit
self-corrections. It is not a triumphant narrative and shouldn't be read as one.

---

## 1. QNAP disk health — disk-failure ruled out (commit `80311e5`)

The session started as "resume the QNAP SMART investigation." The prior session had raised a disk-failure
hypothesis as the promoted data-risk concern.

**The access problem.** `qnap-ro` MCP was not auto-connected — the `claude()` zsh guard that loads
`mcp-auth` only fires on a terminal launch, not a GUI/IDE session, so the in-process MCP client had
no credentials. Rather than relaunch Claude, the tool was reached **directly via JSON-RPC over HTTP**:

```
op read "op://pi-cluster/QNAP NAS/MCP_Token_ReadOnly"
POST http://qnap-mcp.lab.mtgibbs.dev:8442/mcp
  initialize → grab Mcp-Session-Id header
  notifications/initialized
  tools/list
  tools/call
```

This is now the documented fallback for when the in-process MCP client isn't connected.

**Result.** Disk-failure hypothesis does **not** hold up:

- System log clean for 7 weeks — `list_logs` (warning+error) returns 15 total entries, newest
  2026-04-30, **zero** disk/RAID/SMART/bad-sector/read-error/command-timeout events, nothing at the
  06-16 stall times. A drive in TLER deep-recovery would raise QTS System-Event warnings; there are none.
- All 3 WD Red 10TB disks at 46–49 °C, no temp alerts; RAID5 intact; volume 41% used.
- QNAP CPU idle (load_1min 0.31 @ 20:24, 0.25 @ 22:14 EDT during both stalls) — pure disk iowait, not
  a runaway QNAP process.

**MCP gaps noted.** `qnap-ro` exposes disk temperature and status flags but **not** raw SMART sector
counts (reallocated/pending/uncorrectable). Those require `smartctl -a /dev/sd[abc]` over SSH or the
QTS UI. Also: `query_top_processes` returns empty even when the QNAP is live — useless here. Both
gaps are now documented in the skill.

---

## 2. Immich parked via GitOps (commits `509bda6` doc, `53e5b34` infra)

Checking live cluster state revealed `immich-server` was already at `replicas: 0` — a manual scale-down
that wasn't in Git. Because the server was scaled to zero, Immich could not be driving the evening iowait
on the QNAP photo spindles. The "Immich as prime suspect" call in the prior session was stale.

This exposed a config-drift problem: `helmrelease.yaml` declared `server.enabled: true` and
`valkey.enabled: true` while the live pod count was zero. Flux wasn't enforcing the replica count
because something had bypassed it. Rather than leave this state inconsistent, Immich was parked properly
via GitOps:

- `helmrelease.yaml`: `server.enabled: false`, `valkey.enabled: false`
- `postgresql.yaml`: `replicas: 0` (a kustomize-managed patch — a plain `kubectl scale` would get
  reverted by Flux on next reconcile)

**The critical detail here:** `server.enabled` had to flip to `false` at the same time as
`valkey.enabled`. If only `valkey.enabled` is set to `false`, the resulting Helm upgrade re-renders the
server component from its default and re-spawns the server pod. Both must change together.

All PVCs were retained (`prune: disabled`) — photo library and postgres data are preserved. Resume path
is `server.enabled: true` + `valkey.enabled: true` + `postgres replicas: 1`. Flux verified green, all
immich pods gone.

---

## 3. Cluster-side iowait attribution — downloads, imports, Plex ruled out (commits `f7c7a06`, `73208f8`)

With disk-failure and Immich both ruled out, the session turned to systematically eliminating everything
that could have driven iowait on pi-k3s at 20:32 and 22:18 EDT on 06-16.

| Candidate | Evidence | Verdict |
|---|---|---|
| Downloads / imports | Sonarr last import 06-15 14:30Z; Radarr last 06-16 02:58Z (22:58 EDT 06-15); SAB idle at recovery | Ruled out |
| Backup jobs | Weekly Sunday (last 06-14) | Not the cause |
| Jellyfin scan tasks | Scheduled 02:00–06:00; zero scan activity in 19:xx–20:xx log window | Not the cause |
| Plex | Dead. `192.168.1.53:32400` (decommissioned Pi 3) no response (no ping, conn timeout) | Dead service |

**Plex discovery.** The `plex-external` ExternalService — Endpoint + Service + Ingress + TLS cert — was
pointing at a Pi 3 that was replaced by Jellyfin in December 2025 and decommissioned in May 2026.
cert-manager was renewing `plex.lab.mtgibbs.dev` for a server that didn't exist. Deleted the whole
file (`clusters/pi-k3s/external-services/plex.yaml`, 52 lines) and removed it from the kustomization.
Flux prune removes the live resources; cert-manager GCs the Certificate with the Ingress.

---

## 4. NFS streaming-stall instrumentation (commit `6f4e1af`)

The recurring diagnosis problem was that stalls were happening in the evening and being reconstructed
from incomplete after-the-fact data. The next drop needed to be captured live. Two instruments were
deployed against already-scraped metrics (mountstats was ruled out — the node-exporter DaemonSet runs
in a different mount namespace than the host NFS mounts, making it unreliable in K8s):

**PrometheusRule `NodeIOWaitStall`:** fires when any node sustains >30% iowait for 5 minutes, routed
via the existing Discord receiver. The 5-minute window was deliberate — the hand-rolled 12-second watcher
used during the investigation was too short and fired false alarms on brief SD-card write spikes. The
deployed alert wouldn't have triggered on those (see instrumentation caveats below).

**Grafana dashboard `media-nfs-health`** (uid `media-nfs-health`): pairs node iowait % with NIC receive
throughput as a proxy for NFS read throughput. The two together are a discriminator:
- High RX + high iowait = a reader on the cluster is saturating the array.
- Low/zero RX + high iowait = the QNAP itself can't serve reads — the array is the bottleneck.

Verified the dashboard actually renders via the Grafana API (imported, provisioned, all panel queries
return data).

---

## 5. Live crash capture — "The Bad Guys 2" (2026-06-17 13:12 EDT)

With instrumentation in place, the next drop was captured in Prometheus detail.

**"The Bad Guys 2" via Infuse direct-play died at 1h19m57s (13:12 EDT 2026-06-17).**

Prometheus replay on pi-k3s:
- Steady stream at ~6% iowait, ~11.7 MB/s RX.
- At 13:12: RX **collapsed** (11.7 → 0.06 MB/s) while iowait **pinned ~92% for ~8 minutes**.
- SD card stayed at 3% — not local disk contention.
- Jellyfin logged `/health "task was canceled"` (alive but I/O-blocked), then `Playback stopped`.

Ruled out simultaneously:
- TCP retransmits: 0
- NIC errors: 0
- conntrack: fine
- QNAP CPU: idle
- No QNAP logged event
- QNAP disks: 0 stuck in-flight I/O

**The signature: a mid-stream NFS read that stopped returning.** iowait = the kernel is waiting,
not computing. The QNAP could not serve the read; it had nothing to do with the cluster, the network,
or the node's own load.

---

## 6. Byte path confirmed — Infuse proxies through Jellyfin (commit `ce31465`)

An "Atomic Blonde" Infuse direct-play session was used to measure the live byte path.

**During an active read, pi-k3s `eth0` RX ≈ TX.** Both sides moved at ~45 MB/s locked together during
the opening burst, with no transcode. This means pi-k3s is a **pure pass-through proxy** — it reads
from QNAP via NFS and forwards to the Apple TV over HTTP. There is no direct Apple TV↔QNAP connection;
only the 3 K3s nodes hold NFS/2049 sessions.

**Self-correction.** An earlier claim that Infuse reads "directly from QNAP" was wrong. The commit
message records this correction.

**Infuse's buffering behavior.** Infuse front-loads approximately 12 GB in one ~4.5-minute burst at
~370 Mbps, then **coasts** — between refills, pi-k3s RX, QNAP TX, and the QNAP disks all go effectively
idle. This is important: during the coast, a movie plays from local Apple TV memory with no active NFS
reads. "It's playing" does not mean "the read path is healthy."

The initial commit message described the failure model as "buffer-burst the array can't sustain" — which
turned out to be incorrect and was corrected in a later commit.

---

## 7. `timeo` shortened 60s → 15s (commit `69181d4`)

The 2026-06-15 fix set `soft,timeo=600,retrans=2` — which means each NFS attempt gets 60 seconds before
timing out, with 2 retries before returning EIO. The Bad Guys 2 capture showed that a single slow read
was amplified into an 8-minute freeze by the long timeout.

`timeo=600 → 150` (15 seconds per attempt). A hung read now errors ~4× faster and becomes a short blip
rather than a multi-minute freeze. `retrans=2` is left unchanged.

**Apply procedure.** `mountOptions` can be patched in place on a bound PV (Flux reconciles it;
Kustomization stays Ready; a `rollout restart` on the consumer pod is sufficient to remount). Only
`nfs.server` and `nfs.path` (volume source fields) require the full `suspend → scale0 → delete PV/PVC
→ resume` swap. This was applied via `ssh pi-k3s`, `sudo k3s kubectl`, since the Mac has no local
kubeconfig or kubectl binary (only the Flux CLI is present on the Mac).

Verified live: `mount` in the running pod shows `vers=4.1,soft,nconnect=4,timeo=150,retrans=2`.

---

## 8. Docs correction — `mountOptions` is mutable; actual protocol is NFSv4.1 (commit `affe330`)

The apply revealed two stale claims in `docs/flux-gitops.md` and the media skill:

**Claim 1 (wrong): `mountOptions` is an immutable PV field.** Not true. Flux patched the bound PV in
place; no swap was needed. The 2026-06-16 "immutable PV deadlock" session was actually triggered by the
`nfs.server` change (hardcoding the IP at the same time as the mount options), not by `mountOptions`
itself. `nfs.server` and `nfs.path` are the actually-immutable fields. `docs/flux-gitops.md` was
rewritten to reflect this.

**Claim 2 (wrong): `jellyfin-video` mounts as NFSv3.** Live `/proc/mounts` shows `vers=4.1`. No
`nfsvers` is pinned in the PV, so it auto-negotiates; the QNAP agreed on NFSv4.1. The "do not pin
`nfsvers=4`" warning remains valid (it broke Immich mounts), but the NFSv3 label in the PV manifest
comment and the media skill was corrected.

---

## 9. HDD Standby hypothesis — the user's insight (commits `e06047b`, then `3440169`)

The user asked "is this a power-saving thing?" This reframed the investigation.

SSH to the QNAP (`mtgibbs@192.168.1.61`, password via `op://pi-cluster/QNAP NAS/password`, force
password-only auth, needs PTY for sudo) confirmed: **Disk Standby was enabled with a 30-minute
spin-down timer** (`Disk StandBy Timeout = 30` in `uLinux.conf`).

**The proposed failure chain:**
1. Infuse front-loads ~12 GB, then coasts 30+ min with zero reads (QNAP idle during this period).
2. After 30 minutes of idle, the 3 RAID5 disks spin down.
3. Infuse issues the next refill read → it hits cold disks → the array spins them back up (15–30 s,
   RAID5 staggered = longer). The NFS READ RPC hangs during spin-up.
4. Jellyfin's read thread blocks (D-state, uninterruptible) → pi-k3s iowait pins ~90% while RX
   collapses to ~0 → Infuse's buffer drains → drop. The `timeo=600` mount amplified the spin-up
   wait into a multi-minute freeze before EIO.

This fits many of the data points: healthy SMART (spin-up isn't an error), idle QNAP CPU (spin-up is
mechanical), no QTS logged event, 0 TCP retransmits, 0 NIC errors, and the intermittent pattern (only
when a coast exceeds 30 minutes before a refill).

**Two-layer fix applied:**
- **Disk Standby disabled** on the QNAP (disks never spin down → no spin-up latency to hang on).
- **`timeo=150` backstop** (commit `69181d4`) — any future read-stall errors in ~15 s regardless.

---

## 10. Self-correction — "confirmed" → "leading hypothesis" (commit `3440169`)

Commit `e06047b` used the language "ROOT CAUSE FOUND / confirmed." This was an overstatement that the
prior commit's wording made. A follow-up commit (`3440169`) dialed it back.

**What was actually proved:**
- The symptom: a mid-stream NFS read-hang (RX collapses, iowait pins).
- All the rule-outs (not network, not CPU, not disk-error, not local disk, not competing jobs, not Immich,
  not Plex, not downloads).
- That Disk Standby **was** enabled with a 30-minute timer.

**What was inferred, never observed:**
- That the disks actually spun down during a hang.
- That the refill read hit cold disks.
- That spin-up caused the hang.

We never observed the disks in standby during a hang. We never reproduced it. The "replay from 1h15m"
during the session appeared to be a transient iowait blip while Infuse was playing from local buffer —
not a real repro. The Bad Guys 2 blip was watched live and resolved on its own without any intervention.

**The inconsistency that keeps this a hypothesis, not a confirmed cause:** the one crash captured in
real detail (13:12 EDT on 06-17, The Bad Guys 2) was preceded by ~22 minutes of **steady** ~11.7 MB/s
reads. Continuous reads keep platters spun up. A spin-down shouldn't have been possible immediately
before that crash. Either that crash was atypical, there's a gap at the 2-minute Prometheus sampling
granularity, or spin-down is the wrong explanation for it.

**Confirmation is still open:** by absence (several coast-prone movies, zero drops, no `NodeIOWaitStall`
alert), or by the gold standard — catching a `hdparm -C standby → spinning-up` transition during a live
hang via SSH to the QNAP.

---

## Instrumentation caveats (learned the hard way)

**pi-k3s iowait alone is a noisy signal.** Brief 40–54% blips self-recover in ~1 minute and are often
local `/config` SD-card writes, not a stream stall. The real signature is a **sustained 5-minute+ iowait
pin with RX collapsing** — exactly what the deployed `NodeIOWaitStall` alert keys on. A hand-rolled
12-second watcher cried wolf several times during the session; the deployed alert would not have.

**During coast, there are no live NFS reads.** Between Infuse refill bursts, the Apple TV plays from
local memory with nothing happening on the network or QNAP. "It's playing" does not mean the read path
is healthy; the next refill is when you find out.

---

## Process notes — two self-corrections in one session

Two claims were made and then walked back after the user pushed back:

1. **"Infuse reads directly from QNAP."** Wrong. pi-k3s eth0 RX ≈ TX during reads proves it proxies
   through Jellyfin.
2. **"ROOT CAUSE CONFIRMED."** Overstated. The fix is low-risk and worth applying even without
   confirmation, but the inconsistency in the data (steady reads before the 13:12 crash) means causation
   is not proved.

The lesson is not to conflate "fits the data" with "proved." The rule-outs were rigorous; the positive
identification of spin-down as the cause was not. Distinguish proved vs. inferred before using
"confirmed."

---

## Access notes for next time

- **QNAP SSH:** `mtgibbs@192.168.1.61`, password in `op://pi-cluster/QNAP NAS/password` (force
  password-only auth, not key; sudo requires a PTY).
- **pi-k3s SSH:** via 1Password agent (needs unlock), passwordless sudo, `sudo k3s kubectl`.
- **Mac:** no local kubectl or kubeconfig. Flux CLI is present but has no cluster credentials. All
  kubectl operations must go via pi-k3s SSH or MCP tools.
- **`qnap-ro` when not auto-connected:** POST JSON-RPC to
  `http://qnap-mcp.lab.mtgibbs.dev:8442/mcp` with the token from
  `op://pi-cluster/QNAP NAS/MCP_Token_ReadOnly`. Sequence: `initialize` → save `Mcp-Session-Id`
  header → `notifications/initialized` → `tools/list` → `tools/call`.

---

## Commits

| Hash | Subject |
|---|---|
| `80311e5` | docs(media): QNAP SMART check — disk-failure ruled out, pivot to cluster-side iowait |
| `509bda6` | docs(media): correct resume trail — Immich ruled out (server scaled to 0) |
| `53e5b34` | chore(immich): park Immich — disable server+valkey, postgres replicas 0 |
| `f7c7a06` | docs(media): iowait chase — downloads/imports + Plex ruled out |
| `73208f8` | chore(external-services): remove dead Plex config (replaced by Jellyfin Dec 2025) |
| `6f4e1af` | feat(monitoring): NFS streaming-stall alert + dashboard |
| `ce31465` | docs(media): record confirmed byte-path + burst-buffer failure model (live capture) |
| `69181d4` | fix(jellyfin): shorten NFS timeo 60s→15s |
| `affe330` | docs(flux,media): mountOptions is mutable; NFS mount is v4.1 not v3 |
| `e06047b` | docs(media): reconcile failure model to ROOT CAUSE (overstated — see next) |
| `3440169` | docs(media): dial back HDD-standby from "confirmed" to LEADING HYPOTHESIS + caveat |

---

## Key decisions

**Disk Standby disabled.** Low-risk regardless of whether the hypothesis is correct. Disks that never
spin down can't hang a read on spin-up. The only cost is slightly higher idle power draw on the NAS.

**`timeo=150` instead of `timeo=600`.** A 15-second timeout means a hung read surfaces as a blip,
not a multi-minute freeze. `retrans=2` still multiplies before EIO; drop it to 1 for a harder ceiling
if 15-second-class stalls still drop Infuse.

**`mountOptions` is mutable** — only patch `nfs.server`/`nfs.path` require the full PV swap. Document
this precisely to avoid unnecessary suspend-delete-recreate surgery.

**Both fixes applied even without confirmed causation.** Both are low-risk and address real measured
behavior (the iowait pin, the long timeout amplification). The confirmation can come passively — by the
absence of drops over coast-prone movies — which costs nothing.

---

## Verified end state

| Component | State | Notes |
|---|---|---|
| QNAP disk health | Clean (7 wk logs, healthy temps, RAID5 intact) | Disk-failure ruled out |
| Immich | All pods zero; PVCs retained | `server.enabled:false`, `valkey.enabled:false`, `postgres replicas:0` |
| Dead Plex config | Deleted | 52-line `plex.yaml` + kustomization entry removed |
| `NodeIOWaitStall` alert | Live | >30% iowait for 5 min → Discord |
| `media-nfs-health` dashboard | Live (verified rendering) | iowait × NIC-RX on pi-k3s |
| `jellyfin-video-nfs` PV | `timeo=150` live | Verified via `mount` in running pod |
| QNAP Disk Standby | Disabled | 30-min spin-down timer removed |
| `docs/flux-gitops.md` | mountOptions mutability corrected | Immutable = `nfs.server`/`nfs.path` only |
| media-services SKILL.md | Leading hypothesis + caveats documented | Honest status: not confirmed |
| Stream-drop root cause | **Leading hypothesis (HDD Standby spin-up), fix applied, NOT confirmed** | Steady-read caveat is the open inconsistency |

---

## Open items

- [ ] **Confirm by absence:** watch a few coast-prone movies (long films, 4K, Infuse direct-play). Zero
  drops + no `NodeIOWaitStall` = leading hypothesis accepted. A recurrence = theory wrong, restart from
  the steady-read inconsistency.
- [ ] **Gold-standard confirmation (optional):** if a drop does recur, SSH to QNAP during the hang and
  run `hdparm -C /dev/sd[abc]` to check for a `standby` → `spinning-up` state transition.
- [ ] **`retrans` tuning:** if 15-second stalls still drop Infuse, lower `retrans` from 2 to 1 for a
  harder EIO ceiling (~15 s flat instead of ~45 s worst case).
- [ ] **`kiwix-zim-nfs` PV:** also read-only NFS on pi-k3s, currently only `[nolock]`. Could benefit
  from `soft,timeo,retrans,nconnect` treatment, but kiwix is lower-stakes than live streaming — deferred.
- [ ] **Investigate the 01:38–01:44 UTC iowait spike** (noted in the skill) — a second broad-random-read
  job lands in that window; identify it before it ambushes a stream.
