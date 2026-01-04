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
