# scripts/

Local-stack helper scripts. General-purpose (usable across projects) but documented
and bootstrapped from this repo since they depend on the home lab stack.

## Local-creds model (why no biometric per run)

The laptop↔Beelink-qwen link is a **device-to-tool** connection on a trusted machine — it
doesn't act on behalf of the cluster, it just *uses the model like a tool that belongs to the
box*. So its working creds live **locally** (no Touch-ID-per-use lockout), while the
**canonical copies stay in 1Password** for easy re-bootstrap. Crown-jewel / cluster-acting
creds stay behind the biometric, untouched. Two channels:

- **`oc run` → qwen** (HTTPS/LiteLLM): the key is cached in the **macOS Keychain** (service
  `opencode-qwen`); `oc` reads Keychain-first, 1Password as fallback. Re-seed with:
  `security add-generic-password -U -s opencode-qwen -a oc -T /usr/bin/security -w "$(op read 'op://pi-cluster/opencode-coder/password')"`
- **`ssh beelink-ai`** (host access): a private key on disk at `~/.ssh/beelink-ai` (0600),
  with `~/.ssh/config` set to `IdentityAgent none` for that host so it bypasses the 1Password
  SSH agent. Canonical copy: 1Password item `beelink-ai SSH`. Re-extract with:
  `op read 'op://pi-cluster/beelink-ai SSH/private key?ssh-format=openssh' > ~/.ssh/beelink-ai && chmod 600 ~/.ssh/beelink-ai`

## `oc` — opencode launcher

Wraps `opencode` so the LiteLLM/qwen key is loaded into opencode's process env only — never
exported to your shell. Reads the key from the Keychain (no biometric) and falls back to
1Password. Adds a watchdog timeout to `oc run`.

**Bootstrap onto any machine:**

```bash
cp scripts/oc ~/.local/bin/oc && chmod +x ~/.local/bin/oc   # ~/.local/bin must be on PATH
```

**Use:**

```bash
oc                 # interactive TUI (qwen3-coder via ai.lab)
oc run "do thing"  # headless one-shot
```

**Other machines / other key:** override the vault reference —

```bash
OC_KEY_REF="op://work-vault/opencode/key" oc
```

### Codesheet injection

Every headless `oc run` prepends a navigation codesheet to the prompt: a repo map plus the
reference sheet the repo's shape calls for. Layer selection is automatic, from the repo's
contents: **symbol graph** for code repos, **edge index** for manifest repos, both
(domain-disjoint) for mixed repos.

- **Generator:** `scripts/gen-codesheet.mjs`. Resolution order: `$OC_SHEET_GEN` env var,
  then `<target repo>/scripts/gen-codesheet.mjs`, then the canonical pi-cluster checkout.
  If none is found, `oc run` works unchanged (silent passthrough).
- **Opt-out:** `OC_SHEET=off oc run "..."`.
- **Interactive `oc` (TUI) sessions are not injected.**

Measured basis: 20-56% less context at equal-or-better accuracy across 783 trials —
`docs/research/codemap-serena-token-efficiency.md`.

## `harness` — remote coding-agent containers (Beelink)

Four persistent, sandboxed containers on the Beelink give you the laptop's `oc`/
`ralph-qwen.sh` setup as a remote session reachable from anywhere over Tailscale —
no laptop needs to stay open, and you can pop in and drive it live or fire off a
loop and check back later. Full details, security model, and the human setup
steps: `.claude/skills/coding-agent-ops/SKILL.md` → "Remote harness (Beelink)".

**Bootstrap onto any machine** (same one-time step as `oc` — it's not on `PATH` by default):

```bash
cp scripts/harness ~/.local/bin/harness && chmod +x ~/.local/bin/harness   # ~/.local/bin must be on PATH
```

**Use:**

```bash
harness attach qwen              # pop in and drive opencode/qwen live
harness attach claude            # pop in to a real Claude Code session
harness attach codex             # pop in to an OpenAI Codex CLI session
harness run qwen "specs/foo"     # fire-and-forget ralph-qwen run; attach anytime to watch
harness run codex "specs/foo"    # same, but ralph-codex — a separate billing lane
harness status                   # are the containers up?
harness sync-ctx [claude|codex]  # ship a snapshot of the laptop's ctx index (default: claude)
harness push-memory              # laptop main -> GitHub -> container fetch (no auto-merge)
harness pull-memory              # container branch -> GitHub -> laptop fetch + diff
```

Requires: `ssh beelink-ai` already configured (see the local-creds model above).

Deployed via `beelink-ansible/playbooks/50-ai-stack.yml` (source: `beelink-ansible/files/coding-harness-{qwen,claude,codex}/`).

## `ralph-qwen.sh` — bounded SDD loop

Runs the bounded SDD loop (one task per fresh session, deterministic verify.sh gate, retry
with failure feedback). Generates the codesheet **ONCE per loop** so the identical bytes
ride the prefix cache across every task and retry, and sets `OC_SHEET=off` on its own `oc`
calls so the sheet is never injected twice.

- **Use:** `scripts/ralph-qwen.sh specs/<feature>` from a git worktree on a throwaway branch.
- **Opt-out:** `RALPH_SHEET=off`.

## `ralph-codex.sh` — the same loop, driven by the OpenAI Codex CLI

Structurally identical to `ralph-qwen.sh` — same spec-dir contract, same fresh session per
attempt, same deterministic `verify.sh` gate, same stop-for-a-human. Only the executor swaps
(`codex exec` instead of `oc run`), and codex reads `AGENTS.md` natively so there's no second
brief to keep in sync.

- **Use:** `scripts/ralph-codex.sh specs/<feature>` from a git worktree on a throwaway branch.
- **Codesheet defaults OFF here** (`RALPH_SHEET=on` to enable) — the 20-56% win was measured
  on a 30B with a small window and is unmeasured for codex.
- **Sandbox:** defaults to `danger-full-access` because the *container* is the boundary.
  On a laptop there is no outer sandbox — use `CODEX_SANDBOX=workspace-write`.
- **Watchdog:** `CODEX_RUN_TIMEOUT` (default 900s), same background-kill pattern as `oc`.

## `supervise.sh` — restart a loop that never started

    scripts/supervise.sh <strategy> <spec-dir>          # from the target worktree root
    OC_RUN_TIMEOUT=2400 RALPH_RETRIES=3 scripts/supervise.sh build-then-judge specs/v1

Wraps `run-loop.sh` and recovers the one fault the `oc` watchdog cannot: opencode logs a
`stream` line, never receives a first token, and never returns. Four for four in one session —
one run sat 53 minutes against a 2400 s budget — so detection has to live outside the timeout
that failed to fire.

- **Discriminator is size, not staleness.** ≤40 B *and* stale = stillborn; an 82 KB log idle
  25 minutes is a healthy run buffering. Kills the process group, then sweeps by name.
- **Snapshots before killing.** ralph writes its `.diff` only when *verify* fails, so a killed
  attempt leaves no evidence unless someone takes it first: log dir, worktree diff, status and
  untracked files land in `~/.harness/evidence/<repo>/killed-attempts/`.
- **Stamps the epitaph.** Calls `hb_mark <status-file> killed`, so the orphaned heartbeat says
  `killed` instead of freezing at `running` forever.
- **Not a retry loop.** It never re-runs a task that failed *verification* — that is ralph's
  job and it burns attempts deliberately. Any nonzero exit that is not a hang stops the run.

## `agent-bus` — Matrix chat CLI

Post/read/wait on the homelab Matrix chat bus over the plain client-server API (pure
`curl` + `jq`). Shared by laptop-Claude, the harness agents, qwen, and humans (Element Web).
Full design: `docs/agent-bus.md`.

**Creds** (same tiering as `oc`): picks the identity `AGENT_BUS_IDENTITY` (default
`laptop-claude`); token resolves `MATRIX_TOKEN` env → macOS Keychain (`agent-bus-<id>`) →
`op://pi-cluster/agent-bus-<id>/token`. Homeserver defaults to `https://matrix.lab.mtgibbs.dev`.

**Use:**

```
agent-bus whoami                                  # confirm identity + token
agent-bus rooms                                   # joined rooms
agent-bus post agents "hello"                      # post to #agents
agent-bus post tasks "task: foo done" --thread '$evt'   # reply in-thread
agent-bus read agents --limit 20                   # recent messages
agent-bus wait --room tasks --mention --timeout 300     # block until mentioned (/sync)
agent-bus upload ./plan.md agents                  # upload a file + post the link
```

**Dependency:** `jq` (the only thing beyond `curl`) — add it to any harness container that
runs the CLI. Requires the account bootstrap (see `docs/agent-bus.md`) to have populated the
`agent-bus-<name>` 1Password items.

## `ralph-judge.sh` — the post-convergence judge loop (+ its bindings)

Runs AFTER a spec's gate is green: an independent judge proposes findings against the spec's
*intent*, an executor applies one mutation per round, and the deterministic gate arbitrates
every change (spec: `specs/judge-loop/`). Command bindings are REQUIRED and explicit — they
live at this operator layer by design (first-run triage #3), so the loop never bakes in a
host's tool paths:

- **`ralph-judge-codex.sh`** — `JUDGE_CMD`: Codex (read-only) emits findings JSONL; also
  serves `--check-resolution`. A different model family from the executor, on a separate
  billing lane.
- **`ralph-judge-exec-qwen.sh`** — `EXECUTOR_CMD`: qwen via `oc run` applies exactly one
  finding; never commits, never leaves the finding's file.

**Use** (from a clean worktree on a throwaway branch — copy the gitignored `opencode.json`
in first, or headless `oc` auto-rejects every tool call):

```bash
JUDGE_CMD=scripts/ralph-judge-codex.sh EXECUTOR_CMD=scripts/ralph-judge-exec-qwen.sh \
  scripts/ralph-judge.sh specs/<feature>
```

State + report land under the worktree's git-dir (`ralph-judge/ledger.jsonl`, `report.json`);
exit 0 = completed (see report), 1 = aborted fail-closed, 2 = gate-unstable/needs a human.

The **ledger is cumulative** across invocations; the report describes all of it. Read the two
counts together: `rounds_run` is this invocation's rounds, `ledger_sessions` is how many
invocations the `accepted`/`rejected`/`gate_gaps` lists span. Every record carries `session`
and a `head` SHA, so a finding can be joined to the build it was found against — and a dry
re-run that recorded nothing will correctly show its own `session` absent from the ledger.

## Running loops from a fresh worktree — the opencode.json gotcha

`opencode.json` (repo root) carries the loop permissions qwen needs — `edit: allow`,
`bash` allow with `kubectl`/`op` denied. It is **gitignored**, so a fresh worktree does
not inherit it, and headless `oc run` then falls back to the global `edit: ask`, which
**auto-rejects every write**. The failure looks like the model doing nothing: three
attempts, `STOP — needs a human`, ~700-byte session logs.

Before running any loop in a worktree:

    cp opencode.json ../pi-cluster-<task>/opencode.json

Safe: it is ignored at `.gitignore:27`, so the loop's `git add -A` cannot commit it.
(Learned 2026-08-10 — the loop-report race's first heat burned six sessions on this.)

## loop-report.sh — one-screen summary of a strategy run

    scripts/gate-score.sh specs/<f>/verify.sh > /tmp/gate.log
    scripts/loop-report.sh --spec specs/<f> --base origin/main --gate-log /tmp/gate.log

Prints branch, commit count, the last gate score line, and the judge ledger summary
(`judge: none` if no judge ran). Built by the race it now reports on — see
specs/loop-report/ and the race/* branches for the full evidence trail.
