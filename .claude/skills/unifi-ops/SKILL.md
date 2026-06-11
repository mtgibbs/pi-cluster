# UniFi Network Operations

## Overview
UniFi network management via `go-unifi-mcp` — a local stdio MCP server running on the dev machine.

## Hardware
- **Controller**: UDM Pro Max (built-in controller, cutover 2026-04-19 — CK Gen1 retired)
- **UDM Pro Max IP**: 192.168.1.1 (gateway + controller)
- **Site**: `default`
- **Auth**: Username/password only

> **Note**: The UDM Pro Max uses `/api/auth/login` (newer UniFi API), not the classic `/api/login` used by CK Gen1. If go-unifi-mcp auth fails, verify it is configured for the new endpoint. Core operations should work; some older endpoint patterns may need updating.

> **CK Gen1 (retired)**: Was at 192.168.1.30:8443, firmware 6.1.71 (EOL). The `cmd:backup` on-demand backup hung indefinitely on 6.1.71. The CK Gen1 backup workaround (use `cmd:list-backups` + download from `/dl/autobackup/`) is no longer relevant — the UDM Pro Max backup flow may differ; verify before relying on it.

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
- Manifest: `clusters/pi-k3s/backup-jobs/unifi-backup-cronjob.yaml`
- **Ported to UDM Pro Max 2026-06-11** (was hardcoded to CK Gen1 `192.168.1.30:8443`
  and silently failed every Sunday from the 2026-04-19 cutover until then).
- **Flow (UniFi OS):**
  - Auth: `POST https://192.168.1.1/api/auth/login` → grab the `TOKEN` session
    cookie *and* the `x-csrf-token` response header
  - **Generates on-demand** backup (the UDM can; CK Gen1 6.1.71 couldn't):
    `POST /proxy/network/api/s/default/cmd/backup {"cmd":"backup","days":-1}`,
    then downloads the `.data[0].url` from `/proxy/network/dl/backup/<ver>.unf`
  - `.unf` stored on NAS at `/share/cluster/backups/{date}/unifi/` (QNAP), keep last 4
  - Uses `scp -O` (legacy protocol)
- **Gotchas (all bit us during the port — see commit `cbbc730`):**
  - **Needs a Network *admin* account.** A login-only UniFi account authenticates
    (HTTP 200) but `403 Forbidden`s on every `/proxy/network/` call. The stored
    `unifi` account must have full Network admin rights.
  - **CHIPS cookie:** the `TOKEN` cookie has the `partitioned` attribute, which some
    curl builds won't replay from a jar — extract it and send it back via an explicit
    `Cookie:` header (this is what the manifest does).
  - **24h secret lag:** after changing the creds in 1Password, the `unifi-credentials`
    ExternalSecret (`refreshInterval: 24h`) won't resync until forced. Run
    `refresh_secret(backup-jobs, unifi-credentials)` or the pod keeps using old creds.

## Credentials
- **MCP server**: Inherits `UNIFI_USERNAME` and `UNIFI_PASSWORD` from shell (set by `mcp-auth`)
- **Backup CronJob**: ExternalSecret `unifi-credentials` pulling from 1Password `unifi/username` and `unifi/password`
- **Both use the same `unifi` 1Password item** — it must hold a **Network admin** account
  (not a login-only one), or the backup job 403s. go-unifi-mcp reads its creds at startup,
  so restart it after rotating the account.
