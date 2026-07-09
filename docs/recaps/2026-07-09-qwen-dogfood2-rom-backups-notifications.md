# Recap — qwen-harness dogfood #2, RomM backups, and harness notifications (2026-07-09)

Three threads from today's coding-harness-claude container session: the second dogfood run of the
qwen ralph loop (this time from inside the Claude container itself), closing out Task 5 of the
Game Preservation plan (RomM backup wiring), and getting turn-end notifications working through the
full `harness attach claude` chain. All three are independent but landed in the same session.

---

## 1. qwen-harness dogfood #2 — ROM library structure (Task 4) — MERGED

This was the first ralph-qwen loop run from *inside* `coding-harness-claude` rather than the qwen
container — there's no SSH from the Claude container to the qwen one, so the loop had to be driven
locally. Two mechanical gaps surfaced immediately and were worked around in-session:

- `run-task.sh` hardcoded `origin/main` as its base branch, so the worktree for
  `spec/rom-library-structure` had to be created manually.
- Container `opencode` reads `HARNESS_LITELLM_KEY` directly rather than going through the `oc`
  wrapper the qwen container ships with — an `oc` shim went into `~/.local/bin` to bridge that.

**The loop stopped on T1 after 3 attempts**, and the failure was the exact one the spec-authoring
session had predicted: qwen violated T1's "touch ONLY this one file" scope and created
`scripts/rom-organize.sh` mid-task. Ralph's retry reset at the time was `git checkout -- .`, which
can't remove untracked files — the out-of-scope file persisted across retries and ended up arming
verify.sh's PEND-gated T2 checks prematurely.

Claude (orchestrator) took over per the loop's intended design at that point:

- Two targeted `oc run` retries fixed the sanitize logic and most of the PSX packaging algorithm.
- Five remaining check failures were hand-fixed directly:
  - Bash word-splitting on filenames containing spaces in cue/bin parsing — `parse_cue_bins`
    switched from space-separated to newline-separated + `while read`.
  - PSX loose-file move ordering — a `.bin` must never be moved without its paired `.cue` already
    in place.
  - Folder-name derivation — strip the `.cue` extension *before* applying the end-anchored
    disc-tag regex, or the regex misses.

**Result: verify.sh 54/54 PASS.** PR #44 squash-merged by Matt (`7312c37`). qwen's solo score before
Claude's intervention was ~49/54 — consistent with the standing finding on this project: qwen is
strong at faithful codegen, weak at scope discipline and bash string-safety under edge-case inputs.

Same day, Matt (laptop side) shipped all three fixes this run had queued:

1. Ralph's retry reset changed from `git checkout -- .` to `git clean -fd` + `checkout`, so
   untracked scope violations actually get removed between attempts.
2. `run-task.sh`'s base-branch argument wired through end-to-end, including the laptop
   `harness-run` wrapper — which turned out to be passing no base branch at all, a separate bug
   with the same root cause.
3. The ansible copy task that provisions the containers never actually included `oc` — a
   from-scratch rebuild of either harness would have silently failed to have it. Fixed in
   `beelink-ansible`.

Both harness containers were rebuilt and recreated to pick up the fixes. Claude's post-rebuild
cleanup: removed the now-shadowing `~/.local/bin/oc` shim left over from the manual workaround,
since the rebuilt image provisions it correctly.

---

## 2. Game-preservation Task 5 — RomM backup scope — MERGED + VERIFIED

Added a new node-independent `mariadb-backup` CronJob (Sundays 3:45 AM) for RomM's MariaDB, mirroring
the existing Immich Postgres backup pattern with three deliberate deviations:

- **Single-target, no soft-skip.** An unreachable DB fails the Job outright rather than silently
  skipping, since RomM (unlike Immich) has exactly one database to back up.
- **`set -o pipefail`.** A failed `mariadb-dump` can't hide behind gzip's exit 0 in the pipe.
- **`MYSQL_PWD` env var** instead of `-p` on the command line, keeping the password out of process
  listings.

The job runs `mariadb-dump --single-transaction` as the `romm` app user against the Service, gzips
the output, and rsyncs it to `{date}/romm/` on the QNAP.

Other pieces in the same PR:

- `romm_romm-config` added to media-backup's PVC list. Both RomM pods are pinned to
  `pi5-worker-1`. `romm-redis-data` was deliberately skipped — regenerable cache, not backup-worthy.
  ROMs/saves/assets are already NAS-side on NFS and don't need a separate backup path.
- A new `romm-db-password` ExternalSecret in `backup-jobs`, reusing the existing 1Password field
  (RomM already had a DB password item) — a second consumer, zero new secrets minted.
- Docs: `backup-ops` SKILL.md gained job #6 (RomM/MariaDB) plus a restore procedure; the
  game-preservation plan doc's Task 5 row updated.

PR #45 merged (`637b3da`) — merged and reconciled by the other/laptop agent working the same cluster.
A manual `trigger_backup` run afterward **succeeded**: `romm-mariadb-2026-07-09.sql.gz` (6.6K)
confirmed present on the NAS via the job's own post-rsync `ls`.

**Open (human decision, flagged in the plan doc):** there's no QNAP-side snapshot or second copy for
`/share/cluster/games` — the backups tree and the ROM library itself currently share one physical box.

**Process lesson.** Matt flagged mid-task that a handed-off plan step (`reconcile_flux`) fired
redundantly — the merge had already been reconciled by the other agent before this step ran. With
multiple agents operating on the same cluster, a cheap status read before each mutating step of a
handed-off plan is now the expectation, not an optional check.

---

## 3. Notifications through the harness attach chain — LIVE (one PR pending)

Goal: turn-end notifications reach Matt in iTerm2 on the Mac while attached via
`harness attach claude` — a chain of container tmux → `docker exec` → ssh → iTerm2.

Verified live during the session:

- Plain BEL forwards through tmux by default (`bell-action any` is already the behavior needed).
- OSC 9 labeled macOS notifications work with tmux's `allow-passthrough` turned on — confirmed by
  writing a wrapped escape sequence directly to the pane's tty.

Shipped container-side:

- `preferredNotifChannel: terminal_bell` set in persistent `settings.json` for turn-end bells.
  Note: `claude config set` as a subcommand no longer exists — running it spawns a headless prompt
  instead of erroring, which is a trap. Editing `settings.json` directly is the way.
- `~/.tmux.conf` with `allow-passthrough` on, on the persistent volume — an interim location (see
  below).
- `~/.claude/hooks/tmux-notify.sh` wired to the `Notification` event: extracts the message via
  `node` (no `jq` in the lean container image), sanitizes and caps it, and emits a wrapped OSC 9
  sequence to the pane's tty. Pipe-tested live and confirmed working.
- Caveat: the hook was added mid-session, so it may need a session restart or `/hooks` to actually
  load for the current session.

**Open — `beelink-ansible` PR #1:** bake `/etc/tmux.conf` with `allow-passthrough` into *both* harness
images. It has to live in `/etc`, not `$HOME`, because `$HOME` is shadowed by the first-boot bind
mount and the read-only rootfs blocks runtime writes to `/etc`. Deploying this means rebuilding and
recreating both containers.

SKILL.md (`coding-agent-ops`) updated in commit `cc658ce` with the full notification-chain runbook.

---

## 4. Process/boundary decisions worth recording

- **Config-from-outside boundary refined** after Matt pushed back ("why can't you work this on your
  own?"). The rule bans invisible in-place runtime mutation of harness config, not participation.
  Container-Claude's actual scope: source PRs to `beelink-ansible` (the PAT covers all repos; PR is
  the reviewed channel) and edits to `$HOME` dotfiles/settings directly. What's genuinely laptop-side:
  deploys (the container has no docker socket — it can't recreate itself) and runtime writes outside
  `$HOME`.
- **Harness PAT gap discovered:** no Issues permission on the token (Contents + PR only), so the tmux
  bake couldn't be filed as a `beelink-ansible` issue — it went in as a PR description note instead.
  Flagged for Matt: add Issues RW if GitHub issues should become the harness→laptop queue channel.
- Matt explicitly endorsed the report-don't-self-patch behavior demonstrated during the dogfood
  ("keep doing that"). Both harness containers (`coding-harness-qwen` and `coding-harness-claude`)
  have now been dogfooded end-to-end.

---

## Commits / PRs

| Repo | Ref | Subject |
| :--- | :--- | :--- |
| pi-cluster | PR #44 (`7312c37`) | ROM library organizer structure (Task 4) |
| pi-cluster | PR #45 (`637b3da`) | RomM MariaDB backup CronJob (Task 5) |
| pi-cluster | `cc658ce` | docs(coding-agent-ops): document the notification-chain runbook |
| beelink-ansible | PR #1 (open) | bake `/etc/tmux.conf` allow-passthrough into both harness images |

## Open items

- [ ] `beelink-ansible` PR #1 — merge + rebuild/recreate both harness containers.
- [ ] Confirm the `tmux-notify.sh` hook loads without a session restart, or document that one is
  required.
- [ ] Add Issues RW to the harness PAT if GitHub issues are meant to be the harness→laptop queue.
- [ ] QNAP-side snapshot/second copy for `/share/cluster/games` (human decision, backups + library
  currently share one box).
- [ ] Game Preservation Task 6 — first real dump → RomM scan → browser-play smoke test, still
  blocked on dumper hardware arrival.
