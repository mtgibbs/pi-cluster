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

### 3. MCP-First Protocol (CRITICAL)
MCP homelab tools (`mcp__homelab__*`) provide direct, structured access to cluster data.

**NEVER use kubectl via `cluster-ops` or Bash when an MCP tool exists for the operation.**
This includes pod logs, deployment restarts, resource inspection, queue checks, and all status queries.
Only fall back to kubectl for operations with NO MCP equivalent.

**For status checks and diagnostics — use MCP tools directly:**

#### Cluster & Workloads
| Operation | MCP Tool |
| :--- | :--- |
| Cluster health | `get_cluster_health` |
| Pod logs | `get_pod_logs` |
| Restart deployment | `restart_deployment` |
| Inspect resource | `describe_resource` |
| List PVCs | `get_pvcs` |
| CronJob details | `get_cronjob_details` |
| Job logs | `get_job_logs` |

#### DNS & Pi-hole
| Operation | MCP Tool | Status |
| :--- | :--- | :--- |
| DNS / Pi-hole status | `get_dns_status` | ⚠️ Stats broken ([#17](https://github.com/mtgibbs/pi-cluster-mcp/issues/17)) |
| **Full DNS diagnostic** | **`diagnose_dns`** | ✅ **USE THIS for troubleshooting** (tests Pi-hole + both Unbounds + DNSSEC) |
| DNS resolution test (cached) | `test_dns_query` | ⚠️ May return stale cache — prefer `diagnose_dns` |
| Pi-hole query log | `get_pihole_queries` | ✅ |
| Pi-hole whitelist | `get_pihole_whitelist` | ✅ |
| Gravity update | `update_pihole_gravity` | ✅ |

#### GitOps & Secrets
| Operation | MCP Tool | Status |
| :--- | :--- | :--- |
| Flux sync status | `get_flux_status` | ✅ |
| Flux reconcile | `reconcile_flux` | ✅ |
| Secrets sync status | `get_secrets_status` | ✅ |
| Refresh a secret | `refresh_secret` | ✅ |

#### Infrastructure
| Operation | MCP Tool |
| :--- | :--- |
| Certificate status | `get_certificate_status` |
| Ingress status | `get_ingress_status` |
| Tailscale status | `get_tailscale_status` |
| Backup status | `get_backup_status` |
| Trigger backup | `trigger_backup` |

#### Media Services
| Operation | MCP Tool |
| :--- | :--- |
| Media services health | `get_media_status` |
| Fix Jellyfin metadata | `fix_jellyfin_metadata` |
| Touch NAS path | `touch_nas_path` |
| Subtitle status | `get_subtitle_status` |
| Subtitle history | `get_subtitle_history` |
| Search subtitles | `search_subtitles` |

#### Sonarr (TV)
| Operation | MCP Tool |
| :--- | :--- |
| Download queue | `get_sonarr_queue` |
| Recent history | `get_sonarr_history` |
| Manual episode search | `search_sonarr_episode` |

#### Radarr (Movies)
| Operation | MCP Tool |
| :--- | :--- |
| Download queue | `get_radarr_queue` |
| Recent history | `get_radarr_history` |
| Manual movie search | `search_radarr_movie` |

#### SABnzbd (Downloads)
| Operation | MCP Tool |
| :--- | :--- |
| Download queue | `get_sabnzbd_queue` |
| Download history | `get_sabnzbd_history` |
| Retry failed download | `retry_sabnzbd_download` |
| Pause/resume queue | `pause_resume_sabnzbd` |

#### Shared Media Tools
| Operation | MCP Tool |
| :--- | :--- |
| Quality profiles | `get_quality_profile` |
| Reject & re-search | `reject_and_search` |

#### Network Diagnostics
| Operation | MCP Tool | Status |
| :--- | :--- | :--- |
| Node networking info | `get_node_networking` | ✅ |
| iptables rules | `get_iptables_rules` | ✅ |
| Connection tracking | `get_conntrack_entries` | ✅ |
| Test ingress HTTP(S) | `curl_ingress` | ✅ |
| Test pod connectivity | `test_pod_connectivity` | ✅ |

**Delegate to `cluster-ops` only when you need:**
- Editing manifests / GitOps files
- Git operations (commit, push)
- kubectl commands with NO MCP equivalent (e.g., `scale`, `exec`, `apply`)
- Complex multi-step troubleshooting requiring shell pipelines
- Workarounds for broken MCP tools (use kubectl directly)

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
