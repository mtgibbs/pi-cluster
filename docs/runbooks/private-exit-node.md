# Private Exit Node Runbook

Whole-network VPN gateway that routes all LAN traffic through a Hetzner VPS in Germany via obfuscated tunnels. Dormant by default (`replicas: 0`), activated with a single command.

## Architecture

```
LAN Device (192.168.1.x)
    |  Gateway: 192.168.1.55 (via USG static route)
    v
pi-k3s (192.168.1.55) -- gateway pod (hostNetwork, NET_ADMIN)
    |
    +-- Policy routing (fwmark 100 -> table 100)
    +-- iptables NAT (MASQUERADE on wg0)
    +-- WireGuard client (wg0, 10.66.66.2/24)
    |      Endpoint: 127.0.0.1:51820
    |
    +--[PRIMARY] shadowsocks-rust ss-local
    |      tunnel mode, udp_over_tcp
    |      local UDP :51820 -> VPS:443 -> remote UDP :51820
    |
    +--[FALLBACK] wstunnel client
           UDP :51820 -> wss://VPS:8443 -> remote UDP :51820

         --- Internet (looks like HTTPS) ---

Hetzner VPS (Nuremberg, CX23)
    +-- shadowsocks-rust ss-server (:443)
    +-- wstunnel server (:8443)
    +-- WireGuard server (127.0.0.1:51820, localhost only)
    |      wg0: 10.66.66.1/24
    |      NAT MASQUERADE -> eth0 -> Internet
    +-- Firewall: only 443/tcp + 8443/tcp + 22/tcp exposed
```

## Prerequisites

- Hetzner Cloud account with API token
- Terraform >= 1.5 installed
- SSH key pair for VPS management access (can be generated in 1Password)
- GitHub classic PAT with `read:packages` scope for GHCR image pulls

## Repos

| Repo | Purpose |
|------|---------|
| `private-exit-node` | Hetzner VPS provisioning + container image (Terraform + Dockerfile) |
| `pi-cluster` | Gateway pod on K3s cluster (Flux GitOps) |

## Initial Deployment

### 1. Provision VPS (Terraform)

```bash
cd private-exit-node

# Set Hetzner API token (can read from 1Password)
export HCLOUD_TOKEN=$(op read "op://pi-cluster/hetzner-api-token/credential")

# Initialize and apply
terraform init
terraform plan -var 'ssh_public_key=ssh-ed25519 AAAA...'
terraform apply -var 'ssh_public_key=ssh-ed25519 AAAA...'
```

### 2. Create 1Password Secrets

Terraform outputs the secrets. Create a `private-exit-node` item in the `pi-cluster` vault manually:

```bash
# Get all outputs including sensitive values
terraform output -json

# Or create the 1Password item directly
op item create \
  --category=SecureNote \
  --title="private-exit-node" \
  --vault="pi-cluster" \
  "wg-private-key[password]=$(terraform output -raw onepassword_wg_private_key)" \
  "wg-peer-public-key[text]=$(terraform output -raw onepassword_wg_peer_public_key)" \
  "ss-password[password]=$(terraform output -raw onepassword_ss_password)" \
  "vps-ip[text]=$(terraform output -raw onepassword_vps_ip)"
```

### 3. Add GHCR Pull Token

Create a GitHub classic PAT with `read:packages` scope and store it:
- 1Password item: `ghcr-read-token` in `pi-cluster` vault
- Field: `token`

### 4. Verify VPS

```bash
VPS_IP=$(terraform output -raw vps_ip)

# SSH to VPS and check services
ssh root@$VPS_IP

# On the VPS:
wg show                  # WireGuard interface up (no handshake yet)
ss -tlnp | grep 443      # Shadowsocks listening
ss -tlnp | grep 8443     # wstunnel listening
systemctl status wg-quick@wg0
systemctl status shadowsocks-server
systemctl status wstunnel-server
```

### 5. Deploy to Cluster (GitOps)

The pi-cluster manifests are committed. Flux syncs automatically, or force it:

```bash
flux reconcile source git flux-system
flux reconcile kustomization private-exit-node
```

### 6. Verify ExternalSecrets

```bash
kubectl get externalsecret -n private-exit-node
# Both should show "SecretSynced":
#   exit-node-secrets     - WireGuard keys, SS password, VPS IP
#   ghcr-pull-secret      - Docker registry auth
```

## Activate

```bash
# 1. Scale up the gateway pod
kubectl scale deployment exit-node-gateway -n private-exit-node --replicas=1
kubectl wait --for=condition=available deployment/exit-node-gateway -n private-exit-node --timeout=120s

# 2. Verify tunnel is working
kubectl exec -n private-exit-node deploy/exit-node-gateway -- curl -s https://ifconfig.me
# Should show the Hetzner VPS IP

# 3. Add USG static route (Unifi Controller UI)
#    Settings > Routing & Firewall > Static Routes > Add:
#    Name: private-exit-node
#    Destination: 0.0.0.0/0
#    Next Hop: 192.168.1.55
#    Distance: 1
```

## Deactivate

```bash
# 1. Remove USG static route
#    Unifi UI > Settings > Routing & Firewall > Static Routes
#    Delete "private-exit-node" route

# 2. Scale down
kubectl scale deployment exit-node-gateway -n private-exit-node --replicas=0
```

## Switch Obfuscation Mode

Default is **wstunnel** (WebSocket over TLS on port 8443). Both modes are verified working.

```bash
# Switch to Shadowsocks (UDP relay on port 443)
kubectl set env deployment/exit-node-gateway -n private-exit-node TUNNEL_MODE=shadowsocks

# Switch back to wstunnel (default, WebSocket/TLS on port 8443)
kubectl set env deployment/exit-node-gateway -n private-exit-node TUNNEL_MODE=wstunnel
```

**Differences**:
- **wstunnel**: All traffic over TCP/TLS WebSocket. Indistinguishable from HTTPS. No UDP exposure.
- **Shadowsocks**: Uses UDP relay on port 443. AEAD-2022 encrypted, probe-resistant, but UDP:443 is an unusual traffic pattern that sophisticated DPI could flag.

The deployment automatically restarts with the new tunnel mode.

## Verification Checklist

| Check | Command | Expected |
|-------|---------|----------|
| Pod running | `kubectl get pods -n private-exit-node` | 1/1 Running |
| WireGuard up | `kubectl exec -n private-exit-node deploy/exit-node-gateway -- wg show` | Handshake recent |
| Exit IP | `kubectl exec -n private-exit-node deploy/exit-node-gateway -- curl -s https://ifconfig.me` | Hetzner VPS IP |
| NAT rules | `kubectl exec -n private-exit-node deploy/exit-node-gateway -- iptables -t nat -L POSTROUTING` | MASQUERADE on wg0 |
| Policy routing | `kubectl exec -n private-exit-node deploy/exit-node-gateway -- ip rule show` | fwmark 100 -> table 100 |
| LAN egress | From laptop: `curl https://ifconfig.me` | Hetzner VPS IP (after USG route) |
| DNS works | `dig @192.168.1.55 google.com` | Resolves (Pi-hole unaffected) |
| Secrets synced | `kubectl get externalsecret -n private-exit-node` | Both SecretSynced |

## Troubleshooting

### Pod won't start
```bash
kubectl describe pod -n private-exit-node -l app=exit-node-gateway
kubectl logs -n private-exit-node -l app=exit-node-gateway
```

### ImagePullBackOff
The GHCR package is private. Verify the pull secret:
```bash
kubectl get secret ghcr-pull-secret -n private-exit-node -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d
```

### No WireGuard handshake
```bash
# Check tunnel process is running
kubectl exec -n private-exit-node deploy/exit-node-gateway -- ps aux | grep -E 'sslocal|wstunnel'

# Check WireGuard status
kubectl exec -n private-exit-node deploy/exit-node-gateway -- wg show

# Test connectivity to VPS
kubectl exec -n private-exit-node deploy/exit-node-gateway -- curl -v --max-time 5 https://$VPS_IP:443
```

### NAT not working
```bash
# Check iptables rules
kubectl exec -n private-exit-node deploy/exit-node-gateway -- iptables -t nat -L -v
kubectl exec -n private-exit-node deploy/exit-node-gateway -- iptables -t mangle -L -v

# Check policy routing
kubectl exec -n private-exit-node deploy/exit-node-gateway -- ip rule show
kubectl exec -n private-exit-node deploy/exit-node-gateway -- ip route show table 100

# Check IPv6 is blocked
kubectl exec -n private-exit-node deploy/exit-node-gateway -- ip6tables -L FORWARD
```

### VPS services down
```bash
VPS_IP=$(cd private-exit-node && terraform output -raw vps_ip)
ssh root@$VPS_IP

systemctl status wg-quick@wg0
systemctl status shadowsocks-server
systemctl status wstunnel-server
journalctl -u shadowsocks-server --no-pager -n 50
journalctl -u wstunnel-server --no-pager -n 50
```

## What Still Works

- **Pi-hole DNS**: Pi-hole -> Unbound (recursive) still works directly. DNS is not tunneled.
- **Cluster-internal traffic**: Pod-to-pod and service communication is unaffected.
- **Tailscale**: Continues to work independently.
- **Host traffic**: The pi-k3s node's own traffic (not forwarded LAN traffic) uses the normal route.

## What Changes

- **LAN egress**: Forwarded traffic from 192.168.1.0/24 routes through Germany when active.
- **Latency**: Added ~80-100ms for transatlantic hop.
- **IP geolocation**: Shows German IP for external services.

## VPS Rebuild (If Compromised)

```bash
cd private-exit-node

# Destroy existing VPS
terraform destroy -var 'ssh_public_key=ssh-ed25519 AAAA...'

# Recreate with fresh IP
terraform apply -var 'ssh_public_key=ssh-ed25519 AAAA...'

# Update VPS IP in 1Password (or recreate the item)
op item edit private-exit-node --vault=pi-cluster \
  "vps-ip[text]=$(terraform output -raw onepassword_vps_ip)"
```

To rotate ALL keys (WireGuard + Shadowsocks), delete the 1Password item first, then recreate from new Terraform outputs.

## Secrets

| 1Password Item | Field | Description |
|----------------|-------|-------------|
| `private-exit-node` | `wg-private-key` | Pi's WireGuard private key |
| `private-exit-node` | `wg-peer-public-key` | VPS's WireGuard public key |
| `private-exit-node` | `ss-password` | Shared Shadowsocks AEAD-2022 key (base64, 32 bytes) |
| `private-exit-node` | `vps-ip` | Hetzner VPS public IPv4 |
| `ghcr-read-token` | `token` | GitHub PAT for private GHCR pulls |
| `hetzner-api-token` | `credential` | Hetzner Cloud API token |

## Container Image

- **Registry**: `ghcr.io/mtgibbs/private-exit-node`
- **Versioning**: Semver via release-please, Flux image automation updates deployment
- **Multi-arch**: linux/amd64, linux/arm64
- **Contents**: Alpine + wireguard-tools + shadowsocks-rust (sslocal) + wstunnel + iptables

## Known Issues

### Shadowsocks `udp_over_tcp` not supported in official sslocal

**Status**: Fixed

The `"udp_over_tcp": true` config field is a proprietary SagerNet protocol not implemented in official shadowsocks-rust. The field was silently ignored, and sslocal defaulted to `tcp_only` server mode, producing the warning:
```
WARN no valid UDP server serving for UDP clients
```

**Fix**: Removed `"udp_over_tcp": true` from both client and server configs. Added `"mode": "tcp_and_udp"` at the client config top level so sslocal uses standard Shadowsocks UDP relay. Added `443/udp` to both Hetzner cloud firewall (Terraform) and VPS UFW.

### hostNetwork cleanup on restart

**Status**: Fixed

With `hostNetwork: true`, the WireGuard interface and iptables/routing rules persist on the host between container restarts. The entrypoint script now includes cleanup logic that runs before setup to remove stale state.
