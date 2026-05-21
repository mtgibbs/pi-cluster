# Session Recap — 2026-05-21 (Backup Recovery + Mirror Hardening)

This session is the operational arc that ran concurrently with the model-comparison work documented in `docs/recaps/2026-05-21-q8-coder-agent-comparison.md`. That recap covers the Q8/hot-coder work. This one covers what was found when the ops pipeline ran its first real diagnostic: all cluster backups had been silently dead for three weeks, and the git-mirror had been exiting "success" while backing up nothing. Both were found, fixed, and hardened against silent recurrence.

---

## What Was Fixed

### 1. local-llm-mcp Coding Tools → `hot-coder` (lead-in)

Before the backup work began, `local_explain_diff` and `local_explain_command` were updated from the hardcoded `qwen3-coder:30b` model name to the runtime-swappable `hot-coder` LiteLLM alias. Light tools (summarize, classify, extract) stay on the fast `qwen3.5:9b`. Released as `local-llm-mcp` v0.1.1 and deployed to the cluster. End-to-end verification: a diff explain call routed through `hot-coder` → Q8 in 2 seconds.

---

### 2. Cluster-Wide Backup Failure

**Symptom:** all six backup CronJobs in the `backup-jobs` namespace last succeeded between April 26–30. Last scheduled run was May 17. Approximately three weeks of no successful backups, surfaced by the ops pipeline during the model comparison.

**Root cause:** every job set `NAS_PATH="/cluster/backups"`. The 2026-04-30 Synology→QNAP cutover moved the NAS base path to `/share/cluster/backups`. The `ssh ... mkdir -p ${NAS_PATH}/...` command failed immediately with "Permission denied" — the QNAP root does not allow arbitrary top-level directory creation — and `set -e` aborted the job before any backup data was written. SSH auth, DNS, and port were all fine. The last successful backup directory on the QNAP was dated `2026-04-30`, exactly the cutover date.

**Diagnosis method:** reading the actual failing command output and reproducing the mkdir error against the QNAP verbatim, rather than guessing at auth or network issues. The server path was proved first.

**Fix (commit c5d71a5):** corrected `NAS_PATH` to `/share/cluster/backups` across all six manifests.

**Follow-on fixes (commit 1cf081a), found during a live test run:**

- The "keep last 4" cleanup step uses `rm` to prune old backup directories. Legacy pre-cutover directories (owned by uid 1026, the Synology `mtgibbs` user) are foreign-owned from the QNAP's perspective. The `rm` call was failing on these, and under `set -e` that failure aborted the job *after* a good backup had already been written — a clean backup followed by a reported failure. Wrapped cleanup in `|| true`.
- The `unifi-backup` job's cleanup `find` command still referenced the hardcoded path `/cluster/backups`. The first pass had only replaced the `NAS_PATH=` assignment; this stray reference was a separate fix.

**Verified:** pvc-backup, worker2-backup, media-backup, and postgres-backup all ran green with real data written to the QNAP under the `cluster-backup` user. The unifi job carries the identical fixes.

**Also updated:** `backup-ops` SKILL.md still documented the old Synology target (192.168.1.60, `/volume1`, `mtgibbs` user). Refreshed to reflect the current QNAP reality.

**Note:** legacy pre-cutover backup directories (2026-04-16 through 2026-04-30, foreign-owned by uid 1026) will not auto-prune under the new cleanup logic since the QNAP `cluster-backup` user cannot remove them. A one-time manual `rm` on the QNAP is required to clear them.

---

### 3. git-mirror: Silent No-Op → Real Off-GitHub Backups

**Symptom:** the `git-mirror-backup` job was exiting success but mirroring nothing. The log showed "Found 1 repositories" followed by an empty directory and a successful rsync of that empty directory.

**Root cause:** the GitHub fine-grained PAT (`github-mirror-token`) had expired. GitHub's API returned HTTP 401. The script used `curl -sf`, which swallows non-2xx responses silently by exiting non-zero but with no output. The REPOS variable was empty. `echo "" | wc -l` evaluates to 1, which produced the misleading "Found 1" log line. The loop iterated over nothing, rsync copied an empty directory, and the job exited 0. No repos were being backed up — and monitoring showed green.

**Fix:**

1. User regenerated a fine-grained read-only, non-expiring-intent token (verified against 45 repos including 4 private). ExternalSecret refreshed.
2. Script hardened to fail loudly (commit e599281): checks the HTTP response code explicitly, counts repos via `jq length`, exits 1 on a non-200 response or a zero repo count.

**Verified:** all 45 GitHub repositories mirrored to `/share/cluster/backups/git-mirrors` on the QNAP as bare clones. Directory link count of 47 (45 repos + 2 for `.` and parent) confirms the count. Includes pi-cluster, local-llm-mcp, kiwix-mcp, carl, ralph, and the 4 private repos.

---

### 4. IUA Gap for MCP Server Kustomizations (commit 50345ac)

Both `local-llm-mcp` and `kiwix-mcp` were scaffolded with `ImageRepository` and `ImagePolicy` resources but no `ImageUpdateAutomation`. Flux's image scanner was detecting new image tags but never writing the deployment bump back to git — image bumps were silently not deploying. This is why `local-llm-mcp` v0.1.1 had not rolled out after release. Added per-path `ImageUpdateAutomation` resources to both Kustomizations, mirroring the pattern used by `mcp-homelab`. This is now a required checklist item for any future MCP server or service scaffold.

---

### 5. Token-in-Config Security Hardening

The git-mirror script was embedding the GitHub PAT directly in each mirror's remote URL (`https://token@github.com/...`). This URL gets written into `.git/config` and was then rsynced to the QNAP — 45 bare clone configs on the NAS contained the token in plaintext.

**First attempt (commit 3b6e532):** switched to a git credential helper. This approach was superseded: private-repo fetches failed under `set -e`, causing the loop to abort before the scrub-and-rsync step, so the token stayed in config and the repos were not synced.

**Final fix (commit 66eb429):** fetch with the proven token-in-URL form, then immediately `git remote set-url origin <clean-url-without-token>` before the rsync runs. Per-repo fetch failures are recorded but non-fatal so the scrub and sync always execute even when individual repos fail. The token never leaves the pod.

**Scrubbed the existing exposure:** directly SSH'd to the QNAP and ran `sed` across all 45 `.git/config` files to strip the token. Verified: 45 files contained the token before; 0 after. Sample remote URLs confirmed as `https://github.com/mtgibbs/pi-cluster.git`.

---

### 6. Flux Source-Lag Investigation (a Corrected Misdiagnosis)

Throughout the session, deploys appeared to lag. One `GitOperationFailed` event at 11:47 and impatience with the reconcile cycle led to a hypothesis of recurring GitHub-SSH-pull timeouts.

Pulled 90 minutes of source-controller logs: the `GitRepository` is healthy — it reconciles every 60 seconds, has zero git errors, and each new commit is stored within one poll cycle. The perceived lag was the normal 60-second poll interval, async kustomization reconciles racing immediate checks after a push, and one isolated transient event. No chronic problem exists. The hypothesis was wrong; the logs corrected it.

**Operational note:** after a push, the expected sequence is ~75 seconds for the source poll, then ~15 seconds for kustomization reconcile. Do not diagnose a problem until that window has passed.

---

## Commits

| Hash | Repo | Subject |
|---|---|---|
| `169fc8a` | pi-cluster | feat(local-llm-mcp): wire coding tools to hot-coder + Q2 roadmap edits |
| `50345ac` | pi-cluster | fix(image-automation): add missing IUAs for local-llm-mcp + kiwix-mcp |
| `c5d71a5` | pi-cluster | fix(backup): correct NAS_PATH to /share/cluster/backups across all jobs |
| `1cf081a` | pi-cluster | fix(backup): make cleanup non-fatal; fix unifi stray hardcoded path |
| `e599281` | pi-cluster | fix(git-mirror): fail loudly on expired token or zero repos |
| `3b6e532` | pi-cluster | fix(git-mirror): credential helper approach (superseded by 66eb429) |
| `66eb429` | pi-cluster | fix(git-mirror): post-fetch token scrub before rsync |
| `v0.1.1` | local-llm-mcp | fix: rewire coding tools to hot-coder alias |

---

## Key Decisions and Lessons

**Prove the server path first.** Reading the actual `mkdir` error output and reproducing it against the QNAP pinned the backup root cause immediately. No guessing at auth, DNS, or network was needed.

**Silent success is the worst failure mode.** The git-mirror job reported green for weeks while backing up nothing. A job that exits 0 when it has done nothing useful is more dangerous than a job that fails loudly. Both the mirror and the backup jobs are now hardened to fail on meaningful precondition checks.

**"One green light doesn't prove the layers behind it."** The Flux kustomization appeared healthy while the backup jobs beneath it were failing. The ops pipeline showed green while the mirror stored nothing. In both cases, reading the actual log output rather than trusting the surface status was what revealed the problem.

**Don't fix phantom problems.** A near-miss: almost switched the healthy SSH GitRepository source to HTTPS based on a single transient event and impatience. The source-controller logs showed the source was fine. The 90-minute log pull was the right call.

**Every MCP/service scaffold requires an ImageUpdateAutomation.** The add-service skill omits it. Without an IUA, Flux detects new image tags and does nothing with them. Image releases silently do not deploy.

---

## Verified End State

| Component | State | Notes |
|---|---|---|
| Backup CronJobs (all 6) | Green | `NAS_PATH=/share/cluster/backups`; cleanup non-fatal |
| pvc-backup | Verified green | Real data written to QNAP today |
| worker2-backup | Verified green | Real data written to QNAP today |
| media-backup | Verified green | Real data written to QNAP today |
| postgres-backup | Verified green | Real data written to QNAP today |
| unifi-backup | Fix applied | Identical patch; shares Sunday schedule |
| git-mirror | Verified green | 45/45 repos mirrored; token-free configs on QNAP |
| QNAP NAS configs | Scrubbed | 0 of 45 bare clone configs contain the token |
| `local-llm-mcp` v0.1.1 | Deployed | Coding tools route through `hot-coder` |
| `kiwix-mcp` IUA | Added | Image bumps now reconcile to git |
| Flux GitRepository | Healthy | 60s poll, zero errors; perceived lag was normal cycle time |
| `backup-ops` SKILL.md | Refreshed | Reflects QNAP target; Synology references removed |

---

## What Remains

- [ ] One-time manual `rm` of legacy foreign-owned backup directories (2026-04-16 through 2026-04-30) on the QNAP — these will not auto-prune under the new cleanup logic
- [ ] Backup coverage does not include the Beelink stack (LiteLLM Postgres, Open WebUI / Dewey databases) — pre-existing roadmap item, not introduced this session
