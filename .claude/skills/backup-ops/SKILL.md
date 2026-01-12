---
name: backup-ops
description: Expert knowledge for cluster backup and restore operations. Use when configuring backups, triggering manual jobs, or restoring data.
allowed-tools: Bash, Read, Grep, Glob, Edit, Write
---

# Backup Operations

## Strategy
Backups target the Synology NAS (`192.168.1.60`) using **rsync over SSH**.

### 1. PVC Backups (Filesystem)
- **Schedule**: Sundays 2:00 AM
- **Job**: `immich-backup`
- **Scope**: Immich upload directory (photos/videos).
- **Destination**: `/volume1/k3s-backups/{date}/immich/`

### 2. PostgreSQL Backups (Database)
- **Schedule**: Sundays 2:30 AM
- **Job**: `postgres-backup`
- **Scope**: Immich database (metadata, albums, users).
- **Format**: `pg_dump` custom format (compression level 9).
- **Destination**: `/volume1/k3s-backups/{date}/postgres/`

## Configuration
- **Namespace**: `backup-jobs`
- **Secret**: `postgres-backup-secret` (DB password from 1Password).
- **Transport**: `rsync` is used because Synology SFTP is often disabled/finicky.

## Operations

### Trigger Manual Backup
```bash
# Trigger PVC backup
kubectl create job --from=cronjob/immich-backup manual-immich-backup -n backup-jobs

# Trigger DB backup
kubectl create job --from=cronjob/postgres-backup manual-postgres-backup -n backup-jobs
```

### Restore Procedure (Database)
1. Stop the application (scale deployment to 0).
2. Copy backup file from NAS to pod.
3. Drop existing database.
4. Restore using `pg_restore`.

```bash
pg_restore -U immich -d immich -v /path/to/backup.dump
```
