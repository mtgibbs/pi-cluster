# D2 reproduction — a staged file survives ralph's reset

Minimal reproduction of §1.3, run 2026-08-18. Not a story about the loop: a four-line git
sequence anyone can re-run.

## Setup — a failed attempt's leftovers

```
A  staged.txt      executor ran `git add` (nothing forbids it — §1.4 D3)
 M tracked.txt     a modified tracked file
?? untracked.txt   a stray file
   opencode.json   gitignored, and REQUIRED by the next attempt
```

## Current reset (`ralph-qwen.sh:146-147`)

```bash
git checkout -- . ; git clean -fd -- .
```

```
A  staged.txt                       <-- SURVIVED
files: opencode.json staged.txt tracked.txt
```

`checkout -- .` restores the worktree **from the index**, so it rewrites the staged version back
into place rather than removing it; `clean -fd` skips it because it is no longer untracked. The
next "fresh" attempt begins holding code that no session in its context wrote.

## Proposed reset (§3.4)

```bash
git reset -q -- . ; git checkout -- . ; git clean -fd -- .
```

```
files: opencode.json tracked.txt
  staged.txt gone?        YES
  tracked.txt restored?   YES  (contents back to `base`)
  untracked.txt gone?     YES
  opencode.json survived? YES   <-- AC8; `clean -fd` without -x
  commits intact?         2     <-- no committed work touched (§8.1)
```

Unstaging first is what lets `checkout` restore from `HEAD` instead of from the executor's index.

## Provenance

Codex called this out on 2026-08-02 while adversarially reviewing the **judge**-loop spec
(`specs/judge-loop/reviews/2026-08-02-codex-planning-check.md`, finding #4). It was fixed there
(the §8.4 `before_head` protocol) and never carried across to the build loops. It surfaced in
production on 2026-08-18 as `A scripts/loop-doctor.sh` left in the `qwen-61568` worktree.

**The lesson worth keeping:** an adversarial finding against one component is evidence about
every component that shares the pattern. The planning check found it in the spec under review;
nobody asked whether the two scripts it was *copied from* had the same hole.

---

# Gate evidence — red before green

`specs/ralph-retry-contract/verify.sh`, compiled 2026-08-18, run **before any fix exists**.

## Structure

- **Unit tier** (AC1-AC6) — feeds fixture gate output straight into `retry_record` /
  `retry_regressions`. Pends on `scripts/ralph-retry.sh` existing.
- **Integration tier** (AC7, AC9, AC13) — runs the **real `ralph-qwen.sh`** inside a throwaway
  git repo with a mock `oc` first on `PATH`, `RALPH_STATUS_DIR`/`RALPH_LOG_DIR` redirected and
  `RALPH_BUS=off`, so it never touches the operator's `~/.harness` corpus.

T2-T4 edit *existing* files, which have no new artifact to arm a `pend` on. Each therefore pends
on **its own literal edit being present** and only then asserts the behaviour that edit is meant
to produce: the grep is the arming condition, never the assertion.

## Pre-implementation

```
PASS  ac13:happy-path-one-commit          <- the mock harness really drives a ralph run
PASS  ac13:happy-path-commit-message
PASS  ac8:gitignored-file-survives
pend  × 21
exit=0 ;  STRICT=1 -> exit=1
```

AC13 passing is the load-bearing signal: it proves the integration harness works *before* any
fix, so a later green cannot be an artefact of a broken harness.

## The defect, reproduced automatically

Forcing the T2/T4 presence-gates open against the **current, unmodified** loops:

```
FAIL  ac7:staged-file-gone-next-attempt — attempt 2 saw 'DIRTY'
FAIL  ac9:regression-heading-in-next-prompt
FAIL  ac9:regressed-check-named-inside-block
PASS  ac9:fail-feedback-preserved
PASS  ac9:no-false-regression-on-first-retry
```

`attempt 2 saw 'DIRTY'` **is** the `qwen-61568` failure, now reproduced by machine in a few
seconds: the mock stages a file in attempt 1, and attempt 2 still finds it. The two PASSes are
deliberate don't-break-it guards that must hold both before and after the fix.

## A second false positive, caught the same way

The check began life as *"does attempt 3's prompt contain `alpha`?"* — and it **passed against
the unfixed loop**, because the ordinary FAIL feedback already contains `FAIL  alpha`. It was
testing nothing.

Fixed by scoping the search to the text *between* the regression heading and its closing line.

This is the second time in two specs that running a gate against **known-bad** code exposed a
check that passes for the wrong reason (the first: `ac15` in
`specs/loop-doctor/evidence/2026-08-18-red-before-green.md` §4, which matched a comment).
Red-before-green is not a formality here; it has now caught a real defect in the gate on both
attempts.

---

# Build run — `qwen-86499`, 2026-08-18

`run-loop.sh build-converge specs/ralph-retry-contract`, driven from an **isolated copy** of
`scripts/` (§11b: the loop being modified is the loop doing the modifying; bash re-seeks in a
running script, so the executing copy must not be the edited one).

| Task | Result |
|---|---|
| T1 `ralph-retry.sh` helper | **passed, attempt 1** |
| T2 reset fix in both twins | **passed, attempt 1** |
| T3 prompt fix in both twins | **passed, attempt 1** |
| T4 wire the helper in | failed ×3 → STOP |

Three of four first try, against the previous run's stop-on-T1. The tasks that landed cleanly
were the ones with a literal target: a named function set, a named line to insert, a named string
to replace.

## T4 did not fail — the gate did

The gate's `run_loop` set `RETRY_STATE_DIR="$T/retry"` and **never created that directory**.
`retry_init`'s `: > "$RETRY_STATE_FILE"` then failed, `RETRY_OK` stayed 0, and the helper
degraded to silence — which is exactly what **AC6 requires it to do**. AC9 could therefore never
pass, whatever the executor wrote.

qwen's attempt-3 implementation was correct: sourced with stubs, `retry_init` per task,
`retry_record` on both paths, the regression block appended to the verify-failure feedback only.
Recovering it from `~/.harness/logs/qwen-86499/T4-attempt3.diff` and adding one `mkdir`:

```
28 PASS, 0 FAIL, 0 pend    score=1.000    STRICT exit 0
```

**A gate that models a degraded mode must not accidentally create that mode in its own fixtures**,
or it tests the degradation instead of the feature.

## Two things this run proves about the fix itself

- `ac7:staged-file-gone-next-attempt` **passes** — D2 is closed, verified by a real ralph run
  that stages a file in attempt 1 and finds it gone in attempt 2.
- The twins are byte-identical on all three shared clauses (`ac12`).

Note the ordering subtlety: because the executing loop was the frozen copy, T4's own retries ran
under the **unfixed** reset. The fix was proven by the gate, not by the run that produced it.

## Three specs, three gate defects

| Spec | Defect in the gate | Found by |
|---|---|---|
| loop-doctor | `ac15` matched a comment, not a call | running it against known-good code |
| ralph-retry-contract | "prompt contains `alpha`" passed unfixed | running it against known-bad code |
| ralph-retry-contract | `RETRY_STATE_DIR` never created | **a real executor failing honestly against it** |

The third is the one no mutation test would have caught: the gate was self-consistently wrong, and
only an independent implementation trying to satisfy it exposed the contradiction. This is the
strongest argument yet for running a spec through the loop even when the answer is already known.
