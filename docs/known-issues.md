# Known Issues

### Immich High CPU Usage
- **Issue**: Immich causing ~2 CPU cores usage on Pi 5 due to ML job retry loop
- **Cause**: Machine learning disabled but jobs still queued and retrying
- **Impact**: High CPU usage, no functional issues
- **Resolution**: Deferred - ML features not needed, workaround is acceptable

### Dead Pi-hole Blocklists
- **Issue**: Two dead blocklists (IDs 19, 28) in Pi-hole database
- **Cause**: Manually added via web UI (not in GitOps ConfigMap)
- **Impact**: Warning logs, no blocking issues (~900k domains still active)
- **Resolution**: Deferred - not affecting DNS blocking functionality

### NFS UID/GID Mapping
- **Issue**: Files created on NFS volumes have incorrect ownership (uid=0, gid=0 instead of uid=568)
- **Cause**: Synology NFS no_root_squash setting vs application UID expectations
- **Impact**: Minimal - applications can read/write, but file ownership is incorrect
- **Resolution**: Deferred - functional workaround exists, proper fix requires Synology NFS reconfiguration

### Pod Overlay Networking Broken on pi-k3s Node
- **Issue**: Cross-node pod overlay networking broken on pi-k3s master node
- **Cause**: Unknown - possibly Flannel VXLAN, dual-stack IPv6, or CNI misconfiguration
- **Impact**: Pods scheduled on pi-k3s cannot reach pods on other nodes (e.g., CoreDNS on pi5-worker-1)
- **Symptoms**: DNS resolution failures, connection timeouts to cross-node services
- **Workaround**: Use `hostNetwork: true` with `dnsPolicy: ClusterFirstWithHostNet` for affected pods
- **Resolution**: Deferred - requires deep K3s/Flannel debugging with tcpdump
- **Affected Workloads**: git-mirror-cronjob (workaround applied)
- **Last Observed**: 2026-01-28

### AT&T IPv6 Routing Problems
- **Issue**: Certain services are slow or broken when accessed via IPv6
- **Cause**: AT&T Fiber has poor IPv6 peering/routing to some CDNs
- **Impact**: Slow page loads, timeouts, 503 errors on affected services
- **Affected Services**: Amazon, Netflix, MyFitnessPal, Slack (see `pihole-custom-dns.yaml`)
- **Resolution**: Selective IPv6 blocking via Pi-hole dnsmasq config - returns `::` for affected domains, forcing IPv4 fallback
- **Testing Protocol**: Before adding new domains, verify IPv6 is the cause:
  ```bash
  # Check if domain returns AAAA records
  dig AAAA <domain>

  # Compare IPv4 vs IPv6 response times
  curl -4 -w "%{time_total}\n" -o /dev/null -s https://<domain>
  curl -6 -w "%{time_total}\n" -o /dev/null -s https://<domain>
  ```
