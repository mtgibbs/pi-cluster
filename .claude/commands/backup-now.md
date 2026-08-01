---
description: Trigger a manual PVC backup to the QNAP NAS
allowed-tools: mcp__homelab__trigger_backup, mcp__homelab__get_backup_status, mcp__homelab__get_job_logs
---

# Manual Backup Trigger

Trigger an immediate backup of the cluster PVCs to the QNAP NAS.

## Backup Configuration

Source of truth is `clusters/pi-k3s/backup-jobs/backup-cronjob.yaml`; see also the `backup-ops` skill.

- **CronJob**: `pvc-backup` in namespace `backup-jobs` (normally weekly, Sun 02:00)
- **Destination**: `cluster-backup@storage.lab.mtgibbs.dev:/share/cluster/backups/{date}/`
  (QNAP — the Synology was retired in the 2026-04-30 cutover)
- **Method**: rsync over SSH, runs on `pi-k3s` (local-path PVCs live there)
- **PVCs backed up**: `uptime-kuma-data`, `autokuma-data`, `pihole-etc`, `pihole-dnsmasq`,
  `kube-prometheus-grafana`, `jellyfin-config`

## Steps

1. **Trigger**: `trigger_backup(namespace="backup-jobs", cronjob="pvc-backup")` — creates a Job
   from the CronJob and returns the Job name.
2. **Watch**: `get_job_logs(namespace="backup-jobs", job="<name from step 1>")`.
3. **Verify**: `get_backup_status` — confirms last-run times across the backup CronJobs.

## Output

Report:
- Job name created
- Backup progress (per-PVC lines from the logs)
- Success/failure status
- Any PVC that logged `WARNING: PVC directory not found` (a silent skip, not a failure)

## Note

`pvc-backup` is only one of the backup CronJobs in `backup-jobs` (there are also media, postgres,
mariadb, k3s-datastore, unifi, git-mirror, worker2, and restore-test). This command triggers the
**PVC** one. To trigger another, pass its name to `trigger_backup` — check `get_backup_status`
for the full roster first.
