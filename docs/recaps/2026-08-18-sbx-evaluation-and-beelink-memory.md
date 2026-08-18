# Recap — the sbx question, and what measuring the Beelink actually found (2026-08-17 → 2026-08-18)

Four PRs (#168, #170, #171, #174). It started as a reading task — *Docker Sandboxes (`sbx`) looks
like our Docker setup, is it time to retrofit it?* — and the answer required a measurement nobody
had taken. That measurement turned out to be the most valuable thing in the arc: **the Beelink's OS
sees ~30.5 GiB, not 128 GB.** It decided the sbx question, produced a new class of alerting, exposed
a false-positive I had shipped myself, and ended with the follow-up work spec'd rather than merely
recorded.

## 1. The question: is sbx a retrofit?

`sbx` (v0.38.0, 2026-08-06) runs coding agents in **microVMs** — own kernel, own Docker daemon, own
network. Free CLI, Docker Inc. proprietary, Linux supported (Ubuntu 24.04+, KVM). Structurally it is
close to what we already run: sandboxes persist until `sbx rm`, `--detached` starts one unattached,
`sbx ssh` exposes each as `<name>.sbx`. That maps nearly 1:1 onto `harness attach` → `docker exec -it
… tmux attach`.

The genuine draw was the **egress policy engine** — a host-side proxy enforcing rules per connection,
three presets, wildcard domains, CIDR, per-sandbox scope, deny-beats-allow, UDP/ICMP blocked outright.
That is exactly the gap `coding-agent-ops/SKILL.md` had carried open since the harness was built, and
the reason our third-party dependency-install policy was a written rule rather than an enforced one.

## 2. The measurement that decided it

Read from inside `coding-harness-claude`:

```
MemTotal:      31,960,940 kB  =  30.5 GiB      SwapTotal: 8.0 GiB (~4.0 GiB in use)
MemAvailable:   6,736,884 kB  =   6.4 GiB      cgroup memory.max = 4 GiB / current = 425 MiB
```

128 − 96 ≈ 32. **The iGPU UMA carve is taken before the kernel counts it**, so everything non-GPU on
that machine shares ~30 GiB. `prometheusrule-beelink.yaml:63` already said so ("only 32 GB after the
96 GB VRAM carveout") — the understanding existed, it just wasn't where anyone designing against the
box would trip over it.

`sbx` allocates **50% of host RAM per sandbox, capped 32 GiB, with no swap**. At our size the cap
never binds, so we land on the worse branch: ~15.2 GiB per sandbox, ~61 GiB for four lanes, on a 30.5
GiB host. The retrofit doesn't fail on preference; it fails on arithmetic.

Three second-order costs mattered as much as the headline:

- **A cap is elastic; a slice is rigid.** The harness container is capped at 4 GiB and using 425 MiB
  — that headroom is real memory ollama can use *today*. A microVM fences it regardless.
- **The slice pays for its own kernel and page cache**, and virtiofs reads get cached on both sides,
  so `--memory 4g` yields materially less working memory than a 4 GiB cap.
- **It would slow model heat-ups.** `beelink-ai-stack.md` measures 6.4s page-cache-warm vs ~15s cold
  for a 25 GB model. That gap *is* host page cache — which is already squeezed to ~1.5 GiB. Fencing
  RAM into rigid slices would trade `aimode work` responsiveness for isolation we don't need.

## 3. What the measurement found on the way: the box is tight

The same `/proc` read surfaced a picture nobody was watching, at 72.3 days uptime: **8 cumulative
`oom_kill`s**, ~176 GiB paged out to swap, ~112 GiB paged back in, file cache down to ~1.5 GiB,
`AnonPages` at 20.8 of 30.5 GiB, and `Committed_AS` at **145% of `CommitLimit`**.

Meanwhile `BeelinkMemoryPressure` — the only memory rule we had — sat quiet at 81.7% used against a
`> 0.90 for: 10m` threshold. Not because the box was fine, but because the metric is **structurally
blind to this failure mode**: `MemAvailable` ignores swap entirely, and an OOM kill *frees* memory,
so a 10m-averaged gauge can never catch the spike that preceded it. Eight kills, silent for all of
them, by construction.

## 4. #168 — alerting the gauge can't do

Three rules, all against metrics node-exporter already exported:

| Alert | Expression | Catches |
|---|---|---|
| `BeelinkOOMKill` | `increase(node_vmstat_oom_kill[1h]) > 0` | The discrete event |
| `BeelinkSwapHigh` | swap `> 0.60`, guarded on `SwapTotal > 0` | Displacement `MemAvailable` ignores |
| `BeelinkMemoryStalled` | `rate(node_pressure_memory_waiting_seconds_total[5m]) > 0.05` | PSI — what pressure *costs* |

Two calls worth keeping: the swap threshold is **60%, not 50%**, because the measured baseline is
49.99% and a 50% threshold would flap on the noise floor. And **all four metrics were verified to
exist before the rules were written** — a rule against a disabled collector fails silently, which is
the exact failure mode being fixed.

That verification needed a technique, since `curl_ingress` returns no response body: query Prometheus
by ClusterIP and compare `sizeBytes` against a deliberately-bogus-metric control (63 bytes for an
empty vector). It proves existence and that PromQL parses — not values. **That limitation is the
whole of §5.**

## 5. #170 — the correction

I read `increase(node_vmstat_oom_kill[1h]) > 0` returning a non-empty result as evidence that a kill
had landed *within the hour*, and reported the 8 kills as **ongoing rather than historical** — in
this conversation, in the #168 commit message, and in its PR body. It was wrong.

`increase()` extrapolates to the range edges, and on a flat low-cardinality integer counter it yields
a phantom positive. Exact arithmetic settled it:

```
(node_vmstat_oom_kill - ... offset 90m) > 0   → empty
(node_vmstat_oom_kill - ... offset 24h) > 0   → empty
(node_vmstat_oom_kill - ... offset 7d)  > 0   → empty
```

The counter hadn't moved in a week. **All 8 kills predate 2026-08-11.** The box is tight, not
actively failing — and the "the Pi-harness decision already has its answer" conclusion I'd drawn from
it was withdrawn.

Same root cause made the shipped rule a latent false-positive generator, so #170 replaced it with
offset subtraction — exact integer arithmetic, no extrapolation — with a `DO NOT rewrite this as
increase(...)` comment carrying the evidence. Documented tradeoff: if the series didn't exist an hour
ago, it returns nothing and we're blind for an hour. Better than a `critical` page that cries wolf.

Merged history can't be rewritten, so the retraction lives in the manifest comments where the next
reader will actually find it.

## 6. #171 — ADR-009, the decision

**Adopt `sbx` narrowly as a disposable blast zone; do not retrofit; close the egress gap ourselves.**

The disposable lane (`sbx create --memory 6g`) is for untrusted third-party code — model-onboarding
evals, cloned prototypes, anything we don't own. That is the case microVM isolation is actually
priced for, and it upgrades the dependency-install policy from "ask first" to "run it where it can't
hurt us." Constraint: not concurrent with a work-mode Q8 session.

Two alternatives were **parked with their numbers**, not dismissed:

- **Move the harness off-box (16 GB Pi 5).** The workload genuinely suits it — verify gates across
  ~23 specs are python/node/shell with a single `cargo`, and the container idles at 425 MiB on 2
  CPUs, so a Pi 5's 4 cores would be a per-lane *upgrade*. Blockers: arm64 vs the pinned linux_x64
  `ctx` binary, SD-card storage, and 4 GiB × 4 lanes exceeding 16 GB.
- **Shrink the UMA carve.** ~8 GiB recoverable (host 30.5 → ~38.5 GiB), costs 256k work-mode context,
  BIOS-granularity — so "grow the pool later" means a reboot. A lever, not a solution.

## 7. #174 — the spec, because a decision isn't a schedule

ADR-009 committed us to building the egress control, and nothing scheduled it. That reads as done
when it isn't, so it became `specs/harness-egress-allowlist/`.

**Belt and braces, in that order:** the braces are a forward proxy with a hostname allowlist; the
belt is host nftables default-deny for the harness subnet. The proxy alone is *not* a boundary —
`HTTP_PROXY` is advisory and any process can ignore it. The nftables rule makes it real; the proxy
makes it legible. No TLS interception: hostname filtering via `CONNECT` answers "which host", and a
MITM CA inside a container running agent code is a worse artifact than the problem.

**Phase 1 is log-only and not optional** — observe a week of real ralph traffic and let the observed
destinations *become* the allowlist. Phase 2 is explicitly not a loop task: it touches host firewall
rules where a mistake costs remote access to the box (Safeguard 7, AC11).

Status is **Draft**: OQ1 (compose network topology) and OQ2 (proxy choice) need a read of
`beelink-ansible` that this container couldn't do, and `tasks.txt` is marked provisional accordingly.

## 8. Lessons

- **Measure the box you're designing for.** Every conclusion in this arc would have been wrong on the
  assumption of 128 GB. The correct number existed in one alert comment and nowhere a designer would
  look; it now lives in ADR-009, the rule comments, and a SKILL.md pointer.
- **A gauge cannot see a discrete event.** `MemAvailable` was silent through 8 OOM kills — not
  misconfigured, *structurally incapable*. When an alert has been quiet, ask whether it *could* have
  fired, not just whether it did.
- **`increase()` lies on flat integer counters.** For "did this counter change", exact offset
  subtraction beats extrapolation. The deeper miss was reading a non-empty PromQL result as evidence
  of an event without an exact-arithmetic control.
- **Exercise a gate before trusting it.** Running `verify.sh` against six fixtures caught a real bug
  in my own lockout safeguard: the SSH guard matched `:22` and sailed past `tcp dport 22 accept`. The
  check whose silent failure would have been most expensive is the one testing found.
- **A decision recorded is not work scheduled.** ADR-009 would have read as complete indefinitely.
  The spec is what makes it real.
- **Finish MCP-dependent verification early.** The homelab MCP dropped mid-session, after the merges
  but before post-deploy checks. Where verification couldn't run, the PR says so rather than implying
  it passed.

## Artifacts

- `docs/adr/009-sbx-sandboxes.md` — the decision, with the arithmetic and the parked alternatives.
- `specs/harness-egress-allowlist/{spec.md,verify.sh,tasks.txt}` — phase-1 work, Draft pending OQ1/OQ2.
- `clusters/pi-k3s/monitoring/prometheusrule-beelink.yaml` — `BeelinkOOMKill` / `BeelinkSwapHigh` /
  `BeelinkMemoryStalled`, plus the correction comment.
- `.claude/skills/coding-agent-ops/SKILL.md` — the "Known gap" paragraph now points at ADR-009.

## Open threads

1. **OQ1/OQ2 on the egress spec** — a laptop-side read of `beelink-ansible` unblocks the loop.
2. **`journalctl -k | grep -i "killed process"`** on the Beelink to date the 8 kills. No longer
   time-sensitive (all >7 days old), but it names the victim, which decides how urgent the off-box
   harness move is.
3. **The parked ADR alternatives** — off-box harness (blocked on arm64 `ctx`), UMA carve shave.
4. **Post-deploy eyeball** on `beelink.rules` in Grafana, since #170's rule change couldn't be
   verified live from the container.
