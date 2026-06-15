# Recap — DNS saturation fix + Usenet hardening + Media DR (2026-06-12 → 2026-06-14)

Picks up where the homepage retro-theme recap left off. That session surfaced two parked items —
Pi-hole query saturation and a DNS connection error pattern — that got chased to root cause and
fixed. Alongside that, a Usenet reliability problem was diagnosed and patched, and the session
ended with a substantial media disaster-recovery build: a tested restore procedure, a runbook,
and a weekly canary that now proves backups are restorable on an ongoing basis.

---

## 1. Pi-hole/Unbound DNS saturation — root-caused and fixed (PR #7, deployed 2026-06-13)

**What was observed.** Both Pi-holes were logging `DNSMASQ_WARN "max concurrent queries (150)"
simultaneously, plus `CONNECTION_ERROR "connection prematurely closed"` TCP drops to Unbound on
`10.43.x#5335`. These had been visible as a "Parked" item in the previous recap. The errors
were pulled via Pi-hole v6's `/api/info/messages` endpoint on both boxes.

**Root cause: `tcp-upstream: yes` in `unbound-configmap.yaml`.**
This option does NOT mean "fall back to TCP if UDP fails." That fallback is automatic on
truncated UDP. `tcp-upstream: yes` forces *all* upstream recursion over TCP, always. It was
added 2025-12-31 (`17b857f`) under the misconception it was a general resilience toggle. The
AT&T/IPv6 slowness it was loosely associated with was a separate issue fixed on the gateway
(UniFi IPv6 prefix delegation, 2026-01-04) — no relationship to DNS transport. The January
2026 TCP-pool bump (`4ed431f`) only masked the symptom rather than addressing it.

The TCP-everything design saturated the Pi-holes because each DNS query from a client opened a
new TCP connection to Unbound. Under normal household DNS load, the 150-query concurrent limit
hit on both boxes simultaneously because both share the same `unbound-config` ConfigMap.

**Fix (PR #7, `c1f2be5`).** Removed `tcp-upstream: yes`. Added a guard comment so it is not
re-added. Reverted to UDP-first + automatic TCP fallback + default `edns-buffer-size 1232`
(the fragmentation-safe value).

**Deploy sequence.** Off-hours (Saturday night). Reconcile git source first, then Kustomization
(the ConfigMap mount does not auto-roll pods — both Unbound pods were restarted manually after
the ConfigMap landed). Walked the dependency chain: source → pihole Kustomization → roll
unbound-primary → roll unbound-secondary. Verified DNSSEC on both paths post-restart.

**Outcome (verified 2026-06-14).** `DNSMASQ_WARN` has not recurred since before the fix.
`CONNECTION_ERROR` still fires at a low rate — that is benign TCP churn (stray TCP connections
closing cleanly), not a sign of ongoing saturation. DNS is healthy.

Durable notes live in `.claude/skills/dns-ops/SKILL.md`. A correction was also applied to
`docs/SESSION-RECAP-2025-12-31.md`, which described the option inaccurately.

---

## 2. Chatty-client identification (diagnostic only, no change)

While the Pi-hole message logs were open, the top talkers were identified from DNS-query
fingerprints:

| Client | Identity | Verdict |
|---|---|---|
| `.57` (pi5-worker-2) | Uptime Kuma + homepage status monitor | Self-inflicted, benign |
| `.1` | UDM Pro Max gateway | Normal |
| `.80` | NVIDIA gaming PC | GeForce Experience telemetry; ~59% blocked — working as intended |
| `.206` | Minecraft/Lunar Client rig | Rate-limited by Lunar CDN; benign |

Conclusion: no client warranted action. The dual-box saturation was the resolver, not any
single client.

---

## 3. Usenet completion — ViperNews fill server added (operational, no GitOps change)

**Symptom.** SABnzbd was logging recurring par2 repairs on completion — sometimes extensive
ones that dragged download time significantly.

**Root cause.** The affected downloads were old releases (1–2 year posts). Old Usenet articles
are not universally retained. Newshosting (the primary Usenet provider) uses the Omicron
backbone. On single-backbone coverage, articles missing from that backbone are simply absent;
SABnzbd tries par2 repair with whatever it has, which is incomplete for very old content.

**Fix.** Added a **ViperNews 1000 GB block account** as a **priority-1 fill server** in SABnzbd
(priority 0 = Newshosting primary). ViperNews runs an independent NL backbone — articles missing
from Omicron are frequently present in the NL pool. Credentials are stored in 1Password under
`vipernews`.

**Important note on scope.** SABnzbd's server config (including the fill server) is **runtime
PVC state, not GitOps.** It is stored in `sabnzbd-config` and is in the same class as Pi-hole
app-passwords: present in weekly backups, but not reproducible from a git checkout alone. A
clean PVC rebuild requires restoring from backup or reconfiguring manually. This is the same
class of finding that drove the media DR work below.

**Also diagnosed (no action taken).**
- `Illegal end of multipart body` CherryPy errors: one-off truncated NZB upload; transient,
  not a bug.
- Transient SABnzbd "504 / hang": NFS I/O stall on the spinning QNAP RAID under concurrent
  par2 + unpack load. Self-healed; the pod never restarted.

---

## 4. Media/*arr disaster recovery — built, tested, and made self-verifying (PRs #10–#12)

This is the centerpiece of the session.

### The finding that drove it

`*arr`, SABnzbd, and friends use `linuxserver.io` images. These images do not accept
environment-based configuration — they generate `config.xml` with an encrypted API key on
first run, and all subsequent user configuration (indexers, download clients, quality profiles,
paths) is stored there and in the app's SQLite database. There is no `configarr`-style
config-as-code path that can replace this state. (Configarr was evaluated and explicitly
deferred: it can manage a subset of settings declaratively but cannot replace a backup as the
full DR mechanism for this class of app.)

All 11 media config PVCs are backed up weekly by `media-backup` (worker-1) and `worker2-backup`
(worker-2 for SABnzbd and Bazarr). The backups were running and green. But restore was
undocumented and had never been tested. The ViperNews finding — SAB config is runtime state —
made the gap concrete.

### What was built

**Restore Job template (PR #10, `110951e`)**
`clusters/pi-k3s/backup-jobs/restore-job.template.yaml` — a parametrized Kubernetes Job
that mounts the target PVC directly (K3s local-path auto-provisions the volume on the correct
node, so there is no `pvc-<uuid>` path hunting), rsyncs the QNAP backup into it, and chowns
to `1029:100`. The template is intentionally excluded from the Kustomization — Flux never
auto-applies it; it is applied by hand during DR or drills.

`clusters/pi-k3s/media/external-secret.yaml` was extended to mirror `backup-ssh-key` into the
`media` namespace so that a restore Job running in that namespace can SSH to the NAS.

**Full validated runbook (PR #11, `fe4deea`)**
`.claude/skills/backup-ops/SKILL.md` — expanded from a 4-line stub into a full, step-by-step
restore procedure with node/source mapping, scale-down/apply/scale-up steps, and the
mandatory chown explained.

**Weekly restore-test canary (PR #12, `50efe00`)**
`clusters/pi-k3s/backup-jobs/restore-test-cronjob.yaml` — a CronJob (`restore-test`, Sundays
04:00) that restores Sonarr's latest config backup into a dedicated scratch PVC (never touches
the production `sonarr-config`), runs `PRAGMA integrity_check` on the database, and confirms
real configuration is present (indexers > 0). Exits non-zero on any failure, which is caught
within 15 minutes by the existing `BackupJobFailed` alert
(`kube_job_failed{namespace="backup-jobs"}`) and by `BackupCronJobStale` if it stops running.
No new alert rule was needed — the canary inherits the existing backup-jobs alerting by living
in the same namespace.

### The critical finding the dry-run surfaced

> **The QNAP squashes backup file ownership to uid 1001 (the `cluster-backup` user) on write.
> The media apps run as PUID 1029 / PGID 100. Without a `chown -R 1029:100` after the rsync,
> the restored app cannot read its own config.**

This is exactly the class of bug that a "backups are green" dashboard check would never reveal
and that a tested restore catches immediately. The restore Job template performs the chown; the
runbook documents it as mandatory. The canary does not test the chown directly (it runs as the
backup user and reads the file anyway), but it proves the database is intact and the restore
path works end-to-end.

### Validation

Dry-run: Sonarr's latest backup was restored into a scratch PVC. Outcome:

```
PRAGMA integrity_check: ok
Indexers: 7
Download clients: 2
Root folders: 1
```

Production `sonarr-config` was never touched. First manual run of the canary: passed.

---

## Commits

| Hash | PR | Subject |
|---|---|---|
| `c1f2be5` | #7 | fix(dns): remove tcp-upstream from Unbound (root of query saturation) |
| `110951e` | #10 | feat(backup): media/*arr restore Job template + media backup-ssh-key ESO |
| `fe4deea` | #11 | docs(backup): tested media/*arr restore runbook in backup-ops |
| `50efe00` | #12 | feat(backup): weekly restore-test canary — verifies backups are restorable |

---

## Key decisions and lessons

**`tcp-upstream: yes` is not a safe-guard; it is a foot-gun.** The option name implies fallback
behavior; it actually overrides the default to TCP-only. The Dec 2025 → Jun 2026 duration shows
how long a misread option comment can live. The guard comment in the ConfigMap should prevent
re-introduction.

**"Backups are green" is not the same as "backups are restorable."** Six backup CronJobs running
weekly with no alerts gives high confidence in write coverage. It gives zero confidence that a
restore would succeed. The chown finding is the proof: a restore without it silently appears to
complete but produces an unusable app. The canary closes this gap on a weekly cadence.

**Config-as-code does not replace backups for this class of app.** Linuxserver images generate
state on first run; Configarr manages a subset of it declaratively. The correct DR mechanism
is backup + tested restore. Configarr is a partial enhancement and was deferred, not adopted
as the primary posture.

**Runtime PVC state is a class, not a single thing.** Pi-hole app-passwords (noted in the
previous recap), SABnzbd server config, and `*arr` API keys + settings are all in the same
category: they exist in the cluster, they are backed up, but they are not reproducible from
git. Knowing what falls in this class matters for DR planning.

---

## Verified end state

| Component | State | Notes |
|---|---|---|
| Both Unbounds | `DNSMASQ_WARN` clear | Not recurred since 2026-06-13 deploy |
| Unbound ConfigMap | `tcp-upstream` removed | Guard comment added; not to be re-added |
| DNS SKILL.md | Updated | Do-not-re-add note + transport explanation |
| SABnzbd | ViperNews fill server added | Priority-1; Newshosting remains primary |
| `restore-job.template.yaml` | Merged, excluded from kustomization | DR/drill use only |
| `media` namespace `backup-ssh-key` | ESO deployed | Mirrors backup-jobs key |
| Restore runbook | `.claude/skills/backup-ops/SKILL.md` | Full procedure with chown warning |
| `restore-test` CronJob | Deployed, first run passed | Sundays 04:00 AM |
| `restore-canary` PVC | Provisioned | Scratch only; never prod |

---

## Open items

- [ ] The Jellyfin library scan reference in `ARCHITECTURE.md` says "15-min" in three places
  (lines 554, 2123, 2145) — it was changed to daily 4am back in May (see
  `docs/recaps/2026-05-30-canvas-ingestion-and-jellyfin-incident.md`). Not introduced this
  session; noted for cleanup.
- [ ] ViperNews block account is runtime SABnzbd config — document under servarr-ops SKILL if
  the Usenet provider stack becomes more complex.
- [ ] The canary only tests Sonarr. Adding Radarr or Bazarr as a second canary target would
  increase coverage but is not urgent while Sonarr proves the pattern.
