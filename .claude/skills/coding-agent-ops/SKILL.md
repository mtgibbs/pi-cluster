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
| History search | `ctx` (`~/.local/bin/ctx`, data `~/.ctx`) | indexes Claude + opencode sessions; **orchestrator-side only** — qwen never calls it. opencode imports are lite fidelity (diffs + timing, no prose); the Claude sessions *about* a run carry the analysis |

## Day-to-day usage

```bash
oc                       # interactive TUI (qwen3-coder)
oc run "do one thing"    # headless one-shot (watchdog: OC_RUN_TIMEOUT, default 600s)
```

**The supervised SDD loop** (the intended flow):
1. **Prior-art pass** (Claude, not qwen): `ctx setup` to pick up sessions since the last
   index, then `ctx search "<feature terms>"` + `ctx search --file <path>` for each path in
   the spec's Touches. Fold failed attempts / rejected approaches into §4 and prior
   decisions into §6 — broad single terms beat long phrases. Coverage floor: Claude Code
   pruned transcripts after 30 days until `cleanupPeriodDays: 365` was set (2026-07-08),
   so no Claude history exists before ~2026-06-07 — the recaps in `docs/recaps/` are the
   only record of older work.
2. Write `specs/<feature>/spec.md` from `specs/TEMPLATE.md` (outcomes, scope, EARS §7 criteria).
3. Plan: resolve correctness + **granularity** (verify the exact field, not a proxy) + **design**
   (idiomatic/tasteful pattern, per `design-principles.md`) unknowns. Fold answers into §10.
4. Write `specs/<feature>/verify.sh` — §7 compiled to a deterministic static gate (exit 0 = ok).
5. Decompose §6 into `tasks.txt`; run on a **git worktree/branch**:
   `scripts/ralph-qwen.sh specs/<feature>`
6. Review the diff against §7 + eyeball the rendered result (taste); merge via PR. If the
   loop stopped for a human, `ctx setup` re-indexes the failed run so the re-spec's
   prior-art pass (step 1) can cite it.

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
- **ctx stays out of qwen's path** — never in `AGENTS.md` or opencode's toolset. History
  goes to qwen only as distilled spec text (§4/§6), pre-baked by the orchestrator; a live
  query would burn prefill on the model's bottleneck and reopen the headless tool-use failure.

## Known failure modes → fix

| Symptom | Cause | Fix |
|---|---|---|
| Run hangs for a long time | un-timed-out streaming stall (NOT the GPU — verify model with a direct `/api/generate`) | watchdog kills it (`OC_RUN_TIMEOUT`); bound scope |
| Headless `oc run` writes **no files** / stalls at step 1 | qwen3 emits a malformed **text-format tool call** (`<function=read>`…`</tool_call>`) and never executes it, so generation never starts (seen 2026-06-07 building the Renovate scaffold) | **Don't drive qwen as a tool-*user* when headless.** Make it a pure text generator: spec inline → output between explicit markers on stdout → the orchestrator does the file I/O + verify. The failure is orthogonal to codegen quality — 30B nailed the YAML once tools left the path |
| Output looks correct but ugly | no taste in the spec/model | `design-principles.md` + human visual review |
| Widget/config wrong despite "correct" spec | model executed a **spec bug** faithfully | specs must be correct; **test worked examples** before handoff |
| ExternalSecret won't sync | verified the *item*, not the *field* | check the exact field exists (the prowlarr lesson) |
| Biometric lockout mid-session | a cluster-gated cred crept onto the hot path | hot-path creds belong in Keychain/on-disk (above); crown jewels stay biometric |
| Dewey cold after `aimode family` | `aimode warm()` was a no-op (ollama image has no curl) — fixed 2026-05-24 to use `docker exec open-webui curl` + Dewey's real models | redeploy `beelink-ansible/files/aimode.sh`; warm path must hit ollama from a container that *has* curl |
| Want the loop on the Q8 | `oc` follows `hot-coder` → run `aimode work` (sole-tenant Q8 @ 256k — `-c 262144`, the model's native max; raised from 32k on 2026-06-24). 30B@64k is niche (slow prefill, see research §12) — prefer Q8 + decompose | `aimode work` then `oc`; `aimode family` to restore |

## Remote harness (Beelink) — persistent, sandboxed, tmux-attach sessions

Two containers on the Beelink give the laptop's `oc`/`ralph-qwen.sh` setup a
persistent, remotely-reachable home — no laptop needs to stay open, and you
can either let a loop run unattended or pop in and drive it live, same session
either way. Deployed via `beelink-ansible/playbooks/50-ai-stack.yml`; source
in `beelink-ansible/files/coding-harness-{qwen,claude}/` (separate repo).

| Container | What it is |
|---|---|
| `coding-harness-qwen` | opencode + qwen, ralph-loop capable — the remote equivalent of `oc run` / `scripts/ralph-qwen.sh`. Single-repo (pi-cluster). |
| `coding-harness-claude` | Real Claude Code CLI. Also carries opencode/`oc`/`ralph-qwen.sh` (delegates to qwen like a laptop session), **plus `ctx`** (local agent-history search) and this laptop's synced Claude memory. **General workstation, not repo-locked** — clone anything under `/Users/mtgibbs/dev/`. |

**General workstation, not pi-cluster-only:** `coding-harness-claude` mounts
`/Users/mtgibbs/dev` (not just a scratch dir) specifically so it matches the
laptop's real repo paths — `git clone <url> /Users/mtgibbs/dev/<name>` works
for any repo the PAT covers, and Claude Code's own project-memory-directory
naming (a sanitized copy of the absolute cwd path — confirmed via the
worktree-path example `-Users-mtgibbs-dev-mtgibbs-xyz--claude-worktrees-...`)
lines up automatically, so a synced copy of that repo's laptop memory (if any)
is found without extra config. **The GitHub PAT should be scoped to "All
repositories,"** not just pi-cluster — this is meant to be usable for anything,
the narrow part is the *permission* set (Contents+PR RW, no admin), not the
repo list.

**`ctx` (local agent-history search):** stdio-only (no network transport), so
both the binary (baked into the image, linux_x64, pinned) and its indexed
SQLite data (`~/.ctx/work.sqlite`) need to physically be in the container.
The data is a laptop-local point-in-time snapshot shipped via `harness
sync-ctx` — re-run it to refresh; there's no live sync. Once synced, `ctx
search`/`ctx mcp serve` work exactly like on the laptop.

**Claude's own memory:** `harness sync-memory` ships this laptop's
`~/.claude/projects/*/memory/` content (curated summaries only — deliberately
NOT the raw `.jsonl` session transcripts, since `ctx` already covers full
history search and there's no need to double-ship the verbose form) to the
matching path in the container. Works for any project the laptop has memory
for, not just pi-cluster, because of the path-matching design above.

**Access:** `scripts/harness attach {qwen\|claude}` (or `harness run qwen <spec-dir>`
to fire a loop and check on it later) — wraps `ssh beelink-ai` + `docker exec -it
<container> tmux attach -t main`. Zero new exposed ports: reachability is entirely
inherited from the existing Tailscale SSH access to the box (see tailscale-ops
SKILL.md), gated by the same tailnet ACLs as everything else on the Beelink.

**Sandboxing (why this is low blast radius):**
- No Docker socket, no kubeconfig, no 1Password service token, no NAS mount.
- Root filesystem `read_only: true`; the only writable path is the bind-mounted
  `/home/agent` workspace (`/srv/coding-harness-{qwen,claude}-data` on the host) +
  a `/tmp` tmpfs. Everything else — including `entrypoint.sh`/`run-task.sh`
  themselves — lives outside `$HOME` specifically so the empty bind mount can
  never shadow them on first boot.
- `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, non-root (uid 1000),
  `mem_limit`/`cpus` caps.
- Model access: `http://litellm:4000`, model alias `hot-coder` — same
  family-vs-work-mode-following alias every other Beelink consumer uses (see
  `aimode.sh` in beelink-ansible), reused via the SAME LiteLLM key `oc` already
  uses on the laptop (`op://pi-cluster/opencode-coder/password`) — one role, one
  credential, whether it's driven from the laptop or this container.
- git identity: both containers push using a **dedicated fine-grained GitHub PAT**
  (`op://pi-cluster/coding-harness-github-pat/token`, **repository access: All
  repositories** — this is a general workstation, not one-repo-locked — but
  **permissions stay narrow**: Contents+PR read/write only, no admin) — **not**
  your personal `gh` session.

**Required human setup (not yet done as of this writing):**
1. Mint a fine-grained PAT on GitHub (https://github.com/settings/tokens?type=beta):
   **Resource owner:** your account. **Repository access: All repositories**
   (broad coverage, since this is a general workstation — the safety boundary
   is the permission list below, not the repo list). **Permissions:**
   **Contents: Read and write**, **Pull requests: Read and write**,
   **Metadata: Read-only** (auto-required) — leave every other permission at
   "No access." Store it in 1Password as `coding-harness-github-pat`
   (field `token`), vault `pi-cluster`.
2. Deploy: `ansible-playbook playbooks/50-ai-stack.yml --extra-vars "harness_github_pat=$(op read 'op://pi-cluster/coding-harness-github-pat/token') harness_litellm_key=$(op read 'op://pi-cluster/opencode-coder/password') ..."`
   (plus all the *existing* ai-stack secrets already required — this doesn't
   replace that invocation, it adds two more `--extra-vars`).
3. First attach to `coding-harness-claude` needs a one-time interactive Claude
   login (`claude` prompts for OAuth device-code, or set `ANTHROPIC_API_KEY`
   first if you'd rather bill via API than subscription — **your call, not
   decided yet**) — session state persists in the bind-mounted volume after that.
4. MCP tool access for `coding-harness-claude` (reaching `mcp-homelab` etc. the
   way this session does) is **not wired up** — deliberately left as an open
   scoping decision (full parity with this session's tools vs. a more
   restricted read-mostly set to start) rather than assumed.
5. `harness sync-ctx` and `harness sync-memory` (from the laptop, after deploy)
   ship the local `ctx` index snapshot and this laptop's Claude memory into
   `coding-harness-claude`. Not automatic/scheduled — re-run either after the
   laptop's data has moved on meaningfully.

**Known gap, not yet built:** egress isn't restricted to just `ai.lab.mtgibbs.dev`
+ `github.com` — the containers can reach the open internet like any other
Docker container on this host. Would need an egress proxy/firewall rule to
tighten further; noted as a possible future hardening step, not done because
it's meaningfully more complexity than the current risk (a PR-gated coding
loop, not an untrusted-code sandbox) warrants today.

## Pointers

- Research log (findings, gaps, open decisions): `docs/research/local-coding-agent-sdd.md`
- SDD method: `specs/README.md`, `specs/TEMPLATE.md`, `specs/constitution.md`, `specs/design-principles.md`
- Launcher + loop + cred details: `scripts/README.md`, `scripts/oc`, `scripts/ralph-qwen.sh`
- First worked example: `specs/homepage-refresh/` (spec.md §11 tuning log + verify.sh)
