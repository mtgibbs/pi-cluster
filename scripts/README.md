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

- **Generator:** `scripts/gen-codesheet.mjs`, which now lives in **`mtgibbs/harness`**.
  Resolution order: `$OC_SHEET_GEN` env var, then `<target repo>/scripts/gen-codesheet.mjs`,
  then `$HARNESS_DIR`, then the canonical `harness` checkout (`~/dev/harness`). If none is
  found, `oc run` works unchanged (silent passthrough) — which is exactly why the harness
  fallbacks had to be added the moment the generator moved: a dead path here is invisible,
  not loud.
- **Opt-out:** `OC_SHEET=off oc run "..."`. The build loop generates the sheet once per loop
  and sets `OC_SHEET=off` on its own `oc` calls so it is never injected twice; its own
  opt-out is `RALPH_SHEET=off` (a harness knob — see `harness:scripts/ralph-build.sh`).
- **Interactive `oc` (TUI) sessions are not injected.**

Measured basis: 20-56% less context at equal-or-better accuracy across 783 trials —
`docs/research/codemap-serena-token-efficiency.md`.

## `harness` — remote coding-agent containers (Beelink)

Four persistent, sandboxed containers on the Beelink give you the laptop's `oc`/
`ralph-build.sh` setup as a remote session reachable from anywhere over Tailscale —
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
harness run qwen "specs/foo"     # fire-and-forget build-loop run; attach anytime to watch
harness run codex "specs/foo"    # same loop, Codex binding — a separate billing lane
harness status                   # are the containers up?
harness sync-ctx [claude|codex]  # ship a snapshot of the laptop's ctx index (default: claude)
harness push-memory              # laptop main -> GitHub -> container fetch (no auto-merge)
harness pull-memory              # container branch -> GitHub -> laptop fetch + diff
```

Requires: `ssh beelink-ai` already configured (see the local-creds model above).

Deployed via `beelink-ansible/playbooks/50-ai-stack.yml` (source: `beelink-ansible/files/coding-harness-{qwen,claude,codex}/`).

## The loop itself lives in `mtgibbs/harness`

Everything that *runs* a spec — the build loop, the executor bindings, the judge and its
bindings, the sourced helpers, the telemetry, the codesheet generator, `agent-bus`, and the
SDD methodology (`TEMPLATE.md` / `constitution.md` / `design-principles.md` / `amendments.md`)
— moved to **[`mtgibbs/harness`](https://github.com/mtgibbs/harness)** on 2026-08-26, per the
trigger `docs/adr/008` set: *extract when a second repo wants the framework*. `notes-from-hearing`
became that repo.

What this repo keeps is the **instance**: `harness` (which names *this* Beelink and *these*
containers), `oc`, the deploy scripts, the generated-doc generators, `reviewhub`, and its own
`specs/`. Read the seam as: **a project brings `specs/<feature>/{spec.md,tasks.txt,verify.sh}`
and nothing else; the harness owns the rest.**

| you want | it is now at |
|---|---|
| the build loop (was `ralph-qwen.sh`) | `harness:scripts/ralph-build.sh` — renamed, because the executor has been a binding since #199 |
| executor bindings | `harness:scripts/exec-{qwen,codex}.sh` |
| strategies + runner | `harness:scripts/loops/`, `harness:scripts/run-loop.sh` |
| the judge loop + bindings | `harness:scripts/ralph-judge{,-codex,-exec-qwen}.sh` |
| stall recovery | `harness:scripts/supervise.sh` |
| gate scoring | `harness:scripts/gate-score.sh` |
| run telemetry | `harness:scripts/loop-{index.py,doctor.sh,metrics.sh,report.sh,meta-audit.py}` |
| heartbeat / attempt evidence / retry | `harness:scripts/ralph-{status,log,retry,bus}.sh` |
| codesheet generator | `harness:scripts/gen-codesheet.mjs`, `harness:scripts/token-bench/` |
| Matrix chat CLI | `harness:scripts/agent-bus` (this repo still owns the *service* — `docs/agent-bus.md`, `clusters/pi-k3s/matrix/`) |
| how to write a spec | `harness:specs/TEMPLATE.md`, `harness:specs/README.md` |
| the principles a judge cites | `harness:specs/{constitution,design-principles,amendments}.md` |

The harness is **cloned, not baked into the container images** — `run-task.sh` does a
`fetch origin` + `reset --hard origin/main` on every dispatch, so a harness fix ships on merge
with no image rebuild. The containers resolve it as `$HARNESS_DIR`.

## Running loops from a fresh worktree — the opencode.json gotcha

`opencode.json` (repo root) carries the loop permissions qwen needs — `edit: allow`,
`bash` allow with `kubectl`/`op` denied. It is **gitignored**, so a fresh worktree does
not inherit it, and headless `oc run` then falls back to the global `edit: ask`, which
**auto-rejects every write**. The failure looks like the model doing nothing: three
attempts, `STOP — needs a human`, ~700-byte session logs.

Before running any loop in a worktree of this repo:

    cp opencode.json ../pi-cluster-<task>/opencode.json

Safe: it is ignored at `.gitignore:27`, so the loop's `git add -A` cannot commit it.
(Learned 2026-08-10 — the loop-report race's first heat burned six sessions on this.)
