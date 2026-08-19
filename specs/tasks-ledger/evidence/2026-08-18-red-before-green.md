# Red-before-green — specs/tasks-ledger

Recorded 2026-08-18, at compile time, against `origin/main` @ `b7027ed`.

## Two configurations, one gate

| configuration | PASS | FAIL | pend | exit |
|---|---|---|---|---|
| **A** — clean `main`, nothing implemented | 8 | 0 | 20 | 0 (STRICT: 1) |
| **B** — a full ANCESTRY-ONLY implementation | 25 | 2 | 1 | 1 |

Configuration B is a complete, working, plausible implementation of this spec with **one**
thing left out: `ledger_resume_index` checks `git merge-base --is-ancestor` and stops there,
never comparing the recorded verdicts against the current gate. It was written in the
scratchpad and never committed, so a real loop run stays a fair measurement.

It passes 25 of 28 checks. The two it fails are exactly the two the spec says exist to
catch it:

```
  FAIL  ac8:reverted-not-skipped — ancestor=1 a.txt-absent=yes T1-rerun=no
  FAIL  ac9:walk-stops-at-first-gap — T1-rerun=no T2-rerun=no T3-rerun=no; want no/yes/yes
```

`ac8` is the revert case from §4.3 — `ancestor=1` and `a.txt` is gone, and the adversary
skipped the task anyway. `ac9` is the monotonic walk. **§4.3's claim that ancestry alone is
insufficient is now demonstrated by machine rather than argued.**

## Three gate defects, found by running against a near-correct implementation

None of these were visible against clean `main`, where everything simply pends.

### 1. The gate tested the CLI while claiming to test `ledger_key`

The idiom `bash -c '. "$0"; ledger_key' <helper>` sets `$0` **to the helper**, so a correct
`[ "${BASH_SOURCE[0]}" = "$0" ]` guard fires and the CLI dispatcher runs instead of the
function. `ledger_key` returned `no ledger yet at /…`, and every downstream check inherited
that string as a filename. Fixed by sourcing through a wrapper script, the way the loops
themselves do it.

### 2. `ac6` passed for the wrong reason — the fourth instance of that family

The probes grepped `^T[0-9]:` in the recorded prompts. The label is **not** at line start —
ralph's prompt reads `…this one task, nothing else: T1: create a.txt`. So the probe never
matched anything and reported "0 tasks executed" for every run, which is precisely what
`ac6` wants to see. **It would have passed against a loop that skipped nothing at all.**

| spec | check that lied | why it passed |
|---|---|---|
| loop-doctor | `ac15:no-forbidden-invocations` | matched the word in a **comment** |
| ralph-retry-contract | `ac9:regressed-check-named` | FAIL feedback already contained the name |
| run-regression-guard | `ac9:stop-names-destroying-task` | task banner already contained the label |
| **tasks-ledger** | **`ac6:resume-skips-proven-tasks`** | **probe never matched, so "0 executed" was free** |

### 3. `grep -c` on a missing file yields the empty string, not `0`

A fully-skipped resume run never creates `prompts.txt`, so this was the normal path, not an
edge case. The count compared unequal to `0` and failed a check that should have passed.

## One fixture defect

`ac5`'s second half asserted all three tasks re-execute with `RALPH_RESUME` off. Unreachable:
a second run over an already-built tree makes every task a no-op, and ralph correctly refuses
a no-op attempt (`ralph-qwen.sh:126`), stopping at T1. Rewritten to assert what AC5 actually
forbids — that T1 is still handed to the executor.
