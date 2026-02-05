---
name: backup-ops
description: Expert knowledge for cluster backup and restore operations. Use when configuring backups, triggering manual jobs, or restoring data.
allowed-tools: Bash, Read, Grep, Glob, Edit, Write
---

# Backup Operations

## Strategy
All backups target the Synology NAS (`192.168.1.60`) using **rsync over SSH**.
Backups run weekly on Sundays, staggered to avoid overlap.
Destination base: `/volume1/cluster/backups/`

## Backup Jobs

### 1. `pvc-backup` — Master Node PVCs
- **Schedule**: Sundays 2:00 AM
- **Node**: `pi-k3s`
- **Scope**: Local-path PVCs on the master node
- **PVCs**: `uptime-kuma_uptime-kuma-data`, `uptime-kuma_autokuma-data`, `pihole_pihole-etc`, `pihole_pihole-dnsmasq`, `monitoring_kube-prometheus-grafana`, `jellyfin_jellyfin-config`
- **Destination**: `/volume1/cluster/backups/{date}/{pvc_name}/`
- **Retention**: Last 4 backups (auto-cleanup)

### 2. `worker2-backup` — Worker 2 PVCs
- **Schedule**: Sundays 2:30 AM
- **Node**: `pi5-worker-2`
- **Scope**: Local-path PVCs on worker 2
- **PVCs**: `media_sabnzbd-config`, `media_bazarr-config`, `n8n_n8n-data`
- **Destination**: `/volume1/cluster/backups/{date}/worker2/{pvc_name}/`

### 3. `postgres-backup` — Immich Database
- **Schedule**: Sundays 2:30 AM
- **Node**: Any (connects to DB service)
- **Scope**: Immich PostgreSQL database
- **Format**: `pg_dump` custom format (compression level 9)
- **Destination**: `/volume1/cluster/backups/{date}/postgres/`
- **Secret**: `immich-db-password` (from 1Password via ExternalSecret)

### 4. `media-backup` — Worker 1 Media Stack PVCs
- **Schedule**: Sundays 3:00 AM
- **Node**: `pi5-worker-1`
- **Scope**: All media service config PVCs on worker 1
- **PVCs**: `media_prowlarr-config`, `media_sonarr-config`, `media_radarr-config`, `media_qbittorrent-config`, `media_jellyseerr-config`, `media_lazylibrarian-config`, `media_calibre-web-config`, `media_readarr-config`, `media_lidarr-config`
- **Destination**: `/volume1/cluster/backups/{date}/media/{pvc_name}/`

### 5. `git-mirror-backup` — GitHub Repository Mirrors
- **Schedule**: Sundays 3:30 AM
- **Node**: `pi-k3s`
- **Scope**: All GitHub repos owned by `mtgibbs` (bare mirror clones)
- **Destination**: `/volume1/cluster/backups/git-mirrors/`
- **Secret**: `github-mirror-token` (from 1Password via ExternalSecret)
- **Note**: Incremental — pulls existing mirrors from NAS before updating

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
```bash
# PVC backup (master node)
kubectl create job --from=cronjob/pvc-backup manual-pvc-backup -n backup-jobs

# Media stack backup (worker 1)
kubectl create job --from=cronjob/media-backup manual-media-backup -n backup-jobs

# Worker 2 backup
kubectl create job --from=cronjob/worker2-backup manual-worker2-backup -n backup-jobs

# PostgreSQL backup
kubectl create job --from=cronjob/postgres-backup manual-postgres-backup -n backup-jobs

# Git mirror backup
kubectl create job --from=cronjob/git-mirror-backup manual-git-mirror -n backup-jobs
```

### Check Backup Logs
```bash
# Find the most recent job for a cronjob
kubectl get jobs -n backup-jobs --sort-by=.metadata.creationTimestamp

# Get logs from last run
kubectl logs job/<job-name> -n backup-jobs
```

### Restore Procedure (PVC)
1. Identify the backup on NAS: `ssh mtgibbs@192.168.1.60 "ls /volume1/cluster/backups/"`
2. Scale down the deployment using the PVC
3. Rsync from NAS back to the PVC directory on the correct node
4. Scale deployment back up

### Restore Procedure (PostgreSQL)
1. Scale Immich deployment to 0
2. Copy backup from NAS to a pod with DB access
3. Drop and recreate database
4. Restore: `pg_restore -U immich -d immich -v /path/to/backup.dump`
5. Scale Immich back up
