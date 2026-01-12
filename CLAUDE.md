# Pi K3s Cluster Project

## Project Goal
Build a learning Kubernetes cluster on a Raspberry Pi 5 to run Pi-hole + Unbound, with observability (Grafana/Prometheus), using proper IaC practices. Managed via GitOps (Flux) with secrets from 1Password.

## Core Mandates

### Security Principles
1.  **Never request secrets in conversation.**
2.  **Always use 1Password.** (`pi-cluster` vault)
3.  **Use ExternalSecrets** for Kubernetes integration.
4.  **Verify secrets exist** (`kubectl get externalsecrets`) but do not view values.

### Expert Skills Protocol (Routing)
Before modifying or troubleshooting, **YOU MUST** check if a specialized skill exists.

-   **DNS / Ad-Blocking** → Read `dns-ops` (Pi-hole v6, Unbound)
-   **VPN / Remote Access** → Read `tailscale-ops` (ACLs, OAuth, Exit Node)
-   **Observability** → Read `monitoring-ops` (Prometheus, Grafana, Alerts)
-   **Media / Storage** → Read `media-services` (Immich, Jellyfin, NFS)
-   **Backups** → Read `backup-ops` (PVC & Postgres)
-   **TLS / Certs** → Read `cert-tls` (Cloudflare DNS-01)
-   **Secrets** → Read `secrets-management` (1Password SDK)

## Service Index

| Service | URL | Namespace | Expert Skill |
| :--- | :--- | :--- | :--- |
| **Homepage** | `https://home.lab.mtgibbs.dev` | `homepage` | `monitoring-ops` |
| **Pi-hole** | `https://pihole.lab.mtgibbs.dev` | `pihole` | `dns-ops` |
| **Grafana** | `https://grafana.lab.mtgibbs.dev` | `monitoring` | `monitoring-ops` |
| **Uptime Kuma** | `https://status.lab.mtgibbs.dev` | `uptime-kuma` | `monitoring-ops` |
| **Jellyfin** | `https://jellyfin.lab.mtgibbs.dev` | `jellyfin` | `media-services` |
| **Immich** | `https://immich.lab.mtgibbs.dev` | `immich` | `media-services` |
| **Tailscale** | (Exit Node: `pi-cluster-exit`) | `tailscale` | `tailscale-ops` |

## Hardware Overview
-   **Master**: `pi-k3s` (Pi 5, 8GB) - Critical workloads (DNS, Backup, Flux)
-   **Workers**: `pi5-worker-1/2` (Pi 5, 8GB) - Heavy workloads
-   **Worker**: `pi3-worker-2` (Pi 3, 1GB) - Lightweight only (Homepage)

**Architecture Reference**: See `ARCHITECTURE.md` for diagrams and topology.

## Repository Structure
```
pi-cluster/
├── ARCHITECTURE.md          # Detailed diagrams & design decisions
├── CLAUDE.md                # This file (Router)
├── docs/                    # Reference Docs
│   ├── flux-gitops.md       # Flux dependency chain
│   ├── known-issues.md      # Current bugs
│   └── pi-worker-setup.md   # Node setup
├── clusters/pi-k3s/         # Flux manifests
└── .claude/
    ├── skills/              # Expert Knowledge Bases
    └── agents/              # Sub-agent prompts
```

## Agents & Commands

### Sub-Agents
*   **`cluster-ops`**: The Primary Worker. Use for **ALL** kubectl/flux operations.
    *   *Usage*: "Deploy this change", "Check pod status".
*   **`recap-architect`**: The Historian. Use for documentation and recaps.

### Slash Commands
*   `/deploy` - Commit, push, and reconcile.
*   `/flux-status` - Check GitOps sync state.
*   `/cluster-health` - Quick pod/node check.
*   `/test-dns` - Verify resolution.