# ADR-009: Docker Sandboxes (sbx) — Adopt as a Disposable Blast Zone, Not as a Harness Retrofit

## Status
Accepted

## Date
2026-08-18

## Context

We run four coding-agent containers on the Beelink (`coding-harness-{qwen,claude,claude-2,codex}`),
provisioned by `beelink-ansible/playbooks/50-ai-stack.yml` as Docker Compose services. They are
mature: read-only rootfs, `cap_drop: [ALL]`, `no-new-privileges`, non-root uid 1000, no Docker
socket, no kubeconfig, no 1Password service token, no NAS mount, `mem_limit`/`cpus` caps, and all
output PR-gated. Full description in `.claude/skills/coding-agent-ops/SKILL.md`.

That skill also records an open gap:

> **Known gap, not yet built:** egress isn't restricted to just `ai.lab.mtgibbs.dev` + `github.com`
> — the containers can reach the open internet like any other Docker container on this host.

The same gap is why our dependency-install policy is a *written rule* ("`npm ci` allowed for
`mtgibbs/*` repos with a committed lockfile; ask before third-party") rather than an enforced
boundary. Nothing stops a postinstall script from phoning home.

**Docker Sandboxes (`sbx`)** is Docker Inc.'s product for exactly this problem: it runs coding
agents (Claude Code, Codex, Gemini CLI, opencode) inside **microVMs**, each with its own kernel,
Docker daemon, filesystem, and network. v0.38.0 as of 2026-08-06. The CLI is free including for
commercial use; only org-wide governance is a paid tier. Linux is supported (Ubuntu 24.04+,
x86_64 or arm64, KVM required, user in the `kvm` group) alongside macOS and Windows.

Structurally it is close to what we already run. Sandboxes persist until `sbx rm`; `--detached`
starts one without attaching; `sbx ssh` exposes each as `<name>.sbx`; there is a TUI dashboard for
attach/shell/network. That maps nearly 1:1 onto `scripts/harness attach` → `docker exec -it … tmux
attach`.

### What sbx would genuinely buy us

- **An egress policy engine.** All outbound TCP leaves through a host-side proxy enforcing rules
  per connection. Three presets (Open / Balanced / Locked Down), wildcard domains, CIDR ranges,
  port suffixes, global-or-per-sandbox scope, deny-beats-allow precedence. UDP and ICMP are blocked
  outright and cannot be re-enabled by policy. This is precisely our documented gap.
- **A nested Docker daemon per sandbox** — we deliberately have no socket today, so testcontainers
  and image builds are off the table.
- **Credential proxy injection**, keeping API keys out of the sandbox entirely.
- **An MCP gateway** (`sbx mcp`) — register a server once, reuse across agents.

### The hardware reality (measured 2026-08-18, from inside `coding-harness-claude`)

```
MemTotal:      31,960,940 kB   =  30.5 GiB
MemAvailable:   6,736,884 kB   =   6.4 GiB
SwapTotal:      8,388,604 kB   =   8.0 GiB   (≈4.0 GiB in use)
cgroup memory.max = 4 GiB;  memory.current = 425 MiB;  cpu.max = 2 CPUs
nproc = 32   (16C/32T Ryzen AI Max+ 395)
```

**The host OS sees 30.5 GiB, not 128 GB.** The ~96 GB iGPU carve is a UMA reservation taken before
the kernel counts it (128 − 96 ≈ 32). `prometheusrule-beelink.yaml` already carried this correctly
("only 32 GB after the 96 GB VRAM carveout"); it is restated here because it is the single fact
that decides this ADR.

`sbx` allocates **50% of host RAM per sandbox, capped at 32 GiB, with no swap** — at the limit,
processes are OOM-killed rather than paged out. On a 30.5 GiB host the 32 GiB cap never binds, so
we land on the 50% branch: **~15.2 GiB per sandbox.**

## Decision

**Adopt `sbx` narrowly, as a disposable lane for untrusted third-party code. Do not retrofit the
four harness containers. Close the egress gap with our own ansible-managed proxy instead.**

### The arithmetic that decides it

| Scenario | Per sandbox | Four lanes | Verdict |
|---|---|---|---|
| sbx defaults (50% of host RAM) | ~15.2 GiB | ~61 GiB | 2× oversubscribed on a 30.5 GiB host. One sandbox alone exceeds the 6.4 GiB currently available |
| Tuned to today's caps (`--memory 4g`) | 4 GiB + guest kernel | ~16–18 GiB fenced | Fits on paper, leaves nothing for the inference plane |
| One disposable lane (`--memory 6g`) | 6 GiB | n/a | **Viable.** Roughly what is actually free |

### Why a slice is not equivalent to a cap

- **A cap is elastic; a slice is rigid.** This container is capped at 4 GiB and using 425 MiB. The
  unused 3.6 GiB is available to ollama/llama-server right now. A microVM fences its allocation
  whether the agent uses it or not.
- **The slice pays for its own kernel and page cache.** In a container, file reads land in *host*
  page cache — shared and reclaimable. A microVM guest has its own kernel (~200–500 MiB) and its
  own page cache inside the slice, and virtiofs reads are cached on both sides. `--memory 4g`
  therefore yields materially less usable working memory than today's 4 GiB cap.
- **No swap inside the VM.** The host currently leans on ~4 GiB of swap. A dependency install that
  overshoots survives today (slowly); in a microVM it is killed. Memory-spiky installs are exactly
  the workload that drove the `CLAUDE_CODE_TEMP_DIR` / `noexec`-tmpfs fix.
- **It would slow model heat-ups.** `docs/beelink-ai-stack.md` measures page-cache-warm heat-up at
  6.4s for a 25 GB model versus ~15s true-cold. That gap *is* host page cache holding GGUF bytes —
  and file cache is already squeezed to ~1.5 GiB. Every GiB fenced into a rigid slice is a GiB that
  cannot cache model weights, so a retrofit would make `aimode work` flips measurably slower. We
  would be trading inference responsiveness for isolation we do not need.

### The other reasons, briefly

- **Lifecycle conflict.** The harness is ansible + compose, declaratively provisioned, reproducible
  from scratch. `sbx` state lives in its own daemon store, mutated imperatively (`sbx create`,
  `sbx policy allow …`). Adopting it wholesale trades a declarative stack for CLI-managed state — a
  regression against "everything as code, a from-scratch rebuild just works." We would end up
  wrapping every policy call in ansible to stay honest, clawing back much of the benefit.
- **Threat model mismatch.** MicroVM isolation earns its cost when you need Docker-in-Docker, when
  adversarial model behaviour requires hypervisor-level boundaries, or when compliance mandates VM
  isolation. We run our own code, from our own repos, PR-gated, already heavily confined. The gap
  that is actually open is egress, not kernel isolation. `coding-agent-ops/SKILL.md` made this call
  first: "a PR-gated coding loop, not an untrusted-code sandbox."
- **Performance.** Independent hands-on reports describe the overhead as "crippling" for even
  modest projects, plus 2–5s microVM boot. Ralph loops are long-running and file-I/O-heavy —
  virtiofs passthrough is the workload that suffers most.
- **Path-matching.** `coding-harness-claude` deliberately mounts `/Users/mtgibbs/dev` so Claude
  Code's project-memory-directory naming lines up with the laptop's. `sbx` mounts the workspace at
  the same absolute path as on the *host*, which on the Beelink is `/srv/coding-harness-*-data`.
  Solvable via extra workspace mounts, but it is friction against a property we rely on.
- **Vendor.** `sbx` is Docker Inc. proprietary. The free tier is genuinely free, so this is not
  disqualifying, but it is a new proprietary dependency in the trust path of every agent we run —
  in tension with the digital-homesteading preference for vendor-independent tooling.

### What we adopt instead

1. **A disposable blast-zone lane.** `sbx create --memory 6g` for untrusted third-party code:
   model-onboarding evals, the cloned `recipecate-api`/`-ui` prototypes, any repo we do not own.
   This is the case microVM isolation is priced for, and it upgrades the dependency-install policy
   from "ask first" to "run it somewhere it cannot hurt us." Constraint: do not run it concurrently
   with a work-mode Q8 session — there is not enough RAM for both.
2. **Our own egress allowlist proxy**, under ansible, for the four harness containers —
   `ai.lab.mtgibbs.dev`, `github.com`, and the package registries. `sbx`'s real contribution here
   is proving the idea is worth the complexity; we can have the security win without the lifecycle
   regression.

### Open questions (deliberately not resolved here)

- Whether `sbx` enables virtio-balloon free-page-reporting. If it does, unused guest memory returns
  to the host and the rigidity argument softens. Docker's docs do not say, and the documented
  "no swap, OOM at the limit" behaviour suggests they do not reclaim aggressively.
- Whether the `sbx mcp` gateway can express an `X-API-Key` header, which would unblock codex's
  homelab-MCP problem (its streamable-HTTP config supports only a bearer token). Unconfirmed.
- Whether the apt channel covers Ubuntu 26.04 "Resolute" — the install docs target 24.04+.
- Whether the Strix Halo UMA carve is runtime-tunable or BIOS-fixed. Relevant to a *different*
  decision (below), not this one.

## Consequences

### Positive

- We get the isolation where it is actually needed — untrusted code — at a RAM cost the box can pay.
- The four working harness containers are untouched. No migration risk, no lifecycle regression.
- The egress gap gets closed on our own terms, declaratively, without a proprietary dependency in
  the path of every agent.
- The measured 30.5 GiB figure is now written down somewhere load-bearing. It was previously
  implicit in one alert comment and easy to mis-state as "128 GB."

### Negative

- Two mechanisms rather than one: an `sbx` lane *and* a hand-rolled egress proxy. A wholesale
  retrofit would have been conceptually simpler.
- The egress proxy is work we now own and maintain, versus configuration we could have consumed.
- The blast-zone lane cannot run concurrently with work-mode Q8. That contention is a standing
  operational constraint, not a one-time cost.

### Risks

- `sbx` is young and moving fast (0.38.0). Behaviour observed today — memory defaults, policy
  semantics — may shift. Mitigated by using it for a narrow, disposable purpose where a breaking
  change costs us a rebuild, not an outage.
- If the harness ever moves off the Beelink, the RAM arithmetic that decides this ADR changes
  completely and the retrofit question should be reopened. That is a feature of writing the
  measurement down, not a flaw.

## Alternatives Considered

### Retrofit all four harness containers onto sbx

- Pro: one mechanism, strongest isolation, egress policy included.
- Con: does not close arithmetically on 30.5 GiB. Would fence ~16–18 GiB of rigid slices on a host
  already at 6.4 GiB available with swap in use, crush the file cache that makes model heat-ups
  fast, and trade declarative ansible provisioning for imperative CLI state. Rejected on numbers,
  not preference.

### Do nothing — keep the status quo

- Pro: zero work; the containers are already well-confined and PR-gated.
- Con: leaves the documented egress gap open indefinitely and keeps the third-party dependency-install
  policy unenforceable. The gap is real even if the threat is modest.

### Move the harness off the Beelink entirely (e.g. a 16 GB Pi 5)

- Pro: removes harness/inference RAM contention at the root, costs zero VRAM, and the workload
  suits it — verify gates across ~23 specs are python/node/shell with a single `cargo`, and this
  container idles at 425 MiB against a 4 GiB cap on 2 CPUs. A Pi 5's 4 cores would be a per-lane
  upgrade.
- Con: arm64 versus the pinned linux_x64 `ctx` binary baked into the image; SD-card storage is a
  known chronic pain (NVMe HAT effectively mandatory); 4 GiB × 4 lanes exceeds 16 GB with nothing
  left for the OS.
- **Parked as a separate decision, not rejected.** It is orthogonal to sbx — the blast-zone lane is
  worth having wherever the harness lives. Revisit once the OOM-kill history is dated
  (`journalctl -k | grep -i "killed process"` on the Beelink) and the arm64 `ctx` question is
  answered.

### Shrink the UMA carve to give RAM back to the host

- Pro: the split is a real lever. Work-mode Q8 at 256k context occupies ~86 of 96 GiB
  (≈79 GiB weights + ~6.4 GiB KV), so dropping context to 64k frees ~4.8 GiB of KV and the carve
  could fall to ~88 GiB — handing ~8 GiB back, taking the host from 30.5 to ~38.5 GiB (+26%).
- Con: it is a BIOS setting, so "growing the pool later" happens at reboot granularity with work
  mode down and cold model reloads on the way back. The yield is bounded at roughly 8 GiB and costs
  the 256k context that `opencode.json` declares. A lever, not a solution — and unnecessary if the
  harness moves off-box.

## Related

- `.claude/skills/coding-agent-ops/SKILL.md` — harness container architecture, sandboxing posture,
  and the egress gap this ADR responds to.
- `docs/beelink-ai-stack.md` — VRAM carve, `aimode` flip timings, model heat-up measurements.
- `clusters/pi-k3s/monitoring/prometheusrule-beelink.yaml` — memory alerting added while measuring
  for this ADR (PRs #168, #170). The investigation that produced the 30.5 GiB figure also surfaced
  8 cumulative OOM kills, ~176 GiB paged out, file cache at ~1.5 GiB, and `Committed_AS` at 145% of
  `CommitLimit`. All 8 kills predate 2026-08-11; the box is tight, not actively failing.
