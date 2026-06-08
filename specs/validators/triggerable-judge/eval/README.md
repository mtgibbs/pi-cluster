# Triggerable-Judge — Evaluation Set

The **ruler** for the triggerable-judge prototype. Before building the LLM
judge, we built a labelled set of CronJobs with known-correct verdicts so we
can *measure* what the judge adds over the deterministic lint — precision and
recall, not vibes.

See `../PLAN.md` for the overall plan and the triggerable contract.

## Layout

```
eval/
  expected.yaml     # case registry — the ground truth (verdict + violated criteria + lint baseline)
  synthetic/        # synthetic manifests (the cases with no real cluster equivalent)
  score.py          # grades the lint baseline (live) and a judge output against expected.yaml
  README.md         # this file
```

Real cluster jobs are referenced by path (kept live, no drift); only the cases
that don't exist in the cluster are synthesised under `synthetic/`.

## The 15 cases

Positive class = "not safe to silently trigger" = verdict `fail` or `flag`.
Negative = `pass`. `judge_value` says what each case tests:

- **baseline** (5) — lint passes, judge must pass. Tests **precision** (no false-blocks).
- **agreement** (5) — lint blocks, judge must also fail. Tests **no regression**.
- **judge-only** (5) — lint is blind, judge must catch. Tests **recall beyond the lint** — the value-add.

| # | id | verdict | lint | tests |
|---|----|---------|------|-------|
| 01 | renovate (real) | pass | pass | precision |
| 02 | orphan-sweep-report (real) | pass | pass | precision — has `find` + "delete" in comments, readOnly |
| 03 | postgres-backup (real) | pass | pass | precision — a backup that IS safe (no `--delete`) |
| 04 | flock-writer (synthetic) | pass | pass | precision — writable PVC but takes a `flock` |
| 05 | idempotent-upsert (synthetic) | pass | pass | precision — `ON CONFLICT DO UPDATE`; partner to 11 |
| 06 | pvc-backup (real) | fail | block | no-regression — rsync `--delete` |
| 07 | git-mirror (real) | fail | block | no-regression — rsync `--delete` |
| 08 | media-backup (real) | fail | block | no-regression — rsync `--delete` |
| 09 | worker2-backup (real) | fail | block | no-regression — rsync `--delete` |
| 10 | orphan-sweep-delete (synthetic) | fail | block | no-regression — writable mount + `find -delete` |
| 11 | duplicate-insert-rollup (synthetic) | fail | **pass** | **recall** — blind INSERT, not idempotent |
| 12 | quota-burn-loop (synthetic) | fail | **pass** | **recall** — unthrottled public-API loop |
| 13 | external-counter-rmw (synthetic) | fail | **pass** | **recall** — non-atomic read-modify-write |
| 14 | stale-window-reprocess (synthetic) | fail | **pass** | **recall** — wall-clock window + additive sink |
| 15 | import-resolver (real) | flag | **pass** | **recall** — double-POST on overlap; escalate, don't pass |

The judge-only cases (11–15) are deliberately built to slip past a mount/regex
lint: no `--delete`/`rm -r`/`DROP`/`TRUNCATE`/`mkfs`/`dd`, and no writable
shared NFS/PVC mount. Their shared state lives in an external service or in
wall-clock time — exactly the slice that needs reasoning, not pattern-matching.

## Running the scorer

Needs `pyyaml` (repo `.venv` has it):

```bash
# lint baseline only + validate the eval set's own `lint:` labels
.venv/bin/python specs/validators/triggerable-judge/eval/score.py

# fail if a `lint:` label in expected.yaml disagrees with the live lint
.venv/bin/python specs/validators/triggerable-judge/eval/score.py --check

# grade an LLM-judge output (Phase 1+)
.venv/bin/python specs/validators/triggerable-judge/eval/score.py --judge out.json
```

### Current lint-baseline result

```
precision=1.00  recall=0.50  F1=0.67
DoD: [PASS] no false-blocks   [FAIL] judge-only gap closed (0/5)   [PASS] no regression
```

1.00 precision / 0.50 recall is the bar. The judge's job is to push recall to
1.00 — catch all five judge-only cases — **without** dropping precision below
1.00 (no false-blocks on the PASS set), and name the right violated criteria.

## Judge-output format (the Phase 1 contract)

`score.py --judge` expects JSON — a `{"results": [...]}` object or a bare list:

```json
{"results": [
  {"id": "11-duplicate-insert-rollup",
   "verdict": "fail",
   "criteria": ["idempotent"],
   "findings": ["second run inserts a duplicate row for current_date"]}
]}
```

- `verdict`: `pass` | `fail` | `flag`
- `criteria`: subset of `idempotent`, `concurrency-tolerant`, `time-insensitive`,
  `bounded`, `quota-safe`, `fails-safe`
- `findings`: optional free-text evidence (not scored, but shown in the PR review)

## Adding a case

1. Drop the manifest under `synthetic/` (or point at a real path).
2. Add an entry to `expected.yaml` with `verdict`, `criteria`, `lint`, `judge_value`, `why`.
3. Run `score.py --check` — it confirms your `lint:` label matches the live lint.
