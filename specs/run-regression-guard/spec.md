# Spec: the run-scoped regression guard — a later task must not destroy an earlier task's work

- **Status:** Draft v0.1
- **Owner:** Matt (design by Claude; executor TBD)
- **Constitution:** `specs/constitution.md` + `specs/amendments.md` (v1.3.0)
- **Touches:** `scripts/ralph-retry.sh`, `scripts/ralph-qwen.sh`, `scripts/ralph-codex.sh`,
  new `specs/run-regression-guard/{tasks.txt,verify.sh,fixtures/}`.
- **Source:** run `qwen-10668` on `specs/loop-doctor`, 2026-08-18 — six tasks passed
  individually, and the final `STRICT=1` gate then found ten checks unbuilt.

---

## 1. Why · [R]

### 1.1 What happened

`qwen-10668` committed all six tasks and then stopped:

```
✋ STOP: every task passed, but the final STRICT gate found unbuilt work:
  FAIL  ac3:one-line-per-run(8) — still unbuilt at the final check (STRICT)
  FAIL  t2:sorted-newest-updated-first — still unbuilt at the final check (STRICT)
  … 8 more
```

T6 (`--ledger`) had **deleted the human-output branch T2 built**:

```diff
     cat "$JSON_OUTPUT_TEMP"
-else
-    # Output human-readable format
-    echo "$SORTED"
+fi
```

Bisect confirms it: T2, T3, T4 and T5 each emit 8 lines on stdout; **T6 emits 0**.

### 1.2 Why the gate let it through

T2's checks are armed by a presence-gate — `if <output contains a run id> … else pend`. With the
output deleted the gate sees no output, the checks **pend**, and **a pend is not a failure**. T6
passed its own checks and committed.

> **`pend` means "not built yet." A gate cannot distinguish that from "built, then broken."**
> The observable is identical. This is a property of the three-verdict contract itself
> (`specs/TEMPLATE.md` §11), not of one gate — every presence-gated check in this repo has it.

### 1.3 Why STRICT is not sufficient on its own

`STRICT=1` **did** catch it — that is exactly what the final pass is for, and it worked. But:

- it fires **after the whole run is spent**, six tasks and ~40 minutes in;
- it reports *"still unbuilt at the final check"*, which points a human at **T2**, when the
  culprit is **T6**. The attribution is not just missing, it is actively misleading.

### 1.4 Why the retry contract does not cover it

`scripts/ralph-retry.sh` tracks `PASSED_EVER` **per task** — `retry_init` resets at every task
boundary, which is right for attempt-level check-trading (the `qwen-61568` failure) and blind by
construction to a *later task* breaking an *earlier task's* work. The two are different scopes of
the same idea, and only one is built.

## 2. Outcomes (Definition of Done) · [R]

1. A check that **passed at the moment an earlier task committed** and is now failing or pending
   is treated as a **regression**, not as a pend — the task does not commit.
2. The regression is named in the retry feedback, together with **which task last held it green**.
3. If retries are exhausted, the loop stops naming the **destroying** task, not the victim.
4. `STRICT=1` remains unchanged as the final backstop. This guard makes detection earlier and the
   attribution correct; it does not replace the last line of defence.
5. Both build loops get it, with the logic **shared, not duplicated** (§7).
6. A task that legitimately passes, and every green run today, behaves **exactly as before** —
   no new failure mode on the happy path.

## 3. Entities · [E]

### 3.1 Two scopes, two files

| scope | file | reset when | answers |
|---|---|---|---|
| **task** (exists) | `$RETRY_STATE_DIR/ralph-retry-$$.passed` | every task, by `retry_init` | "did this attempt trade away a check an earlier *attempt* had?" |
| **run** (new) | `$RETRY_STATE_DIR/ralph-run-$$.passed` | once per run, by `retry_run_init` | "did this task break a check an earlier *task* had?" |

Same format — one check name per line. Same best-effort contract. Kept as separate files, not one
file with scopes, so `retry_init`'s per-task truncation can never clear the run-scoped set.

### 3.2 `RUN_PASSED` — the run-scoped high-water set

Every check name that was classified `passed` **in the gate output of a task that went on to
commit**. It is written only at a successful task boundary — never from a failed attempt, whose
tree is about to be discarded.

### 3.3 Cross-task regression

`RUN_PASSED` ∩ { names classified `failed` **or** `pending` in the gate output of the task now
claiming success }.

`pending` is deliberately included: `PASS → PEND` is the exact signature of the `qwen-10668`
failure, and it is the one a `failed`-only rule would miss.

## 4. Approach · [A]

**Check at the moment a task claims success, not during its retries.**

Transient failures between attempts are normal and already handled by the task-scoped feedback.
The invariant that matters is at the commit boundary: *when a task says it is done, everything
that was green before it must still be green.* So the hook sits between the gate passing and the
`git commit`, and a violation converts that "pass" into a failed attempt on the existing retry
path — no new control flow.

**Fail-open to the status quo, never fail-closed on bad data.** The guard can only *add* a
failure, so it must never fire on missing or unreadable state. If the run-scoped file is absent,
there are no regressions and the loop behaves exactly as it does today — with `STRICT` still
catching the case at the end. That asymmetry is what makes a best-effort helper acceptable here
even though it participates in a failing decision.

**Rejected — making the presence-gate smarter instead.** The natural instinct is to have gates
distinguish "absent" from "deleted". They cannot: a gate sees one filesystem state and has no
memory of earlier ones. The memory has to live in the loop, which is the only component that
watches the whole run.

**Rejected — failing on any `PASS → PEND` inside a single task's attempts.** During retries a
tree is reset between attempts, so a pend there is ordinary. Only the commit boundary is
meaningful.

## 5. Scope · [S]

### In scope
- `scripts/ralph-retry.sh` — add `retry_run_init`, `retry_run_record`, `retry_run_regressions`;
  **fix the bash 3.2 defect in §6.**
- `scripts/ralph-qwen.sh`, `scripts/ralph-codex.sh` — call them; convert a detected regression
  into a failed attempt.
- `specs/run-regression-guard/{tasks.txt,verify.sh,fixtures/}`.

### Out of scope — do NOT touch
- `specs/TEMPLATE.md` and the three-verdict contract. The `pend` semantics are correct; this adds
  a guard around them rather than redefining them.
- `scripts/gate-score.sh`, `loop-report.sh`, `run-loop.sh`, `scripts/loops/*`,
  `scripts/ralph-judge.sh`, `ralph-status.sh`, `ralph-log.sh`, `ralph-bus.sh`.
- The final `STRICT=1` block in either loop — it stays exactly as it is (§2.4).
- `specs/loop-doctor/**` — its T6 defect is the evidence for this spec, not its subject.

## 6. Prior decisions / facts the implementer must know · [S]

- **A live bash 3.2 defect in the file you are editing — fix it as part of T1.**
  `scripts/ralph-retry.sh` declares `regressions=()` at **line 45** and expands it at
  **line 58**, under `set -u`:
  ```
  local line verdict name regressions=()     # line 45
  …
  for i in "${regressions[@]}"; do           # line 58  <- the failing expansion
  ```
  **The runtime error says `line 41`, which is the `retry_regressions() {` line** — bash 3.2
  attributes an unbound-variable error inside a function to the function's opening line, not to
  the offending one. Do not go looking at line 41; the fix belongs at 58 (or 45).
  On macOS bash 3.2 (`GNU bash, version 3.2.57`) `"${arr[@]}"` on an **empty** array under
  `set -u` is an error, not an empty expansion. Reproduced:
  ```
  $ /bin/bash -c 'set -u; a=(); for i in "${a[@]}"; do :; done'
  /bin/bash: a[@]: unbound variable
  ```
  It fires on the **healthy** path — no regressions — and `qwen-10668` emitted it twice:
  `ralph-retry.sh: line 41: regressions[@]: unbound variable`. Impact today is stderr noise plus
  a nonzero return, because the caller's `&&` short-circuits and simply adds no block. But it
  breaks the helper's stated "return 0 always" contract, and any new caller that checks the
  status differently would misbehave. Fix with the standard 3.2 guard —
  `[ ${#regressions[@]} -gt 0 ] && for i in …` — or drop the array for a temp file, which is
  what the rest of the helper already uses.
- **Exact hook site.** `ralph-qwen.sh` — the gate block is `if out="$(cd "$ROOT" && bash "$VERIFY" 2>&1)"; then`,
  followed by `git add -A`, `git commit`, `passed=1`, `hb_write passed true`, `break`. The guard
  goes **after `out` is known and before `git add -A`**. `ralph-codex.sh` has the same block.
  Anchor on the literal strings; line numbers move.
- **The two loops are deliberate twins** (`scripts/README.md`). Every change lands in both, and
  the retry-contract gate already asserts they do not drift — extend that, do not weaken it.
- **Verdict classification already exists twice**; do not write a third dialect. `gate-score.sh`
  lines 45-59 hold the canonical awk; `ralph-retry.sh` already mirrors it. Reuse it, and never
  substring-match a verdict word anywhere in a line.
- **`retry_record` is already called on both the pass and fail paths** (T4 of the retry contract).
  The run-scoped recorder is a *different* call with different timing — commit boundary only.
- **Testing a loop is solved here**: `specs/ralph-retry-contract/verify.sh` runs the real
  `ralph-qwen.sh` in a throwaway git repo against a mock `oc` first on `PATH`. Copy that harness
  wholesale, including its lesson — **create every directory you point the loop at.** The
  retry-contract gate failed a correct implementation for three attempts because `run_loop` set
  `RETRY_STATE_DIR` to a directory it never created, so the helper degraded to silence exactly as
  its own AC required (`specs/ralph-retry-contract/evidence/`).
- **Redirect the side channels in tests**: `RALPH_STATUS_DIR`, `RALPH_LOG_DIR` under a temp dir
  and `RALPH_BUS=off`, so a gate run never writes into the operator's real `~/.harness` corpus —
  which `specs/loop-doctor` reads.

## 7. Norms · [N]

- **The guard adds failures, never removes them.** It can turn a pass into a retry; it must never
  turn a failure into a pass.
- **Name both parties.** A regression message names the regressed check *and* the task that last
  held it green. "Something broke" is not actionable; that is the whole complaint against
  STRICT's current wording.
- **Shared, not duplicated.** The logic lives in `ralph-retry.sh`; the loops only call it.
- **Twins move together.** Any edit to one loop is made identically to the other.
- **macOS bash 3.2**: no `declare -A`, no `mapfile`, and **no unguarded `"${arr[@]}"`** — see §6.
- **Bounded output**: cap the named regressions (10) as the task-scoped path already does.

## 8. Safeguards · [S]

1. **Never fire on absent or unreadable state.** No run-scoped file, or an unwritable state dir,
   means "no regressions" — never "everything regressed". The loop degrades to today's behaviour.
2. **Record only from committed states.** `retry_run_record` runs *after* the commit succeeds, so
   a discarded attempt can never poison the high-water set.
3. **`STRICT=1` is untouched** (§2.4). If this guard has a hole, the backstop still holds.
4. **No change to the happy path.** A run with no cross-task regression must produce byte-identical
   commits, messages and exit status to today.
5. **Bounded retries.** A regression consumes an attempt like any other failure; the existing
   `RALPH_RETRIES` cap and the STOP path are unchanged.
6. **No new dependencies.** bash + coreutils + git.

## 9. Task breakdown · [O]

Deferred to `tasks.txt`. Sketch, each with its own observable:

- **T1** — `ralph-retry.sh`: fix the §6 bash 3.2 array defect, then add `retry_run_init`,
  `retry_run_record`, `retry_run_regressions` against the §3.1 run-scoped file.
  Observable: called directly with fixture gate output, on bash 3.2, both the empty and non-empty
  cases return 0.
- **T2** — wire into **both** loops: `retry_run_init` once per run; after a task's gate passes,
  call `retry_run_regressions "$out"`; on a non-empty result treat the attempt as failed (feedback
  + the existing reset path) instead of committing; on a clean result commit as today and then
  `retry_run_record "$out"`. Observable: a two-task mock run where task 2 deletes task 1's file.
- **T3** — the STOP message: when retries are exhausted on a cross-task regression, name the
  destroying task and the regressed checks. Observable: the literal string in the loop log.

## 10. Acceptance criteria (EARS) · [O]

- **AC1** (Ubiquitous) `scripts/ralph-retry.sh` shall define `retry_run_init`,
  `retry_run_record` and `retry_run_regressions`, and shall be `bash -n` clean.
- **AC2** (Unwanted) If `retry_regressions` or `retry_run_regressions` finds no regressions, then
  it shall print nothing, **return 0, and emit nothing on stderr** — asserted under
  `/bin/bash` with `set -u` (the §6 defect).
- **AC3** (Event-driven) When `retry_run_record` is given gate output containing `  PASS  alpha`
  and `retry_run_regressions` is later given output containing `  PEND  alpha`, it shall print
  `alpha` — **a pend counts, not only a fail**.
- **AC4** (Unwanted) If a check never passed in any committed task, then failing or pending now
  shall not be reported as a cross-task regression.
- **AC5** (Ubiquitous) `retry_init` shall not clear the run-scoped state, and `retry_run_init`
  shall not clear the task-scoped state.
- **AC6** (Unwanted) If the state directory is unwritable, then every run-scoped function shall
  return 0 and print nothing, and the loop shall behave exactly as it does without this feature.
- **AC7** (State-driven) While running a multi-task spec, when a later task's gate passes but a
  check that passed at an earlier task's commit is now failing or pending, the loop **shall not
  commit that task**.
- **AC8** (Event-driven) When AC7 fires, the next attempt's prompt shall name the regressed check
  **and** the task that last held it green.
- **AC9** (Event-driven) When retries are exhausted on a cross-task regression, the loop shall
  stop with a message naming the **destroying** task, and shall exit non-zero.
- **AC10** (State-driven) While a multi-task spec has no cross-task regression, the loop shall
  produce the same number of commits, the same `ralph(` message prefix, and the same exit status
  as before this spec.
- **AC11** (Ubiquitous) `ralph-qwen.sh` and `ralph-codex.sh` shall carry identical guard call
  sites — asserted by comparing the extracted lines, so the twins cannot drift.

## 11. Verification (the harness)

`specs/run-regression-guard/verify.sh`, hermetic, two tiers — copy the shape of
`specs/ralph-retry-contract/verify.sh` and **create every directory the loop is pointed at**
(§6).

**Unit tier** (AC1-AC6): drive the helper directly with fixture gate output, under `/bin/bash`
with `set -u` so the §6 empty-array defect is actually exercised. AC2 must assert **empty stderr**,
not merely empty stdout — the current defect produces the right stdout and the wrong stderr, so a
stdout-only assertion would pass against the broken version.

**Integration tier** (AC7-AC10): a real `ralph-qwen.sh` run in a throwaway git repo, mock `oc`
first on `PATH`, two-task inner spec.

| fixture | task 1 | task 2 | proves |
|---|---|---|---|
| `destroy-earlier` | creates `a.txt` (gate: `alpha` PASS) | **deletes `a.txt`**, creates `b.txt` | AC7 — no commit for task 2; AC8 — prompt names `alpha` and T1; AC9 — STOP names task 2 |
| `clean-two-task` | creates `a.txt` | creates `b.txt`, leaves `a.txt` | AC10 — two commits, unchanged |

The inner `verify.sh` must **presence-gate `alpha` on `a.txt`**, so deleting the file makes the
check pend rather than fail. That is what reproduces `qwen-10668` exactly, and it is the case a
`failed`-only rule would miss (§3.3).

**Red-before-green** (amendment): AC2, AC7, AC8 and AC9 must each be shown RED against the
**current, unmodified** loops before the fix lands — AC7 is literally the `qwen-10668` failure, so
the pre-fix red run is its reproduction. Record it in `evidence/`. AC10 must be shown PASSING
before the fix, since it is a don't-break-it guard, and a green AC10 pre-fix is what proves the
harness really drives the loop.

**Blind spot, stated:** this guard only sees checks the gate emits. Work a later task destroys
that **no check covers** remains invisible — to this guard, to STRICT, and to the gate. The only
defence there is gate coverage, which is a spec-authoring problem, not a loop problem.

## 11b. Loop execution

`scripts/run-loop.sh build-converge specs/run-regression-guard` from a worktree on a throwaway
branch. **The same §11b caution as `specs/ralph-retry-contract` applies: the loop being modified
is the loop doing the modifying.** Run from an isolated copy of `scripts/` — bash re-seeks in a
running script, so the executing copy must not be the one being edited. Note it in `tasks.txt`.

## 12. Open questions

- **OQ1 — Should a cross-task regression be retryable at all?** It is arguably a stronger signal
  than an ordinary failure: the task did something destructive, and the model has no memory of the
  earlier task. **Proposed:** retryable for v1 (the feedback names exactly what to restore), and
  revisit if runs show the retries are wasted.
- **OQ2 — Attribution granularity.** Recording which *task* last held a check green needs a task
  label alongside each name in the run-scoped file. Cheap, and AC8 requires it. Flagged only
  because it makes the state file a two-column format rather than a name list.
- **OQ3 — Does this belong in `ralph-judge.sh` too?** The judge loop already forbids score
  regression via `total == total_base`, which is the same instinct at a different altitude. It is
  probably already covered; confirm rather than assume.
- **OQ4 — Checks that legitimately stop applying.** A spec could, in principle, have a later task
  consolidate away an artifact an earlier check gates on. No spec here does, and it would be a
  spec smell. If one ever appears, the answer is an explicit opt-out in the spec, never a weaker
  guard.

## Two-way sync rule

Logic change → fix this spec, then the scripts. Both loops always move together; divergence
between them is a defect, not a variation.
