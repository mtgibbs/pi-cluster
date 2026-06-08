# gate-regression — a single-concern validator

One specialist in the roster. **It checks exactly one thing:** does a PR diff to
`pi-cluster-mcp` *weaken a security gate*? Nothing else — not style, not perf, not
general bugs. A narrow validator beats a generalist because it can be prompted,
evaluated, and tuned for this one job.

## The gates it protects (from the real code)

| gate | where | weakening looks like |
|---|---|---|
| `triggerable-label` | `whitelist.ts` `isCronjobTriggerable` + its call in `backups.ts` | `=== 'true'` → truthy/`!== 'false'`/`true`; or the check is no longer *called* |
| `guard-a` | `backups.ts` active-run refusal | the `throw AlreadyRunningError` deleted or turned into a warn-and-proceed |
| `deploy-allowlist` | `whitelist.ts` `isDeploymentAllowed` | bypasses the Set membership check |
| `fail-closed` | `errors.ts` sentinels | a sentinel stops *stopping* the action |

## The eval set (`eval/expected.yaml`)

13 labelled diffs grounded in the real files. Positive class = `{fail, flag}`.

- **5 PASS** — safe changes it must NOT flag, incl. the trap
  `relocate-check-still-enforced` (the gate moves into a helper; a naive diff-reader
  sees the `throw` "deleted" and cries regression — the validator must see it's still enforced).
- **7 FAIL** — real weakenings across all three gates (default-permissive, return-true,
  loosen-value, remove-label-check, remove/neuter Guard A, allowlist-bypass).
- **1 FLAG** — `rename-label-constant`: not a weakening alone, but silently breaks the
  contract unless manifests change in lockstep → escalate.

The validator reasons about the **change**, not the final file. A check deleted *here*
but re-added *there* is not a regression. It judges **all changed gate-relevant files
together** (cross-file context) so a gate *defined* in `whitelist.ts` and *enforced* in
`backups.ts` is seen as one wired-up change, not a flag.

## Vote rule — majority of 5

Each PR is judged `--repeat 5`; the verdict is **strict majority** (block on ≥3 escalating
votes). Measured on this eval the gap is clean: a real weakening is unanimous (5/5), while
a safe-but-subtle change the model occasionally misreads tops out at 2/5. Majority sits in
that gap — every weakening blocks, no safe change false-blocks. (Score the eval at `--repeat 5`
to reflect this; reps=1 is a coin-flip on the borderline cases.)

## Scoring

```bash
.venv/bin/python scripts/reviewhub/validators/gate_regression.py \
  --eval --backend litellm --repeat 5 --out /tmp/gr.json --score
```
Bar: catch every weakening (recall 1.00) with no false-blocks on the safe set
(precision 1.00), naming the right gate. **Achieved: 1.00 / 1.00 at reps=5, majority vote.**

## Status

Built + eval'd (1.00/1.00) + registered in the roster. Verified live against a real PR
(`pi-cluster-mcp#32`, the trigger_cronjob PR) → PASS once cross-file context confirmed the
gate is wired. Goes live on `pi-cluster-mcp` PRs once that repo ships its `.review-hub.yml`.
