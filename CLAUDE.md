# Pi K3s Cluster Project

## Project Goal

Build a learning Kubernetes cluster on a Raspberry Pi 5 to run Pi-hole + Unbound, with observability (Grafana/Prometheus), using proper IaC practices. The setup should be maintainable long-term and eventually managed via GitOps (Flux).

## Current State

### Hardware & OS
- Raspberry Pi 5 (8GB RAM)
- Raspberry Pi OS Lite (64-bit)
- Hostname: `pi-k3s`
- Static IP assigned via router DHCP reservation
- User: `mtgibbs`

### Completed Setup
1. **cgroups enabled** - Added `cgroup_memory=1 cgroup_enable=memory` to `/boot/firmware/cmdline.txt`
2. **Swap disabled** - Masked `systemd-zram-setup@zram0.service` (Pi OS uses zram, not dphys-swapfile)
3. **k3s installed** - Version v1.33.6+k3s1, installed with `--disable=traefik`
4. **kubectl configured** - Config at `~/.kube/config`, `KUBECONFIG` exported in `~/.bashrc`
5. **Namespace created** - `pihole` namespace exists
6. **Repo structure started**:
   ```
   ~/pi-cluster/
   ├── README.md
   └── clusters/
       └── pi-k3s/
           ├── pihole/        # Manifests go here
           └── flux-system/   # Empty, for later GitOps
   ```

### Completed
- [x] Unbound deployment (recursive DNS resolver) - `madnuttah/unbound:latest`
- [x] Pi-hole deployment - `pihole/pihole:latest` with hostNetwork

### Not Yet Done
- [ ] Secrets management (Sealed Secrets or SOPS for GitOps)
- [ ] Observability stack (Prometheus, Grafana, Loki)
- [ ] Flux GitOps setup

## Architecture

```
User Device → Pi-hole (ad filtering) → Unbound (recursive DNS) → Root/TLD/Authoritative servers
```

**Why Unbound?** Instead of forwarding DNS to Cloudflare/Google, Unbound does full recursive resolution by talking directly to authoritative DNS servers. Better privacy (no single upstream sees all queries), no third-party trust required, DNSSEC validation.

## Manifest Structure for Pi-hole + Unbound

All manifests go in `~/pi-cluster/clusters/pi-k3s/pihole/`. Files to create:

### Unbound
1. `unbound-configmap.yaml` - Unbound configuration (server settings, access control, caching)
2. `unbound-deployment.yaml` - Deployment + ClusterIP Service

### Pi-hole
3. `pihole-pvc.yaml` - PersistentVolumeClaims for `/etc/pihole` and `/etc/dnsmasq.d`
4. `pihole-secret.yaml` - Web admin password (generate with `kubectl create secret`)
5. `pihole-deployment.yaml` - Deployment with env vars, volume mounts, probes
6. `pihole-service.yaml` - ClusterIP for web UI, LoadBalancer for DNS (port 53)

### Optional
7. `kustomization.yaml` - For `kubectl apply -k` convenience

## Key Technical Details

### Unbound Config Notes
- Runs on port 5335 (non-privileged)
- Access control allows RFC1918 ranges (10.x, 172.16.x, 192.168.x)
- Pi-hole references it via k8s DNS: `unbound.pihole.svc.cluster.local#5335`

### Pi-hole Config Notes
- `PIHOLE_DNS_` env var points to Unbound service
- `DNSSEC=false` because Unbound handles DNSSEC
- Strategy: `Recreate` (not RollingUpdate) because PVCs are ReadWriteOnce
- Uses `hostNetwork: true` to bind directly to port 53 (LoadBalancer had iptables-nft issues)
- Password set via `pihole setpassword` command (env var unreliable in v6+)

### Secrets Management
- `pihole-secret.yaml` is in `.gitignore` - DO NOT commit secrets to git
- Secret must be created manually: `kubectl -n pihole create secret generic pihole-secret --from-literal=WEBPASSWORD=<password>`
- For GitOps: implement Sealed Secrets or SOPS before adding Flux

### k3s Specifics
- Default storage class: `local-path` (provisions PVs automatically)
- No Traefik installed (disabled at install)
- ServiceLB (formerly Klipper) handles LoadBalancer services using host ports

## Commands Reference

```bash
# Use local kubeconfig (from Mac)
export KUBECONFIG=~/dev/pi-cluster/kubeconfig

# Check cluster
kubectl get nodes
kubectl get pods -A

# Apply manifests
kubectl apply -f <file.yaml>
kubectl apply -k clusters/pi-k3s/pihole/  # if using kustomization

# Debug
kubectl -n pihole get pods
kubectl -n pihole describe pod <name>
kubectl -n pihole logs <pod-name>

# Test DNS
dig @192.168.1.55 google.com

# Set Pi-hole password
kubectl -n pihole exec deploy/pihole -- pihole setpassword '<password>'

# SSH to Pi (if needed)
ssh mtgibbs@pi-k3s.local
```

## Next Steps

1. ~~Create Unbound manifests~~ Done
2. ~~Create Pi-hole manifests~~ Done
3. ~~Apply and test~~ Done
4. Point router/devices to Pi (192.168.1.55) for DNS
5. Set up secrets management (Sealed Secrets or SOPS)
6. Add observability stack
7. Set up Flux for GitOps

## Future Additions (Backlog)

- **Observability**: Prometheus, Grafana, Loki (via kube-prometheus-stack Helm chart)
- **GitOps**: Flux watching this repo, auto-sync on push
- **Ingress**: Traefik or nginx-ingress + cert-manager for TLS
- **Additional workloads**: Uptime Kuma, Gitea, Homepage dashboard
- **Multi-node**: Add another Pi, learn scheduling/affinity/taints
