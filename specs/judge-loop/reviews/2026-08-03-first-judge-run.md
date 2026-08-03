# First production judge run — 2026-08-03

- **Target:** `specs/judge-loop` judging its own implementation (freshly merged #136).
- **Cast:** `JUDGE_CMD` = Codex (`codex exec`, read-only, JSONL contract wrapper) ·
  `EXECUTOR_CMD` = qwen (`oc run`) · gate = the 17-check judge-loop verify via `gate-score.sh`.
- **Result:** baseline `1.000/17` (double-run, stable) · **5 findings, all `gate-gap`,
  0 mutations** · outcome `dry` · exit 0.
- **Machinery verdict:** every contract held on the first try — Codex emitted valid JSONL
  (no fences, no prose), nothing was auto-applied (all findings were behavior-adjacent and the
  conservative v1 surface routed them to the report channel), the report matched the ledger,
  and the run bounded itself. The recursion also held: the outer loop's gate spawned eleven
  inner `ralph-judge` fixture runs without interference.

## The headline

All five findings are **genuine spec-fidelity drift, and every one entered at the same seam:
the human compilation of spec §§ → `tasks.txt`**. The executor built exactly what the tasks
gated; what the spec merely described drifted. This is the evidence doc's §6 pattern
("the loop fixes precisely what is gated and regresses what is merely described") observed one
level up — at spec-compile time, caught by the judge whose designed input is precisely the
delta between spec prose and gate assertions.

## Findings (full payloads, recovered — see finding 6)

### 1. `finding-schema-drift` [gate-gap] — §3 Finding JSONL contract
- **problem:** Validation omits the required `line` field and accepts empty `file`, `problem`,
  `spec_anchor`, `suggested_change` strings.
- **suggested:** Reject findings missing `line` or carrying empty required strings; add
  rejection fixtures.

### 2. `unbounded-accept-staging` [gate-gap] — §8.4 snapshot/restore
- **problem:** Acceptance uses `git add -A` rather than staging only the paths changed for
  the finding.
- **suggested:** Enforce staging scope; add a fixture where the executor modifies an
  unrelated path.

### 3. `missing-command-defaults` [gate-gap] — §7 judge ≠ executor
- **problem:** The script requires `JUDGE_CMD`/`EXECUTOR_CMD` instead of providing the
  spec's Codex/qwen defaults.
- **suggested:** Reconcile the contract (implement defaults, or amend the spec).

### 4. `incomplete-preflight-identity` [gate-gap] — §8.4
- **problem:** Preflight records the current branch but never proves an isolated worktree on
  the exact expected branch.
- **suggested:** Add identity checks + primary-checkout / wrong-branch rejection fixtures.

### 5. `ledger-contract-incomplete` [gate-gap] — §8.5 persistent ledger
- **problem:** Ledger appends are non-atomic, not keyed by repo/branch/spec path, and there is
  no interrupted-run reconciliation.
- **suggested:** Complete the persistence contract; add interrupted-write recovery fixtures.

### 6. `gate-gap-payload-lost` [meta — found by the run itself]
- **problem:** v1 ledgers gate-gaps by id only; the problem/suggestion payloads existed nowhere
  after the run. These five were recovered only because Codex's session log
  (`~/.codex/sessions/…`) happened to retain the message.
- **suggested:** Ledger records for `gate-gap` (and `rejected`) carry the full finding object.

## Triage (recommendations — decided with Matt)

| # | finding | call | rationale |
|---|---|---|---|
| 1 | finding-schema-drift | **fix now** | The spec's Finding table is the contract; `line` + nonempty enforcement is small and pure fail-closed. |
| 6 | gate-gap-payload-lost | **fix now** | Without payloads the judge's most valuable output evaporates; one-line ledger change + fixture. |
| 2 | unbounded-accept-staging | **fix now (as scope enforcement)** | Stronger than partial staging: any post-mutation change outside the finding's `file` ⇒ reject `scope-violation`. Subsumes the staging concern and adds a safety property. |
| 4 | incomplete-preflight-identity | **partial fix** | Optional `RJ_EXPECTED_BRANCH` assert is cheap; *isolated-worktree detection* defers to v1.1 (fixture repos are primary checkouts — the detection story needs design, not a patch). |
| 3 | missing-command-defaults | **amend spec (two-way sync)** | Explicit-required is safer than silent defaults for a code-mutating loop, and env-bound defaults couple the script to a host's tool paths. The spec's "defaults" describe the intended *cast*, which belongs in the operator's wrapper — codify that. |
| 5 | ledger-contract-incomplete | **amend spec + defer** | The state dir already lives under the worktree's git-dir, which *is* per-repo/branch keying — spec overstated. Interrupted-run reconciliation stays a real v1.1 item. |

## Runbook notes for the next pass

- Findings recovery must never depend on `~/.codex/sessions` — that was luck (#6).
- Judge call ~9 min under a 25-min `run_bounded` cap; full run ~22 min, dominated by the
  gate's 11 live fixture cases (this target's gate is unusually heavy — it *is* the loop).
- The wrapper pair lives at the operator layer, as triage #3 recommends:
  `judge-codex.sh` (JSONL + fence-strip + `--check-resolution`) and `exec-qwen.sh`
  (one finding, one file, no commits). Home them in `scripts/` when #3's spec amendment lands.
