---
name: backup-ops
description: Expert knowledge for cluster backup and restore operations. Use when configuring backups, triggering manual jobs, or restoring data.
allowed-tools: Bash, Read, Grep, Glob, Edit, Write
---

# Backup Operations

## MCP Quick Actions (USE FIRST)

| Operation | MCP Tool |
| :--- | :--- |
| Backup status (schedules, last runs) | `get_backup_status` |
| Trigger manual backup | `trigger_backup(namespace, cronjob)` |
| CronJob details (spec, volumes, history) | `get_cronjob_details(namespace, cronjob)` |
| Job logs (check output) | `get_job_logs(namespace, job)` |

## Strategy
All backups target the QNAP NAS (`storage.lab.mtgibbs.dev` → 192.168.1.61) as user `cluster-backup` using **rsync over SSH**.
In-cluster jobs run weekly on Sundays, staggered to avoid overlap. The Beelink job runs **nightly** (it lives off-cluster — see below).
Destination base: `/share/cluster/backups/`

> **Two backup planes.** Jobs #1–#5 are Kubernetes CronJobs in the `backup-jobs` namespace — visible to the MCP tools and watched by the `BackupCronJobStale` alert. The **Beelink AI-stack backup** is NOT a cluster CronJob (its data is off-cluster); it's a systemd-timed Compose container ON the Beelink, watched by a separate metric-based alert. The MCP `get_backup_status`/`trigger_backup` tools do **not** see it.

## Backup Jobs

### 1. `pvc-backup` — Master Node PVCs
- **Schedule**: Sundays 2:00 AM
- **Node**: `pi-k3s`
- **Scope**: Local-path PVCs on the master node
- **PVCs**: `uptime-kuma_uptime-kuma-data`, `uptime-kuma_autokuma-data`, `pihole_pihole-etc`, `pihole_pihole-dnsmasq`, `monitoring_kube-prometheus-grafana`, `jellyfin_jellyfin-config`
- **Destination**: `/share/cluster/backups/{date}/{pvc_name}/`
- **Retention**: Last 4 backups (auto-cleanup)

### 2. `worker2-backup` — Worker 2 PVCs
- **Schedule**: Sundays 2:30 AM
- **Node**: `pi5-worker-2`
- **Scope**: Local-path PVCs on worker 2
- **PVCs**: `media_sabnzbd-config`, `media_bazarr-config`, `n8n_n8n-data`
- **Destination**: `/share/cluster/backups/{date}/worker2/{pvc_name}/`

### 3. `postgres-backup` — Immich Database
- **Schedule**: Sundays 2:30 AM
- **Node**: Any (connects to DB service)
- **Scope**: Immich PostgreSQL database
- **Format**: `pg_dump` custom format (compression level 9)
- **Destination**: `/share/cluster/backups/{date}/postgres/`
- **Secret**: `immich-db-password` (from 1Password via ExternalSecret)

### 4. `media-backup` — Worker 1 Media Stack PVCs
- **Schedule**: Sundays 3:00 AM
- **Node**: `pi5-worker-1`
- **Scope**: All media service config PVCs on worker 1
- **PVCs**: `media_prowlarr-config`, `media_sonarr-config`, `media_radarr-config`, `media_qbittorrent-config`, `media_jellyseerr-config`, `media_lazylibrarian-config`, `media_calibre-web-config`, `media_readarr-config`, `media_lidarr-config`, `romm_romm-config`
- **Destination**: `/share/cluster/backups/{date}/media/{pvc_name}/`

### 5. `git-mirror-backup` — GitHub Repository Mirrors
- **Schedule**: Sundays 3:30 AM
- **Node**: `pi-k3s`
- **Scope**: All GitHub repos owned by `mtgibbs` (bare mirror clones)
- **Destination**: `/share/cluster/backups/git-mirrors/`
- **Secret**: `github-mirror-token` (from 1Password via ExternalSecret)
- **Note**: Incremental — pulls existing mirrors from NAS before updating

### 6. `mariadb-backup` — RomM Database
- **Schedule**: Sundays 3:45 AM
- **Node**: Any (connects to DB service — deliberately node-independent, unlike the per-node PVC jobs)
- **Scope**: RomM MariaDB (`romm` db on `romm-mariadb.romm.svc.cluster.local`, as the `romm` app user)
- **Format**: `mariadb-dump --single-transaction --routines --triggers` (consistent online InnoDB dump), gzipped
- **Destination**: `/share/cluster/backups/{date}/romm/romm-mariadb-{date}.sql.gz`
- **Secret**: `romm-db-password` (from 1Password `romm/db-password` via ExternalSecret)
- **Note**: single-target job — unreachable DB = FAILED Job (no soft-skip like postgres-backup's multi-target pattern). The rest of RomM's state: `romm-config` PVC rides `media-backup` (pi5-worker-1), `romm-redis-data` is regenerable cache (not backed up), ROMs/saves/assets live on the QNAP NFS share directly (`/share/cluster/games`).

## Beelink AI-stack Backup (OFF-CLUSTER — not a Kubernetes CronJob)

The Beelink (`beelink-ai`, 192.168.1.70) holds stateful data that lives outside
the cluster, so it's backed up by a systemd-timed Compose container ON the Beelink
— NOT by a `backup-jobs` CronJob. Managed in the **`beelink-ansible`** repo
(`playbooks/50-ai-stack.yml` + `files/beelink-backup.sh`), not in this one.

- **Schedule**: nightly, `OnCalendar=03:30` + up to 15 min jitter (`beelink-backup.timer`)
- **Service**: `beelink-backup` Compose service, profile `backup` (not started by `docker compose up`); fired by `beelink-backup.service` (`docker compose --profile backup run --rm`)
- **Scope & method**:
  - **LiteLLM Postgres** — `pg_dump` (custom format, compress 9) over the `ai-internal` Docker network as the SELECT-only **`backup_ro`** role (no DB port is exposed; the role cannot mutate anything)
  - **`/srv/openwebui`** (adults' OWUI), **`/srv/dewey-data`** (kids' OWUI), **`/srv/pipelines-data`**, **`/srv/ops-pipelines-data`** — `tar -czf` from **`:ro`** bind mounts
- **Destination**: `/share/cluster/backups/{date}/beelink/` (`litellm-{date}.dump` + four `*-{date}.tar.gz`)
- **Retention**: last 14 nightly `beelink/` snapshots (prunes only the `beelink/` subdir, never the date dirs)
- **Secrets**: `backup_ro` password = `op://pi-cluster/litellm-postgres-backup-ro/password` (passed as the `litellm_backup_ro_password` extra-var); QNAP key reuses `op://pi-cluster/synology_backup/private key` via the `QNAP_BACKUP_SSH_KEY` env var (multiline → env, not an inline extra-var)
- **Lock-down**: no Docker socket, no host root mount. Only writable targets are the QNAP backup share and the node_exporter textfile.
- **Monitoring**: on success the script writes `beelink_backup_last_success_timestamp_seconds` to the node_exporter textfile collector (`/textfile/beelink_backup.prom`). The **`BeelinkBackupStale`** alert (>36h) + **`BeelinkBackupMetricMissing`** (absent ≥30h) in `clusters/pi-k3s/monitoring/prometheusrule-beelink.yaml` watch it — this is the Beelink analogue of `BackupCronJobStale`, which can't see a non-cluster job.

## Configuration
- **Namespace**: `backup-jobs`
- **SSH Key Secret**: `backup-ssh-key` (from 1Password, `synology_backup/private key`)
- **Transport**: rsync over SSH (Synology SFTP is disabled/finicky)
- **Image**: `instrumentisto/rsync-ssh:alpine` (all jobs)
- **Manifests**: `clusters/pi-k3s/backup-jobs/`

## PVC Backup Pattern
All PVC backup jobs use the same approach:
1. Mount the node's `/var/lib/rancher/k3s/storage` as `/storage` (read-only)
2. Find PVC dirs matching pattern `pvc-*_{namespace}_{pvcname}`
3. Rsync each to NAS over SSH

**Adding a new PVC to backups**: Determine which node the PVC lives on, then add `{namespace}_{pvcname}` to the `PVCS` variable in the corresponding cronjob manifest.

## Operations

### Trigger Manual Backup

**MCP (preferred):**
```
trigger_backup(namespace="backup-jobs", cronjob="pvc-backup")
trigger_backup(namespace="backup-jobs", cronjob="media-backup")
trigger_backup(namespace="backup-jobs", cronjob="worker2-backup")
trigger_backup(namespace="backup-jobs", cronjob="postgres-backup")
trigger_backup(namespace="backup-jobs", cronjob="git-mirror-backup")
trigger_backup(namespace="backup-jobs", cronjob="mariadb-backup")
```

**kubectl fallback (cluster-ops):**
```bash
kubectl create job --from=cronjob/pvc-backup manual-pvc-backup -n backup-jobs
kubectl create job --from=cronjob/media-backup manual-media-backup -n backup-jobs
kubectl create job --from=cronjob/worker2-backup manual-worker2-backup -n backup-jobs
kubectl create job --from=cronjob/postgres-backup manual-postgres-backup -n backup-jobs
kubectl create job --from=cronjob/git-mirror-backup manual-git-mirror -n backup-jobs
```

### Check Backup Logs

**MCP (preferred):**
```
get_backup_status                              # Overview of all jobs
get_job_logs(namespace="backup-jobs", job="<job-name>")  # Specific job output
```

**kubectl fallback (cluster-ops):**
```bash
kubectl get jobs -n backup-jobs --sort-by=.metadata.creationTimestamp
kubectl logs job/<job-name> -n backup-jobs
```

### Beelink Backup Ops (off-cluster — run on the Beelink, not via MCP)

Run on `beelink-ai` directly, or remotely with `ansible inference -m shell -a "..."`
from the `beelink-ansible` repo.

```bash
# Trigger a backup now (oneshot)
sudo systemctl start beelink-backup.service

# Status / last result / next scheduled run
journalctl -u beelink-backup.service -n 50 --no-pager
systemctl list-timers beelink-backup.timer --no-pager

# Confirm the freshness metric is being served (what the alert watches)
curl -s localhost:9100/metrics | grep beelink_backup
```

### Restore Procedure (Beelink AI-stack)
On the Beelink. Backups are at `cluster-backup@storage.lab.mtgibbs.dev:/share/cluster/backups/{date}/beelink/`.

1. **LiteLLM Postgres** (DB-backed virtual keys + usage):
   ```bash
   # copy the dump to the postgres container and restore as the litellm superuser
   docker exec -i postgres pg_restore -U litellm -d litellm --clean --if-exists < litellm-{date}.dump
   ```
2. **OWUI / Dewey / pipelines dirs**: stop the relevant container, untar over the dir, restart:
   ```bash
   cd /opt/ai-stack && docker compose stop open-webui
   tar -xzf openwebui-{date}.tar.gz -C /srv/openwebui
   docker compose start open-webui
   ```
   (same shape for `dewey-data`→`open-webui-dewey`, `pipelines-data`→`pipelines`, `ops-pipelines-data`→`pipelines-ops`)

### Restore Procedure — Media/*arr config PVCs (TESTED)

Recovery = Flux redeploys the apps (empty PVCs) + restore each config PVC from the QNAP.
Uses `clusters/pi-k3s/backup-jobs/restore-job.template.yaml` — a Job that **mounts the
target PVC** (K3s auto-provisions the local-path volume on the right node, so no
`pvc-<uuid>` path hunting) and rsyncs the backup back in.

> **Proven 2026-06-14** via a scratch-PVC dry-run: sonarr's backup restored with
> `PRAGMA integrity_check: ok` and real config (7 indexers, 2 download clients, 1 root
> folder), production untouched.

> ⚠️ **The chown to `1029:100` is MANDATORY.** The QNAP squashes backup file ownership to
> the backup user (**uid 1001**) on write, but the apps run as **PUID 1029 / PGID 100**.
> The restore Job re-chowns; skip it and the restored app can't read its own config.
> (All media apps share 1029:100 — verify with `kubectl exec deploy/<app> -- ls -ln /config` if unsure.)

**Per-app steps:**
1. Latest dated backup: `ssh cluster-backup@storage.lab.mtgibbs.dev "ls -dt /share/cluster/backups/*/ | head"`
2. Scale app down (RWO PVC must be free): `kubectl -n media scale deploy/<app> --replicas=0`
3. Substitute placeholders + apply (node/src map below), then watch:
   ```sh
   sed -e 's/__APP__/sonarr/' -e 's/__PVC__/sonarr-config/' \
       -e 's/__NODE__/pi5-worker-1/' -e 's#__SRC__#media/media_sonarr-config#' \
       -e 's/__DATE__/2026-06-14/' \
     clusters/pi-k3s/backup-jobs/restore-job.template.yaml | kubectl apply -f -
   kubectl -n media logs -f job/restore-sonarr     # has an empty-source guard
   ```
4. Scale up + clean up: `kubectl -n media scale deploy/<app> --replicas=1 && kubectl -n media delete job restore-<app>`
5. Verify in-app (indexers/profiles present; `*-config` API key still works).

**Node + source map** (local-path PVCs are node-pinned):

| Node | `__SRC__` prefix | apps |
|---|---|---|
| `pi5-worker-1` | `media/media_<app>-config` | sonarr radarr prowlarr qbittorrent jellyseerr lazylibrarian calibre-web readarr lidarr |
| `pi5-worker-2` | `worker2/media_<app>-config` | sabnzbd bazarr |

**API-key note:** restoring the PVC keeps the app's API key matching 1Password
(`<app>.lab.mtgibbs.dev/api-key`), so homepage / MCP / import-resolver keep working. A
from-**empty** rebuild (no restore) mints a NEW key — re-harvest it into 1Password.

**Caveats:** single NAS copy, `rsync --delete` mirror, ~4 weekly snapshots, no offsite.
NFS media library (movies/tv/music/books) lives on the QNAP and is **not** in these config
backups. The `restore-job.template.yaml` is intentionally **excluded from kustomization**
(Flux never auto-runs it).

### Restore Procedure (other PVCs — pihole / grafana / uptime-kuma)
These live on `pi-k3s` (via `pvc-backup`). Same idea, but they're not media-namespace:
identify the backup, scale the workload down, rsync the dated dir back to the node's
`/var/lib/rancher/k3s/storage/pvc-*_<ns>_<name>/`, fix ownership, scale up.

### Restore Procedure (PostgreSQL)
1. Scale Immich deployment to 0
2. Copy backup from NAS to a pod with DB access
3. Drop and recreate database
4. Restore: `pg_restore -U immich -d immich -v /path/to/backup.dump`
5. Scale Immich back up

### Restore Procedure (RomM MariaDB)
1. Scale RomM app down (DB stays up): `kubectl -n romm scale deploy/romm --replicas=0`
2. Pull the dump from the NAS: `scp cluster-backup@storage.lab.mtgibbs.dev:/share/cluster/backups/{date}/romm/romm-mariadb-{date}.sql.gz /tmp/`
3. Restore into the running MariaDB pod (plain SQL dump — tables are recreated by the DROP/CREATE statements in it):
   ```bash
   gunzip -c /tmp/romm-mariadb-{date}.sql.gz | \
     kubectl -n romm exec -i deploy/romm-mariadb -- \
       sh -c 'mariadb -u romm -p"$MARIADB_PASSWORD" romm'
   ```
4. Scale RomM back up and verify: library visible, login works (`romm-config` PVC holds the auth assets — restore it from `media/romm_romm-config` via the media restore template if it's also lost).
