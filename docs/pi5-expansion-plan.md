# Pi 5 Cluster Expansion Plan

This document outlines the plan for adding a second Raspberry Pi 5 to the K3s cluster to improve capacity, enable HA for critical services, and future-proof for additional workloads.

## Current State Analysis

### Hardware Overview

| Node | Hardware | RAM | IP | Role | Memory Usage |
|------|----------|-----|-----|------|--------------|
| pi-k3s | Pi 5 | 8GB | 192.168.1.55 | Master + Worker | 81% (6.5GB/8GB) |
| pi3-worker-1 | Pi 3 | 1GB | 192.168.1.53 | Worker | 54% (493Mi/910Mi) |
| pi3-worker-2 | Pi 3 | 1GB | 192.168.1.51 | Worker | 57% (519Mi/910Mi) |

### Current Workload Distribution

**Pi 5 (pi-k3s) - Heavily Loaded:**
| Workload | Memory | Notes |
|----------|--------|-------|
| Immich Server | 1425Mi | Largest consumer, photo processing |
| Prometheus | 785Mi | Metrics storage and queries |
| Grafana | 696Mi | Dashboard rendering |
| Jellyfin | 467Mi | Media streaming |
| Immich PostgreSQL | 213Mi | Database |
| Pi-hole | 190Mi | DNS + ad blocking (hostNetwork) |
| Uptime Kuma | 152Mi | Status page |
| Homepage | 147Mi | Dashboard |
| Flux Controllers | ~264Mi | GitOps (6 controllers) |
| cert-manager | ~119Mi | TLS certificates (3 pods) |
| ESO | ~71Mi | Secret sync (2 pods on pi-k3s) |
| Others | ~200Mi | CoreDNS, metrics-server, etc. |

**Pi 3 Workers - Underutilized:**
- pi3-worker-1: Homepage (147Mi), ingress-nginx, node-exporter, mtgibbs-site
- pi3-worker-2: External Secrets, Alertmanager, Prometheus Operator, ingress-nginx

### Problems Identified

1. **Memory Pressure**: Pi 5 at 81% with no headroom for growth
2. **Single Point of Failure**: Pi-hole on single node (DNS outage = network outage)
3. **Workload Concentration**: Heavy services all on Pi 5 due to Pi 3 limitations
4. **Pi 3 Constraints**: 1GB RAM insufficient for most modern workloads
5. **No HA**: Critical infrastructure has no redundancy

---

## Hardware Requirements

### New Pi 5 Specifications

| Component | Specification | Rationale |
|-----------|---------------|-----------|
| Board | Raspberry Pi 5 8GB | Matches existing master capacity |
| Storage | 64GB+ microSD (A2 rated) | Fast boot, sufficient for OS + local-path |
| Case | Active cooling (fan) | Prevents thermal throttling under load |
| Power | Official 27W USB-C PSU | Required for stable operation |
| Network | Ethernet (1Gbps) | Required for cluster traffic |

**Optional but Recommended:**
- NVMe SSD + HAT: Better I/O for database workloads
- PoE HAT: Simplified cabling if using PoE switch

### Network Configuration

| Parameter | Value |
|-----------|-------|
| Hostname | `pi5-worker-1` |
| IP Address | `192.168.1.54` (DHCP reservation) |
| Gateway | `192.168.1.1` |
| DNS | `1.1.1.1, 8.8.8.8` (static, not Pi-hole) |

**Note:** Static DNS ensures the node can pull images even when Pi-hole is unavailable.

---

## Phase 1: Hardware Setup and K3s Join

### Step 1: OS Installation

1. Flash Raspberry Pi OS Lite 64-bit to microSD
2. Enable SSH by creating empty `ssh` file in boot partition
3. Create user `mtgibbs` during first boot or via `userconf.txt`

### Step 2: Initial Configuration

SSH into the Pi and run:

```bash
# Set hostname
sudo hostnamectl set-hostname pi5-worker-1

# Add SSH key
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo 'YOUR_PUBLIC_KEY_HERE' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys

# Enable cgroups for K3s
sudo sed -i 's/$/ cgroup_memory=1 cgroup_enable=memory/' /boot/firmware/cmdline.txt

# Disable swap
sudo systemctl mask systemd-zram-setup@zram0.service
sudo systemctl disable --now dphys-swapfile 2>/dev/null || true
sudo swapoff -a

# Configure static DNS (critical for image pulls)
sudo nmcli con mod "Wired connection 1" ipv4.dns "1.1.1.1 8.8.8.8"
sudo nmcli con mod "Wired connection 1" ipv4.ignore-auto-dns yes
sudo nmcli con up "Wired connection 1"

# Reboot
sudo reboot
```

### Step 3: Join K3s Cluster

Get the node token from master:
```bash
# On pi-k3s (master)
sudo cat /var/lib/rancher/k3s/server/node-token
```

Install K3s agent on new Pi 5:
```bash
curl -sfL https://get.k3s.io | K3S_URL=https://192.168.1.55:6443 K3S_TOKEN=<TOKEN> sh -
```

### Step 4: Verify Join

```bash
# From workstation
export KUBECONFIG=~/dev/pi-cluster/kubeconfig
kubectl get nodes
# Should show 4 nodes: pi-k3s, pi5-worker-1, pi3-worker-1, pi3-worker-2

kubectl top nodes
# Verify new node resources available
```

### Step 5: Label the Node

```bash
# Add labels for workload targeting
kubectl label node pi5-worker-1 node-role.kubernetes.io/worker=worker
kubectl label node pi5-worker-1 hardware=pi5
kubectl label node pi5-worker-1 memory-class=high

# Also label existing nodes for consistency
kubectl label node pi-k3s hardware=pi5 memory-class=high
kubectl label node pi3-worker-1 hardware=pi3 memory-class=low
kubectl label node pi3-worker-2 hardware=pi3 memory-class=low
```

---

## Phase 2: Workload Redistribution

### Target Architecture

After expansion, workloads should be distributed based on resource requirements:

```
+-------------------+-------------------+-------------------+-------------------+
|     pi-k3s        |   pi5-worker-1    |   pi3-worker-1    |   pi3-worker-2    |
|   (Master+Work)   |     (Worker)      |     (Worker)      |     (Worker)      |
|   192.168.1.55    |   192.168.1.54    |   192.168.1.53    |   192.168.1.51    |
|      8GB          |       8GB         |       1GB         |       1GB         |
+-------------------+-------------------+-------------------+-------------------+
|                   |                   |                   |                   |
| INFRASTRUCTURE    | MEDIA + DATA      | LIGHTWEIGHT       | LIGHTWEIGHT       |
| ---------------   | ---------------   | ---------------   | ---------------   |
| Flux controllers  | Immich Server     | Homepage          | mtgibbs-site      |
| cert-manager      | Immich PostgreSQL | Uptime Kuma       | AutoKuma          |
| ESO               | Jellyfin          | External Secrets  | Alertmanager      |
| CoreDNS           | Prometheus        | ingress-nginx     | ingress-nginx     |
| metrics-server    | Grafana           | node-exporter     | node-exporter     |
|                   |                   | pihole-exporter   | kube-state-metrics|
| DNS + CRITICAL    |                   |                   |                   |
| ---------------   |                   |                   |                   |
| Pi-hole (primary) | Pi-hole (standby) | Unbound           | Unbound           |
| Unbound           |                   | (HA replica)      | (HA replica)      |
|                   |                   |                   |                   |
| Backup jobs       | Immich Valkey     |                   |                   |
| local-path-prov   |                   |                   |                   |
+-------------------+-------------------+-------------------+-------------------+
   ~3.5GB used          ~4.0GB used         ~400Mi used         ~300Mi used
```

### Migration Order

1. **Move Prometheus** (785Mi) - Largest movable workload
2. **Move Grafana** (696Mi) - Can run independently
3. **Move Immich components** (1.6GB total) - All together for latency
4. **Move Jellyfin** (467Mi) - Media workload

### Step-by-Step Migration

#### 2.1 Move Prometheus to pi5-worker-1

Edit `clusters/pi-k3s/monitoring/helmrelease.yaml`:

```yaml
spec:
  values:
    prometheus:
      prometheusSpec:
        nodeSelector:
          kubernetes.io/hostname: pi5-worker-1
        # OR use hardware label
        # nodeSelector:
        #   hardware: pi5
        #   kubernetes.io/hostname: pi5-worker-1
```

**Note:** Prometheus uses PVC with local-path storage. Migration requires:
1. Stop Prometheus on pi-k3s
2. Backup PVC data via rsync
3. Create new PVC on pi5-worker-1
4. Restore data
5. Start Prometheus

Alternative: Use NFS PVC (see Phase 4).

#### 2.2 Move Grafana to pi5-worker-1

Edit `clusters/pi-k3s/monitoring/helmrelease.yaml`:

```yaml
spec:
  values:
    grafana:
      nodeSelector:
        kubernetes.io/hostname: pi5-worker-1
```

Grafana uses local-path PVC for SQLite database. Same migration considerations as Prometheus.

#### 2.3 Move Immich to pi5-worker-1

Edit `clusters/pi-k3s/immich/helmrelease.yaml`:

```yaml
spec:
  values:
    server:
      nodeSelector:
        kubernetes.io/hostname: pi5-worker-1
    postgresql:
      primary:
        nodeSelector:
          kubernetes.io/hostname: pi5-worker-1
    valkey:
      master:
        nodeSelector:
          kubernetes.io/hostname: pi5-worker-1
```

**Critical:** Immich PostgreSQL uses local-path PVC. Migration path:
1. Trigger pg_dump backup (manual or wait for Sunday)
2. Stop Immich completely
3. Deploy fresh PostgreSQL on pi5-worker-1
4. Restore from backup
5. Start Immich server

Photos stored on NFS (Synology) are accessible from any node.

#### 2.4 Move Jellyfin to pi5-worker-1

Edit `clusters/pi-k3s/jellyfin/deployment.yaml`:

```yaml
spec:
  template:
    spec:
      nodeSelector:
        kubernetes.io/hostname: pi5-worker-1
```

Jellyfin uses NFS for media (no migration needed), but config is in local-path PVC.
Consider fresh deploy or backup/restore.

---

## Phase 3: DNS High Availability

### Current DNS Architecture
```
Clients --> Pi-hole (pi-k3s:53) --> Unbound (ClusterIP) --> Root DNS
```

### Target DNS Architecture (HA)
```
                    +---> Pi-hole Primary (pi-k3s:53)    --+
                    |                                      |
Clients --> DHCP ---+                                      +--> Unbound (anycast)
                    |                                      |
                    +---> Pi-hole Secondary (pi5-worker-1) --+
```

### Implementation Options

#### Option A: Dual Pi-hole with Keepalived (Recommended)

Use keepalived for Virtual IP failover:

1. **Virtual IP**: 192.168.1.100 (shared between pi-k3s and pi5-worker-1)
2. **DHCP advertises**: 192.168.1.100 as DNS server
3. **Failover**: keepalived moves VIP on failure

**Pros:**
- Automatic failover
- Clients see single DNS IP
- No client reconfiguration

**Cons:**
- Additional complexity (keepalived pods)
- Blocklist sync between instances needed

Implementation:
```yaml
# keepalived DaemonSet targeting Pi 5 nodes
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: keepalived
  namespace: pihole
spec:
  selector:
    matchLabels:
      app: keepalived
  template:
    spec:
      hostNetwork: true
      nodeSelector:
        hardware: pi5
      containers:
      - name: keepalived
        image: osixia/keepalived:2.0.20
        env:
        - name: KEEPALIVED_VIRTUAL_IPS
          value: "192.168.1.100"
        - name: KEEPALIVED_INTERFACE
          value: "eth0"
        securityContext:
          capabilities:
            add: [NET_ADMIN, NET_BROADCAST, NET_RAW]
```

#### Option B: DHCP with Multiple DNS Servers

Configure Unifi DHCP to advertise both Pi-hole IPs:
- Primary DNS: 192.168.1.55 (pi-k3s)
- Secondary DNS: 192.168.1.54 (pi5-worker-1)

**Pros:**
- Simple to implement
- No additional software

**Cons:**
- Clients may not failover predictably
- Some devices only use primary DNS
- Blocklist sync still needed

#### Option C: Gravity Sync

Use [Gravity Sync](https://github.com/vmstan/gravity-sync) to keep Pi-hole instances synchronized:

1. Install Gravity Sync on both Pi 5 nodes
2. Configure primary (pi-k3s) and secondary (pi5-worker-1)
3. Sync blocklists, whitelist, blacklist, and settings
4. Run via CronJob every 5 minutes

### Recommended Approach

1. Start with **Option B** (simpler, immediate benefit)
2. Add **Gravity Sync** for blocklist synchronization
3. Optionally add **Option A** (keepalived) later for true VIP failover

---

## Phase 4: Storage Considerations

### Current Storage

| Type | Usage | Node Affinity |
|------|-------|---------------|
| local-path | Prometheus, Grafana, Pi-hole, Uptime Kuma, PostgreSQL | Node-bound |
| NFS | Jellyfin media, Immich photos | Any node |

### Storage Strategy for 4-Node Cluster

#### Local-path (Keep for Now)
- Fast I/O for databases
- Node-specific, requires migration planning
- Suitable for: PostgreSQL, Prometheus TSDB

#### NFS (Expand Usage)
- Shared across all nodes
- Already configured for Synology NAS
- Expand for: Grafana dashboards, application configs

#### Future: Longhorn (Distributed Storage)
Consider Longhorn for distributed block storage:
- Replicated across nodes
- Automatic failover
- Requires: 2+ Pi 5 nodes (Pi 3s too limited)

### Creating NFS PVC for Prometheus

```yaml
# clusters/pi-k3s/monitoring/prometheus-pv.yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: prometheus-nfs
spec:
  capacity:
    storage: 20Gi
  accessModes:
    - ReadWriteOnce
  nfs:
    server: 192.168.1.60
    path: /volume1/k3s-data/prometheus
  persistentVolumeReclaimPolicy: Retain
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: prometheus-nfs
  namespace: monitoring
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 20Gi
  volumeName: prometheus-nfs
```

---

## Phase 5: Update Documentation

### Files to Update

1. **CLAUDE.md** - Update current state, node list, workload distribution
2. **ARCHITECTURE.md** - Update diagrams and hardware section
3. **docs/pi-worker-setup.md** - Add Pi 5-specific notes
4. **Homepage configmap** - Add new node to Kubernetes widget

### Node Inventory Update

```markdown
| Role | Hostname | IP | Hardware | RAM |
|------|----------|-----|----------|-----|
| Master | pi-k3s | 192.168.1.55 | Pi 5 | 8GB |
| Worker | pi5-worker-1 | 192.168.1.54 | Pi 5 | 8GB |
| Worker | pi3-worker-1 | 192.168.1.53 | Pi 3 | 1GB |
| Worker | pi3-worker-2 | 192.168.1.51 | Pi 3 | 1GB |
```

---

## Implementation Checklist

### Phase 1: Hardware Setup (Day 1)
- [ ] Purchase Pi 5 8GB + accessories
- [ ] Configure network (DHCP reservation for 192.168.1.54)
- [ ] Flash Pi OS Lite 64-bit
- [ ] Configure hostname, SSH, cgroups, swap
- [ ] Configure static DNS
- [ ] Join K3s cluster
- [ ] Label node (hardware=pi5, memory-class=high)
- [ ] Verify node healthy with `kubectl get nodes`

### Phase 2: Workload Migration (Days 2-3)
- [ ] Move Grafana to pi5-worker-1 (verify dashboards work)
- [ ] Plan Prometheus migration (backup TSDB data)
- [ ] Migrate Prometheus to pi5-worker-1
- [ ] Plan Immich migration (backup PostgreSQL)
- [ ] Migrate Immich to pi5-worker-1
- [ ] Move Jellyfin to pi5-worker-1
- [ ] Verify all services accessible
- [ ] Monitor for 24-48 hours

### Phase 3: DNS HA (Day 4)
- [ ] Deploy second Pi-hole on pi5-worker-1 (hostNetwork)
- [ ] Configure DHCP with dual DNS servers
- [ ] Install Gravity Sync for blocklist sync
- [ ] Test failover (stop primary, verify secondary works)
- [ ] Consider keepalived VIP (optional)

### Phase 4: Documentation (Day 5)
- [ ] Update CLAUDE.md with new architecture
- [ ] Update ARCHITECTURE.md diagrams
- [ ] Update Homepage dashboard config
- [ ] Add Uptime Kuma monitors for new node
- [ ] Create session recap

### Validation Tests
- [ ] All services accessible via Ingress
- [ ] DNS resolution works from all nodes
- [ ] Pi-hole failover works (if HA configured)
- [ ] Prometheus scraping all targets
- [ ] Grafana dashboards loading
- [ ] Discord notifications working
- [ ] Backups completing successfully

---

## Expected Outcome

### Before Expansion
```
pi-k3s:       81% memory (6.5GB/8GB) - CRITICAL
pi3-worker-1: 54% memory (493Mi/910Mi)
pi3-worker-2: 57% memory (519Mi/910Mi)

Total cluster memory: ~10GB usable
```

### After Expansion
```
pi-k3s:       45% memory (~3.5GB/8GB) - Infrastructure + DNS
pi5-worker-1: 50% memory (~4.0GB/8GB) - Media + Monitoring
pi3-worker-1: 45% memory (~400Mi/910Mi) - Lightweight services
pi3-worker-2: 35% memory (~300Mi/910Mi) - Lightweight services

Total cluster memory: ~18GB usable (+80% increase)
```

### Benefits
1. **Headroom for growth**: ~4GB free on each Pi 5
2. **DNS HA**: No single point of failure for DNS
3. **Better separation**: Infrastructure vs. workload nodes
4. **Future-proof**: Room for additional services
5. **Reliability**: Can tolerate single node failure

---

## Cost Estimate

| Item | Cost (USD) |
|------|------------|
| Raspberry Pi 5 8GB | $80 |
| Official 27W PSU | $15 |
| Active cooling case | $15-25 |
| 64GB A2 microSD | $15 |
| Ethernet cable | $5 |
| **Total** | **~$130-140** |

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Data loss during migration | Backup before each migration step |
| DNS downtime during HA setup | Maintain primary until secondary verified |
| Service disruption | Migrate during low-usage hours |
| local-path PVC node affinity | Plan migrations with backup/restore |
| Network misconfiguration | Double-check DHCP reservation before join |

---

## Future Considerations

1. **Remove Pi 3 workers**: Once Pi 5 cluster is stable, Pi 3s can be repurposed
2. **Add third Pi 5**: Full HA with N+1 redundancy
3. **Longhorn storage**: Distributed storage for stateful workloads
4. **K3s HA control plane**: Second master node (requires etcd or external DB)
5. **Dedicated database node**: PostgreSQL, Redis on dedicated hardware
