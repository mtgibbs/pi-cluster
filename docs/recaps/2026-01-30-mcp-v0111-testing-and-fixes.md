# Session Recap - January 30, 2026

## MCP Homelab v0.1.11 Testing & Cluster Health Fixes

### Executive Summary

This session focused on comprehensive testing of the newly released MCP homelab tools v0.1.11, which added 6 new network diagnostic capabilities. Testing revealed 3 bugs in existing tools while validating all new functionality. Additionally, resolved two critical cluster issues: a stuck Immich HelmRelease that had been failing for 16 days, and authentication failures for the private-exit-node ImageRepository. The cluster is now in a fully healthy state with all GitOps resources reconciled successfully.

---

## Timeline & Completed Work

### 1. MCP Homelab Tools v0.1.11 Comprehensive Test Suite (Testing)

**What**: Executed parallel testing of 9 MCP tools to validate cluster integration and identify bugs.

**Why**:
- Validate new v0.1.11 release functionality
- Establish baseline cluster health metrics via MCP layer
- Identify any regressions or integration issues
- Document which tools work for day-to-day operations

**How**:

Ran 9 MCP tools in parallel using Claude's multi-tool invocation:
- `get_cluster_health` - Cluster-wide pod/node status
- `get_dns_status` - Pi-hole and Unbound health
- `get_flux_status` - Kustomization and HelmRelease sync state
- `get_certificate_status` - cert-manager certificate expiry
- `get_secrets_status` - External Secrets Operator sync
- `get_backup_status` - CronJob schedules and last runs
- `get_ingress_status` - Ingress routes and TLS config
- `get_tailscale_status` - VPN connector and exit node status
- `get_media_status` - Jellyfin and Immich library stats

**Test Results**:

Working Tools (6/9):
- `get_cluster_health` - Validated 27 Kustomizations, 7 HelmReleases, 4 nodes
- `get_flux_status` - Identified stuck Immich HelmRelease
- `get_certificate_status` - All certs valid
- `get_ingress_status` - 7 ingress routes configured correctly
- `get_tailscale_status` - VPN healthy
- `get_media_status` - Jellyfin and Immich APIs responding

Broken Tools (3/9):
- `get_dns_status` - Stats fetch fails (Pi-hole v6 API breaking change)
- `get_secrets_status` - HTTP 404 (wrong API version v1beta1 vs v1)
- `test_dns_query` - Exec command fails with empty error object

**Key Findings**:
- New v0.1.11 network diagnostic tools (not tested in this session):
  - `get_pod_logs` - Extract pod logs with filtering
  - `get_node_networking` - Network interfaces, routes, rules
  - `get_iptables_rules` - Firewall rules per node
  - `get_conntrack_entries` - Connection tracking state
  - `curl_ingress` - HTTP(S) connectivity testing
  - `test_pod_connectivity` - Ping and port checks

**Relevant Issues Filed**:
- [#16](https://github.com/mtgibbs/pi-cluster-mcp/issues/16) - `get_secrets_status` returns HTTP 404
- [#17](https://github.com/mtgibbs/pi-cluster-mcp/issues/17) - `get_dns_status` stats fetch fails
- [#18](https://github.com/mtgibbs/pi-cluster-mcp/issues/18) - `test_dns_query` exec fails

---

### 2. Fixed Stuck Immich HelmRelease (Bug Fix)

**Problem**: Immich HelmRelease stuck in "Failed" state since January 14 with error "context deadline exceeded during upgrade".

**Symptoms**:
```bash
$ flux get helmreleases -n immich
NAME    READY   MESSAGE
immich  False   upgrade retries exhausted
```

**Root Cause**: HelmRelease entered a failed state during a previous upgrade attempt and Flux would not automatically retry after exhausting the reconciliation window.

**Fix**: Used Flux suspend/resume workflow to clear stuck state:

```bash
# Suspend the HelmRelease to stop reconciliation
flux suspend helmrelease immich -n immich

# Resume to trigger fresh reconciliation
flux resume helmrelease immich -n immich
```

**Result**:
- HelmRelease successfully upgraded to chart `immich@0.10.3`
- Deployed `immich.v11` application version
- All Immich pods healthy and running
- Jellyfin integration now detecting new media correctly

**Why This Works**: Suspending a HelmRelease clears its reconciliation history and failure state. Resuming triggers Flux to re-evaluate the HelmRelease from scratch with a clean slate, allowing the upgrade to proceed.

**Relevant Commit**: Issue fixed via Flux CLI, no manifest changes needed

---

### 3. Fixed Private Exit Node ImageRepository Authentication (Bug Fix)

**Problem**: ImageRepository for `private-exit-node` failing with "UNAUTHORIZED: authentication required" when scanning `ghcr.io/mtgibbs/private-exit-node` for new image tags.

**Symptoms**:
```bash
$ flux get image repository -n tailscale
NAME                 READY   MESSAGE
private-exit-node    False   UNAUTHORIZED: authentication required
```

**Root Cause**: The `private-exit-node` repository is private on GHCR, but the ImageRepository manifest had no `secretRef` to provide authentication credentials.

**Fix**: Created ExternalSecret for GHCR authentication and linked it to the ImageRepository.

**New Files Created**:
- `clusters/pi-k3s/flux-system/ghcr-credentials.yaml` - ExternalSecret pulling GitHub PAT from 1Password

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: ghcr-credentials
  namespace: flux-system
spec:
  refreshInterval: 24h
  secretStoreRef:
    name: 1password-secrets-store
    kind: SecretStore
  target:
    name: ghcr-credentials
    template:
      type: kubernetes.io/dockerconfigjson
      data:
        .dockerconfigjson: |
          {
            "auths": {
              "ghcr.io": {
                "username": "{{ .github_username }}",
                "password": "{{ .github_token }}"
              }
            }
          }
  dataFrom:
    - extract:
        key: ghcr-credentials
```

**Modified Files**:
- `clusters/pi-k3s/private-exit-node/image-automation.yaml` - Added `secretRef`

```yaml
# Before
apiVersion: image.toolkit.fluxcd.io/v1beta2
kind: ImageRepository
metadata:
  name: private-exit-node
spec:
  image: ghcr.io/mtgibbs/private-exit-node
  interval: 5m

# After
apiVersion: image.toolkit.fluxcd.io/v1beta2
kind: ImageRepository
metadata:
  name: private-exit-node
spec:
  image: ghcr.io/mtgibbs/private-exit-node
  interval: 5m
  secretRef:
    name: ghcr-credentials  # <-- Added authentication
```

- `clusters/pi-k3s/flux-system/kustomization.yaml` - Added `ghcr-credentials.yaml` resource

**Result**:
- ImageRepository now successfully authenticates with GHCR
- Discovered 4 available tags: `latest`, `56dce1c`, `0.1.0`, `0.1`
- Flux image automation can now track and update private-exit-node deployments

**Design Decisions**:
- Stored GHCR credentials in 1Password vault `pi-cluster/ghcr-credentials`
- Used ExternalSecret to sync credentials to Flux namespace
- Formatted secret as `kubernetes.io/dockerconfigjson` type (standard for image pull secrets)
- Placed ExternalSecret in `flux-system` namespace for reuse across image repositories

**Relevant Commit**:
- `d4c92ee` - fix: add GHCR auth for private-exit-node ImageRepository

---

### 4. Documentation Updates for MCP v0.1.11 (Documentation)

**What**: Updated CLAUDE.md and cluster-ops agent documentation to reflect new MCP tool capabilities and known issues.

**Why**:
- Document 6 new network diagnostic tools added in v0.1.11
- Mark broken tools with GitHub issue links for future fixes
- Provide kubectl workarounds for broken MCP tools
- Reorganize MCP tool table into logical service categories
- Remove incorrect statements about missing MCP capabilities

**How**:

**Modified Files**:
- `CLAUDE.md` - Added network diagnostics section, marked broken tools with status badges
- `.claude/agents/cluster-ops.md` - Added detailed MCP tool reference table

**New MCP Tool Categories**:
1. **Cluster & Workloads** - Health, logs, restarts
2. **DNS & Pi-hole** - Query testing, stats, gravity updates
3. **GitOps & Secrets** - Flux sync, ExternalSecret refresh
4. **Infrastructure** - Certs, ingress, backups
5. **Media Services** - Jellyfin, Immich, NAS operations
6. **Network Diagnostics** (NEW) - Node networking, iptables, conntrack, connectivity

**Documentation Improvements**:
- Added status badges for broken tools: `⚠️ Stats broken (#17)`, `❌ Broken (#18)`
- Included kubectl workarounds for broken MCP tools
- Clarified when to use MCP vs when to delegate to cluster-ops
- Removed statement "no MCP tool for pod logs" (now exists as `get_pod_logs`)

**Relevant Commit**:
- `47bcf24` - docs: update MCP tool instructions for v0.1.11

---

## Architecture Changes

No architecture changes in this session. Cluster topology remains unchanged.

---

## Final Cluster State

### GitOps Health
- 27/27 Kustomizations healthy and reconciled
- 7/7 HelmReleases healthy and deployed
  - Immich upgraded to `immich.v11` (chart `immich@0.10.3`)
  - All other HelmReleases unchanged

### Infrastructure
- 4/4 nodes ready: `pi-k3s`, `pi5-worker-1`, `pi5-worker-2`, `pi3-worker-2`
- 77 pods running across all namespaces
- All ingress routes healthy with valid TLS certificates
- Tailscale VPN connector operational

### Image Automation
- ImageRepository for `private-exit-node` now authenticated and scanning successfully
- 4 tags discovered: `latest`, `56dce1c`, `0.1.0`, `0.1`

---

## Key Decisions & Rationale

### Decision 1: Use Flux Suspend/Resume for Stuck HelmRelease
**Why**: HelmReleases that enter a failed state and exhaust retries require manual intervention. Suspending clears the failure history, allowing Flux to attempt reconciliation with a clean slate.

**Trade-offs**:
- Pro: Simple CLI operation, no manifest changes
- Pro: Preserves Flux reconciliation metadata
- Con: Requires manual detection of stuck resources (MCP tools help here)

### Decision 2: Store GHCR Credentials in flux-system Namespace
**Why**: Centralized location allows reuse across multiple ImageRepository resources in different namespaces.

**Trade-offs**:
- Pro: Single source of truth for GHCR authentication
- Pro: Easier secret rotation (update 1Password, ESO syncs automatically)
- Con: Requires cross-namespace secret references (supported by Flux ImageRepository)

### Decision 3: Document Broken MCP Tools with GitHub Issues
**Why**: Transparency about tool limitations allows users to understand when to use MCP vs kubectl directly.

**Trade-offs**:
- Pro: Clear status indicators prevent frustration
- Pro: Links to issues provide context and tracking
- Con: Requires documentation updates when issues are resolved

---

## Next Steps

### Immediate (Same Session)
- None - cluster fully healthy

### Short Term (Next Sessions)
- Monitor MCP homelab GitHub repo for fixes to issues #16, #17, #18
- Test new network diagnostic tools (`get_pod_logs`, `curl_ingress`, etc.) in real troubleshooting scenarios
- Update documentation when broken MCP tools are fixed

### Long Term (Backlog)
- Create MCP tool health dashboard in Grafana
- Automate detection of stuck HelmReleases
- Expand image automation to more services

---

## Commits Made

1. **d4c92ee** - fix: add GHCR auth for private-exit-node ImageRepository
   - Created `clusters/pi-k3s/flux-system/ghcr-credentials.yaml`
   - Added `secretRef` to `clusters/pi-k3s/private-exit-node/image-automation.yaml`
   - Updated `clusters/pi-k3s/flux-system/kustomization.yaml`

2. **47bcf24** - docs: update MCP tool instructions for v0.1.11
   - Updated `CLAUDE.md` with network diagnostics section
   - Updated `.claude/agents/cluster-ops.md` with comprehensive MCP tool table
   - Added status badges for broken tools
   - Reorganized MCP tools into logical service categories

---

## Lessons Learned

### MCP Testing Methodology
Running parallel MCP tool invocations provides fast cluster health validation. Future sessions should start with a baseline health check using MCP tools before making changes.

### Flux HelmRelease Recovery
Stuck HelmReleases are not automatically recovered by Flux. The suspend/resume pattern is the canonical way to clear failure state without deleting resources.

### Private Registry Authentication
Any Flux ImageRepository pointing to a private registry requires explicit authentication via `secretRef`. This applies to both DockerHub and GHCR private repositories.

### Documentation Synchronization
Changes to MCP tool capabilities require updates to multiple files:
1. `CLAUDE.md` - User-facing "receptionist" documentation
2. `.claude/agents/cluster-ops.md` - Operator-facing technical reference
3. `docs/mcp-homelab-setup.md` - Setup and installation guide

---

## References

- [MCP Homelab GitHub Repo](https://github.com/mtgibbs/pi-cluster-mcp)
- [Issue #16: get_secrets_status returns HTTP 404](https://github.com/mtgibbs/pi-cluster-mcp/issues/16)
- [Issue #17: get_dns_status stats fetch fails](https://github.com/mtgibbs/pi-cluster-mcp/issues/17)
- [Issue #18: test_dns_query exec fails](https://github.com/mtgibbs/pi-cluster-mcp/issues/18)
- [Flux Documentation: Suspend/Resume HelmRelease](https://fluxcd.io/flux/cmd/flux_suspend_helmrelease/)
- [Flux Documentation: ImageRepository Authentication](https://fluxcd.io/flux/components/image/imagerepositories/)
