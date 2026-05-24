---
name: coding-agent-ops
description: Operating the local coding agent — qwen3-coder via opencode, Claude-orchestrated, spec-driven. Use when running/troubleshooting `oc`, the ralph-qwen loop, or the laptop↔Beelink-qwen creds.
allowed-tools: Bash, Read, Grep, Glob, Edit, Write
---

# Local Coding Agent — Operations

The operational runbook for running **qwen3-coder** as an executing coding agent under Claude
orchestration. For the *why / findings / open decisions*, see `docs/research/local-coding-agent-sdd.md`.
For the *SDD method* (how to write specs), see `specs/README.md`.

## What's wired (as-built)

| Piece | Where | Notes |
|---|---|---|
| Harness | `opencode` 1.15.6 (Homebrew, on the laptop) | provider-agnostic; only ever points at qwen, never Claude |
| Brain | `qwen3-coder-30b` on the Beelink | via LiteLLM `https://ai.lab.mtgibbs.dev/v1` |
| Provider config | `opencode.json` (repo root) | custom `beelink` provider; model = `beelink/hot-coder` (**follows `aimode`**: 30B family / Q8 work); `instructions: ["AGENTS.md"]`; unused tools (`skill`/`task`/`todowrite`) disabled to shrink the preamble |
| Agent brief | `AGENTS.md` (repo root) | qwen's lean operating brief — NOT `CLAUDE.md` (that's Claude-only, too big) |
| Launcher | `scripts/oc` → `~/.local/bin/oc` | loads the key, adds a watchdog timeout to `oc run` |
| Loop | `scripts/ralph-qwen.sh` | one-task-per-iteration, fresh context, verify-gated |
| SDD docs | `specs/{README,TEMPLATE,constitution,design-principles}.md` | the spec practice |

## Day-to-day usage

```bash
oc                       # interactive TUI (qwen3-coder)
oc run "do one thing"    # headless one-shot (watchdog: OC_RUN_TIMEOUT, default 600s)
```

**The supervised SDD loop** (the intended flow):
1. Write `specs/<feature>/spec.md` from `specs/TEMPLATE.md` (outcomes, scope, EARS §7 criteria).
2. Plan: resolve correctness + **granularity** (verify the exact field, not a proxy) + **design**
   (idiomatic/tasteful pattern, per `design-principles.md`) unknowns. Fold answers into §10.
3. Write `specs/<feature>/verify.sh` — §7 compiled to a deterministic static gate (exit 0 = ok).
4. Decompose §6 into `tasks.txt`; run on a **git worktree/branch**:
   `scripts/ralph-qwen.sh specs/<feature>`
5. Review the diff against §7 + eyeball the rendered result (taste); merge via PR.

> **Capture quirk:** piping `oc run … | tail` in a *backgrounded* shell can swallow opencode's
> output (TTY detection). Redirect to a file (`oc run … > out.txt 2>&1`) or run in a real terminal.

## Credentials & re-bootstrap

Working creds are **local** (device→tool, trusted machine, no biometric lockout); **canonical
copies stay in 1Password**. Crown-jewel / cluster-acting creds stay behind Touch ID — do NOT
relocate those.

- **qwen key (`oc`):** macOS Keychain, service `opencode-qwen`. `oc` reads Keychain-first, 1Password fallback. Re-seed:
  ```bash
  security add-generic-password -U -s opencode-qwen -a oc -T /usr/bin/security \
    -w "$(op read 'op://pi-cluster/opencode-coder/password')"
  ```
- **SSH to the box:** `~/.ssh/beelink-ai` (0600) + `~/.ssh/config` `IdentityAgent none` for that host. Re-extract:
  ```bash
  op read 'op://pi-cluster/beelink-ai SSH/private key?ssh-format=openssh' > ~/.ssh/beelink-ai && chmod 600 ~/.ssh/beelink-ai
  ```
- **Bootstrap a new machine:** `cp scripts/oc ~/.local/bin/ && chmod +x ~/.local/bin/oc`, `brew install opencode`, then re-seed the two creds above.

## Operating rules (guardrails)

- **opencode drives qwen only — never Claude** (Claude via opencode = metered/capped/ToS-risky; see research §3).
- **Supervised runs** while you're present (the loop isn't trusted unattended yet).
- **PR-gated:** output is a reviewed diff; Flux applies on merge. Never direct-to-cluster.
- **The loop runs `verify.sh`; the model never self-certifies "done".**
- **Bound scope + fresh context per task** (avoids the context bloat that preceded a stall).

## Known failure modes → fix

| Symptom | Cause | Fix |
|---|---|---|
| Run hangs for a long time | un-timed-out streaming stall (NOT the GPU — verify model with a direct `/api/generate`) | watchdog kills it (`OC_RUN_TIMEOUT`); bound scope |
| Output looks correct but ugly | no taste in the spec/model | `design-principles.md` + human visual review |
| Widget/config wrong despite "correct" spec | model executed a **spec bug** faithfully | specs must be correct; **test worked examples** before handoff |
| ExternalSecret won't sync | verified the *item*, not the *field* | check the exact field exists (the prowlarr lesson) |
| Biometric lockout mid-session | a cluster-gated cred crept onto the hot path | hot-path creds belong in Keychain/on-disk (above); crown jewels stay biometric |
| Dewey cold after `aimode family` | `aimode warm()` was a no-op (ollama image has no curl) — fixed 2026-05-24 to use `docker exec open-webui curl` + Dewey's real models | redeploy `beelink-ansible/files/aimode.sh`; warm path must hit ollama from a container that *has* curl |
| Want the loop on the Q8 | `oc` follows `hot-coder` → run `aimode work` (sole-tenant Q8 @ 32k). 30B@64k is niche (slow prefill, see research §12) — prefer Q8 + decompose | `aimode work` then `oc`; `aimode family` to restore |

## Pointers

- Research log (findings, gaps, open decisions): `docs/research/local-coding-agent-sdd.md`
- SDD method: `specs/README.md`, `specs/TEMPLATE.md`, `specs/constitution.md`, `specs/design-principles.md`
- Launcher + loop + cred details: `scripts/README.md`, `scripts/oc`, `scripts/ralph-qwen.sh`
- First worked example: `specs/homepage-refresh/` (spec.md §11 tuning log + verify.sh)
