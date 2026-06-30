# Recap — DNS lockdown, bypass alerting, and the Phase 3 reversal (2026-06-29 → 2026-06-30)

Picks up from the 2026-06-26 checkpoint, where the YouTube/short-form blackout was deployed
(`cc4fae2` + `8fdefe0`) but the adult MacBooks were still being blocked. The previous checkpoint
blamed DHCP reservations not binding. That was wrong. This session found the real root cause,
built three mitigating layers, self-inflicted a cluster-wide DNS incident while doing it, and
then reverted a Phase 3 fix that broke a kid's Windows machine. It is a candid account; the
incident and the reversal get the same weight as the things that worked.

---

## 1. Root-cause correction — IPv6 RDNSS via the UDM, not DHCP reservations

The work laptop was confirmed to be on its reserved IP (`.82`). DHCP reservations were
working fine. The actual mechanism:

**macOS honors the IPv6 Router Advertisement RDNSS option; Windows does not.**

The Default LAN has `ipv6_ra_enabled: true` with no explicit IPv6 DNS configured, so the UDM
advertises its own link-local (`fe80::5ad6:1fff:fe32:f9a1`) as the IPv6 resolver. macOS
picks it as `nameserver[0]`. The UDM then proxies the query to Pi-hole, but the arriving
source IP is `192.168.1.1` — the UDM's own NAT/proxy address — not the client's `.82`.
Pi-hole sees `.1` in group 0, applies the brain-rot regex deny, and returns `0.0.0.0`.

**Proof:** every blocked `youtube.com` in the FTL log shows `client.ip = 192.168.1.1, status
REGEX`. Forcing IPv4-direct — `dig @192.168.1.55 youtube.com` from the Mac — resolves
correctly (`.82` is in the adults group). The system resolver, which prefers the UDM v6 path,
gets `0.0.0.0`.

This is also why the block "works" so robustly on the kid devices: everything funneling through
the UDM v6 proxy collapses to `.1` in group 0. Windows PCs (`.80`, `.81`) are exempt because
Windows ignores RDNSS and queries Pi-hole directly via the IPv4 DHCP-handed DNS IPs.

The monitoring blind spot that comes with this: ALL IPv6-originated queries show as `.1` in
Pi-hole. Per-device DNS visibility is lost for anything using the UDM v6 resolver.

---

## 2. Design decisions

- **Disable IPv6 / RA**: Rejected by user. IPv6 is a hard requirement.
- **VLAN segmentation (kids on a separate SSID)**: Rejected. LAN gaming between the
  kids' machines and the main network; no VLANs "at this time."
- **Chosen path**: (A) lock the doors — UDM firewall rules that force all `:53`/`:853`
  traffic through Pi-hole; (B) bypass alerting — see who tries to sneak around it; (C)
  advertise Pi-hole's v6 address as the RDNSS resolver instead of the UDM so the proxy
  detour disappears. Phases executed in order.

---

## 3. Phase 1 — DNS lockdown (done, verified)

**What:** Three UDM legacy-firewall objects force all DNS through Pi-hole. The UDM Pro Max
on this site is not zone-based (zone lists are empty), so legacy `firewallrule` / `firewallgroup`
objects are the correct API surface.

The go-unifi-mcp server was used initially, then crashed mid-session with an unrecoverable
stdio error. All remaining Phase 1 work was done via direct API-key curl — `X-API-KEY` header
against `https://192.168.1.1/proxy/network/api/s/default`. This is now the documented
break-glass path in `unifi-ops/SKILL.md`.

**Objects created (all live on the UDM, not in GitOps; captured by the weekly `unifi-backup`
CronJob):**

| Object | ID | Detail |
| :--- | :--- | :--- |
| group `fw-dns-ports` | `6a42d22fe2d626152d14ed86` | port-group `53, 853` |
| group `fw-dns-infra` | `6a42d234e2d626152d14edda` | address-group `192.168.1.48/28` |
| `LAN_IN` 20000 accept | `6a42d290e2d626152d14f4ad` | src infra → dst dns-ports |
| `LAN_IN` 20001 drop+log | `6a42d2a6e2d626152d14f5ed` | any → dst dns-ports (v4 clients) |
| `LANv6_IN` 25000 drop+log | `6a42d3a1e2d626152d15027d` | any → dst dns-ports (v6 clients) |

The infra exempt group `192.168.1.48/28` covers `.48–.63`, which encompasses both Pi-holes
(`.55`, `.56`) and all cluster nodes. The accept rule must have a lower index number than the
drop rule so it is evaluated first.

**Gotchas:**
- Legacy rule index bands: `LAN_IN` user rules start at `20000+`, `LANv6_IN` at `25000+`.
  Indexes like `2000`, `20002`, `22000`, `40000` all return `api.err.FirewallRuleIndexOutOfRange`.
- Unbound is configured with `do-ip6: no`, so the IPv6 recursion path is already disabled;
  no Unbound v6 exemption is needed.
- `port` in the rsyslog settings payload must be a **string** (`"30514"`), not an integer.
  An integer returns `api.err.InvalidPayload`.

**Verified:** `dig +time=3 +tries=1 @8.8.8.8 google.com` and
`@2606:4700:4700::1111 google.com` both time out from a LAN client. Pi-hole resolution,
Unbound recursion (`www.kernel.org`), and `diagnose_dns` all pass.

**Residual gap:** DoH over port 443 to a hardcoded resolver IP is not covered by these rules.
A client sending DoH to, say, `8.8.8.8:443` bypasses the port-53/853 block. The Firefox
`use-application-dns.net` canary is in the Pi-hole doh-block list, but arbitrary hardcoded-IP
DoH is not addressed. User assessment: "that's on them, they'll be dead soon."

---

## 4. The incident — self-inflicted, self-recovered, but documented here fully

**What happened:** the DNS lockdown blocked CoreDNS's upstream resolver, cascading to ~25
failing Kustomizations and a GitOps deadlock. This was entirely caused by the session's
firewall work.

**Root cause:** the `coredns-custom` ConfigMap (`kube-system`, `custom.override`) contains:

```
forward . 1.1.1.1 8.8.8.8 { policy sequential }
```

In-cluster CoreDNS forwards all external DNS lookups to public resolvers. CoreDNS pods run
on the worker nodes (`.56`, `.57`), which were not in the `fw-dns-infra` exempt group at the
time the lockdown was applied (the group held only `.55` and `.56`, missing `.57`). So worker-
node traffic to `:53` was dropped.

The result: every pod's first-time external lookup returned `SERVFAIL` ("server misbehaving").
Flux source-controller could not resolve `github.com` — the git source stayed pinned at
`8fdefe0` even though subsequent commits existed. Helm chart repositories were unreachable.
~25 Kustomizations cascaded to `dependency not ready`.

**Why `diagnose_dns` was not sufficient here:** this tool tests Pi-hole and Unbound directly.
It bypasses CoreDNS entirely. It reported all green while CoreDNS's own upstream path was
severed. The cluster path and the direct path are different legs, and only one of them was
being checked. This is exactly the "one green light doesn't prove the layers behind it" error
from the project's Diagnostic Discipline mandate.

The session declared the firewall innocent twice before the CoreDNS forwarding was identified.
Each wrong declaration came from checking the wrong layer.

**Recovery:** GitOps could not self-heal — pulling the fix requires resolving `github.com`,
which requires DNS, which was broken. Broke the deadlock by widening `fw-dns-infra` to
`192.168.1.48/28` via api-key curl (covering all four node IPs: `.51`, `.55`, `.56`, `.57`).
CoreDNS reached its upstream again within a few minutes; the Flux cascade unwound as the
HelmRepository `InProgress` conditions cleared and dependencies propagated.

**Process misstep:** `reconcile_flux` was issued against all 33 Kustomizations during
troubleshooting, adding churn to an already-recovering system. The correct scope would have
been `log-aggregation` only. No workload outage resulted (running pods use cached DNS; Pi-hole
and Unbound continued serving the LAN throughout).

**What the invariant now says:** the `fw-dns-infra` group must always be `192.168.1.48/28`,
never just the Pi-hole IPs. Any new infra device should get an address in `.48–.63` and it
is automatically exempt. The reasoning and the pre-flight checklist are codified in
`unifi-ops/SKILL.md` under "DNS Lockdown Runbook."

---

## 5. Deadlock safeguards codified in `unifi-ops/SKILL.md`

`d11a8d1` added the "DNS Lockdown Runbook" section to the unifi-ops skill, establishing:

- **The standing invariant:** `fw-dns-infra` = `192.168.1.48/28`. Every DNS-restriction
  rule references it as the exempt source. No exceptions.
- **Pre-flight checklist:** before any DNS/firewall lockdown, explicitly enumerate
  `coredns-custom custom.override`, node `/etc/resolv.conf`, gateway upstream, and any
  apps with hardcoded DNS.
- **Real-path verification:** confirm an in-cluster pod can resolve external by checking
  `source-controller` logs for `server misbehaving`, not just `diagnose_dns`.
- **Break-glass revert:** api-key curl commands to widen the exempt group to `0.0.0.0/0`
  or delete the drop rules individually, operable even when the MCP server and GitOps are
  both unavailable.

---

## 6. Phase 2 — bypass alerting (done, verified)

**What:** UDM remote syslog → Vector → parse firewall drops → ntfy push + Loki.

**Architecture:**

```
UDM Pro Max (remote syslog enabled)
    │  UDP/30514 → NodePort → Vector :5514
    ▼
Vector (log-aggregation namespace)
    ├── udm_syslog source (UDP :5514)
    ├── udm_dns_bypass transform: keep only "Block public DNS bypass" lines
    │       extract src_ip, dst_ip, dpt, proto, ip_ver
    │       src_mac = octets 7-12 of iptables MAC= field
    ├── udm_dns_bypass_only filter (drop non-bypass lines)
    ├── udm_dns_bypass_throttled: 1 push / src_ip / 5 min
    ├── ntfy_body remap → message = .alert text
    │
    ├── loki_dns_bypass sink: JSON, labels source="udm-fw-dns-bypass", ip_ver
    └── ntfy_dns_bypass sink: POST http://ntfy.ntfy.svc.cluster.local/dns-bypass
            basic auth: family / ${NTFY_PASSWORD}
            healthcheck: disabled
```

The `vector-ntfy` ExternalSecret (`log-aggregation` namespace) pulls `ntfy/family-password`
from the `pi-cluster` 1Password vault. Grafana picks up the `grafana_dashboard: "1"` label
on the `grafana-dashboard-dns-bypass` ConfigMap in the `monitoring` namespace and renders
a stat panel (total bypass attempts), a per-device time-series, and a table with src_ip,
src_mac, dst_ip, and timestamp.

**Verified:** a Samsung TV (`.154`) was logged hitting `8.8.8.8` in real traffic; a test
query from `.82` produced a second push. Throttle held: only one push per device per 5 minutes
appeared in the ntfy `dns-bypass` topic.

**Hard-won gotchas (~10 deploy cycles to reach working state):**

- **ConfigMap-only edits do not restart Vector.** The `--watch-config` flag was added to the
  deployment args (`4220d95`) so Vector hot-reloads on ConfigMap changes. Before this flag,
  every config fix required a manual rollout — and because there was no visible error, it was
  not obvious the old config was still running.

- **The ntfy 401 at startup was not a trailing newline.** It was the first pod starting before
  the `vector-ntfy` ExternalSecret had synced, leaving `NTFY_PASSWORD` empty. The ExternalSecret
  is marked `optional: true` so Vector starts anyway; a fresh pod after the secret syncs
  authenticates correctly.

- **`get_env_var` + `encode_base64` in VRL to build an auth header silently dropped events.**
  There was no error log; events were simply not arriving at ntfy. Reverted to the sink's
  native `auth:` block (`strategy: basic, user: family, password: "${NTFY_PASSWORD}"`).

- **ntfy `NTFY_AUTH_DEFAULT_ACCESS=deny-all` requires an ACL entry for the publisher.** The
  ntfy postStart hook needed `ntfy access family "dns-bypass" rw`. The family creds are
  delivered via the `vector-ntfy` ExternalSecret.

- **Disable the http sink healthcheck.** ntfy's `deny-all` policy returns 401 on the
  unauthenticated Vector healthcheck probe, causing the sink to mark itself unhealthy and
  drop events (`5648ff2`).

- **`zsh` does not word-split `$VAR` in a bare `for M in $MACS` loop.** All four MAC
  addresses were posted as one string, returning HTTP 400. Inlining the list in the `for`
  loop is the fix.

**Minor known issue:** the VRL `ip_ver` field uses label detection via `contains(msg, "LANv6_IN")`.
Because the UDM firewall log prefixes the rule name, this produces `[v4]` on the drop line
from the v6 rule (the prefix contains `LANv6_IN` but the actual packet tag in the iptables
log line can say otherwise). Low-priority cleanup.

---

## 7. Device identifications from the bypass logs

- **192.168.1.154** — Samsung device (Smart TV). Relentlessly hitting `8.8.8.8:53`. The
  first real bypass event caught by the alerting pipeline.
- **`aa:27:4d:5b:13:f8`** — Rory's iPhone. Appears in the `adults` group (id=1) on both
  Pi-holes and in `pihole-allowlist-configmap`. This is wrong — a kid's device should not
  be exempt. Cleanup is an open item.
- **Matt's iPhone (`.90`)** — blocked by the same IPv6 detour as the MacBooks. Its MAC
  `4e:2b:56:67:b1:68` is in the adults group (correct), but v6 proxy collapses it to `.1`.

---

## 8. Phase 3 — IPv6 detour fix: attempted, reverted

**Goal:** advertise Pi-hole's own IPv6 address as the RDNSS resolver instead of the UDM's
link-local, so macOS and iOS devices reach Pi-hole directly over v6 and are seen as their
real MACs / IPs rather than `.1`.

**What was attempted:** via api-key curl GET→modify→PUT on the Default LAN network object
(`_id 59c6ba27e4b04e1acfd40185`), set `dhcpdv6_dns_1` to pi-k3s's link-local
`fe80::cef4:1f47:81cf:14d7`. Pi-hole/FTL already listens on v6 (verified with
`dig @fe80::cef4...%en0`). No ULA or reconfiguration of Pi-hole was needed.

Simultaneously, the four adult Mac MACs were added to the adults group (id=1) on both
Pi-holes and committed to `pihole-allowlist-configmap` (`7421031`). Over v6, a Mac arrives
at Pi-hole as its link-local source — matched by MAC, not its `.8x` reserved IP. This
combination was verified working: the Mac's resolver auto-flipped to
`fe80::cef4::...` without any manual pin, and `youtube.com` resolved to a real IP.

**What broke:** the kid's BG3 host machine (Windows 11 laptop) lost DNS entirely. Win11 does
honor RDNSS (unlike the Windows desktops, which ignore it), but it cannot use a link-local
address as a DNS resolver when that address is not the link's router. Total DNS loss on the
laptop meant NAT-punch failed and the web went dead — mid-session, mid-game.

Matt's Windows desktop (`.80`) was unaffected because it was already ignoring RDNSS and
querying Pi-hole at `.55`/`.56` directly over IPv4.

**Recovery:** set `dhcpdv6_dns_1` back to `""` via api-key curl (UDM re-advertises its own
link-local). The kid recovered DNS by disabling IPv6 on the laptop's Wi-Fi adapter to
force IPv4-only, then re-enabled after the revert.

**Lesson:** a link-local address is not universally valid as an RDNSS entry. RFC 4191 and
practical implementation in Windows, iOS, and other stacks diverge on what they accept. **Do
not advertise a link-local as the RDNSS resolver.** The redo path requires a stable global or
ULA address on the Pi nodes.

The adult Mac MAC additions (`7421031`) are harmless and remain committed — they will be
useful once Phase 3 is redone correctly, since v6-via-Pi-hole MACs will still be matched.

---

## 9. State at close

| Component | State | Notes |
| :--- | :--- | :--- |
| Phase 1 DNS lockdown (UDM firewall) | **LIVE** | `fw-dns-infra` = `192.168.1.48/28`, all node IPs exempt |
| Phase 2 bypass alerting (Vector → ntfy + Loki) | **LIVE, verified** | Samsung TV `.154` caught; throttle working |
| Grafana `dns-bypass` dashboard | **LIVE** | `grafana_dashboard: "1"` label; stat + time-series + table |
| Phase 3 IPv6 RDNSS fix | **REVERTED** | Link-local broke Win11; redo with ULA/global |
| Adult Mac MACs in Pi-hole adults group | Committed (`7421031`) | Harmless now; needed for Phase 3 redo |
| DNS lockdown runbook | Codified (`d11a8d1`) | `unifi-ops/SKILL.md`, invariant + pre-flight + break-glass |
| Rory's iPhone in adults group | **OPEN BUG** | `aa:27:4d:5b:13:f8` should be in kids group |
| go-unifi-mcp | Down for session | Stdio crash; revive = restart Claude Code |
| UDM firewall + syslog config | Live on UDM (non-GitOps) | Captured by weekly `unifi-backup` CronJob |

---

## 10. Open items

- [ ] **Phase 3 redo — ULA/global v6 on the Pi nodes.** Assign a stable ULA prefix to
  `pi-k3s` (`.55`) and `pi5-worker-1` (`.56`), verify Pi-hole/FTL listens on it, set
  `dhcpdv6_dns_1` to that ULA address, **test on a Win11 device first** before trusting
  macOS verification alone.
- [ ] **Remove Rory's iPhone from the adults allowlist.** MAC `aa:27:4d:5b:13:f8` is in the
  `adults` group on both Pi-holes and in `pihole-allowlist-configmap`. Remove it from both.
- [ ] **DoH-over-443-to-hardcoded-IP gap.** Port-53/853 is locked; port-443 to a hardcoded
  resolver IP is not. Future option: maintain a DoH-endpoint IP blocklist and block it at
  the UDM.
- [ ] **`[v4]` mislabel on v6 drops in the Vector parser.** The `ip_ver` VRL field detects
  by rule-name substring; minor cleanup.
- [ ] **Document that UDM firewall rules and syslog config are non-GitOps.** They live on
  the UDM and are backed up only by the weekly `unifi-backup` CronJob. Relevant if the UDM
  is ever reset or replaced.
- [ ] **Subscribe to `dns-bypass` ntfy topic.** Currently `subscribers=0` — no one receives
  the pushes. Subscribe as the `family` user: `https://ntfy.mtgibbs.dev/dns-bypass`.
- [ ] **Clean the broken postStart `setup.sh` calls** on both Pi-hole deployments (`cc4fae2`
  left dead hook code; the actual config is applied by the `pihole-brainrot-setup` Job).

---

## Commits

| Hash | Subject |
| :--- | :--- |
| `ae33e5c` | feat(log-aggregation): UDM firewall syslog ingestion via Vector |
| `c081495` | feat(log-aggregation): DNS-bypass alerting — parse UDM drops, ntfy + Loki |
| `5648ff2` | fix(log-aggregation): ntfy sink — disable healthcheck, drop console flood |
| `3111796` | fix(log-aggregation): ntfy auth — strip newline, build header in VRL |
| `4220d95` | fix(log-aggregation): vector --watch-config for ConfigMap hot-reload |
| `6b535fa` | fix(log-aggregation): ntfy sink — back to static basic auth + force rollout |
| `d11a8d1` | docs(unifi-ops): DNS lockdown runbook (invariant, pre-flight, break-glass) |
| `4358a70` | feat(monitoring): DNS-bypass Grafana dashboard (Loki) |
| `7421031` | feat(pihole): adult Mac MACs for IPv6 exemption (Phase 3) |
