# Spec: the task ledger — a sidecar that remembers which tasks are already green

- **Status:** Draft v0.1
- **Owner:** Matt (design by Claude; executor TBD)
- **Constitution:** `specs/constitution.md` + `specs/amendments.md` (v1.3.0)
- **Touches:** new `scripts/ralph-ledger.sh`, `scripts/ralph-qwen.sh`, `scripts/ralph-codex.sh`,
  new `specs/tasks-ledger/{tasks.txt,verify.sh,fixtures/}`.
- **Source:** Codex spec-review finding #8 (2026-08-17, `notes-from-hearing`), field-confirmed
  by the VoiceCapture Phase 1 build loop on 2026-08-18 — 10 runs, 36 executor attempts.

---

## 1. Why · [R]

### 1.1 The loop cannot remember anything between runs

`scripts/ralph-qwen.sh:81` opens the task queue and `:177` closes it:

```bash
while IFS= read -r task || [ -n "$task" ]; do
  …
done < "$TASKS"
```

Every line, every run. **Nothing anywhere records that a task finished.** The twin
`scripts/ralph-codex.sh` is identical.

Codex's wording, reviewing `notes-from-hearing/specs/v1` on 2026-08-17:

> "no task file, checkbox, status field, or verdict-path convention records 'unfinished'."

### 1.2 What that costs, measured

On 2026-08-18 in `notes-from-hearing`, requeuing **one** task meant hand-editing `tasks.txt` to
delete four completed ones — otherwise all five would have rebuilt from scratch. That repo now
has **eight** tasks queued (`T14 T06 T07 T08 T10 T11 T12 T13`), several of them Xcode builds. The
cost of a restart is now the dominant cost of the loop, and it is paid in full every time.

Worse, the hand-edit is *lossy and unreviewed*: the operator deletes lines from the driver file
to express state, so the queue file no longer says what the spec's task breakdown says. There is
no way to tell "we chose not to build this" from "this is already built".

### 1.3 Why this is not just ergonomics

The three artefacts a completed task produces — **its verdict set, its attempt count, its commit
sha** — are exactly the missing inputs elsewhere:

- `specs/loop-doctor` classifies harness faults but has **no cross-run corpus** to classify
  against, because nothing survives a run.
- Five telemetry channels exist (`ralph-status.sh`, `ralph-log.sh`, `ralph-bus.sh`,
  `gate-score.sh`, `loop-report.sh`) and **nothing reads any of them**. They are all
  *within*-run; there is no per-item durable record to read.

A ledger is the first thing this harness has written that outlives the process that wrote it.

---

## 2. Outcomes (Definition of Done) · [R]

1. Every task that passes its gate and commits appends one line to a **sidecar ledger outside the
   repository**. `tasks.txt` is never written to.
2. With `RALPH_RESUME=1`, a run skips leading tasks that **prove** they are already built, and
   starts work at the first one that cannot.
3. Skipping is **never** the default and never silent.
4. A single task can be requeued with one command, without editing any file by hand.
5. With the feature absent, unwritable, or off, the loop behaves **exactly** as it does today.

---

## 3. Entities · [E]

| Entity | What it is |
|---|---|
| **ledger file** | `$HOME/.harness/ledger/<key>.tsv`, append-only, one line per completed task |
| **key** | `<project>__<spec-slug>` — stable across worktrees and clones (§4.2) |
| **entry** | `task-label ⇥ commit ⇥ epoch ⇥ attempt ⇥ n_pass ⇥ pass-names` |
| **resume point** | index of the first task that fails the §4.3 proof; everything from there rebuilds |
| **`ralph-ledger.sh`** | dual-form: sourced by the loops as a helper, executed by a human as a CLI |

---

## 4. Approach · [A]

### 4.1 Sidecar, outside the repo — and why the two in-repo options are both wrong

The ledger lives at `$HOME/.harness/ledger/`, beside `logs/` and `status/` — the established home
for durable loop artefacts (`ralph-log.sh:24`, `ralph-status.sh:41`) — but see §6 on culling.

It cannot live in the repo. The loop resets the worktree between attempts
(`ralph-qwen.sh:162-164`):

```bash
git reset -q -- . ; git checkout -- . ; git clean -fd -- .
```

- An **untracked** in-repo ledger is destroyed by `git clean -fd` on the first retry.
- A **tracked** one is swept into `git add -A` and pollutes every task commit with loop
  bookkeeping — and is then subject to the same reset.

A gitignored file would survive (`clean` is deliberately `-fd`, never `-x`), but that makes loop
state invisible to `git status` while still sitting in the operator's tree. Outside is cleaner and
matches where the rest of the harness already writes.

### 4.2 The key must not be the worktree basename

`ralph-status.sh:35` uses `HB_REPO="$(basename "$HB_ROOT")"`. For a worktree at `~/dev/nfh-phase1`
that yields `nfh-phase1`, not `notes-from-hearing` — so a second worktree of the same project gets
a different identity, and two projects with the same directory name collide. That is a known
defect of the status channel and **must not be inherited here**, because a ledger that changes
identity per worktree cannot resume anything.

Key derivation, readable rather than hashed — this is a diagnostic artefact and a greppable
ledger is a debuggable one:

```
project = basename of remote.origin.url, minus .git   (fallback: basename of repo toplevel)
slug    = spec dir relative to repo root, '/' -> '-'
key     = <project>__<slug>          e.g.  notes-from-hearing__specs-v1
```

### 4.3 The ledger proposes; the gate disposes

**An entry is permission to skip re-executing. It is never proof the work exists.** Two
independent conditions must *both* hold before a task is skipped:

1. **Ancestry** — `git merge-base --is-ancestor <recorded-commit> HEAD`. Proves the commit is in
   this history at all. Fails correctly against a fresh worktree whose branch never carried the
   work.
2. **Verdict** — every check the entry recorded as `PASS` is `PASS` in the gate output *right
   now*. Proves the work is still there.

Ancestry alone is not enough, and the counter-example is concrete: if the work merged and was
later **reverted**, the original commit is still an ancestor of HEAD while the code is gone. Only
the verdict test catches that.

The walk is **monotonic**: iterate the queue from the top, skip while both conditions hold, and
**stop skipping permanently at the first task that fails either**. No holes, no reordering — the
resume point is a single index, which is the only version of this a human can reason about at 2am.

### 4.4 Skipping is opt-in; recording is not

Recording is always on: it appends to a file outside the repo and changes no loop behaviour.

**Skipping requires `RALPH_RESUME=1`.** A skip that happens by default is a false-PASS shape — the
loop claims progress it did not make — and the field report is explicit that *a false PASS is
strictly worse than a false FAIL, because the line keeps moving*. The operator must ask for it,
and the run must say out loud which tasks it skipped and why.

### 4.5 Fail-open, in the direction of doing the work

Same never-fatal contract as every other sourced helper. Unwritable dir, absent file, malformed
line → every function returns 0, prints nothing on stderr, and **no task is skipped**.

Note the asymmetry with `ralph-retry.sh`: there, degraded means *don't report a regression*; here,
degraded means *don't skip*. Both err toward doing more work and claiming less.

---

## 5. Scope · [S]

### In scope

- `scripts/ralph-ledger.sh` — the sidecar helper and its CLI.
- Recording at the commit boundary in **both** `ralph-qwen.sh` and `ralph-codex.sh`, identically.
- Resume-skip behind `RALPH_RESUME`, in both.
- `list` / `forget` / `clear` subcommands.

### Out of scope

- Any write to `tasks.txt` or `tasks-blocked.txt`. **The driver file is read-only to the loop.**
- Cross-run analysis, corpus building, or trend reporting. The ledger is the *substrate* those
  need; consuming it belongs to `specs/loop-doctor` and a future reader.
- Reordering, dependency resolution, or parallel task execution.
- Any change to the three-verdict contract, STRICT, or the reset.
- Merging with the run-scoped state in `specs/run-regression-guard` — see §6.

---

## 6. Prior decisions / facts the implementer must know · [S]

- **Shell is macOS bash 3.2.** No `declare -A`, no `mapfile`, no `${var,,}`, no unguarded
  `"${arr[@]}"` under `set -u`. See `AGENTS.md`. This is the single most repeated mistake in this
  repo's loop history.
- **`ralph-qwen.sh` and `ralph-codex.sh` are deliberate structural twins.** Every change lands in
  both, identically. `specs/run-regression-guard` AC11 asserts this by comparing extracted lines.
- **`specs/run-regression-guard` introduces a *different* state file** —
  `$RETRY_STATE_DIR/ralph-run-$$.passed`, keyed on `$$`, which dies with the process. That is
  correct for its job (within-run regression). **The ledger must not reuse it and must not be
  reused by it**: different lifetime, different key, different failure mode. Two files.
- **`ralph-log.sh` and `ralph-status.sh` cull old artefacts** (logs at 3 days, heartbeats at 1
  day). **The ledger must NOT cull** — a resume six weeks later is a legitimate use, and the
  corpus value is in the old rows.
- The loop already computes everything needed at the commit site: `out` (gate output), `task`,
  `attempt`, and — after `git commit` — the new sha. **The twins' line numbers differ; both are
  given so neither has to be hunted:**

  | site | `ralph-qwen.sh` | `ralph-codex.sh` |
  |---|---|---|
  | task loop opens | `:81` | `:108` |
  | `git add -A` | `:139` | `:145` |
  | `git commit` | `:140` | `:146` |
  | task loop closes | `:177` | `:183` |

- **Nothing in `scripts/` writes `tasks.txt` today** — it is opened for existence
  (`ralph-qwen.sh:25`, `ralph-codex.sh:28`) and line-counted (`ralph-status.sh:37`), never
  written. AC10 preserves that property; it does not establish it.
- `SPEC_DIR` is the loop's first argument and is relative to the target repo's root.
- Culling, for contrast with §6's no-cull rule: logs at `-mmin +4320` (3 days,
  `ralph-log.sh:28`), heartbeats at `-mmin +1440` (1 day, `ralph-status.sh:45`).

---

## 7. Norms · [N]

- Sourced helpers are **best-effort and never fatal**; the loop defines no-op stubs when the file
  is absent, exactly as it does for `ralph-status.sh`/`ralph-bus.sh`/`ralph-retry.sh`.
- **CLI is the base form.** `ralph-ledger.sh` must be runnable by a human with no arguments and
  print something useful. A channel with no reader is how the other five ended up unread.
- Every skip prints one line to stdout naming the task and the commit it trusted.
- Append-only. No function rewrites or truncates the ledger except `clear` and `forget`, both of
  which are explicit human commands.

---

## 8. Safeguards · [S]

1. **`tasks.txt` is never opened for writing** by any code this spec adds.
2. A malformed or truncated ledger line is ignored, not fatal, and does not stop the walk from
   evaluating — it simply fails the proof and ends skipping there.
3. `RALPH_RESUME` unset or `0` ⇒ byte-identical behaviour to today.
4. The final `STRICT=1` pass is untouched and still runs over the whole spec, so a resumed run is
   held to the same standard as a fresh one. **A skip can never reduce what the run must prove.**

---

## 9. Task breakdown · [O]

- **T1** — `scripts/ralph-ledger.sh`: key derivation, `ledger_record`, `ledger_resume_index`,
  never-fatal contract.
- **T2** — the CLI: `list`, `forget <task>`, `clear`, and the sourced-vs-executed guard.
- **T3** — record at the commit boundary in both loops.
- **T4** — resume-skip behind `RALPH_RESUME`, in both loops.

> Reordered from the draft at compile time: the two file-local tasks (helper, CLI) come first and
> the two loop-wiring tasks after, so each pair shares one file and one blast radius. The gate's
> unit tier covers T1-T2 and its integration tier covers T3-T4, which is only a clean split
> because of this order.

**`RALPH_LEDGER_DIR` was added at compile time** as an override of §3's `$HOME/.harness/ledger`,
which remains the default. Every sibling channel has one (`RALPH_LOG_DIR`, `RALPH_STATUS_DIR`,
`RETRY_STATE_DIR`) and §11 forbids the gate from writing the operator's real corpus — a feature
whose whole purpose is to accumulate a durable ledger must not have its ledger scribbled on by
its own test suite.

---

## 10. Acceptance criteria (EARS) · [O]

- **AC1** (Ubiquitous) `scripts/ralph-ledger.sh` shall define `ledger_key`, `ledger_record` and
  `ledger_resume_index`, shall be `bash -n` clean, and shall be executable.
- **AC2** (Ubiquitous) `ledger_key` shall derive from the **origin remote URL**, not the worktree
  directory name — asserted by computing the key in two worktrees of one repo and requiring them
  **equal**, and in two same-named directories of different repos and requiring them **unequal**.
- **AC3** (Event-driven) When `ledger_record` is called with a task label, commit, attempt and
  gate output, it shall append exactly one tab-delimited line, and the `pass-names` field shall
  contain every check the output marked `PASS` and no check it marked `FAIL` or `PEND`.
- **AC4** (Unwanted) If `$HOME/.harness/ledger` is unwritable, then every function shall return 0,
  print nothing on stderr, and `ledger_resume_index` shall report **0**.
- **AC5** (State-driven) While `RALPH_RESUME` is unset or `0`, the loop shall execute every task in
  `tasks.txt` and produce the same commits and exit status as before this spec.
- **AC6** (Event-driven) When `RALPH_RESUME=1` and a ledger entry's commit is an ancestor of HEAD
  **and** every check it recorded as `PASS` is `PASS` now, the loop shall skip that task and print
  a line naming the task and the trusted commit.
- **AC7** (Unwanted) If a ledger entry's commit is **not** an ancestor of HEAD, then that task
  shall not be skipped — asserted in a fresh worktree that never carried the commit.
- **AC8** (Unwanted) If a ledger entry's commit **is** an ancestor of HEAD but a check it recorded
  as `PASS` is not `PASS` now, then that task shall not be skipped. **This is the revert case, and
  it is the reason ancestry alone is insufficient.**
- **AC9** (State-driven) While walking the queue, once a task fails the proof, no later task shall
  be skipped even if its own entry would qualify — the resume point is a single index.
- **AC10** (Ubiquitous) No code path added by this spec shall open `tasks.txt` for writing —
  asserted structurally over both loops and the helper.
- **AC11** (Event-driven) When `ralph-ledger.sh` is executed with no arguments, it shall exit 0 and
  print the current ledger's rows (or a clear "no ledger yet" line), never a usage error.
- **AC12** (Event-driven) When `ralph-ledger.sh forget <task>` is run, that task's rows shall be
  removed and every other row preserved byte-for-byte.
- **AC13** (Ubiquitous) `ralph-qwen.sh` and `ralph-codex.sh` shall carry identical ledger call
  sites — asserted by comparing the extracted lines, so the twins cannot drift.
- **AC14** (Unwanted) If the ledger contains a malformed line, then the walk shall not abort and
  shall not skip past it.

---

## 11. Verification (the harness)

`specs/tasks-ledger/verify.sh`, hermetic, two tiers — copy the shape of
`specs/run-regression-guard/verify.sh`, and **create every directory the loop is pointed at** (the
`RETRY_STATE_DIR` lesson: a gate that models a degraded mode must not accidentally *create* that
mode in its own fixtures, or it tests the degradation instead of the feature).

**Unit tier** (AC1, AC2, AC3, AC4, AC11, AC12, AC14): drive the helper directly under `/bin/bash`
with `set -u`, with `HOME` redirected to a scratch dir.

- **AC2** needs two real worktrees of one throwaway repo (keys must match) and two same-named
  directories in different throwaway repos (keys must differ). Both halves are required — a
  constant-returning `ledger_key` satisfies the first on its own.
- **AC3** must be driven with fixture gate output containing **all three verdicts**, and must
  assert both directions: the `PASS` name is present **and** the `FAIL`/`PEND` names are absent.
  The trap is that `pend` lines carry the check name too (`  pend  alpha (not built yet)`), so a
  naive `grep`-the-name implementation records pending checks as passed and a one-directional
  assertion cannot tell. Feed it `alpha`=PASS, `beta`=FAIL, `gamma`=PEND and require exactly
  `alpha`.

**Integration tier** (AC5-AC10, AC13): real `ralph-qwen.sh` runs in a throwaway git repo, mock `oc`
first on `PATH`, `RALPH_STATUS_DIR`/`RALPH_LOG_DIR` redirected, `RALPH_BUS=off`.

| fixture | shape | proves |
|---|---|---|
| `resume-clean` | 2-task spec, run to green, run again with `RALPH_RESUME=1` | AC6 — both skipped, run is a no-op |
| `resume-off` | same, second run **without** `RALPH_RESUME` | AC5 — both re-executed |
| `resume-fresh-worktree` | ledger present, new worktree off a branch lacking the commits | AC7 — nothing skipped |
| `resume-reverted` | run to green, `git revert` T1's commit, resume | **AC8** — T1 not skipped though its commit is still an ancestor |
| `resume-gap` | T1 qualifies, T2 does not, T3 would qualify | AC9 — only T1 skipped |

**Red-before-green** (amendment): AC6, AC7, AC8 and AC9 must each be shown RED against the current,
unmodified loops before the fix lands. AC5 must be shown **PASSING** pre-fix — it is a
don't-break-it guard, and a green AC5 before any change is what proves the harness really drives
the loop rather than asserting into a void.

**Anchoring** — per the dilemma recorded 2026-08-18, presence-gate each check on **its own task's
narrowest deliverable**, never on a shared container. `$HOME/.harness/ledger/` is created by T1, so
gating T2/T3 checks on *the directory* would arm them during T1 and make T1 impossible.

**Blind spot, stated:** the verdict test compares check *names*. A gate that renames a check
between runs will fail the proof and rebuild the task — conservative, correct, and mildly annoying.
A gate that **deletes** a check makes the entry that referenced it unprovable, which is also the
safe direction. Neither is worth solving here.

## 11b. Loop execution

`scripts/run-loop.sh build-converge specs/tasks-ledger` from a worktree on a throwaway branch.
**Same caution as `specs/ralph-retry-contract` and `specs/run-regression-guard`: the loop being
modified is the loop doing the modifying.** Run from an isolated copy of `scripts/` — bash re-seeks
in a running script, so the executing copy must not be the one being edited. Note it in
`tasks.txt`.

## 12. Open questions

- **OQ1** — should `ledger_record` also fire for a task that was **skipped**, so the ledger shows a
  resumed run's shape? Leaning no: an append-only file of things that actually happened is easier to
  trust than one that records inferences.
- **OQ2** — `forget` currently means "rebuild this task". Should there be a `pin` (never rebuild,
  even if the proof fails)? It is the natural next ask and it is also a footgun that defeats §4.3
  entirely. Deferred until something asks for it twice.
- **OQ3** — the ledger is per `(project, spec)`. A spec that gets renamed loses its history
  silently. Acceptable, or worth a `migrate` subcommand?
