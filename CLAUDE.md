# Pi K3s Cluster Project

## Project Goal

Build a learning Kubernetes cluster on a Raspberry Pi 5 to run Pi-hole + Unbound, with observability (Grafana/Prometheus), using proper IaC practices. Managed via GitOps (Flux) with secrets from 1Password.

## Security Principles

**IMPORTANT: Never ask the user for secrets, tokens, passwords, or API keys directly.**

As a security-conscious assistant working on this infrastructure project:

1. **Never request secrets in conversation** - Don't ask users to paste tokens, passwords, API keys, or any sensitive credentials into the chat.

2. **Always use 1Password** - When a new secret is needed, instruct the user to:
   - Create/store the secret in 1Password (`pi-cluster` vault)
   - Provide the item name and field structure
   - Example: "Please create a 1Password item called `my-service` with fields `api-key` and `password` in the `pi-cluster` vault"

3. **Use ExternalSecrets for Kubernetes** - Secrets are synced via:
   - `ClusterSecretStore` named `onepassword` (already configured)
   - `ExternalSecret` resources that reference 1Password items
   - Key format: `item-name/field-name` (e.g., `pihole/password`)

4. **Never commit secrets** - All sensitive values stay in 1Password. Git only contains references.

5. **Verify secrets exist, don't view them** - Use commands like:
   ```bash
   kubectl get externalsecrets -A  # Check sync status
   kubectl get secret <name> -o yaml | grep -c "^  [a-z]"  # Count keys, don't show values
   ```

**When adding new services that need secrets:**
1. **Proactively create the 1Password item** using the CLI (see below) - this prevents typos and makes it easier for the user to find
2. Create the ExternalSecret manifest referencing those fields
3. Reference the resulting K8s secret in deployments
4. Tell the user to fill in the values in 1Password

**Creating 1Password Items via CLI:**
When a new secret is needed, create a blank "Password" type item in 1Password with the correct structure. The user will then fill in the actual values. This ensures field names match exactly what the ExternalSecret expects.

```bash
# Create a new item with fields (values left blank for user to fill)
op item create \
  --vault "pi-cluster" \
  --category "Password" \
  --title "service-name" \
  --field "label=api-key,type=concealed" \
  --field "label=password,type=concealed"

# Example for Tailscale:
op item create \
  --vault "pi-cluster" \
  --category "Password" \
  --title "tailscale" \
  --field "label=oauth-client-id,type=concealed" \
  --field "label=oauth-client-secret,type=concealed" \
  --field "label=api-key,type=concealed" \
  --field "label=device-id,type=text"
```

After creating the item, tell the user: "I've created a `service-name` item in 1Password with the required fields. Please fill in the values."

## Current State

### Hardware & OS

**Master Node:**
- Raspberry Pi 5 (8GB RAM)
- Raspberry Pi OS Lite (64-bit)
- Hostname: `pi-k3s`
- Static IP: 192.168.1.55 (DHCP reservation)
- User: `mtgibbs`

**Worker Nodes:**
- Raspberry Pi 5 (8GB RAM) - `pi5-worker-1` (192.168.1.56)
- Raspberry Pi 5 (8GB RAM) - `pi5-worker-2` (192.168.1.57)
- Raspberry Pi 3 (1GB RAM) - `pi3-worker-2` (192.168.1.51)
- All running Raspberry Pi OS Lite (64-bit)
- SSH keys and K3s node token stored in 1Password
- Setup documented in `docs/pi-worker-setup.md`

**Node Capabilities:**
- **Pi 5 nodes (3x)**: Full workloads - DNS, databases, media servers, resource-intensive services
- **Pi 3 node (1x)**: Lightweight stateless apps only (Homepage, simple web services) - 1GB RAM limitation

### Completed Setup
1. **cgroups enabled** - Added `cgroup_memory=1 cgroup_enable=memory` to `/boot/firmware/cmdline.txt`
2. **Swap disabled** - Masked `systemd-zram-setup@zram0.service`
3. **k3s installed** - Version v1.34.3+k3s1, installed with `--disable=traefik`
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
16. **Multi-node cluster** - 3x Pi 5 + 1x Pi 3 (4 nodes total) for workload distribution
17. **Flux Image Automation** - Auto-deploy personal website from GHCR
18. **mtgibbs.xyz Personal Site** - Next.js website with auto-deploy on git push
19. **Pi-hole HA** - Redundant DNS with two Pi-hole instances on separate Pi 5 nodes
20. **Tailscale VPN** - Mobile ad blocking via exit node, remote access without open ports

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
- [x] Multi-node cluster (Pi 5 master + 2x Pi 5 workers + 1x Pi 3 worker)
- [x] Workload distribution across nodes
- [x] Tailscale VPN with exit node for mobile ad blocking

### Service URLs
All services use subdomain-based routing via `*.lab.mtgibbs.dev`:

**Cluster Services:**
- **Homepage**: https://home.lab.mtgibbs.dev (unified dashboard with node stats)
- **Grafana**: https://grafana.lab.mtgibbs.dev
- **Uptime Kuma**: https://status.lab.mtgibbs.dev
- **Pi-hole Admin**: https://pihole.lab.mtgibbs.dev (also available via hostNetwork: http://192.168.1.55/admin/)
- **Jellyfin**: https://jellyfin.lab.mtgibbs.dev (media server)
- **Immich**: https://immich.lab.mtgibbs.dev (photo backup)
- **Personal Site**: https://site.lab.mtgibbs.dev (mtgibbs.xyz)

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
│                        K3s Cluster (4 nodes)                                │
│                                                                             │
│  ┌────────────────┐   ┌─────────────────┐   ┌─────────────────┐            │
│  │  pi-k3s (Pi 5) │   │ pi5-worker-1    │   │ pi5-worker-2    │            │
│  │  192.168.1.55  │   │ 192.168.1.56    │   │ 192.168.1.57    │            │
│  │  (master, 8GB) │   │ (worker, 8GB)   │   │ (worker, 8GB)   │            │
│  │                │   │                 │   │                 │            │
│  │ • Pi-hole      │   │ • Workloads     │   │ • Workloads     │            │
│  │ • Flux         │   │                 │   │                 │            │
│  │ • Backups      │   │                 │   │                 │            │
│  └────────────────┘   └─────────────────┘   └─────────────────┘            │
│                                                                             │
│  ┌────────────────┐                                                        │
│  │ pi3-worker-2   │                                                        │
│  │ 192.168.1.51   │                                                        │
│  │ (worker, 1GB)  │                                                        │
│  │                │                                                        │
│  │ • Homepage     │                                                        │
│  │ • Lightweight  │                                                        │
│  └────────────────┘                                                        │
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
│  │  │ (pi-k3s) │     │ (pi-k3s)       │                 │             │   │
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
        │   ├── helmrelease.yaml        # kube-prometheus-stack HelmRelease (Alertmanager enabled)
        │   ├── ingress.yaml            # Grafana Ingress
        │   └── external-secret.yaml    # Grafana password + Discord webhook from 1Password
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
        │   ├── rbac.yaml                  # ServiceAccount + ClusterRole for Kubernetes widget
        │   ├── ingress.yaml               # home.lab.mtgibbs.dev
        │   ├── configmap.yaml             # Dashboard config (settings, services, widgets, bookmarks)
        │   └── external-secret.yaml       # API keys for widget auth (4 separate secrets)
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
        │   ├── helmrelease.yaml           # Immich Helm chart v0.10.3 (telemetry enabled)
        │   ├── pv.yaml                    # NFS PV to Synology NAS
        │   ├── servicemonitor.yaml        # Prometheus scraping config
        │   ├── prometheusrule.yaml        # Alert definitions (6 alerts)
        │   └── external-secret.yaml       # Database password from 1Password
        ├── flux-notifications/
        │   ├── kustomization.yaml
        │   ├── discord-provider.yaml      # Discord notification provider
        │   ├── discord-alert.yaml         # Alert for all Flux events
        │   └── external-secret.yaml       # Discord webhook URL from 1Password
        ├── backup-jobs/
        │   ├── kustomization.yaml
        │   ├── immich-backup.yaml         # Nightly PVC backup to Synology NAS (2:00 AM Sundays)
        │   ├── postgres-backup-cronjob.yaml  # PostgreSQL backup CronJob (2:30 AM Sundays)
        │   └── postgres-backup-secret.yaml   # ExternalSecret for DB password
        ├── external-services/
        │   ├── kustomization.yaml
        │   ├── namespace.yaml
        │   ├── unifi.yaml                 # Unifi Controller (192.168.1.30:8443, HTTPS backend)
        │   └── synology.yaml              # Synology NAS (192.168.1.60:5000)
        ├── tailscale/
        │   ├── kustomization.yaml
        │   ├── namespace.yaml             # tailscale namespace
        │   ├── external-secret.yaml       # OAuth credentials from 1Password
        │   └── helmrelease.yaml           # Tailscale Operator HelmRelease (v1.92.5)
        ├── tailscale-config/
        │   ├── kustomization.yaml
        │   ├── proxyclass.yaml            # ProxyClass for exit node pods (arm64 nodeSelector)
        │   └── connector.yaml             # Connector CRD for exit node
        └── mtgibbs-site/
            ├── kustomization.yaml
            ├── namespace.yaml
            ├── deployment.yaml            # Next.js app with image automation marker
            ├── service.yaml               # ClusterIP on port 3000
            ├── ingress.yaml               # site.lab.mtgibbs.dev with TLS
            └── image-automation.yaml      # ImageRepository + ImagePolicy + ImageUpdateAutomation
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
11. flux-notifications      → Discord deployment notifications (needs ESO)
12. backup-jobs             → PVC + PostgreSQL backups (needs ESO, workloads)
13. immich                  → Photo management (needs ESO, ingress, certs)
14. jellyfin                → Media server (needs ingress, certs)
15. mtgibbs-site            → Personal website (needs ingress, certs)
16. tailscale               → Tailscale Operator (needs ESO for OAuth credentials)
17. tailscale-config        → Connector + ProxyClass CRDs (needs tailscale operator running)
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
| `pihole` | `api-key` | Pi-hole v6 API key for Homepage widget |
| `grafana` | `admin-user`, `admin-password` | Grafana login |
| `cloudflare` | `api-token` | Let's Encrypt DNS-01 challenge |
| `uptime-kuma` | `username`, `password` | Uptime Kuma login + AutoKuma API access |
| `immich` | `db-password` | Immich PostgreSQL database password |
| `immich` | `api-key` | Immich API key (server.statistics permission) for Homepage widget |
| `jellyfin` | `api-key` | Jellyfin API key for Homepage widget |
| `unifi` | `username`, `password` | Unifi local account for Homepage widget |
| `discord-alerts` | `webhook-url` | Discord webhook for Flux notifications |
| `alertmanager` | `discord-alerts-webhook-url` | Discord webhook for Prometheus alerts |
| `flux-github-pat` | `token` | Fine-grained GitHub PAT for Flux image automation (write access) |
| `mtgibbs-spotify` | `client`, `client-secret`, `refresh-token` | Spotify integration for mtgibbs.xyz |
| `mtgibbs-github` | `token` | GitHub PAT for mtgibbs.xyz Project Deck (read-only, repo contents) |
| `tailscale` | `oauth-client-id`, `oauth-client-secret` | Tailscale Kubernetes Operator OAuth credentials |

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
- **Node placement**: Pi 5 nodes only via nodeSelector
  - **Why**: Pi 3 hardware insufficient for reliable DNS operations (TCP connection failures observed)
  - **Performance**: 21ms uncached queries, 0-15ms cached (vs 500-10,000ms on Pi 3)

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

#### Configured Monitors (14 total)
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
| Personal Site (Cluster) | http | https://site.lab.mtgibbs.dev/ |
| Personal Site (Heroku) | http | https://mtgibbs.xyz/ |

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

### Flux Image Automation

**Purpose**: Automatically update deployment manifests when new images are pushed to container registry

**Components**:
- **image-reflector-controller**: Scans container registries for new image tags
- **image-automation-controller**: Updates manifests in git when new images are detected

**Configuration** (`mtgibbs-site` example):
```yaml
# ImageRepository - scans GHCR every 5 minutes
apiVersion: image.toolkit.fluxcd.io/v1
kind: ImageRepository
metadata:
  name: mtgibbs-site
  namespace: flux-system
spec:
  image: ghcr.io/mtgibbs/mtgibbs.xyz
  interval: 5m0s

# ImagePolicy - selects newest timestamp tag (YYYYMMDDHHmmss)
apiVersion: image.toolkit.fluxcd.io/v1
kind: ImagePolicy
metadata:
  name: mtgibbs-site
  namespace: flux-system
spec:
  imageRepositoryRef:
    name: mtgibbs-site
  filterTags:
    pattern: '^[0-9]{14}$'  # Timestamp tags only
  policy:
    numerical:
      order: asc  # Higher number = newer

# ImageUpdateAutomation - updates deployment.yaml, commits, pushes
apiVersion: image.toolkit.fluxcd.io/v1
kind: ImageUpdateAutomation
metadata:
  name: mtgibbs-site
  namespace: flux-system
spec:
  interval: 5m0s
  sourceRef:
    kind: GitRepository
    name: flux-system
  git:
    checkout:
      ref:
        branch: main
    commit:
      author:
        name: fluxcdbot
        email: fluxcdbot@users.noreply.github.com
      messageTemplate: |
        chore: update mtgibbs-site to {{range .Changed.Changes}}{{.NewValue}}{{end}}
    push:
      branch: main
  update:
    path: ./clusters/pi-k3s/mtgibbs-site
    strategy: Setters
```

**Deployment Marker** (required for Setters strategy):
```yaml
# deployment.yaml
spec:
  template:
    spec:
      containers:
        - name: mtgibbs-site
          image: ghcr.io/mtgibbs/mtgibbs.xyz:20260104084623 # {"$imagepolicy": "flux-system:mtgibbs-site"}
```

**Auto-Deploy Flow**:
1. Developer pushes code to `mater` branch in mtgibbs.xyz repository
2. GitHub Actions builds multi-arch image (AMD64 + ARM64), tags with timestamp
3. Image pushed to GHCR: `ghcr.io/mtgibbs/mtgibbs.xyz:20260104084623`
4. ImageRepository scans GHCR every 5 minutes, detects new tag
5. ImagePolicy evaluates tag (higher timestamp = newer)
6. ImageUpdateAutomation updates deployment.yaml with new tag
7. Flux commits + pushes update to pi-cluster repository
8. Standard Flux Kustomization reconciles deployment (every 10 minutes)
9. New image deployed to cluster

**Total deployment time**: ~5-15 minutes from code push to live

**GitHub PAT Requirements**:
- Flux needs write access to push commits (default deploy key is read-only)
- Re-bootstrap with `--read-write-key` flag
- Fine-grained PAT with:
  - Repository: pi-cluster only
  - Permissions: Contents (read/write), Administration (read/write for deploy keys)
  - Expiration: 90 days (stored in 1Password: `flux-github-pat`)

**Security Considerations**:
- Flux has write access to infrastructure repository (potential attack vector)
- Fine-grained PAT limits blast radius (single repo, specific permissions)
- Image tags must match policy pattern (prevents arbitrary image injection)
- Only commits to specified path (`./clusters/pi-k3s/mtgibbs-site`)

## Known Issues / Future Work

### DNS Resilience (RESOLVED)
The Pi now uses static DNS (1.1.1.1, 8.8.8.8) configured via NetworkManager. This ensures the Pi can pull images even when Pi-hole is down. See ARCHITECTURE.md for details.

### Monitoring Stack
kube-prometheus-stack is fully managed via Flux GitOps with ExternalSecret for Grafana password.

**Alerting Configuration**:
- **Alertmanager**: Enabled in kube-prometheus-stack
- **Discord Notifications**: Webhook URL synced from 1Password
- **Routing**: All alerts sent to Discord receiver with 5-minute group interval
- **Silenced Alerts**: Watchdog (intentional heartbeat), KubeMemoryOvercommit (expected behavior)
- **Message Format**: Alert name, severity, instance, and description

**Active PrometheusRules**:
- Immich: 6 alerts (server down, queue stuck, slow queries, no activity)
- Default Kubernetes alerts from kube-prometheus-stack (node health, pod failures, etc.)

### Homepage Dashboard
- **Image**: `ghcr.io/gethomepage/homepage:latest`
- **URL**: https://home.lab.mtgibbs.dev
- **Configuration**: Fully GitOps-managed via ConfigMap
- **Node placement**: Prefers Pi 3 workers via nodeAffinity
  - **Why**: Lightweight service (~111Mi), frees memory on Pi 5 for critical infrastructure
- **Theme**: Dark theme with clean layout
- **Sections**:
  - Infrastructure: Pi-hole (with live stats), Unbound, K3s Cluster
  - Monitoring: Grafana, Uptime Kuma (with service status), Prometheus (with target stats)
  - Web: Personal Site (Cluster), Personal Site (Heroku), Cloudflare
  - Media: Jellyfin (with library stats), Immich (with photo/video counts)
  - Network: Unifi Controller (with WiFi/LAN device counts)
  - Storage: Synology NAS
  - **Kubernetes widget**: Real-time node metrics (CPU, memory, uptime for all 4 nodes)
  - **Weather widget**: Johns Creek, GA (34.0289, -84.1986)
  - System resources widget (CPU, RAM, disk)
  - Bookmarks to GitHub repo and Flux docs
- **Live Widgets** (API-integrated):
  - **Pi-hole**: queries, blocked count, blocked %, gravity size (v6 API)
  - **Immich**: photos, videos, storage (requires API key with server.statistics permission)
  - **Jellyfin**: library stats, now playing (requires API key)
  - **Prometheus**: targets up/down/total (read-only metrics endpoint)
  - **Uptime Kuma**: service status (requires status page with slug 'home')
  - **Unifi**: WiFi users, LAN devices, WAN stats (requires local account)
- **Technical details**:
  - Uses initContainer to copy ConfigMap to writable emptyDir (Homepage needs writable config dir)
  - Requires `HOMEPAGE_ALLOWED_HOSTS` env var set to ingress hostname
  - Port 3000 exposed via ClusterIP service
  - TLS certificate via Let's Encrypt (cert-manager)
  - **RBAC**: ServiceAccount with ClusterRole for read-only permissions
    - Enables Kubernetes widget to query cluster API for node stats
    - ClusterRoleBinding grants permissions: nodes (get/list), ingresses (get/list), deployments (get/list)
  - **Secrets management**: Each widget has its own ExternalSecret for independent auth
    - `pihole-api-key`, `immich-api-key`, `jellyfin-api-key`, `unifi-credentials`
    - API keys passed as env vars via `HOMEPAGE_VAR_*` pattern
  - **Security**: No secrets in git, only references to 1Password items

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
- **Monitoring**: Prometheus metrics enabled on ports 8081/8082
  - ServiceMonitor scrapes metrics every 30 seconds
  - PrometheusRule with 6 alerts (queue stuck, slow queries, no activity)
  - Alerts routed to Discord via Alertmanager

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

### Tailscale VPN
- **Namespace**: `tailscale`
- **Version**: Operator v1.92.5
- **Purpose**: Mobile ad blocking via Pi-hole exit node, remote access without opening router ports

#### Architecture
```
Phone (Tailscale App)
    │
    │ NAT traversal (no open ports)
    ▼
Pi K3s Cluster
    │
    ├─► Tailscale Operator (manages Connectors, ProxyClasses)
    │
    └─► Connector Pod (exit node on Pi 5)
              │
              ▼
         Pi-hole (192.168.1.55:53) → Unbound → Internet
```

#### Mode Switching
| Mode | Exit Node | What Happens |
|------|-----------|--------------|
| Split Tunnel | OFF | Only DNS queries to Pi-hole (ad blocking) |
| Full Tunnel | ON | All traffic routes through home network (privacy + ads) |

#### Components
- **HelmRelease**: Installs Tailscale Kubernetes Operator from `pkgs.tailscale.com/helmcharts`
- **ExternalSecret**: Syncs OAuth credentials from 1Password
- **ProxyClass**: Defines pod settings for exit node (arm64 nodeSelector for Pi 5)
- **Connector**: Creates the exit node with hostname `pi-cluster-exit`

#### OAuth Client Configuration
The Tailscale Operator requires OAuth credentials with minimal permissions. **Critical**: Only include necessary scopes/tags - extra scopes cause "requested tags are invalid" errors.

**Minimum OAuth Client Settings**:
- **Devices Core**: Read + Write, Tags: `tag:k8s-operator` only
- **Auth Keys**: Read + Write, Tags: `tag:k8s-operator` only
- **No other scopes** (Services, Routes, etc. are not needed)

**Common OAuth Errors**:
| Error | Cause | Fix |
|-------|-------|-----|
| `requested tags [tag:X] are invalid or not permitted` | OAuth client has extra scopes or tags | Create new OAuth client with ONLY Devices Core + Auth Keys, ONLY `tag:k8s-operator` |
| Exit node not visible in app | Missing `autogroup:internet` grant in ACL | Add grant to ACL policy |

#### Required Tailscale ACL Policy
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
        {"src": ["autogroup:member"], "dst": ["autogroup:member"], "ip": ["*"]},
        {"src": ["tag:k8s-operator"], "dst": ["autogroup:member"], "ip": ["*"]},
        {"src": ["autogroup:member"], "dst": ["tag:k8s-operator"], "ip": ["*"]},
        {"src": ["autogroup:member"], "dst": ["autogroup:internet"], "ip": ["*"]},
        {"src": ["autogroup:member"], "dst": ["192.168.1.0/24"], "ip": ["*"]}
    ],
    "ssh": [
        {"action": "check", "src": ["autogroup:member"], "dst": ["autogroup:self"], "users": ["autogroup:nonroot", "root"]}
    ]
}
```

**Critical Requirements**:
1. **Exit node grant**: `autogroup:internet` allows devices to route traffic through the exit node
2. **Subnet route grant**: `192.168.1.0/24` grant allows access to advertised subnet routes (Pi-hole IPs)
3. **Auto-approvers for routes**: Auto-approves subnet routes advertised by `tag:k8s-operator`

**Why Both Are Needed**:
- Exit node provides NAT traversal and tunnel connectivity
- Subnet routes advertise specific IPs (192.168.1.55, 192.168.1.56) to the Tailscale network
- Grants allow clients to access those advertised routes
- Without subnet route grant, DNS queries to Pi-hole IPs fail (even with tunnel connected)

#### Tailscale Admin DNS Settings
For ad blocking via Pi-hole:
1. **Add Nameservers**: `192.168.1.55` and `192.168.1.56` (Pi-hole IPs)
2. **Enable "Use with exit node"**: DNS applies when exit node is active
3. **Enable "Override local DNS"**: Forces all DNS through Pi-hole
4. **Approve Subnet Routes**: Admin console → Machines → pi-cluster-exit → Edit route settings → Approve both routes:
   - `192.168.1.55/32` (Pi-hole primary)
   - `192.168.1.56/32` (Pi-hole secondary)

**Critical**: Both subnet routes AND the grant in ACL policy must be configured. Approving routes in admin console is not enough - the ACL grant allows clients to use those routes.

#### Setup Steps
1. Create Tailscale account (any SSO provider)
2. Configure ACL tags in admin console (see policy above)
3. Create OAuth client with minimal scopes (Devices Core + Auth Keys, `tag:k8s-operator` only)
4. Store credentials in 1Password (`tailscale` item, `oauth-client-id` and `oauth-client-secret` fields)
5. Deploy via Flux (tailscale → tailscale-config dependency order)
6. Verify in Tailscale admin: exit node shows as "pi-cluster-exit"
7. Configure DNS: add Pi-hole as nameserver, enable "Override local DNS"
8. On phone: install Tailscale app, connect, select exit node for full tunnel

#### Verification Commands
```bash
# Check operator running
kubectl get pods -n tailscale

# Check connector status
kubectl get connector pi-cluster-exit -n tailscale

# Check exit node pod
kubectl get pods -n tailscale -l app=ts-pi-cluster-exit

# View operator logs for OAuth issues
kubectl logs -n tailscale deploy/operator
```

#### Troubleshooting
| Issue | Diagnostic | Solution |
|-------|-----------|----------|
| Operator pod CrashLoopBackOff | Check logs for OAuth errors | Recreate OAuth client with minimal scopes |
| Connector not creating pod | `kubectl describe connector` | Check tags match OAuth client |
| Exit node not in app | Check ACL grants | Add `autogroup:internet` grant |
| DNS not resolving | Check ACL grants and route approval | Add `192.168.1.0/24` grant to ACL, approve subnet routes in admin console |
| DNS not blocking ads | Check "Override local DNS" and "Use with exit node" | Enable both in Tailscale admin DNS settings |
| Exit node shows offline | Check pod logs | Verify OAuth client not revoked |
| Routes not showing in admin | Check Connector advertiseRoutes | Ensure `subnetRouter.advertiseRoutes` includes Pi-hole IPs |

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

## Backup Strategy

### PVC Backups (2:00 AM Sundays)
- **Job**: `immich-backup` CronJob in `backup-jobs` namespace
- **Source**: Immich PVCs on pi-k3s node (local-path storage)
- **Destination**: Synology NAS at `/volume1/k3s-backups/{date}/immich/`
- **Method**: rsync over SSH
- **Retention**: Manual (stored on NAS)

### PostgreSQL Backups (2:30 AM Sundays)
- **Job**: `postgres-backup` CronJob in `backup-jobs` namespace
- **Target**: Immich PostgreSQL database
- **Format**: pg_dump custom format with compression level 9
- **Destination**: Synology NAS at `/volume1/k3s-backups/{date}/postgres/`
- **Credentials**: DB password synced from 1Password via ExternalSecret
- **Timing**: Runs 30 minutes after PVC backup to avoid I/O conflicts
- **Transfer Method**: rsync over SSH (replaced scp due to Synology SFTP subsystem disabled)
- **PostgreSQL Client**: postgresql16-client (Alpine package name updated)

**Why Both?**
- **PVC backup**: Captures uploaded photos, app data, configuration (filesystem-level)
- **PostgreSQL backup**: Captures metadata, user accounts, albums, sharing settings (database-level)
- Together they provide complete disaster recovery (can restore from either backup type)

## Known Issues

### Immich High CPU Usage
- **Issue**: Immich causing ~2 CPU cores usage on Pi 5 due to ML job retry loop
- **Cause**: Machine learning disabled but jobs still queued and retrying
- **Impact**: High CPU usage, no functional issues
- **Resolution**: Deferred - ML features not needed, workaround is acceptable

### Dead Pi-hole Blocklists
- **Issue**: Two dead blocklists (IDs 19, 28) in Pi-hole database
- **Cause**: Manually added via web UI (not in GitOps ConfigMap)
- **Impact**: Warning logs, no blocking issues (~900k domains still active)
- **Resolution**: Deferred - not affecting DNS blocking functionality

### NFS UID/GID Mapping
- **Issue**: Files created on NFS volumes have incorrect ownership (uid=0, gid=0 instead of uid=568)
- **Cause**: Synology NFS no_root_squash setting vs application UID expectations
- **Impact**: Minimal - applications can read/write, but file ownership is incorrect
- **Resolution**: Deferred - functional workaround exists, proper fix requires Synology NFS reconfiguration

## Future Additions (Backlog)

### Planned (Ready to Implement)
- **Pi-hole HA** - Two Pi-holes on Pi 5 nodes, GitOps config, router DHCP failover
- **Cloudflare Tunnels + Loki** - Log aggregation from Heroku, outbound-only tunnel
- **Windows Remote Access** - RDP/SSH via Tailscale to home workstation

### Future Considerations
- **Headscale** - Self-hosted Tailscale control plane (when 3-user limit is hit)
- **Shared NFS storage** - Migrate from local-path to NFS for multi-node PVC access
- **Resource quotas** - Namespace-level resource limits and policies
- **Network policies** - Pod-to-pod traffic segmentation and security
- **Horizontal Pod Autoscaling** - Auto-scale workloads based on CPU/memory metrics
- **Immich ML optimization** - Resolve ML job retry loop causing high CPU
- **Pi-hole blocklist cleanup** - Remove dead lists, ensure all lists in GitOps
- **Cluster logs to Loki** - Ship K8s pod logs via Promtail

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
