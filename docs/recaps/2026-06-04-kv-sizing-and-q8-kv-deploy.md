# Session Recap — 2026-06-04 (KV Cache Sizing, Prefix Reuse Measurements, q8_0 KV Shipped)

This recap covers a thread that started at QCon (~2026-06-01) and resumed for measurements and a deploy on 2026-06-04. The work has three parts: a living research doc built section by section from QCon notes, two measurements run directly on the Beelink, and the q8_0 KV-cache quantization committed to `beelink-ansible` and deployed to production.

Related prior recaps: `docs/recaps/2026-05-21-q8-coder-agent-comparison.md` (model tier strategy, OLLAMA_CONTEXT_LENGTH fix) and `docs/recaps/2026-05-24-ai-controlpanel-and-context-budget.md` (32k-vs-64k prefill benchmark, Path A/B decision).

---

## Chapter 1 — The Research Doc: `docs/research/kv-sizing-and-sessions.md`

### What

A new living research document built section by section from QCon 2026 notes, covering the full KV cache lifecycle from budget sizing through quantization and agentic-flow optimizations, with everything mapped to what the Beelink can actually do today.

### Why

Previous sessions (the CONTEXT_LENGTH crisis, the context-budget benchmark) produced scattered institutional knowledge. The KV budget is the single most important resource constraint on the Beelink — it is not the weights that blow the budget on a 128 GB machine, it is the KV cache from `NUM_PARALLEL × context_length × kv_bytes`. The doc is the durable home for that understanding.

### Structure

| Section | Topic |
|---|---|
| §0 | Guiding principle: minimize copies of KV state |
| §1 | KV budget math: weights + NUM_PARALLEL × context × kv_bytes share one pool; admit by projected KV footprint, not concurrency |
| §2 | Prefix caching: the causal-chain intuition (KV is a vector bound to a causal chain; evicting any mid-prefix token forfeits the whole tail; reuse only works contiguously from token 0) + MEASURED results (see Chapter 2) |
| §3 | Tiered/remote KV — unified memory collapses the hierarchy for us; the "spill-survives-churn" angle |
| §4 | LMCache + Valkey: chunk=256 tokens, tiered-not-remote-only |
| §5 | Frontier KV techniques |
| §6 | P/D disaggregation — includes the ABCD exercise (the "switch-tax" analogy: reciting A B C D is easy; interleaving A1 B2 C3 D4 is slow → prefill vs decode interference → motivates disaggregation; single-box echo = chunked prefill) and cache-aware routing (vLLM consistent-hash, Dynamo tunable KV-overlap threshold) |
| §7 | The talk's close: three pillars (cache-aware placement / disaggregation / KV state) + "every token becomes state someone has to carry" / "plan the KV not the QPS" / "design for the state you create" |
| §8 | Tool defs live in the prefix: MCP schema churn busts the cache; cloud prompt-caching cost angle (cache_read ≈ 10% cost; proxy exposes hit-rate) |
| §9 | "Steal the principle, skip the framework" synthesis table: every gated datacenter technique paired with the hardware-agnostic 80/20 for this box |
| §10 | Quantization: weight quant ladder (Q4_K_M sweet spot; IQ to fit bigger models) + KV-cache quant (`OLLAMA_KV_CACHE_TYPE=q8_0`, FA prereq already met) + MEASURED results (see Chapter 2) |
| §11 | Agentic-flow optimizations: ordered levers (prefix reuse first, assembly discipline, context-growth management, agentic KV shape, route-by-step-type) |

The unifying theme: this is a one-iGPU shop. The win is "create less state / reuse what was already computed," not the multi-box carrying machinery from the talk.

### Commits (2026-06-01)

| Hash | Subject |
|---|---|
| `8b3e032` | docs(research): KV sizing & prefix-caching notes (QCon 2026) — initial scaffold |
| `bdc5877` | docs(research): admit by projected KV footprint, not concurrency (§1) |
| `f30dfee` | docs(research): LMCache + Valkey notes (§4) |
| `921c5f6` | docs(research): tiered/remote KV — unified-memory collapses the hierarchy (§3) |
| `a313e2f` | docs(research): cache-aware routing (§6) |
| `f13d296` | docs(research): P/D disaggregation deep-dive + single-device echo (§6) |
| `41eaa00` | docs(research): §7 — talk's close (three pillars) |
| `ce02715` | docs(research): §8 — tool defs live in the prefix + cost angle |
| `fc13c8a` | docs(research): §2 — the causal chain (why caching is prefix-shaped) |
| `1a2f0c5` | docs(research): §9 — "steal the principle, skip the framework" synthesis table |
| `037a29a` | docs(research): §6 — fill in the ABCD exercise |
| `8210cde` | docs(research): §10 quantization + §11 agentic-flow optimizations |

---

## Chapter 2 — Two Measurements on the Actual Box

Hardware: Beelink GTR9 Pro, Ryzen AI Max+ 395 (gfx1151 / Strix Halo), 128 GB unified RAM, Ollama 0.17.7 on Vulkan/RADV. Live config going in: `OLLAMA_CONTEXT_LENGTH=32768`, `NUM_PARALLEL=2`, `MAX_LOADED_MODELS=3`, `FLASH_ATTENTION=1`.

### Measurement 1 — Prefix reuse (2026-06-04, commit `a2e71ac`)

**Setup:** `qwen3-coder:30b`, ~5,078-token shared prefix, 6 sequential calls over Tailscale SSH.

| Call | `prompt_eval_duration` | Notes |
|---|---|---|
| 1 (cold) | 22,615 ms (~225 tok/s) | Full KV build |
| 2–6 (warm) | ~290 ms | Cache hit; prefix served from KV |

**Result: ~77x speedup. Within-session prefix reuse is confirmed and huge.**

Two findings that revise earlier notes:

1. **Watch `prompt_eval_duration`, not `prompt_eval_count`.** Ollama reports the full prompt token count even on a cache hit. Duration is the honest signal for whether the cache fired.

2. **No NUM_PARALLEL=2 warm-up penalty for sequential agentic loops.** `llama.cpp` picks the slot with the longest common prefix, so a single agent self-warms across calls. The earlier concern about NUM_PARALLEL=2 thrashing was real but narrower than believed — it only applies when two or more *different* long sessions are competing for both slots simultaneously.

**Implication:** a cold 32K agentic context costs ~145 seconds of prefill at this hardware. Cache reuse is not a nice-to-have; it is make-or-break for agentic loop latency.

### Measurement 2 — q8_0 KV-cache quantization (2026-06-04, commit `5ed075e`)

**Setup:** edited the on-box `docker-compose.yml` to add `OLLAMA_KV_CACHE_TYPE=q8_0`, tested with `qwen3-coder:30b` at 32K × 2 slots, then reverted to `f16` to leave no untracked drift.

| Metric | f16 baseline | q8_0 | Delta |
|---|---|---|---|
| KV cache size | 6.0 GiB | 3.2 GiB | −47% |
| GPU placement | 100% Vulkan0 (49/49 layers) | 100% Vulkan0 (49/49 layers) | No change |
| CPU fallback | None | None | No regression |
| Output quality | Coherent | Coherent | No regression |

**Result: KV halved, stayed fully on GPU, output coherent.**

The prior Vulkan concern (whether KV quant was safe on RADV) is cleared. Flash Attention prerequisite (`FLASH_ATTENTION=1`) was already met. Across 3 loaded models, `~3 GB freed each = ~9 GB total` — headroom for a larger `num_ctx` or a fourth model. Near-zero quality cost.

---

## Chapter 3 — q8_0 Made Permanent in IaC (commit `9a2cdfd`, deployed)

### What

`OLLAMA_KV_CACHE_TYPE=q8_0` committed to `beelink-ansible` repo, `playbooks/50-ai-stack.yml` (which renders `/opt/ai-stack/docker-compose.yml`). Deployed via `ansible-playbook`.

### Why this matters architecturally

The Beelink is **not in the Flux repo** — it is a standalone Ansible-managed host. `/opt/ai-stack/docker-compose.yml` is a rendered artifact; hand-edits on the box get overwritten on the next `git pull + playbook` run. The source of truth is `beelink-ansible/playbooks/50-ai-stack.yml`. Any configuration that should survive a rerun must live there.

### How

Secrets were supplied as extra-vars from 1Password via `op read` piped into a `chmod 600` temp file, shredded after the run:

```
ansible-playbook 50-ai-stack.yml -e @<tempfile>
```

Result: `ok=40 changed=4 failed=0`.

Side effect: the Open WebUI image-pull step (OWUI tracks a moving `:main` tag) bounced both OWUI instances. Both recovered healthy within the play.

### Verified end state

`OLLAMA_KV_CACHE_TYPE=q8_0` confirmed live in running container env. All containers healthy.

### Commits (2026-06-04)

| Repo | Hash | Subject |
|---|---|---|
| `beelink-ansible` | `9a2cdfd` | feat(ollama): add OLLAMA_KV_CACHE_TYPE=q8_0 (KV halved, stays on Vulkan) |
| `pi-cluster` | `5ed075e` | docs(research): §10 — MEASURED q8_0 KV (6.0→3.2 GiB, stays on Vulkan, ~9 GB freed) |
| `pi-cluster` | `90fda3c` | docs(research): §10 — q8_0 KV now PERMANENT (committed + deployed 2026-06-04) |

---

## Chapter 4 — The Remote-Ops / VPN Gap (Discovered, NOT Yet Fixed)

During the off-net Ansible deploy (laptop on `10.10.10.x`, Tailscale exit node = pi-cluster), a connectivity gap became concrete:

- **What works**: ICMP + SSH to Tailscale `100.x` IPs.
- **What does not work**: all service ports — LiteLLM `:4000` and Ollama `:11434` are Docker-internal (not host-published, by design); K8s API `:6443` and Caddy `:443` are blocked by the Tailscale ACL (`autogroup:member` is not granted to `tag:inference` or cluster tags; only `tag:k8s-operator ↔ member` is).
- **Root cause**: the full home `/24` is not routed over Tailscale — only `/32`s for `.55`/`.56` are advertised. The Beelink's LAN IP `192.168.1.70` is unreachable from the Tailscale exit node.

**Practical consequence:** the first deploy attempt failed because `beelink-ansible`'s inventory resolves `beelink-ai` → `192.168.1.70` (LAN, unrouted from Tailscale). Required override: `-e ansible_host=100.123.94.31` (Tailscale MagicDNS IP).

**Proposed fixes (open, not yet decided):**

| Option | Description | Scope |
|---|---|---|
| (a) Quick | Point `beelink-ansible` inventory at the Tailscale MagicDNS hostname / `100.x` IP | Inventory-only change; deploy works off-net; services still not reachable |
| (b) Fuller | ACL grant `autogroup:member → tag:inference` + subnet route or DNS so all services reach from the road | Requires Tailscale ACL edit + subnet advertisement |

The durable home for the full analysis is `.claude/skills/tailscale-ops/SKILL.md`.

---

## Key Technical Decisions

### q8_0 KV is the correct default for this hardware

FA=1 was already set. The quant halves KV resident size with no GPU placement regression and no detectable quality loss. Every model that loads under Ollama benefits. There is no reason to keep `f16` KV on a machine where the budget pressure is real and the FA prerequisite is met.

### The Beelink's source of truth is `beelink-ansible`, not on-box edits

Verified the hard way: the deploy pipeline renders `docker-compose.yml` from a Jinja template on every `ansible-playbook` run. On-box edits are valid for testing but must be promoted through the playbook to survive. This applies to all Ollama env vars, Caddy routes, systemd units, and Pipelines configs.

### `prompt_eval_duration` is the canonical cache-hit signal

`prompt_eval_count` is misleading — Ollama reports the full prompt length even when the KV cache absorbed the prefix and no actual prefill work was done. `prompt_eval_duration` drops by ~77x on a cache hit. Any future caching verification should use duration, not count.

---

## Verified End State

| Component | State | Notes |
|---|---|---|
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | Live; committed to `beelink-ansible`; deployed 2026-06-04 |
| KV cache per model | ~3.2 GiB (was 6.0 GiB) | At 32K context × 2 slots, `qwen3-coder:30b` |
| GPU placement | 100% Vulkan0, 49/49 layers | No CPU fallback; Vulkan KV-quant concern cleared |
| Prefix reuse | Confirmed ~77x speedup | Within-session; `NUM_PARALLEL=2` no penalty for sequential loops |
| `kv-sizing-and-sessions.md` | 11 sections complete | Durable research doc; open-questions checklist at end |
| Off-net Ansible deploy | Workaround found (`-e ansible_host=`) | Root cause documented; fix not yet implemented |
| All containers | Healthy | OWUI bounce during deploy; recovered within play |

---

## What Remains

- [ ] Fix `beelink-ansible` inventory to use the Tailscale MagicDNS name / `100.x` IP so off-net deploys work without the `ansible_host` override (option a)
- [ ] Decide whether to grant `autogroup:member → tag:inference` in the Tailscale ACL for full road-access to LiteLLM and Caddy (option b — see `.claude/skills/tailscale-ops/SKILL.md`)
- [ ] Per-model `num_ctx` tuning: the freed ~9 GB could go toward a larger context window on specific models (e.g., bump the agentic/ops slot to 48K or 64K) — still on the measurement checklist
- [ ] Route-by-size: short requests (Dewey keyword extraction, quick Q&A) vs long agentic loops have different KV pressure profiles; the `hot-coder` / `hot-reasoner` alias layer is already in place to support this; the routing logic is not yet built
- [ ] Validate `NUM_PARALLEL=2` behaviour under real concurrent load — the measurement confirmed no penalty for a single sequential agent; two competing long sessions were not tested

---

## Related Documentation

- `docs/research/kv-sizing-and-sessions.md` — the living research doc built this session
- `docs/beelink-ai-stack.md` — Beelink hardware framing, aimode timings, Vulkan runbook
- `docs/recaps/2026-05-21-q8-coder-agent-comparison.md` — two-tier model strategy, `OLLAMA_CONTEXT_LENGTH=32768` rationale
- `docs/recaps/2026-05-24-ai-controlpanel-and-context-budget.md` — 32k-vs-64k prefill benchmark, Path A/B context decision
- `.claude/skills/tailscale-ops/SKILL.md` — durable home for the off-net VPN gap analysis
