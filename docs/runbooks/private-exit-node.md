# Private Exit Node Runbook

Whole-network VPN gateway that routes all LAN traffic through a Hetzner VPS in Germany via obfuscated tunnels. Dormant by default (`replicas: 0`), activated with a single command.

## Architecture

```
LAN Device (192.168.1.x)
    |  Gateway: 192.168.1.55 (via USG static route)
    v
pi-k3s (192.168.1.55) -- gateway pod (hostNetwork, NET_ADMIN)
    |
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

Hetzner VPS (Germany, CX22)
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
- 1Password service account token (same one used by ESO in the cluster)
- SSH key pair for VPS management access
- `ghcr.io/mtgibbs/exit-node-gateway:latest` container image built and pushed

## Repos

| Repo | Purpose |
|------|---------|
| `private-exit-node` | Hetzner VPS provisioning + secret generation (Terraform) |
| `pi-cluster` | Gateway pod on K3s cluster (Flux GitOps) |

## Initial Deployment

### 1. Provision VPS (Terraform)

```bash
cd private-exit-node

# Set required env vars
export HCLOUD_TOKEN="<hetzner-api-token>"
export OP_SERVICE_ACCOUNT_TOKEN="<1password-service-account-token>"

# Initialize and apply
terraform init
terraform plan -var 'ssh_public_key=ssh-ed25519 AAAA...'
terraform apply -var 'ssh_public_key=ssh-ed25519 AAAA...'

# Verify outputs
terraform output
```

This creates:
- Hetzner VPS with WireGuard, Shadowsocks, and wstunnel
- WireGuard keypairs and Shadowsocks password
- 1Password item `private-exit-node` with all secrets

### 2. Verify VPS

```bash
VPS_IP=$(terraform output -raw vps_ip)

# SSH to VPS and check services
ssh root@$VPS_IP

# On the VPS:
wg show                  # WireGuard interface should be up (no handshake yet)
ss -tlnp | grep 443     # Shadowsocks listening
ss -tlnp | grep 8443    # wstunnel listening
systemctl status wg-quick@wg0
systemctl status shadowsocks-server
systemctl status wstunnel-server
```

### 3. Deploy to Cluster (GitOps)

The pi-cluster manifests are already committed. Flux will sync automatically, or force it:

```bash
flux reconcile source git flux-system
flux reconcile kustomization private-exit-node
```

### 4. Verify ExternalSecret

```bash
kubectl get externalsecret -n private-exit-node
# Should show "SecretSynced" condition
kubectl get secret exit-node-secrets -n private-exit-node
# Should exist with 4 keys
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

```bash
# Switch to wstunnel (WebSocket fallback)
kubectl set env deployment/exit-node-gateway -n private-exit-node TUNNEL_MODE=wstunnel

# Switch back to Shadowsocks (primary)
kubectl set env deployment/exit-node-gateway -n private-exit-node TUNNEL_MODE=shadowsocks
```

The deployment will automatically restart with the new tunnel mode.

## Verification Checklist

| Check | Command | Expected |
|-------|---------|----------|
| Pod running | `kubectl get pods -n private-exit-node` | 1/1 Running |
| WireGuard up | `kubectl exec -n private-exit-node deploy/exit-node-gateway -- wg show` | Handshake recent |
| Exit IP | `kubectl exec -n private-exit-node deploy/exit-node-gateway -- curl -s https://ifconfig.me` | Hetzner VPS IP |
| NAT rules | `kubectl exec -n private-exit-node deploy/exit-node-gateway -- iptables -t nat -L POSTROUTING` | MASQUERADE on wg0 |
| LAN egress | From laptop: `curl https://ifconfig.me` | Hetzner VPS IP (after USG route) |
| DNS works | `dig @192.168.1.55 google.com` | Resolves (Pi-hole unaffected) |
| Secret synced | `kubectl get externalsecret -n private-exit-node` | SecretSynced |

## Troubleshooting

### Pod won't start
```bash
kubectl describe pod -n private-exit-node -l app=exit-node-gateway
kubectl logs -n private-exit-node -l app=exit-node-gateway
```

### No WireGuard handshake
```bash
# Check tunnel is running
kubectl exec -n private-exit-node deploy/exit-node-gateway -- ps aux | grep -E 'sslocal|wstunnel'

# Check WireGuard status
kubectl exec -n private-exit-node deploy/exit-node-gateway -- wg show

# Test SS connectivity manually
kubectl exec -n private-exit-node deploy/exit-node-gateway -- curl -v https://$VPS_IP:443
```

### NAT not working
```bash
# Check iptables rules
kubectl exec -n private-exit-node deploy/exit-node-gateway -- iptables -t nat -L -v

# Check IP forwarding
kubectl exec -n private-exit-node deploy/exit-node-gateway -- sysctl net.ipv4.ip_forward

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

## What Changes

- **All LAN egress**: Routes through Germany when active (USG route in place).
- **Latency**: Added ~30-50ms for transatlantic hop.
- **IP geolocation**: Shows German IP for external services.

## VPS Rebuild (If Compromised)

```bash
cd private-exit-node

# Destroy existing VPS
terraform destroy -var 'ssh_public_key=ssh-ed25519 AAAA...'

# Recreate with fresh IP, same keys
terraform apply -var 'ssh_public_key=ssh-ed25519 AAAA...'

# No cluster-side changes needed - secrets in 1Password remain the same
# (WireGuard keys and SS password are generated once and stored in 1Password)
```

To rotate keys as well, delete the 1Password item first, then `terraform apply` will regenerate everything.

## Secrets

All secrets are managed via Terraform -> 1Password -> ExternalSecrets:

| Field | Source | Description |
|-------|--------|-------------|
| `wg-private-key` | Terraform `wireguard_asymmetric_key.pi` | Pi's WireGuard private key |
| `wg-peer-public-key` | Terraform `wireguard_asymmetric_key.vps` | VPS's WireGuard public key |
| `ss-password` | Terraform `random_id` (base64, 32 bytes) | Shared Shadowsocks AEAD-2022 key |
| `vps-ip` | Terraform `hcloud_server` | Hetzner VPS public IPv4 |
