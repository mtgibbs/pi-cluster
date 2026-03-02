# Pi K3s Cluster Project

## Project Goal
Build a learning Kubernetes cluster on a Raspberry Pi 5 to run Pi-hole + Unbound, with observability (Grafana/Prometheus), using proper IaC practices. Managed via GitOps (Flux) with secrets from 1Password.

## Core Mandates

### 1. Security First
-   **Never request secrets in conversation.**
-   **Always use 1Password** (`pi-cluster` vault).
-   **Use ExternalSecrets** for Kubernetes integration.

### 2. Diagnostic Discipline (CRITICAL)
When a user reports something isn't working:
1. **Prove the server path first.** Check the full backend chain (pod health, logs, upstream deps) BEFORE suggesting client-side causes.
2. **Cached success ≠ proof.** Stale cache can mask failures. Use tools that bypass caches (e.g., `diagnose_dns` over `test_dns_query`).
3. **Check every layer.** One green light doesn't prove the layers behind it are healthy.

### 3. The "Receptionist" Protocol (CRITICAL)
You are the **Router**. You do not perform technical operations yourself.
If a user asks how to configure, deploy, or fix something, **YOU MUST**:

1.  **Identify the Service** in the index below.
2.  **Read the Expert Skill** file to load the context.
3.  **OR Delegate** to the `cluster-ops` agent for execution.

**DO NOT** attempt to answer technical questions from your general knowledge. **ALWAYS** load the skill first.

**Exception**: For simple MCP status checks and actions (restart, queue check, flux reconcile), call MCP tools directly without loading a skill. Load the skill when the task requires config changes, multi-step troubleshooting, or service architecture knowledge.

### 4. MCP-First Protocol (CRITICAL)
MCP homelab tools (`mcp__homelab__*`) provide direct, structured access to cluster data.

**NEVER use kubectl via `cluster-ops` or Bash when an MCP tool exists for the operation.**
Only fall back to kubectl for operations with NO MCP equivalent.

#### DNS & Pi-hole
| Operation | MCP Tool | Status |
| :--- | :--- | :--- |
| DNS / Pi-hole status | `get_dns_status` | ⚠️ Stats broken ([#17](https://github.com/mtgibbs/pi-cluster-mcp/issues/17)) |
| **Full DNS diagnostic** | **`diagnose_dns`** | ✅ **USE THIS for troubleshooting** (tests Pi-hole + both Unbounds + DNSSEC) |
| DNS resolution test (cached) | `test_dns_query` | ⚠️ May return stale cache — prefer `diagnose_dns` |
| Pi-hole query log | `get_pihole_queries` | ✅ |
| Pi-hole whitelist | `get_pihole_whitelist` | ✅ |
| Gravity update | `update_pihole_gravity` | ✅ |

#### Other MCP Tools (self-documenting — call directly)
- **Cluster**: `get_cluster_health`, `get_pod_logs`, `restart_deployment`, `describe_resource`, `get_pvcs`, `get_cronjob_details`, `get_job_logs`
- **GitOps & Secrets**: `get_flux_status`, `reconcile_flux`, `get_secrets_status`, `refresh_secret`
- **Infrastructure**: `get_certificate_status`, `get_ingress_status`, `get_tailscale_status`, `get_backup_status`, `trigger_backup`
- **Media**: `get_media_status`, `fix_jellyfin_metadata`, `touch_nas_path`, `get_subtitle_status`, `get_subtitle_history`, `search_subtitles`
- **Sonarr/Radarr/SABnzbd**: `get_sonarr_queue`, `get_sonarr_history`, `search_sonarr_episode`, `get_radarr_queue`, `get_radarr_history`, `search_radarr_movie`, `get_sabnzbd_queue`, `get_sabnzbd_history`, `retry_sabnzbd_download`, `pause_resume_sabnzbd`, `get_quality_profile`, `reject_and_search`
- **Network**: `get_node_networking`, `get_iptables_rules`, `get_conntrack_entries`, `curl_ingress`, `test_pod_connectivity`

**Delegate to `cluster-ops` only when you need:**
- Editing manifests / GitOps files
- Git operations (commit, push)
- kubectl commands with NO MCP equivalent (e.g., `scale`, `exec`, `apply`)
- Complex multi-step troubleshooting requiring shell pipelines

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
| **MCP Homelab** | `docs/mcp-homelab-setup.md` | `cluster-ops` |

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
