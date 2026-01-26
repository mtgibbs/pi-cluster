# Session Recap - January 23-26, 2026

## Session Overview

This multi-day session began with troubleshooting a Jellyfin media visibility issue and evolved into a significant infrastructure enhancement: designing, building, and deploying a custom Model Context Protocol (MCP) server for the Pi K3s homelab cluster.

## Timeline

### January 23, 2026 - Jellyfin Troubleshooting

**Problem**: "Better Off Ted" TV series was downloaded and visible on the Synology NAS at the correct path (`/volume1/video/tvshows/Better Off Ted`), but did not appear in Jellyfin's library after multiple refresh attempts.

**Root Cause**: The show existed in Jellyfin's SQLite database but had NULL values for critical metadata fields (specifically `DateLastRefreshed`). This indicated an interrupted or failed metadata fetch from TVDB. Jellyfin's UI filters out items with incomplete metadata, making them invisible despite being in the database.

**Solution**: Two approaches were documented:
1. UI-based: Navigate to the item (if visible) and force metadata refresh with "Replace all metadata" checked
2. API-based: Query the database to find the item ID, then use Jellyfin's API to trigger a full metadata refresh

```bash
# Find the item in the database
kubectl -n jellyfin exec -it deploy/jellyfin -- sqlite3 /config/data/library.db \
  "SELECT Id, Name FROM TypedBaseItems WHERE Name LIKE '%Better Off Ted%' AND Type LIKE '%Series%';"

# Trigger metadata refresh via API
kubectl -n jellyfin exec -it deploy/jellyfin -- curl -X POST \
  "http://localhost:8096/Items/ITEM_ID/Refresh?metadataRefreshMode=FullRefresh&imageRefreshMode=FullRefresh" \
  -H "X-Emby-Token: API_KEY"
```

**Outcomes**:
- Created `/fix-jellyfin` slash command (commit `14:53:46 Jan 23`)
- Updated `.claude/skills/media-services/SKILL.md` with troubleshooting documentation
- Added this pattern to institutional knowledge for future incidents

---

### January 26, 2026 - MCP Server Design & Implementation

**What**: Built a production-grade Model Context Protocol server to provide structured, safe cluster operations for Claude Desktop and CLI.

**Why**: Several pain points motivated this:
1. Repetitive manual kubectl commands for common tasks
2. Knowledge scattered across skills and docs requiring constant lookups
3. No structured way for AI assistants to interact with the cluster safely
4. Desire to enable faster troubleshooting and cluster management
5. Learning opportunity for MCP protocol and TypeScript/K8s integration

**How**: Multi-phase approach spanning design, implementation, deployment, and integration.

---

## Phase 1: Architecture & Planning (Morning)

### Design Decisions

Created comprehensive planning documents capturing:
- Tool taxonomy (diagnostics vs. actions)
- Security model (defense in depth)
- RBAC requirements
- Transport options (stdio vs. SSE)
- Development workflow

**Key Documents Created**:
- `docs/plans/homelab-mcp-CLAUDE.md` - Project overview and tool reference
- `docs/plans/homelab-mcp-cluster-integration.md` - Deployment architecture

### Security Model

**Decision**: Three-layer defense in depth approach

**Rationale**: Single-layer security (just RBAC or just API key) is insufficient for a tool with write capabilities.

**Implementation**:
1. **Network Layer**: Ingress only accessible via Tailscale VPN
2. **Application Layer**: API key authentication required in `X-API-Key` header
3. **Kubernetes Layer**: Minimal RBAC with explicit allow-list

**Trade-offs**:
- Increased complexity (API key rotation process)
- Better security posture (three independent failures needed for compromise)
- Operational overhead (key management, Tailscale dependency)

### RBAC Permissions

**Decision**: Read-only by default, explicit limited writes

**Allowed Reads**:
- Core resources (pods, services, nodes, events, configmaps, PVCs)
- App resources (deployments, statefulsets, daemonsets)
- Flux resources (kustomizations, helmreleases, sources, images)
- Cert-manager (certificates, challenges, issuers)
- External Secrets (status only)
- Networking (ingresses)
- Tailscale (connectors)
- Batch (jobs, cronjobs)
- Metrics

**Allowed Writes** (patch only, no creates/deletes):
- Patch deployments (for `kubectl rollout restart`)
- Patch Flux resources (for reconcile triggers)
- Patch ExternalSecrets (for force refresh)
- Create jobs (for manual backup triggers)
- Create pods/exec (jellyfin namespace only, for metadata fixes)

**Explicitly Denied**:
- Delete on any resource
- Create pods/deployments/services
- Access to Secret values
- Node operations (cordon, drain)
- Namespace deletion

**Trade-offs**:
- Cannot auto-remediate severe issues (e.g., deleting failed pods)
- Safe against accidental destruction
- Limits usefulness in emergency scenarios vs. safety in day-to-day use

### Deployment Whitelist

**Decision**: Hard-coded whitelist of deployments that can be restarted

**Allowed**:
- `jellyfin/jellyfin`
- `pihole/pihole`
- `pihole/unbound`
- `immich/immich-server`
- `homepage/homepage`
- `uptime-kuma/uptime-kuma`

**Rationale**: Even with RBAC restrictions, prevent accidental restarts of critical infrastructure (Flux, cert-manager, external-secrets-operator).

**Trade-offs**:
- Must update code to add new services (not dynamic)
- Complete protection against accidental restarts of critical services
- Simple enforcement at application layer

---

## Phase 2: Server Implementation (External Repo)

Built the MCP server in a separate repository (`mtgibbs/pi-cluster-mcp`) with:

**Tech Stack**:
- TypeScript with @modelcontextprotocol/sdk
- @kubernetes/client-node for in-cluster operations
- node-ssh for Synology NAS operations
- Multi-stage Docker build
- GitHub Actions CI/CD

**Tools Implemented**:

Diagnostic (Read-Only):
- `get_cluster_health` - Nodes, resource usage, problem pods
- `get_dns_status` - Pi-hole + Unbound health
- `get_flux_status` - GitOps sync state
- `get_certificate_status` - TLS cert health
- `get_secrets_status` - ExternalSecret sync status
- `get_backup_status` - Backup job schedules
- `get_ingress_status` - Ingress health
- `get_tailscale_status` - VPN connector status
- `get_media_status` - Jellyfin/Immich health

Action Tools:
- `reconcile_flux` - Trigger Flux sync
- `restart_deployment` - Rollout restart (whitelisted only)
- `fix_jellyfin_metadata` - Database query + API refresh
- `trigger_backup` - Create Job from CronJob
- `test_dns_query` - Run dig against Pi-hole
- `refresh_secret` - Force ExternalSecret resync
- `touch_nas_path` - SSH to NAS, touch file

**CI/CD**:
- GitHub Actions builds multi-arch container (arm64/amd64)
- Published to ghcr.io/mtgibbs/pi-cluster-mcp
- Semantic versioning via git tags

---

## Phase 3: Cluster Integration (Commit: 89e6974)

**What**: Deployed MCP server to K3s cluster with full GitOps workflow

**Manifests Created** (`clusters/pi-k3s/mcp-homelab/`):
- `namespace.yaml` - Dedicated namespace
- `serviceaccount.yaml` - K8s identity
- `clusterrole.yaml` + binding - RBAC permissions (122 lines)
- `deployment.yaml` - Container spec with health checks
- `service.yaml` - ClusterIP service on port 3000
- `ingress.yaml` - HTTPS at `mcp.lab.mtgibbs.dev`
- `external-secret.yaml` - 1Password integration for API key
- `image-automation.yaml` - Auto-updates on new semver tags

**1Password Secrets**:
- `mcp-homelab/api-key` - API key for client authentication
- `synology-mcp-ssh/private-key` - SSH key for NAS operations
- `jellyfin-api-key/api-key` - Jellyfin API authentication

**Flux Integration**:
- Added to `clusters/pi-k3s/flux-system/infrastructure.yaml`
- ImageRepository scanning ghcr.io/mtgibbs/pi-cluster-mcp
- ImagePolicy for semver tags (^0.1.0)
- ImageUpdateAutomation commits new versions automatically

---

## Phase 4: Debugging & Fixes (Commits: 24fe98f)

**Issue**: MCP server deployed successfully but Claude Desktop couldn't connect

**Root Cause**: Transport mismatch between client configuration and server implementation

**Problem Details**:
- Client registered with `transport: sse` (Server-Sent Events)
- Server implemented HTTP JSON-RPC transport
- MCP SDK supports both but requires matching on client/server

**Fix**: Updated deployment manifest

```yaml
# Before
env:
  - name: MCP_TRANSPORT
    value: "sse"

# After
env:
  - name: MCP_TRANSPORT
    value: "http"
```

**Client Registration**:
```bash
claude mcp add homelab https://mcp.lab.mtgibbs.dev/mcp \
  -s local -t http \
  -H "X-API-Key:${MCP_HOMELAB_API_KEY}"
```

**Verification**:
```bash
curl -X POST https://mcp.lab.mtgibbs.dev/mcp \
  -H "Content-Type: application/json" \
  -H "X-API-Key:${MCP_HOMELAB_API_KEY}" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0.0"}}}'
```

---

## Phase 5: Client Setup & Documentation (Commit: 11f111e)

**What**: Documented MCP client setup and operational procedures

**Created**: `docs/mcp-homelab-setup.md`

**Contents**:
1. Architecture diagram (1Password → ESO → K8s, 1Password → shell → claude CLI)
2. Initial setup instructions
3. Shell environment configuration for 1Password CLI integration
4. API key rotation procedure (5-step process)
5. Troubleshooting guide

**Shell Integration**:
```bash
# ~/.zshrc
export MCP_HOMELAB_API_KEY=$(op read "op://pi-cluster/mcp-homelab/api-key" --no-newline 2>/dev/null)
```

This uses 1Password CLI with biometric authentication, loading the key on first use per shell session.

**Key Rotation Process**:
1. Generate new key: `openssl rand -hex 32`
2. Update 1Password item
3. Force ExternalSecret refresh: `kubectl annotate externalsecret mcp-homelab-secrets -n mcp-homelab force-sync=$(date +%s)`
4. Restart MCP pod: `kubectl rollout restart deployment/mcp-homelab -n mcp-homelab`
5. Re-register client: `claude mcp remove homelab && claude mcp add ...`

---

## Phase 6: Flux Automation (Commit: ca3a22d)

**What**: First automated image update deployed

**How**: Flux ImageUpdateAutomation detected new tag (0.1.1) and committed update

**Commit by**: fluxcdbot at 2026-01-26 19:23:08 UTC

This validated the complete CI/CD pipeline:
1. Developer pushes tag to pi-cluster-mcp repo
2. GitHub Actions builds container
3. Pushes to GHCR
4. Flux ImageRepository scans registry
5. ImagePolicy evaluates semver
6. ImageUpdateAutomation commits to pi-cluster repo
7. Flux reconciles deployment

---

## Architecture Diagram Updates

### MCP Integration Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    Claude Desktop / CLI                           │
│                    (Local Machine)                                │
└─────────────────────────────┬────────────────────────────────────┘
                              │
                              │ HTTPS + X-API-Key
                              │ (Tailscale Network)
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                   Ingress (mcp.lab.mtgibbs.dev)                   │
│                   Namespace: mcp-homelab                          │
└─────────────────────────────┬────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                      MCP Server Pod                               │
│  ┌────────────────┐  ┌──────────────┐  ┌────────────────────┐   │
│  │ HTTP Transport │  │ K8s Client   │  │ SSH Client (NAS)   │   │
│  │ (Port 3000)    │  │ (InCluster)  │  │ (node-ssh)         │   │
│  └────────────────┘  └──────┬───────┘  └────────┬───────────┘   │
│                             │                    │                │
│  ServiceAccount: mcp-homelab                    │                │
└─────────────────────────────┼─────────────────────┼──────────────┘
                              │                    │
                              ▼                    ▼
                    ┌──────────────────┐   ┌──────────────┐
                    │  K8s API Server  │   │ Synology NAS │
                    │  (RBAC Limited)  │   │ (SSH)        │
                    └──────────────────┘   └──────────────┘
                              │
                              ▼
                    ┌──────────────────────────────────────┐
                    │ Cluster Resources                    │
                    │ - Pods, Services, Deployments        │
                    │ - Flux (Kustomizations, HelmReleases)│
                    │ - Certificates, ExternalSecrets      │
                    │ - Ingresses, Jobs, Metrics           │
                    └──────────────────────────────────────┘

Secrets Flow (API Key):
┌──────────────────┐
│ 1Password        │
│ pi-cluster vault │
│ mcp-homelab item │
└────────┬─────────┘
         │
         ├─────────────────────────────┐
         │                             │
         ▼                             ▼
┌─────────────────┐         ┌──────────────────────┐
│ ExternalSecret  │         │ op CLI               │
│ (K8s)           │         │ (Local Shell)        │
└────────┬────────┘         └──────────┬───────────┘
         │                             │
         ▼                             ▼
┌─────────────────┐         ┌──────────────────────┐
│ K8s Secret      │         │ $MCP_HOMELAB_API_KEY │
│ (Server)        │         │ (Claude CLI Config)  │
└─────────────────┘         └──────────────────────┘
```

---

## Architectural Decision Records

### ADR-001: Build Custom MCP Server Instead of Generic Tools

**Context**: Need to enable Claude to manage the cluster without exposing full kubectl access.

**Options Considered**:
1. Generic shell access with kubectl
2. Pre-built MCP servers (if any exist for K8s)
3. Custom MCP server tailored to homelab needs

**Decision**: Build custom MCP server

**Rationale**:
- Generic shell access too risky (no guardrails)
- No existing MCP servers found with suitable feature set
- Custom server allows enforcement of security model in code
- Learning opportunity for MCP protocol
- Can evolve with cluster needs

**Consequences**:
- Maintenance burden (must update as cluster evolves)
- Complete control over security model
- Can add homelab-specific operations (NAS SSH, Jellyfin fixes)
- Better error handling and structured responses vs. raw CLI output

---

### ADR-002: Defense in Depth Security Model

**Context**: MCP server has write capabilities (restart deployments, trigger backups, force reconciles). Single security layer insufficient.

**Decision**: Three-layer security model

**Layers**:
1. **Network**: Tailscale VPN requirement
2. **Application**: API key authentication
3. **Kubernetes**: RBAC restrictions

**Rationale**:
- Tailscale prevents internet exposure
- API key prevents unauthorized Tailscale clients
- RBAC limits blast radius if API key compromised
- Each layer fails independently

**Trade-offs**:
- API key rotation requires documented procedure
- Tailscale dependency (cluster unreachable if Tailscale down)
- Increased operational complexity vs. better security posture

**Implementation Details**:
- API key stored in 1Password
- ExternalSecret syncs to cluster (server auth)
- 1Password CLI injects to shell (client auth)
- RBAC enforced by K8s API server (cannot be bypassed)

---

### ADR-003: HTTP Transport Over SSE

**Context**: MCP SDK supports both stdio (local processes) and HTTP/SSE (remote servers).

**Decision**: Use HTTP transport, not SSE

**Rationale**:
- Simpler implementation (JSON-RPC over HTTP POST)
- Standard REST-like semantics
- Easier debugging with curl
- SSE adds complexity for bidirectional communication we don't need

**Implementation**:
- Server: `MCP_TRANSPORT=http` environment variable
- Client: `claude mcp add ... -t http`
- Endpoint: `POST /mcp` with JSON-RPC payload

**Note**: Initial deployment used SSE but was corrected to HTTP after connection failures.

---

### ADR-004: Deployment Whitelist in Application Code

**Context**: RBAC allows patching deployments but need finer-grained control.

**Decision**: Hard-coded whitelist in TypeScript tool implementation

**Rationale**:
- RBAC too coarse-grained (all-or-nothing per namespace)
- ConfigMap whitelist still allows RBAC-level access if compromised
- Code-level enforcement requires redeployment to change (deliberate friction)

**Trade-offs**:
- Must update code and redeploy to add new services
- Complete protection against accidental restarts of critical infrastructure
- Simple enforcement logic (array membership check)

**Allowed Deployments**:
- User-facing services (Jellyfin, Immich, Homepage, Uptime Kuma)
- DNS infrastructure (Pi-hole, Unbound)
- Explicitly excludes: Flux, cert-manager, ESO, ingress-nginx

---

### ADR-005: Flux Image Automation for MCP Server

**Context**: MCP server will evolve rapidly during initial development.

**Decision**: Enable Flux ImageUpdateAutomation with semver policy

**Rationale**:
- Avoid manual image tag updates in Git
- Get patches/fixes automatically
- Standard GitOps workflow
- Version pinning via semver (^0.1.0)

**Configuration**:
- ImageRepository scans ghcr.io/mtgibbs/pi-cluster-mcp
- ImagePolicy: semver ^0.1.0 (minor/patch auto-update, no major bumps)
- ImageUpdateAutomation commits to main branch
- Flux reconciles automatically

**Trade-offs**:
- Potential for breaking changes if semver not respected
- Automatic updates may introduce bugs
- Fast iteration vs. manual review of each change

---

## Updated CLAUDE.md

Added MCP homelab to service index:

| Service | Expert Skill | Notes |
|---------|--------------|-------|
| MCP Homelab | `docs/mcp-homelab-setup.md` | MCP server for cluster operations |

---

## Metrics

**Commits**: 4 (excluding external pi-cluster-mcp repo)
- 1 feature (MCP deployment)
- 1 fix (transport correction)
- 1 docs (setup guide)
- 1 automated (Flux image update)

**Files Changed**: 14 files, 1,184 insertions

**New Manifests**: 10 Kubernetes manifests in `clusters/pi-k3s/mcp-homelab/`

**Documentation**: 3 new docs (2 planning, 1 operational guide)

**Skills Updated**: 1 (media-services)

**Slash Commands Created**: 1 (/fix-jellyfin)

---

## Key Learnings

### Technical

1. **MCP Protocol**: Learned Model Context Protocol SDK, tool definitions, transport options
2. **TypeScript + K8s**: Deepened knowledge of @kubernetes/client-node library
3. **In-Cluster Auth**: ServiceAccounts, RBAC, and in-cluster config
4. **Flux Image Automation**: First real-world use of ImageRepository/Policy/Automation
5. **1Password CLI**: Biometric shell integration for secret injection

### Operational

1. **Jellyfin Metadata**: NULL database fields cause invisible items
2. **Transport Mismatches**: Client/server must agree on MCP transport
3. **Defense in Depth**: Multiple security layers reduce single points of failure
4. **Whitelisting**: Application-level enforcement supplements RBAC
5. **GitOps CI/CD**: End-to-end automation from git tag to deployed pod

### Process

1. Comprehensive planning documents accelerated implementation
2. Separate repo for MCP server simplified CI/CD
3. Git commit messages captured decision rationale
4. Documentation-first approach reduced support burden

---

## Next Steps

### Immediate
- Monitor MCP server logs for errors/edge cases
- Test all diagnostic tools in real troubleshooting scenarios
- Validate API key rotation procedure

### Short-term
- Add more diagnostic tools (storage, network, logs)
- Implement resource-level tools (describe pod, get logs)
- Add unit tests for tool handlers
- Document tool usage patterns in skills

### Long-term
- Evaluate adding more action tools (scale deployments, update configs)
- Consider read-only access to Secret metadata (not values)
- Build dashboard/UI for MCP server status
- Explore GitHub integration (PR creation from cluster drift detection)

---

## Files Changed

### New Files
- `docs/mcp-homelab-setup.md` - Client setup and key rotation guide
- `docs/plans/homelab-mcp-CLAUDE.md` - MCP server project overview
- `docs/plans/homelab-mcp-cluster-integration.md` - Deployment architecture
- `clusters/pi-k3s/mcp-homelab/namespace.yaml`
- `clusters/pi-k3s/mcp-homelab/serviceaccount.yaml`
- `clusters/pi-k3s/mcp-homelab/clusterrole.yaml`
- `clusters/pi-k3s/mcp-homelab/deployment.yaml`
- `clusters/pi-k3s/mcp-homelab/service.yaml`
- `clusters/pi-k3s/mcp-homelab/ingress.yaml`
- `clusters/pi-k3s/mcp-homelab/external-secret.yaml`
- `clusters/pi-k3s/mcp-homelab/image-automation.yaml`
- `clusters/pi-k3s/mcp-homelab/kustomization.yaml`

### Modified Files
- `CLAUDE.md` - Added MCP homelab to service index
- `clusters/pi-k3s/flux-system/infrastructure.yaml` - Added mcp-homelab kustomization
- `.claude/skills/media-services/SKILL.md` - Added Jellyfin troubleshooting section

---

## Relevant Commits

```
11f111e - docs: add MCP homelab client setup and key rotation guide
24fe98f - fix: set MCP transport to http (matching server implementation)
ca3a22d - chore: update mcp-homelab to ghcr.io/mtgibbs/pi-cluster-mcp:0.1.1 (fluxcdbot)
89e6974 - feat: add MCP homelab server deployment to cluster
--- (Jan 23) ---
14:53:46 - feat: add /fix-jellyfin command for media troubleshooting
```

External repo (mtgibbs/pi-cluster-mcp): Multiple commits during initial implementation.

---

## Acknowledgments

This session demonstrated the value of:
- Comprehensive planning before implementation
- Layered security models
- GitOps automation
- Documentation-first workflows
- Learning in public (this recap!)

The MCP server represents a significant evolution in how we interact with the homelab, moving from ad-hoc kubectl commands to structured, safe operations with built-in guardrails.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
