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
