# Pi-K3s Cluster Architecture

## Overview

A single-node Kubernetes learning cluster running on a Raspberry Pi 5, providing network-wide ad blocking via Pi-hole with privacy-focused recursive DNS resolution via Unbound.

## Hardware

```
┌─────────────────────────────────────────────────────────┐
│                   Raspberry Pi 5                        │
│                                                         │
│   CPU: ARM Cortex-A76 (4 cores)                        │
│   RAM: 8GB                                              │
│   OS:  Raspberry Pi OS Lite (64-bit, Bookworm)         │
│   IP:  192.168.1.55 (DHCP reservation)                 │
│                                                         │
│   ┌─────────────────────────────────────────────────┐  │
│   │                 K3s v1.33.6+k3s1                │  │
│   │                                                 │  │
│   │  • Lightweight Kubernetes distribution          │  │
│   │  • Traefik disabled (--disable=traefik)        │  │
│   │  • Uses local-path storage provisioner         │  │
│   │  • ServiceLB for LoadBalancer services         │  │
│   └─────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## DNS Architecture

### Request Flow

```
┌──────────────┐      DNS Query        ┌──────────────────────────────────────┐
│              │     (port 53)         │           Raspberry Pi               │
│ Client       │ ───────────────────── │                                      │
│ Devices      │                       │  ┌────────────────────────────────┐  │
│              │                       │  │         Pi-hole                │  │
│ • Phones     │                       │  │     (hostNetwork: true)        │  │
│ • Laptops    │                       │  │                                │  │
│ • IoT        │                       │  │  • Ad/tracker blocking         │  │
│              │                       │  │  • DNS caching                 │  │
└──────────────┘                       │  │  • Query logging               │  │
                                       │  │  • Web UI on :80               │  │
                                       │  └───────────┬────────────────────┘  │
                                       │              │                       │
                                       │              │ unbound.pihole.svc    │
                                       │              │ .cluster.local:5335   │
                                       │              ▼                       │
                                       │  ┌────────────────────────────────┐  │
                                       │  │         Unbound                │  │
                                       │  │      (ClusterIP svc)           │  │
                                       │  │                                │  │
                                       │  │  • Recursive resolver          │  │
                                       │  │  • DNSSEC validation           │  │
                                       │  │  • No upstream forwarder       │  │
                                       │  └───────────┬────────────────────┘  │
                                       └──────────────┼───────────────────────┘
                                                      │
                              ┌────────────────────── │ ──────────────────────┐
                              │                       ▼                       │
                              │              ┌─────────────────┐              │
                              │              │  Root DNS       │              │
                              │              │  Servers        │              │
                              │              └────────┬────────┘              │
                              │                       │                       │
                              │              ┌────────▼────────┐              │
                              │              │  TLD Servers    │              │
                              │              │  (.com, .org)   │              │
                              │              └────────┬────────┘              │
                              │                       │                       │
                              │              ┌────────▼────────┐              │
                              │              │  Authoritative  │              │
                              │              │  Nameservers    │              │
                              │              └─────────────────┘              │
                              │                                               │
                              │                  Internet                     │
                              └───────────────────────────────────────────────┘
```

### Why Recursive DNS (Unbound) Instead of Forwarding?

Traditional setup: Pi-hole → Cloudflare/Google (upstream forwarder)

Our setup: Pi-hole → Unbound → Root servers (recursive resolution)

**Benefits:**
- **Privacy**: No single upstream provider sees all your DNS queries
- **No trust required**: You're not trusting Google/Cloudflare with your browsing data
- **DNSSEC validation**: Unbound validates signatures at the source
- **Reduced latency** (after cache warm-up): Popular domains cached locally

**Trade-offs:**
- Initial queries slower (must traverse DNS hierarchy)
- Slightly more CPU/memory usage
- More complex setup

## Kubernetes Architecture

### Namespace Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              K3s Cluster                                │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                      pihole namespace                             │  │
│  │                                                                   │  │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐  │  │
│  │  │    Pi-hole      │  │    Unbound      │  │ pihole-exporter  │  │  │
│  │  │   Deployment    │  │   Deployment    │  │   Deployment     │  │  │
│  │  │                 │  │                 │  │                  │  │  │
│  │  │ pihole/pihole   │  │ madnuttah/      │  │ ekofr/pihole-    │  │  │
│  │  │ :latest         │  │ unbound:latest  │  │ exporter:latest  │  │  │
│  │  └────────┬────────┘  └────────┬────────┘  └────────┬─────────┘  │  │
│  │           │                    │                    │            │  │
│  │  ┌────────▼────────┐  ┌────────▼────────┐  ┌────────▼─────────┐  │  │
│  │  │    (hostNet)    │  │  ClusterIP svc  │  │  ClusterIP svc   │  │  │
│  │  │  :53 UDP/TCP    │  │  :5335 UDP/TCP  │  │  :9617 metrics   │  │  │
│  │  │  :80 HTTP       │  └─────────────────┘  └──────────────────┘  │  │
│  │  └─────────────────┘                                             │  │
│  │                                                                   │  │
│  │  ┌─────────────────────────────────────────────────────────────┐ │  │
│  │  │                     Storage (PVCs)                          │ │  │
│  │  │  • pihole-etc (1Gi)      → /etc/pihole                     │ │  │
│  │  │  • pihole-dnsmasq (100Mi) → /etc/dnsmasq.d                 │ │  │
│  │  │  StorageClass: local-path (k3s default)                    │ │  │
│  │  └─────────────────────────────────────────────────────────────┘ │  │
│  │                                                                   │  │
│  │  ┌─────────────────────────────────────────────────────────────┐ │  │
│  │  │                       Secrets                               │ │  │
│  │  │  • pihole-secret (WEBPASSWORD)                             │ │  │
│  │  │    Synced from 1Password via ExternalSecret                │ │  │
│  │  └─────────────────────────────────────────────────────────────┘ │  │
│  │                                                                   │  │
│  │  ┌─────────────────────────────────────────────────────────────┐ │  │
│  │  │                      ConfigMaps                             │ │  │
│  │  │  • pihole-adlists (adlists.txt)                            │ │  │
│  │  │    GitOps-managed blocklists (Firebog curated, ~900k)      │ │  │
│  │  └─────────────────────────────────────────────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                  external-secrets namespace                       │  │
│  │                                                                   │  │
│  │  ┌─────────────────────────────────────────────────────────────┐ │  │
│  │  │  External Secrets Operator (ESO v1.2.0)                     │ │  │
│  │  │  • Syncs secrets from 1Password via SDK provider            │ │  │
│  │  │  • ClusterSecretStore: onepassword (pi-cluster vault)       │ │  │
│  │  │  • Service Account token in onepassword-service-account     │ │  │
│  │  └─────────────────────────────────────────────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    monitoring namespace                           │  │
│  │                                                                   │  │
│  │  kube-prometheus-stack (Helm)                                    │  │
│  │  • Prometheus     - metrics collection                           │  │
│  │  • Grafana        - dashboards & visualization                   │  │
│  │  • Alertmanager   - alert routing                                │  │
│  │  • Node Exporter  - host metrics                                 │  │
│  │                                                                   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

### 1. hostNetwork for Pi-hole

**Decision**: Use `hostNetwork: true` instead of LoadBalancer service

**Why**:
- K3s ServiceLB had issues with iptables-nft on Raspberry Pi OS Bookworm
- DNS on port 53 needs to be directly accessible
- Simpler network path, easier debugging
- Pi-hole binds directly to host's 192.168.1.55:53

**Trade-off**: Pod uses host network stack, potential port conflicts

### 2. Recreate Deployment Strategy

**Decision**: Use `strategy: Recreate` instead of RollingUpdate

**Why**:
- PVCs use ReadWriteOnce access mode
- Only one pod can mount the volume at a time
- Recreate ensures old pod terminates before new one starts

### 3. Unbound on Port 5335

**Decision**: Non-standard DNS port for Unbound

**Why**:
- Avoids conflict with Pi-hole on port 53
- No need for root/privileged port binding
- Standard practice for local recursive resolvers

### 4. DNSSEC Disabled in Pi-hole

**Decision**: Set `DNSSEC=false` in Pi-hole config

**Why**:
- Unbound handles DNSSEC validation
- Enabling in both would be redundant
- Unbound is the authoritative validator in our chain

### 5. Secrets via External Secrets Operator

**Decision**: Use ESO with 1Password SDK provider instead of manual secrets

**Why**:
- Secrets synced from 1Password cloud automatically
- No secrets in git, no manual `kubectl create secret` commands
- Service account token is the only bootstrap secret (one-time setup)
- Secrets auto-refresh on schedule (1h default)

### 6. Pi-hole v6 Configuration via API

**Decision**: Configure Pi-hole settings via REST API in postStart hook, not env vars

**Why**:
- Pi-hole v6 ignores most environment variables (`WEBPASSWORD`, `PIHOLE_DNS_`, etc.)
- postStart lifecycle hook runs after container starts
- API calls configure: password, upstream DNS (Unbound), adlists
- Adlists managed via ConfigMap, added in batch via API

### 7. Traefik Disabled

**Decision**: Install k3s with `--disable=traefik`

**Why**:
- Not needed for DNS workload
- Reduces resource usage on single Pi
- Can add nginx-ingress or Traefik later if needed for web workloads

## Observability Stack

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Monitoring Flow                                 │
│                                                                         │
│  ┌──────────────┐     scrapes      ┌──────────────┐                    │
│  │ pihole-      │ ◄──────────────  │  Prometheus  │                    │
│  │ exporter     │    /metrics      │              │                    │
│  │ :9617        │    (30s)         │  • Stores    │                    │
│  └──────────────┘                  │    metrics   │                    │
│                                    │  • Runs      │                    │
│  ┌──────────────┐     scrapes      │    queries   │                    │
│  │ node-        │ ◄──────────────  │              │                    │
│  │ exporter     │    /metrics      └───────┬──────┘                    │
│  │ :9100        │                          │                           │
│  └──────────────┘                          │ PromQL queries            │
│                                            ▼                           │
│                                    ┌──────────────┐                    │
│                                    │   Grafana    │                    │
│                                    │              │                    │
│                                    │  • Dashboards│                    │
│                                    │  • Alerts    │                    │
│                                    │  • :3000     │                    │
│                                    └──────────────┘                    │
└─────────────────────────────────────────────────────────────────────────┘
```

### Pi-hole Metrics Available

Via ServiceMonitor → pihole-exporter:
- `pihole_domains_being_blocked` - Total blocklist size
- `pihole_dns_queries_today` - Query count
- `pihole_ads_blocked_today` - Blocked count
- `pihole_ads_percentage_today` - Block rate %
- `pihole_unique_domains` - Unique domains queried
- `pihole_queries_forwarded` - Queries sent to Unbound
- `pihole_queries_cached` - Cache hit count

## File Structure

```
pi-cluster/
├── ARCHITECTURE.md          # This file
├── CLAUDE.md                # Project context & instructions
├── README.md                # Basic readme
├── kubeconfig               # Local kubectl config (git-ignored)
├── scripts/                 # Utility scripts
└── clusters/
    └── pi-k3s/
        ├── pihole/
        │   ├── unbound-configmap.yaml    # Unbound DNS config
        │   ├── unbound-deployment.yaml   # Unbound + ClusterIP svc
        │   ├── pihole-pvc.yaml           # Persistent volumes
        │   ├── pihole-deployment.yaml    # Pi-hole with hostNetwork
        │   ├── pihole-service.yaml       # ClusterIP for web UI
        │   └── pihole-exporter.yaml      # Prometheus exporter + ServiceMonitor
        └── flux-system/                  # Future GitOps (empty)
```

## Network Details

| Component | Port | Protocol | Exposure |
|-----------|------|----------|----------|
| Pi-hole DNS | 53 | UDP/TCP | hostNetwork (192.168.1.55:53) |
| Pi-hole Web | 80 | TCP | hostNetwork (192.168.1.55:80) |
| Unbound | 5335 | UDP/TCP | ClusterIP (internal only) |
| pihole-exporter | 9617 | TCP | ClusterIP (Prometheus scrapes) |
| Grafana | 3000 | TCP | ClusterIP (port-forward to access) |
| Prometheus | 9090 | TCP | ClusterIP (port-forward to access) |

## Resource Allocations

| Component | CPU Request | CPU Limit | Memory Request | Memory Limit |
|-----------|-------------|-----------|----------------|--------------|
| Pi-hole | 100m | 500m | 128Mi | 512Mi |
| Unbound | 50m | 500m | 64Mi | 256Mi |
| pihole-exporter | 10m | 100m | 32Mi | 64Mi |

## Quick Reference Commands

```bash
# Set kubeconfig
export KUBECONFIG=~/dev/pi-cluster/kubeconfig

# Check everything
kubectl get pods -A

# Pi-hole logs
kubectl -n pihole logs -f deploy/pihole

# Test DNS resolution
nslookup google.com 192.168.1.55

# Access Grafana (then open http://localhost:3000)
kubectl -n monitoring port-forward svc/kube-prometheus-grafana 3000:80

# Set/reset Pi-hole password
kubectl -n pihole exec deploy/pihole -- pihole setpassword 'newpassword'

# Check metrics endpoint
kubectl -n pihole port-forward svc/pihole-exporter 9617:9617
curl localhost:9617/metrics
```

## DNS Resilience

The Pi node needs DNS to pull container images during upgrades. Since the Pi runs Pi-hole, there's a chicken-and-egg problem: if Pi-hole is down, the Pi can't resolve DNS to pull the new Pi-hole image.

**Solution**: Configure static DNS on the Pi node that doesn't depend on Pi-hole:

```bash
# NetworkManager configuration (persists across reboots)
sudo nmcli con mod "Wired connection 1" ipv4.dns "1.1.1.1 8.8.8.8"
sudo nmcli con mod "Wired connection 1" ipv4.ignore-auto-dns yes
sudo nmcli con up "Wired connection 1"
```

This ensures:
- Pi node can always pull images (uses 1.1.1.1/8.8.8.8 directly)
- K8s pods use CoreDNS → Unbound for cluster DNS (independent of Pi-hole)
- Network clients experience brief timeouts during Pi-hole restarts, but never bypass ad blocking

## Future Roadmap

- [x] **Secrets Management**: External Secrets Operator with 1Password
- [x] **Flux GitOps**: Auto-deploy on git push
- [x] **DNS Resilience**: Static DNS on Pi node for image pulls
- [ ] **Ingress + TLS**: nginx-ingress + cert-manager for HTTPS
- [ ] **Additional Apps**: Uptime Kuma, Homepage dashboard
- [ ] **Multi-node**: Add second Pi for HA learning
