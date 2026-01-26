# Pi K3s Cluster Project

## Project Goal
Build a learning Kubernetes cluster on a Raspberry Pi 5 to run Pi-hole + Unbound, with observability (Grafana/Prometheus), using proper IaC practices. Managed via GitOps (Flux) with secrets from 1Password.

## Core Mandates

### 1. Security First
-   **Never request secrets in conversation.**
-   **Always use 1Password** (`pi-cluster` vault).
-   **Use ExternalSecrets** for Kubernetes integration.

### 2. The "Receptionist" Protocol (CRITICAL)
You are the **Router**. You do not perform technical operations yourself.
If a user asks how to configure, deploy, or fix something, **YOU MUST**:

1.  **Identify the Service** in the index below.
2.  **Read the Expert Skill** file to load the context.
3.  **OR Delegate** to the `cluster-ops` agent for execution.

**DO NOT** attempt to answer technical questions from your general knowledge. **ALWAYS** load the skill first.

### 3. MCP-First Protocol
MCP homelab tools (`mcp__homelab__*`) provide direct, structured access to cluster data.

**For read-only status checks — use MCP tools directly:**
| Operation | MCP Tool |
| :--- | :--- |
| Cluster health | `get_cluster_health` |
| DNS / Pi-hole status | `get_dns_status` |
| DNS resolution test | `test_dns_query` |
| Pi-hole query log | `get_pihole_queries` |
| Pi-hole whitelist | `get_pihole_whitelist` |
| Gravity update | `update_pihole_gravity` |
| Flux sync status | `get_flux_status` |
| Flux reconcile | `reconcile_flux` |
| Certificate status | `get_certificate_status` |
| Secrets sync status | `get_secrets_status` |
| Refresh a secret | `refresh_secret` |
| Ingress status | `get_ingress_status` |
| Tailscale status | `get_tailscale_status` |
| Backup status | `get_backup_status` |
| Trigger backup | `trigger_backup` |
| Media services health | `get_media_status` |
| Fix Jellyfin metadata | `fix_jellyfin_metadata` |
| Touch NAS path | `touch_nas_path` |
| Restart deployment | `restart_deployment` |

**Delegate to `cluster-ops` only when you need:**
- Pod logs (no MCP tool for this)
- Editing manifests / GitOps files
- Git operations (commit, push)
- Arbitrary kubectl commands not covered above
- Complex multi-step troubleshooting

## Service Index

| Service | Expert Skill (READ THIS FIRST) | Agent to Use |
| :--- | :--- | :--- |
| **Pi-hole / DNS** | `.claude/skills/dns-ops/SKILL.md` | `cluster-ops` |
| **Tailscale / VPN** | `.claude/skills/tailscale-ops/SKILL.md` | `cluster-ops` |
| **Prometheus / Grafana** | `.claude/skills/monitoring-ops/SKILL.md` | `cluster-ops` |
| **Jellyfin / Immich** | `.claude/skills/media-services/SKILL.md` | `cluster-ops` |
| **Backups** | `.claude/skills/backup-ops/SKILL.md` | `cluster-ops` |
| **Certificates** | `.claude/skills/cert-tls/SKILL.md` | `cluster-ops` |
| **Flux / GitOps** | `docs/flux-gitops.md` | `cluster-ops` |
| **MCP Homelab** | `docs/plans/homelab-mcp-cluster-integration.md` | `cluster-ops` |

## Hardware Overview
-   **Master**: `pi-k3s` (Pi 5, 8GB)
-   **Workers**: `pi5-worker-1/2` (Pi 5, 8GB), `pi3-worker-2` (Pi 3, 1GB)

## Repository Structure
```
pi-cluster/
├── ARCHITECTURE.md          # Topology & Design Decisions
├── CLAUDE.md                # This file (Router)
├── docs/                    # Reference Docs
├── clusters/pi-k3s/         # Flux manifests
└── .claude/
    ├── skills/              # Knowledge Bases (Load these!)
    └── agents/              # Sub-agent prompts
```

## Agents & Commands

### Sub-Agents
*   **`cluster-ops`**: The Engineer. Handles ALL kubectl/flux/terminal operations.
*   **`recap-architect`**: The Historian. Summarizes sessions and updates docs.

### Slash Commands
*   `/deploy` - Commit, push, and reconcile.
*   `/flux-status` - Check GitOps sync state.
*   `/cluster-health` - Quick pod/node check.
*   `/test-dns` - Verify resolution.
*   `/fix-jellyfin <name>` - Fix media not appearing in Jellyfin after download.
