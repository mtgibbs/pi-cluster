# Spec: judge loop — climb above the deterministic gate toward "good"

- **Status:** **Draft v0.3** — v0.2 folded in the 2026-08-02 Codex planning check
  (`reviews/2026-08-02-codex-planning-check.md`; verdict NEEDS-REVISION, all four BLOCKERs
  independently verified); v0.3 folds in **field evidence from production**
  (`evidence/2026-08-03-harness-gate-gap-evidence.md` — four reproduced gate-gap classes from
  `specs/export` in new-horizons#25). §12's open questions are RESOLVED. `tasks.txt` +
  `verify.sh` remain deferred until the **§6 gate-score interface fix lands** — that is the one
  hard prerequisite.
- **Owner:** Matt (design by Claude; adversarial review by Codex; executor TBD)
- **Constitution:** `specs/constitution.md` (+ `/CLAUDE.md` Core Mandates)
- **Depends on:** `scripts/gate-score.sh` **with the amended fail-closed contract** (§6 — it must
  expose `verify_rc` and propagate a nonzero verifier exit). Implementation is blocked until that
  contract exists. Wiring the score into `ralph-qwen.sh` is **not** a prerequisite (OQ-5).
- **Touches (proposed):** new `scripts/ralph-judge.sh`; a small amendment to
  `scripts/gate-score.sh` (separate, prerequisite PR). No change to `ralph-qwen.sh` or `review-hub`.

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

Production proof this layer is necessary (`evidence/2026-08-03-harness-gate-gap-evidence.md`): the
`specs/export` gate was validated **two ways before handoff** — a reference implementation (15/15)
and mutation testing (5/5 caught) — and still missed **four distinct defect classes**, every one
found by reading the diff above a green gate. Both validation techniques share a structural blind
spot: they only ever run the gate against implementations that *attempted the task*. **A gate
cannot validate its own blind spots.** That is exactly the gap a judge fills — and why the judge
reads the **diff against spec intent**, never the gate's verdict.

## 2. Outcomes (Definition of Done) · [R]

1. After a spec's deterministic gate is green, `scripts/ralph-judge.sh <spec-dir>` runs an
   independent judge that reviews the solution against **intent** (spec §§ + constitution +
   design-principles), proposes concrete improvements, applies the safe ones, and commits them.
2. **The deterministic gate is inviolable.** Any judge-proposed mutation that breaks the gate,
   *lowers* the score, or **shrinks the check count** is auto-reverted. A green gate can only get
   greener or stay green — and it must stay the *same gate* (§6 baseline contract).
3. It **terminates in bounded time**: every external command runs under a timeout, every round
   processes a bounded number of findings, loop-until-dry with a hard round cap (§4 bounds).
4. It leaves an **audit trail** with a stable location and schema (§8): which findings, applied vs
   rejected, score before/after each, and a **gate-gap list** (defects the judge found that the
   gate *missed* — candidates to tighten the gate/spec next time).
5. It is **PR-gated**: it improves the branch a human still reviews and merges. It does not merge.

## 3. Entities · [E]

**Finding** — one judge observation. Ungrounded findings are rejected as bikeshedding:

| field | meaning |
|---|---|
| `id` | stable slug (dedupe key across rounds AND runs — see §8 ledger) |
| `file`, `line` | where (repo-relative path; absolute or escaping paths are invalid) |
| `category` | `clarity` \| `naming` \| `spec-fidelity` \| `gate-gap` |
| `spec_anchor` | **REQUIRED** — the spec § or design-principle it serves. No anchor → dropped. |
| `problem` | one sentence |
| `suggested_change` | concrete, applyable |
| `kind` | `mutate` (apply to the solution) \| `gate-gap` (the gate missed this — report, don't apply) |

**JSONL contract (fail-closed).** Each nonblank judge-output line MUST be one JSON object matching
the Finding schema. The **entire judge invocation is rejected before any mutation** on: malformed
JSON, missing/extra fields, invalid enums, non-relative paths, invalid line numbers, invalid IDs,
or duplicate IDs with unequal payloads. Empty output is the only valid zero-finding response — a
parse failure is never treated as "dry."

**Gate-gap taxonomy** — the four production-reproduced classes (evidence doc §§1–4), each with
the mechanical question the judge asks. `gate-gap` findings SHOULD name their class:

| class | the defect | the judge's question |
|---|---|---|
| `fail-open-ordering` | an early-exit path (pend/presence) returns success before scope/litter checks run | does any exit-0 path skip later checks? |
| `assertion-theatre` | the assertion checks the feature *said something*, not the *right thing* | is the expected value a literal string instead of a computed comparison against an oracle? |
| `invariant-blindness` | round-trip/idempotency/symmetry ACs pass when both sides are equally wrong | does every invariant AC also have an absolute anchor? |
| `fixture-coincidence` | the fixture's data cannot express the failure, so the AC passes for the wrong reason | could this fixture ever produce a failing value — and has this assertion ever been observed RED? |

> A fixture that cannot fail is worse than no fixture — it purchases false confidence, and it
> survives review because the line item is present and green. *(evidence doc §4)*

**Two injectable commands** — the seam that makes this testable AND model-swappable. Both are
specified as full contracts (argv, stdin, stdout, exit codes) in tasks — mockable in substance,
not just in name:

- `JUDGE_CMD` — reads the spec + the current solution/diff, emits findings (JSONL above). Also
  callable as `JUDGE_CMD --check-resolution <finding-json>`, which MUST emit exactly
  `{"id":"…","resolved":true|false}` (§4). **Default: Codex (`codex exec`)** — a different model
  family from the executor (OQ-2).
- `EXECUTOR_CMD` — applies one finding. **Default: the same `oc run` qwen path `ralph-qwen.sh`
  uses** — local labor, frontier judgment.

## 4. Approach · [A]

A **mutate → re-gate → accept/reject** loop, with the deterministic gate as the guardrail.
**One `mutate` finding per judge invocation** — each round re-judges against the new HEAD, so
findings never act on a stale tree and two-mutation oscillation (rename A→B, then B→A, both
gate-neutral) cannot arise within a run; the cross-run ledger (§8) blocks it across runs:

```
preflight: isolated worktree, expected branch, clean porcelain (§8) — else abort
baseline:  two consecutive identical converged gate runs (§8 flake rule) → s_base, total_base
until dry (a round with no fresh accepted mutation) or round == MAX_ROUNDS:
  findings = JUDGE_CMD(spec, solution)           # under JUDGE_TIMEOUT; JSONL fail-closed (§3)
  fresh    = findings - ledger                   # persistent dedupe; rejected ids never return
  f        = first fresh mutate finding (MAX_FINDINGS_PER_ROUND bounds gate-gap intake too)
  before_head = git rev-parse HEAD
  EXECUTOR_CMD(apply f)                          # under EXECUTOR_TIMEOUT; MUST NOT commit
  s2 = gate-score(verify.sh)                     # under GATE_TIMEOUT; STRICT=1; §6 parse contract
  accept iff: verify_rc==0 AND converged AND no_fail
          AND total == total_base AND score >= s_base
          AND JUDGE_CMD --check-resolution f → resolved:true
  on accept: stage only paths changed by f, re-check branch, commit (finding id in message)
  on reject/timeout/nonzero-exit: restore exactly before_head + clean to preflight state
  record every decision in the ledger BEFORE continuing (§8)
gate-gaps collected into the report — NOT applied; suggestions to harden the gate
```

**Bounds (all mandatory):** `MAX_ROUNDS` bounds judge invocations; `MAX_FINDINGS_PER_ROUND` bounds
records processed per invocation; `JUDGE_TIMEOUT`, `EXECUTOR_TIMEOUT`, `GATE_TIMEOUT` bound every
external command. Judge or gate timeout/nonzero exit aborts the run **fail-closed**; executor
timeout/nonzero exit rejects and restores that mutation, then aborts. (Empirical footnote: the
very first Codex dispatch for this spec's own review hung silently for 30+ minutes — the timeout
rule is not theoretical.)

**Judge above gate, never instead of it.** The judge is free to be creative *because* every change
is caught by an objective net — a mutation the judge loves but that breaks a check simply doesn't
land. The **`--check-resolution` confirmation** closes the other half: a gate-neutral edit that
*doesn't actually address the finding* is rejected too, so "accepted" means both safe AND on-point.

**The judge's first-class input is the delta between spec prose and gate assertions.** Field
observation (evidence doc §6): the executor *fixes precisely what is gated and regresses what is
merely described* — a faithful stamper optimising against the only objective it can observe. The
judge's value is highest exactly where the spec says something the gate cannot measure, so the
judge prompt receives spec + diff + the gate's assertion list, and is asked what the spec promises
that no assertion covers. It never receives the gate's verdict as evidence of quality.

**`escalate` is a legitimate judge verdict.** Some findings need judgment neither model has (the
export loop's id-preservation fix took a human-verified collision branch). A judge may end the
run with `escalate` + rationale instead of a mutation — "stop and hand to a human" is a success
mode of the loop, not a failure of it.

Rejected alternative: a judge with no deterministic anchor. That is a slot machine — always finds
*something*, "improvements" silently regress, and it never terminates. The gate is what turns
"keep going toward better" from a random walk into a ratchet.

## 5. Scope · [S]

### In scope (proposed)
- `scripts/ralph-judge.sh` — the post-convergence judge loop. Standalone; composes AFTER
  `ralph-qwen.sh`, so the deterministic loop stays pure and terminating (OQ-4).
- **Prerequisite amendment to `scripts/gate-score.sh`** (separate PR, sequenced first): expose
  `verify_rc=<n>` on the score line and exit nonzero whenever the underlying verifier exits
  nonzero. Fail-closed gating is impossible without it (§6).

### Out of scope
- Modifying `ralph-qwen.sh` (score-into-retry wiring is independent work, no longer sequenced
  before this — OQ-5). Modifying `review-hub` internals. Auto-merging. Auto-hardening the gate
  from gate-gaps (v1 only *reports* them).

## 6. Prior decisions / facts the implementer must know · [S]

- **`gate-score.sh` as merged (#104) is NOT sufficient** — two verified defects (planning-check
  findings 2–3):
  1. It never captures the verifier's exit status (`run="$(bash "$V" 2>&1)"`); its own exit is
     derived purely from parsed lines. A verifier that prints PASS lines then crashes still
     yields `converged=1`.
  2. `score=passed/total` of *parsed* lines: a mutation that deletes 9 of 10 checks from
     `verify.sh` still scores 1.000.
  **Required contract before this loop is built:** `gate-score.sh` exposes `verify_rc=<n>` and
  returns nonzero when the verifier does. **A valid accept requires** `verify_rc=0`,
  `converged=1`, `no_fail=1`, `total>0`, **and `total` equal to the pre-run baseline** — score
  alone never proves the gate was preserved.
- **Score-line parsing:** parse ONLY the **final** `---GATE-SCORE---` sentinel and the single
  key-value line immediately following it. Raw verifier output is printed verbatim *before* the
  sentinel, so a verifier that itself prints `score=` or a sentinel string must not fool the
  parser. Reject missing / duplicate-after-final / malformed / nonnumeric fields.
- **STRICT parity:** every baseline and post-mutation gate invocation runs from repo root with
  `STRICT=1` exported through `gate-score.sh` — the same final convergence gate `ralph-qwen.sh`
  uses (`STRICT=1 bash "$VERIFY"`), not a weaker variant.
- **Executor pattern to mirror** (`ralph-qwen.sh`): `OC_RUN_TIMEOUT=… oc run --dir "$ROOT" "$prompt"`.
  Its tree-restore (`git checkout -- . && git clean -fd`) is NOT sufficient here — it restores
  from the index (staged rejected edits survive) — hence the §8 `before_head` protocol.
- **`review-hub` reuse rejected for v1 (OQ-1):** its validators are coupled to GitHub webhooks,
  changed-file APIs and Check-Run reporting, and return pass/block summaries, not this Finding
  schema. Steal its *patterns* (model-call wrapper, fail-closed defaults, repeated-vote stability),
  not its validators.
- **Reference implementation of the pend/scope contract ruling:** `specs/export/verify.sh` in
  new-horizons#25 — PEND keys on the *dependency's* observable, never the task-under-test's own
  deliverable; missing deliverable on a single-task spec is a hard FAIL; scope/litter checks run
  first and fatal. The ruling's text ships with the gate-score amendment; that file is the shape
  to copy.
- **Red-before-green, per AC (evidence doc §5):** an assertion that has never been observed
  failing is an assertion of unknown value. The judge's gate-gap checklist asks it mechanically
  ("has this assertion been seen RED?"); making it a *required field per AC* in the spec template
  is the deeper constitution-level upgrade, sequenced separately.
- **Lessons from the scored-gate dogfood — apply them when this becomes tasks:** match task
  granularity to the deliverable; every task must be observable/gradeable; give literal shapes not
  prose; the judge/executor calls MUST be mockable so `verify.sh` can test the loop deterministically.

## 7. Norms · [N]

- POSIX-ish bash, matching `ralph-qwen.sh`. Optional-and-never-fatal side channels (heartbeat, log).
- **Judge ≠ executor.** Default judge is Codex (different family = real independence); default
  executor is qwen. Both are knobs (`JUDGE_CMD`/`EXECUTOR_CMD`), but a same-model pairing is an
  explicit operator override the operator chooses, never a silent default (OQ-2).
- Every accepted mutation is its own commit with the finding id in the message — reviewable,
  revertible. The executor never commits; only the loop does, after all accept checks pass.
- Findings cite a spec § or principle, or they don't count.

## 8. Safeguards · [S]

1. **Gate inviolable — fully specified.** Accept requires `verify_rc=0 ∧ converged ∧ no_fail ∧
   total==total_base ∧ score>=s_base` (§6). Anything else restores `before_head`, full stop.
2. **Flake detection.** The baseline is TWO consecutive identical converged gate runs; any
   post-mutation disagreement between two runs marks the gate `gate-unstable`, restores the
   mutation, and stops for human review. A flaky gate is a finding, not a coin to flip.
3. **Bounded everything.** `MAX_ROUNDS`, `MAX_FINDINGS_PER_ROUND`, and per-command timeouts (§4).
   Judge/gate failures abort fail-closed.
4. **Snapshot/restore protocol.** Preflight asserts an isolated worktree, the exact expected
   branch, and empty `git status --porcelain` (untracked included). Each mutation records
   `before_head`; the executor MUST NOT commit; rejection restores exactly `before_head`, removes
   only files created after preflight, and asserts the tree is clean again. Acceptance re-checks
   the branch and stages only the paths that mutation changed.
5. **Persistent ledger.** `JUDGE_STATE_DIR` (default under `git rev-parse --git-path ralph-judge`)
   holds an append-only JSONL ledger keyed by repo, branch, spec path, and finding id. Every
   seen/accepted/rejected/gate-gap decision is written atomically BEFORE the loop continues, and
   reloaded on startup — a rejected finding stays rejected across runs; interrupted runs recover
   by reconciling recorded `before_head`/`after_head` against current HEAD.
6. **PR-gated.** Runs in the sandbox/worktree; output is a better branch for human review, never a
   merge.
7. **Grounded.** An ungrounded / no-`spec_anchor` finding is dropped — no taste-only churn. The
   JSONL contract (§3) is fail-closed: parse failure rejects the invocation, never fakes a dry round.
8. **Conservative mutation surface (OQ-3).** v1 accepts only localized comments, naming, clarity,
   and literal spec-fidelity corrections. Dead-code deletion and behavior-preserving refactors are
   OUT — both can change behavior the gate doesn't observe, which is precisely this loop's founding
   problem. Such proposals are reported as gate-gaps for a human instead.
9. **Read-only to secrets/tree beyond scope** — same as every ralph stage; the judge reads
   code+spec, never secrets.
10. **Audit trail is an interface, not an aspiration.** The report lives OUTSIDE the worktree (in
    `JUDGE_STATE_DIR`) so reject-cleanup can never delete it, has a stable path and JSON schema
    (defined with tasks), and every decision is recorded before the next action starts.

## 9. Task breakdown · [O] — SKETCH ONLY (not yet `tasks.txt`)

Anticipated ~4 observable tasks, each testable with mock `JUDGE_CMD`/`EXECUTOR_CMD` + a fixture gate:
- **The gate-score amendment** (separate, first): `verify_rc` + exit propagation + tests.
- **The guardrail apply-cycle:** given ONE finding, apply via `EXECUTOR_CMD`, re-gate, run
  `--check-resolution`, accept iff the full §6/§8 predicate holds, else restore `before_head`.
- **The judge round:** call `JUDGE_CMD`, enforce the JSONL contract, consult + update the
  persistent ledger, run the single mutate through the cycle; shunt gate-gaps to the report.
- **Terminate + report:** loop-until-dry with `MAX_ROUNDS` and all timeouts; write the audit
  (stable path + schema) as decisions happen; clean recovery from an interrupted run.

`verify.sh` (deferred) injects a fake judge/executor and asserts, minimum: a safe finding commits;
a gate-breaking one restores `before_head` exactly (staged-state case included); a gate-gap is
reported-not-applied; malformed JSONL rejects the invocation without mutating; a check-deleting
mutation is rejected on `total` shrink; an executor "timeout" restores and aborts; a re-run after
interrupt does not replay a rejected finding (ledger); and the loop terminates under every case.
Deterministic, offline, like #104.

## 10. Acceptance criteria (EARS) — deferred with tasks.

## 12. Open questions — RESOLVED 2026-08-02 (Codex planning check + orchestrator concurrence)

1. **Judge source → fresh spec-intent judge.** review-hub's validators are webhook/Check-Run
   shaped with pass/block outputs — wrong seam. Reuse its patterns, not its code. (Fast-follow
   reuse remains open for v2.)
2. **Judge model → Codex by default; never the executor's model silently.** Different family =
   real independence; qwen-as-judge is an explicit operator override only.
3. **Autonomy boundary → conservative set** (comments, naming, clarity, literal spec-fidelity).
   Dead-code and refactors excluded in v1 — reported as gate-gaps instead (§8.8).
4. **Placement → standalone `ralph-judge.sh` after `ralph-qwen.sh`.** Folding a stochastic
   reviewer into ralph would corrupt its one-task/fresh-context contract.
5. **Sequencing → the gate-score fail-closed amendment is the prerequisite** (it blocks
   implementation). Wiring the score into `ralph-qwen.sh` retry is independent, valuable, and no
   longer sequenced before this.
