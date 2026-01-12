---
name: dns-ops
description: Expert knowledge for Pi-hole and Unbound DNS operations. Use when configuring DNS, troubleshooting resolution issues, modifying adlists, or understanding the DNS data flow.
allowed-tools: Bash, Read, Grep, Glob, Edit, Write
---

# DNS Operations (Pi-hole + Unbound)

## Architecture

```
User Device → Pi-hole (ad filtering) → Unbound (recursive DNS) → Root/TLD/Authoritative servers
```

**Why Unbound?** Full recursive resolution directly to authoritative DNS servers. Better privacy (no single upstream sees all queries), no third-party trust required, DNSSEC validation.

## Service Details

### Pi-hole
- **Deployment**: `pihole/pihole:latest` with `hostNetwork: true`
- **Port**: 53 (UDP/TCP) directly on host IP (192.168.1.55)
- **Password**: Synced from 1Password via ExternalSecret
- **Upstream DNS**: Unbound ClusterIP service (configured via API)
- **Adlists**: Firebog curated lists via ConfigMap (~900k domains)
- **DNSSEC**: Disabled (handled by Unbound)

### Unbound
- **Deployment**: `mvance/unbound:latest`
- **Port**: 5335 (non-privileged)
- **Type**: Recursive resolver
- **Node Placement**: Pi 5 nodes ONLY via nodeSelector (Pi 3 hardware causes TCP failures)
- **Performance**: ~21ms uncached, 0-15ms cached

## Configuration

### Pi-hole v6 API (Critical)
Pi-hole v6 ignores most environment variables. Configuration is done via REST API in `postStart` hook:

- `POST /api/auth` - Get session ID
- `PATCH /api/config` - Set upstream DNS to Unbound ClusterIP
- `POST /api/lists` - Add adlists from ConfigMap (batch format)
- `POST /api/action/gravity` - Update gravity database

Reference: `docs/pihole-v6-api.md`

### DNS Resilience
The Pi node uses static DNS (`1.1.1.1`, `8.8.8.8`) configured via NetworkManager.
*   **Why**: Ensures the Pi can pull images (like Pi-hole itself) even if the cluster DNS is down.

## Troubleshooting

### Testing Resolution
```bash
# Test against Pi-hole (Local)
dig @192.168.1.55 google.com

# Test against Unbound (Inside Cluster)
kubectl exec -it deploy/pihole -n pihole -- dig @unbound.pihole.svc.cluster.local -p 5335 google.com
```

### Common Issues
1.  **"Refused"**: Check if Pi-hole is running and `hostNetwork` is true.
2.  **"ServFail"**: Check Unbound logs. Often upstream timeout or TCP failure on Pi 3 nodes.
3.  **Adlists not loading**: Check `postStart` hook logs in Pi-hole pod.

### Checking Logs
```bash
# Pi-hole logs
kubectl -n pihole logs deploy/pihole

# Unbound logs
kubectl -n pihole logs deploy/unbound
```

## Relevant Files
- `clusters/pi-k3s/pihole/pihole-deployment.yaml`
- `clusters/pi-k3s/pihole/unbound-deployment.yaml`
- `clusters/pi-k3s/pihole/pihole-custom-dns.yaml`
