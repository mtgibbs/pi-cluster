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
opencode export <ses_id> # full session as clean markdown — the way to hand a qwen
                         # transcript to Claude (TUI copy-paste mangles; ctx import is lite)
```

### Codesheet injection (default ON for `oc run` and ralph)

Every headless `oc run` prepends a **navigation codesheet** to the prompt:
repo map + the reference sheet the repo's shape calls for (symbol graph for
code, edge index for manifests, both — domain-disjoint — for mixed). Measured
on 783 trials: **20–56% less context at equal-or-better accuracy**, ~free
after first use via prefix caching. Full evidence:
`docs/research/codemap-serena-token-efficiency.md`.

- Generator: `scripts/gen-codesheet.mjs` (wraps `scripts/token-bench/gen-*.mjs`;
  picks layers from the data — pi-cluster→G, mtgibbs.xyz→S, pi-cluster-mcp→GS).
- Resolution order: `$OC_SHEET_GEN` → `<target-repo>/scripts/gen-codesheet.mjs`
  → the canonical pi-cluster checkout (`$HOME/dev/…` on the laptop, literal
  `/Users/mtgibbs/dev/…` in the harness containers). No generator → silent
  passthrough, `oc run` works anywhere.
- `OC_SHEET=off oc run …` disables. `ralph-qwen.sh` generates the sheet ONCE
  per loop (byte-stable → cached across every task/retry) and sets
  `OC_SHEET=off` on its own oc calls so it never double-injects;
  `RALPH_SHEET=off` disables the loop's copy.
- Interactive `oc` (TUI) is NOT injected — sheets are a headless-prompt
  mechanism; the TUI user navigates personally.
- Gotcha class to watch: never add a second sheet describing the same
  relations in a different vocabulary — that exact overlap made qwen fabricate
  index lines (bench ms3 0/3). One vocabulary per relation.

## Ops mode — `oc ops` (local-model homelab diagnostician)

Self-sustainability requires the local model to diagnose the lab without Claude — the
role the §16 baseline (research log) showed unscaffolded qwen flailing at. The fix is a
dedicated opencode **agent**, not more coding-brief prose:

- **Agent definition (repo-tracked):** `.opencode/agents/ops.md` — its own system prompt
  (world model + media pipeline + diagnostic discipline), a **curated 23-tool subset** of
  mcp-homelab (reads + 4 bounded mutations, mutations set to `ask`), `edit: deny`,
  `kubectl`/`op` denied, other bash `ask`. Rides into any checkout automatically.
- **Launcher:** `oc ops` (in `scripts/oc`) — loads `MCP_HOMELAB_KEY` (Keychain service
  `mcp-homelab` first, else `op://pi-cluster/mcp-homelab/api-key` with Touch ID) and
  execs `opencode --agent ops`. Plain `oc` never prompts for the ops key. **Tier
  decision:** the MCP key is cluster-acting (restarts, exec-in-jellyfin) — leaving it
  1Password-only (one Touch ID per ops session) respects the crown-jewel rule; seed the
  Keychain only if you decide it's medium-tier.
- **Machine-local wiring (NOT in git — merge into the repo-root `opencode.json` on each
  machine; while there, DELETE any `mcpServers` key, that's Claude's schema and throws
  `ConfigInvalidError`):**

  ```jsonc
  {
    "$schema": "https://opencode.ai/config.json",
    "mcp": {
      "homelab": {
        "type": "remote",
        "url": "https://mcp.lab.mtgibbs.dev/mcp",
        "enabled": true,
        "headers": { "X-API-Key": "{env:MCP_HOMELAB_KEY}" }
      }
    },
    "tools": { "homelab_*": false },
    "permission": { "bash": { "kubectl *": "deny", "op *": "deny", "*": "allow" } }
  }
  ```

  `"homelab_*": false` hides the ~50 tool schemas from the build/coding agents (context
  budget, §12 of the research log); `ops.md` re-enables its subset. The `permission`
  block is the binding enforcement for the §16 secret-extraction failure — AGENTS.md
  rules alone don't bind a 30B.
- **Smoke test:** `oc ops` → the TUI should show the ops agent with only homelab tools;
  ask "what's the cluster health?" and confirm it calls `homelab_get_cluster_health`
  instead of shelling out. Known wrinkle: in plain `oc` sessions with no
  `MCP_HOMELAB_KEY`, opencode still connects to the MCP server at startup and may log an
  auth warning — harmless (tools are globally disabled); seed the Keychain to silence it.
- **Eval:** rerun the §16 baseline prompt verbatim ("check on a download of 'seeking
  persophone' and then make sure it's imported into our jellyfin") in `oc ops`; correct
  behavior is 2-3 queue/history calls → "never grabbed; want me to add it?". Log the
  after-result in research log §16. Ops quality is meaningfully better on the Q8
  (`aimode work`) — prefer it for nontrivial debugging.
- **Container follow-up (not done):** `coding-harness-qwen` gets `ops.md` via the repo
  but needs `MCP_HOMELAB_KEY` in its env (beelink-ansible, laptop-side change) before
  `oc ops` works there.

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
| Headless `opencode run` targeting **another repo** silently operates on the WRONG project (reads the launcher's repo; target-repo paths auto-reject as `external_directory`) | **opencode resolves its project from `$PWD`, not process cwd** — a program spawning it with `cwd:` set but env inherited pins every session to the launcher's directory (found 2026-07-10; invalidated 181 token-bench site trials across two rounds). A shell `cd` works only because the shell rewrites `$PWD` | set `PWD=<target>` in the spawned env (see run-bench.mjs runOnce) — and AUDIT afterward: join your run's `session_id`s to `session.directory` in `~/.local/share/opencode/opencode.db`. Secondary gotcha: a repo opencode has never met interactively has `project.sandboxes: []` → file ops need one interactive approval or a seeded trust row (`update project set sandboxes='["<dir>"]' where worktree='<dir>'`) |
| `oc ops` gave (or nearly gave) a wrong "never grabbed" verdict for a title that *was* imported | eval'd 2026-07-11 on a real re-run of the §16 baseline prompt: it checked only Radarr (title was actually a Sonarr series) and never circled back, then reached for `homelab_fix_jellyfin_metadata` as an improvised "does this exist" search — an ask-gated mutation, auto-rejected headless, stalling the session with no verdict | `ops.md` now requires checking BOTH Radarr and Sonarr before declaring "never grabbed," and states plainly that there's no per-title Jellyfin lookup tool — don't reach for a mutation as a search substitute, say the limitation and stop |

## Remote harness (Beelink) — persistent, sandboxed, tmux-attach sessions

Three containers on the Beelink give the laptop's `oc`/`ralph-qwen.sh` setup a
persistent, remotely-reachable home — no laptop needs to stay open, and you
can either let a loop run unattended or pop in and drive it live, same session
either way. Deployed via `beelink-ansible/playbooks/50-ai-stack.yml`; source
in `beelink-ansible/files/coding-harness-{qwen,claude}/` (separate repo) —
`coding-harness-claude-2` reuses the `coding-harness-claude` image/build
context, just a second compose service with its own volume.

| Container | What it is |
|---|---|
| `coding-harness-qwen` | opencode + qwen, ralph-loop capable — the remote equivalent of `oc run` / `scripts/ralph-qwen.sh`. Single-repo (pi-cluster). |
| `coding-harness-claude` | Real Claude Code CLI. Also carries opencode/`oc`/`ralph-qwen.sh` (delegates to qwen like a laptop session), **plus `ctx`** (local agent-history search) and this laptop's synced Claude memory. **General workstation, not repo-locked** — clone anything under `/Users/mtgibbs/dev/`. |
| `coding-harness-claude-2` | **Second, independent Claude Code instance** — same role/image as `coding-harness-claude`, own `$HOME`/repo-mirror/tmux session, so two windows can drive parallel work without sharing state. Added 2026-07-14. **Provisioned but not activated** — see below. |

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

**Access:** `scripts/harness attach {qwen\|claude\|claude2}` (or `harness run qwen <spec-dir>`
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
3. **DONE.** First attach to `coding-harness-claude` did the one-time interactive
   Claude login (subscription OAuth device-code — not API key) — session state
   persists in the bind-mounted volume across restarts.
3a. **`coding-harness-claude-2` — provisioned but NOT activated.** Container is
    up, verified working (binaries, git identity `mtgibbs (coding-harness-claude-2)`,
    GitHub PAT auth, MCP env vars, tmux session all confirmed 2026-07-14), but two
    manual steps are still outstanding — same first-attach pattern as above, done
    per-container since `$HOME` isn't shared:
    - `scripts/harness attach claude2` → run `claude` → subscription OAuth login.
    - `gh auth login` inside, if you want `gh` usable there too (git push/pull
      already works via the shared PAT regardless).
    Known gap: `harness sync-ctx` / `push-memory` / `pull-memory` are hardcoded to
    the first `coding-harness-claude` container/volume — they don't touch
    `-2` yet. Not needed until `-2` is actually put to use.
4. MCP tool access for `coding-harness-claude` (reaching `mcp-homelab` etc. the
   way this session does) is **not wired up** — deliberately left as an open
   scoping decision (full parity with this session's tools vs. a more
   restricted read-mostly set to start) rather than assumed.
5. `harness sync-ctx` (from the laptop, after deploy) ships the local `ctx`
   index snapshot into `coding-harness-claude`. Not automatic/scheduled —
   re-run after the laptop's index has moved on meaningfully. (Memory sync no
   longer uses rsync — see "Memory protection" below.)

**Known gap, not yet built:** egress isn't restricted to just `ai.lab.mtgibbs.dev`
+ `github.com` — the containers can reach the open internet like any other
Docker container on this host. Would need an egress proxy/firewall rule to
tighten further; noted as a possible future hardening step, not done because
it's meaningfully more complexity than the current risk (a PR-gated coding
loop, not an untrusted-code sandbox) warrants today.

**Notifications through the attach chain (tmux → ssh → iTerm2)** — working as of
2026-07-09; only the image bake is pending review:
- **Turn-end/attention bells:** `preferredNotifChannel: terminal_bell` in the claude
  container's persistent settings.json. Plain BEL forwards through tmux by default.
- **Labeled macOS notifications (OSC 9):** need tmux `allow-passthrough on`. Live now
  via the claude container's `~/.tmux.conf` (persistent volume); the reproducible
  image bake (`/etc/tmux.conf` in BOTH images — NOT `$HOME`, the first-boot bind
  mount shadows it) is **beelink-ansible PR #1**, awaiting review + the usual
  rebuild/recreate deploy.
- **Hook:** `~/.claude/hooks/tmux-notify.sh` on the `Notification` event emits the
  wrapped OSC 9 (`\ePtmux;\e\e]9;<msg>\a\e\\` → pane tty, msg sanitized/capped) so
  permission prompts and attention events surface as real Notification Center
  alerts while attached. Silent no-op with no tmux pane.
- **iTerm2 side (per Mac):** Settings → Profiles → Terminal → "Send Notification
  Center alerts" + macOS notification permission; alerts are suppressed while the
  window is focused.
- Gotcha: the harness PAT lacks the Issues permission (Contents+PR only) — add
  Issues RW if GH issues should become the harness→laptop queue channel.

### Memory protection — git-tracked, hooked, GitHub-hub backed up

Both the laptop and `coding-harness-claude` run real Claude Code sessions with
the same auto-memory instructions — the container will save its own memories
as it works, so a blind rsync overwrite (the old `sync-memory`) would silently
destroy them. Fixed 2026-07-08/09 with:

- **Git-track `~/.claude/projects/`** (laptop) and `/home/agent/.claude/projects/`
  (container) independently. Whitelist `.gitignore` on both — tracks ONLY
  `*/memory/**`, never raw `.jsonl` session transcripts.
- **A `Stop` hook** (`~/.claude/hooks/memory-autocommit.sh` / the container's
  copy at the same path under its own `$HOME`) auto-commits any memory changes
  at the end of each turn — atomic (whole-turn, not per-Write/Edit, so a
  `MEMORY.md` + topic-file pair never lands as a torn half-commit), portable
  (an `mkdir`-based lock, since `flock` isn't on macOS by default), and
  self-protecting (refuses + resets if anything outside `*/memory/*` gets
  staged, rather than trusting the `.gitignore` alone).
- **GitHub as the sync hub, not a live remote or bundle transport**:
  `mtgibbs/claude-memory-vault` (private). Laptop owns `main`, the container
  owns its own `container` branch — neither ever pushes to the other's, so
  merges are always a deliberate, reviewed `git diff`-then-`merge`, never a
  blind overwrite. This also gets offsite backup for free: the existing weekly
  `git-mirror-backup` CronJob already mirrors every GitHub repo `mtgibbs` owns
  to the QNAP, no new cluster infra needed.
- `harness push-memory` (laptop `main` → GitHub → container `fetch`, no
  auto-merge) and `harness pull-memory` (container's branch → GitHub → laptop
  `fetch` + diff, you merge by hand) replace the memory half of the old
  `sync-memory`. `sync-ctx` is untouched (unrelated, still a single-file
  rsync).
- **Dogfooded, not pre-scripted**: the container set up its OWN half of this
  (git init, hook, initial commit, push to `container`) by being *prompted*
  the spec and executing it itself — proving the harness can do real
  infrastructure work on itself, not just respond to questions.

**Gotcha for next time — drive setup/config tasks like this interactively,
not via `claude -p`.** A first attempt tried dispatching the dogfood prompt
headlessly (`claude -p`); it correctly self-documented every mutating
operation being auto-denied (no TTY = no way to clear a permission prompt) and
made zero progress. Attaching to the container's live tmux session
(`harness attach claude`) and pasting the same prompt by hand worked cleanly
end to end — git init, remote+branch setup, hook install, and two verified
pipe-tests (no-op case + real-change case, including a deletion).

**A stale memory can outlive the problem it describes.** The killed headless
attempt left behind a memory file honestly reporting "fully blocked" — which
went stale the moment the interactive retry succeeded. Caught during the
`harness pull-memory` review (not blindly merged) and corrected before it
reached the laptop's canonical history. The lesson generalizes: a "reviewed
merge, not blind auto-sync" design earns its keep exactly in moments like
this — a mechanical sync would have merged the stale claim without anyone
noticing.

## Pointers

- Research log (findings, gaps, open decisions): `docs/research/local-coding-agent-sdd.md`
- SDD method: `specs/README.md`, `specs/TEMPLATE.md`, `specs/constitution.md`, `specs/design-principles.md`
- Launcher + loop + cred details: `scripts/README.md`, `scripts/oc`, `scripts/ralph-qwen.sh`
- First worked example: `specs/homepage-refresh/` (spec.md §11 tuning log + verify.sh)
