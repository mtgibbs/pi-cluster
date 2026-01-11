# Session Recap - 2026-01-11: Tailscale VPN for Mobile Ad Blocking

## Summary

Successfully deployed Tailscale VPN with exit node functionality to enable mobile ad blocking via Pi-hole while away from home. Resolved critical DNS resolution issues by implementing subnet route advertising and ACL grants.

## Completed

### 1. Tailscale Kubernetes Operator Deployment
- **What**: Deployed Tailscale Operator v1.92.5 via HelmRelease
- **Why**: Enables VPN connectivity without opening router ports (NAT traversal)
- **How**:
  - Created OAuth client in Tailscale admin with minimal scopes (Devices Core + Auth Keys, `tag:k8s-operator` only)
  - Stored credentials in 1Password, synced via ExternalSecret
  - Deployed Operator via Flux with proper dependency chain (ESO → tailscale)

**Files Modified**:
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/tailscale/namespace.yaml`
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/tailscale/external-secret.yaml`
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/tailscale/helmrelease.yaml`

### 2. Exit Node Configuration
- **What**: Created Connector CRD to expose cluster as Tailscale exit node
- **Why**: Allows full tunnel mode (all traffic through home network) for privacy + ad blocking
- **How**:
  - ProxyClass with arm64 nodeSelector (ensures exit node runs on Pi 5)
  - Connector resource with `exitNode: true` and hostname `pi-cluster-exit`
  - Tagged with `tag:k8s-operator` for ACL policy matching

**Files Modified**:
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/tailscale-config/proxyclass.yaml`
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/tailscale-config/connector.yaml`

### 3. Pi-hole HA Verification
- **What**: Confirmed dual Pi-hole setup running on separate Pi 5 nodes
- **Why**: Redundancy for DNS service, failover capability
- **Current State**:
  - Primary: 192.168.1.55 (pi-k3s)
  - Secondary: 192.168.1.56 (pi5-worker-1)
  - Both accessible via local network and Tailscale subnet routes

### 4. DNS Subnet Route Configuration (Critical Fix)
- **What**: Added `subnetRouter.advertiseRoutes` to Connector with Pi-hole IPs
- **Why**: Exit node tunnel connects, but DNS queries fail without subnet routes
- **How**:
  ```yaml
  subnetRouter:
    advertiseRoutes:
      - 192.168.1.55/32   # Pi-hole primary
      - 192.168.1.56/32   # Pi-hole secondary
  ```
- **Impact**: DNS resolution working after adding ACL grant

**Files Modified**:
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/tailscale-config/connector.yaml`

### 5. Tailscale ACL Policy Updates (Root Cause Fix)
- **What**: Added subnet route ACL grant to allow client access to advertised routes
- **Why**: Subnet routes must be both advertised (Connector) AND granted (ACL) for clients to use them
- **How**:
  ```json
  "autoApprovers": {
      "routes": {
          "192.168.1.0/24": ["tag:k8s-operator"]
      }
  },
  "grants": [
      {"src": ["autogroup:member"], "dst": ["192.168.1.0/24"], "ip": ["*"]}
  ]
  ```
- **Result**: DNS queries to Pi-hole IPs now resolve successfully

**Tailscale Admin Changes**:
- ACL policy updated with subnet route grant
- Both subnet routes approved in admin console (pi-cluster-exit machine settings)
- Global nameservers configured: 192.168.1.55, 192.168.1.56 with "Use with exit node" enabled
- "Override local DNS" enabled to force all DNS through Pi-hole

### 6. Documentation Updates
- **What**: Updated CLAUDE.md with comprehensive Tailscale setup instructions
- **Why**: Critical troubleshooting steps and ACL requirements must be documented
- **How**: Added sections on:
  - Subnet route requirements (advertiseRoutes + ACL grants)
  - OAuth client minimal scope requirements
  - DNS settings in Tailscale admin console
  - Complete ACL policy example with route auto-approval
  - Troubleshooting table with DNS resolution issues

**Files Modified**:
- `/Users/mtgibbs/dev/pi-cluster/CLAUDE.md`

## Key Decisions

### 1. Subnet Route Architecture
**Decision**: Use subnet routes (`192.168.1.55/32`, `192.168.1.56/32`) instead of relying on MagicDNS

**Why**:
- Exit node provides tunnel, but doesn't automatically route to local IPs
- MagicDNS (100.100.100.100) is Tailscale's internal resolver, not our Pi-hole
- Subnet routes advertise specific IPs to the Tailscale network mesh
- ACL grants allow clients to access those advertised IPs

**Trade-offs**:
- More complex setup (requires Connector config + ACL policy + admin approval)
- Must update if Pi-hole IPs change (DHCP reservations protect against this)
- But: proper security boundary (explicit grants), works reliably

### 2. ACL Grant Requirement Discovery
**Decision**: Document that BOTH advertiseRoutes AND ACL grants are required

**Why**:
- This was the root cause of "DNS not resolving" issue
- Advertising routes makes them visible, but doesn't grant access
- ACL policy must explicitly allow `autogroup:member` to access `192.168.1.0/24`
- Underdocumented in Tailscale docs (easy to miss)

**Impact**: Prevents future troubleshooting loops on similar issues

## Architecture Changes

### Tailscale VPN Flow
```
Mobile Device (iPhone/Android)
    │ Tailscale App
    │ Exit Node: pi-cluster-exit
    ▼
NAT Traversal (WireGuard)
    │ No open ports required
    ▼
Pi K3s Cluster
    │
    ├─► Connector Pod (Exit Node)
    │   ├─► Advertises subnet routes: 192.168.1.55/32, 192.168.1.56/32
    │   └─► Tagged: tag:k8s-operator
    │
    └─► DNS Queries
        │
        ├─► 192.168.1.55:53 (Pi-hole primary) → Unbound → Internet
        └─► 192.168.1.56:53 (Pi-hole secondary) → Unbound → Internet
```

### Updated Flux Dependency Chain
```
16. tailscale               → Tailscale Operator (needs ESO for OAuth credentials)
17. tailscale-config        → Connector + ProxyClass CRDs (needs tailscale operator running)
```

## Troubleshooting Journey

### Problem 1: OAuth "Requested Tags Are Invalid"
**Symptom**: Operator pod CrashLoopBackOff with error about tags
**Root Cause**: OAuth client had extra scopes/tags beyond `tag:k8s-operator`
**Solution**: Created new OAuth client with ONLY Devices Core + Auth Keys, ONLY `tag:k8s-operator`
**Learning**: Tailscale OAuth is strict - any extra scopes cause tag validation failures

### Problem 2: Exit Node Not Visible in App
**Symptom**: Connector pod running, but exit node not showing in Tailscale mobile app
**Root Cause**: Missing `autogroup:internet` grant in ACL policy
**Solution**: Added grant: `{"src": ["autogroup:member"], "dst": ["autogroup:internet"], "ip": ["*"]}`
**Learning**: Exit node functionality requires explicit ACL grant

### Problem 3: DNS Not Resolving (Critical Issue)
**Symptom**: Exit node tunnel connected, but DNS queries to Pi-hole IPs timeout
**Investigation Steps**:
1. Verified exit node pod running and connected
2. Verified exit node can reach Pi-hole (exec into pod, `curl` works)
3. Verified MagicDNS not interfering (100.100.100.100 is separate)
4. Discovered subnet routes visible in admin console but not usable
5. **Root cause**: Subnet routes advertised but ACL policy didn't grant access

**Solution**:
1. Added `subnetRouter.advertiseRoutes` to Connector (already done)
2. Added ACL grant: `{"src": ["autogroup:member"], "dst": ["192.168.1.0/24"], "ip": ["*"]}`
3. Added auto-approver: `"routes": {"192.168.1.0/24": ["tag:k8s-operator"]}`
4. Approved routes in Tailscale admin console
5. Configured global nameservers: 192.168.1.55, 192.168.1.56 with "Use with exit node"

**Result**: DNS resolution working, ad blocking functional on mobile

**Learning**: Tailscale subnet routes require THREE things:
1. Advertise routes in Connector resource
2. Approve routes in admin console
3. Grant access in ACL policy (often missed!)

## Testing Results

### Exit Node Connectivity
- Mobile device successfully connects to pi-cluster-exit
- Tunnel established via WireGuard (no open ports required)
- Public IP shows as home network IP when exit node active

### DNS Resolution
- Queries to `google.com`, `reddit.com`, `example.com` resolve instantly
- Pi-hole admin shows queries from mobile device (source IP: 192.168.1.x via Tailscale)
- Ad blocking confirmed (trackers blocked, query log shows blocks)

### Split Tunnel vs Full Tunnel
- **Split Tunnel** (exit node OFF): Only DNS queries to Pi-hole, other traffic direct
- **Full Tunnel** (exit node ON): All traffic through home network + DNS via Pi-hole
- Both modes working as expected

## Lessons Learned

### 1. Tailscale Subnet Routes Are Not Intuitive
- Advertising routes != granting access (two separate steps)
- ACL policy grant is easy to miss (not emphasized in docs)
- Admin console approval is visible, but doesn't fix access without grant

### 2. OAuth Client Scopes Must Be Minimal
- Extra scopes/tags cause cryptic validation errors
- "Requested tags are invalid" usually means OAuth client has extra tags
- Best practice: Create new OAuth client, don't modify existing

### 3. Exit Node Functionality Has Two Separate Grants
- `autogroup:internet` grant for exit node usage (general internet access)
- Subnet-specific grants for local network access (e.g., `192.168.1.0/24`)
- Both required for full functionality

### 4. DNS Override Settings Are Critical
- "Override local DNS" ensures Pi-hole is used (not device default)
- "Use with exit node" ensures DNS settings apply when tunnel active
- Without both, device may bypass Pi-hole and use cellular DNS

## Next Steps

### Immediate
- [ ] Test ad blocking on mobile devices in various scenarios (WiFi, cellular, VPN)
- [ ] Monitor Tailscale operator logs for any connection issues
- [ ] Verify exit node performance (latency, throughput)

### Future Enhancements
- [ ] Add Uptime Kuma monitor for Tailscale exit node availability
- [ ] Consider Headscale (self-hosted control plane) if 3-user limit becomes issue
- [ ] Document ACL policy in git (currently only in Tailscale admin console)
- [ ] Add Grafana dashboard for Tailscale metrics (if available)

## Commits

- `1dc95ee` - feat(tailscale): Add subnet routes for Pi-hole DNS
- `bfd235d` - chore: Update Tailscale operator to 1.92.5
- `d450e27` - fix: Simplify Tailscale config to use only tag:k8s-operator
- `2700e81` - chore: Explicitly set Tailscale operator and proxy tags
- `64e9a71` - fix: Use correct 1Password SDK format for Tailscale secret
- `5eaf1cd` - fix: Split Tailscale into operator + config kustomizations
- `088aeda` - feat: Add Tailscale VPN for mobile ad-blocking

## References

- Tailscale Kubernetes Operator: https://tailscale.com/kb/1236/kubernetes-operator
- Tailscale Exit Nodes: https://tailscale.com/kb/1103/exit-nodes
- Tailscale Subnet Routes: https://tailscale.com/kb/1019/subnets
- Tailscale ACL Policy: https://tailscale.com/kb/1018/acls
- Pi-hole HA Documentation: `/Users/mtgibbs/dev/pi-cluster/docs/pihole-ha-setup.md`

---

**Session Duration**: ~2 hours (troubleshooting DNS routing)
**Key Blocker**: ACL grant for subnet routes (resolved via documentation dive)
**Outcome**: Full mobile ad blocking via Tailscale VPN functional
