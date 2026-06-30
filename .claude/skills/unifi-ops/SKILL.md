# UniFi Network Operations

## Overview
UniFi network management via `go-unifi-mcp` — a local stdio MCP server running on the dev machine.

## Hardware
- **Controller**: UDM Pro Max (built-in controller, cutover 2026-04-19 — CK Gen1 retired)
- **UDM Pro Max IP**: 192.168.1.1 (gateway + controller)
- **Site**: `default`
- **Auth**: API key (`UNIFI_API_KEY`) for the go-unifi-mcp server; username/password (`/api/auth/login`) for the backup CronJob's curl flow

> **Note**: The UDM Pro Max uses `/api/auth/login` (newer UniFi API), not the classic `/api/login` used by CK Gen1. If go-unifi-mcp auth fails, verify it is configured for the new endpoint. Core operations should work; some older endpoint patterns may need updating.

> **CK Gen1 (retired)**: Was at 192.168.1.30:8443, firmware 6.1.71 (EOL). The `cmd:backup` on-demand backup hung indefinitely on 6.1.71. The CK Gen1 backup workaround (use `cmd:list-backups` + download from `/dl/autobackup/`) is no longer relevant — the UDM Pro Max backup flow may differ; verify before relying on it.

## MCP Tools

### Registration (required — not auto-present)
The server is **not** bundled with Claude Code; it must be registered or its tools won't load
(this bit us 2026-06-26 — the binary + creds were ready but the server was never added):
```
claude mcp add unifi -- /opt/homebrew/bin/go-unifi-mcp
```
- Binary: Homebrew `go-unifi-mcp` (`/opt/homebrew/bin/go-unifi-mcp`), **zero flags** — configured purely via env.
- Registers in **local (project) scope**, alongside `homelab` / `browser-control`.
- Env (`UNIFI_HOST`, `UNIFI_API_KEY`, `UNIFI_VERIFY_SSL`) comes from `mcp-auth` and is **inherited**
  from the Claude process — the registered entry itself has an empty `env: {}`.
- After registering, **restart Claude Code** (the `claude` shell wrapper runs `mcp-auth` first) so
  the server spawns and its tools appear. `UNIFI_TOOL_MODE` defaults to `lazy`.

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

## DNS Lockdown Runbook (force all DNS through Pi-hole)

**Purpose:** block client devices (kids/IoT) from bypassing Pi-hole via public resolvers or DoT,
log every attempt, while never breaking the cluster's own DNS. Born from the 2026-06-29 incident
(see bottom). **Read this whole section before touching DNS firewall rules.**

### The standing INVARIANT — "infra always resolves" (this is what prevents the deadlock)
- Exempt group **`fw-dns-infra`** (`address-group`, id `6a42d234e2d626152d14edda`) =
  **`192.168.1.48/28`** (`.48–.63`) — covers **all cluster nodes + both NASes**, zero client devices.
- **Every DNS-restriction rule MUST list `fw-dns-infra` as an allowed source.** New infra → give it a
  `.48–.63` address and it is auto-exempt. **Never** put a client/kid/IoT device in `.48–.63`.
- **Why this is non-negotiable:** in-cluster **CoreDNS forwards all external lookups to public DNS**
  (`coredns-custom` ConfigMap `custom.override` = `forward . 1.1.1.1 8.8.8.8`). pi-k3s's own
  `/etc/resolv.conf` also uses `1.1.1.1/8.8.8.8` (intentional bootstrap). If a lockdown blocks the
  nodes from reaching their DNS upstream, **Flux can't resolve github.com → can't pull the fix →
  deadlock** (GitOps cannot self-heal a DNS break). Exempting all infra makes that impossible.

### Pre-flight checklist (before ANY DNS/firewall lockdown)
Enumerate every resolver path and confirm each is exempt or routed through an allowed resolver:
1. **`coredns-custom` `custom.override`** (kube-system) — the cluster's external forward (→ public!).
2. **Node `/etc/resolv.conf`** — esp. pi-k3s bootstrap (→ `1.1.1.1/8.8.8.8`).
3. **Gateway's own upstream** — UDM `wan_dns1/2` (→ `.55/.56`, fine — internal).
4. **Apps with hardcoded DNS** (some IoT/NAS hardcode `8.8.8.8`).

### Live lockdown objects (UDM **legacy** firewall — this site is not zone-based)
| Object | id | detail |
| :--- | :--- | :--- |
| group `fw-dns-ports` | `6a42d22fe2d626152d14ed86` | port-group `53, 853` |
| group `fw-dns-infra` | `6a42d234e2d626152d14edda` | address-group `192.168.1.48/28` |
| `LAN_IN` **20000** accept | `6a42d290e2d626152d14f4ad` | src `fw-dns-infra` → dst `fw-dns-ports` (exemption) |
| `LAN_IN` **20001** drop+log | `6a42d2a6e2d626152d14f5ed` | any → dst `fw-dns-ports` (block v4 client DNS) |
| `LANv6_IN` **25000** drop+log | `6a42d3a1e2d626152d15027d` | any → dst `fw-dns-ports` (block v6 client DNS) |

- **Index-band gotchas:** `LAN_IN` user rules = **20000+**, `LANv6_IN` = **25000+**. Other values
  (`2000`, `20002`, `22000`, `40000`) → `api.err.FirewallRuleIndexOutOfRange`.
- The accept rule MUST rank **below** (lower index than) the drop, and exist first, or you sever
  Unbound recursion + pi-k3s bootstrap + CoreDNS upstream.
- **Residual gap:** DoH over `:443` to a hardcoded resolver IP is NOT blocked (would need a DoH-endpoint
  IP blocklist). Plain `:53` + DoT `:853` + the Firefox canary (in pihole doh-block) are covered.

### Verify the REAL paths — not a proxy
- ✅ **Client bypass blocked:** from a client, `dig +time=3 +tries=1 @8.8.8.8 google.com` AND
  `@2606:4700:4700::1111 google.com` → must **TIME OUT**.
- ✅ **Normal DNS works:** `dig @192.168.1.55 <domain>` resolves.
- ✅ **Cluster path works (the leg that bit us):** confirm an in-cluster **pod** can resolve external —
  `get_pod_logs flux-system source-controller` shows **no** `server misbehaving`, and `get_flux_status`
  source advances. **`diagnose_dns` is NOT sufficient** — it queries Pi-hole/Unbound directly and
  **bypasses CoreDNS**, so it stays green even when CoreDNS→upstream is severed. One green light ≠ the
  layers behind it.

### Break-glass revert (when the unifi MCP and/or GitOps is down)
Rules live on the **UDM, not GitOps**, and block only `:53/:853` (never `:443`), so the UDM API is
**always reachable**. Revert with the API key — no MCP, no Flux needed:
```sh
KEY=$(op read "op://pi-cluster/unifi/api-key")
BASE="https://192.168.1.1/proxy/network/api/s/default"
# FASTEST unblock — widen the exempt group to the whole LAN (re-tighten to .48/28 after):
curl -sk -X PUT "$BASE/rest/firewallgroup/6a42d234e2d626152d14edda" -H "X-API-KEY: $KEY" \
  -H 'Content-Type: application/json' \
  -d '{"_id":"6a42d234e2d626152d14edda","name":"fw-dns-infra","group_type":"address-group","group_members":["192.168.1.0/24"],"site_id":"59c6ba1fe4b04e1acfd4017e"}'
# OR delete a rule entirely:
curl -sk -X DELETE "$BASE/rest/firewallrule/6a42d2a6e2d626152d14f5ed" -H "X-API-KEY: $KEY"   # v4 drop
curl -sk -X DELETE "$BASE/rest/firewallrule/6a42d3a1e2d626152d15027d" -H "X-API-KEY: $KEY"   # v6 drop
```

### API-key curl pattern (MCP-down fallback — the go-unifi-mcp stdio server crashes)
- Auth: header `X-API-KEY: $(op read op://pi-cluster/unifi/api-key)`; base
  `https://192.168.1.1/proxy/network/api/s/default`. (Works on the legacy `/rest` + `/set|get/setting` endpoints.)
- Firewall: `/rest/firewallrule[/<id>]`, `/rest/firewallgroup[/<id>]` (GET/PUT/DELETE; create = POST).
- Settings: `GET /get/setting/<key>`, `PUT /set/setting/<key>`. **Numeric fields are STRINGS** (e.g.
  rsyslogd `port:"30514"` — int → `api.err.InvalidPayload`); settings PUTs want the identity+fields, not a sparse patch.
- `zsh` mangles a hex `_id` in a `$VAR` (reads it as arithmetic) — **inline the id** in the URL/payload.

### UDM remote syslog (firewall drop logs → Vector/Loki)
`SettingRsyslogd` (id `59c6e539e4b04e1acfd401d8`): `enabled:true, ip:"192.168.1.55", port:"30514"`
(STRING), `log_all_contents:true`. Ships to the Vector NodePort `30514/udp` in `log-aggregation`.

### Incident 2026-06-29 (why this runbook exists)
Locked down public DNS with only `.55/.56` exempt. CoreDNS (forwards to `1.1.1.1/8.8.8.8`) runs on
worker nodes → its upstream was dropped → every pod's fresh external lookup `SERVFAIL`ed
(`server misbehaving`) → Flux couldn't resolve github.com (stuck commit) or chart repos → ~25
Kustomizations cascaded. GitOps couldn't self-heal (needs DNS to pull the fix). Recovered by exempting
all infra via API-key curl. **Lesson: the cluster itself was a DNS bypasser — always check
`coredns-custom` first, and exempt the whole `.48/28` infra block, never just the resolvers.**

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
- **MCP server (go-unifi-mcp)**: Inherits `UNIFI_HOST`, `UNIFI_API_KEY`, `UNIFI_VERIFY_SSL` from the
  shell (set by `mcp-auth` from `op://pi-cluster/unifi/api-key`) — **API-key auth, not user/pass**
- **Backup CronJob**: ExternalSecret `unifi-credentials` pulling from 1Password `unifi/username` and `unifi/password`
- **Both use the same `unifi` 1Password item** — it must hold a **Network admin** account
  (not a login-only one), or the backup job 403s. go-unifi-mcp reads its creds at startup,
  so restart it after rotating the account.
