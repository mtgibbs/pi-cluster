# Pi-K3s Cluster Architecture

## Overview

A 3-node Kubernetes learning cluster running on Raspberry Pi hardware, providing network-wide ad blocking via Pi-hole with privacy-focused recursive DNS resolution via Unbound, plus self-hosted media services and comprehensive monitoring.

## Hardware

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                           K3s Cluster (3 nodes)                               │
├───────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌──────────────────────────┐  ┌──────────────────────┐  ┌─────────────────┐│
│  │  pi-k3s (Master+Worker)  │  │  pi3-worker-1        │  │  pi3-worker-2   ││
│  │  192.168.1.55            │  │  192.168.1.53        │  │  192.168.1.51   ││
│  ├──────────────────────────┤  ├──────────────────────┤  ├─────────────────┤│
│  │ Raspberry Pi 5           │  │ Raspberry Pi 3       │  │ Raspberry Pi 3  ││
│  │ ARM Cortex-A76 (4 cores) │  │ ARM Cortex-A53       │  │ ARM Cortex-A53  ││
│  │ RAM: 8GB                 │  │ RAM: 1GB             │  │ RAM: 1GB        ││
│  │ Pi OS Lite 64-bit        │  │ Pi OS Lite 64-bit    │  │ Pi OS Lite 64   ││
│  │                          │  │                      │  │                 ││
│  │ Workloads:               │  │ Workloads:           │  │ Workloads:      ││
│  │ • Pi-hole (hostNetwork)  │  │ • Unbound DNS        │  │ • Most services ││
│  │ • Flux controllers       │  │   (nodeSelector)     │  │   schedule here ││
│  │ • Backup jobs            │  │                      │  │   or on pi-k3s  ││
│  │ • Most workloads         │  │                      │  │                 ││
│  └──────────────────────────┘  └──────────────────────┘  └─────────────────┘│
│                                                                               │
│  K3s Version: v1.33.6+k3s1                                                   │
│  • Traefik disabled (--disable=traefik)                                      │
│  • local-path storage provisioner (hostPath on pi-k3s)                       │
│  • ServiceLB for LoadBalancer services                                       │
└───────────────────────────────────────────────────────────────────────────────┘
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
│  │  • Prometheus     - metrics collection                           │  │
│  │  • Grafana        - dashboards & visualization                   │  │
│  │  • Alertmanager   - alert routing                                │  │
│  │  • Node Exporter  - host metrics                                 │  │
│  │                                                                   │  │
│  │  Grafana Ingress: grafana.lab.mtgibbs.dev                       │  │
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
│  │  • Monitors: Pi-hole DNS, Admin, Grafana, Prometheus, Unbound,  │  │
│  │    K3s API, Uptime Kuma, Homepage (8 total)                      │  │
│  │                                                                   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                      homepage namespace                           │  │
│  │                                                                   │  │
│  │  Homepage (gethomepage/homepage)                                 │  │
│  │  • Unified dashboard for all cluster services                    │  │
│  │  • Dark theme with system resource widgets                       │  │
│  │  • Live service widgets (Pi-hole, Immich, Jellyfin, Prometheus) │  │
│  │  • Kubernetes widget with node metrics                           │  │
│  │  • GitOps-managed configuration via ConfigMap                    │  │
│  │  • initContainer copies config to writable emptyDir              │  │
│  │  • RBAC: ServiceAccount with ClusterRole for API access          │  │
│  │  • Secrets: 4 ExternalSecrets for widget API keys                │  │
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
- Transfers compressed dump to Synology NAS via SCP
- DB password synced from 1Password via ExternalSecret
- Pinned to pi-k3s node (same as PVC backup for consistency)

**Backup Strategy**:
- PVC backup: Full filesystem snapshot (photos, config, data directory)
- PostgreSQL backup: Database logical backup (metadata, schema, indexes)
- Together: Complete disaster recovery capability

**Trade-offs**:
- Duplicates some data (database files exist in both backups)
- Additional backup window (30 minutes offset)
- More complex restore procedure (requires both backup types)
- But: provides defense-in-depth and flexible recovery options

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
        │   ├── helmrelease.yaml     # kube-prometheus-stack
        │   ├── ingress.yaml         # Grafana Ingress
        │   └── external-secret.yaml # Grafana password from 1Password
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
        │   ├── helmrelease.yaml          # Immich Helm chart v0.10.3 (app v2.4.1)
        │   ├── pv.yaml                   # NFS PV to Synology NAS for photos
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
        └── external-services/
            ├── namespace.yaml            # external-services namespace
            ├── unifi.yaml                # Unifi Controller reverse proxy
            ├── synology.yaml             # Synology NAS reverse proxy
            └── kustomization.yaml
```

## Network Details

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
| Jellyfin | 8096 | TCP | Ingress (jellyfin.lab.mtgibbs.dev) |
| Immich | 3001 | TCP | Ingress (immich.lab.mtgibbs.dev) |
| Immich PostgreSQL | 5432 | TCP | ClusterIP (internal only, backup job access) |
| Unifi Controller | 8443 | HTTPS | External (192.168.1.30) → Ingress (unifi.lab.mtgibbs.dev) |
| Synology NAS | 5000 | HTTP | External (192.168.1.60) → Ingress (nas.lab.mtgibbs.dev) |

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
# Homepage:    https://home.lab.mtgibbs.dev
# Grafana:     https://grafana.lab.mtgibbs.dev
# Uptime Kuma: https://status.lab.mtgibbs.dev
# Pi-hole:     https://pihole.lab.mtgibbs.dev (or http://192.168.1.55/admin/)
# Jellyfin:    https://jellyfin.lab.mtgibbs.dev
# Immich:      https://immich.lab.mtgibbs.dev
# Unifi:       https://unifi.lab.mtgibbs.dev
# NAS:         https://nas.lab.mtgibbs.dev

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
- [ ] **High availability**: Pi-hole failover/redundancy
- [ ] **Shared storage**: Migrate from local-path to NFS for multi-node PVC access
- [ ] **Resource quotas**: Namespace-level resource limits
- [ ] **Network policies**: Pod-to-pod traffic control
- [ ] **Horizontal Pod Autoscaling**: Auto-scale workloads based on metrics
