# Pi K3s Cluster Project

## Project Goal

Build a learning Kubernetes cluster on a Raspberry Pi 5 to run Pi-hole + Unbound, with observability (Grafana/Prometheus), using proper IaC practices. Managed via GitOps (Flux) with secrets from 1Password.

## Current State

### Hardware & OS
- Raspberry Pi 5 (8GB RAM)
- Raspberry Pi OS Lite (64-bit)
- Hostname: `pi-k3s`
- Static IP: 192.168.1.55 (DHCP reservation)
- User: `mtgibbs`

### Completed Setup
1. **cgroups enabled** - Added `cgroup_memory=1 cgroup_enable=memory` to `/boot/firmware/cmdline.txt`
2. **Swap disabled** - Masked `systemd-zram-setup@zram0.service`
3. **k3s installed** - Version v1.33.6+k3s1, installed with `--disable=traefik`
4. **Flux GitOps** - Bootstrapped to GitHub repo, manages all workloads
5. **External Secrets Operator** - v1.2.0, syncs secrets from 1Password
6. **Pi-hole + Unbound** - Deployed via Flux with GitOps-managed secrets
7. **nginx-ingress** - Ingress controller with hostPort 443 (port 80 used by Pi-hole)
8. **cert-manager** - Self-signed CA for TLS certificates
9. **Uptime Kuma** - Status page for home services monitoring

### Checklist
- [x] Unbound deployment (recursive DNS resolver)
- [x] Pi-hole deployment with hostNetwork
- [x] Flux GitOps setup
- [x] 1Password + ESO secrets management
- [x] Observability stack (Prometheus, Grafana) - via kube-prometheus-stack
- [x] DNS resilience during upgrades (Pi uses static DNS: 1.1.1.1/8.8.8.8)
- [x] Pi-hole v6 API configuration (password, upstream DNS, adlists)
- [x] GitOps-managed adlists (Firebog curated, ~900k domains)
- [x] Ingress + TLS for web UIs (nginx-ingress + cert-manager with self-signed CA)
- [x] Uptime Kuma status page (subdomain-based routing)

### Service URLs
All services use subdomain-based routing via sslip.io (resolves to 192.168.1.55):
- **Grafana**: https://grafana.192-168-1-55.sslip.io
- **Uptime Kuma**: https://status.192-168-1-55.sslip.io
- **Pi-hole Admin**: http://192.168.1.55/admin/ (hostNetwork, no ingress)

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
│                              K3s Cluster                                    │
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
│   └── external-secrets-1password-sdk.md  # ESO reference
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
        │   └── cluster-issuer.yaml   # Self-signed CA ClusterIssuer
        ├── pihole/
        │   ├── kustomization.yaml
        │   ├── unbound-configmap.yaml
        │   ├── unbound-deployment.yaml
        │   ├── pihole-pvc.yaml
        │   ├── pihole-deployment.yaml
        │   ├── pihole-service.yaml
        │   ├── pihole-exporter.yaml
        │   └── external-secret.yaml   # Syncs password from 1Password
        ├── monitoring/
        │   ├── kustomization.yaml
        │   ├── helmrelease.yaml        # kube-prometheus-stack HelmRelease
        │   ├── ingress.yaml            # Grafana Ingress
        │   └── external-secret.yaml    # Grafana password from 1Password
        └── uptime-kuma/
            ├── kustomization.yaml
            ├── namespace.yaml
            ├── pvc.yaml
            ├── deployment.yaml
            ├── service.yaml
            └── ingress.yaml            # status.192-168-1-55.sslip.io
```

## Flux Dependency Chain

Kustomizations are applied in order via `dependsOn`:

```
1. external-secrets        → Installs ESO operator + CRDs
2. external-secrets-config → Creates ClusterSecretStore (needs CRDs)
3. ingress                 → nginx-ingress controller
4. cert-manager            → Installs cert-manager CRDs + controllers
5. cert-manager-config     → Creates ClusterIssuer (needs cert-manager CRDs)
6. pihole                  → Creates ExternalSecret + workloads (needs SecretStore)
7. monitoring              → kube-prometheus-stack + Grafana (needs secrets, ingress, certs)
8. uptime-kuma             → Status page (needs secrets, ingress, certs)
```

## Key Technical Details

### External Secrets Operator (ESO)
- Version: 1.2.0
- Provider: `onepasswordSDK` (uses service account, no Connect server)
- ClusterSecretStore: `onepassword` (cluster-wide, references `pi-cluster` vault)
- ExternalSecret: Creates K8s secrets from 1Password items
- Key format: `item/field` (e.g., `pihole/password`)

### 1Password Setup
- Vault: `pi-cluster` (contains `pihole`, `grafana` items)
- Service Account: `pi-cluster-operator` (token in Development - Private vault)
- K8s Secret: `onepassword-service-account` in `external-secrets` namespace
- Bootstrap: Service account token must be created manually before Flux sync

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

### cert-manager Config
- Self-signed CA ClusterIssuer: `pi-cluster-ca-issuer`
- Auto-generates TLS certificates for Ingress resources
- Certificates are stored as K8s secrets (e.g., `grafana-tls`, `uptime-kuma-tls`)

### Uptime Kuma Config
- Version 2.x
- Status page for monitoring home services
- URL: https://status.192-168-1-55.sslip.io
- Data persisted to PVC (2Gi, local-path storage)
- Monitors configured manually via web UI (uptime-kuma-api library has v2 compatibility issues)

### sslip.io DNS Pattern
Services use subdomain-based routing via sslip.io:
- `*.192-168-1-55.sslip.io` resolves to `192.168.1.55`
- Allows wildcard DNS without custom DNS server configuration
- Future migration: Can switch to custom domain by updating Ingress hosts

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

## Future Additions (Backlog)

- **Homepage dashboard** - Unified dashboard for all services
- **Multi-node** - Add another Pi for HA learning
- **GitOps monitor configuration** - Automated Uptime Kuma monitor setup when library supports v2
