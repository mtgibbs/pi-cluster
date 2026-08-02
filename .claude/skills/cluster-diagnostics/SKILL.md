---
name: cluster-diagnostics
description: >
  Read-only cluster diagnosis via the homelab MCP. Load when investigating ANY
  "X is broken/slow/down" report. Holds the Diagnostic Discipline, the MCP tool
  gotchas, and the fan-out patterns (one independent layer-check per worker →
  synthesize). Executor-agnostic on purpose: Claude and the local qwen/Beelink
  harness both run these, so the cluster stays diagnosable even without the
  premier model.
---

# Cluster diagnostics — read the layers, prove the path

This skill is **knowledge, not a person.** Two front-ends run it:
- **Claude** via the `cluster-diagnostics` agent (fan out one agent per layer, in parallel).
- **qwen / opencode on Beelink** via its own agent + `mcp-homelab` (run the layers, sequentially if it
  can't parallelize). See [Portability](#portability--surviving-the-loss-of-the-premier-model).

Diagnosis is **read-only.** It never edits manifests, commits, or applies — it produces a **verdict per
layer** and a root cause. Changes are handed to `cluster-ops` (the mutation executor).

## Diagnostic Discipline (the rules that catch real bugs)

1. **Prove the server path first.** Walk the backend chain — pod health → logs → upstream deps — BEFORE
   blaming the client/network. One green light doesn't prove the layers behind it.
2. **Cached success ≠ proof.** DNS caches, stale metrics, and HTTP caches mask failures for hours. Use
   the tool that *bypasses* caches (`diagnose_dns`, not `test_dns_query`).
3. **Check every layer, independently.** That's why we fan out: each layer is a separate question with a
   separate tool and a separate verdict. Serial checking in one thread is slower and biases you toward
   the first thing you looked at.
4. **Return verdicts, not dumps.** Each worker reports "layer X: healthy / broken (evidence)" — not 300
   lines of logs. The orchestrator synthesizes verdicts into a root cause.

## MCP tool gotchas (the non-obvious ones — trust these over instinct)

| Situation | Use / know |
| :--- | :--- |
| DNS resolution | **`diagnose_dns`** — tests Pi-hole + BOTH Unbounds + DNSSEC in one shot, cache-bypassing. |
| DNS "quick test" | `test_dns_query` may return **stale cache** — do NOT trust a green from it. Prefer `diagnose_dns`. |
| **`get_dns_status` says `healthy: false`** | **Read `statsError` before believing it.** The flag is dragged false by a *stats* failure even when every Pi-hole and Unbound pod is Running and ready. Judge DNS health from the `pihole[]`/`unbound[]` pod arrays plus `diagnose_dns` — never from the summary flag alone. |
| Pi-hole query stats | Currently failing **401 Unauthorized** (verified 2026-08-01): the `PIHOLE_API_TOKEN` the MCP holds no longer matches Pi-hole's app password. That's a **credential** problem in *our* repo (1Password `mcp-homelab/pihole-api-token` → `mcp-homelab/external-secret.yaml`), not an MCP code bug — the older v6-API bug ([#17](https://github.com/mtgibbs/pi-cluster-mcp/issues/17)) is **closed/fixed**. Re-minting needs `op` from the laptop; the container can't. |
| Tailscale health | `get_tailscale_status` reports connector `ready: false` even when healthy (still true 2026-08-01). No kubectl here, so judge from the **same payload**: `pods[]` all Running/ready + `activeRoutes` populated = healthy. Escalate for `kubectl describe connector.tailscale.com` only if those disagree. |
| Subtitles history | `get_subtitle_history` returns **HTML** (broken) — don't parse it. Tracked in [#31](https://github.com/mtgibbs/pi-cluster-mcp/issues/31). |
| Any "it works for me" | that's a cached success. Re-check with a cache-bypassing path before closing. |

Full tool list is self-documenting via the MCP — don't memorize it; this table is only the traps.

**Keep this table honest.** Every row is a claim about live behaviour, so it rots in both directions —
a bug gets fixed upstream and we keep teaching the workaround, or the cause changes underneath a
still-true symptom. Both happened to the `get_dns_status` row. When a row actually matters to a
diagnosis, **verify it in the moment** instead of quoting it, and correct it here when it's wrong.

## Fan-out patterns (pre-built layer-sets)

Each is a scenario with its independent layers. Load the one that matches the report:

- **[patterns/dns.md](patterns/dns.md)** — "DNS is down / a domain won't resolve / ad-blocking broke."
- **[patterns/streaming.md](patterns/streaming.md)** — "Jellyfin/Infuse drops mid-stream / playback stalls."
- **[patterns/deploy-health.md](patterns/deploy-health.md)** — "did my deploy actually come up healthy?"
- **[patterns/pod-health.md](patterns/pod-health.md)** — "a pod is crashing/Pending, a Service is
  unreachable" with no recent deploy to blame. Carries the pod-state table and the Pi-specific
  constraints (8GB nodes, the 1GB pi3, ARM64-only, hostNetwork, node-bound `local-path` PVCs).

**How to run a pattern:**
- *Claude:* spawn one `cluster-diagnostics` agent per layer in a single message (parallel), or a
  `Workflow` when you want adversarial verification. Collect the verdicts, synthesize.
- *qwen/opencode:* run each layer's tool call, record the verdict, synthesize at the end. Same layers,
  same discipline — parallelism is an optimization, not a requirement.

New recurring incident? Add a `patterns/<name>.md` with the same shape (When → Layers → Synthesis).

## Offloading reasoning to the local model

The Claude agent may push heavy log/summarization work to the Beelink qwen via `mcp__local-llm__*`
(e.g. `local_summarize` a 2000-line pod log, `local_classify` an error) — keeps the premier model's
context clean and exercises the local path so it stays warm for the resilience case.

## Portability — surviving the loss of the premier model

These patterns are **plain markdown + MCP/kubectl calls on purpose.** If Claude is unavailable, the
qwen/opencode harness on Beelink must keep the cluster diagnosable. That requires, on the Beelink side:
1. `mcp-homelab` configured as an MCP server in opencode (same in-cluster endpoint the Claude harness uses).
2. An opencode agent that loads this skill dir (`.claude/skills/cluster-diagnostics/`) as its instructions.
3. `oc`/opencode able to read this repo (already true for the ralph harness).

The Beelink-side opencode wiring is **container/base-image config** (done from the laptop, not
self-patchable from inside a harness). Tracked separately; see `[[coding-agent-ops]]`. Until it's wired,
this skill is Claude-runnable today and qwen-ready by design.
