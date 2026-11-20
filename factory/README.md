# The factory: idea → spec → code → gates → judges → merge, with an earn-out

Status: **Stage 0 (shadow mode)** for one target repo, `mtgibbs/pi-cluster-mcp`.
Engine: Fabro at `https://fabro.lab.mtgibbs.dev` (`clusters/pi-k3s/fabro/`).
Decided 2026-11-20.

## What this is for

One Fabro run takes an idea to a pull request with no human in the loop except one
decision: approving the spec. The long-term goal is that the human also leaves the
review step — the factory merges the feature PR and the release PR itself — but only
after it has *earned* that, class of change by class of change, by measured agreement
with the human's own merge decisions.

Until a class is promoted, the factory runs in **shadow mode**: it does everything,
records "would merge" or "would hold", and a human still merges.

## Rules that do not bend

1. **The factory's own gates live here, not in the target repo.** The workflow, the
   risk classifier and the merge policy are in this directory. A run's sandbox clones
   only the target repo, so a run cannot edit what judges it.
2. **Risk class is decided by code, never by a model.** See `classify.sh`.
3. **An errored check is not a pass.** A gate that crashes, a judge that returns no
   verdict, a check that never reports: all route to "hold".
4. **A model check may only raise.** A judge can turn "would merge" into "hold". No
   judge output can turn a failed deterministic gate into a pass.
5. **Stricter bar to merge than to block.** review-hub blocks on a 3-of-5 majority.
   The factory's "would merge" needs every judge unanimous clear (5 of 5).
6. **Class C never earns out.** See below.
7. **Stage 0 never merges anything.**

## The run

| # | Stage | Kind | What it does |
|---|-------|------|--------------|
| 1 | ideate | agent | Reads the repo and drafts `specs/<name>/{spec.md,tasks.txt,verify.sh}` in the REASONS shape (`mtgibbs/jig:specs/TEMPLATE.md`). |
| 2 | spec judge | judge | Are the outcomes testable? Can `verify.sh` actually fail (does each check assert on something the change creates)? |
| 3 | approve spec | **human** | Approve / revise / reject. The only human decision in a clean run. |
| 4 | implement | agent | Works `tasks.txt`. May not edit `specs/<name>/verify.sh` after approval. |
| 5 | gates | commands | `npm ci`, `lint`, `typecheck`, `test`, `build`, then `STRICT=1 specs/<name>/verify.sh`. Failure → back to 4, three rounds at most. |
| 6 | conformance judge | judge | Does the diff satisfy the spec, and would the tests fail on a wrong implementation? Reads the diff from a file, never from a truncated preview. |
| 7 | classify | command | `classify.sh` → class A, B or C, plus a tamper check (spec's `verify.sh` unchanged since approval). |
| 8 | open PR | command | PR labelled `factory` and `factory:class-<x>`. |
| 9 | wait for checks | command | Waits for CI and review-hub. Collects each validator's vote count. |
| 10 | fix or escalate | agent / **human** | A red check goes back to 4 with the report card. After three rounds: human gate — *judge is right* (note to builder) / *judge is wrong* (override, logged) / *abandon*. |
| 11 | verdict | command | Posts the factory verdict on the PR: **would merge** or **hold**, with the reasons. Stage 0 stops here. |

## Risk classes

Computed from the diff by `classify.sh`. The highest class any changed path hits wins.

- **C — never auto-merged.** `package.json`, `package-lock.json`, `Dockerfile`,
  `.github/**`, `.review-hub.yml`, `.fabro/**`, lint/ts/vitest config, anything that
  deletes or skips a test, any change to RBAC or deploy manifests, any change to a
  judge contract, and any change to `specs/<name>/verify.sh` after spec approval.
- **B — mutating surface.** `src/clients/**`, `src/utils/**`, auth, and any tool file
  in `src/tools/**` that defines a tool with `readOnly: false` or calls exec/SSH.
- **A — everything else.** Docs, tests, specs, tool files whose tools are all read-only.

## Earning out

Evidence is **derived from GitHub**, not hand-kept: every factory PR carries the
`factory` label, its class label, the verdict comment, the check runs with vote
counts, who merged or closed it, and whether a later PR reverted or patched it.
`ledger.mjs` rebuilds the table from that.

| Stage | Feature PR | Release PR | Entered when |
|-------|-----------|------------|--------------|
| 0 shadow | human merges | human merges | now |
| 1 | class A auto-merges | human | 10 consecutive class-A agreements, zero "factory would merge, human rejected" |
| 2 | A and B auto-merge | human | 20 consecutive class-B agreements, same condition |
| 3 | A and B auto-merge | auto-merges if every change in it was auto-merged; post-deploy check; rollback PR on failure | Stage 2 held for 10 releases with no rollback |

**Demotion:** one revert, or one defect traced to an auto-merged PR, sends that class
back to shadow.

**Agreement** means: factory said "would merge" and the human merged it unchanged, or
factory said "hold" and the human did not merge it as-is.

### Preconditions for any promotion (not yet met)

- **A judge on a different model than the builder.** Today both are `hot-coder`;
  their agreement is correlated and counts as one opinion.
- **Every judge has a passing eval score** (`specs/validators/<name>/eval/`).
- **Every judge has a positive control**: a periodic seeded-defect PR it must block.
  A judge that cannot fail is indistinguishable from one that passes.
- **Overrides feed the judges.** Every "judge is wrong" answer becomes a labelled case
  in that validator's `eval/expected.yaml`. The override rate is the earn-out metric.
- **Verdicts are re-run when a judge's contract changes.** A verdict from an old judge
  version is stale, not standing (pi-cluster-mcp PR 32 sat five months on one).

## Known limits of the engine

- Fabro has no GitHub triggers in token mode: runs start from the Fabro UI or API.
- No spend cap; visit and retry limits are the only bound.
- Sandbox CPU/memory limits are not enforced (rootless Docker without cgroups).
- The sandbox holds an all-repo token until a GitHub App replaces it.
