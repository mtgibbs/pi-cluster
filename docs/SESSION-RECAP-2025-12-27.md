# Session Recap - December 27, 2025

## Overview

Major cluster expansion from single-node to 3-node multi-Pi deployment, plus significant media service upgrades (Immich v2 migration, Jellyfin deployment) and improved observability (Discord notifications, Homepage enhancements).

## Completed

### 1. Multi-Node Cluster Expansion
- **What**: Added two Raspberry Pi 3 worker nodes to the cluster
  - `pi3-worker-1` (192.168.1.53, 1GB RAM)
  - `pi3-worker-2` (192.168.1.51, 1GB RAM)
- **Why**: Distribute workloads across multiple nodes for better resource utilization and learning about Kubernetes multi-node operations
- **How**:
  - Configured cgroups and disabled swap on both Pi 3s
  - Generated SSH keys and stored in 1Password
  - Retrieved K3s node token from master and stored in 1Password
  - Joined workers to cluster via `K3S_URL=https://192.168.1.55:6443`
  - Created `/Users/mtgibbs/dev/pi-cluster/docs/pi-worker-setup.md` for reproducibility

### 2. Workload Distribution Strategy
- **What**: Strategically distributed services across the 3-node cluster using nodeSelectors
- **Why**: Optimize resource usage - keep critical infrastructure on Pi 5, offload lighter workloads to Pi 3s
- **Implementation**:
  - **pi-k3s (Pi 5, master)**: Pi-hole (hostNetwork requirement), Flux controllers, backup jobs (needs hostPath access)
  - **pi3-worker-1**: Unbound DNS resolver (lightweight, stable workload)
  - **pi3-worker-2**: Homepage dashboard (initially pinned, later removed to allow scheduler flexibility)
- **Trade-offs**: Some services needed memory increases due to Pi 3's limited RAM (e.g., Homepage startup timeouts)

### 3. Immich Photo Management Upgrade (v1.123.0 → v2.4.1)
- **What**: Migrated Immich through major version upgrade (two-step migration path)
- **Why**: v2.x brings significant improvements in photo management, new features, and better performance
- **How**:
  - Step 1: Upgraded to v1.132.3 (final TypeORM version before migration)
  - Step 2: Upgraded to v2.4.1 (Kysely database migration)
  - Fixed NFS storage configuration: `IMMICH_MEDIA_LOCATION=/data` (previously tried `/usr/src/app/upload`)
  - Installed Immich CLI for bulk photo imports: `npx @immich/cli@latest upload`
  - Fixed Helm chart breaking changes (0.10.x):
    - Updated database configuration format
    - Fixed Valkey (Redis) persistence configuration
    - Addressed NFSv4/NFSv3 compatibility with Synology NAS
    - Used Pi-compatible postgres image with pgvector extension
- **Commits**:
  - `fix(immich): Step through v1.132.3 for proper migration path` (0944615)
  - `feat(immich): Complete upgrade to v2.4.1` (47b5f58)
  - `fix: Add explicit namespace entries for HelmRelease alerts` (65326d1)

### 4. Jellyfin Media Server Deployment
- **What**: Deployed Jellyfin as a self-hosted alternative to Plex
- **Why**: Open-source media server with no proprietary restrictions, better privacy
- **How**:
  - Created namespace: `jellyfin`
  - NFS PersistentVolume to Synology NAS (`192.168.1.60:/volume1/video`)
  - PersistentVolumeClaim for media library access
  - Deployment with Jellyfin image
  - Service (ClusterIP) on port 8096
  - Ingress with TLS: `https://jellyfin.lab.mtgibbs.dev`
- **Location**: `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/jellyfin/`
- **Commits**:
  - `feat(jellyfin): Add Jellyfin media server` (35816da)
  - `fix(jellyfin): Correct NFS path to /volume1/video` (bfea5ec)

### 5. Homepage Dashboard Enhancements
- **What**: Upgraded Homepage with Kubernetes cluster metrics widget and updated service links
- **Why**: Provide real-time visibility into cluster node health (CPU, memory, uptime)
- **How**:
  - Added Kubernetes widget configuration in ConfigMap
  - Created ServiceAccount, ClusterRole, ClusterRoleBinding for read access to node metrics
  - Replaced Plex entry with Jellyfin in services list
  - Initially pinned to pi-k3s for performance, later removed nodeSelector to allow scheduling flexibility
  - Increased liveness/readiness probe timeouts to accommodate slower Pi 3 startup times
- **Files Modified**:
  - `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/homepage/configmap.yaml`
  - `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/homepage/serviceaccount.yaml` (new)
  - `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/homepage/deployment.yaml`
- **Commits**:
  - `feat(homepage): Replace Plex with Jellyfin, add cluster node stats` (302b759)
  - `fix: Increase Homepage probe timeouts for slower startup` (ffbdbdc)
  - `fix: Remove nodeSelector and increase memory for homepage` (b6f7749)

### 6. Discord Deployment Notifications
- **What**: Integrated Flux notifications with Discord webhook
- **Why**: Real-time deployment status updates in Discord for better observability
- **How**:
  - Created namespace: `flux-notifications`
  - Created Discord Provider pointing to webhook URL
  - Created Alert resource for all Flux Kustomization/HelmRelease events
  - ExternalSecret syncs webhook URL from 1Password (`discord-alerts` item, `webhook-url` field)
  - Added 30s timeout to Discord provider to accommodate Pi network latency
  - Configured Alert to include namespace metadata for HelmReleases
- **Location**: `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/flux-notifications/`
- **1Password Setup**: Created `discord-alerts` item in `pi-cluster` vault with `webhook-url` field
- **Commits**:
  - `feat: Add Discord deployment notifications + fix Immich storage` (65093f5)
  - Multiple fixes for correct 1Password field names and timeout settings

### 7. Backup Job Node Pinning
- **What**: Added nodeSelector to pin backup CronJob to pi-k3s master node
- **Why**: Backup job needs access to local-path storage PVCs which are hostPath-based on the master node
- **How**: Added `nodeSelector: kubernetes.io/hostname: pi-k3s` to backup job spec
- **Commit**: `chore: Pin backup job to pi-k3s master node` (ab1ff70)

## Key Decisions

### Decision 1: Two-Step Immich Migration Path
- **Why**: Direct upgrade from v1.123.0 to v2.4.1 would skip critical database migrations
- **Approach**: v1.123.0 → v1.132.3 (TypeORM final) → v2.4.1 (Kysely migration)
- **Trade-offs**: Longer migration time, but ensures data integrity

### Decision 2: NodeSelector Strategy
- **Why**: Optimize workload placement given heterogeneous cluster (Pi 5 + 2x Pi 3)
- **Approach**:
  - Critical infrastructure on Pi 5 (Pi-hole, Flux, backups)
  - Stable, lightweight workloads on Pi 3s (Unbound, Homepage)
  - Most services allowed to float (no nodeSelector)
- **Trade-offs**: Some manual tuning required, but better resource utilization

### Decision 3: Homepage Performance Tuning
- **Why**: Homepage slow to start on Pi 3 due to limited RAM and CPU
- **Initial attempt**: Pin to pi-k3s with nodeSelector
- **Final solution**: Remove nodeSelector, increase memory limits, extend probe timeouts
- **Rationale**: Let Kubernetes scheduler make decisions, but give service more resources and time to start

### Decision 4: Jellyfin Over Plex
- **Why**: Open-source, no proprietary restrictions, better privacy
- **Implementation**: Full GitOps deployment with NFS storage to Synology NAS
- **Trade-offs**: Less polished UI than Plex, but no licensing concerns

## Architecture Changes

### Before (Single Node)
```
┌──────────────────────────────────┐
│  pi-k3s (Pi 5, 192.168.1.55)    │
│  - All workloads                 │
│  - Master + Worker               │
└──────────────────────────────────┘
```

### After (3-Node Cluster)
```
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  pi-k3s (Pi 5)   │  │ pi3-worker-1     │  │ pi3-worker-2     │
│  192.168.1.55    │  │ 192.168.1.53     │  │ 192.168.1.51     │
│  (master+worker) │  │ (worker, 1GB)    │  │ (worker, 1GB)    │
│                  │  │                  │  │                  │
│ • Pi-hole        │  │ • Unbound        │  │ • Homepage       │
│ • Flux           │  │                  │  │ • (scheduler     │
│ • Backups        │  │                  │  │    decides)      │
│ • Most workloads │  │                  │  │                  │
└──────────────────┘  └──────────────────┘  └──────────────────┘
```

### New Services Added
- **Jellyfin**: `https://jellyfin.lab.mtgibbs.dev` (media server)
- **Immich**: `https://immich.lab.mtgibbs.dev` (photo backup, upgraded to v2.4.1)
- **Discord**: Flux notifications to Discord webhook

## Next Steps

### Completed from Backlog
- [x] Multi-node cluster (was listed as future work in ARCHITECTURE.md)
- [x] Workload distribution across nodes
- [x] Jellyfin media server deployment
- [x] Immich v2 migration
- [x] Discord deployment notifications
- [x] Homepage Kubernetes widget

### Potential Future Work
- [ ] High availability for critical services (Pi-hole failover)
- [ ] Automated backup testing/restore procedures
- [ ] Persistent storage migration to NFS (currently using local-path)
- [ ] Resource quota policies per namespace
- [ ] Network policies for pod-to-pod traffic control
- [ ] Horizontal Pod Autoscaling (HPA) for eligible workloads
- [ ] Additional monitoring dashboards (node exporter, Pi-hole metrics)

## Troubleshooting Notes

### Issue 1: Homepage Slow Startup on Pi 3
**Symptoms**: Homepage pod failing liveness/readiness probes, CrashLoopBackOff
**Root cause**: Pi 3's limited resources (1GB RAM, slower CPU) + default 10s probe timeouts
**Solution**: Increased probe timeouts to 60s, added memory limits, increased initialDelaySeconds

### Issue 2: Immich Storage Configuration
**Symptoms**: Immich unable to write uploaded photos
**Root cause**: Incorrect `IMMICH_MEDIA_LOCATION` environment variable
**Solution**: Changed from `/usr/src/app/upload` to `/data` (matches PVC mount point)

### Issue 3: Discord Webhook 1Password Field Name
**Symptoms**: ExternalSecret failing to sync Discord webhook URL
**Root cause**: Using wrong field names (`password`, `api-token`) instead of `webhook-url`
**Solution**: Updated ExternalSecret to reference correct field: `discord-alerts/webhook-url`

### Issue 4: Backup Job Failing on Worker Nodes
**Symptoms**: Backup CronJob pods failing to access PVCs
**Root cause**: local-path PVCs are hostPath-based, only accessible on the node where they were created (pi-k3s)
**Solution**: Added nodeSelector to pin backup job to pi-k3s master node

## Files Modified/Created

### New Files
- `/Users/mtgibbs/dev/pi-cluster/docs/pi-worker-setup.md` - Worker node setup guide
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/jellyfin/` - Complete Jellyfin deployment
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/flux-notifications/` - Discord notification setup
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/homepage/serviceaccount.yaml` - RBAC for K8s widget

### Modified Files
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/immich/helmrelease.yaml` - v2.4.1 upgrade config
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/homepage/configmap.yaml` - Jellyfin + K8s widget
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/homepage/deployment.yaml` - Probe timeouts, memory
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/pihole/unbound-deployment.yaml` - nodeSelector
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/backup-jobs/immich-backup.yaml` - nodeSelector

## References

**Relevant Commits**: 30 commits from `54b1ebd` to `ab1ff70`

**Key Documentation**:
- Worker setup: `/Users/mtgibbs/dev/pi-cluster/docs/pi-worker-setup.md`
- Immich Helm chart docs: https://github.com/immich-app/immich-charts
- Jellyfin docs: https://jellyfin.org/docs/
- Flux notifications: https://fluxcd.io/flux/guides/notifications/

**1Password Items Updated**:
- Created `discord-alerts` item with `webhook-url` field
- Stored SSH keys for pi3-worker-1, pi3-worker-2
- Stored K3s node token
