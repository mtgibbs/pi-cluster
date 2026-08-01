---
description: Test DNS resolution through Pi-hole and Unbound
allowed-tools: mcp__homelab__diagnose_dns
argument-hint: [domain]
---

# DNS Resolution Test

Test resolution through the Pi-hole + Unbound stack.

## Configuration
- Pi-hole IP: 192.168.1.55
- DNS Flow: Client → Pi-hole (53) → Unbound (5335) → Root servers
- Wildcard: `*.lab.mtgibbs.dev` → 192.168.1.55

## Tests to Run

Domain to test: $ARGUMENTS (default: `google.com`)

1. `diagnose_dns(domain)` — the external domain. This single call walks the **whole** path:
   Pi-hole cache, Unbound primary, Unbound secondary, and DNSSEC. It is **cache-bypassing**.
2. `diagnose_dns("test.lab.mtgibbs.dev")` — the internal wildcard; expect 192.168.1.55.

## Why not `test_dns_query` or `dig`

- `test_dns_query` can return a **stale cache** hit — a green from it does not prove resolution
  works. Never close a DNS question on it.
- `dig @192.168.1.55` was the laptop-era check. This harness runs in a container off the LAN;
  it reaches DNS only through the homelab MCP.

## Expected Results

- External domains: resolve, DNSSEC validates, both Unbounds answer
- `*.lab.mtgibbs.dev`: returns 192.168.1.55
- Any leg failing = a real finding — report *which* leg

## Output

Report per-leg status (Pi-hole / Unbound primary / Unbound secondary / DNSSEC), response times,
and any failures. If a leg is down, that's an **Investigate** — fan out `cluster-diagnostics`
with `patterns/dns.md` rather than retrying the same query.
