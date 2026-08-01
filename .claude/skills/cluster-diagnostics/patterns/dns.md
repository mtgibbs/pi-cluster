# Pattern: DNS diagnosis

**When:** "DNS is down", "a domain won't resolve", "ad-blocking stopped", "internet is slow" (often DNS).

**Architecture reminder:** two independent paths — Pi-hole(`pi-k3s:53`)→Unbound(`:5335`) and
Pi-hole-secondary(`pi5-worker-1:53`)→Unbound-secondary. DNSSEC validated at Unbound, disabled at Pi-hole.
Custom records are GitOps-managed in `clusters/pi-k3s/pihole/pihole-custom-dns.yaml` (never the web UI).
Full architecture: `[[dns-ops]]`.

## Layers (each independent — fan out one worker per layer)

| # | Layer | Tool(s) | Healthy verdict | Red flags |
|---|---|---|---|---|
| 1 | **Full chain (do this first)** | `diagnose_dns` | Pi-hole + both Unbounds + DNSSEC all pass | any leg fails → that's your culprit layer |
| 2 | Pi-hole pods | `get_cluster_health`, `get_pod_logs pihole` | both primary + secondary Running | CrashLoop, gravity/DB errors, OOM |
| 3 | Unbound resolution | `get_pod_logs unbound` (+ secondary) | recursion to roots, no SERVFAIL storms | SERVFAIL, "no route", DNSSEC bogus |
| 4 | Custom/local records | read `clusters/pi-k3s/pihole/pihole-custom-dns.yaml` + `coredns-custom` CM | expected records present; `lab.mtgibbs.dev.server` block intact | missing record, someone edited via UI (won't persist) |
| 5 | Upstream reachability | `test_pod_connectivity`, `get_node_networking` | roots reachable from Unbound pod | egress blocked (check UDM DNS lockdown — 53/853→Pi-hole only) |

## Discipline for THIS scenario

- **Never trust `test_dns_query`** here — stale cache can show green for 24h while resolution is broken.
  Layer 1 (`diagnose_dns`) is the source of truth.
- The `pi-k3s` master intentionally uses **public DNS (1.1.1.1/8.8.8.8)** as bootstrap fallback — that's
  NOT a bug, don't "fix" it.
- The `lab.mtgibbs.dev.server` block in `coredns-custom` is **permanent infrastructure** — its absence,
  not its presence, is the bug.

## Synthesis

`diagnose_dns` usually names the failing leg directly. If it's green but users still fail → suspect
**client-side** (device pinned to a dead resolver, IPv6 RA/RDNSS handing out a stale DNS) — but only
after layers 1–5 are green. If one Unbound is down, the other path should still serve (HA) — a total
outage with one Unbound up points at Pi-hole or the client, not Unbound.
