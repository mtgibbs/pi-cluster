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

Two persistent, sandboxed containers on the Beelink give you the laptop's `oc`/
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
harness run qwen "specs/foo"     # fire-and-forget ralph-qwen run; attach anytime to watch
harness status                   # is either container up?
harness sync-ctx                 # ship a snapshot of the laptop's ctx index (claude only)
harness sync-memory              # ship this laptop's Claude memory (claude only)
```

Requires: `ssh beelink-ai` already configured (see the local-creds model above).

Deployed via `beelink-ansible/playbooks/50-ai-stack.yml` (source: `beelink-ansible/files/coding-harness-{qwen,claude}/`).

## `ralph-qwen.sh` — bounded SDD loop

Runs the bounded SDD loop (one task per fresh session, deterministic verify.sh gate, retry
with failure feedback). Generates the codesheet **ONCE per loop** so the identical bytes
ride the prefix cache across every task and retry, and sets `OC_SHEET=off` on its own `oc`
calls so the sheet is never injected twice. `ralph-qwen.sh` is mentioned (its sheet is
generated once per loop).

- **Opt-out:** `RALPH_SHEET=off`.
