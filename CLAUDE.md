# Pi K3s Cluster Project

## Project Goal

Build a learning Kubernetes cluster on a Raspberry Pi 5 to run Pi-hole + Unbound, with observability (Grafana/Prometheus), using proper IaC practices. Managed via GitOps (Flux) with secrets from 1Password.

## Current State

### Hardware & OS

**Master Node:**
- Raspberry Pi 5 (8GB RAM)
- Raspberry Pi OS Lite (64-bit)
- Hostname: `pi-k3s`
- Static IP: 192.168.1.55 (DHCP reservation)
- User: `mtgibbs`

**Worker Nodes:**
- Raspberry Pi 3 (1GB RAM) - `pi3-worker-1` (192.168.1.53)
- Raspberry Pi 3 (1GB RAM) - `pi3-worker-2` (192.168.1.51)
- Both running Raspberry Pi OS Lite (64-bit)
- SSH keys and K3s node token stored in 1Password
- Setup documented in `docs/pi-worker-setup.md`

### Completed Setup
1. **cgroups enabled** - Added `cgroup_memory=1 cgroup_enable=memory` to `/boot/firmware/cmdline.txt`
2. **Swap disabled** - Masked `systemd-zram-setup@zram0.service`
3. **k3s installed** - Version v1.33.6+k3s1, installed with `--disable=traefik`
4. **Flux GitOps** - Bootstrapped to GitHub repo, manages all workloads
5. **External Secrets Operator** - v1.2.0, syncs secrets from 1Password
6. **Pi-hole + Unbound** - Deployed via Flux with GitOps-managed secrets
7. **nginx-ingress** - Ingress controller with hostPort 443 (port 80 used by Pi-hole)
8. **cert-manager** - Let's Encrypt certificates via Cloudflare DNS-01 challenge
9. **Uptime Kuma** - Status page for home services monitoring
10. **AutoKuma** - GitOps-managed monitors for Uptime Kuma (with persistent storage)
11. **Homepage** - Unified dashboard for all cluster services with Kubernetes widget
12. **External Service Proxies** - Reverse proxies for Unifi, Synology with TLS
13. **Jellyfin** - Self-hosted media server with NFS storage from Synology NAS
14. **Immich** - Self-hosted photo backup and management (upgraded to v2.4.1)
15. **Discord Notifications** - Flux deployment notifications via Discord webhook
16. **Multi-node cluster** - Two Pi 3 worker nodes for workload distribution

### Checklist
- [x] Unbound deployment (recursive DNS resolver)
- [x] Pi-hole deployment with hostNetwork
- [x] Flux GitOps setup
- [x] 1Password + ESO secrets management
- [x] Observability stack (Prometheus, Grafana) - via kube-prometheus-stack
- [x] DNS resilience during upgrades (Pi uses static DNS: 1.1.1.1/8.8.8.8)
- [x] Pi-hole v6 API configuration (password, upstream DNS, adlists)
- [x] GitOps-managed adlists (Firebog curated, ~900k domains)
- [x] Ingress + TLS for web UIs (nginx-ingress + cert-manager)
- [x] Uptime Kuma status page (subdomain-based routing)
- [x] Let's Encrypt certificates via Cloudflare DNS-01 challenge
- [x] AutoKuma for GitOps-managed monitors
- [x] Pi-hole ingress (pihole.lab.mtgibbs.dev)
- [x] Jellyfin media server with NFS storage
- [x] Immich photo backup (upgraded to v2.4.1)
- [x] Discord deployment notifications
- [x] Multi-node cluster (Pi 5 master + 2x Pi 3 workers)
- [x] Workload distribution across nodes

### Service URLs
All services use subdomain-based routing via `*.lab.mtgibbs.dev`:

**Cluster Services:**
- **Homepage**: https://home.lab.mtgibbs.dev (unified dashboard with node stats)
- **Grafana**: https://grafana.lab.mtgibbs.dev
- **Uptime Kuma**: https://status.lab.mtgibbs.dev
- **Pi-hole Admin**: https://pihole.lab.mtgibbs.dev (also available via hostNetwork: http://192.168.1.55/admin/)
- **Jellyfin**: https://jellyfin.lab.mtgibbs.dev (media server)
- **Immich**: https://immich.lab.mtgibbs.dev (photo backup)

**External Services (Reverse Proxies):**
- **Unifi Controller**: https://unifi.lab.mtgibbs.dev (192.168.1.30:8443)
- **Synology NAS**: https://nas.lab.mtgibbs.dev (192.168.1.60:5000)

## Architecture

### GitOps Flow
```
┌──────────────┐     push      ┌──────────────┐     sync      ┌──────────────┐
│   Developer  │ ───────────── │    GitHub    │ ──────────────│    Flux      │
│   (Mac)      │               │  pi-cluster  │               │  (in cluster)│
└──────────────┘               └──────────────┘               └──────┬───────┘
                                                                     │
                               ┌─────────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        K3s Cluster (3 nodes)                                │
│                                                                             │
│  ┌────────────────┐   ┌─────────────────┐   ┌─────────────────┐            │
│  │  pi-k3s (Pi 5) │   │ pi3-worker-1    │   │ pi3-worker-2    │            │
│  │  192.168.1.55  │   │ 192.168.1.53    │   │ 192.168.1.51    │            │
│  │  (master+work) │   │ (worker, 1GB)   │   │ (worker, 1GB)   │            │
│  │                │   │                 │   │                 │            │
│  │ • Pi-hole      │   │ • Unbound       │   │ • Homepage      │            │
│  │ • Flux         │   │                 │   │                 │            │
│  │ • Backups      │   │                 │   │                 │            │
│  └────────────────┘   └─────────────────┘   └─────────────────┘            │
│                                                                             │
│  ┌─────────────────┐    ┌──────────────────┐    ┌─────────────────────┐   │
│  │ External Secrets│────│ 1Password Cloud  │    │ ClusterSecretStore  │   │
│  │ Operator        │    │ (pi-cluster vault)│◄───│ (onepassword)       │   │
│  └────────┬────────┘    └──────────────────┘    └─────────────────────┘   │
│           │                                                                 │
│           ▼ creates                                                        │
│  ┌─────────────────┐                                                       │
│  │ K8s Secrets     │───────────────────────────────────────────┐           │
│  │ (pihole-secret) │                                           │           │
│  └─────────────────┘                                           │           │
│                                                                 ▼           │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         pihole namespace                            │   │
│  │  ┌──────────┐     ┌──────────┐     ┌─────────────────┐             │   │
│  │  │ Pi-hole  │────▶│ Unbound  │────▶│ Root DNS Servers│             │   │
│  │  │ (ads)    │     │ (recursive)    │ (Internet)      │             │   │
│  │  │ (pi-k3s) │     │(pi3-worker-1)  │ (Internet)      │             │   │
│  │  └──────────┘     └──────────┘     └─────────────────┘             │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### DNS Flow
```
User Device → Pi-hole (ad filtering) → Unbound (recursive DNS) → Root/TLD/Authoritative servers
```

**Why Unbound?** Full recursive resolution directly to authoritative DNS servers. Better privacy (no single upstream sees all queries), no third-party trust required, DNSSEC validation.

## Repository Structure

```
pi-cluster/
├── ARCHITECTURE.md              # Detailed architecture docs
├── CLAUDE.md                    # This file (project context)
├── kubeconfig                   # Local kubectl config (gitignored)
├── docs/
│   ├── external-secrets-1password-sdk.md  # ESO reference
│   └── pi-worker-setup.md                 # Worker node setup guide
├── scripts/
│   ├── deploy-all.sh            # Legacy deploy scripts
│   ├── deploy-monitoring.sh     # (superseded by Flux)
│   └── deploy-pihole.sh
└── clusters/
    └── pi-k3s/
        ├── kustomization.yaml   # Root - only includes flux-system
        ├── flux-system/
        │   ├── gotk-components.yaml  # Flux controllers
        │   ├── gotk-sync.yaml        # GitRepository + root Kustomization
        │   ├── kustomization.yaml
        │   └── infrastructure.yaml   # Child Kustomizations with dependencies
        ├── external-secrets/
        │   ├── kustomization.yaml
        │   └── helmrelease.yaml      # ESO HelmRelease + HelmRepository
        ├── external-secrets-config/
        │   ├── kustomization.yaml
        │   └── cluster-secret-store.yaml  # 1Password ClusterSecretStore
        ├── ingress/
        │   ├── kustomization.yaml
        │   └── helmrelease.yaml      # nginx-ingress HelmRelease
        ├── cert-manager/
        │   ├── kustomization.yaml
        │   └── helmrelease.yaml      # cert-manager HelmRelease
        ├── cert-manager-config/
        │   ├── kustomization.yaml
        │   ├── external-secret.yaml  # Cloudflare API token from 1Password
        │   └── cluster-issuer.yaml   # Let's Encrypt ClusterIssuers
        ├── pihole/
        │   ├── kustomization.yaml
        │   ├── unbound-configmap.yaml
        │   ├── unbound-deployment.yaml
        │   ├── pihole-pvc.yaml
        │   ├── pihole-deployment.yaml
        │   ├── pihole-service.yaml
        │   ├── pihole-exporter.yaml
        │   ├── ingress.yaml           # pihole.lab.mtgibbs.dev
        │   └── external-secret.yaml   # Syncs password from 1Password
        ├── monitoring/
        │   ├── kustomization.yaml
        │   ├── helmrelease.yaml        # kube-prometheus-stack HelmRelease
        │   ├── ingress.yaml            # Grafana Ingress
        │   └── external-secret.yaml    # Grafana password from 1Password
        ├── uptime-kuma/
        │   ├── kustomization.yaml
        │   ├── namespace.yaml
        │   ├── pvc.yaml
        │   ├── deployment.yaml
        │   ├── service.yaml
        │   ├── ingress.yaml               # status.lab.mtgibbs.dev
        │   ├── external-secret.yaml       # Uptime Kuma password from 1Password
        │   ├── autokuma-deployment.yaml   # AutoKuma for GitOps monitors
        │   ├── autokuma-pvc.yaml          # AutoKuma persistent storage (prevents duplicate monitors)
        │   └── autokuma-monitors.yaml     # ConfigMap with monitor definitions
        ├── homepage/
        │   ├── kustomization.yaml
        │   ├── namespace.yaml
        │   ├── deployment.yaml            # Homepage with initContainer + emptyDir
        │   ├── service.yaml
        │   ├── serviceaccount.yaml        # RBAC for Kubernetes widget
        │   ├── ingress.yaml               # home.lab.mtgibbs.dev
        │   └── configmap.yaml             # Dashboard config (settings, services, widgets, bookmarks)
        ├── jellyfin/
        │   ├── kustomization.yaml
        │   ├── namespace.yaml
        │   ├── pv.yaml                    # NFS PV to Synology NAS
        │   ├── pvc.yaml                   # PersistentVolumeClaim for media
        │   ├── deployment.yaml            # Jellyfin media server
        │   ├── service.yaml
        │   └── ingress.yaml               # jellyfin.lab.mtgibbs.dev
        ├── immich/
        │   ├── kustomization.yaml
        │   ├── namespace.yaml
        │   ├── helmrelease.yaml           # Immich Helm chart v0.10.3
        │   ├── pv.yaml                    # NFS PV to Synology NAS
        │   └── external-secret.yaml       # Database password from 1Password
        ├── flux-notifications/
        │   ├── kustomization.yaml
        │   ├── discord-provider.yaml      # Discord notification provider
        │   ├── discord-alert.yaml         # Alert for all Flux events
        │   └── external-secret.yaml       # Discord webhook URL from 1Password
        ├── backup-jobs/
        │   ├── kustomization.yaml
        │   └── immich-backup.yaml         # Nightly PVC backup to Synology NAS
        └── external-services/
            ├── kustomization.yaml
            ├── namespace.yaml
            ├── unifi.yaml                 # Unifi Controller (192.168.1.30:8443, HTTPS backend)
            └── synology.yaml              # Synology NAS (192.168.1.60:5000)
```

## Flux Dependency Chain

Kustomizations are applied in order via `dependsOn`:

```
1.  external-secrets        → Installs ESO operator + CRDs
2.  external-secrets-config → Creates ClusterSecretStore (needs CRDs)
3.  ingress                 → nginx-ingress controller
4.  cert-manager            → Installs cert-manager CRDs + controllers
5.  cert-manager-config     → Creates ClusterIssuers + Cloudflare secret (needs cert-manager + ESO)
6.  pihole                  → Creates ExternalSecret + workloads (needs SecretStore)
7.  monitoring              → kube-prometheus-stack + Grafana (needs secrets, ingress, certs)
8.  uptime-kuma             → Status page (needs secrets, ingress, certs)
9.  homepage                → Unified dashboard (needs ingress, certs)
10. external-services       → Reverse proxies for home infrastructure (needs ingress, certs)
```

## Key Technical Details

### External Secrets Operator (ESO)
- Version: 1.2.0
- Provider: `onepasswordSDK` (uses service account, no Connect server)
- ClusterSecretStore: `onepassword` (cluster-wide, references `pi-cluster` vault)
- ExternalSecret: Creates K8s secrets from 1Password items
- Key format: `item/field` (e.g., `pihole/password`)

### Kustomize Namespace Transformer (IMPORTANT)

**Never use `namespace:` in kustomization.yaml when deploying HelmReleases.**

When you set `namespace: <name>` in a `kustomization.yaml`, Kustomize applies a namespace transformer that overrides ALL resources, ignoring their declared namespaces:

```yaml
# BAD - This breaks HelmReleases
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: myapp  # <-- Overrides EVERYTHING, including HelmRepository in flux-system
```

**Why it matters for Flux:**
- `HelmRepository` must be in `flux-system` (where source-controller runs)
- `HelmRelease` can be in any namespace, but references `HelmRepository` in `flux-system`
- If `HelmRepository` gets namespace-transformed, Flux can't find it

**Correct pattern:**
```yaml
# GOOD - Let resources declare their own namespaces
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
# Don't set namespace here - resources have explicit namespaces
resources:
  - namespace.yaml      # Creates 'myapp' namespace
  - helmrelease.yaml    # Contains HelmRepo (flux-system) + HelmRelease (myapp)
```

### 1Password Setup
- Vault: `pi-cluster` (contains `pihole`, `grafana`, `cloudflare` items)
- Service Account: `pi-cluster-operator` (token in Development - Private vault)
- K8s Secret: `onepassword-service-account` in `external-secrets` namespace
- Bootstrap: Service account token must be created manually before Flux sync

**Required 1Password Items:**
| Item | Field | Used By |
|------|-------|---------|
| `pihole` | `password` | Pi-hole admin password |
| `grafana` | `admin-user`, `admin-password` | Grafana login |
| `cloudflare` | `api-token` | Let's Encrypt DNS-01 challenge |
| `uptime-kuma` | `username`, `password` | Uptime Kuma login + AutoKuma API access |
| `immich` | `db-password` | Immich PostgreSQL database password |
| `discord-alerts` | `webhook-url` | Discord webhook for Flux notifications |

### Pi-hole Config
- Uses `hostNetwork: true` for port 53 access
- Strategy: `Recreate` (PVCs are ReadWriteOnce)
- Password via ExternalSecret from 1Password
- Upstream DNS: Unbound (configured via API, env vars ignored in v6)
- DNSSEC disabled (Unbound handles it)
- Adlists: Firebog curated lists via ConfigMap (~900k domains)

### Pi-hole v6 API Notes
Pi-hole v6 ignores most environment variables. Configuration is done via REST API in postStart hook:
- `POST /api/auth` - Get session ID
- `PATCH /api/config` - Set upstream DNS to Unbound ClusterIP
- `POST /api/lists` - Add adlists from ConfigMap (batch format)
- `POST /api/action/gravity` - Update gravity database

See `docs/pihole-v6-api.md` for full API reference.

### Unbound Config
- Port 5335 (non-privileged)
- Full recursive resolution
- DNSSEC validation enabled

### nginx-ingress Config
- Uses hostPort 443 (HTTPS only, port 80 is used by Pi-hole's hostNetwork)
- Deployed via HelmRelease
- Handles TLS termination for all web UIs

### TLS Certificates (Let's Encrypt + Cloudflare)
- **ClusterIssuers**: `letsencrypt-prod` (primary), `letsencrypt-staging` (testing)
- **Challenge type**: DNS-01 via Cloudflare API
- **Domain**: `*.lab.mtgibbs.dev` (wildcard DNS record)
- **Email**: matt@mtgibbs.xyz (for Let's Encrypt notifications)
- **Cloudflare API token**: Synced from 1Password via ExternalSecret

#### Cloudflare Setup
1. **API Token** (https://dash.cloudflare.com/profile/api-tokens):
   - Permissions: Zone → DNS → Edit
   - Zone Resources: Include → mtgibbs.dev
2. **DNS Record**:
   - Type: A, Name: `*.lab`, Content: `192.168.1.55`, Proxy status: OFF
3. **1Password Item**:
   - Vault: `pi-cluster`, Item: `cloudflare`, Field: `api-token`

#### Certificate Troubleshooting
```bash
# Check ClusterIssuers status
kubectl get clusterissuers

# Check certificate status
kubectl get certificates -A

# Debug certificate issues
kubectl describe certificate grafana-tls -n monitoring

# Check cert-manager logs
kubectl -n cert-manager logs deploy/cert-manager

# Test HTTPS (should show "Let's Encrypt" issuer)
curl -v https://grafana.lab.mtgibbs.dev 2>&1 | grep issuer
```

### Uptime Kuma Config
- Version 2.x
- Status page for monitoring home services
- URL: https://status.lab.mtgibbs.dev
- Data persisted to PVC (2Gi, local-path storage)
- **AutoKuma** manages monitors declaratively via GitOps

#### AutoKuma Configuration
- Image: `ghcr.io/bigboot/autokuma:latest`
- Monitors defined as JSON files in ConfigMap (`autokuma-monitors`)
- Each `.json` file in the ConfigMap becomes a monitor (filename = monitor ID)
- Required settings:
  - `AUTOKUMA__FILES__FOLLOW_SYMLINKS=true` (Kubernetes ConfigMaps use symlinks)
  - `AUTOKUMA__DOCKER__ENABLED=false` (not using Docker source)
  - `AUTOKUMA__ON_DELETE=delete` (monitors removed from ConfigMap are deleted)
- Credentials synced from 1Password via ExternalSecret
- **Persistent Storage**: 100Mi PVC mounted at `/data` to store sled database
  - **Critical**: Prevents duplicate monitor creation on pod restart
  - Without PVC, AutoKuma forgets which monitors it created and creates duplicates
  - Uses `strategy: Recreate` (required for ReadWriteOnce PVC)

#### Configured Monitors (12 total)
| Monitor | Type | Target |
|---------|------|--------|
| Pi-hole DNS | port | 192.168.1.55:53 |
| Pi-hole Admin | http | https://pihole.lab.mtgibbs.dev/admin/ |
| Grafana | http | https://grafana.lab.mtgibbs.dev/api/health |
| Prometheus | http | http://prometheus-kube-prometheus-prometheus.monitoring:9090/-/healthy |
| Unbound DNS | port | unbound.pihole.svc.cluster.local:5335 |
| K3s API | port | 192.168.1.55:6443 (TCP port check) |
| Uptime Kuma | http | https://status.lab.mtgibbs.dev/ |
| Homepage | http | https://home.lab.mtgibbs.dev/ |
| Jellyfin | http | https://jellyfin.lab.mtgibbs.dev/ |
| Immich | http | https://immich.lab.mtgibbs.dev/ |
| Unifi Controller | http | https://unifi.lab.mtgibbs.dev/ |
| Synology NAS | http | https://nas.lab.mtgibbs.dev/ |

## Commands Reference

```bash
# Set kubeconfig
export KUBECONFIG=~/dev/pi-cluster/kubeconfig

# Flux commands
flux get all                              # Check all Flux resources
flux reconcile source git flux-system     # Force git sync
flux reconcile kustomization pihole       # Reconcile specific kustomization

# Check secrets
kubectl get clustersecretstores           # Should show 'onepassword' as Ready
kubectl get externalsecrets -A            # Should show SecretSynced
kubectl get secrets -n pihole             # Should show pihole-secret

# Test DNS (from Mac)
# dig @192.168.1.55 google.com

# Debug
kubectl get pods -A
kubectl -n pihole logs deploy/pihole
kubectl -n external-secrets logs deploy/external-secrets

# Bootstrap 1Password secret (one-time, on fresh cluster)
op run --env-file=<(echo 'OP_TOKEN="op://Development - Private/<item-id>/credential"') -- \
  bash -c 'kubectl create secret generic onepassword-service-account \
    --namespace=external-secrets \
    --from-literal=token="$OP_TOKEN"'
```

## Known Issues / Future Work

### DNS Resilience (RESOLVED)
The Pi now uses static DNS (1.1.1.1, 8.8.8.8) configured via NetworkManager. This ensures the Pi can pull images even when Pi-hole is down. See ARCHITECTURE.md for details.

### Monitoring Stack
kube-prometheus-stack is fully managed via Flux GitOps with ExternalSecret for Grafana password.

### Homepage Dashboard
- **Image**: `ghcr.io/gethomepage/homepage:latest`
- **URL**: https://home.lab.mtgibbs.dev
- **Configuration**: Fully GitOps-managed via ConfigMap
- **Theme**: Dark theme with clean layout
- **Sections**:
  - Infrastructure: Pi-hole, Unbound, K3s Cluster
  - Monitoring: Grafana, Uptime Kuma, Prometheus
  - Media: Jellyfin, Immich
  - Network: Unifi Controller
  - Storage: Synology NAS
  - **Kubernetes widget**: Real-time node metrics (CPU, memory, uptime for all 3 nodes)
  - System resources widget (CPU, RAM, disk)
  - Bookmarks to GitHub repo and Flux docs
- **Technical details**:
  - Uses initContainer to copy ConfigMap to writable emptyDir (Homepage needs writable config dir)
  - Requires `HOMEPAGE_ALLOWED_HOSTS` env var set to ingress hostname
  - Port 3000 exposed via ClusterIP service
  - TLS certificate via Let's Encrypt (cert-manager)
  - **RBAC**: ServiceAccount with ClusterRole for read-only node metrics access
    - Enables Kubernetes widget to query cluster API for node stats
    - ClusterRoleBinding grants necessary permissions

### Jellyfin Media Server
- **Image**: `jellyfin/jellyfin:latest`
- **URL**: https://jellyfin.lab.mtgibbs.dev
- **Purpose**: Self-hosted media streaming server (open-source Plex alternative)
- **Storage**: NFS PersistentVolume to Synology NAS (`192.168.1.60:/volume1/video`)
- **Why Jellyfin**: Open-source, no proprietary restrictions, better privacy, no licensing concerns
- **Configuration**:
  - Namespace: `jellyfin`
  - Port: 8096
  - Ingress with Let's Encrypt TLS certificate
  - Replaces Plex in Homepage dashboard

### Immich Photo Management
- **Version**: v2.4.1 (upgraded from v1.123.0)
- **URL**: https://immich.lab.mtgibbs.dev
- **Purpose**: Self-hosted photo backup and management (Google Photos alternative)
- **Deployment**: Helm chart (immich-charts v0.10.3)
- **Storage**: NFS PersistentVolume to Synology NAS for photo storage
- **Database**: PostgreSQL with pgvector extension (for ML features)
- **Cache**: Valkey (Redis fork) for performance
- **Migration Notes**:
  - Upgraded via two-step path: v1.123.0 → v1.132.3 → v2.4.1
  - v1.132.3 was the last TypeORM version before Kysely migration
  - v2.x introduced major database schema changes
  - Fixed storage: `IMMICH_MEDIA_LOCATION=/data` (matches PVC mount)
  - NFSv3 required for Synology NAS compatibility with Pi ARM architecture
- **CLI Import**: `npx @immich/cli@latest upload --key <api-key> /path/to/photos`

### Discord Deployment Notifications
- **Namespace**: `flux-notifications`
- **Provider**: Discord webhook
- **Purpose**: Real-time notifications for Flux GitOps deployments
- **Configuration**:
  - Discord Provider with webhook URL from 1Password (`discord-alerts/webhook-url`)
  - Alert monitors all Kustomizations and HelmReleases
  - 30s timeout to accommodate Pi network latency
  - Notifies on: info, error events (reconciliation success/failure)
- **Setup**:
  1. Create Discord webhook in server settings
  2. Store webhook URL in 1Password (`pi-cluster` vault, `discord-alerts` item)
  3. ExternalSecret syncs webhook URL to Kubernetes secret
  4. Flux Provider references secret for webhook URL

### External Service Reverse Proxies
- **Namespace**: `external-services`
- **Purpose**: Provide unified TLS-enabled access to home infrastructure devices
- **Pattern**: Kubernetes Endpoints + Service without selector
  - Endpoints resource defines external IP:port
  - Service (ClusterIP) routes to Endpoints
  - Ingress adds TLS termination and subdomain routing

#### Configured Services
| Service | Backend | URL |
|---------|---------|-----|
| Unifi Controller | 192.168.1.30:8443 (HTTPS) | https://unifi.lab.mtgibbs.dev |
| Synology NAS | 192.168.1.60:5000 (HTTP) | https://nas.lab.mtgibbs.dev |

**Special Configuration**:
- **Unifi**: Requires nginx annotations for HTTPS backend:
  - `nginx.ingress.kubernetes.io/backend-protocol: "HTTPS"`
  - `nginx.ingress.kubernetes.io/proxy-ssl-verify: "false"` (self-signed backend cert)
- All services get Let's Encrypt TLS certificates via cert-manager

## Future Additions (Backlog)

- **Pi-hole HA** - Implement failover/redundancy for DNS service
- **Shared NFS storage** - Migrate from local-path to NFS for multi-node PVC access
- **Resource quotas** - Namespace-level resource limits and policies
- **Network policies** - Pod-to-pod traffic segmentation and security
- **Horizontal Pod Autoscaling** - Auto-scale workloads based on CPU/memory metrics

## Claude Code Extensions

This project includes custom slash commands, skills, and agents to streamline cluster operations.

### Slash Commands (User-Invoked)

| Command | Purpose | When to Use |
|---------|---------|-------------|
| `/flux-status` | Show Flux sync status | "Is everything synced?", "Check flux" |
| `/deploy` | Commit, push, reconcile | "Deploy this", "Push these changes" |
| `/test-dns` | Test DNS resolution | "Is DNS working?", "Test pihole" |
| `/backup-now` | Trigger manual backup | "Backup now", "Run a backup" |
| `/cluster-health` | Quick health check | "How's the cluster?", "Any issues?" |

### Skills (Auto-Activated by Context)

| Skill | Triggers On | Provides |
|-------|-------------|----------|
| `flux-deployment` | Flux issues, deployments, GitOps | Deployment procedures, dependency chain, troubleshooting |
| `k8s-troubleshooting` | Pod failures, connectivity, errors | Diagnostic commands, common fixes |
| `secrets-management` | 1Password, ExternalSecrets | ESO setup, secret sync debugging |
| `add-service` | Adding new apps | Full scaffold templates, checklist |

### Agents (Specialized AI Assistants)

| Agent | Purpose |
|-------|---------|
| `cluster-ops` | Infrastructure changes, deployments, troubleshooting |

**IMPORTANT: Use `cluster-ops` agent for ALL cluster operations.**

When performing any kubectl, flux, or helm operations, Claude MUST use the `cluster-ops` agent (via the Task tool with `subagent_type: cluster-ops`). This includes:
- Checking pod status, logs, events
- Reconciling Flux resources
- Debugging deployments
- Verifying PVCs, secrets, ingress
- Any other cluster introspection or troubleshooting

This ensures consistent kubeconfig usage and proper error handling. Only exception: simple status checks in slash commands (which handle their own kubeconfig).

### How to Leverage These

**For vague requests, Claude will clarify:**

| You Say | Claude May Ask |
|---------|---------------|
| "Deploy this" | "Should I run `/deploy` to commit and sync, or do you want me to just reconcile?" |
| "Something's broken" | "I'll use k8s-troubleshooting - is it a pod issue, DNS, or connectivity?" |
| "Add a new service" | "I'll use add-service skill. What's the service name, image, and port?" |
| "Check on things" | "Would you like `/cluster-health` for a quick check or `/flux-status` for GitOps status?" |

**Be specific when you can:**

| Vague | Specific |
|-------|----------|
| "Deploy" | "/deploy feat: Add redis cache" |
| "DNS broken" | "/test-dns google.com" |
| "Status" | "/flux-status" or "/cluster-health" |

### Directory Structure

```
.claude/
├── commands/           # Slash commands (user-invoked)
│   ├── flux-status.md
│   ├── deploy.md
│   ├── test-dns.md
│   ├── backup-now.md
│   └── cluster-health.md
├── skills/             # Skills (auto-activated)
│   ├── flux-deployment/
│   ├── k8s-troubleshooting/
│   ├── secrets-management/
│   └── add-service/
└── agents/             # Subagents
    └── cluster-ops.md
```
