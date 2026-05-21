# Session Recap — 2026-05-21 (Beelink AI-Stack Backup Coverage)

This is the fourth arc of 2026-05-21. The other three are `docs/recaps/2026-05-21-backup-recovery-and-mirror-hardening.md` (three weeks of silent cluster backup failure, fixed), `docs/recaps/2026-05-21-observability-phase1.md` (alert and uptime-probe coverage for the AI surfaces), and `docs/recaps/2026-05-21-q8-coder-agent-comparison.md` (model benchmarking). This arc closes the gap called out at the end of the backup-recovery recap: the Beelink AI box had zero backup coverage for its stateful data.

---

## What Was Backed Up

Four host directories and one Postgres database on the Beelink (192.168.1.70):

| Dataset | Notes |
|---|---|
| LiteLLM Postgres DB | Compose container `postgres`, db/user `litellm`, no published port |
| `/srv/openwebui` | Adults' Open WebUI data |
| `/srv/dewey-data` | Kids' Open WebUI (Dewey) data |
| `/srv/pipelines-data` | User pipelines data |
| `/srv/ops-pipelines-data` | Ops pipeline data |

---

## The Design Decision: Push vs. Pull

Two architectures were weighed:

**Option A — Pull (in-cluster CronJob that SSHes into the Beelink).** This would have given `BackupCronJobStale` coverage for free, since the in-cluster alert can already see `backup-jobs` CronJobs via `kube_cronjob_status_last_successful_time`. The cost: the cluster would require docker-exec-capable SSH access into the Beelink — a wider blast radius than wanted for a backup credential.

**Option B — Push (backup job lives on the Beelink).** Matches the preference to keep backup logic co-located with the data and easier to manage. The cost: the in-cluster alert cannot see a non-cluster job, so freshness monitoring requires a separate approach.

Option B was chosen, with two conditions: (1) the backup process must not be able to mutate the database or application data, and (2) freshness must still alert if the nightly run goes missing.

Both conditions were satisfied:

- **No write access:** a dedicated `backup_ro` Postgres role (CONNECT + SELECT-only, including sequences, with ALTER DEFAULT PRIVILEGES to cover future tables) is the only DB credential the backup process holds. The four `/srv` directories are mounted `:ro`. No Docker socket. No host root mount.
- **Freshness alerting without a CronJob:** the backup script writes `beelink_backup_last_success_timestamp_seconds` to the node_exporter textfile collector (the same collector already used for GPU metrics) after a fully successful run. Two PrometheusRule alerts watch that metric — the same pattern as `BackupCronJobStale`, just on a different visibility substrate.

---

## What Was Built

### beelink-ansible repo — commit `61a8a61`

**`files/beelink-backup.sh`** — the backup script:

- `pg_dump` via the `backup_ro` role over the `ai-internal` Docker network (Postgres port not published to the host)
- Fails loudly on a dump smaller than a sanity threshold — an empty or near-empty dump is treated as a hard failure
- `tar` of the four `/srv` directories (via `:ro` bind mounts)
- `rsync` to `cluster-backup@storage.lab.mtgibbs.dev:/share/cluster/backups/<date>/beelink/` using the existing cluster-backup QNAP SSH key
- Writes `beelink_backup_last_success_timestamp_seconds` to the node_exporter textfile directory on success
- Retains 14 snapshots (two weeks), pruning older ones

**`playbooks/50-ai-stack.yml`** additions (idempotent):

- `backup_ro` role creation in LiteLLM Postgres (CONNECT + SELECT including sequences; ALTER DEFAULT PRIVILEGES for future tables)
- `beelink-backup` Compose service with profile `backup` — only runs when explicitly invoked, not part of the always-on stack
- `beelink-backup.service` and `beelink-backup.timer` systemd units — `OnCalendar=03:30` with a 15-minute random jitter, `Persistent=true` so a missed window runs on next boot
- A "wait for postgres healthy" gate before the backup service definition
- A one-shot validation run at the end of the play
- Also folded in the previously-untracked `files/gpu-metrics.sh`

The `backup_ro` password lives in 1Password as `litellm-postgres-backup-ro` in the `pi-cluster` vault (generated, never printed). The QNAP key is delivered via the existing `QNAP_BACKUP_SSH_KEY` env var with a loud assert if absent.

### pi-cluster repo — commit `0ff937a`

**`clusters/pi-k3s/monitoring/prometheusrule-beelink.yaml`** — two new rules appended to the existing Beelink alert group:

- **`BeelinkBackupStale`**: fires (after 1h hold) when the freshness metric is more than 36 hours old. The 36h window covers one missed nightly run plus a morning-discovery buffer.
- **`BeelinkBackupMetricMissing`**: fires (after 30h hold) when the metric is absent entirely. The 30h grace avoids a false alarm on a fresh deploy before the first nightly run — the playbook seeds it with a one-shot run, but the grace is there for future re-deploys.

### Other pi-cluster commits

| Hash | Subject |
|---|---|
| `956e427` | docs(roadmap): mark Beelink backup coverage done |
| `a6fd9fb` | docs(backup-ops): document off-cluster backup + restore procedures in SKILL.md |

---

## Validation

The playbook ran to completion (`ok=35 changed=9 failed=0`). Only `caddy` was recreated (its service is `build: always`); the always-on Ollama/LiteLLM/Open WebUI stack was undisturbed.

The one-shot validation backup produced five artifacts on the QNAP:

| Artifact | Size |
|---|---|
| `litellm-2026-05-21.dump` | 219 K |
| `openwebui/` | 805 MB |
| `dewey-data/` | 805 MB |
| `ops-pipelines/` | 13 KB |
| `pipelines/` | 10 KB |
| **Total** | **~1.69 GB** |

Confirmed that node_exporter is serving `beelink_backup_last_success_timestamp_seconds` and `node_textfile_mtime_seconds` (for file age). Confirmed the timer is `enabled` with next run Fri 2026-05-22 03:33 EDT.

The diagnostic-discipline practice held: the metric path was verified end-to-end (node_exporter actually serving the metric, not just the script writing the file) before declaring the observability loop closed.

---

## Commits

| Hash | Repo | Subject |
|---|---|---|
| `61a8a61` | beelink-ansible | feat(backup): nightly Beelink AI-stack backup to QNAP |
| `0ff937a` | pi-cluster | feat(monitoring): add BeelinkBackupStale freshness alert |
| `956e427` | pi-cluster | docs(roadmap): mark Beelink backup coverage done |
| `a6fd9fb` | pi-cluster | docs(backup-ops): document the off-cluster Beelink AI-stack backup |

---

## Key Decisions and Lessons

**Two backup planes now exist.** In-cluster CronJobs (visible via MCP `get_backup_status` / `trigger_backup` / `BackupCronJobStale`) are one plane. The off-cluster Beelink systemd timer is a second, separate plane — it is not visible to the MCP tools or `kube_cronjob_status_last_successful_time`, and its freshness signal is the node_exporter textfile metric. SKILL.md was updated to document both.

**Reusing the textfile collector avoids a new probe CronJob.** The GPU metrics script already established the pattern: write a gauge to `/var/lib/node_exporter/textfile_collector/` and let the existing scrape job pick it up. The backup script reused that pattern for freshness signaling. No new components, no new scrape targets.

**Least-privilege is structurally enforced, not policy-enforced.** The `backup_ro` role cannot issue writes — it's a permissions constraint, not a convention. The `:ro` mount flags prevent the container from modifying app data even if the script were compromised. These constraints were chosen specifically to make the push architecture as tight as the pull alternative.

**Existing QNAP key reused.** The `cluster-backup` SSH key (`op://pi-cluster/synology_backup/private key`) was not minted for the Beelink, but it scopes to the `cluster-backup` user on the QNAP, which can only write to `/share/cluster/backups`. A Beelink-specific key is a future option if isolation becomes desirable.

---

## Verified End State

| Component | State |
|---|---|
| `beelink-backup` Compose service | Deployed with `backup` profile |
| `beelink-backup.timer` | Enabled, next run 2026-05-22 03:33 EDT |
| QNAP backup artifacts | 5 files, ~1.69 GB at `/share/cluster/backups/2026-05-21/beelink/` |
| `backup_ro` Postgres role | Created; SELECT-only |
| `beelink_backup_last_success_timestamp_seconds` | Serving via node_exporter |
| `BeelinkBackupStale` + `BeelinkBackupMetricMissing` | Live in PrometheusRule |
| `backup-ops` SKILL.md | Updated with off-cluster section + restore procedures |
