# Recap — Branch protection + CARL cleanup + Jellyfin NFS wedge root-cause and fix (2026-06-14 → 2026-06-16)

Picks up where the DNS/Usenet/media-DR recap left off (PRs #7, #10–#12). Three separate threads
closed out: a lightweight GitOps safety net for `main`, a long-overdue architecture doc cleanup
for two retired services, and a recurring Jellyfin streaming outage that got root-caused, fixed,
and extended to the full media NFS fleet.

---

## 1. Branch protection — force-push guard only, intentionally not full protection (PR #15, 2026-06-15)

**The concern.** A destructive `git push --force` to `main` could overwrite Flux commit history
silently. The repo had no branch protection at all.

**The constraint that shapes the solution.** Flux `ImageUpdateAutomation` commits image-tag bumps
**directly to `main`** as the Flux bot — no PR, no review. Six apps currently use it
(`mtgibbs-site`, `mcp-homelab`, `review-hub`, `local-llm-mcp`, `kiwix-mcp`,
`private-exit-node`). A **required-PR or required-review rule** would silently reject those
bot pushes and halt image automation with no obvious error. This is the kind of breakage that
sits undetected until you wonder why a container hasn't updated in weeks.

**The fix.** Enable `enforce_admins: true` + block force-pushes and branch deletion — but
**no required-PR, no required-review, no required-status-check**. Fast-forward bot pushes are
unaffected. Force-pushes are blocked for everyone including the repo owner. The weekly
`git-mirror-backup` job (mirrors to QNAP) is the backstop for worst-case history loss.

The `gh` commands to view, lift, and re-apply the rule are now in `docs/flux-gitops.md` so
lifting it for an intentional force-push (rare but legitimate — e.g., image-automation cleanup)
is a one-liner rather than a GitHub UI detour.

---

## 2. ARCHITECTURE.md — CARL and in-cluster Ollama retired, stale entries removed (PR #14, 2026-06-15)

CARL (§33) was decommissioned 2026-05-30, and its dedicated in-cluster Ollama (§34) went with
it. The Beelink AI-stack took over the inference role. But `ARCHITECTURE.md` still showed both
as active across several places: a `carl` namespace box in the topology diagram, a
`pi-k3s → Beelink` routing-diagram line labeled `carl`, a `carl/` + `ollama/` entry in the
repo tree, rows in the port table, and a URL in the access list. The narrative in §33–§34
correctly described the retirement but the structural artifacts implied current operation.

**What changed.** Removed all the structural active-state entries. Added a `RETIRED` banner to
§34 to match the §33 banner that was already there. Kept the §33–§34 narrative blocks as
bannered provenance (design history is worth keeping). The Beelink AI-stack Ollama (Vulkan/RADV,
a distinct live service) was not touched.

Net: `-70 lines, +9 lines`. The topology diagram now reflects what's actually running.

---

## 3. Jellyfin NFS wedge — root-caused, fixed, extended to the full media fleet (PRs #16–#18)

This is the centerpiece of the session.

### The symptom

Jellyfin streaming froze hard and repeatedly. Infuse clients reported `error 1`; Jellyfin's
`/health` liveness probe timed out and triggered a pod restart. Recovery required SSH-ing to
`pi-k3s` and force-unmounting the NFS mount manually — a ~30-second operation, but it needed
to happen every time streaming was attempted. The pattern was recurring ("every time we stream"),
making the service effectively unusable.

### Ruling out the obvious suspects

The diagnosis required going through every layer, because the symptom (streaming freeze) has
many plausible causes. What was ruled out:

| Suspect | Evidence | Verdict |
|---|---|---|
| Node crash / resource pressure | pi-k3s Ready 174d, 0 memory/disk/PID pressure | Clear |
| QNAP overloaded | pi5-worker-1 read the same NAS at 89 MB/s concurrently, no stall; QNAP CPU and IO-wait low | Clear |
| QNAP scheduled task | Malware-remover daily 03:00; no snapshot schedule | Not the cause |
| conntrack saturation | 3,569 / 131,072 entries (3% full) | Clear |
| NIC errors | 0 errors, 0 drops, MTU 1500 | Clear |
| DNS failure | `storage.lab.mtgibbs.dev` resolved correctly to `.61`; DaemonSet `/etc/hosts` override healthy | Clear |
| Other media services | radarr/sonarr on worker-1 — zero stalls in logs during Jellyfin freezes | Not the cause |

**The tell.** The kernel NFS log on `pi-k3s` showed `nfs: server storage.lab.mtgibbs.dev not
responding, still trying` on a `hard` mount. On a `hard` mount, the kernel retries **forever**
when the server stops responding — no timeout, no error. A momentary NAS read-stall (a
natural occurrence on a 3-disk spinning RAID5 under sustained sequential reads) becomes a
permanent freeze. The "metronomic ~4m22s stall cadence" that initially looked like a QNAP
scheduled task was an artifact of the old single connection's retry/back-off rhythm, not
a periodic external event.

**Why only Jellyfin, not the other services.** Jellyfin is pinned to `pi-k3s` (local-path
config PVC). The `jellyfin-video-nfs` PV (`ReadOnlyMany`, a single NFS connection on a `hard`
mount) sustained the only *continuous* streaming reads against the spinning array. radarr/sonarr
on worker-1 do *bursty* reads that slip between the array's stall windows. Worker-1 logged zero
stalls during Jellyfin's freeze events.

**Diagnostic note on the QNAP.** The QNAP NAS is not directly reachable from the operator's
Mac over Tailscale — Tailscale routes to the cluster API, not the NAS management interface.
All NAS-side diagnosis (IO-wait, scheduled tasks, concurrent throughput) had to go through the
cluster nodes via `kubectl exec` and `mcp__homelab__*` tools.

### The fix — Jellyfin video PV (PR #16, 2026-06-15)

`clusters/pi-k3s/jellyfin/nfs-pv.yaml`: changed `mountOptions` from `[nolock]` to
`[nolock, soft, timeo=600, retrans=2, nconnect=4]` and hardcoded `server: 192.168.1.61`.

- `soft`: a brief NAS stall now **errors and recovers** (2 retries × 60s = 2 min max stall)
  instead of hanging forever. Safe on a read-only PV — no write corruption risk.
- `timeo=600, retrans=2`: 60-second timeout, 2 retries before erroring.
- `nconnect=4`: 4 parallel TCP connections → more throughput headroom + per-connection
  resilience (a single connection stall no longer blocks all I/O).
- `server: 192.168.1.61` (hardcoded IP): this PV mounts on `pi-k3s`, which uses public DNS
  (not Pi-hole) and only resolves `storage.lab.mtgibbs.dev` via the `/etc/hosts`-override
  DaemonSet. That DaemonSet is a single point of failure. Hardcoding the QNAP IP removes
  that dependency. Trade-off: a future QNAP IP change must edit this PV directly, not just
  a Pi-hole DNS record. Acceptable — the QNAP IP is `192.168.1.61` by DHCP reservation and
  is not expected to change.

**Validated.** 0 stalls across a 17.6-minute continuous streaming read after the new mount
negotiated. The old mount could not sustain 60 seconds.

### Extended to the 4 read-write media PVs (PR #17, 2026-06-16)

`clusters/pi-k3s/media/nfs-pv.yaml`: same `timeo=600, retrans=2, nconnect=4` added to
`media-downloads`, `media-library`, `media-music`, and `media-books`.

Differences from the Jellyfin fix:
- **`hard` not `soft`**: these are `ReadWriteMany` PVs. A `soft` write-timeout mid-write
  can corrupt data. `hard` is kept; the tuned `timeo`/`retrans` adds throughput headroom
  without the corruption risk.
- **Hostname kept** (`storage.lab.mtgibbs.dev`, not hardcoded IP): these PVs mount on the
  worker nodes, which use Pi-hole DNS. The IP-hardcode rationale was pi-k3s-specific.

The `nconnect=4` addition in particular benefits SABnzbd, which writes large (multi-GB)
files to the downloads NFS share — parallel connections raise the throughput ceiling.

### Operational gotchas captured (PR #18, 2026-06-16)

Two gotchas from the apply sequence are now documented in `docs/flux-gitops.md`:

**Gotcha 1 — `kubectl rollout restart` does not clear a wedged NFS mount.**
A rolling restart staggers pod termination so there is always an overlap: the new pod starts
mounting before the old pod fully terminates. The wedged mount is never fully dropped. The
correct recovery is scale-to-0 (all pods down) or a manual force-unmount on the node.

**Gotcha 2 — PV-swap deadlock if the Kustomization is not suspended.**
`mountOptions` and `nfs.server` are **immutable** PV fields — the API rejects edits, so the
Kustomization goes `NotReady`. The correct path is delete + recreate. But if the Flux
Kustomization is *active* during the delete, Flux re-spawns the consumer Deployments (which
have `replicas: 1`) mid-delete. Those Pending pods hold the `pvc-protection` finalizer. The
PVC sticks in `Terminating`, the new PVC can't be created, the pods stay Pending. **Deadlock.**

The fix: `flux suspend kustomization` **before** deleting anything, keep it suspended through
PVC and PV deletion, let Flux recreate both on resume. For an NFS-pointer PV (`Retain` policy,
data on the NAS) this is zero-data-loss. Recovery if already stuck: scale consumers to 0, then
force-clear the finalizer:
```bash
kubectl patch pvc <name> -n <ns> -p '{"metadata":{"finalizers":null}}' --type=merge
```
Then delete the `Released` PV (the stale `claimRef` blocks rebinding) and let Flux recreate.

**Also noted.** The new mounts negotiated NFSv4.1 without incident. The earlier "v4 broke immich"
note in the SKILL (from the 2026-05-30 Immich incident) was Immich-specific and does not
generalize.

---

## Commits

| Hash | PR | Subject |
|---|---|---|
| `cc63ca2` | #14 | docs(architecture): remove stale active CARL/Ollama entries |
| `f32fc00` | #15 | docs(flux): document main's force-push-only branch protection |
| `7ede720` | #16 | fix(jellyfin): resilient NFS mount options + hardcoded IP |
| `71b3ad3` | #17 | fix(media): resilient NFS mount options on the 4 RW media PVs |
| `584b422` | #18 | docs(flux): swapping immutable PV fields without the stuck-PVC deadlock |

---

## Key decisions and lessons

**Branch protection is not binary.** "No protection" vs. "full PR workflow" is a false choice.
Force-push blocking with `enforce_admins` stops the destructive case (history rewrite) without
adding friction to the normal case (bot image-tag commits). Required-PR would silently break
image automation — a worse outcome than the problem it was solving.

**`hard` NFS + spinning storage under sustained reads = latent time bomb.**
The `hard` default is often described as "safer" (no data loss on timeout). It is — for writes
on intermittent connections. For a sustained read stream against spinning RAID, it converts every
brief seek-contention stall into a permanent freeze. `soft` with tuned `timeo`/`retrans` is the
right posture for read-only mounts; `nconnect` is the right uplift for both.

**`soft` vs. `hard` is a per-access-mode decision, not a per-cluster decision.**
Read-only: `soft` is safe, `hard` is a wedge risk. Read-write: `hard` is required, `soft` risks
corruption on timeout. The two mount-option sets in this repo now reflect that distinction
explicitly.

**`rollout restart` does not fully release NFS.** This is a surprising but well-documented
behavior: a rolling restart maintains a running pod throughout (that's the whole point), so the
NFS connection is never fully dropped. Force-unmount or scale-to-0 are the only tools that fully
clear a wedged mount.

**Suspend Flux before touching immutable fields.** Flux's reconcile loop is not aware that you
are mid-surgery. It will helpfully re-apply Deployments while their PVCs are being deleted,
and the resulting `pvc-protection` deadlock is not immediately obvious from the error messages.
The rule is: suspend the Kustomization, do the surgery, resume only when the new PV/PVC exist.

**Docs in the repo live longer than memory.** The `tcp-upstream: yes` option from Dec 2025
survived six months because the rationale wasn't documented near the knob. The PV gotcha and
branch-protection rationale are now in `docs/flux-gitops.md` where they'll be found by the
next person (or future-self) who reaches for the same operation.

---

## Verified end state

| Component | State | Notes |
|---|---|---|
| `main` branch | Force-push/deletion blocked | `enforce_admins: true`; no PR required (image-automation) |
| `docs/flux-gitops.md` | Branch protection section added | Includes manage/lift/re-apply commands |
| `ARCHITECTURE.md` | CARL + in-cluster Ollama removed from active entries | Bannered provenance kept; Beelink Ollama untouched |
| `jellyfin-video-nfs` PV | `soft,timeo=600,retrans=2,nconnect=4`, server `192.168.1.61` | ReadOnlyMany; `soft` safe for reads |
| 4 media RW PVs | `hard,timeo=600,retrans=2,nconnect=4`, hostname kept | ReadWriteMany; `hard` required for writes |
| `media-services/SKILL.md` | Mount resilience rationale + wedged-mount recovery runbook | soft vs. hard distinction documented |
| `docs/flux-gitops.md` | Immutable-PV swap procedure + deadlock recovery | suspend-through-swap rule documented |
| Jellyfin streaming | Stable — 0 stalls in 17.6-min validation read | Old mount could not sustain 60s |

---

## Open items

- [ ] The 4 RW media PVs (PR #17) apply in the next maintenance window — they have the same
  immutable-field constraint; the suspend-through-swap procedure in `docs/flux-gitops.md` is
  the runbook.
- [ ] `jellyfin-video-nfs` has a hardcoded IP (`192.168.1.61`). If the QNAP's IP ever changes,
  this PV (and its PVC) must be recreated — it will not be enough to update DNS.
- [ ] The canary restore-test (PR #12) only covers Sonarr. Radarr or Bazarr as a second
  target would increase coverage; deferred until the Sonarr pattern proves stable.
- [ ] The `kiwix-zim-nfs` PV is also read-only NFS on pi-k3s (noted in SKILL.md). It
  currently has only `[nolock]`. It could benefit from the same `soft,timeo,retrans,nconnect`
  treatment, but kiwix is a lower-stakes read (reference library, not live streaming), so
  it's not urgent.
