# Red before green — `specs/executor-binding/verify.sh`

`specs/amendments.md`, **"Gates must prove they can fail"**. Unlike `evidence-spec-nesting`,
this gate was written **before** the implementation, so the red run is the tree as it stood —
no pinned commit needed.

| | RED (gate written, nothing implemented) | GREEN (T1–T3 done) |
|---|---|---|
| score | 5 PASS / **9 FAIL** / 2 pend | **16 PASS / 0 FAIL / 0 pend** |

## RED

```
  FAIL  AC-1:default-binding-is-qwen — no RALPH_EXEC_CMD defaulting to exec-qwen.sh
  FAIL  AC-2:no-executor-name-in-loop — 99:  OC_SHEET=off OC_RUN_TIMEOUT="${OC_RUN_TIMEOUT:-480}" oc run --dir "$ROOT" "$prompt"
  pend  binding-present-exec-qwen.sh (absent)
  pend  binding-present-exec-codex.sh (absent)
  FAIL  AC-6:codex-builder-deleted — scripts/ralph-codex.sh still exists
  FAIL  AC-6:no-gate-references-a-twin — evidence-convention, evidence-spec-nesting, loop-doctor, ralph-retry-contract, run-regression-guard
  FAIL  AC-6:twin-symmetry-guards-removed — ralph-retry-contract, run-regression-guard, tasks-ledger
  FAIL  AC-7:harness-surface-shrank — 7602 harness lines, was 7465
  FAIL  AC-3:binding-receives-prompt — binding did not receive the task prompt as $1
  FAIL  AC-4:binding-is-bounded — a 60s hang ran 62s — RALPH_EXEC_TIMEOUT did not bound it
  FAIL  AC-5:stillborn-aborts — a stillborn binding gave rc=0, want 3
```

`AC-4`'s *"a 60s hang ran 62s"* is the cleanest single line here: before this change the build
loop had no watchdog of its own at all. `oc` happened to carry one and the deleted codex copy
hand-rolled another, so any third executor would have run unbounded.

## Three defects this gate caught **in itself**

Worth recording, because each one passed a casual reading first.

**1. `/tmp` is `noexec` — and two checks went green having tested nothing.**
The mock bindings were written to `$TMPDIR` and `chmod +x`'d, but the container mounts
`tmpfs … noexec`, so every mock died instantly on *Permission denied*. `AC-4` asserted only
"finished in under 30s" — satisfied by a binding that never started. `AC-5` asserted "exit 3" —
also satisfied, because a binding that cannot start is indistinguishable from one that dies
stillborn. **Two of three executing checks were false green.**

Fixed three ways: bindings are invoked as `bash <path>` so `noexec` cannot silently decide the
result; `AC-4` now requires the elapsed time to be **≥ 3s and < 30s**, so an instant failure can
no longer masquerade as a successful timeout; and `AC-5` additionally greps the transcript for
the binding's own output, distinguishing *"the loop rejected a stillborn binding"* from *"the
binding could not start"*.

**2. `RALPH_LOG=off` in the fixture disabled the thing under test.** With logging off,
`log_path` returns `/dev/null`, the transcript measures 0 bytes, and the stillborn check
(`rc≠0 AND <512B`) fires on *any* nonzero exit. Logging now points into the fixture. Turning off
the mechanism you are testing is not isolation.

**3. Deleting `C="scripts/ralph-codex.sh"` silently deleted six behavioural checks.**
`ralph-retry-contract` gates whole blocks on `grep … "$C"`, and the file runs under `set -u`, so
an unbound `$C` killed the gate at line 50 — every check after it simply never ran. The failure
count *dropped from 7 to 1* and looked like an improvement. It was six behavioural tests
disappearing.

Caught by asking why an unrelated gate got better, then grepping for the check names and finding
them absent rather than passing. All four dangling `"$C"` references are now removed properly,
and the six checks are back, failing exactly as they do on `origin/main`.

> **A falling failure count is not evidence of progress.** Verify that checks *pass*, not that
> they stop failing — the two look identical in a summary line.

## GREEN

```
evidence: 6 negative-invariant · 3 executing · 7 presence
score: 16 PASS / 0 FAIL / 0 pend
```

`AC-4` now reports `(4s)` — the watchdog genuinely fired and waited.

## No collateral damage

Failure counts excluding the by-construction `scope:out-of-scope-files-untouched` guard, which
trips on any branch touching the shared harness:

| gate | control | this branch |
|---|---|---|
| `evidence-convention` | 2 | **2** |
| `evidence-spec-nesting` | 0 | **0** |
| `ralph-retry-contract` | 6 | **6** |
| `run-regression-guard` | 3 | **3** |
| `tasks-ledger` | 3 | **3** |
| `loop-doctor` | 12 | **12** |

Identical throughout. The removed twin-symmetry checks (`ac11`, `ac13`, `ac12`) were the only
ones deleted, and each asserted that two files were byte-identical — never that anything worked.
