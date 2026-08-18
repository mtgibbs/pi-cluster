# Red-before-green evidence — `specs/loop-doctor/verify.sh`

Required by the ratified amendment **"Gates must prove they can fail"** (`specs/amendments.md`
v1.1.0): *a check must be shown RED without the change it verifies — not merely green with it.*

- **Date:** 2026-08-18
- **Method:** the gate was run (a) against an empty tree, (b) against a human-written reference
  implementation, and (c) against six deliberately mutated copies of that implementation.
- **Reference implementation:** written to validate the gate only. It is not the deliverable —
  see "Disposition" below.

---

## 1. Empty tree — the gate does not pass vacuously

```
FAIL  t1:script-exists / t1:script-executable / t1:bash-n-clean
FAIL  ac2:unknown-flag-exit-1 / ac2:usage-on-stderr / t1:unreadable-dir-exit-2
pend  × 33   (T2-T6, each keyed on its own observable)
exit=1
```

T1's deliverable is a **hard FAIL, never a pend** — pend-on-your-own-first-deliverable is exactly
what scored "built nothing" as green in the `specs/export` incident. T2-T6 pend correctly, and
`STRICT=1` converts every pend to a FAIL.

## 2. Reference implementation — the gate can go green

```
50 PASS, 0 FAIL, 0 pend    exit=0
STRICT=1                   exit=0
```

## 3. Mutation battery — every load-bearing check fires

| Mutation to the implementation | Check that went RED |
|---|---|
| classifier tries `executor-stillborn` before `watchdog-kill` | `ac6:watchdog-kill-beats-stillborn` |
| `--now` ignored, clock hardcoded | `ac5:fresh-heartbeat-is-running` |
| `permission requested:` marker never matches | `ac9:permission-blocked` |
| ledger appends unconditionally instead of skipping known `run_id`s | `ac13:ledger-idempotent — 8 then 16` |
| `evidence` blanked for one fault class | `ac7:evidence-non-empty-for-every-run` |
| `evidence` carries 200 bytes of the transcript instead of the marker | `ac14:no-transcript-payload-in-output` |

The AC4/AC5 pair is self-proving by construction: **one fixture, two `--now` values, two
verdicts.** Neither can pass vacuously while the other holds, so the staleness rule cannot be
satisfied by a constant.

## 4. A false negative the green direction caught — in the gate itself

`ac15:no-forbidden-invocations` **failed against known-good code.** Its grep matched the
reference implementation's *header comment*, which merely named `verify.sh`; nothing was invoked.

Fixed by stripping comments before matching. This is the same defect class `gate-score.sh`
already warns about — *"NEVER substring-match a status word anywhere in a line"* — and it is the
concrete argument for research-log §17 finding #3:

> **Verify in both directions.** A gate that only ever fails is as useless as one that only ever
> passes.

Had the gate only ever been run against an empty tree, this would have shipped as a permanent
false FAIL that every future run would have had to work around.

## 5. Known blind spot (stated, not hidden)

A fixtures-only gate validates the classifier against **shapes we already know**. It cannot prove
the §3.3 rule table covers a fault class nobody has observed. That is precisely what the
`unknown` fault and the `unparsed` counter exist to surface at runtime, and why both are printed
rather than swallowed.

## 6. Disposition of the reference implementation

It passes STRICT and is real, working code — but it was written to test the gate, not as the
spec's deliverable. Two legitimate paths, and the choice is the operator's:

- **Ship it** — PR `scripts/loop-doctor.sh` as-is; the loop is not needed for this spec.
- **Hold it back** — let `run-loop.sh build-converge specs/loop-doctor` build it fresh. This spec
  is *about measuring loops*, so executing it with the loop and then pointing the result at that
  very run is the natural dogfood. Note the risk: a reference implementation kept where the
  executor can read it stops being a fair measurement (research log §17, "the fair-comparison
  spec and the effective spec are different documents").
