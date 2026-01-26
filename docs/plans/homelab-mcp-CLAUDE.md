# Homelab MCP Server

## Project Goal
Build a Model Context Protocol (MCP) server that provides structured tools for Pi K3s cluster operations. This enables Claude (Desktop and CLI) to interact with the homelab using well-defined, safe operations instead of raw kubectl commands.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                  Claude Desktop / CLI                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ SSE (HTTPS) / stdio
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   mcp-homelab (K3s Pod)                      │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ MCP Server  │  │ K8s Client   │  │ SSH Client (NAS)  │  │
│  │ (stdio/SSE) │  │ (in-cluster) │  │ (node-ssh)        │  │
│  └─────────────┘  └──────────────┘  └───────────────────┘  │
└─────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
   Ingress (SSE)       K8s API Server        Synology NAS
   mcp.lab.mtgibbs.dev (ServiceAccount)      (SSH @ 192.168.1.60)
```

## Tech Stack
- **Runtime**: Node.js 20+ with TypeScript
- **MCP SDK**: @modelcontextprotocol/sdk
- **K8s Client**: @kubernetes/client-node
- **SSH Client**: node-ssh (for Synology operations)
- **Container**: Docker multi-stage build
- **CI/CD**: GitHub Actions → GHCR

## Project Structure

```
homelab-mcp/
├── .github/
│   └── workflows/
│       ├── ci.yaml              # Lint, test, build
│       └── release.yaml         # Build + push container
├── src/
│   ├── index.ts                 # Entry point, transport setup
│   ├── server.ts                # MCP server definition
│   ├── auth.ts                  # API key validation middleware
│   ├── clients/
│   │   ├── kubernetes.ts        # K8s client wrapper
│   │   └── synology.ts          # SSH client for NAS
│   ├── tools/
│   │   ├── index.ts             # Tool registry
│   │   ├── cluster.ts           # get_cluster_health, restart_deployment
│   │   ├── dns.ts               # get_dns_status, test_dns_query
│   │   ├── flux.ts              # get_flux_status, reconcile_flux
│   │   ├── certificates.ts      # get_certificate_status
│   │   ├── secrets.ts           # get_secrets_status, refresh_secret
│   │   ├── backups.ts           # get_backup_status, trigger_backup
│   │   ├── ingress.ts           # get_ingress_status
│   │   ├── tailscale.ts         # get_tailscale_status
│   │   └── media.ts             # get_media_status, fix_jellyfin_metadata
│   └── utils/
│       ├── errors.ts            # Structured error responses
│       └── whitelist.ts         # Allowed deployments for restart
├── k8s/
│   ├── namespace.yaml
│   ├── serviceaccount.yaml
│   ├── clusterrole.yaml
│   ├── clusterrolebinding.yaml
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── ingress.yaml
│   ├── externalsecret.yaml
│   └── kustomization.yaml
├── Dockerfile
├── package.json
├── tsconfig.json
├── .eslintrc.json
└── CLAUDE.md
```

## Security Model

### Defense in Depth
1. **Network**: Ingress only accessible via Tailscale
2. **Application**: API key required in `X-API-Key` header
3. **Kubernetes**: ServiceAccount with minimal RBAC
4. **Code**: Deployment whitelist enforced in implementation

### RBAC Permissions

**Read-Only Access:**
- Pods, Services, Nodes, Events, ConfigMaps, PVCs, Namespaces
- Deployments, StatefulSets, DaemonSets
- Flux resources (Kustomizations, HelmReleases, Sources)
- Cert-manager resources (Certificates, Challenges)
- ExternalSecrets (status only, not secret values)
- Ingresses, Tailscale Connectors, Jobs/CronJobs
- Metrics (nodes, pods)

**Limited Actions:**
- `patch` deployments (for rollout restart) - whitelisted only
- `patch` Flux resources (for reconcile trigger)
- `patch` ExternalSecrets (for force refresh)
- `create` Jobs (for manual backup trigger)
- `create` pods/exec (Jellyfin namespace only, for metadata fix)

**Explicitly NOT Allowed:**
- `delete` on any resource
- `create` pods/deployments/services
- Access to Secret values
- Node operations (cordon, drain)
- Namespace deletion

### Deployment Whitelist
Only these deployments can be restarted via `restart_deployment`:
- `jellyfin/jellyfin`
- `pihole/pihole`
- `pihole/unbound`
- `immich/immich-server`
- `homepage/homepage`
- `uptime-kuma/uptime-kuma`

## Tools Reference

### Diagnostic Tools (Read-Only)

| Tool | Description | Returns |
|------|-------------|---------|
| `get_cluster_health` | Overall cluster status | Nodes, resource usage, problem pods, warning events |
| `get_dns_status` | Pi-hole + Unbound health | Pod status, blocked queries, upstream health |
| `get_flux_status` | GitOps sync state | Kustomizations, HelmReleases with ready state |
| `get_certificate_status` | TLS cert health | Certs with ready state, expiry, pending challenges |
| `get_secrets_status` | External Secrets sync | Sync status, last refresh, errors |
| `get_backup_status` | Backup job status | CronJob schedules, last run, next run |
| `get_ingress_status` | Ingress health | Hosts, TLS status, backend health |
| `get_tailscale_status` | VPN connector status | Exit node, routes, connectivity |
| `get_media_status` | Media services health | Jellyfin/Immich pod status, NFS mounts |

### Action Tools

| Tool | Parameters | Description |
|------|------------|-------------|
| `reconcile_flux` | `resource?` | Trigger Flux sync (all or specific) |
| `restart_deployment` | `namespace`, `deployment` | Rollout restart (whitelisted only) |
| `fix_jellyfin_metadata` | `name` | Find item in DB, trigger API refresh |
| `trigger_backup` | `job_name` | Create Job from CronJob |
| `test_dns_query` | `domain`, `type?` | Run dig against Pi-hole |
| `refresh_secret` | `namespace`, `name` | Force ExternalSecret resync |
| `touch_nas_path` | `path` | SSH to Synology, touch path |

## Secrets Required (1Password)

| Item | Field | Purpose |
|------|-------|---------|
| `synology-mcp-ssh` | `private-key` | SSH key for NAS operations |
| `jellyfin-api-key` | `api-key` | Jellyfin API for metadata refresh |
| `mcp-homelab-api-key` | `api-key` | SSE endpoint authentication |

## Development

### Prerequisites
- Node.js 20+
- Docker
- kubectl configured for local testing
- Access to pi-cluster 1Password vault

### Local Testing (stdio mode)
```bash
npm install
npm run build
npm run dev  # Runs in stdio mode for CLI testing
```

### Container Build
```bash
docker build -t homelab-mcp:dev .
docker run -it --rm \
  -v ~/.kube/config:/root/.kube/config:ro \
  -e MCP_TRANSPORT=stdio \
  homelab-mcp:dev
```

### Deploy to Cluster
```bash
# From pi-cluster repo after MCP manifests are added
flux reconcile kustomization mcp-homelab
```

## CI/CD

### GitHub Actions Workflows

**ci.yaml** - On PR and push to main:
- Lint (ESLint)
- Type check (tsc)
- Build
- Unit tests

**release.yaml** - On tag push (v*):
- Build multi-arch container (arm64 + amd64)
- Push to ghcr.io/mtgibbs/homelab-mcp
- Create GitHub release

## Adding New Tools

1. Create tool implementation in `src/tools/<category>.ts`:
```typescript
export const myNewTool: Tool = {
  name: 'my_new_tool',
  description: 'What this tool does',
  inputSchema: {
    type: 'object',
    properties: {
      param1: { type: 'string', description: 'First param' }
    },
    required: ['param1']
  },
  handler: async (params) => {
    // Implementation
    return { result: 'data' };
  }
};
```

2. Register in `src/tools/index.ts`

3. If new K8s permissions needed:
   - Update `k8s/clusterrole.yaml`
   - Document in this file

4. Test locally before deploying

## Troubleshooting

### Pod won't start
- Check ServiceAccount exists: `kubectl get sa mcp-homelab -n mcp-homelab`
- Check RBAC: `kubectl auth can-i list pods --as=system:serviceaccount:mcp-homelab:mcp-homelab`
- Check secrets synced: `kubectl get externalsecrets -n mcp-homelab`

### SSE connection fails
- Verify Tailscale connected
- Check API key in request header
- Check ingress: `kubectl describe ingress mcp-homelab -n mcp-homelab`
- Check cert: `kubectl get certificate -n mcp-homelab`

### Tool returns permission denied
- Check ClusterRole has required verb/resource
- Check ClusterRoleBinding references correct ServiceAccount
- For deployment restart, verify it's in the whitelist
