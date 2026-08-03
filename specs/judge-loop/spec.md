# Spec: judge loop — climb above the deterministic gate toward "good"

- **Status:** **Draft v0.1 — SKETCH.** `tasks.txt` + `verify.sh` are deliberately NOT written yet;
  the §12 open questions are real forks that change the design. Resolve those → Planned → build.
- **Owner:** Matt (design by Claude; executor TBD)
- **Constitution:** `specs/constitution.md` (+ `/CLAUDE.md` Core Mandates)
- **Depends on:** `scripts/gate-score.sh` (PR #104) — the score is this loop's regression signal.
- **Touches (proposed):** new `scripts/ralph-judge.sh`. No change to `ralph-qwen.sh` or `review-hub`.

---

## 1. Why · [R]

The deterministic gate has a **ceiling of 1.000** = "passes every check I wrote." It cannot pull a
solution *beyond* what the spec author thought to check. Proof from the scored-gate dogfood: the
gate scored a perfect 1.000 and still shipped a **header comment copied from the wrong file** —
caught by eye, never by gate. `verify.sh` answers *"is it correct?"*; nothing yet answers *"is it
good?"* — and "good" (clarity, simplicity, intent-fidelity, the edge the spec implied but never
encoded) is where quality lives.

This is the judge/gradient layer from the original eval-loop discussion: an **independent reviewer
that proposes improvements and keeps mutating the solution toward the spec's intent** — bounded so
it converges instead of bikeshedding forever.

## 2. Outcomes (Definition of Done) · [R]

1. After a spec's deterministic gate is green, `scripts/ralph-judge.sh <spec-dir> [branch]` runs an
   independent judge that reviews the solution against **intent** (spec §§ + constitution +
   design-principles), proposes concrete improvements, applies the safe ones, and commits them.
2. **The deterministic gate is inviolable.** Any judge-proposed mutation that breaks `no_fail` or
   *lowers* the score is auto-reverted. A green gate can only get greener or stay green.
3. It **terminates**: loop-until-dry (a round with zero fresh accepted mutations) with a hard round
   cap — no infinite polishing.
4. It leaves an **audit trail**: which findings, applied vs rejected, score before/after each, and
   a **gate-gap list** (defects the judge found that the gate *missed* — candidates to tighten the
   gate/spec next time).
5. It is **PR-gated**: it improves the branch a human still reviews and merges. It does not merge.

## 3. Entities · [E]

**Finding** — one judge observation. Ungrounded findings are rejected as bikeshedding:

| field | meaning |
|---|---|
| `id` | stable slug (dedupe key across rounds) |
| `file`, `line` | where |
| `category` | `clarity` \| `simplicity` \| `safety` \| `spec-fidelity` \| `dead-code` \| `gate-gap` |
| `spec_anchor` | **REQUIRED** — the spec § or design-principle it serves. No anchor → dropped. |
| `problem` | one sentence |
| `suggested_change` | concrete, applyable |
| `kind` | `mutate` (apply to the solution) \| `gate-gap` (the gate missed this — report, don't apply) |

**Two injectable commands** — the seam that makes this testable AND model-swappable:

- `JUDGE_CMD` — reads the spec + the current solution/diff, emits findings (JSON lines). Default TBD
  (see §12). A mock that emits canned findings is how `verify.sh` will test the loop deterministically.
- `EXECUTOR_CMD` — applies one finding (defaults to the same `oc run` qwen path `ralph-qwen.sh` uses).

## 4. Approach · [A]

A **mutate → re-gate → accept/reject** loop, with the deterministic gate as the guardrail:

```
until dry or round == MAX_ROUNDS:
  findings = JUDGE_CMD(spec, solution)          # independent review vs INTENT, not the checklist
  fresh    = findings - already_seen            # dedupe; never re-propose a rejected id
  for f in fresh where f.kind == mutate:
    snapshot = git stash-point
    EXECUTOR_CMD(apply f)                        # qwen makes the change
    s2 = gate-score.sh(verify.sh)               # the SAME gate, re-run
    if s2.no_fail and s2.score >= s_before:  commit, accept          # gate is the net
    else:                                    revert to snapshot, reject
  collect f where f.kind == gate-gap into the report   # NOT applied — a suggestion to harden the gate
```

**Judge above gate, never instead of it.** The judge is free to be creative *because* every change
is caught by an objective net — a mutation the judge loves but that breaks a check simply doesn't
land. The `score` from #104 is precisely the "did this move us or hurt us?" signal the accept rule
needs. This is why the scored gate had to come first.

Rejected alternative: a judge with no deterministic anchor. That is a slot machine — always finds
*something*, "improvements" silently regress, and it never terminates. The gate is what turns
"keep going toward better" from a random walk into a ratchet.

## 5. Scope · [S]

### In scope (proposed)
- `scripts/ralph-judge.sh` — the post-convergence judge loop. Standalone; composes AFTER
  `ralph-qwen.sh`, so the deterministic loop stays pure and terminating.
- Reuses `scripts/gate-score.sh` unchanged as the guardrail.

### Out of scope
- Modifying `ralph-qwen.sh` (wiring the *score* into its retry is a **separate** PR, sequenced
  first). Modifying `review-hub` internals. Auto-merging. Auto-hardening the gate from gate-gaps
  (v1 only *reports* them).

## 6. Prior decisions / facts the implementer must know · [S]

- **`gate-score.sh` interface (PR #104):** prints `passed/failed/pending/total/score/no_fail/converged`
  after a `---GATE-SCORE---` sentinel, plus `FAIL:`/`TODO:` lines; exit 0 iff converged. This loop
  reads `score` and `no_fail` from that line.
- **Executor pattern to mirror** (`ralph-qwen.sh`): `OC_RUN_TIMEOUT=… oc run --dir "$ROOT" "$prompt"`,
  then `bash "$VERIFY"`, and on reject `git checkout -- . && git clean -fd` to restore the tree.
- **`review-hub` already exists** as an LLM-judge layer (11 validators, eval-first; ADR-008 defines
  its framework seam). It is a *reviewer*, not a *fixer-loop* — but it is a candidate `JUDGE_CMD`
  (see §12 OQ-1).
- **Lessons from the scored-gate dogfood — apply them when this becomes tasks:** match task
  granularity to the deliverable; every task must be observable/gradeable; give literal shapes not
  prose; the judge/executor calls MUST be mockable so `verify.sh` can test the loop deterministically.

## 7. Norms · [N]

- POSIX-ish bash, matching `ralph-qwen.sh`. Optional-and-never-fatal side channels (heartbeat, log).
- **Judge ≠ executor by default.** A model grading its own work is weak; the judge should be a
  different (ideally stronger) model than the one that wrote the code. Both are knobs.
- Every accepted mutation is its own commit with the finding id in the message — reviewable, revertible.
- Findings cite a spec § or principle, or they don't count.

## 8. Safeguards · [S]

1. **Gate inviolable.** A mutation that breaks `no_fail` or lowers `score` is reverted, full stop.
2. **Bounded.** Hard `MAX_ROUNDS` cap + loop-until-dry; deduped findings so nothing re-litigates.
3. **PR-gated.** Runs in the sandbox/worktree; output is a better branch for human review, never a merge.
4. **Grounded.** An ungrounded / no-`spec_anchor` finding is dropped — no taste-only churn.
5. **Auditable.** Full record: findings, accept/reject, score deltas, gate-gaps. No silent changes.
6. **Read-only to secrets/tree beyond scope** — same as every ralph stage; the judge reads code+spec,
   never secrets.

## 9. Task breakdown · [O] — SKETCH ONLY (not yet `tasks.txt`)

Anticipated ~3 observable tasks, each testable with mock `JUDGE_CMD`/`EXECUTOR_CMD` + a fixture gate:
- **The guardrail apply-cycle:** given ONE finding, apply via `EXECUTOR_CMD`, re-gate, accept iff
  still-green-and-not-worse else revert. (The core safety primitive.)
- **The judge round:** call `JUDGE_CMD`, parse + dedupe findings, run each mutate through the cycle;
  shunt gate-gaps to the report.
- **Terminate + report:** loop-until-dry with `MAX_ROUNDS`; write the audit + gate-gap report.

`verify.sh` (deferred) will inject a fake judge that returns a scripted finding set — one safe, one
that breaks the gate, one gate-gap — and assert: the safe one commits, the breaking one reverts, the
gate-gap is reported-not-applied, and the loop terminates. Deterministic, offline, like #104.

## 10. Acceptance criteria (EARS) — deferred with tasks.

## 12. Open questions — **these decide the design; answer before Planned**

1. **Judge source.** Reuse `review-hub`'s validators as `JUDGE_CMD` (DRY, already eval-first and
   grounded — but they're PR/trigger-shaped, not spec-intent-shaped), **or** a fresh
   "review this solution against its spec's intent" judge prompt? *Leaning: fresh spec-intent judge
   for v1 (simpler, purpose-fit), with review-hub reuse as a fast-follow once the seam is proven.*
2. **Judge model.** Local qwen (free, but it's also the executor — self-grading is weak), a *different*
   local model, or a stronger model for judgment only? *Leaning: a different/stronger model than the
   executor — judgment quality matters more here than raw throughput.*
3. **Autonomy boundary.** How far may it mutate before the human PR — clarity/comments/dead-code/naming
   only, or also behavior-preserving refactors within spec? *Leaning: start conservative (non-behavioral
   + spec-fidelity fixes the gate can't see), widen once trusted.*
4. **Placement.** Standalone `ralph-judge.sh` run after `ralph-qwen.sh` (my rec), or a phase inside it?
5. **Sequencing.** This depends on #104 merging AND the score being wired into `ralph-qwen.sh` first.
   Confirm that order.
