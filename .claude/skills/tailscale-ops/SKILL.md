---
name: tailscale-ops
description: Expert knowledge for Tailscale VPN operations. Use when configuring remote access, exit nodes, ACL policies, or troubleshooting VPN connectivity.
allowed-tools: Bash, Read, Grep, Glob, Edit, Write
---

# Tailscale Operations

## Purpose
Mobile ad blocking via Pi-hole exit node and remote access without opening router ports.

## Architecture
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

## Configuration

### Components
- **Namespace**: `tailscale`
- **Operator**: `tailscale-operator` (HelmRelease)
- **Exit Node**: `Connector` resource named `pi-cluster-exit`
- **ProxyClass**: Enforces `nodeSelector: arm64` (Pi 5)

### OAuth Client (Critical)
The Operator requires an OAuth client with **minimal scopes**. Extra scopes cause "requested tags are invalid" errors.

| Setting | Value |
|---------|-------|
| **Devices Core** | Read + Write |
| **Auth Keys** | Read + Write |
| **Tags** | `tag:k8s-operator` (ONLY) |
| **Other Scopes** | NONE |

### ACL Policy (JSON)
You must grant access to the advertised routes in the Tailscale admin console.

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
    ]
}
```
**Why grants are needed:**
1.  `autogroup:internet`: Allows traffic through the Exit Node.
2.  `192.168.1.0/24`: Allows access to the advertised Subnet Routes (Pi-hole IPs).

## Setup & Maintenance

### Creating Secrets
1.  Create OAuth client in Tailscale Admin.
2.  Create 1Password item `tailscale` with `oauth-client-id` and `oauth-client-secret`.
3.  ExternalSecret syncs this to `tailscale-oauth` in `tailscale` namespace.

### DNS Settings (Tailscale Admin)
For ad-blocking to work remotely:
1.  **Nameservers**: Add `192.168.1.55` and `192.168.1.56`.
2.  **Override Local DNS**: Enabled.
3.  **Use with Exit Node**: Enabled.

## Remote Ops (deploy / diagnose the lab from off-net)

**The gap (learned 2026-06-04, fixed 2026-06-06):** member devices (laptop,
`autogroup:member`) only get the `192.168.1.55/.56` Pi-hole `/32`s advertised —
**not** the full home `/24`. So anything addressed by a LAN IP other than those two
(e.g. the Beelink at `192.168.1.70`) is **unrouted over Tailscale**. Off-net, only
ICMP + SSH to the tailnet `100.x` IPs work; service ports (`:443` Caddy, `:6443`
k8s API) return `000` because `autogroup:member` has no grant to `tag:inference`.

**Rule: address cross-site ops by the tailnet, never the LAN IP.** Use the MagicDNS
name (stable across IP changes) or the `100.x` literal.

- **Tailnet domain (MagicDNS suffix):** `tailf8d786.ts.net`.
- **Beelink:** `beelink-ai.tailf8d786.ts.net` → `100.123.94.31`, `tag:inference`.
- **`get_tailscale_status` (MCP) reports `ready:false` even when healthy** — trust
  `tailscale status` / `kubectl describe connector` instead.

### Ansible deploys to the Beelink
The `beelink-ansible` inventory pins `ansible_host: beelink-ai.tailf8d786.ts.net`,
so `ansible-playbook … -l inference` connects over the tailnet from **anywhere**
with **no `-e ansible_host=` override**. Requires Tailscale **up** on the control
machine (there is no bare-LAN `.70` fallback by design). On-LAN, Tailscale still
prefers a direct path, so home deploys stay fast. (First use of a new MagicDNS
hostname needs its key in `known_hosts`; it presents the same host key as the IP.)

### Break-glass: reach a host's internal Docker services from off-net
Ollama (`:11434`) and LiteLLM (`:4000`) are **Docker-internal by design — never
host-expose them.** To hit them remotely, tunnel through SSH to the tailnet IP, then
address the container on the Docker network:
```bash
ssh mtgibbs@100.123.94.31           # tailnet IP (or MagicDNS name)
#  on-box, find the container IP:
docker inspect <ctr> | grep IPAddress
curl http://172.18.0.5:11434/...    # e.g. Ollama on the bridge network
```
The Caddy `:443` front door (`https://ai.lab.mtgibbs.dev`) is the *intended* remote
path, but needs the Phase-2 `autogroup:member → tag:inference` grant (below) first.

> Spec & verify gate for this work: `specs/remote-ops-access/`.

## Troubleshooting

### Verification Commands
```bash
# Check operator status
kubectl get pods -n tailscale

# Check exit node status
kubectl get connector pi-cluster-exit -n tailscale
kubectl describe connector pi-cluster-exit -n tailscale
```

### Common Issues
*   **"Requested tags are invalid"**: You added extra scopes to the OAuth client. Recreate it with ONLY Devices Core + Auth Keys.
*   **Exit node not in app**: Missing `autogroup:internet` grant in ACL.
*   **DNS not resolving**: Missing `192.168.1.0/24` grant in ACL or routes not approved in Admin Console.
