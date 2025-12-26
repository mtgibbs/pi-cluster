---
description: Trigger a manual PVC backup to Synology NAS
allowed-tools: Bash(KUBECONFIG=~/dev/pi-cluster/kubeconfig kubectl:*)
---

# Manual Backup Trigger

Trigger an immediate backup of all PVCs to Synology NAS.

## Backup Configuration
- **Destination**: mtgibbs@192.168.1.60:/volume1/k3s-backups/
- **Method**: rsync over SSH
- **PVCs backed up**:
  - uptime-kuma-data (2Gi)
  - autokuma-data (100Mi)
  - pihole-etc (1Gi)
  - pihole-dnsmasq (100Mi)
  - kube-prometheus-grafana (1Gi)

## Steps

1. **Create job from CronJob**:
   ```bash
   KUBECONFIG=~/dev/pi-cluster/kubeconfig kubectl -n backup-jobs create job --from=cronjob/pvc-backup manual-backup-$(date +%Y%m%d-%H%M%S)
   ```

2. **Watch progress**:
   ```bash
   KUBECONFIG=~/dev/pi-cluster/kubeconfig kubectl -n backup-jobs logs -f job/manual-backup-<timestamp>
   ```

3. **Verify completion**:
   ```bash
   KUBECONFIG=~/dev/pi-cluster/kubeconfig kubectl -n backup-jobs get jobs
   ```

## Output

Report:
- Job name created
- Backup progress (show log output)
- Success/failure status
- Size of data backed up (if available)
