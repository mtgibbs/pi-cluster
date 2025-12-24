# Pi K3s Cluster

A production-grade Kubernetes homelab running on a Raspberry Pi 5, featuring GitOps, secrets management, and network-wide ad blocking.

## Overview

This project demonstrates enterprise-grade infrastructure practices on affordable hardware:

- **GitOps with Flux**: All configuration is declarative and version-controlled
- **Secrets Management**: 1Password integration via External Secrets Operator - no secrets in git
- **DNS Security**: Pi-hole for ad blocking + Unbound for recursive DNS resolution
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
- **Pi-hole**: Blocks ads, trackers, and malware domains
- **Unbound**: Full recursive resolution (no Cloudflare/Google dependency)
- **DNSSEC**: Validated by Unbound
- **Firebog curated lists**: 25+ blocklists, ~900k domains

## Hardware

| Component | Specification |
|-----------|---------------|
| Device | Raspberry Pi 5 |
| RAM | 8GB |
| Storage | microSD (local-path provisioner) |
| OS | Raspberry Pi OS Lite (64-bit) / Debian 13 |
| IP | 192.168.1.55 (static via DHCP reservation) |

## Stack

| Component | Version | Purpose |
|-----------|---------|---------|
| K3s | v1.33.6+k3s1 | Lightweight Kubernetes |
| Flux | v2.x | GitOps operator |
| External Secrets Operator | 1.2.0 | Secrets sync from 1Password |
| Pi-hole | latest | DNS-level ad blocking |
| Unbound | latest | Recursive DNS resolver |

## Repository Structure

```
├── README.md                 # You are here
├── ARCHITECTURE.md           # Detailed architecture documentation
├── CLAUDE.md                 # Development context and notes
├── clusters/
│   └── pi-k3s/
│       ├── flux-system/      # Flux bootstrap and orchestration
│       │   └── infrastructure.yaml
│       ├── external-secrets/ # ESO Helm release
│       ├── external-secrets-config/  # ClusterSecretStore
│       └── pihole/           # Pi-hole + Unbound manifests
│           ├── kustomization.yaml
│           ├── unbound-*.yaml
│           ├── pihole-*.yaml
│           └── external-secret.yaml
├── docs/
│   ├── external-secrets-1password-sdk.md
│   └── pihole-v6-api.md
└── scripts/                  # Helper scripts
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

Create items in your 1Password vault with these fields:
- `pihole` item with `password` field

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

## Future Improvements

- [x] Observability stack (Prometheus, Grafana) - deployed via kube-prometheus-stack
- [ ] Ingress controller with TLS (cert-manager)
- [ ] Additional workloads (Uptime Kuma, Homepage)
- [ ] Multi-node cluster (add another Pi)
- [ ] Automated backups
- [ ] Migrate Grafana secrets to ExternalSecret

## License

MIT
