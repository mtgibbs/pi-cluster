# Spec: the retry contract — a retry must be clean, informed, and honest about regression

- **Status:** Draft v0.1
- **Owner:** Matt (design by Claude; executor TBD)
- **Constitution:** `specs/constitution.md` + `specs/amendments.md` (v1.3.0) (+ `/CLAUDE.md` Core Mandates)
- **Touches:** `scripts/ralph-qwen.sh`, `scripts/ralph-codex.sh`, new `scripts/ralph-retry.sh`,
  new `specs/ralph-retry-contract/{tasks.txt,verify.sh,fixtures/}`.
- **Source:** dogfood run `qwen-61568` on `specs/loop-doctor`, 2026-08-18 — stopped on T1 after
  3 attempts having twice held the right answer, never at the same time.

---

## 1. Why · [R]

Ralph's retry loop promises a **fresh, targeted second try**: reset the tree, feed back exactly
what failed, run again with clean context. Run `qwen-61568` showed the promise is broken in three
independent ways, all with the same root — **the retry is neither clean nor informed.**

### 1.1 The observation

T1 of `specs/loop-doctor`, three attempts, one check away from passing the whole time:

| Attempt | `t1:unreadable-dir-exit-2` | `t1:no-declare-A-bash32` |
|---|---|---|
| 1 | **PASS** | FAIL |
| 3 | FAIL | **PASS** |

The loop had the correct implementation of each half, in different attempts, and stopped for a
human with neither. Nothing in the machinery noticed that attempt 3 *lost* something attempt 1
had.

### 1.2 D1 — the feedback is regression-blind

`ralph-qwen.sh:142-145` (identical at `ralph-codex.sh:148-151`):

```bash
feedback="
A previous attempt FAILED verification with:
$(printf '%s' "$out" | grep -E 'FAIL|VERIFY' | head -20)
Fix exactly those failures."
```

Only **FAIL** lines travel. The next attempt is never told what already passed, so "fix exactly
those failures" is, structurally, an invitation to trade one check for another. This is the same
blind spot the judge loop closed with `total == total_base` (`specs/judge-loop/spec.md` §6:
*"score alone never proves the gate was preserved"*) — the build loop has no equivalent guard.

### 1.3 D2 — the reset cannot clear a staged file

```bash
git -C "$ROOT" checkout -- . 2>/dev/null || true
git -C "$ROOT" clean -fd -- . 2>/dev/null || true
```

`checkout -- .` restores the worktree **from the index**; `clean -fd` removes only **untracked**
files. A file the executor ran `git add` on is neither. After `qwen-61568` stopped, its worktree
still held `A  scripts/loop-doctor.sh` — attempt 3's rejected work, staged, surviving the reset
that exists to remove it.

**Codex predicted this exact failure** in the judge-loop planning check
(`specs/judge-loop/reviews/2026-08-02-codex-planning-check.md`, finding #4):

> the cited ralph restore only resets the worktree and deletes untracked files. **If the executor
> stages a rejected edit, `git checkout -- .` restores that staged version into the worktree**;
> the rejected mutation can enter the next accepted commit.

It was fixed for `ralph-judge.sh` (the §8.4 `before_head` protocol) and **left live in the build
loops**. Two consequences: attempt N+1 is not a fresh attempt (it inherits code no session in its
context wrote), and a later task's `git add -A && git commit` sweeps the leftovers into a commit
whose message claims to be about something else.

### 1.4 D3 — the prompt never forbids staging

`ralph-qwen.sh:82-86` tells the model what to build and never mentions git. The judge loop's
executor binding is explicit — `ralph-judge-exec-qwen.sh`: *"Do NOT run `git add` or
`git commit`"* — because the loop, not the executor, owns the index. The build loops make the
same assumption and never state it. D3 is what pulls D2's trigger.

### 1.5 D4 — the prompt points at the wrong spec sections

Same line, both loops:

> `Follow the spec's section 10 reference and section 7 acceptance criteria EXACTLY.`

In the current `specs/TEMPLATE.md`, **§7 is Norms** and **§10 is Acceptance criteria** — the
sentence has them backwards, and calls §10 a "reference". Every task of every loop run carries
this misdirection.

## 2. Outcomes (Definition of Done) · [R]

1. A failed attempt's work is **fully removed** before the next attempt — staged, unstaged, and
   untracked alike. A retry starts from the same tree state the task started from.
2. When an attempt fails a check that a **previous attempt of the same task passed**, the loop
   names those checks in the feedback as regressions, distinctly from ordinary failures.
3. The executor is **told not to touch the index** (`git add`/`commit`/`stash`), matching the
   contract the judge loop already states.
4. The prompt's spec-section pointers match `specs/TEMPLATE.md`.
5. Both build loops (`ralph-qwen.sh`, `ralph-codex.sh`) get all four, with the regression logic
   **shared, not duplicated**.
6. The gate proves each of these against a **real ralph run driven by a mock executor** — not by
   grepping the script for the fix.

## 3. Entities · [E]

### 3.1 Check line and check name

The gate's own output is the data source. A **check line** matches the classifier
`gate-score.sh` already uses: 1-4 leading spaces, then a leading token, case-insensitive.

| leading token | verdict |
|---|---|
| `PASS`, `OK` | passed |
| `FAIL` | failed |
| `PEND`, `PENDING` | pending |
| anything else | not a check — ignored |

The **check name** is the first whitespace-delimited field *after* the verdict token, e.g.
`t1:unreadable-dir-exit-2`. Names are opaque strings; the loop never interprets them.

> Reuse `gate-score.sh`'s awk classifier idiom verbatim. Do **not** substring-match a verdict word
> anywhere in a line — that defect has now been shipped twice (`gate-score.sh` header;
> `specs/loop-doctor/evidence/2026-08-18-red-before-green.md` §4).

### 3.2 `PASSED_EVER` — the per-task high-water set

The set of check names that have reported `passed` in **any prior attempt of the current task**.
Reset to empty at the start of each task, never carried across tasks. Held in a temp file (macOS
bash 3.2 — no associative arrays).

### 3.3 `REGRESSED`

`PASSED_EVER` ∩ {names failing or pending in the attempt that just failed}. Ordered as the gate
emitted them. Empty is the normal, healthy case.

### 3.4 Reset contract

Three steps, in this order, all against `$ROOT`:

| step | command | removes |
|---|---|---|
| 1 | `git reset -q -- .` | staged entries (the D2 gap) |
| 2 | `git checkout -- .` | modifications to tracked files |
| 3 | `git clean -fd -- .` | untracked files and directories |

Order is load-bearing: unstaging first is what lets step 2 restore from `HEAD` rather than from
the executor's staged version. Step 3 must remain **`-fd` without `-x`** — the gitignored
`opencode.json` a worktree needs must survive (`scripts/README.md`).

## 4. Approach · [A]

**Split by contract, because the two halves have different failure tolerances.**

- **The reset (D2) and the prompt (D3, D4) are correctness**, not telemetry. They are small inline
  edits in both loops — one added line and two edited strings each. They must never be
  best-effort.
- **Regression detection (D1) is commentary.** It gets a new sourced helper
  `scripts/ralph-retry.sh` with the same optional-and-never-fatal contract as
  `scripts/ralph-status.sh` and `scripts/ralph-log.sh`: no-op stubs when absent, every write
  guarded, and a failure to compute regressions can never fail the run it is annotating. Both
  loops source it, so the logic exists once.

**Rejected — putting the reset in the sourced helper too.** It would give a correctness-critical
operation the helper's "never fatal" contract, which is exactly backwards: a reset that silently
no-ops is D2 again.

**Rejected — feeding back the full PASS list.** With a 50-check gate that is 50 lines of prompt
per retry against a ~32k window, and §17 already showed context pressure changes qwen's behaviour.
Naming only the regressions is cheaper and a stronger signal.

**Rejected for v1 — keeping the best attempt's tree.** Attempt 1 scored higher than attempt 3;
the loop discarded it. Retaining the best attempt means stashing per attempt and choosing between
trees, which is a different (and larger) feature. OQ2.

## 5. Scope · [S]

### In scope
- `scripts/ralph-qwen.sh` — reset (§3.4), prompt (D3, D4), source + call the helper.
- `scripts/ralph-codex.sh` — the same four, identically.
- `scripts/ralph-retry.sh` — new, sourced, best-effort.
- `specs/ralph-retry-contract/{tasks.txt,verify.sh,fixtures/}`.

### Out of scope — do NOT touch
- `scripts/ralph-judge.sh` — its §8.4 `before_head` protocol already solves D2 its own way.
  Do not "unify" them in this spec.
- `scripts/ralph-status.sh`, `ralph-log.sh`, `ralph-bus.sh`, `gate-score.sh`, `loop-report.sh`,
  `run-loop.sh`, `scripts/loops/*`.
- `specs/TEMPLATE.md` — D4 is fixed by correcting the **prompt** to match the template, never by
  renumbering the template to match the prompt.
- Any `clusters/pi-k3s/**` manifest, and `specs/loop-doctor/**`.

## 6. Prior decisions / facts the implementer must know · [S]

- **Exact sites.** `ralph-qwen.sh`: prompt 82-86, feedback 142-145, reset 146-147.
  `ralph-codex.sh`: prompt 109-113, feedback 148-151, reset 152-153. Line numbers will move as
  the file is edited — anchor on the literal strings, not the numbers.
- **There are TWO `feedback=` assignment sites in `ralph-qwen.sh`, not one.** Line 142 is the
  verify-failure path this spec is about; **line 122 is the no-op guard's** ("A previous attempt
  produced NO file changes at all…"). Only the verify-failure site gets a regression block — a
  no-op attempt regressed nothing, it wrote nothing. Appending to both would attach a regression
  notice to an attempt that never ran a gate. `ralph-codex.sh` has the same pair.
- **`git reset` needs the pathspec.** Use `git -C "$ROOT" reset -q -- .`, matching the `-- .` the
  neighbouring commands already carry. A bare `git reset --hard` is forbidden: it would also
  discard the *committed* work of earlier tasks in this run if HEAD were ever mis-set, and the
  loop's whole safety story is that each passing task is already committed.
- **`clean -fd` must not become `-fdx`.** `opencode.json` is gitignored and MUST survive; without
  it a fresh worktree's headless `oc` auto-rejects every write — the exact fault
  `specs/loop-doctor` classifies as `permission-blocked`.
- **The verdict classifier already exists.** `scripts/gate-score.sh` lines 45-59 hold the awk
  that classifies by leading token only. Copy that shape; do not write a second dialect.
- **Best-effort helper pattern to mirror.** `scripts/ralph-log.sh` — sourced, `*_init` guarded,
  no-op stubs defined by the caller when the file is absent (`ralph-qwen.sh:51`). Copy the shape
  including the stub line.
- **The loops are near-copies, deliberately.** `ralph-codex.sh` is a structural twin of
  `ralph-qwen.sh` (`scripts/README.md`: *"Structurally identical... Only the executor swaps"*).
  Every change here lands in both. Divergence between them is a defect.
- **Testing a loop is a solved problem here.** `specs/judge-loop/verify.sh` runs the real
  `ralph-judge.sh` against mock judge/executor commands — *"the outer loop's gate spawned eleven
  inner `ralph-judge` fixture runs without interference"*. This gate does the same to the build
  loop (§11).
- **Redirect the loop's side channels in tests.** `RALPH_STATUS_DIR`, `RALPH_LOG_DIR` and
  `RALPH_BUS=off` must point at temp paths so a gate run never writes into the operator's real
  `~/.harness` corpus — which `specs/loop-doctor` reads.

## 7. Norms · [N]

- **Correctness inline, commentary sourced.** Never give a correctness-critical step the
  never-fatal contract (§4).
- **Name regressions, don't summarise them.** The feedback names each regressed check by its
  check name, so the model can act on it. A count is not actionable.
- **The two loops stay twins.** Any edit to one is made to the other in the same task.
- **Speak the existing dialect.** Verdict classification reuses `gate-score.sh`'s leading-token
  rule; the helper reuses `ralph-log.sh`'s init/stub shape; the prompt keeps its existing voice.
- **No new dependencies.** bash + coreutils + git, macOS bash 3.2, no `declare -A`, no `mapfile`.

## 8. Safeguards · [S]

1. **A reset must never destroy committed work.** Only `reset -q -- .`, `checkout -- .`,
   `clean -fd -- .`. Never `reset --hard`, never `clean -x`, never a bare `git reset` without the
   pathspec.
2. **Gitignored files survive.** `opencode.json` must exist in the worktree after a reset, or the
   next attempt is `permission-blocked` by construction.
3. **The regression helper can never fail a run.** Absent file, unwritable temp dir, malformed
   gate output — all degrade to "no regression info", never to a nonzero exit or a stall.
4. **No test writes to the real corpus.** Every gate invocation sets `RALPH_STATUS_DIR`,
   `RALPH_LOG_DIR` under a temp dir and `RALPH_BUS=off`.
5. **No behaviour change on the happy path.** A task that passes on attempt 1 must produce the
   same commit, the same message, and the same exit status as before this change.
6. **Bounded feedback.** The regression list is capped (10 names) so a wholesale collapse cannot
   flood the prompt.

## 9. Task breakdown · [O]

Deferred to `tasks.txt`. Sketch, ordered so each task has its own observable:

- **T1** — `scripts/ralph-retry.sh`: the sourced helper. `retry_init` (per-task reset of state),
  `retry_record <gate-output>` (fold passed names into `PASSED_EVER`), `retry_regressions
  <gate-output>` (print `REGRESSED` names, one per line, capped at 10). Observable: called
  directly with fixture gate output, it prints the expected names.
- **T2** — the reset fix in **both** loops: add `git -C "$ROOT" reset -q -- .` ahead of the
  existing `checkout`/`clean` pair. Observable: a staged file no longer survives a failed attempt.
- **T3** — the prompt fix in **both** loops: correct the section pointers (§7 Norms, §10
  Acceptance criteria) and add the index prohibition. Observable: the literal strings.
- **T4** — wire the helper into **both** loops: source it with no-op stubs, call `retry_init` per
  task, `retry_record` after every gate run, and append a named regression block to `feedback`
  when `retry_regressions` is non-empty. Observable: a two-attempt mock run whose second attempt's
  prompt contains the regressed check's name.

## 10. Acceptance criteria (EARS) · [O]

- **AC1** (Ubiquitous) `scripts/ralph-retry.sh` shall exist, be `bash -n` clean, and define
  `retry_init`, `retry_record`, and `retry_regressions`.
- **AC2** (Event-driven) When `retry_record` is given gate output containing `  PASS  alpha` and
  `  FAIL  beta`, and `retry_regressions` is then given output containing `  FAIL  alpha`, it
  shall print `alpha`.
- **AC3** (Unwanted) If a check failed in an earlier attempt and fails again, then
  `retry_regressions` shall **not** print it — only checks that were previously passing count.
- **AC4** (Event-driven) When `retry_record` is given a line whose message text contains the word
  `fail` inside a `PASS` check, it shall still count that check as passed (leading-token rule).
- **AC5** (Ubiquitous) `retry_init` shall clear state so names from a previous task never appear
  in a later task's regressions.
- **AC6** (Unwanted) If the helper's state directory is unwritable, then `retry_record` and
  `retry_regressions` shall exit 0 and print nothing.
- **AC7** (State-driven) While running a task, when an attempt fails after the executor has
  **staged** a new file, the next attempt shall begin with that file absent from both the index
  and the worktree.
- **AC8** (Ubiquitous) A reset shall leave a gitignored `opencode.json` present in the worktree.
- **AC9** (Event-driven) When an attempt regresses a previously-passing check, the next attempt's
  prompt shall contain that check's name and a distinct regression heading (not merely the FAIL
  list).
- **AC10** (Ubiquitous) Neither loop's script shall contain `reset --hard`, `clean -fdx`, or
  `clean -x`.
- **AC11** (Ubiquitous) Both loops' prompts shall reference `section 7` as Norms and `section 10`
  as acceptance criteria, and shall instruct the executor not to run `git add`, `git commit`, or
  `git stash`.
- **AC12** (Ubiquitous) `ralph-qwen.sh` and `ralph-codex.sh` shall carry the same reset sequence
  and the same prompt clauses — asserted by comparing the extracted strings, so the twins cannot
  drift.
- **AC13** (State-driven) While a task passes on its first attempt, the loop shall commit exactly
  as before — one commit, message prefix `ralph(`, same exit status.

## 11. Verification (the harness)

`specs/ralph-retry-contract/verify.sh`, hermetic. Two tiers:

**Unit tier — the helper.** Feed `retry_record`/`retry_regressions` fixture gate output
(`fixtures/gate-*.txt`) and assert names. Covers AC1-AC6. Cheap and fully deterministic.

**Integration tier — a real ralph run with a mock executor.** The only honest way to prove AC7,
AC9, AC13. Precedent: `specs/judge-loop/verify.sh` drives the real `ralph-judge.sh` with mock
commands.

```
mktemp -d  ->  git init  ->  seed a trivial spec dir (spec.md, tasks.txt, verify.sh)
           ->  put a fake `oc` FIRST on PATH; it reads a per-attempt script from
               fixtures/mock-exec/ so attempt 1 and attempt 2 behave differently
           ->  RALPH_STATUS_DIR/RALPH_LOG_DIR under the temp dir, RALPH_BUS=off,
               RALPH_SHEET=off, OC_RUN_TIMEOUT small
           ->  run scripts/ralph-qwen.sh <temp spec dir>, capture the prompts the mock saw
```

The mock records each prompt it receives to a file — that captured prompt is what AC9 asserts
against. Mock behaviours needed:

| fixture | attempt 1 | attempt 2 | proves |
|---|---|---|---|
| `stage-and-fail` | writes a file **and `git add`s it**, gate fails | writes nothing | AC7 — the file is gone |
| `trade-checks` | makes check `alpha` pass, `beta` fail | makes `beta` pass, `alpha` fail | AC9 — prompt names `alpha` |
| `pass-first-try` | makes the gate pass | (never runs) | AC13 — one commit, unchanged |

**Red-before-green** (amendment): each of AC7, AC9, AC12 must be shown RED against the
**current, unmodified** `ralph-qwen.sh` before the fix lands — AC7 and AC9 are literally the
`qwen-61568` failure, so the pre-fix red run is the reproduction, and it belongs in
`evidence/`. AC10 and AC11 must be shown red by a deliberately wrong edit.

**Blind spot, stated:** the mock executor is not qwen. This gate proves the *loop's* contract —
what it resets, what it says, what it commits. It cannot prove a real model reacts usefully to a
regression notice. That is measurable only by re-running `specs/loop-doctor` after this lands
(§12/OQ1), which is the point of having a corpus.

## 11b. Loop execution

`scripts/run-loop.sh build-converge specs/ralph-retry-contract` from a worktree on a throwaway
branch, `opencode.json` copied in first.

**Caution, unique to this spec:** the loop being modified is the loop doing the modifying. The
executor edits `scripts/ralph-qwen.sh` **while a copy of it is running the task**. bash reads
scripts incrementally, so editing a running script can change what it executes next. Mitigation:
the gate's integration tier runs a **copy** of the loop from the temp dir, and the operator should
prefer `ralph-codex.sh` as the driver (`run-loop.sh` is qwen-only today — see OQ3) or accept that
a mid-task edit may require a re-run. Note this in `tasks.txt` so the executor does not "helpfully"
restructure the file it is running.

## 12. Open questions

- **OQ1 — Does a regression notice actually help?** Unknown, and measurable: re-run
  `specs/loop-doctor` T1 after this lands and compare against `qwen-61568`'s ledger row. If qwen
  still trades checks, the answer is that the *task* was too big (loop-doctor finding 4) and the
  feedback was never the binding constraint. **Proposed:** land the fix, then re-run, and treat
  the pair as the first entry in the cross-run corpus `specs/loop-doctor` exists to build.
- **OQ2 — Keep the best attempt?** Attempt 1 outscored attempt 3 and was discarded. Retaining the
  best tree needs per-attempt stashing plus a comparison rule; `gate-score.sh` already emits the
  score to compare on, and the judge loop's `total == total_base` shows score alone is not enough.
  Out of scope here; genuinely valuable.
- **OQ3 — `run-loop.sh` build phase is qwen-only.** It hardcodes `ralph-qwen.sh`, so a
  `build-converge` run can never use codex. That is a strategy-layer gap, not a retry-contract
  one, but it is what forces the §11b caution above. Sequenced separately.
- **OQ4 — Should a regression be more than a message?** A regressed check is arguably a stronger
  signal than a plain failure — grounds for stopping early (Loop Library "progress-based
  stopping", `reference_loop_library` upgrade 3) rather than burning the last retry. **Proposed:**
  message-only for v1; revisit once OQ1 has data.

## Two-way sync rule

Logic change → fix this spec, then the scripts. Both loops always move together; if they ever
diverge, that is a defect to fix, not a variation to document.
