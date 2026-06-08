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
but re-added *there* is not a regression.

## Scoring

```bash
.venv/bin/python specs/validators/gate-regression/eval/score.py              # set summary
.venv/bin/python specs/validators/gate-regression/eval/score.py --judge out.json
```
Bar: catch every weakening (recall 1.00) with no false-blocks on the safe set
(precision 1.00), naming the right gate.

## Status

Eval set built (the ruler). Next: the validator harness (judge a diff against this one
concern, multi-vote, fail-safe) + register it in the roster so the receiver runs it on
`pi-cluster-mcp` PRs and posts its own `gate-regression` check.
