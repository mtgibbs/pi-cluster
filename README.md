# Pi K3s Cluster

A production-grade Kubernetes homelab running on a Raspberry Pi 5, featuring GitOps, secrets management, and network-wide ad blocking.

## Overview

This project demonstrates enterprise-grade infrastructure practices on affordable hardware:

- **GitOps with Flux**: All configuration is declarative and version-controlled
- **Secrets Management**: 1Password integration via External Secrets Operator - no secrets in git
- **DNS Security**: Pi-hole for ad blocking + Unbound for recursive DNS resolution
- **Ingress + TLS**: nginx-ingress with Let's Encrypt certificates via Cloudflare DNS-01
- **Observability**: Prometheus + Grafana with GitOps-managed dashboards
- **Status Monitoring**: Uptime Kuma for home service health checks
- **Infrastructure as Code**: Reproducible, auditable, and self-healing

```
┌─────────────────────────────────────────────────────────────────┐
│                        Network Clients                          │
│                    (phones, laptops, IoT)                       │
└───────────────────────────┬─────────────────────────────────────┘
                            │ DNS queries (port 53)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Raspberry Pi 5 (8GB)                        │
│                        K3s Cluster                              │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    Pi-hole (pihole/pihole)                │  │
│  │              Ad blocking, DNS filtering                   │  │
│  │                   ~900k domains blocked                   │  │
│  └─────────────────────────┬─────────────────────────────────┘  │
│                            │                                    │
│                            ▼                                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │               Unbound (madnuttah/unbound)                 │  │
│  │         Recursive DNS resolver with DNSSEC                │  │
│  │              No upstream DNS providers                    │  │
│  └─────────────────────────┬─────────────────────────────────┘  │
│                            │                                    │
└────────────────────────────┼────────────────────────────────────┘
                             ▼
              Root → TLD → Authoritative DNS Servers
```

## Features

### GitOps Pipeline
```
Git Push → GitHub → Flux detects change → Applies to cluster
```
- Automatic reconciliation every 10 minutes
- Dependency ordering (secrets before apps)
- Drift detection and self-healing

### Secrets Management
- **1Password Service Account** syncs secrets to Kubernetes
- **External Secrets Operator** creates native K8s secrets from 1Password
- Zero secrets committed to git - ever

### DNS Architecture
- **Pi-hole HA**: Dual Pi-hole instances for redundancy (192.168.1.55 primary, 192.168.1.56 secondary)
- **Unbound**: Full recursive resolution (no Cloudflare/Google dependency)
- **DNSSEC**: Validated by Unbound
- **Firebog curated lists**: 25+ blocklists, ~900k domains

### VPN Remote Access
- **Tailscale Exit Node**: Secure remote access with WireGuard protocol
- **Subnet Routes**: Advertises Pi-hole IPs for mobile ad blocking
- **Zero Port Forwarding**: NAT traversal via Tailscale mesh
- **Split/Full Tunnel**: DNS-only or all traffic routing modes

## Hardware

### Master Node
| Component | Specification |
|-----------|---------------|
| Device | Raspberry Pi 5 (pi-k3s) |
| RAM | 8GB |
| CPU | ARM Cortex-A76 (4 cores) |
| Storage | microSD (local-path provisioner) |
| OS | Raspberry Pi OS Lite (64-bit) / Debian 13 |
| IP | 192.168.1.55 (static via DHCP reservation) |
| Role | Master + Worker (control plane + critical workloads) |

### Worker Nodes
| Node | Device | RAM | CPU | IP | Role |
|------|--------|-----|-----|-----|------|
| pi5-worker-1 | Raspberry Pi 5 | 8GB | ARM Cortex-A76 (4 cores) | 192.168.1.56 | Heavy workloads + Pi-hole HA |
| pi5-worker-2 | Raspberry Pi 5 | 8GB | ARM Cortex-A76 (4 cores) | 192.168.1.57 | Heavy workloads |
| pi3-worker-2 | Raspberry Pi 3 | 1GB | ARM Cortex-A53 | 192.168.1.51 | Lightweight services only |

## Stack

### Core Infrastructure
| Component | Version | Purpose |
|-----------|---------|---------|
| K3s | v1.34.3+k3s1 | Lightweight Kubernetes |
| Flux | v2.x | GitOps operator |
| External Secrets Operator | 1.2.0 | Secrets sync from 1Password |
| nginx-ingress | 4.12.0 | Ingress controller (hostPort 443) |
| cert-manager | v1.17.1 | TLS certificates (Let's Encrypt via Cloudflare) |

### DNS & VPN
| Component | Version | Purpose |
|-----------|---------|---------|
| Pi-hole | v6 (latest) | DNS-level ad blocking (HA with 2 instances) |
| Unbound | latest | Recursive DNS resolver |
| Tailscale | v1.92.5 | VPN with exit node for mobile ad blocking |

### Observability
| Component | Version | Purpose |
|-----------|---------|---------|
| kube-prometheus-stack | 80.6.0 | Prometheus + Grafana |
| Loki | 6.51.0 | Log aggregation |
| Uptime Kuma | v2.x | Status page for home services |
| AutoKuma | latest | GitOps-managed monitors for Uptime Kuma |
| Homepage | latest | Unified dashboard with live service widgets |

### Media & Photos
| Component | Version | Purpose |
|-----------|---------|---------|
| Jellyfin | latest | Self-hosted media server |
| Immich | 0.10.3 (chart) | Self-hosted photo backup and management |
| Sonarr | latest | TV show management |
| Radarr | latest | Movie management |
| Lidarr | latest | Music management |
| Prowlarr | latest | Indexer management |
| Bazarr | latest | Subtitle management |
| Jellyseerr | latest | Media request management |
| qBittorrent | latest | Torrent client |
| SABnzbd | latest | Usenet client |

### Applications
| Component | Version | Purpose |
|-----------|---------|---------|
| n8n | latest | Workflow automation |
| Ollama | latest | Local LLM inference |
| CARL | 0.3.3 | AI assistant |
| MCP Homelab | 0.1.12 | Claude Code cluster integration |
| PostgreSQL | 16 | Database for Immich (pgvector) |
| Valkey | latest | Redis-compatible cache for Immich |

## Service URLs

### Dashboards & Monitoring
| Service | URL |
|---------|-----|
| Homepage (Dashboard) | https://home.lab.mtgibbs.dev |
| Grafana (Monitoring) | https://grafana.lab.mtgibbs.dev |
| Uptime Kuma (Status) | https://status.lab.mtgibbs.dev |
| Pi-hole Admin | https://pihole.lab.mtgibbs.dev |

### Media Services
| Service | URL |
|---------|-----|
| Jellyfin (Streaming) | https://jellyfin.lab.mtgibbs.dev |
| Immich (Photos) | https://immich.lab.mtgibbs.dev |
| Jellyseerr (Requests) | https://requests.lab.mtgibbs.dev |
| Sonarr (TV) | https://sonarr.lab.mtgibbs.dev |
| Radarr (Movies) | https://radarr.lab.mtgibbs.dev |
| Lidarr (Music) | https://lidarr.lab.mtgibbs.dev |
| Bazarr (Subtitles) | https://bazarr.lab.mtgibbs.dev |
| Prowlarr (Indexers) | https://prowlarr.lab.mtgibbs.dev |
| qBittorrent | https://qbit.lab.mtgibbs.dev |
| SABnzbd | https://sabnzbd.lab.mtgibbs.dev |

### Applications
| Service | URL |
|---------|-----|
| n8n (Automation) | https://n8n.lab.mtgibbs.dev |
| CARL (AI Assistant) | https://carl.lab.mtgibbs.dev |
| MCP Homelab (Claude Code) | https://mcp.lab.mtgibbs.dev |
| Personal Website | https://site.lab.mtgibbs.dev |

### External Services (Reverse Proxy)
| Service | URL |
|---------|-----|
| Plex | https://plex.lab.mtgibbs.dev |
| Unifi Controller | https://unifi.lab.mtgibbs.dev |
| Synology NAS | https://nas.lab.mtgibbs.dev |

*Note: Services use trusted Let's Encrypt certificates. Requires `*.lab.mtgibbs.dev` DNS configured in Cloudflare.*

## Repository Structure

```
├── README.md                 # You are here
├── ARCHITECTURE.md           # Detailed architecture documentation
├── CLAUDE.md                 # Development context and routing instructions
├── clusters/
│   └── pi-k3s/
│       ├── flux-system/              # Flux bootstrap and orchestration
│       │   └── infrastructure.yaml   # Kustomizations with dependencies
│       │
│       │   # Core Infrastructure
│       ├── external-secrets/         # ESO Helm release
│       ├── external-secrets-config/  # ClusterSecretStore for 1Password
│       ├── ingress/                  # nginx-ingress HelmRelease
│       ├── cert-manager/             # cert-manager HelmRelease
│       ├── cert-manager-config/      # ClusterIssuers (Let's Encrypt) + Cloudflare secret
│       │
│       │   # DNS & VPN
│       ├── pihole/                   # Pi-hole + Unbound + exporter + ingress
│       ├── tailscale/                # Tailscale operator for VPN
│       ├── tailscale-config/         # Exit node + subnet routes
│       ├── cloudflare-tunnel/        # Cloudflare Tunnel for external access
│       ├── private-exit-node/        # Alternative WireGuard exit node
│       │
│       │   # Observability
│       ├── monitoring/               # kube-prometheus-stack + Grafana
│       ├── log-aggregation/          # Loki for log collection
│       ├── uptime-kuma/              # Status page + AutoKuma monitors
│       ├── homepage/                 # Homepage dashboard
│       │
│       │   # Media Services
│       ├── jellyfin/                 # Media server with NFS storage
│       ├── immich/                   # Photo management with NFS storage
│       ├── media/                    # *arr stack (Sonarr, Radarr, etc.)
│       │
│       │   # Applications
│       ├── n8n/                      # Workflow automation
│       ├── carl/                     # AI assistant
│       ├── ollama/                   # Local LLM inference
│       ├── mcp-homelab/              # Claude Code cluster integration
│       ├── calendar/                 # Calendar file server
│       ├── mtgibbs-site/             # Personal website with Flux auto-deploy
│       │
│       │   # Operations
│       ├── backup-jobs/              # PVC + PostgreSQL backups to NAS
│       ├── flux-notifications/       # Discord deployment notifications
│       └── external-services/        # Reverse proxies for external infrastructure
├── docs/
│   ├── flux-gitops.md                # Flux dependency chain reference
│   ├── known-issues.md               # Current known issues
│   ├── recaps/                       # Session recaps
│   └── plans/                        # Implementation plans
├── scripts/                          # Helper scripts
└── .claude/
    ├── agents/                       # Sub-agent prompts (cluster-ops, recap-architect)
    └── skills/                       # Modular knowledge base (11 expert skills)
```

## Pi Configuration

These steps were performed manually on the Raspberry Pi before deploying the cluster.

### 1. Enable cgroups (required for Kubernetes)

Edit `/boot/firmware/cmdline.txt` and append:
```
cgroup_memory=1 cgroup_enable=memory
```

Reboot after making this change.

### 2. Disable swap

Raspberry Pi OS uses zram for swap. Disable it:
```bash
sudo systemctl disable --now systemd-zram-setup@zram0.service
sudo systemctl mask systemd-zram-setup@zram0.service
```

### 3. Install K3s

```bash
curl -sfL https://get.k3s.io | sh -s - --disable=traefik
```

Traefik is disabled since we're using hostNetwork for Pi-hole (binds directly to port 53).

### 4. Configure kubeconfig for remote access

On the Pi:
```bash
sudo cat /etc/rancher/k3s/k3s.yaml
```

Copy to your workstation as `~/dev/pi-cluster/kubeconfig` and update the server address:
```yaml
server: https://pi-k3s.local:6443  # or use IP: https://192.168.1.55:6443
```

### 5. Configure static DNS for resilience

The Pi node needs DNS that doesn't depend on itself (for pulling images during Pi-hole restarts):

```bash
sudo nmcli con mod "Wired connection 1" ipv4.dns "1.1.1.1 8.8.8.8"
sudo nmcli con mod "Wired connection 1" ipv4.ignore-auto-dns yes
sudo nmcli con up "Wired connection 1"
```

Verify:
```bash
cat /etc/resolv.conf
# Should show 1.1.1.1 and 8.8.8.8, NOT 192.168.1.55
```

## 1Password Setup

### Create Service Account

1. Go to [1Password Developer Portal](https://developer.1password.com/)
2. Create a Service Account with access to your vault
3. Save the token securely

### Create the token secret in cluster

```bash
kubectl create namespace external-secrets
kubectl -n external-secrets create secret generic onepassword-service-account \
  --from-literal=token="<your-service-account-token>"
```

### Create 1Password items

Create items in your 1Password vault (`pi-cluster` vault) with these fields:

| Item | Field | Purpose |
|------|-------|---------|
| `pihole` | `password` | Pi-hole admin password |
| `grafana` | `admin-user`, `admin-password` | Grafana login credentials |
| `cloudflare` | `api-token` | Let's Encrypt DNS-01 challenge |

## Cloudflare Setup (for Let's Encrypt)

Let's Encrypt uses DNS-01 challenge via Cloudflare to issue trusted TLS certificates.

### 1. Create Cloudflare API Token

Go to https://dash.cloudflare.com/profile/api-tokens and create a token:
- **Permissions**: Zone → DNS → Edit
- **Zone Resources**: Include → Specific zone → `mtgibbs.dev`

### 2. Create Wildcard DNS Record

In Cloudflare DNS for `mtgibbs.dev`, add:
- **Type**: A
- **Name**: `*.lab`
- **Content**: `192.168.1.55`
- **Proxy status**: OFF (DNS only, grey cloud)

This makes all `*.lab.mtgibbs.dev` subdomains resolve to the Pi.

### 3. Add Token to 1Password

Create a `cloudflare` item in the `pi-cluster` vault with an `api-token` field containing your API token.

### Troubleshooting Certificates

```bash
# Check ClusterIssuers are ready
kubectl get clusterissuers

# Check certificate status
kubectl get certificates -A

# Debug certificate issues
kubectl describe certificate grafana-tls -n monitoring
kubectl -n cert-manager logs deploy/cert-manager

# Verify certificate issuer (should show "Let's Encrypt")
curl -v https://grafana.lab.mtgibbs.dev 2>&1 | grep issuer
```

## Deployment

### Bootstrap Flux

```bash
# Install Flux CLI
brew install fluxcd/tap/flux

# Bootstrap (creates flux-system namespace and connects to GitHub)
flux bootstrap github \
  --owner=<your-github-username> \
  --repository=pi-cluster \
  --path=clusters/pi-k3s \
  --personal
```

### Verify deployment

```bash
export KUBECONFIG=~/dev/pi-cluster/kubeconfig

# Check Flux status
flux get all

# Check Pi-hole
kubectl -n pihole get pods
kubectl -n pihole logs deploy/pihole

# Test DNS (from a client machine, or install dnsutils on the Pi)
# On Mac/Linux with dig: dig @192.168.1.55 google.com
# On Pi: ping -c 1 google.com  # Verifies DNS resolution works
```

## Network Configuration

Configure your router's DHCP to distribute the Pi's IP as the DNS server:

| Setting | Value |
|---------|-------|
| Primary DNS | 192.168.1.55 |
| Secondary DNS | (none, or accept brief outages) |

**Note**: Adding a secondary public DNS (like 1.1.1.1) will cause clients to bypass Pi-hole when it's slow or restarting, allowing ads through.

## Operations

### Trigger Flux reconciliation

```bash
flux reconcile kustomization flux-system --with-source
```

### Restart Pi-hole

```bash
kubectl -n pihole rollout restart deployment/pihole
```

### Update adlists

Edit `clusters/pi-k3s/pihole/pihole-adlists-configmap.yaml`, commit, and push. Flux will update the ConfigMap. Restart the Pi-hole pod to apply new lists.

### Check blocked domains

```bash
kubectl -n pihole exec deploy/pihole -- pihole status
```

Or visit: http://192.168.1.55/admin

## Troubleshooting

### Pi-hole pod won't start
```bash
kubectl -n pihole describe pod -l app=pihole
kubectl -n pihole logs -l app=pihole --previous
```

### DNS not resolving
```bash
# Test Unbound directly (drill is in the container)
kubectl -n pihole exec deploy/unbound -- drill google.com @127.0.0.1 -p 5335

# Test Pi-hole from your Mac
# dig @192.168.1.55 google.com
```

### Secrets not syncing
```bash
kubectl get externalsecrets -A
kubectl describe externalsecret -n pihole pihole-secret
```

## Features Implemented

- [x] Observability stack (Prometheus, Grafana) - deployed via kube-prometheus-stack
- [x] Ingress controller with TLS (nginx-ingress + cert-manager)
- [x] Uptime Kuma status page with GitOps-managed monitors (AutoKuma)
- [x] Homepage dashboard - unified landing page with live service widgets
- [x] Multi-node cluster - 4 nodes (3x Pi 5, 1x Pi 3)
- [x] Automated backups - PVC snapshots + PostgreSQL dumps to Synology NAS
- [x] Discord notifications - Flux deployments + Alertmanager alerts
- [x] Media services - Jellyfin (streaming) + Immich (photos)
- [x] Comprehensive monitoring - Immich metrics, PrometheusRules, Discord alerts
- [x] Pi-hole HA - Dual Pi-hole instances for DNS redundancy
- [x] Tailscale VPN - Exit node with subnet routes for mobile ad blocking
- [x] Flux Image Automation - Auto-deploy personal website from GHCR
- [x] Modular knowledge base - 11 specialized skills for AI-assisted operations

## Future Enhancements

- [ ] Shared storage (migrate remaining workloads from local-path to NFS)
- [ ] Resource quotas and network policies
- [ ] Horizontal Pod Autoscaling (HPA)
- [ ] Automated ACL policy management for Tailscale (currently manual in admin console)

## License

MIT
