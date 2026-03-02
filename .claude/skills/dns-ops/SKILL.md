---
name: dns-ops
description: Expert knowledge for Pi-hole and Unbound DNS operations. Use when configuring DNS, troubleshooting resolution issues, modifying adlists, or understanding the DNS data flow.
allowed-tools: Bash, Read, Grep, Glob, Edit, Write
---

# DNS Operations (Pi-hole + Unbound)

## Architecture (HA)

```
                    ┌─ Pi-hole (pi-k3s:53) ──── Unbound (pi-k3s:5335) ──── Root Servers
User Device ───┤
                    └─ Pi-hole-secondary (pi5-worker-1:53) ──── Unbound-secondary (pi5-worker-1:5335) ──── Root Servers
```

Both paths are independent. Clients may use either Pi-hole instance via DHCP-assigned DNS.

**Why Unbound?** Full recursive resolution directly to authoritative DNS servers. Better privacy (no single upstream sees all queries), no third-party trust required, DNSSEC validation.

## Service Details

### Pi-hole (Primary + Secondary)
- **Image**: `pihole/pihole:latest` with `hostNetwork: true`
- **Primary**: Port 53 on `pi-k3s` (192.168.1.55)
- **Secondary**: Port 53 on `pi5-worker-1` (192.168.1.56)
- **Password**: Synced from 1Password via ExternalSecret
- **Upstream DNS**: Respective Unbound ClusterIP service
- **Adlists**: Firebog curated lists via ConfigMap (~900k domains)
- **DNSSEC**: Disabled on Pi-hole (handled by Unbound)
- **Caching**: Pi-hole maintains its own DNS cache

### Unbound (Primary + Secondary)
- **Image**: `madnuttah/unbound:latest` (distroless, minimal — no cat/ls/head)
- **Port**: 5335 (non-privileged) via ClusterIP service
- **Type**: Recursive resolver with DNSSEC validation
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

### madnuttah/unbound Config Quirks (CRITICAL)

The `madnuttah/unbound` image **rewrites the main unbound.conf** during its entrypoint. It transforms paths and drops directives it doesn't recognize.

- **Compiled config path**: `/usr/local/unbound/unbound.conf` (NOT `/opt/unbound/etc/unbound/unbound.conf`)
- **Our mount**: `/opt/unbound/etc/unbound/unbound.conf` → entrypoint processes this into the actual config
- **Dropped directives**: `domain-insecure` and other less common server directives are silently dropped
- **conf.d directory**: `/usr/local/unbound/conf.d/*.conf` — mount custom server directives HERE as separate files
- **Verify running config**: `kubectl exec -n pihole deploy/unbound -- unbound-checkconf -o <directive>`

**To add custom server directives** (e.g., `domain-insecure`):
1. Add the directive to the ConfigMap as a separate data key (e.g., `dnssec-exceptions.conf`)
2. Mount it at `/usr/local/unbound/conf.d/<name>.conf` using `subPath`
3. Do NOT put it in the main `unbound.conf` — it will be silently dropped

### DNSSEC Validation

Unbound validates DNSSEC via:
- `auto-trust-anchor-file` — root trust anchor
- `harden-dnssec-stripped: yes` — strict mode, rejects responses that strip DNSSEC

**When a domain has broken DNSSEC** (DS records published but no valid DNSKEY):
- Unbound returns SERVFAIL
- Unbound logs show: `validation failure <domain>: no keys have a DS with algorithm RSASHA256`
- Fix: Add `domain-insecure: "domain.com"` via conf.d mount (see above)

### Caching Behavior (CRITICAL for Diagnostics)

**Unbound `serve-expired` configuration:**
- `serve-expired: yes` with `serve-expired-ttl: 86400` (24 hours)
- Unbound serves stale cache immediately while refreshing in background
- This means a broken upstream can be **masked by stale cache for up to 24 hours**

**Pi-hole also caches results** independently.

**Combined effect**: `test_dns_query` (which runs dig inside Pi-hole) can return a successful cached result even when Unbound is actively returning SERVFAIL. A successful `test_dns_query` does NOT prove the resolution path is healthy. **Always use `diagnose_dns` for troubleshooting.**

### DNS Resilience
The Pi node uses static DNS (`1.1.1.1`, `8.8.8.8`) configured via NetworkManager.
*   **Why**: Ensures the Pi can pull images (like Pi-hole itself) even if the cluster DNS is down.

## IPv6 Blocking (AT&T Routing Issues)

AT&T Fiber has poor IPv6 routing to some CDNs. We selectively block IPv6 for affected domains.

**Current blocked domains**: See `clusters/pi-k3s/pihole/pihole-custom-dns.yaml`

### IMPORTANT: Test Before Blocking

When a user reports slow/broken connectivity to a service, **DO NOT** immediately add it to the IPv6 block list. First verify IPv6 is the cause:

```bash
# 1. Check if domain returns AAAA records (if no AAAA, IPv6 isn't the issue)
dig AAAA <domain>

# 2. Compare IPv4 vs IPv6 response times from a device on the network
curl -4 -w "IPv4: %{time_total}s\n" -o /dev/null -s https://<domain>
curl -6 -w "IPv6: %{time_total}s\n" -o /dev/null -s https://<domain>

# 3. If IPv6 is significantly slower (2x+) or times out, add to block list
```

Only add to the block list after confirming IPv6 is the problem. See `docs/known-issues.md` for details.

## DNS Troubleshooting Runbook (MANDATORY)

**When a user reports a domain is unreachable, follow ALL steps in order. Do NOT stop after step 1 even if it shows success. Do NOT blame the client's browser or machine until the entire server path is proven clean.**

### Step 1: Run `diagnose_dns` MCP Tool (ALWAYS START HERE)

Use `diagnose_dns` with the reported domain. This single tool tests:
- Pi-hole resolution (may be cached)
- Unbound primary direct resolution (bypasses cache)
- Unbound secondary direct resolution (bypasses cache)
- DNSSEC validation check (if Unbound fails, retries with +cd)
- Unbound pod logs filtered for the domain

**If `diagnose_dns` is unavailable**, manually run all substeps:
```
test_dns_query → check Unbound logs (BOTH pods) → dig @unbound directly
```

### Step 2: Interpret Results

| Pi-hole | Unbound Primary | Unbound Secondary | Diagnosis |
|---------|----------------|-------------------|-----------|
| OK | OK | OK | Resolution path is healthy. Issue is client-side. |
| OK | FAIL | FAIL | **Stale cache masking upstream failure.** Check Unbound logs immediately. |
| OK | OK | FAIL | Secondary Unbound is broken. Client may be using secondary. |
| FAIL | FAIL | FAIL | Complete DNS failure. Check pod health, network connectivity. |
| OK (cached) | FAIL + resolves with +cd | FAIL + resolves with +cd | **DNSSEC validation failure.** Domain has broken DNSSEC. |

### Step 3: Check Unbound Logs (NEVER SKIP)

Use `get_pod_logs` for BOTH Unbound pods:
- `namespace: pihole, pod: unbound`
- `namespace: pihole, pod: unbound-secondary`

Look for:
- `validation failure` — DNSSEC issue
- `SERVFAIL` — upstream failure
- `connection timed out` — network issue
- `TCP connection failed` — TCP upstream issue (common on Pi 3)

### Step 4: Apply Fix Based on Root Cause

| Root Cause | Fix |
|-----------|-----|
| DNSSEC validation failure | Add `domain-insecure` via conf.d ConfigMap mount |
| Unbound timeout/crash | Restart Unbound deployment, check node health |
| Pi-hole not forwarding | Check Pi-hole upstream DNS config via API |
| Network issue | Check node connectivity to root servers |

### Common Issues
1.  **"Refused"**: Check if Pi-hole is running and `hostNetwork` is true.
2.  **"ServFail"**: ALWAYS check Unbound logs. Often DNSSEC failure, upstream timeout, or TCP failure on Pi 3 nodes.
3.  **Adlists not loading**: Check `postStart` hook logs in Pi-hole pod.
4.  **`test_dns_query` shows success but client fails**: Stale cache. Use `diagnose_dns` instead.

## Relevant Files
- `clusters/pi-k3s/pihole/pihole-deployment.yaml` — Primary Pi-hole
- `clusters/pi-k3s/pihole/pihole-secondary-deployment.yaml` — Secondary Pi-hole
- `clusters/pi-k3s/pihole/unbound-deployment.yaml` — Primary Unbound + Service
- `clusters/pi-k3s/pihole/unbound-secondary-deployment.yaml` — Secondary Unbound + Service
- `clusters/pi-k3s/pihole/unbound-configmap.yaml` — Unbound config (shared by both, includes conf.d entries)
- `clusters/pi-k3s/pihole/pihole-custom-dns.yaml` — Local DNS + IPv6 overrides
