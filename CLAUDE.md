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

### Checklist
- [x] Unbound deployment (recursive DNS resolver)
- [x] Pi-hole deployment with hostNetwork
- [x] Flux GitOps setup
- [x] 1Password + ESO secrets management
- [x] Observability stack (Prometheus, Grafana) - via kube-prometheus-stack
- [ ] DNS resilience during upgrades (Pi uses itself for DNS)
- [ ] Ingress + TLS for web UIs

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
        ├── pihole/
        │   ├── kustomization.yaml
        │   ├── unbound-configmap.yaml
        │   ├── unbound-deployment.yaml
        │   ├── pihole-pvc.yaml
        │   ├── pihole-deployment.yaml
        │   ├── pihole-service.yaml
        │   ├── pihole-exporter.yaml
        │   └── external-secret.yaml   # Syncs password from 1Password
        └── monitoring/
            └── kube-prometheus-values.yaml.tpl
```

## Flux Dependency Chain

Kustomizations are applied in order via `dependsOn`:

```
1. external-secrets       → Installs ESO operator + CRDs
2. external-secrets-config → Creates ClusterSecretStore (needs CRDs)
3. pihole                  → Creates ExternalSecret + workloads (needs SecretStore)
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
- Upstream DNS: Unbound at `unbound.pihole.svc.cluster.local#5335`
- DNSSEC disabled (Unbound handles it)

### Unbound Config
- Port 5335 (non-privileged)
- Full recursive resolution
- DNSSEC validation enabled

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

# Test DNS
dig @192.168.1.55 google.com

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

### DNS Resilience
The Pi uses itself (192.168.1.55) for DNS resolution. During Pi-hole upgrades or if Pi-hole is down, the Pi cannot resolve DNS to pull new images. Workaround: temporarily add `8.8.8.8` to `/etc/resolv.conf` on the Pi.

### Monitoring Stack
kube-prometheus-stack is partially set up but still uses `op inject` for secrets. Should migrate to ExternalSecret for Grafana password.

## Future Additions (Backlog)

- **Grafana ExternalSecret** - Migrate from op inject to ESO
- **Ingress + TLS** - nginx-ingress + cert-manager
- **Additional workloads** - Uptime Kuma, Homepage dashboard
- **Multi-node** - Add another Pi for HA learning
