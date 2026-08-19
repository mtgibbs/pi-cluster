# Beelink host-RAM OOM + the stale-model 400s (investigation 2026-08-19)

**Purpose:** the record and remediation plan for a report that "the qwen Beelink box keeps crashing
out." Investigation was read-only; **nothing on the box was changed.** Companion docs:
`docs/beelink-ai-stack.md` (the stack), `docs/model-onboarding.md` (§2 memory budget),
`.claude/skills/coding-agent-ops/SKILL.md` (the `oc` loop and its known stalls),
`docs/n8n-email-pipeline.md` (the pipeline in Fault B).

---

## TL;DR — the box never crashed

`beelink-ai` has **74 days uptime**, last boot 2026-06-06. No panic, no reboot, no thermal trip, no
GPU fault, no container restart. The reported "crashing out" is **three unrelated faults**, and they
want three different fixes at three different confidence levels.

1. **Fault A — host-RAM OOM kills. REAL, HISTORICAL, MECHANISM STILL ARMED.**
   8 kills between 2026-07-10 and 2026-07-14 (`llama-server` ×5, Prisma ×3). None since. **Nothing
   was fixed** — the conditions that produced them are all still in place.
2. **Fault B — n8n has called a deleted model for 10 weeks. UNAMBIGUOUS, CHEAP TO FIX.**
   152 × HTTP 400 in 72 h, hourly, ongoing. The model was removed deliberately on 2026-06-06.
3. **Fault C — `opencode` streams aborted mid-response. SYMPTOM REAL, MECHANISM UNPROVEN.**
   8 aborts in 26 h. Correlating conditions identified; causation is **not** established.

**The deepest finding is not any of the three.** It is that Fault B ran at a **100% failure rate for
ten weeks with zero signal reaching a human.** See [Phase 4](#phase-4--the-fault-that-hid-fault-b).

---

## The fact that reframes the whole box

> The Beelink has 128 GB. **~96 GB is carved to VRAM and is invisible to the OS.**
> The kernel sees **30 GiB**, and that is the resource everything actually competes for.

And the part that turns it into a fault:

> **`llama.cpp` keeps its prompt cache and context checkpoints in HOST RAM, not VRAM.**
> Currently an `8192 MiB` cache limit plus a 32-slot checkpoint ring at **75.376 MiB each**.

So pushing longer contexts grows llama-server's footprint in the **scarce** 30 GiB pool while VRAM
sits comfortable. Every OOM kill below is `global_oom` — the *host* ran out, not a container limit.

This is the same shape as the active-vs-total parameter trap in `docs/model-onboarding.md` §2: the
number everyone quotes (128 GB / total params) is not the number that binds.

---

## Evidence

### Fault A — the kill log

`dmesg` reported **zero** OOM events and was **wrong** — its ring buffer had wrapped back to Jul 27.
The persistent journal (`journalctl -k -b 0`) has the record. *Do not trust `dmesg` on this box; 74
days of uptime means it only holds recent history.*

| When | Victim | anon-RSS at kill |
|---|---|---|
| 2026-07-10 14:40 | `llama-server` | 9.5 GB |
| 2026-07-11 07:02 | `llama-server` | 12.1 GB |
| 2026-07-11 15:21 | `llama-server` | 6.7 GB |
| 2026-07-11 17:41 | `llama-server` | 9.2 GB |
| 2026-07-11 17:42 | `query-engine-de` (Prisma) | 5.4 GB |
| 2026-07-11 20:00 | `llama-server` | 11.1 GB |
| 2026-07-14 11:12 | `query-engine-de` (Prisma) | 5.2 GB |
| 2026-07-14 16:32 | `query-engine-de` (Prisma) | 7.3 GB |

All `constraint=CONSTRAINT_NONE, global_oom`. `llama-server` is the **victim, not necessarily the
culprit** — the kernel picks the largest RSS, and `llama-server` runs with `Memory=0` (no Docker
limit), so it is always the fattest target.

### State at time of investigation (2026-08-19 17:30 EDT)

| Metric | Value | Read |
|---|---|---|
| VRAM | 85.9 / 96.0 GiB | Fine — never the constraint |
| Host RAM | 22.6 / 30 GiB, 8.5 GiB avail | Tight but not critical |
| Swap | 3.9 / 8 GiB used | Cold pages; PSI says not thrashing |
| PSI memory | `avg10=0.00 avg60=0.00` | **Not** under pressure right now |
| `query-engine-de` RSS | **8.40 GiB**, 17 d uptime | **Leak** — see Phase 3 |
| `llama-server` RSS | 6.58 GiB, 2 d uptime | Within its 8 GiB cache budget |

**Why the kills stopped on 2026-07-14 is unexplained.** Swap was *not* the mitigation — `/swap.img`
was created 2026-04-27, well before. Treat the five quiet weeks as **luck, not a fix.**

### Fault B — the stale model

```
400: Invalid model name passed in model=qwen3-30b-instruct
```

- **152 occurrences in 72 h**, on the hour, every hour. First seen in window 2026-08-16T22:00,
  most recent 2026-08-19T21:00. Still firing.
- The model was **deliberately removed 2026-06-06** — `docs/beelink-ai-stack.md:334`:
  *"Permanent fix (done 2026-06-06): `ollama rm qwen3-30b-instruct` + deregistered it from LiteLLM."*
- The reason it was removed, from `docs/recaps/2026-06-06-dewey-ai-setup-and-latency-baseline.md:101`:
  *"WEDGED. 0 tok/300s, GPU pegged, `amdgpu Fence fallback timer expired on ring comp_1.1.0`. Reboot
  did NOT clear it. **Do NOT use this unsloth UD quant on Vulkan.**"*

**Callers still hardcoding it:**

| File | Lines |
|---|---|
| `clusters/pi-k3s/n8n/workflows/digest-builder.json` | 73, 106 |
| `clusters/pi-k3s/n8n/workflows/inbound-mail.json` | 115 |

**What LiteLLM serves today** (from `config.yaml`; DB-backed models registered via `/model/new` are
**not** in this list and were not enumerable — see [OQ1](#open-questions)):

`qwen3-0.6b` · `qwen3.5-9b` · `gemma3-27b` · `qwen3-coder-30b` · `qwen3.5-35b` · `qwen2.5-72b` ·
`qwen3-coder-next-q8` · `nomic-embed`

**Blast radius:** the family-board **daily digest** and the **inbound-mail extraction**. Both are
100% failing *now* — that part is measured. That they have been failing **since 2026-06-06** is an
**inference**, not a measurement: the available `litellm` log window is only 72 h, and the inference
rests on the model having been removed on that date while the workflows still name it. Confirming it
needs n8n's own execution history, which was not read during this investigation.

### Fault C — the aborted streams

Caddy, 8 occurrences in 26 h, all from one client:

```
"aborting with incomplete response"
upstream: litellm:4000   client_ip: 192.168.1.82
User-Agent: opencode/1.17.15 ai-sdk/…
Content-Length: 305499 / 334174        (~300 KB prompts)
durations: 0.9s, 1.4s, 2.2s, 2.6s, 5.0s, 12.7s
```

Correlating server-side conditions, all live:

- `n_parallel` auto-selected **4 slots**, each `n_ctx = 262144`, `kv_unified = true`
- **5,983** `erased invalidated context checkpoint` events in 2 days — heavy prompt-cache thrash
- `created context checkpoint 32 of 32` — the checkpoint ring is **saturated**
- Throughput **~29 t/s**, roughly **half** the 59 t/s recorded in `docs/model-onboarding.md` §6

**This is correlation only.** A plausible chain is that with 4 slots sharing one unified KV, an
arriving request invalidates an in-flight slot's context and kills the stream — but that is a
**hypothesis**, and per §4 of the onboarding runbook it stays one until an A/B says otherwise.

---

## RULED OUT — don't re-chase

- **Machine crash / reboot / panic** — 74 days uptime, boot history clean since 2026-06-06.
- **GPU fault** — zero `amdgpu`, `drm`, ring-timeout, or GPU-reset lines in the journal.
- **Thermal** — no throttle or thermal events.
- **Disk** — `/` at 71%, 28 GB free.
- **VRAM exhaustion** — 85.9 of 96.0 GiB. Never the binding constraint. **This is the intuitive
  suspect on an inference box and it is wrong here.**
- **Container crash-looping** — every container reports `restarts=0`. `llama-server`'s "Up 2 days"
  is a *recreate* on 2026-08-17, not a crash restart.
- **`dmesg` as an OOM source** — wrapped, reports 0, actively misleading. Use `journalctl -k -b 0`.

---

## The plan

Ordered by **confidence × safety**, not by severity. Phase 1 has a known-correct answer and cannot
destabilise the running box; Phase 3 is the one that needs evidence before anyone touches a knob.

### Phase 1 — Fault B: repoint the two n8n workflows

**Confidence: high. Risk to the box: none.** Repo change, PR-gated, no Beelink mutation.

| # | Task | Notes |
|---|---|---|
| 1.1 | **Enumerate what LiteLLM actually serves**, including DB-backed models | Blocks 1.2. `config.yaml` is not the full list. Needs a key against `/v1/models` or a read of `proxy_model_table`. |
| 1.2 | **Choose the replacement model** | `docs/n8n-email-pipeline.md:151` requires a **non-thinking Instruct** checkpoint. `qwen3-coder-30b` is a *coder* model and is likely the wrong choice for extraction/summarisation — do not default to it without checking 1.1. |
| 1.3 | Update `digest-builder.json` (lines 73, 106) and `inbound-mail.json` (line 115) | Three string literals. |
| 1.4 | **Verify against a real payload**, not a smoke test | A 200 with garbage output is still a failure for an extraction pipeline. |

> **1.1 is a genuine blocker, not ceremony.** Guessing a replacement is how this pipeline broke in
> the first place: the model name outlived the model.

### Phase 2 — Fault A: stop the host OOM from choosing the inference server

**Confidence: high on the guard rail, medium on the sizing.** `beelink-ansible` PR, applied from the
laptop per `feedback_everything_as_code`.

| # | Task | Notes |
|---|---|---|
| 2.1 | Set a Docker `mem_limit` on `llama-server` | Converts a **global** OOM into a **container** OOM. The kernel stops sacrificing the inference server to save Prisma. This is the single highest-value change in the plan. |
| 2.2 | Set an explicit `--cache-ram` instead of inheriting the 8192 MiB default | The default was never chosen for a box with only 30 GiB of host RAM. |
| 2.3 | Add a `mem_limit` to `litellm` too | Prisma has been OOM-killed 3× and currently holds 8.40 GiB. |
| 2.4 | Re-check `restarts` and the journal after a week of real load | The mechanism is only proven fixed by surviving load, not by the config diff. |

> **Do not raise `-c 262144` or `n_parallel` while doing this.** They are inputs to Phase 3 and
> changing them here would destroy the baseline.

### Phase 3 — Fault C: get a reproduction before touching a knob

**Confidence: low. This phase produces evidence, not a fix.**

| # | Task | Notes |
|---|---|---|
| 3.1 | Capture a failing `oc` run with `llama-server` logs time-aligned to the Caddy abort | Currently we have both sides but have never lined them up on one clock. |
| 3.2 | Establish whether the abort is client-side (opencode) or upstream (llama-server slot eviction) | Caddy's message is ambiguous between the two. This is the fork in the road. |
| 3.3 | Only then A/B `n_parallel` and `--cache-ram` | One variable at a time, same session window — cross-day numbers are invalid (§4). |
| 3.4 | Investigate the Prisma 8.40 GiB leak as its own thread | 17 days uptime, half the spare host RAM. Independent of Fault C. |

> **Also unexplained and worth a line in whatever lands:** throughput is ~29 t/s against a recorded
> 59 t/s. That may be entirely explained by 4 slots at 80–120 k context, or it may be a second
> symptom of the same thrash. Not currently known.

### Phase 4 — the fault that hid Fault B

**This is the one worth doing even if nothing else on this page gets done.**

A pipeline failed **100% of its runs for ten weeks** and nobody found out. Not because the failure
was subtle — it returned a clean HTTP 400 with an explicit error string, hourly, the whole time.
Nothing was watching, so a total outage and a healthy system looked identical from the outside.

That is exactly the failure mode recorded in the repo already: *a passing check and one incapable of
failing look the same.*

| # | Task | Notes |
|---|---|---|
| 4.1 | Alert on LiteLLM 4xx/5xx rate by model name | `litellm-exporter` already runs; the signal exists and is unconsumed. |
| 4.2 | Give the n8n digest + inbound-mail paths an explicit success signal | Absence of output is currently indistinguishable from "quiet week". |
| 4.3 | **Positive-control every alert added here** | Prove it fires by breaking it on purpose. An alert that has never fired is not evidence of health. |

---

## Open questions

- **OQ1 — What does LiteLLM actually serve?** DB-backed models (registered via `/model/new`,
  persisted in Postgres) are invisible in `config.yaml`, and the `psql` read failed during this
  investigation (wrong db/user). **Blocks Phase 1.2.** Notably `hot-coder` — the alias `oc` depends
  on — does not appear in `config.yaml` either, and was not independently confirmed; the coder path
  *is* demonstrably serving (live `tg ≈ 29 t/s`), so this is a gap in the record, not a live outage.
- **OQ2 — Why did the OOM kills stop on 2026-07-14?** No config change found, swap predates it. Until
  answered, the five quiet weeks are not evidence the problem is gone.
- **OQ3 — Is the ~29 t/s a Fault-C symptom or just the cost of 4 slots at 100 k context?**
- **OQ4 — Who else calls a model name that no longer exists?** Fault B was found by accident. The
  same class of rot may exist in other consumers; nothing systematically checks alias validity.

---

## Method note

Every finding above came from read-only commands over `ssh` (`journalctl`, `docker inspect`,
`docker logs`, `/proc/pressure`, `sysfs`) plus a `grep` of this repo. **No process was restarted, no
config was edited, no container was touched** — the box was reported as "running again" and was left
that way.
