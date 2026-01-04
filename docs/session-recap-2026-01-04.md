# Session Recap - 2026-01-04

## Summary

Deployed the mtgibbs.xyz personal website to the Pi K3s cluster with full Flux GitOps image automation, enabling auto-deploy workflow from source code to cluster without manual intervention.

## Completed Work

### 1. New Service Deployment: mtgibbs.xyz Personal Site

**What**: Deployed Next.js personal website to the cluster with GitOps-managed configuration
**Why**: Consolidate personal infrastructure on self-hosted cluster, demonstrate full GitOps workflow with image automation
**How**: Created complete Flux manifests in `clusters/pi-k3s/mtgibbs-site/`

Files created:
- `namespace.yaml` - mtgibbs-site namespace
- `deployment.yaml` - Next.js app with node affinity for Pi 3 workers, image automation marker
- `service.yaml` - ClusterIP service on port 3000
- `ingress.yaml` - HTTPS ingress at site.lab.mtgibbs.dev with Let's Encrypt TLS
- `image-automation.yaml` - ImageRepository, ImagePolicy, ImageUpdateAutomation (Flux API v1)
- `kustomization.yaml` - Kustomize manifest list

**Configuration Details**:
- Image: `ghcr.io/mtgibbs/mtgibbs.xyz` (ARM64 + AMD64 multi-arch)
- Node Affinity: Prefers Pi 3 workers (offloads work from Pi 5 master)
- Resources: 50m/500m CPU, 128Mi/256Mi memory
- Health checks: liveness (30s interval), readiness (10s interval)
- Security: runAsNonRoot, no privilege escalation
- URL: https://site.lab.mtgibbs.dev

### 2. Flux Image Automation Setup

**What**: Installed Flux image-reflector-controller and image-automation-controller
**Why**: Enable automatic image updates when new builds are pushed to GHCR
**How**: Bootstrapped Flux with write access, created RBAC for image controllers

**Implementation**:
- Created ImageRepository to scan `ghcr.io/mtgibbs/mtgibbs.xyz` every 5 minutes
- Created ImagePolicy with timestamp tag pattern (`^[0-9]{14}$`), numerical sorting (ascending)
- Created ImageUpdateAutomation to:
  - Monitor ImagePolicy for new tags
  - Update deployment.yaml with new image tag using Setters strategy
  - Commit changes with message: `chore: update mtgibbs-site to <tag>`
  - Push to main branch
- Added RBAC (ServiceAccounts, ClusterRoles, ClusterRoleBindings) for image controllers

**API Versions**: Used Flux Image Automation API v1 (corrected from initial v1beta2)

### 3. Flux Bootstrap with Write Access

**What**: Re-bootstrapped Flux with `--read-write-key` using fine-grained GitHub PAT
**Why**: Default deploy key was read-only, preventing ImageUpdateAutomation from pushing commits
**How**: Created fine-grained PAT with minimal permissions, stored in 1Password, re-ran `flux bootstrap github`

**1Password Item**: `flux-github-pat`
- Vault: `pi-cluster`
- Field: `token`
- Permissions: Contents (read/write), Administration (manage deploy keys) - scoped to pi-cluster repo only
- Expiration: 90 days

**Security Considerations**:
- PAT has minimal permissions (only pi-cluster repo, only required scopes)
- Stored in 1Password, never committed to git
- Flux uses PAT to manage its own deploy key

### 4. Documentation Created

**File**: `docs/mtgibbs-xyz-ghcr-instructions.md`
**Purpose**: Instructions for adding GHCR publishing workflow to the mtgibbs.xyz repository

**Key details**:
- Multi-architecture builds (linux/amd64 + linux/arm64) for Pi compatibility
- Timestamp tags in YYYYMMDDHHmmss format for Flux ImagePolicy numerical sorting
- GitHub Actions workflow using docker/build-push-action with QEMU + Buildx
- GITHUB_TOKEN has automatic packages:write permission (no new secrets needed)

### 5. External Repository Changes (mtgibbs.xyz)

**Note**: These changes were done in the mtgibbs.xyz repository by user/other agent, not in pi-cluster repo

**What**: Added GitHub Actions workflow to build and push multi-arch images to GHCR
**Files**:
- `.github/workflows/ghcr.yml` - Docker build workflow
- `Dockerfile` - Fixed Node.js version (node:16-alpine → node:20-alpine)

**Workflow Triggers**:
- Push to `mater` branch (repository uses non-standard branch name)
- Builds for linux/amd64 + linux/arm64
- Pushes to ghcr.io/mtgibbs/mtgibbs.xyz with 3 tags:
  - Timestamp tag (e.g., `20260104084623`)
  - Git SHA tag
  - `latest` tag

### 6. Flux Infrastructure Updates

**File**: `clusters/pi-k3s/flux-system/infrastructure.yaml`
**What**: Added Kustomization #15 for mtgibbs-site deployment
**Dependencies**: ingress, cert-manager-config (same as other web services)

### 7. Flux Controller Updates

**File**: `clusters/pi-k3s/flux-system/gotk-components.yaml`
**What**: Updated to Flux v2.7.5 with image automation controllers
**Changes**: Added 2,247 lines of YAML for image-reflector-controller and image-automation-controller

### 8. Homepage Dashboard Web Section

**What**: Added new "Web" section to Homepage dashboard with 3 services
**Why**: Provide quick access to both cluster-hosted and external personal websites
**How**: Updated `clusters/pi-k3s/homepage/configmap.yaml` settings and services

**Services Added**:
- **Personal Site (Cluster)**: https://site.lab.mtgibbs.dev
  - siteMonitor widget for uptime/status
  - Links to cluster-hosted Next.js site
- **Personal Site (Heroku)**: https://mtgibbs.xyz
  - siteMonitor widget for production uptime
  - Links to Heroku-hosted production site
- **Cloudflare**: https://dash.cloudflare.com
  - Direct link to Cloudflare dashboard (no widget)

**Layout Changes**:
- Updated `settings.yaml` to include Web section in layout
- Web section uses 3-column layout for even spacing
- Positioned between Monitoring and Media sections

### 9. Homepage Weather Widget Fix

**What**: Fixed weather widget to display Johns Creek, GA weather
**Why**: Widget was previously showing incorrect location
**How**: Updated coordinates in `configmap.yaml` widgets section

**Configuration**:
```yaml
latitude: 34.0289
longitude: -84.1986
units: imperial
```

### 10. Uptime Kuma Monitor Additions

**What**: Added two new monitors to AutoKuma ConfigMap
**Why**: Track availability of both cluster and production personal sites
**How**: Added JSON monitor definitions to `autokuma-monitors.yaml`

**Monitors Added**:
1. **personal-site-cluster.json**
   - URL: https://site.lab.mtgibbs.dev/
   - Type: HTTP (200 OK check)
   - Interval: 60 seconds

2. **personal-site-heroku.json**
   - URL: https://mtgibbs.xyz/
   - Type: HTTP (200 OK check)
   - Interval: 60 seconds

**Total Monitors**: 14 (up from 12)

## Architecture Changes

### New Auto-Deploy Flow

```
┌──────────────────────┐
│  mtgibbs.xyz repo    │
│  (github.com)        │
│                      │
│  Push to mater ────► │
└──────────┬───────────┘
           │
           │ GitHub Actions
           │ (.github/workflows/ghcr.yml)
           │
           ▼
┌─────────────────────────────────────────┐
│  GitHub Container Registry (GHCR)       │
│  ghcr.io/mtgibbs/mtgibbs.xyz            │
│                                         │
│  Tags:                                  │
│  • 20260104084623 (timestamp)           │
│  • a1b2c3d (git SHA)                    │
│  • latest                               │
└──────────┬──────────────────────────────┘
           │
           │ Flux scans every 5 minutes
           │
           ▼
┌─────────────────────────────────────────┐
│  Flux Image Automation                  │
│  (in pi-k3s cluster)                    │
│                                         │
│  1. ImageRepository scans GHCR          │
│  2. ImagePolicy selects newest tag      │
│     (numerical sort: 20260104084623)    │
│  3. ImageUpdateAutomation updates       │
│     deployment.yaml                     │
│  4. Commits + pushes to pi-cluster      │
└──────────┬──────────────────────────────┘
           │
           │ Git push
           │
           ▼
┌─────────────────────────────────────────┐
│  pi-cluster repo                        │
│  (github.com/mtgibbs/pi-cluster)        │
│                                         │
│  clusters/pi-k3s/mtgibbs-site/          │
│    deployment.yaml (updated)            │
└──────────┬──────────────────────────────┘
           │
           │ Flux reconciles every 10m
           │
           ▼
┌─────────────────────────────────────────┐
│  K3s Cluster                            │
│                                         │
│  mtgibbs-site deployment updated        │
│  New image pulled from GHCR             │
│  Rolling update to new version          │
│                                         │
│  https://site.lab.mtgibbs.dev           │
└─────────────────────────────────────────┘
```

### Flux Dependency Chain Update

Updated dependency order (added #15):

```
1.  external-secrets        → Installs ESO operator + CRDs
2.  external-secrets-config → Creates ClusterSecretStore (needs CRDs)
3.  ingress                 → nginx-ingress controller
4.  cert-manager            → Installs cert-manager CRDs + controllers
5.  cert-manager-config     → Creates ClusterIssuers + Cloudflare secret
6.  pihole                  → Pi-hole + Unbound DNS
7.  monitoring              → kube-prometheus-stack + Grafana
8.  uptime-kuma             → Status page
9.  homepage                → Unified dashboard
10. external-services       → Reverse proxies (Unifi, Synology)
11. flux-notifications      → Discord deployment notifications
12. backup-jobs             → PVC + PostgreSQL backups
13. immich                  → Photo management
14. jellyfin                → Media server
15. mtgibbs-site            → Personal website (NEW)
```

## Issues Encountered and Resolved

### Issue 1: Image Automation API Version Mismatch

**Problem**: Initial manifests used `image.toolkit.fluxcd.io/v1beta2`
**Error**: CRDs not found, resources not applying
**Root Cause**: Flux v2.7.5 uses stable API version `v1` for image automation
**Resolution**: Updated all three resources to use `apiVersion: image.toolkit.fluxcd.io/v1`

**Affected Resources**:
- ImageRepository
- ImagePolicy
- ImageUpdateAutomation

### Issue 2: Image Controllers Missing RBAC

**Problem**: Image controllers failed to start, permission denied errors
**Error**: Controllers using default service account with no permissions
**Root Cause**: Flux bootstrap didn't create RBAC for image controllers
**Resolution**: Manually created ServiceAccounts, ClusterRoles, ClusterRoleBindings in gotk-components.yaml

**RBAC Created**:
- ServiceAccount: image-automation-controller, image-reflector-controller
- ClusterRole: crd-controller (for managing CRDs), image-automation-controller, image-reflector-controller
- ClusterRoleBindings: associated bindings for all roles

### Issue 3: Flux Deploy Key Read-Only

**Problem**: ImageUpdateAutomation couldn't push commits back to pi-cluster repo
**Error**: `git push` failed with permission denied
**Root Cause**: Default Flux bootstrap creates read-only deploy key
**Resolution**: Re-bootstrapped Flux with `--read-write-key` flag using fine-grained GitHub PAT

**Commands Used**:
```bash
# Created fine-grained PAT in GitHub with:
# - Repository: pi-cluster only
# - Permissions: Contents (read/write), Administration (read/write for deploy keys)
# - Expiration: 90 days

# Stored PAT in 1Password (pi-cluster vault, flux-github-pat item)

# Re-bootstrapped Flux
flux bootstrap github \
  --owner=mtgibbs \
  --repository=pi-cluster \
  --branch=main \
  --path=clusters/pi-k3s \
  --personal \
  --read-write-key
```

### Issue 4: Fine-Grained PAT Needed Administration Permission

**Problem**: PAT with only Contents permission couldn't manage deploy keys
**Error**: `flux bootstrap` failed to update deploy key permissions
**Root Cause**: Managing deploy keys requires Administration permission
**Resolution**: Updated PAT to include Administration permission (read/write)

**Note**: This is a one-time operation - after bootstrap, Flux uses the deploy key it created

### Issue 5: GHCR Build Failing (Old Node.js Version)

**Problem**: Docker build failed in GitHub Actions
**Error**: Next.js build errors with Node.js 16
**Root Cause**: Dockerfile used `node:16-alpine` (EOL), Next.js requires Node.js 18+
**Resolution**: Updated Dockerfile to use `node:20-alpine`

**Note**: This change was made in the mtgibbs.xyz repository, not pi-cluster

## Commits Made

| Commit Hash | Message | Files Changed |
|-------------|---------|---------------|
| c58b675 | feat: Add mtgibbs.xyz personal site deployment with Flux image automation | +7 files (namespace, deployment, service, ingress, kustomization, image-automation), infrastructure.yaml |
| 94d84df | fix: Update Flux image automation API versions to v1 | image-automation.yaml |
| a800589 | Add Flux v2.7.5 component manifests | gotk-components.yaml (+2247 lines) |
| 2b7937f | chore: update mtgibbs-site to ghcr.io/mtgibbs/mtgibbs.xyz:20260104084623 | deployment.yaml (automated commit by Flux) |
| ea9c191 | feat(homepage): Add Web section with personal sites and Cloudflare | homepage/configmap.yaml |
| a7c5986 | chore: update mtgibbs-site to ghcr.io/mtgibbs/mtgibbs.xyz:20260104154234 | mtgibbs-site/deployment.yaml (automated commit by Flux) |
| 29bab17 | feat: Update Homepage weather and add Uptime Kuma monitors | homepage/configmap.yaml, uptime-kuma/autokuma-monitors.yaml |

**Note**: Commits 2b7937f and a7c5986 were created automatically by Flux ImageUpdateAutomation, demonstrating the auto-deploy workflow is functioning correctly (2 automated deployments in one day).

## New Service URL

- **mtgibbs.xyz Personal Site**: https://site.lab.mtgibbs.dev
  - TLS certificate via Let's Encrypt
  - Auto-deployed from GHCR on every push to `mater` branch
  - Runs on Pi 3 workers (node affinity)

## Key Decisions

### Decision 1: Use Flux Image Automation Instead of Manual Image Updates

**What**: Deploy Flux image-reflector-controller and image-automation-controller
**Why**:
- Eliminates manual deployment steps (build → push → update YAML → commit → push)
- Demonstrates full GitOps workflow for personal projects
- Auto-deploys website updates within 5-10 minutes of code push
- Provides learning opportunity for advanced Flux features

**How**:
- ImageRepository scans GHCR every 5 minutes for new tags
- ImagePolicy filters for timestamp tags, selects newest numerically
- ImageUpdateAutomation updates deployment.yaml, commits, pushes to GitHub
- Standard Flux Kustomization deploys the update

**Trade-offs**:
- More complex setup (requires write-access deploy key, RBAC, fine-grained PAT)
- Flux now has write access to pi-cluster repo (security consideration)
- Additional Flux controllers consume ~50Mi memory
- But: fully automated deploys, no manual intervention, true GitOps workflow

### Decision 2: Timestamp Tags for Image Versioning

**What**: Use YYYYMMDDHHmmss timestamp format for Docker image tags
**Why**:
- Flux ImagePolicy numerical sorting requires numeric-only tags
- Git SHAs are alphanumeric, can't be sorted numerically
- Timestamps are monotonically increasing (always newer = higher number)
- Human-readable (can see when image was built at a glance)

**How**:
- GitHub Actions workflow uses `docker/metadata-action` with `type=raw,value={{date 'YYYYMMDDHHmmss'}}`
- Example tag: `20260104084623` = 2026-01-04 08:46:23 UTC
- ImagePolicy pattern: `^[0-9]{14}$` (exactly 14 digits)

**Trade-offs**:
- Not semantic versioning (no major/minor/patch)
- Can't easily identify what changed between versions
- But: simple, reliable, works perfectly with Flux numerical sorting

### Decision 3: Node Affinity for Pi 3 Workers

**What**: Set preferredDuringSchedulingIgnoredDuringExecution affinity for Pi 3 workers
**Why**:
- Offload web serving from Pi 5 master node
- Pi 5 runs critical infrastructure (Pi-hole, Flux controllers, backups)
- Pi 3s have lighter workloads (Unbound only scheduled on one)
- Web traffic is bursty, better on dedicated workers

**How**:
- Deployment spec includes nodeAffinity with weight: 100
- Prefers pi3-worker-1 or pi3-worker-2
- Falls back to pi-k3s if workers are unavailable

**Trade-offs**:
- Pi 3s have only 1GB RAM (vs 8GB on Pi 5)
- Website resource limits must stay conservative (256Mi max)
- But: better resource distribution across cluster

### Decision 4: Fine-Grained GitHub PAT Instead of Classic Token

**What**: Use fine-grained personal access token for Flux bootstrap
**Why**:
- Fine-grained PATs have repository-level scoping (not account-wide)
- Minimum permissions (Contents read/write, Administration read/write)
- Expiration enforced (90 days max, must be renewed)
- Better security posture than classic PATs

**How**:
- Created PAT via GitHub Settings → Developer settings → Fine-grained tokens
- Scoped to pi-cluster repository only
- Stored in 1Password (pi-cluster vault, flux-github-pat item)
- Used during `flux bootstrap github --read-write-key`

**Trade-offs**:
- Must renew token every 90 days
- Requires Administration permission (more than just Contents)
- But: significantly better security than classic tokens or account-wide access

## Next Steps

### Immediate Follow-Up (COMPLETED)

- [x] Update Homepage dashboard to include mtgibbs.xyz site
- [x] Add Uptime Kuma monitor for site.lab.mtgibbs.dev
- [x] Add Uptime Kuma monitor for mtgibbs.xyz (production site)
- [ ] Consider making GHCR package public (avoid imagePullSecrets)

### Future Enhancements

- [ ] Add Prometheus ServiceMonitor for Next.js metrics (if exposed)
- [ ] Implement blue/green deployments with Flagger (progressive delivery)
- [ ] Set up image vulnerability scanning with Trivy
- [ ] Add resource quotas for mtgibbs-site namespace

## Lessons Learned

1. **Flux Image Automation API Stability**: Always check Flux version compatibility - v1beta2 → v1 was a breaking change
2. **RBAC is Not Optional**: Controllers need explicit RBAC, default service accounts have no permissions
3. **GitHub Deploy Key Permissions**: Default deploy keys are read-only by design, must explicitly enable write access
4. **Fine-Grained PATs Need Admin**: Managing deploy keys requires Administration permission, not just Contents
5. **Multi-Arch Builds Are Essential**: ARM64 support required for Pi cluster, must use QEMU + Buildx

## Verification

All systems verified working:

```bash
# Flux reconciliation successful
flux get all
# All resources showing "Applied revision: main@sha1:..."

# mtgibbs-site deployed
kubectl get pods -n mtgibbs-site
# NAME                            READY   STATUS    RESTARTS   AGE
# mtgibbs-site-5d8f4c7b9d-x7z2p   1/1     Running   0          15m

# Image automation active
kubectl get imagerepositories,imagepolicies,imageupdateautomations -n flux-system
# All showing Ready/True

# Site accessible
curl -I https://site.lab.mtgibbs.dev
# HTTP/2 200 OK
# Server: nginx (via ingress)
```

## References

- Flux Image Automation Guide: https://fluxcd.io/flux/guides/image-update/
- Flux Bootstrap Documentation: https://fluxcd.io/flux/installation/bootstrap/github/
- GitHub Fine-Grained PAT: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-fine-grained-personal-access-token
- Docker Buildx Multi-Platform: https://docs.docker.com/build/building/multi-platform/

---

**Session Duration**: ~2 hours
**Complexity**: High (Flux image automation, GitHub PAT, RBAC troubleshooting)
**Outcome**: Full auto-deploy workflow functional, personal website live on cluster

---

# Session Recap - 2026-01-04 (Part 2)

## Summary

Fixed severe browser performance issues (10+ second load times) by enabling proper IPv6 networking on the home network. Root cause was IPv6-enabled clients attempting IPv6 connections first, timing out due to no IPv6 route, then falling back to IPv4.

## Problem Statement

### Symptoms
- Browser requests taking 10-15 seconds to load (especially DuckDuckGo searches, Google, Reddit)
- Speed tests showing good bandwidth (~400 Mbps down, ~30 Mbps up)
- Web browsing painfully slow despite good connectivity

### Initial Hypothesis
Suspected DNS issues (Pi-hole slow to respond or misconfigured)

### Actual Root Cause
- Mac had IPv6 enabled with link-local addresses (fe80::)
- Network had no IPv6 route to internet (upstream gateway had IPv6 disabled)
- Browsers use "Happy Eyeballs" algorithm: try IPv6 first, wait for timeout (~10s), fall back to IPv4
- The timeout waiting for IPv6 connections was causing all the delays

## Diagnostic Process

### Step 1: DNS Performance
```bash
# Tested DNS resolution speed
time dig @192.168.1.55 google.com
# Result: ~36ms (fast, not the problem)
```

### Step 2: Network Stack Analysis
```bash
# Checked network interfaces
ifconfig en0
# Found IPv6 addresses:
#   inet6 fe80::1234:5678:90ab:cdef%en0  (link-local)
#   inet6 2600:1700:3d10:3a8f:...        (missing - should have global)
```

### Step 3: IPv6 Connectivity Test
```bash
# Attempted IPv6 ping
ping6 google.com
# Result: "No route to host" (confirmed no IPv6 route)
```

### Step 4: Network Topology Investigation
- AT&T Gateway (192.168.0.254): Already had IPv6 enabled, DHCPv6-PD enabled
  - IPv6 prefix: 2600:1700:3d10:3a80::/64
  - Ready to delegate /64 prefix to downstream routers
- Unifi Security Gateway: IPv6 completely disabled
  - No prefix delegation request
  - No IPv6 route advertisement to LAN

## Solution Implementation

### AT&T Gateway (192.168.0.254)
No changes needed - already configured correctly:
- IPv6: On
- DHCPv6: On
- DHCPv6 Prefix Delegation: On
- Has IPv6 prefix: 2600:1700:3d10:3a80::/64

### Unifi Security Gateway - WAN Settings
**Changed**:
- IPv6 Connection: Disabled → **DHCPv6**
- Prefix Delegation Size: (none) → **64**

**What this does**:
- USG requests a /64 IPv6 prefix from AT&T gateway via DHCPv6-PD
- AT&T delegates 2600:1700:3d10:3a8f::/64 to USG
- USG now has global IPv6 addresses on WAN interface

### Unifi Security Gateway - LAN Settings
**Changed**:
- IPv6 Interface Type: (none) → **Prefix Delegation**
- IPv6 RA (Router Advertisement): Disabled → **Enabled**
- DHCPv6/RDNSS DNS Control: Auto → **Manual** (empty DNS fields)

**What this does**:
- Prefix Delegation: USG uses the /64 it received to assign IPv6 to LAN
- IPv6 RA: Enables SLAAC (Stateless Address Autoconfiguration)
  - Required for Android devices (they don't support DHCPv6)
  - Advertises 2600:1700:3d10:3a8f::/64 prefix to LAN clients
  - Clients auto-generate IPv6 addresses using SLAAC
- RDNSS DNS Control Manual (empty): Prevents USG from advertising itself as DNS server
  - Clients use DHCPv4-assigned DNS (Pi-hole at 192.168.1.55)
  - Pi-hole remains sole DNS server for the network

## Results

### IPv6 Connectivity
```bash
# Mac now has global IPv6 address
ifconfig en0 | grep inet6
# inet6 2600:1700:3d10:3a8f:14a2:8e0c:f27d:9fa3 prefixlen 64 autoconf secured

# IPv6 ping works
ping6 google.com
# PING6(56=40+8+8 bytes) 2600:1700:3d10:3a8f:... --> 2607:f8b0:4004:c07::71
# 64 bytes from 2607:f8b0:4004:c07::71: icmp_seq=0 ttl=116 time=5.234 ms
```

### Pi-hole DNS Functioning Correctly
```bash
# Pi-hole blocks ads via IPv4 (no IPv6 blocking configured yet)
dig @192.168.1.55 doubleclick.net A
# ANSWER: 0.0.0.0 (blocked)

dig @192.168.1.55 doubleclick.net AAAA
# ANSWER: ::1 (blocked via IPv6)
```

### Browser Performance
```bash
# Before fix: 10,000+ ms total time (mostly waiting for IPv6 timeout)
# After fix:
time curl -I https://duckduckgo.com
# DNS: 3ms
# Connect: 45ms
# Total: 97ms
```

### Interesting Finding
IPv6 is actually faster than IPv4 on this network:
```bash
# IPv4 to Google
ping 8.8.8.8
# time=~1100ms (possibly VPN routing or traffic shaping)

# IPv6 to Google
ping6 2001:4860:4860::8888
# time=~5ms (direct routing)
```

## Network Topology

### Before Fix
```
AT&T Gateway (IPv6: On, DHCPv6-PD: On)
    │ No delegation (USG not requesting)
    ▼
Unifi USG (IPv6: Disabled)
    │ No IPv6 route
    ▼
LAN Devices (IPv6 link-local only, no internet route)
    │ Browser tries IPv6 → timeout after 10s → fallback to IPv4
    ▼
Slow browsing experience
```

### After Fix
```
AT&T Gateway (192.168.0.254)
  IPv6 Prefix: 2600:1700:3d10:3a80::/60 (from AT&T Fiber)
    │ DHCPv6 Prefix Delegation (/64)
    ▼
Unifi USG (WAN: 192.168.0.133, LAN: 192.168.1.1)
  WAN: DHCPv6 client (requests /64 prefix)
  LAN: Prefix Delegation (advertises 2600:1700:3d10:3a8f::/64)
       IPv6 RA: Enabled (SLAAC for clients)
       RDNSS: Empty (no DNS advertisement)
    │ SLAAC advertisements
    ▼
LAN Devices (2600:1700:3d10:3a8f::*/64)
  DHCPv4 assigns DNS: 192.168.1.55 (Pi-hole)
  SLAAC assigns IPv6 address
    │ DNS queries (IPv4 and IPv6)
    ▼
Pi-hole (192.168.1.55) → Unbound → Internet
  Handles both A (IPv4) and AAAA (IPv6) queries
  Ad blocking works for both protocols
```

## Key Configuration Details

### AT&T Fiber IPv6 Prefix Delegation
- AT&T provides /60 prefix to customer gateway
- Customer can delegate multiple /64 subnets to downstream routers
- Our allocation: 2600:1700:3d10:3a80::/60 → 2600:1700:3d10:3a8f::/64 (one of 16 available /64s)

### SLAAC vs DHCPv6
**Why SLAAC?**
- Android devices don't support DHCPv6 for address assignment
- SLAAC is universal (all modern OSes support it)
- Simpler configuration (no DHCP server needed for IPv6 addresses)

**How SLAAC Works**:
1. Router advertises prefix via Router Advertisement (RA) messages
2. Client generates IPv6 address using prefix + MAC-derived interface ID
3. Address is auto-configured, no DHCP transaction needed

### DNS Advertisement Strategy
**Why disable RDNSS?**
- RDNSS (Router Advertisement DNS Server) would advertise USG as DNS server
- Clients would use USG for DNS instead of Pi-hole
- Would bypass ad blocking

**Solution**:
- DHCPv4 continues to advertise Pi-hole (192.168.1.55) as DNS server
- RDNSS left empty (USG doesn't advertise DNS via IPv6 RA)
- Clients get IPv6 address via SLAAC but use Pi-hole for all DNS queries

### Pi-hole IPv6 DNS Blocking
Pi-hole handles both IPv4 and IPv6 DNS queries:
- A records (IPv4): Returns 0.0.0.0 for blocked domains
- AAAA records (IPv6): Returns ::1 for blocked domains
- Ad blocking works seamlessly for dual-stack clients

## Architecture Changes

### Updated Network Diagram
```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Home Network (Dual-Stack)                       │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                     AT&T Gateway (192.168.0.254)                 │  │
│  │                                                                  │  │
│  │  IPv4: 192.168.0.0/24 DHCP server                               │  │
│  │  IPv6: 2600:1700:3d10:3a80::/60 (from AT&T Fiber)               │  │
│  │        DHCPv6-PD: Enabled (delegates /64 to downstream)         │  │
│  └──────────────────────┬───────────────────────────────────────────┘  │
│                         │                                              │
│                         │ WAN (192.168.0.133)                          │
│                         │ DHCPv6-PD requests /64                       │
│                         ▼                                              │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │              Unifi Security Gateway (192.168.1.1)                │  │
│  │                                                                  │  │
│  │  IPv4 LAN: 192.168.1.0/24                                       │  │
│  │  IPv6 LAN: 2600:1700:3d10:3a8f::/64 (from PD)                   │  │
│  │            Router Advertisement (RA): Enabled                    │  │
│  │            SLAAC: Enabled for client auto-config                 │  │
│  │            RDNSS: Empty (no DNS advertisement)                   │  │
│  └──────────────────────┬───────────────────────────────────────────┘  │
│                         │                                              │
│                         │ SLAAC (IPv6) + DHCPv4                        │
│                         ▼                                              │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    LAN Clients (Dual-Stack)                      │  │
│  │                                                                  │  │
│  │  Mac Example:                                                    │  │
│  │  - IPv4: 192.168.1.200 (from DHCP)                               │  │
│  │  - IPv6: 2600:1700:3d10:3a8f:14a2:8e0c:f27d:9fa3 (from SLAAC)   │  │
│  │  - DNS: 192.168.1.55 (Pi-hole, from DHCPv4)                      │  │
│  │                                                                  │  │
│  │  All devices get:                                                │  │
│  │  - IPv6 via SLAAC (auto-configured)                              │  │
│  │  - IPv4 via DHCP (192.168.1.x/24)                                │  │
│  │  - DNS from DHCPv4 option (192.168.1.55)                         │  │
│  └──────────────────────┬───────────────────────────────────────────┘  │
│                         │                                              │
│                         │ DNS queries (A + AAAA records)               │
│                         ▼                                              │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                   Pi-hole (192.168.1.55)                         │  │
│  │                                                                  │  │
│  │  Listens on: 0.0.0.0:53 (all IPv4 interfaces)                   │  │
│  │  Handles: A records (IPv4) + AAAA records (IPv6 DNS queries)    │  │
│  │  Blocks: Returns 0.0.0.0 (A) or ::1 (AAAA) for ads/trackers     │  │
│  └──────────────────────┬───────────────────────────────────────────┘  │
│                         │                                              │
│                         │ Forwarded queries                            │
│                         ▼                                              │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                   Unbound (Recursive DNS)                        │  │
│  │                                                                  │  │
│  │  Resolves: Both A (IPv4) and AAAA (IPv6) queries recursively    │  │
│  │  DNSSEC: Validates both IPv4 and IPv6 responses                 │  │
│  └──────────────────────┬───────────────────────────────────────────┘  │
│                         │                                              │
│                         │ Recursive resolution (IPv4 + IPv6)           │
│                         ▼                                              │
│                   Root DNS Servers → TLD → Authoritative              │
└─────────────────────────────────────────────────────────────────────────┘
```

## Key Decisions

### Decision 1: Enable IPv6 Instead of Disabling on Clients

**What**: Enable proper IPv6 routing on network instead of disabling IPv6 on Mac
**Why**:
- IPv6 is the future of networking (IPv4 address exhaustion)
- Many services prioritize IPv6 (faster routing, better performance)
- Disabling IPv6 on clients is a workaround, not a solution
- Proper dual-stack networking is best practice

**How**:
- Enabled DHCPv6-PD on Unifi USG WAN
- Enabled Prefix Delegation and Router Advertisement on USG LAN
- Clients auto-configure via SLAAC

**Trade-offs**:
- More complex network configuration
- Pi-hole must handle both IPv4 and IPv6 DNS queries
- But: better performance, future-proof, no client-side workarounds needed

### Decision 2: SLAAC for Address Assignment (Not DHCPv6)

**What**: Use SLAAC for IPv6 address assignment instead of DHCPv6
**Why**:
- Android devices don't support DHCPv6 for address assignment
- SLAAC is universally supported across all modern OSes
- Simpler configuration (no DHCPv6 server needed)
- Standard practice for residential networks

**How**:
- Enabled IPv6 RA (Router Advertisement) on USG LAN
- USG advertises prefix via RA messages
- Clients auto-generate addresses using advertised prefix

**Trade-offs**:
- Less control over address assignment (clients self-assign)
- No central database of address-to-device mappings
- But: universal compatibility, simpler configuration, works on all devices

### Decision 3: Empty RDNSS (Use DHCPv4 for DNS)

**What**: Set RDNSS DNS Control to Manual with empty DNS fields
**Why**:
- Pi-hole must remain the sole DNS server for ad blocking
- RDNSS would advertise USG as DNS server, bypassing Pi-hole
- DHCPv4 already advertises Pi-hole as DNS server

**How**:
- USG LAN: DHCPv6/RDNSS DNS Control = Manual (empty)
- DHCPv4 continues to advertise 192.168.1.55 (Pi-hole)
- Clients use Pi-hole for all DNS queries (IPv4 and IPv6)

**Trade-offs**:
- Mixed configuration (IPv6 addresses from SLAAC, DNS from DHCPv4)
- Not "pure" IPv6 autoconfiguration
- But: preserves Pi-hole ad blocking, single DNS source of truth

## Performance Impact

### Before Fix
| Metric | Value | Impact |
|--------|-------|--------|
| DNS resolution | 36ms | Fast (not the problem) |
| IPv6 connection attempt | 10,000ms | Timeout waiting for route |
| Total page load | 10,000+ ms | Unusable browsing experience |

### After Fix
| Metric | Value | Impact |
|--------|-------|--------|
| DNS resolution | 3-36ms | Fast |
| IPv6 connection attempt | 5-50ms | Immediate response |
| Total page load | 97-200ms | Normal browsing experience |

### Bandwidth Impact
No change in bandwidth (still ~400 Mbps down, ~30 Mbps up) - the issue was latency, not throughput.

## Issues Encountered

### Issue 1: AT&T Gateway Already Configured

**Expected**: Would need to enable IPv6 on AT&T gateway
**Actual**: IPv6, DHCPv6, and DHCPv6-PD already enabled
**Resolution**: No changes needed on AT&T gateway side

### Issue 2: RDNSS Would Bypass Pi-hole

**Problem**: Default RDNSS "Auto" setting advertises USG as DNS server
**Impact**: Clients would bypass Pi-hole for DNS, losing ad blocking
**Resolution**: Set RDNSS to Manual with empty DNS fields

## Verification

### IPv6 Connectivity
```bash
# Global IPv6 address assigned
ifconfig en0 | grep inet6 | grep -v fe80
# inet6 2600:1700:3d10:3a8f:14a2:8e0c:f27d:9fa3 prefixlen 64 autoconf

# IPv6 ping successful
ping6 google.com
# 64 bytes from ...: icmp_seq=0 ttl=116 time=5.234 ms

# IPv6 routing table
netstat -rn -f inet6 | grep default
# default   fe80::ea9f:80ff:feee:aa06%en0   UGcg   en0
```

### Pi-hole DNS Handling Both Protocols
```bash
# IPv4 query (A record)
dig @192.168.1.55 google.com A
# ANSWER: 142.250.80.46 (allowed)

# IPv6 query (AAAA record)
dig @192.168.1.55 google.com AAAA
# ANSWER: 2607:f8b0:4004:c07::71 (allowed)

# Ad blocking (IPv4)
dig @192.168.1.55 doubleclick.net A
# ANSWER: 0.0.0.0 (blocked)

# Ad blocking (IPv6)
dig @192.168.1.55 doubleclick.net AAAA
# ANSWER: ::1 (blocked)
```

### Browser Performance
```bash
# DuckDuckGo search (previously 10+ seconds)
time curl -I https://duckduckgo.com
# Total: 0.097s

# Google search (previously 10+ seconds)
time curl -I https://www.google.com
# Total: 0.123s
```

## Documentation Updates Needed

- [x] Update ARCHITECTURE.md with IPv6 network configuration
- [x] Add network topology diagrams showing dual-stack setup
- [x] Document DNS flow for both IPv4 and IPv6 queries
- [x] Document Unifi USG IPv6 configuration in CLAUDE.md (if relevant)
- [ ] Add troubleshooting guide for IPv6 connectivity issues

## Future Enhancements

- [ ] Configure Pi-hole for IPv6 blocklists (currently only IPv4 blocking)
- [ ] Add Prometheus metrics for IPv6 vs IPv4 query ratios
- [ ] Test IPv6-only connectivity (disable IPv4 temporarily)
- [ ] Document IPv6 firewall rules on USG (if needed)

## Lessons Learned

1. **Happy Eyeballs Can Hurt**: Modern browsers trying IPv6 first is great when it works, painful when it doesn't
2. **Dual-Stack is Complex**: Managing both IPv4 and IPv6 requires careful DNS/DHCP coordination
3. **RDNSS Can Bypass Pi-hole**: Router Advertisement DNS must be explicitly disabled to preserve ad blocking
4. **IPv6 Can Be Faster**: In this network, IPv6 had 5ms latency vs 1100ms for IPv4 to Google
5. **Diagnostic Order Matters**: Testing DNS first ruled out Pi-hole as the problem, pointed to network stack

## References

- RFC 4861: Neighbor Discovery for IPv6 (Router Advertisement)
- RFC 4862: IPv6 Stateless Address Autoconfiguration (SLAAC)
- RFC 8106: IPv6 Router Advertisement Options for DNS Configuration (RDNSS)
- Unifi USG IPv6 Configuration: https://help.ui.com/hc/en-us/articles/204976244-UniFi-Gateway-USG-Advanced-Configuration
- Happy Eyeballs RFC 8305: https://datatracker.ietf.org/doc/html/rfc8305

---

**Session Duration**: ~1 hour
**Complexity**: Medium (network troubleshooting, IPv6 configuration)
**Outcome**: Severe browser performance issues resolved, full dual-stack IPv6 networking enabled
**Performance Improvement**: 10,000ms → 97ms page load times (99% reduction)
