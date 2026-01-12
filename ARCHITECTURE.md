# Pi-K3s Cluster Architecture

## Overview

A 4-node Kubernetes learning cluster running on Raspberry Pi hardware, providing high-availability network-wide ad blocking via dual Pi-hole instances with privacy-focused recursive DNS resolution via Unbound. Includes Tailscale VPN for mobile ad blocking, self-hosted media services, and comprehensive monitoring with Discord alerting.

## Hardware

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                               K3s Cluster (4 nodes)                                     │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                         │
│  ┌──────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐  ┌───────┐│
│  │  pi-k3s              │  │  pi5-worker-1       │  │  pi5-worker-2       │  │  pi3- ││
│  │  (Master+Worker)     │  │  192.168.1.56       │  │  192.168.1.57       │  │  work ││
│  │  192.168.1.55        │  │                     │  │                     │  │  er-2 ││
│  ├──────────────────────┤  ├─────────────────────┤  ├─────────────────────┤  │  192. ││
│  │ Raspberry Pi 5       │  │ Raspberry Pi 5      │  │ Raspberry Pi 5      │  │  168. ││
│  │ Cortex-A76 (4 cores) │  │ Cortex-A76 (4 core) │  │ Cortex-A76 (4 core) │  │  1.51 ││
│  │ RAM: 8GB             │  │ RAM: 8GB            │  │ RAM: 8GB            │  │       ││
│  │ Debian 13 (64-bit)   │  │ Debian 13 (64-bit)  │  │ Debian 13 (64-bit)  │  │  Pi 3 ││
│  │                      │  │                     │  │                     │  │  1GB  ││
│  │ Workloads:           │  │ Workloads:          │  │ Workloads:          │  │  RAM  ││
│  │ • Pi-hole primary    │  │ • Pi-hole HA        │  │ • Heavy workloads   │  │       ││
│  │ • Unbound            │  │   (secondary)       │  │ • Distributed apps  │  │  Lite ││
│  │ • Flux controllers   │  │ • Heavy workloads   │  │                     │  │  apps ││
│  │ • Backup jobs        │  │ • Media services    │  │                     │  │  only ││
│  │ • Critical infra     │  │ • Tailscale exit    │  │                     │  │       ││
│  │ • Monitoring stack   │  │                     │  │                     │  │       ││
│  └──────────────────────┘  └─────────────────────┘  └─────────────────────┘  └───────┘│
│                                                                                         │
│  K3s Version: v1.34.3+k3s1                                                             │
│  • Traefik disabled (--disable=traefik)                                                │
│  • local-path storage provisioner (hostPath on master)                                 │
│  • ServiceLB for LoadBalancer services                                                 │
└─────────────────────────────────────────────────────────────────────────────────────────┘
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
│  │  │ (on pi-k3s)     │  │ (pi3-worker-1)  │  │                  │  │  │
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
│  │  • Prometheus     - metrics collection + alert evaluation        │  │
│  │  • Grafana        - dashboards & visualization                   │  │
│  │  • Alertmanager   - alert routing to Discord                     │  │
│  │  • Node Exporter  - host metrics                                 │  │
│  │                                                                   │  │
│  │  Grafana Ingress: grafana.lab.mtgibbs.dev                       │  │
│  │                                                                   │  │
│  │  Secrets:                                                         │  │
│  │  • grafana-admin (Grafana password from 1Password)              │  │
│  │  • alertmanager-discord-webhook (Discord URL from 1Password)     │  │
│  │                                                                   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    ingress-nginx namespace                        │  │
│  │                                                                   │  │
│  │  nginx-ingress-controller (Helm)                                 │  │
│  │  • hostPort 443 (HTTPS) - port 80 used by Pi-hole                │  │
│  │  • TLS termination for all web UIs                               │  │
│  │                                                                   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    cert-manager namespace                         │  │
│  │                                                                   │  │
│  │  cert-manager (Helm)                                             │  │
│  │  • Let's Encrypt ClusterIssuers (letsencrypt-prod, staging)      │  │
│  │  • Cloudflare DNS-01 challenge for *.lab.mtgibbs.dev             │  │
│  │  • Auto-generates trusted TLS certs for Ingress resources        │  │
│  │                                                                   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    uptime-kuma namespace                          │  │
│  │                                                                   │  │
│  │  Uptime Kuma v2                                                  │  │
│  │  • Self-hosted status page                                       │  │
│  │  • Monitors home services (Pi-hole, Grafana, K3s API, etc)       │  │
│  │  • PVC for SQLite database (2Gi)                                 │  │
│  │  • Ingress: status.lab.mtgibbs.dev                              │  │
│  │                                                                   │  │
│  │  AutoKuma (bigboot/autokuma)                                     │  │
│  │  • GitOps-managed monitors via ConfigMap                         │  │
│  │  • Syncs monitor definitions to Uptime Kuma API                  │  │
│  │  • Monitors: Pi-hole DNS (primary + HA), Admin, Grafana,        │  │
│  │    Prometheus, Unbound, K3s API, Uptime Kuma, Homepage,          │  │
│  │    Tailscale Exit Node DNS (10 total)                            │  │
│  │                                                                   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                      homepage namespace                           │  │
│  │                                                                   │  │
│  │  Homepage (gethomepage/homepage)                                 │  │
│  │  • Unified dashboard for all cluster services                    │  │
│  │  • Dark theme with system resource widgets                       │  │
│  │  • Live service widgets (Pi-hole HA, Immich, Jellyfin, Prom,    │  │
│  │    Tailscale, Unifi)                                             │  │
│  │  • Kubernetes widget with node metrics (4-node cluster)          │  │
│  │  • GitOps-managed configuration via ConfigMap                    │  │
│  │  • initContainer copies config to writable emptyDir              │  │
│  │  • RBAC: ServiceAccount with ClusterRole for API access          │  │
│  │  • Secrets: 4 ExternalSecrets for widget API keys                │  │
│  │  • nodeAffinity: Prefers Pi 3 workers (lightweight service)      │  │
│  │  • Ingress: home.lab.mtgibbs.dev                                │  │
│  │                                                                   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    jellyfin namespace                             │  │
│  │                                                                   │  │
│  │  Jellyfin Media Server                                           │  │
│  │  • Self-hosted media streaming (Plex alternative)                │  │
│  │  • NFS PersistentVolume → Synology NAS (192.168.1.60:/volume1/  │  │
│  │    video)                                                         │  │
│  │  • Ingress: jellyfin.lab.mtgibbs.dev                            │  │
│  │                                                                   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                     immich namespace                              │  │
│  │                                                                   │  │
│  │  Immich Photo Management (v2.4.1)                                │  │
│  │  • Self-hosted photo backup and management                       │  │
│  │  • Deployed via Helm chart (immich-charts v0.10.3)               │  │
│  │  • NFS storage to Synology NAS for photos                        │  │
│  │  • PostgreSQL with pgvector extension                            │  │
│  │  • Valkey (Redis) for caching                                    │  │
│  │  • Ingress: immich.lab.mtgibbs.dev                              │  │
│  │                                                                   │  │
│  │  Monitoring:                                                      │  │
│  │  • Prometheus metrics on :8081 (server), :8082 (microservices)  │  │
│  │  • ServiceMonitor for automatic scraping                         │  │
│  │  • PrometheusRule with 6 alerts (queue stuck, slow queries)      │  │
│  │  • Alerts routed to Discord via Alertmanager                     │  │
│  │                                                                   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    mtgibbs-site namespace                         │  │
│  │                                                                   │  │
│  │  Personal Website (Next.js)                                      │  │
│  │  • Auto-deployed via Flux Image Automation                       │  │
│  │  • Source: github.com/mtgibbs/mtgibbs.xyz                        │  │
│  │  • Image: ghcr.io/mtgibbs/mtgibbs.xyz (multi-arch ARM64/AMD64)  │  │
│  │  • Node affinity: prefers Pi 3 workers                          │  │
│  │  • Ingress: site.lab.mtgibbs.dev                                │  │
│  │                                                                   │  │
│  │  Flux Image Automation (flux-system namespace):                  │  │
│  │  • ImageRepository scans GHCR every 5 minutes                    │  │
│  │  • ImagePolicy selects newest timestamp tag (YYYYMMDDHHmmss)     │  │
│  │  • ImageUpdateAutomation updates deployment, commits, pushes     │  │
│  │  • Full auto-deploy: code push → GHCR → Flux detects → deploys  │  │
│  │                                                                   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                flux-notifications namespace                       │  │
│  │                                                                   │  │
│  │  Flux Notification System                                        │  │
│  │  • Discord Provider with webhook URL from 1Password              │  │
│  │  • Alert for all Kustomization/HelmRelease events                │  │
│  │  • Real-time deployment notifications                            │  │
│  │                                                                   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                  external-services namespace                      │  │
│  │                                                                   │  │
│  │  Reverse proxies for external home infrastructure devices        │  │
│  │  • Uses Endpoints + Service pattern to proxy external IPs        │  │
│  │  • Each service gets TLS via cert-manager + Ingress              │  │
│  │                                                                   │  │
│  │  Services:                                                        │  │
│  │  • Unifi Controller  - https://unifi.lab.mtgibbs.dev             │  │
│  │    → 192.168.1.30:8443 (HTTPS backend)                          │  │
│  │  • Synology NAS      - https://nas.lab.mtgibbs.dev               │  │
│  │    → 192.168.1.60:5000 (HTTP backend)                           │  │
│  │                                                                   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    tailscale namespace                            │  │
│  │                                                                   │  │
│  │  Tailscale Operator (HelmRelease v1.92.5)                        │  │
│  │  • Kubernetes operator for Tailscale resources                   │  │
│  │  • OAuth authentication (minimal scopes: Devices + Auth Keys)    │  │
│  │  • Credentials synced from 1Password via ExternalSecret          │  │
│  │                                                                   │  │
│  │  Tailscale Connector (Exit Node)                                 │  │
│  │  • Hostname: pi-cluster-exit                                     │  │
│  │  • Exit node enabled for full tunnel VPN                         │  │
│  │  • Subnet routes advertised:                                     │  │
│  │    - 192.168.1.55/32 (Pi-hole primary)                           │  │
│  │    - 192.168.1.56/32 (Pi-hole secondary)                         │  │
│  │  • ProxyClass with arm64 nodeSelector (ensures Pi 5 scheduling)  │  │
│  │  • Tagged with tag:k8s-operator for ACL policy matching          │  │
│  │                                                                   │  │
│  │  Use Cases:                                                       │  │
│  │  • Split Tunnel: DNS-only for mobile ad blocking                 │  │
│  │  • Full Tunnel: All traffic for privacy + ad blocking            │  │
│  │  • Zero port forwarding: NAT traversal via WireGuard             │  │
│  │                                                                   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    mtgibbs-site namespace                         │  │
│  │                                                                   │  │
│  │  Personal Website (Next.js)                                      │  │
│  │  • Auto-deployed via Flux Image Automation                       │  │
│  │  • Image: ghcr.io/mtgibbs/mtgibbs.xyz (multi-arch ARM64/AMD64)  │  │
│  │  • Node affinity: prefers Pi 3 workers                          │  │
│  │  • Ingress: site.lab.mtgibbs.dev                                │  │
│  │                                                                   │  │
│  │  Flux Image Automation (flux-system namespace):                  │  │
│  │  • ImageRepository scans GHCR every 5 minutes                    │  │
│  │  • ImagePolicy selects newest timestamp tag (YYYYMMDDHHmmss)     │  │
│  │  • ImageUpdateAutomation updates deployment, commits, pushes     │  │
│  │                                                                   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                 cloudflare-tunnel namespace                       │  │
│  │                                                                   │  │
│  │  Cloudflare Tunnel (cloudflared)                                 │  │
│  │  • External HTTPS ingress via Cloudflare network                 │  │
│  │  • Public endpoint: logs.mtgibbs.dev                             │  │
│  │  • Routes to internal services without port forwarding           │  │
│  │  • Token authentication from 1Password via ExternalSecret        │  │
│  │  • Init container converts token to credentials.json             │  │
│  │  • Node affinity: prefers Pi 5 workers                          │  │
│  │                                                                   │  │
│  │  Ingress Routes:                                                  │  │
│  │  • logs.mtgibbs.dev → vector.log-aggregation:8080 (HTTP)        │  │
│  │                                                                   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                  log-aggregation namespace                        │  │
│  │                                                                   │  │
│  │  Log Aggregation Stack (Heroku Log Drain)                        │  │
│  │                                                                   │  │
│  │  Vector (Log Processor)                                          │  │
│  │  • HTTP endpoint for log ingestion (port 8080)                   │  │
│  │  • Parses Heroku syslog format with VRL transforms              │  │
│  │  • Extracts structured data: app, dyno, level                   │  │
│  │  • Routes to Loki with labels for filtering                     │  │
│  │  • Node affinity: prefers Pi 5 workers                          │  │
│  │                                                                   │  │
│  │  Loki (Log Storage)                                              │  │
│  │  • Single-binary deployment mode                                │  │
│  │  • Filesystem storage: 10Gi PVC on pi5-worker-2                 │  │
│  │  • 7-day retention (168h)                                       │  │
│  │  • Caching disabled for resource constraints                    │  │
│  │  • Exposed as Grafana datasource                                │  │
│  │                                                                   │  │
│  │  Log Flow:                                                        │  │
│  │  Heroku App → logs.mtgibbs.dev → Vector → Loki → Grafana       │  │
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
- Using nginx-ingress instead for web workloads

### 8. nginx-ingress on hostPort 443 Only

**Decision**: Use hostPort 443 (HTTPS) only, not port 80

**Why**:
- Port 80 is already used by Pi-hole's hostNetwork
- All traffic should be HTTPS anyway
- Services accessed via HTTPS (self-signed certificates)

### 9. Let's Encrypt with Cloudflare DNS-01

**Decision**: Use Let's Encrypt certificates with Cloudflare DNS-01 challenge

**Why**:
- Trusted TLS certificates (no browser warnings)
- DNS-01 challenge works for internal services (no public HTTP required)
- Cloudflare manages `mtgibbs.dev` DNS, easy API integration
- API token synced from 1Password via ExternalSecret

**Setup**:
- ClusterIssuers: `letsencrypt-prod`, `letsencrypt-staging`
- Cloudflare API token with Zone:DNS:Edit permission
- Wildcard DNS record `*.lab.mtgibbs.dev → 192.168.1.55` (proxy OFF)

### 10. Subdomain-based Routing via lab.mtgibbs.dev

**Decision**: Use `service.lab.mtgibbs.dev` pattern instead of path-based routing

**Why**:
- Many apps (like Uptime Kuma) don't work well with subpath routing
- Subdomains are cleaner and more standard
- Custom domain allows for trusted Let's Encrypt certificates
- Wildcard DNS record means no per-service DNS configuration

### 11. External Service Reverse Proxies

**Decision**: Create Kubernetes Endpoints + Service resources to proxy external home infrastructure devices

**Why**:
- Provides unified access pattern via `*.lab.mtgibbs.dev` subdomains
- Adds TLS encryption for devices that don't natively support Let's Encrypt
- Centralizes access through nginx-ingress for consistent logging/monitoring
- No need to expose multiple ports on the Pi - everything goes through 443

**How**:
- Create manual Endpoints resource with external IP:port
- Create Service with same name (type ClusterIP, no selector)
- Service routes to Endpoints automatically
- Ingress points to Service for TLS termination

**Trade-offs**:
- Adds extra network hop (client → nginx → external device)
- Requires manual Endpoints updates if IP changes
- Some devices (like Unifi) need special nginx annotations for HTTPS backends

### 12. AutoKuma Persistent Storage

**Decision**: Add PVC for AutoKuma's /data directory

**Why**:
- AutoKuma uses sled embedded database to track which monitors it has created
- Without persistence, database is lost on pod restart
- This causes AutoKuma to forget it created monitors and creates duplicates
- PVC ensures database survives pod restarts

**Implementation**:
- 100Mi PVC (ReadWriteOnce)
- Mounted at /data in AutoKuma container
- Deployment strategy changed to Recreate (required for RWO PVC)

### 13. Multi-Node Cluster with Heterogeneous Hardware

**Decision**: Expand from single Pi 5 to 3-node cluster (Pi 5 + 2x Pi 3)

**Why**:
- Learning opportunity for multi-node Kubernetes operations
- Better resource utilization through workload distribution
- Foundation for future HA implementations

**How**:
- Pi 5 remains master + worker (critical infrastructure)
- Pi 3s added as workers only (1GB RAM each)
- Strategic nodeSelector placement for specific workloads (Unbound on pi3-worker-1)
- Backup jobs pinned to pi-k3s (require hostPath access to local-path PVCs)

**Trade-offs**:
- Increased complexity in workload placement
- Need to account for Pi 3's limited resources (1GB RAM vs 8GB on Pi 5)
- local-path storage remains node-specific (no shared storage)

### 14. Jellyfin as Plex Alternative

**Decision**: Deploy Jellyfin instead of expanding Plex usage

**Why**:
- Open-source with no proprietary restrictions
- Better privacy (no phone-home to Plex servers)
- Full control over media server functionality
- NFS integration with existing Synology NAS storage

**Implementation**:
- Full GitOps deployment in `jellyfin` namespace
- NFS PersistentVolume to Synology NAS (`/volume1/video`)
- Ingress with Let's Encrypt certificate
- Replaces Plex in Homepage dashboard

**Trade-offs**:
- UI less polished than Plex
- Client apps less feature-rich
- But: no licensing concerns, better long-term maintainability

### 15. Immich v2 Migration Strategy

**Decision**: Two-step upgrade path for Immich (v1.123.0 → v1.132.3 → v2.4.1)

**Why**:
- Immich v2 introduced major database changes (TypeORM → Kysely migration)
- Direct upgrade from v1.123.0 would skip critical migration steps
- Helm chart 0.10.x introduced breaking changes in configuration format

**How**:
- Step 1: Upgrade to v1.132.3 (last TypeORM version, prepares for migration)
- Step 2: Upgrade to v2.4.1 (Kysely migration runs automatically)
- Fixed storage: `IMMICH_MEDIA_LOCATION=/data` (matches PVC mount point)
- Adjusted for Pi ARM compatibility (postgres with pgvector, NFSv3 for Synology)

**Trade-offs**:
- Longer migration window with potential for data issues
- Required manual intervention (couldn't be fully automated)
- But: data integrity preserved, proper migration path followed

### 16. Flux Discord Notifications

**Decision**: Add Discord webhook integration for Flux deployment events

**Why**:
- Real-time visibility into GitOps deployments
- Immediate feedback on successful/failed reconciliations
- Better observability for changes pushed to GitHub

**Implementation**:
- Discord Provider in `flux-notifications` namespace
- Alert resource monitors all Kustomizations and HelmReleases
- Webhook URL synced from 1Password via ExternalSecret
- 30s timeout added to accommodate Pi network latency

**Trade-offs**:
- Adds external dependency (Discord availability)
- Webhook URL is a secret (requires 1Password ESO setup)
- But: significantly improves deployment visibility

### 17. Homepage Kubernetes Widget with RBAC

**Decision**: Add Kubernetes cluster metrics widget to Homepage dashboard

**Why**:
- Real-time visibility into node health (CPU, memory, uptime)
- Centralized cluster status in unified dashboard
- Demonstrates multi-node cluster operation

**Implementation**:
- ServiceAccount with ClusterRole for read-only node metrics access
- ClusterRoleBinding grants Homepage pod ability to query Kubernetes API
- Widget configured in ConfigMap to display all 3 nodes

**Trade-offs**:
- Requires RBAC permissions (security consideration)
- Adds API calls to Kubernetes control plane
- But: invaluable for monitoring cluster health at a glance

### 18. Homepage Live Service Widgets

**Decision**: Add API-integrated widgets for real-time service statistics

**Why**:
- Unified dashboard shows live cluster health at a glance
- Reduces need to visit individual service UIs for status checks
- Demonstrates GitOps secret management with multiple API keys

**Implementation**:
- Each service widget requires its own API key or credentials
- Separate ExternalSecret per service for independent auth lifecycle
- API keys synced from 1Password via ESO to Kubernetes secrets
- Secrets injected as environment variables using `HOMEPAGE_VAR_*` pattern
- Homepage ConfigMap references env vars in widget configuration

**Services with Live Widgets**:
- Pi-hole: queries, blocked count, blocked %, gravity size (v6 API)
- Immich: photos, videos, storage (API key with server.statistics permission)
- Jellyfin: library stats, now playing (API key)
- Prometheus: targets up/down/total (read-only metrics endpoint)
- Uptime Kuma: service status (requires status page with slug 'home')
- Unifi: WiFi users, LAN devices, WAN (local account credentials)

**Security Flow**:
1. API keys stored in 1Password `pi-cluster` vault
2. ExternalSecret syncs to Kubernetes secret in `homepage` namespace
3. Secret mounted as env var in Homepage deployment
4. ConfigMap references env var for widget auth
5. No secrets exposed in git repository

**Trade-offs**:
- More complex secret management (4+ separate ExternalSecrets)
- Requires creating/managing API keys for each service
- Widget failures are graceful (service tiles still show with siteMonitor fallback)
- But: significantly better UX and operational visibility

### 19. PostgreSQL Backup Job

**Decision**: Add dedicated PostgreSQL backup job for database-level backups

**Why**:
- PVC backups capture filesystem state, but database-level backups provide:
  - Consistent point-in-time snapshots (via pg_dump transactional backup)
  - Cross-database restore capability (can restore to different cluster)
  - Easier selective restore (specific tables/schemas)
- Immich database contains critical metadata (albums, user accounts, sharing, ML embeddings)

**Implementation**:
- CronJob runs Sundays at 2:30 AM (30 minutes after PVC backup)
- Uses pg_dump with custom format and compression level 9
- Connects to PostgreSQL service in cluster (immich-postgresql.immich.svc.cluster.local)
- Transfers compressed dump to Synology NAS via **rsync over SSH** (not scp)
- DB password synced from 1Password via ExternalSecret
- Pinned to pi-k3s node (same as PVC backup for consistency)
- PostgreSQL client: postgresql16-client (Alpine package name)

**Backup Strategy**:
- PVC backup: Full filesystem snapshot (photos, config, data directory)
- PostgreSQL backup: Database logical backup (metadata, schema, indexes)
- Together: Complete disaster recovery capability

**Technical Notes**:
- rsync chosen over scp because Synology NAS has SFTP subsystem disabled
- rsync works over plain SSH, provides compression and resume capability
- Alpine Linux repos updated from PostgreSQL 14 to 16 client

**Trade-offs**:
- Duplicates some data (database files exist in both backups)
- Additional backup window (30 minutes offset)
- More complex restore procedure (requires both backup types)
- But: provides defense-in-depth and flexible recovery options

---

### 20. Immich Prometheus Monitoring and Alerting

**Decision**: Enable Prometheus metrics collection and alerting for Immich

**Why**:
- Immich has background job processing (thumbnails, video transcoding, metadata extraction)
- Job queue stuck conditions are not visible without metrics
- Database performance degradation can impact user experience
- Proactive alerting prevents user-facing issues

**Implementation**:
- Enabled Immich telemetry: `IMMICH_TELEMETRY_INCLUDE=all`
- Configured metrics endpoints: port 8081 (server), 8082 (microservices)
- Created ServiceMonitor to scrape metrics every 30 seconds
- Created Service with `app.kubernetes.io/component: metrics` label for Prometheus discovery
- Created PrometheusRule with 6 alerts:
  1. ImmichServerDown (service unreachable > 1 minute)
  2. ImmichThumbnailQueueStuck (queue > 500 for 30 minutes)
  3. ImmichVideoQueueStuck (queue > 50 for 30 minutes)
  4. ImmichMetadataQueueStuck (queue > 100 for 30 minutes)
  5. ImmichNoThumbnailActivity (no processing for 6 hours)
  6. ImmichDatabaseSlowQueries (query duration > 5s for 5 minutes)

**Alert Routing**:
- Alerts fired to Alertmanager
- Routed to Discord receiver with 5-minute group interval
- Resolved alerts also sent for visibility

**Trade-offs**:
- Additional metrics storage in Prometheus (minimal overhead)
- Alert tuning required to avoid false positives
- But: significantly better operational visibility

---

### 21. Alertmanager Discord Integration

**Decision**: Enable Alertmanager in kube-prometheus-stack and route alerts to Discord

**Why**:
- Prometheus alerts were being evaluated but had no notification destination
- Discord provides low-friction, real-time notifications
- Webhook integration is simple and reliable
- Centralized alerting for all cluster alerts (Kubernetes + application)

**Implementation**:
- Enabled `alertmanager.enabled: true` in kube-prometheus-stack HelmRelease
- Configured Discord receiver in `alertmanager.config.receivers`
- Used Flux `valuesFrom` to inject webhook URL from Kubernetes secret
- ExternalSecret syncs webhook URL from 1Password (`alertmanager/discord-alerts-webhook-url`)
- Default route sends all alerts to Discord receiver
- 5-minute group interval to batch related alerts
- Silenced noisy alerts: Watchdog (intentional heartbeat), KubeMemoryOvercommit (expected behavior)

**Message Format**:
```
[SEVERITY] Alert: ALERTNAME
Instance: INSTANCE
Description: DESCRIPTION
```

**Security**:
- Webhook URL never committed to git
- Stored in 1Password, synced via ESO
- Injected at Helm chart deployment time via Flux valuesFrom

**Trade-offs**:
- External dependency on Discord availability
- Webhook URL is a secret (requires 1Password setup)
- Alert fatigue if not properly silenced/tuned
- But: immediate visibility into cluster health issues

---

### 22. ExternalSecret Refresh Interval (1Password Rate Limiting)

**Decision**: Set `refreshInterval: 24h` for all ExternalSecrets (changed from default 1h)

**Why**:
- 1Password SDK provider has strict API rate limits (1,000-10,000 calls/hour depending on tier)
- 13 ExternalSecrets refreshing every 1h = 312 API calls/day
- ESO reconciliation loops + retries amplified traffic, triggering rate limits
- Cluster secrets are static (passwords/API tokens rarely change)
- Frequent refreshes provided no operational value but exhausted quota

**Implementation**:
- Updated all 13 ExternalSecret manifests with `refreshInterval: 24h`
- Reduces API calls from 312/day to 13/day (96% reduction)
- Secrets still refresh daily for validation and drift detection

**Affected ExternalSecrets**:
- backup-jobs: backup-ssh-key, postgres-backup-secret
- cert-manager-config: cloudflare-api-token
- flux-notifications: discord-webhook
- homepage: 4 secrets (pihole, jellyfin, immich, unifi)
- immich: immich-secret
- monitoring: 2 secrets (grafana, alertmanager-discord)
- pihole: pihole-secret
- uptime-kuma: uptime-kuma-secret

**Trade-offs**:
- Secret changes take up to 24h to propagate (acceptable for static credentials)
- Manual secret rotation requires forcing sync or waiting up to 24h
- But: eliminates rate limit errors, improves cluster stability, reduces API costs

**Future Enhancement**: Migrate to 1Password Connect Server for unlimited local re-requests (documented in plans)

---

### 23. Flux Image Automation for Personal Website

**Decision**: Deploy image-reflector-controller and image-automation-controller for automatic image updates

**Why**:
- Eliminate manual deployment steps (build → push → update YAML → commit → push)
- Full GitOps workflow for personal projects (code push → auto-deploy within 10 minutes)
- Demonstrate advanced Flux features in learning cluster
- Enable continuous deployment for frequently updated services

**Implementation**:
- **ImageRepository**: Scans `ghcr.io/mtgibbs/mtgibbs.xyz` every 5 minutes for new tags
- **ImagePolicy**: Filters for timestamp tags matching `^[0-9]{14}$` (YYYYMMDDHHmmss format)
  - Uses numerical sorting (ascending) to select newest tag
  - Example tags: `20260104084623`, `20260104123045`
- **ImageUpdateAutomation**: Updates deployment.yaml with new image tag
  - Uses Setters strategy with marker comment: `# {"$imagepolicy": "flux-system:mtgibbs-site"}`
  - Commits changes with message: `chore: update mtgibbs-site to <tag>`
  - Pushes to main branch using Flux deploy key
- **RBAC**: Created ServiceAccounts + ClusterRoles for both controllers
- **Flux Bootstrap**: Re-bootstrapped with `--read-write-key` flag for git push access
- **GitHub PAT**: Fine-grained token with Contents (read/write) + Administration permissions
  - Scoped to pi-cluster repository only
  - 90-day expiration (stored in 1Password: `flux-github-pat`)

**Auto-Deploy Flow**:
1. Developer pushes to `mater` branch in mtgibbs.xyz repository
2. GitHub Actions builds multi-arch image (AMD64 + ARM64)
3. Image pushed to GHCR with timestamp tag (e.g., `20260104084623`)
4. ImageRepository scans GHCR every 5 minutes, detects new tag
5. ImagePolicy evaluates new tag as newest (higher number = newer)
6. ImageUpdateAutomation updates deployment.yaml, commits, pushes
7. Flux Kustomization reconciles (every 10 minutes), deploys new version
8. Total time from code push to deployment: ~5-15 minutes

**Trade-offs**:
- More complex setup (requires write-access deploy key, RBAC, fine-grained PAT)
- Flux has write access to pi-cluster repo (security consideration)
- Additional controllers consume ~50Mi memory
- Tags are timestamps (not semantic versioning), harder to identify changes between versions
- Must renew GitHub PAT every 90 days
- But: fully automated deploys, no manual intervention, true GitOps workflow

**Multi-Architecture Builds**:
- Uses GitHub Actions with `docker/buildx-action` and QEMU emulation
- Builds for `linux/amd64` and `linux/arm64` platforms
- ARM64 support required for Raspberry Pi cluster
- GHCR stores multi-arch manifest (Docker pulls correct platform automatically)

**Timestamp Tag Rationale**:
- Flux ImagePolicy numerical sorting requires numeric-only tags
- Git SHAs are alphanumeric (can't be sorted numerically)
- Timestamps are monotonically increasing (always newer = higher number)
- Human-readable (can see build time at a glance: `20260104084623` = 2026-01-04 08:46:23 UTC)

---

### 24. Dual-Stack IPv6 Networking (RDNSS Empty for Pi-hole)

**Decision**: Enable full IPv6 dual-stack networking with SLAAC, but leave RDNSS empty to preserve Pi-hole as sole DNS server

**Why**:
- Users experienced 10+ second browser delays due to IPv6 "Happy Eyeballs" timeouts
- Clients had IPv6 enabled but no IPv6 route to internet (link-local only)
- Browsers try IPv6 first, wait ~10s for timeout, then fallback to IPv4
- Disabling IPv6 on clients is a workaround, not a solution
- IPv6 is the future (IPv4 address exhaustion, better routing, many services prioritize IPv6)

**Problem**:
- AT&T Fiber provides IPv6 via DHCPv6-PD, but USG had IPv6 disabled
- Clients advertised fe80:: link-local addresses but had no global IPv6 addresses
- No IPv6 route to internet meant all IPv6 connection attempts timed out
- Page loads: 10,000ms+ (mostly waiting for IPv6 timeout before IPv4 fallback)

**How**:

**AT&T Gateway (192.168.0.254)** - No changes (already configured):
- IPv6: Enabled
- DHCPv6: Enabled
- DHCPv6-PD: Enabled (delegates /64 prefix to downstream routers)
- Allocated prefix: 2600:1700:3d10:3a80::/60 from AT&T Fiber

**Unifi Security Gateway WAN**:
- IPv6 Connection: Disabled → DHCPv6
- Prefix Delegation Size: 64
- USG requests 2600:1700:3d10:3a8f::/64 from AT&T gateway

**Unifi Security Gateway LAN**:
- IPv6 Interface Type: Prefix Delegation
- IPv6 RA (Router Advertisement): Enabled (SLAAC for clients)
- DHCPv6/RDNSS DNS Control: Manual (empty DNS fields)

**Critical RDNSS Configuration**:
- RDNSS (Router Advertisement DNS Server) left empty
- Prevents USG from advertising itself as DNS server via IPv6 RA
- Clients get IPv6 addresses via SLAAC but use Pi-hole for DNS (advertised via DHCPv4)
- Preserves ad blocking for both IPv4 and IPv6 DNS queries

**Trade-offs**:
- More complex network configuration (dual-stack, prefix delegation, SLAAC)
- Mixed configuration (IPv6 addresses from SLAAC, DNS from DHCPv4)
- Not "pure" IPv6 autoconfiguration (DNS requires DHCPv4)
- But: 99% faster page loads (10,000ms → 97ms), future-proof, proper dual-stack networking

**Performance Impact**:
- Before: 10,000ms page loads (IPv6 timeout + IPv4 fallback)
- After: 97ms page loads (instant IPv6 connection)
- IPv6 actually faster than IPv4: 5ms vs 1100ms ping to Google
- Pi-hole handles both A (IPv4) and AAAA (IPv6) queries seamlessly

**SLAAC vs DHCPv6**:
- Used SLAAC (Stateless Address Autoconfiguration) instead of DHCPv6
- Why: Android devices don't support DHCPv6 for address assignment
- SLAAC is universal (all modern OSes support it)
- Simpler configuration (no DHCPv6 server needed)

---

### 25. Unbound Placement on Pi 5 (Not Pi 3 Worker)

**Decision**: Run Unbound on pi-k3s (Pi 5) instead of pi3-worker-1 (Pi 3)

**Why**:
- Pi 3 hardware insufficient for reliable DNS resolver operations
- Observed TCP connection failures to authoritative DNS servers on Pi 3
- DNS resolver is critical infrastructure requiring reliable hardware
- Pi 5 has significantly better CPU (Cortex-A76 vs A53) and networking capabilities

**Problem on Pi 3**:
- Frequent SERVFAIL errors in Unbound logs: "tcp connect: Network is unreachable"
- Upstream server timeouts during TCP connections
- DNS queries taking 500-10,000ms (should be <100ms)
- Pi 3's 1GB RAM, older ARM architecture, and network stack unable to handle recursive DNS load

**How**:
```yaml
# clusters/pi-k3s/pihole/unbound-deployment.yaml
spec:
  template:
    spec:
      nodeSelector:
        kubernetes.io/hostname: pi-k3s  # Changed from pi3-worker-1
```

**Performance Impact**:
- Before (Pi 3): 500-10,000ms for uncached queries, frequent TCP failures
- After (Pi 5): 21ms for fresh uncached queries, 0-15ms for cached, zero failures
- Improvement: 99% latency reduction, 100% reliability increase

**Trade-offs**:
- Adds ~64Mi memory usage to Pi 5 (already at 79% utilization)
- Both Pi-hole and Unbound on same node (no HA, shared failure domain)
- But: DNS reliability is non-negotiable, performance issues completely resolved

**Co-location Benefits**:
- Pi-hole and Unbound on same node eliminates network hop for DNS forwarding
- Cluster-internal DNS queries stay on-node (slight latency improvement)
- Simplified troubleshooting (both components on same hardware)

---

### 26. Homepage Placement on Pi 3 Workers

**Decision**: Use nodeAffinity to prefer Pi 3 workers for Homepage deployment

**Why**:
- Pi 5 at 79% memory utilization needs relief for critical services
- Homepage is lightweight (~111Mi) with no intensive operations
- Pi 3 workers suitable for stateless dashboards and web UIs
- Frees memory on Pi 5 for Unbound, Prometheus, Immich, and other resource-intensive services

**How**:
```yaml
# clusters/pi-k3s/homepage/deployment.yaml
spec:
  template:
    spec:
      affinity:
        nodeAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              preference:
                matchExpressions:
                  - key: kubernetes.io/hostname
                    operator: In
                    values:
                      - pi3-worker-1
                      - pi3-worker-2
```

**Why Preference, Not Requirement**:
- Allows fallback to Pi 5 if Pi 3 workers unavailable
- Better cluster resilience (not a hard constraint)
- Homepage is not mission-critical (can tolerate scheduling flexibility)

**Memory Impact**:
- Pi 5 freed: ~111Mi (79% → ~77% utilization)
- Pi 3 worker-2 usage: +111Mi (40% → 51% utilization)
- Net effect: Better distribution, Pi 5 still constrained

**Trade-offs**:
- Adds scheduling complexity (preference vs hard requirement)
- Homepage performance identical (not CPU/memory intensive)
- But: better resource utilization across heterogeneous cluster

---

### 27. Pi 3 Hardware Limitations

**Decision**: Recognize Pi 3 limitations and restrict workload types accordingly

**Why**:
- Pi 3 has 1GB RAM (vs 8GB on Pi 5)
- ARM Cortex-A53 architecture (older, slower than Pi 5's Cortex-A76)
- Network stack and CPU insufficient for reliable infrastructure services
- Observed failures: TCP connection failures in Unbound, performance degradation

**Suitable Workloads for Pi 3**:
- Stateless web applications (Homepage, dashboards)
- Lightweight proxies and services
- Simple HTTP servers (Next.js sites, static content)
- Services with <200Mi memory footprint

**Unsuitable Workloads for Pi 3**:
- DNS resolvers (Unbound - requires reliable TCP stack)
- Databases (PostgreSQL, Redis - need memory and I/O)
- Observability stack (Prometheus, Grafana - memory intensive)
- Media transcoding (Jellyfin - CPU intensive)
- Machine learning (Immich - CPU and memory intensive)

**Current Workload Distribution**:

**Pi 5 (pi-k3s) - Critical Infrastructure**:
- Pinned: Pi-hole primary (hostNetwork), Unbound (nodeSelector), Flux controllers, Backup jobs
- Heavy: Immich (1.4GB), Prometheus (800Mi), Grafana (695Mi), Jellyfin (466Mi)
- Memory: 6.3GB / 8GB (79%)

**Pi 5 (pi5-worker-1) - HA and Heavy Workloads**:
- Pinned: Pi-hole secondary (hostNetwork on 192.168.1.56)
- Heavy: Tailscale exit node, media services, distributed apps
- Memory: ~60-70% utilization

**Pi 5 (pi5-worker-2) - Heavy Workloads**:
- Heavy: Distributed applications, compute-intensive services
- Memory: ~50-60% utilization

**Pi 3 (pi3-worker-2) - Lightweight Services Only**:
- Preferred: Homepage (~111Mi), mtgibbs-site (~100Mi)
- Memory: ~500-600Mi / 1GB (50-60%)

**Trade-offs**:
- Pi 3 underutilized by design (can't handle heavy workloads safely)
- Heterogeneous cluster requires careful workload placement
- But: Pi 5 workers enable HA for DNS and better workload distribution

---

### 28. Unbound DNS Resilience Settings

**Decision**: Enable serve-expired cache and increase retry limits in Unbound configuration

**Why**:
- Users experienced 10+ second DNS delays on common sites (DuckDuckGo, Google, Reddit)
- Unbound logs showed frequent SERVFAIL errors: "upstream server timeout", "exceeded maximum sends"
- Home network has variable quality, authoritative DNS servers may be slow or unreliable
- Default Unbound settings optimized for reliable datacenter networks, too aggressive for residential use

**Implementation**:
Added 4 categories of resilience settings to `unbound-configmap.yaml`:

**1. Query Retry Settings**
```yaml
outbound-msg-retry: 5  # Retry queries 5 times before giving up (default: 3)
```

**2. Serve-Expired Cache Settings**
```yaml
serve-expired: yes  # Serve stale cache while refreshing in background
serve-expired-ttl: 86400  # Keep stale entries for 24 hours
serve-expired-client-timeout: 1800  # Wait max 30 minutes for fresh data
serve-expired-reply-ttl: 30  # Mark served-expired responses with 30s TTL
```

**3. TCP Fallback**
```yaml
tcp-upstream: yes  # Use TCP if UDP fails (more reliable but slower)
```

**4. Buffer Size Increases**
```yaml
outgoing-range: 8192  # Concurrent outbound ports (default: 4096)
num-queries-per-thread: 4096  # Query buffer per thread (default: 1024)
so-rcvbuf: 4m  # Socket receive buffer (default: 1m)
so-sndbuf: 4m  # Socket send buffer (default: 1m)
```

**How Serve-Expired Works**:
1. Client queries `google.com`
2. Unbound has stale cache entry (expired 5 minutes ago)
3. Unbound immediately returns stale entry (marked with TTL=30s)
4. Unbound fetches fresh data in background
5. Next query gets fresh data

**Trade-offs**:
- Clients may receive slightly outdated DNS records (max 24h old)
- DNS records rarely change, so serving stale data is acceptable
- 30s TTL on served-expired responses ensures client re-queries soon
- But: instant responses, no user-facing delays, dramatically improved user experience

**Performance Impact**:
- Before: 10-15 second delays on cache misses
- After: 0.1-0.5 seconds (cache hit), 0.5-2 seconds (cache miss with serve-expired)

---

### 29. Tailscale VPN with Subnet Routes for Mobile Ad Blocking

**Decision**: Deploy Tailscale Kubernetes Operator with exit node and subnet route advertising for Pi-hole IPs

**Why**:
- Enable mobile ad blocking when away from home network
- Avoid opening router ports (NAT traversal via Tailscale)
- Provide secure remote access to home network services
- Support both split tunnel (DNS only) and full tunnel (all traffic) modes

**Problem**:
- Mobile devices lose ad blocking when on cellular or public WiFi
- Traditional VPN requires port forwarding (security risk, dynamic IP issues)
- Pi-hole only accessible on local network (192.168.1.x)

**How**:

**1. Tailscale Operator Deployment**
- HelmRelease in `tailscale` namespace (chart version 1.92.5)
- OAuth authentication with minimal scopes (Devices Core + Auth Keys, `tag:k8s-operator` only)
- Credentials synced from 1Password via ExternalSecret

**2. Exit Node Configuration**
- Connector CRD with `exitNode: true` (hostname: `pi-cluster-exit`)
- ProxyClass with arm64 nodeSelector (ensures Pi 5 scheduling)
- Tagged with `tag:k8s-operator` for ACL policy matching

**3. Subnet Route Advertising (Critical)**
```yaml
subnetRouter:
  advertiseRoutes:
    - 192.168.1.55/32   # Pi-hole primary (pi-k3s)
    - 192.168.1.56/32   # Pi-hole secondary (pi5-worker-1)
```

**Why Subnet Routes**:
- Exit node provides tunnel, but doesn't automatically route to local IPs
- Subnet routes advertise specific IPs to Tailscale network mesh
- DNS queries to Pi-hole IPs are routed through tunnel

**4. Tailscale ACL Policy (Critical)**
```json
{
    "tagOwners": {
        "tag:k8s-operator": ["autogroup:admin", "autogroup:member"]
    },
    "autoApprovers": {
        "exitNode": ["tag:k8s-operator"],
        "routes": {
            "192.168.1.0/24": ["tag:k8s-operator"]
        }
    },
    "grants": [
        {"src": ["autogroup:member"], "dst": ["autogroup:internet"], "ip": ["*"]},
        {"src": ["autogroup:member"], "dst": ["192.168.1.0/24"], "ip": ["*"]}
    ]
}
```

**Three Required Components**:
1. Advertise routes in Connector resource (`subnetRouter.advertiseRoutes`)
2. Approve routes in Tailscale admin console
3. **Grant access in ACL policy** (often missed, causes DNS failures)

**5. Tailscale Admin DNS Settings**
- Global nameservers: 192.168.1.55, 192.168.1.56
- "Use with exit node" enabled (DNS applies when tunnel active)
- "Override local DNS" enabled (forces all DNS through Pi-hole)

**Implementation**:
```
clusters/pi-k3s/
├── tailscale/
│   ├── namespace.yaml
│   ├── external-secret.yaml       # OAuth credentials from 1Password
│   └── helmrelease.yaml           # Tailscale Operator v1.92.5
└── tailscale-config/
    ├── proxyclass.yaml            # arm64 nodeSelector for Pi 5
    └── connector.yaml             # Exit node + subnet routes
```

**Flux Dependency Chain**:
```
external-secrets → tailscale (needs OAuth secret) → tailscale-config (needs operator CRDs)
```

**Trade-offs**:
- More complex setup than simple VPN (OAuth, ACL policy, subnet routes)
- Requires Tailscale account (free tier supports 3 users, 100 devices)
- ACL policy management outside of git (currently manual in admin console)
- Subnet routes must be manually approved in admin console
- But: zero open ports, NAT traversal works anywhere, reliable WireGuard protocol

**Troubleshooting Gotchas**:
1. **OAuth "Requested tags are invalid"**: OAuth client has extra scopes/tags beyond `tag:k8s-operator`
   - Solution: Create new OAuth client with ONLY Devices Core + Auth Keys
2. **Exit node not visible in app**: Missing `autogroup:internet` grant in ACL
   - Solution: Add grant to ACL policy
3. **DNS not resolving**: Subnet routes advertised but ACL doesn't grant access
   - Solution: Add `{"src": ["autogroup:member"], "dst": ["192.168.1.0/24"], "ip": ["*"]}` grant
   - This was the critical missing piece in initial deployment

**Security**:
- Minimal OAuth scopes prevent privilege escalation
- ACL policy enforces explicit grants (default deny)
- Subnet routes are /32 (single IP), not /24 (entire subnet)
- Exit node pod runs as non-root with arm64-specific scheduling

**Performance**:
- Latency: +20-50ms (WireGuard overhead)
- Throughput: Limited by home network upload (AT&T Fiber: 20 Mbps typical)
- Battery impact: Minimal (WireGuard protocol is efficient)

**Use Cases**:
- **Split Tunnel** (exit node OFF): Only DNS queries to Pi-hole (ad blocking, normal internet speed)
- **Full Tunnel** (exit node ON): All traffic through home network (privacy + ad blocking, slower speed)

**Future Considerations**:
- Headscale (self-hosted control plane) if 3-user limit becomes issue
- Document ACL policy in git (currently only in Tailscale admin console)
- Grafana dashboard for Tailscale metrics (if available)

---

### 31. Cloudflare Tunnel for External Log Ingestion

**Decision**: Deploy Cloudflare Tunnel to enable external Heroku log drains without port forwarding

**Why**:
- Need to receive logs from external Heroku applications
- No public IP or port forwarding available/desirable
- Cloudflare Tunnel provides secure HTTPS ingress without exposing cluster directly

**How**:
- cloudflared deployment in `cloudflare-tunnel` namespace
- Token authentication from 1Password via ExternalSecret (`cloudflare-tunnel/tunnel-token`)
- Init container converts base64 token to credentials.json format
- ConfigMap defines ingress routes: `logs.mtgibbs.dev` → `vector.log-aggregation:8080`
- CNAME DNS record points to `.cfargotunnel.com` domain

**Implementation**:
```yaml
# Init container pattern
initContainers:
  - name: create-credentials
    image: alpine:latest
    command:
      - sh
      - -c
      - |
        apk add --no-cache jq
        TOKEN=$(cat /secrets/token)
        echo $TOKEN | base64 -d | jq '{
          AccountTag: .a,
          TunnelID: .t,
          TunnelSecret: .s
        }' > /credentials/credentials.json
```

**Trade-offs**:
- Adds dependency on Cloudflare service availability
- Tunnel token is long-lived (requires manual rotation)
- But: zero port forwarding, NAT traversal works anywhere, HTTPS encryption

**Troubleshooting**:
- DNS must point to `.cfargotunnel.com` (not cluster IP)
- Health probes use `/ready` endpoint on port 2000 (metrics)
- Tunnel ID required in run command for GitOps-managed tunnels

---

### 32. Log Aggregation with Loki and Vector

**Decision**: Deploy Loki + Vector stack for Heroku application log aggregation

**Why**:
- Centralized log visibility for external applications
- Correlation between application logs and cluster metrics in Grafana
- Long-term log retention for troubleshooting (7 days)
- Structured log querying with LogQL

**How**:

**Loki**:
- Single-binary deployment mode (not microservices)
- Filesystem storage on local-path PVC (10Gi on pi5-worker-2)
- 7-day retention, no caching (resource constraints)
- Exposed as Grafana datasource

**Vector**:
- HTTP endpoint on port 8080 receives Heroku log drain POSTs
- VRL (Vector Remap Language) transforms parse syslog format
- Extracts structured data: app name, dyno type, log level
- Labels logs for Loki filtering
- Console sink enabled for debugging

**Implementation**:
```
Heroku App
    │ HTTPS POST
    ▼
logs.mtgibbs.dev (Cloudflare Tunnel)
    │ HTTP (internal)
    ▼
Vector (VRL transform)
    │ Parse & label
    ▼
Loki (filesystem storage)
    │ LogQL queries
    ▼
Grafana Dashboard
```

**VRL Transform Example**:
```yaml
transforms:
  parse_heroku:
    type: remap
    source: |
      .source = "heroku"
      .level = if contains(string!(.message), "error") { "error" } else { "info" }
      parsed = parse_regex(.message, r'^(?P<timestamp>...) (?P<app>\S+) (?P<dyno>\S+) - (?P<content>.*)$') ?? {}
      .app = parsed.app ?? "unknown"
      .dyno = parsed.dyno ?? "unknown"
```

**Trade-offs**:
- Single-binary Loki has no horizontal scaling
- Filesystem storage limits retention capacity
- No replication (data loss if node fails)
- But: minimal resource overhead, sufficient for learning cluster

**Resource Requirements**:
- cloudflared: 10m CPU / 64Mi memory
- Vector: 50m CPU / 128Mi memory
- Loki: 100m CPU / 256Mi memory / 10Gi storage
- Total: ~160m CPU, ~448Mi memory, 10Gi storage

**Monitoring**:
- Uptime Kuma monitors: Loki HTTP, Vector TCP, Log Drain endpoint
- Homepage dashboard shows Loki status
- Discord alerts on failures

---

### 30. Pi-hole High Availability with Secondary Instance

**Decision**: Deploy secondary Pi-hole instance on pi5-worker-1 (192.168.1.56)

**Why**:
- Primary Pi-hole restarts cause brief DNS outages for all clients
- Router DHCP can advertise multiple DNS servers for failover
- Mobile devices and clients benefit from redundant DNS resolution
- Hardware expansion (additional Pi 5 workers) makes HA feasible
- Learning opportunity for HA DNS architecture

**Problem**:
- Single Pi-hole on pi-k3s means DNS downtime during:
  - K3s upgrades
  - Pi-hole configuration changes
  - Pod restarts (scheduled or crash)
  - Node maintenance
- Clients with secondary public DNS (1.1.1.1) would bypass ad blocking

**How**:

**1. Secondary Pi-hole Deployment**
- Full Pi-hole deployment on pi5-worker-1
- hostNetwork: true with different node selector
- Separate PVCs (pihole-etc, pihole-dnsmasq) on worker node
- Shared configuration via ConfigMap (same adlists)
- Same password from 1Password (shared ExternalSecret)

**2. Router DHCP Configuration**
- Primary DNS: 192.168.1.55 (pi-k3s)
- Secondary DNS: 192.168.1.56 (pi5-worker-1)
- Clients try primary first, failover to secondary

**3. Unbound Configuration**
- Single Unbound instance on pi-k3s (shared by both Pi-holes)
- Both Pi-hole instances forward to unbound.pihole.svc.cluster.local:5335
- Unbound has DNS resilience settings (serve-expired, TCP fallback)

**4. Monitoring**
- Uptime Kuma monitors both Pi-hole instances:
  - DNS resolution test for each IP
  - Admin UI health check for each instance
- Homepage dashboard shows stats from both instances

**Implementation**:
```
clusters/pi-k3s/pihole/
├── pihole-deployment.yaml       # Primary (pi-k3s)
├── pihole-ha-deployment.yaml    # Secondary (pi5-worker-1)
├── pihole-ha-pvc.yaml           # Separate PVCs for secondary
├── pihole-adlists-configmap.yaml # Shared adlists
└── external-secret.yaml         # Shared password
```

**Trade-offs**:
- Doubles resource usage for Pi-hole (~256Mi memory × 2)
- Two instances to maintain (upgrades, config changes)
- Not true HA (no shared state, separate PVCs)
- Clients still experience brief delay during primary failover
- But: significantly improves DNS availability, no single point of failure

**Failover Behavior**:
- Primary (192.168.1.55) down → Clients failover to secondary (192.168.1.56) in ~1-5 seconds
- Both instances have same blocklists and configuration
- Both instances forward to same Unbound resolver
- Query logs and statistics are separate (not synchronized)

**Unbound as Shared Backend**:
- Unbound remains single instance (not HA yet)
- If Unbound down, both Pi-holes fail (shared dependency)
- Future enhancement: Unbound HA with multiple resolvers

## Observability Stack

```
┌────────────────────────────────────────────────────────────────────────────┐
│                     Monitoring + Alerting Flow                             │
│                                                                            │
│  ┌──────────────┐     scrapes      ┌────────────────────────────┐         │
│  │ pihole-      │ ◄──────────────  │      Prometheus            │         │
│  │ exporter     │    /metrics      │                            │         │
│  │ :9617        │    (30s)         │ • Stores metrics           │         │
│  └──────────────┘                  │ • Evaluates rules          │         │
│                                    │ • Fires alerts             │         │
│  ┌──────────────┐     scrapes      │                            │         │
│  │ immich-      │ ◄──────────────  │ ServiceMonitors:           │         │
│  │ metrics      │    /metrics      │ • pihole-exporter          │         │
│  │ :8081, :8082 │    (30s)         │ • immich-metrics           │         │
│  └──────────────┘                  │ • node-exporter            │         │
│                                    └──────┬───────────┬─────────┘         │
│  ┌──────────────┐     scrapes            │           │                   │
│  │ node-        │ ◄──────────────────────┘           │                   │
│  │ exporter     │    /metrics                        │ Alert events      │
│  │ :9100        │                                    ▼                   │
│  └──────────────┘                         ┌────────────────────────────┐  │
│                                           │     Alertmanager           │  │
│       PromQL queries                      │                            │  │
│            │                              │ • Routes alerts            │  │
│            ▼                              │ • Groups notifications     │  │
│   ┌──────────────┐                       │ • Silences (Watchdog,      │  │
│   │   Grafana    │                       │   KubeMemoryOvercommit)    │  │
│   │              │                       │                            │  │
│   │ • Dashboards │                       │ Discord receiver:          │  │
│   │ • Alerts     │                       │ • Webhook from 1Password   │  │
│   │ • :3000      │                       │ • 5min group interval      │  │
│   └──────────────┘                       └──────────┬─────────────────┘  │
│                                                     │                    │
│                                                     │ HTTP POST          │
│                                                     ▼                    │
│                                          ┌────────────────────────────┐  │
│                                          │   Discord Channel          │  │
│                                          │                            │  │
│                                          │ • Real-time notifications  │  │
│                                          │ • Alert + recovery msgs    │  │
│                                          └────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────┘
```

### Available Metrics and Alerts

**Pi-hole Metrics** (via pihole-exporter):
- `pihole_domains_being_blocked` - Total blocklist size
- `pihole_dns_queries_today` - Query count
- `pihole_ads_blocked_today` - Blocked count
- `pihole_ads_percentage_today` - Block rate %
- `pihole_unique_domains` - Unique domains queried
- `pihole_queries_forwarded` - Queries sent to Unbound
- `pihole_queries_cached` - Cache hit count

**Immich Metrics** (via native Prometheus endpoint):
- `immich_server_thumbnail_queue_size` - Photos waiting for thumbnail generation
- `immich_server_video_conversion_queue_size` - Videos waiting for transcoding
- `immich_server_metadata_extraction_queue_size` - Files waiting for metadata extraction
- `immich_server_processing_duration_seconds` - Time spent processing jobs

**Immich Alerts** (PrometheusRule):
| Alert | Condition | Duration | Severity |
|-------|-----------|----------|----------|
| ImmichServerDown | Service unreachable | 1 minute | warning |
| ImmichThumbnailQueueStuck | Queue > 500 | 30 minutes | warning |
| ImmichVideoQueueStuck | Queue > 50 | 30 minutes | warning |
| ImmichMetadataQueueStuck | Queue > 100 | 30 minutes | warning |
| ImmichNoThumbnailActivity | No processing | 6 hours | warning |
| ImmichDatabaseSlowQueries | Query > 5s | 5 minutes | warning |

**Alerting Pipeline**:
1. Prometheus evaluates PrometheusRules every 30 seconds
2. Firing alerts sent to Alertmanager
3. Alertmanager routes to Discord receiver (5-minute group interval)
4. Discord webhook sends formatted message to channel
5. Resolved alerts also sent to Discord

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
        ├── flux-system/             # Flux GitOps controllers
        │   ├── infrastructure.yaml  # Kustomizations with dependencies
        │   └── ...
        ├── external-secrets/        # ESO operator (HelmRelease)
        ├── external-secrets-config/ # ClusterSecretStore for 1Password
        ├── ingress/                 # nginx-ingress (HelmRelease)
        ├── cert-manager/            # cert-manager (HelmRelease)
        ├── cert-manager-config/     # ClusterIssuers (Let's Encrypt) + Cloudflare secret
        ├── pihole/
        │   ├── unbound-*.yaml       # Unbound DNS config + deployment
        │   ├── pihole-*.yaml        # Pi-hole deployment, PVC, service
        │   ├── pihole-exporter.yaml # Prometheus exporter
        │   └── external-secret.yaml # Password from 1Password
        ├── monitoring/
        │   ├── kustomization.yaml
        │   ├── helmrelease.yaml     # kube-prometheus-stack (Alertmanager enabled)
        │   ├── ingress.yaml         # Grafana Ingress
        │   └── external-secret.yaml # Grafana password + Discord webhook from 1Password
        ├── uptime-kuma/
        │   ├── deployment.yaml           # Uptime Kuma v2
        │   ├── pvc.yaml                  # Persistent storage
        │   ├── ingress.yaml              # status.lab.mtgibbs.dev
        │   ├── external-secret.yaml      # Uptime Kuma password from 1Password
        │   ├── autokuma-deployment.yaml  # AutoKuma for GitOps monitors
        │   ├── autokuma-pvc.yaml         # AutoKuma persistent storage for sled DB
        │   └── autokuma-monitors.yaml    # ConfigMap with monitor definitions
        ├── homepage/
        │   ├── namespace.yaml            # homepage namespace
        │   ├── deployment.yaml           # Homepage dashboard with initContainer
        │   ├── service.yaml              # ClusterIP service
        │   ├── serviceaccount.yaml       # RBAC for Kubernetes widget (node metrics)
        │   ├── ingress.yaml              # home.lab.mtgibbs.dev with TLS
        │   ├── configmap.yaml            # Dashboard configuration (settings, services, widgets)
        │   └── kustomization.yaml
        ├── jellyfin/
        │   ├── namespace.yaml            # jellyfin namespace
        │   ├── pv.yaml                   # NFS PV to Synology NAS (/volume1/video)
        │   ├── pvc.yaml                  # PersistentVolumeClaim for media
        │   ├── deployment.yaml           # Jellyfin media server
        │   ├── service.yaml              # ClusterIP service
        │   ├── ingress.yaml              # jellyfin.lab.mtgibbs.dev
        │   └── kustomization.yaml
        ├── immich/
        │   ├── namespace.yaml            # immich namespace
        │   ├── helmrelease.yaml          # Immich Helm chart v0.10.3 (telemetry enabled)
        │   ├── pv.yaml                   # NFS PV to Synology NAS for photos
        │   ├── servicemonitor.yaml       # Prometheus scraping config
        │   ├── prometheusrule.yaml       # Alert definitions (6 alerts)
        │   ├── external-secret.yaml      # Database password from 1Password
        │   └── kustomization.yaml
        ├── flux-notifications/
        │   ├── namespace.yaml            # flux-notifications namespace
        │   ├── discord-provider.yaml     # Discord webhook provider
        │   ├── discord-alert.yaml        # Alert for Flux events
        │   ├── external-secret.yaml      # Discord webhook URL from 1Password
        │   └── kustomization.yaml
        ├── backup-jobs/
        │   ├── kustomization.yaml
        │   ├── immich-backup.yaml        # Nightly PVC backup to Synology (2:00 AM Sundays)
        │   ├── postgres-backup-cronjob.yaml  # PostgreSQL backup (2:30 AM Sundays)
        │   └── postgres-backup-secret.yaml   # ExternalSecret for DB password
        ├── external-services/
        │   ├── namespace.yaml            # external-services namespace
        │   ├── unifi.yaml                # Unifi Controller reverse proxy
        │   ├── synology.yaml             # Synology NAS reverse proxy
        │   └── kustomization.yaml
        ├── mtgibbs-site/
        │   ├── namespace.yaml            # mtgibbs-site namespace
        │   ├── deployment.yaml           # Next.js app with image automation marker
        │   ├── service.yaml              # ClusterIP service
        │   ├── ingress.yaml              # site.lab.mtgibbs.dev with TLS
        │   ├── image-automation.yaml     # ImageRepository + ImagePolicy + ImageUpdateAutomation
        │   └── kustomization.yaml
        ├── cloudflare-tunnel/
        │   ├── namespace.yaml            # cloudflare-tunnel namespace
        │   ├── deployment.yaml           # cloudflared with init container for credentials
        │   ├── service.yaml              # ClusterIP service for tunnel
        │   ├── configmap.yaml            # Tunnel config with ingress routes
        │   ├── external-secret.yaml      # Tunnel token from 1Password
        │   └── kustomization.yaml
        └── log-aggregation/
            ├── namespace.yaml            # log-aggregation namespace
            ├── loki-helmrelease.yaml     # Loki Helm chart (single-binary mode)
            ├── vector-deployment.yaml    # Vector log processor
            ├── vector-configmap.yaml     # Vector pipeline config (VRL transforms)
            ├── vector-service.yaml       # ClusterIP service for log ingestion
            └── kustomization.yaml
```

## Network Details

### Home Network Configuration (Dual-Stack IPv4/IPv6)

The cluster operates on a dual-stack network with both IPv4 and IPv6 connectivity:

#### Network Topology
```
AT&T Gateway (192.168.0.254)
  IPv4: 192.168.0.0/24 DHCP server
  IPv6: 2600:1700:3d10:3a80::/60 (from AT&T Fiber)
        DHCPv6-PD: Enabled (delegates /64 to downstream routers)
    │
    │ DHCPv6-PD: Requests /64 prefix
    ▼
Unifi Security Gateway (192.168.1.1)
  WAN: 192.168.0.133 (IPv4), DHCPv6 client
  LAN IPv4: 192.168.1.0/24 DHCP server
  LAN IPv6: 2600:1700:3d10:3a8f::/64 (from Prefix Delegation)
            Router Advertisement (RA): Enabled (SLAAC)
            RDNSS: Empty (DNS advertised via DHCPv4 only)
    │
    │ SLAAC (IPv6) + DHCPv4 (IPv4 + DNS)
    ▼
LAN Clients (Dual-Stack)
  IPv4: 192.168.1.x/24 (from DHCP)
  IPv6: 2600:1700:3d10:3a8f::/64 (auto-configured via SLAAC)
  DNS: 192.168.1.55 (Pi-hole, from DHCPv4)
```

#### IPv6 Configuration Details

**AT&T Gateway (192.168.0.254)**
- IPv6: Enabled
- DHCPv6: Enabled
- DHCPv6 Prefix Delegation: Enabled
- Allocated prefix: 2600:1700:3d10:3a80::/60 (from AT&T Fiber)
- Delegates /64 subnets to downstream routers

**Unifi Security Gateway WAN Settings**
- IPv6 Connection: DHCPv6
- Prefix Delegation Size: 64
- Requests 2600:1700:3d10:3a8f::/64 from AT&T gateway

**Unifi Security Gateway LAN Settings**
- IPv6 Interface Type: Prefix Delegation
- IPv6 RA (Router Advertisement): Enabled
- SLAAC: Enabled for client auto-configuration
- DHCPv6/RDNSS DNS Control: Manual (empty)
  - **Critical**: Empty RDNSS prevents USG from advertising itself as DNS
  - Clients use Pi-hole (192.168.1.55) advertised via DHCPv4 option 6
  - Preserves ad blocking for both IPv4 and IPv6 DNS queries

**Why Dual-Stack Matters**
- Modern browsers use "Happy Eyeballs" (RFC 8305): try IPv6 first, fallback to IPv4
- Without proper IPv6 routing, clients wait ~10s for IPv6 timeout before fallback
- Dual-stack eliminates timeout delays (99% faster page loads: 10,000ms → 97ms)
- IPv6 often has better routing (5ms vs 1100ms to Google in this network)

**Pi-hole Dual-Stack DNS**
- Listens on 0.0.0.0:53 (all IPv4 interfaces)
- Handles both A (IPv4) and AAAA (IPv6) DNS queries
- Blocks ads for both protocols:
  - A records: Returns 0.0.0.0 for blocked domains
  - AAAA records: Returns ::1 for blocked domains

### Service Ports

| Component | Port | Protocol | Exposure |
|-----------|------|----------|----------|
| Pi-hole DNS | 53 | UDP/TCP | hostNetwork (192.168.1.55:53) |
| Pi-hole Web | 80 | TCP | hostNetwork (192.168.1.55:80) AND Ingress (pihole.lab.mtgibbs.dev) |
| Unbound | 5335 | UDP/TCP | ClusterIP (internal only) |
| pihole-exporter | 9617 | TCP | ClusterIP (Prometheus scrapes) |
| nginx-ingress | 443 | TCP | hostPort (192.168.1.55:443) |
| Grafana | 3000 | TCP | Ingress (grafana.lab.mtgibbs.dev) |
| Uptime Kuma | 3001 | TCP | Ingress (status.lab.mtgibbs.dev) |
| Homepage | 3000 | TCP | Ingress (home.lab.mtgibbs.dev) |
| Prometheus | 9090 | TCP | ClusterIP (port-forward to access) |
| Alertmanager | 9093 | TCP | ClusterIP (port-forward to access) |
| Jellyfin | 8096 | TCP | Ingress (jellyfin.lab.mtgibbs.dev) |
| Immich | 3001 | TCP | Ingress (immich.lab.mtgibbs.dev) |
| Immich Metrics (server) | 8081 | TCP | ClusterIP (Prometheus scrapes) |
| Immich Metrics (microservices) | 8082 | TCP | ClusterIP (Prometheus scrapes) |
| Immich PostgreSQL | 5432 | TCP | ClusterIP (internal only, backup job access) |
| Unifi Controller | 8443 | HTTPS | External (192.168.1.30) → Ingress (unifi.lab.mtgibbs.dev) |
| Synology NAS | 5000 | HTTP | External (192.168.1.60) → Ingress (nas.lab.mtgibbs.dev) |
| mtgibbs.xyz Site | 3000 | TCP | Ingress (site.lab.mtgibbs.dev) |
| Flux ImageRepository | N/A | N/A | Scans GHCR every 5 minutes |
| Flux ImageUpdateAutomation | N/A | N/A | Git push to main branch |
| cloudflared (Tunnel) | 2000 | TCP | Metrics endpoint for health probes |
| Vector (Log Processor) | 8080 | TCP | HTTP log ingestion endpoint |
| Vector API | 8686 | TCP | ClusterIP (health checks) |
| Loki | 3100 | TCP | ClusterIP (log storage API) |
| Log Drain Endpoint | 443 | HTTPS | External (logs.mtgibbs.dev via Cloudflare Tunnel) |

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

# Test DNS resolution (from Mac)
# dig @192.168.1.55 google.com

# Access web UIs (via Ingress with Let's Encrypt certs)
# Homepage:       https://home.lab.mtgibbs.dev
# Grafana:        https://grafana.lab.mtgibbs.dev
# Uptime Kuma:    https://status.lab.mtgibbs.dev
# Pi-hole:        https://pihole.lab.mtgibbs.dev (or http://192.168.1.55/admin/)
# Jellyfin:       https://jellyfin.lab.mtgibbs.dev
# Immich:         https://immich.lab.mtgibbs.dev
# Unifi:          https://unifi.lab.mtgibbs.dev
# NAS:            https://nas.lab.mtgibbs.dev
# Personal Site:  https://site.lab.mtgibbs.dev (auto-deployed from GHCR)

# Flux commands
flux get all                              # Check all Flux resources
flux reconcile source git flux-system     # Force git sync
flux reconcile kustomization monitoring   # Reconcile specific kustomization

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
- [x] **Ingress + TLS**: nginx-ingress + cert-manager for HTTPS
- [x] **Uptime Kuma**: Status page for home services monitoring
- [x] **GitOps monitor setup**: AutoKuma manages monitors declaratively via ConfigMap
- [x] **Homepage dashboard**: Unified landing page for all services
- [x] **Multi-node**: 3-node cluster (Pi 5 + 2x Pi 3 workers)
- [x] **Media services**: Jellyfin media server with NFS storage
- [x] **Photo management**: Immich v2 for self-hosted photo backup
- [x] **Deployment notifications**: Discord webhook integration via Flux
- [x] **Cluster visibility**: Homepage Kubernetes widget with node metrics
- [x] **Flux Image Automation**: Auto-deploy personal website on image push to GHCR
- [x] **Personal website deployment**: mtgibbs.xyz site with auto-deploy workflow
- [x] **Pi-hole high availability**: Secondary Pi-hole on pi5-worker-1 for DNS redundancy
- [x] **Tailscale VPN**: Exit node with subnet routes for mobile ad blocking
- [x] **Hardware expansion**: 4-node cluster with 3x Pi 5 and 1x Pi 3
- [x] **Modular knowledge base**: 11 specialized skills for AI-assisted operations
- [x] **Log aggregation**: Loki + Vector + Cloudflare Tunnel for Heroku log drains
- [ ] **Unbound HA**: Secondary Unbound instance for complete DNS redundancy
- [ ] **Shared storage**: Migrate remaining workloads from local-path to NFS
- [ ] **Resource quotas**: Namespace-level resource limits
- [ ] **Network policies**: Pod-to-pod traffic control
- [ ] **Horizontal Pod Autoscaling**: Auto-scale workloads based on metrics
- [ ] **Progressive delivery**: Flagger for canary/blue-green deployments
- [ ] **Tailscale ACL automation**: GitOps-managed ACL policy (currently manual)
