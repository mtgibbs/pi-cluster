# UniFi Network Operations

## Overview
UniFi network management via `go-unifi-mcp` — a local stdio MCP server running on the dev machine.

## Hardware
- **Controller**: Cloud Key Gen1, firmware 6.1.71 (EOL — max ~7.2.x)
- **IP**: 192.168.1.30:8443
- **Site**: `default`
- **Auth**: Username/password only (no API key support on CK Gen1)

## MCP Tools

go-unifi-mcp runs in **lazy mode** — tools are loaded on demand via three meta-tools:

| Tool | Purpose |
| :--- | :--- |
| `mcp__unifi__tool_index` | Browse available API operations (list devices, networks, firewall rules, etc.) |
| `mcp__unifi__execute` | Execute a single API operation |
| `mcp__unifi__batch` | Execute multiple API operations in one call |

### Workflow
1. Call `tool_index` to find the operation you need
2. Call `execute` with the operation name and parameters
3. Use `batch` for multiple related queries

### Common Operations
- **List devices**: `list_device` — shows all APs, switches, gateways with firmware versions
- **List networks**: `list_networkconf` — VLANs, subnets, DHCP settings
- **List firewall rules**: `list_firewallrule` — all firewall/traffic rules
- **List port forwards**: `list_portforward` — NAT/port forwarding rules
- **List WLANs**: `list_wlanconf` — wireless network configurations
- **List clients**: `list_user` — known clients and their details
- **Active clients**: `list_sta` — currently connected stations

## Compatibility Notes
- go-unifi-mcp auto-generates tools from newer UniFi API definitions
- Core operations (list devices/networks/firewall/clients) work on 6.1.71
- Some newer endpoints may 404 — this is expected and non-breaking
- CK Gen1 uses classic API (`/api/login`, not `/api/auth/login`)

## Safety Notes
- **Write operations exist** — go-unifi-mcp has no read-only mode
- Always confirm with the user before executing create/update/delete operations
- Firewall rule changes can lock you out of the network — double-check before applying
- Consider exporting current config before making changes

## Backup Strategy
- Automated weekly backup CronJob: `unifi-backup` in `backup-jobs` namespace
- Schedule: Sundays 3:30 AM (after PVC backup at 2:00 AM)
- **Downloads the latest auto-backup** from the controller (does NOT generate on-demand)
  - CK Gen1 on 6.1.71 hangs indefinitely on `cmd:backup` (on-demand generation)
  - Uses `cmd:list-backups` to find the newest auto-backup, then downloads from `/dl/autobackup/`
  - Controller auto-backups run monthly (`0 0 1 * *`, 30-day retention)
- `.unf` files stored on NAS at `/volume1/cluster/backups/{date}/unifi/`
- Keeps last 4 backups
- Uses `scp -O` (legacy protocol) — Synology rejects SFTP-based scp
- Critical for eventual CK Gen1 hardware migration

## Credentials
- **MCP server**: Inherits `UNIFI_USERNAME` and `UNIFI_PASSWORD` from shell (set by `mcp-auth`)
- **Backup CronJob**: ExternalSecret `unifi-credentials` pulling from 1Password `unifi/username` and `unifi/password`
