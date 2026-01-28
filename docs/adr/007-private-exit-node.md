# ADR-007: Private Exit Node Architecture

## Status
Accepted

## Date
2026-01-28

## Context

We need the ability to route all home LAN traffic through a VPN exit point in another country on-demand. Use cases include:
- Privacy from local ISP during sensitive browsing
- Accessing geo-restricted content
- Emergency bypass if ISP implements traffic inspection/blocking

Requirements:
- Must be dormant by default (no ongoing cost when inactive)
- Single-command activation/deactivation
- Traffic must not be identifiable as VPN traffic (DPI resistance)
- Fully automated provisioning (IaC)
- Integrate with existing GitOps workflow

## Decision

### VPN Protocol: WireGuard

**Chosen over**: OpenVPN, IPsec

**Rationale**:
- Minimal attack surface (~4,000 lines of code vs 100,000+ for OpenVPN)
- Modern cryptography (ChaCha20, Curve25519, BLAKE2)
- Excellent performance on Raspberry Pi ARM64
- Simple configuration (single config file)
- Built into Linux kernel (no userspace daemon overhead)

**Trade-off**: WireGuard uses UDP which is easily fingerprinted. Mitigated by obfuscation layer (see below).

### Obfuscation: Shadowsocks (Primary) + wstunnel (Fallback)

**Chosen over**: obfs4, Tor, plain WireGuard

**Primary - shadowsocks-rust with AEAD-2022**:
- Modern AEAD-2022 cipher (2022-blake3-aes-256-gcm) resistant to probing attacks
- `udp_over_tcp` encapsulates WireGuard UDP inside the Shadowsocks TCP stream
- Traffic appears as generic TLS on port 443
- Battle-tested against sophisticated DPI (Chinese GFW)
- Active development, Rust implementation is memory-safe

**Fallback - wstunnel**:
- Pure WebSocket over TLS on port 8443
- Indistinguishable from legitimate HTTPS WebSocket traffic
- Useful if Shadowsocks gets blocked (different traffic signature)
- Self-signed TLS certificate (doesn't matter since we control both ends)

**Why both**: Different obfuscation techniques have different signatures. If one gets blocked, switch to the other via environment variable.

### VPS Provider: Hetzner

**Chosen over**: AWS, DigitalOcean, Linode, Vultr

**Rationale**:
- European company (German jurisdiction, strong privacy laws)
- Excellent price/performance (CX23: €3.49/month for 2 vCPU, 4GB RAM)
- Good network connectivity to US
- No bandwidth overage charges (20TB included)
- Simple API for Terraform provisioning

**Location**: Nuremberg (nbg1) datacenter
- Germany provides GDPR jurisdiction
- Good peering to transatlantic cables
- ~80-100ms latency from US East Coast

### Architecture: Localhost WireGuard Endpoint

**Key insight**: WireGuard on VPS listens on `127.0.0.1:51820` (localhost only), not on a public port.

**Why this matters**:
- No public UDP port to probe or fingerprint
- External observers only see TCP connections to ports 443/8443
- The only way to reach WireGuard is through the obfuscation tunnel

**Traffic flow**:
```
Pi → sslocal (127.0.0.1:51820 UDP) → [Shadowsocks TCP] → VPS:443
                                                           ↓
VPS:443 → ssserver → 127.0.0.1:51820 → WireGuard server → Internet
```

### Routing: Policy-Based with fwmark

**Problem**: If we add a default route via wg0, the Shadowsocks TCP connection to the VPS would also route through wg0 → infinite loop.

**Solution**: Only route forwarded LAN traffic through the VPN using fwmark-based policy routing:

```bash
# Mark forwarded traffic from LAN
iptables -t mangle -A PREROUTING -s 192.168.1.0/24 -j MARK --set-mark 100

# Route marked traffic through WireGuard
ip rule add fwmark 100 table 100
ip route add default via 10.66.66.1 dev wg0 table 100
```

**Benefits**:
- Host's own traffic (cluster operations, SSH, etc.) uses normal route
- Only explicitly forwarded LAN traffic goes through VPN
- No routing loops

### Container Approach: Manual WireGuard Setup

**Problem**: `wg-quick` tries to write to `/proc/sys/net/ipv4/conf/all/src_valid_mark` which fails in containers (read-only sysfs).

**Solution**: Replace `wg-quick` with manual commands:
```bash
ip link add wg0 type wireguard
wg set wg0 private-key /tmp/key peer $PUBKEY endpoint 127.0.0.1:51820 allowed-ips 0.0.0.0/0
ip addr add 10.66.66.2/24 dev wg0
ip link set wg0 up
```

**Benefits**:
- Works with only NET_ADMIN capability (no privileged mode)
- More control over what actually gets configured
- Avoids sysctl that's unnecessary for our use case

### Secret Management: Terraform → 1Password (Manual) → ESO

**Flow**:
1. Terraform generates WireGuard keys + Shadowsocks password
2. Terraform outputs secrets (sensitive)
3. User manually creates 1Password item from outputs
4. ExternalSecrets Operator syncs to Kubernetes

**Why manual 1Password step** (vs Terraform writing directly):
- Keeps 1Password vault read-only for all service accounts
- No write credentials to leak
- One-time operation, not ongoing automation need
- Explicit control over what enters the vault

### Image Registry: Private GHCR

**Decision**: Keep container image private despite containing only open-source tools.

**Rationale**:
- Reduces visibility of exit node infrastructure
- Image name/tags don't leak operational details
- Defense in depth (obscurity as one layer)

**Trade-off**: Requires GitHub classic PAT with `read:packages` for cluster pulls. Fine-grained tokens don't support packages (as of 2026).

### Activation: Kubernetes Scale + USG Route

**Cluster side**: `kubectl scale deployment ... --replicas=1`
- Dormant at replicas=0 (zero resource usage)
- Single command activation
- ConfigMap entrypoint means no image rebuild for config changes

**Network side**: USG static route pointing 0.0.0.0/0 → 192.168.1.55
- Instant effect (no DHCP renewal)
- Affects all LAN devices automatically
- Easy to remove in emergency

### DNS: Not Tunneled

**Decision**: Pi-hole → Unbound continues to work directly, DNS is not routed through the VPN.

**Rationale**:
- DNS blocking/filtering is not the threat model we're addressing
- Keeps Pi-hole functioning normally for ad blocking
- Reduces latency for DNS queries
- If DNS privacy is needed, can configure Pi-hole to use DoH/DoT

## Consequences

### Positive
- Complete DPI resistance (traffic looks like HTTPS)
- Fully automated provisioning and deployment
- Single-command activate/deactivate
- Zero ongoing cost when dormant
- Keys generated automatically, no manual crypto
- Integrates with existing GitOps and secrets management

### Negative
- Added latency (~80-100ms) for all LAN traffic when active
- VPS has ongoing cost (~€3.50/month) even when tunnel is dormant
- Requires classic GitHub PAT (legacy auth method)
- Manual 1Password item creation (one-time)

### Risks
- Hetzner could be compelled to log traffic (mitigated: encrypt everything, short sessions)
- VPS IP could get blocked (mitigated: terraform destroy/apply for new IP)
- Shadowsocks signature could be detected (mitigated: wstunnel fallback)

## Alternatives Considered

### Tailscale Exit Node
- Pro: Already deployed, single binary
- Con: Traffic identified as Tailscale/WireGuard, no obfuscation
- Con: Tailscale sees traffic metadata

### Commercial VPN
- Pro: No infrastructure to manage
- Con: Trust third party with all traffic
- Con: No control over exit location or logging policy
- Con: Monthly subscription regardless of usage

### Tor
- Pro: Strong anonymity
- Con: Very slow for general browsing
- Con: Many sites block Tor exit nodes
- Con: Overkill for privacy-from-ISP use case
