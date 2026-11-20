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

Files: `mcp/workflow.fabro` (the graph), `mcp/workflow.toml` (run config), `mcp/prompts/`
(the four agent prompts), `steps.py` (every deterministic stage), `classify.sh` (risk
class), `submit.sh` (start a run), `ledger.mjs` (evidence table), `test/classify.test.sh`.

| # | Stage (node) | Kind | What it does |
|---|-------|------|--------------|
| 0 | setup | command | Unpacks the factory code (below), `npm ci`, records the base commit and the PR branch `factory/<spec>-<run>`. Refuses a spec name that already exists on main. |
| 1 | ideate | agent | Reads `CLAUDE.md` and the code, drafts `specs/<name>/{spec.md,tasks.txt,verify.sh}` in a condensed REASONS shape (see deviations). |
| 1b | spec_check | command | Deterministic: the three files exist, ideate wrote nothing outside `specs/<name>/`, and `STRICT=1 verify.sh` **fails on the unimplemented tree** (red-before-green: a gate that passes before the change exists cannot fail). Failure → back to ideate, at most 2 revisions, then abort. |
| 2 | spec_judge → spec_capture | judge + command | Judge reads the spec packet from a file, answers with a last-line JSON verdict that must echo the packet's SPEC-ID. `spec_capture` parses Fabro's recorded reply. `raise` → ideate (≤2), then a hold marker; anything unparseable / absent / wrong id → hold marker. |
| 2b | lock | command | Writes the approved `verify.sh` into git's object store and records its blob id; prints the spec for the human. |
| 3 | approve_spec | **human** | `[A]` approve / `[R]` revise (free-text notes go to ideate) / `[X]` reject. |
| 4 | implement | agent | Works `tasks.txt`; told it may not touch `specs/<name>/`, deps, CI or config; runs the gates itself. Also the target of every fix round. |
| 5 | gates | command | Tamper check, then `npm ci`, `lint`, `typecheck`, `test`, `build`, `STRICT=1 verify.sh`. Red → implement while failures ≤ 3; then the `gates_escalate` human gate (one more round / open PR as hold / abandon). Green → writes the review diff to a file with a DIFF-ID and records the gated tree hash. |
| 6 | conf_judge → conf_capture | judge + command | Same contract as the spec judge, on `/tmp/factory/review.diff`. `raise` → implement (≤2), then hold marker; no usable verdict → hold marker. |
| 7 | classify | command | `classify.sh` on the full-context diff, with `--tampered` when `verify.sh` differs from the locked blob; also holds if the tree changed after the gates passed (a judge or later stage edited files). |
| 8 | open_pr | command | Pushes `factory/<spec>-<run>`, opens or refreshes the PR, creates/applies labels `factory` and `factory:class-<x>`. Refuses to push to anything not under `factory/`. |
| 9 | wait_checks | command | Polls the head commit's check runs until build, lint, test, typecheck and review-hub have all completed (45 min cap), then reads each validator's check and the review-hub report card. Red → prints the failing checks (with Actions log tails and review-hub findings) for the builder. |
| 10 | fix or escalate | agent / **human** | Red → implement while red rounds ≤ 3, re-running 5–9. Then `review_escalate`: *judge is right* (free-text note → implement) / *judge is wrong* (override, logged, verdict stays hold) / *abandon*. A timeout or crash goes straight to the verdict, as hold. |
| 11 | verdict | command | Posts the verdict comment (**would merge** / **hold** + every reason, vote table, class, and a machine-readable `<!-- factory:record {…} -->` line). Never merges. |

**How the factory's own code reaches the sandbox.** A run's sandbox clones only the target
repo. `submit.sh` base64-packs `steps.py` and `classify.sh` into `[run.inputs]` of the
uploaded `workflow.toml`, so they are part of the content-addressed workflow version.
`setup` writes them to `/tmp/factory`; every later deterministic stage re-checks their
sha256 against `inputs.code_sha` and crashes (→ hold path) if an agent touched them.

**How state moves.** Fabro gives a command node one context key on stdin, so the run's
evidence is one JSON object (`fx`) threaded through the deterministic stages, plus flat
`fx_*` keys for edge conditions. Judge verdicts are read from Fabro's recorded
`response.<judge>`, never from a file the run can edit.

### How each rule is enforced

| Rule | Enforced by |
|--|--|
| 1. Gates live here | The workflow, prompts, `steps.py` and `classify.sh` are uploaded from this directory; the code is pinned by sha256 in the version's inputs and re-verified before every deterministic stage. The target repo's copy of anything is never executed by the factory (its `verify.sh` is, but only the blob locked at the human gate). |
| 2. Class by code | `classify.sh` (deterministic awk over `git diff -U1000000`); its output is the only source of `fx.class` and the label. An unclassifiable diff is treated as C. Unit tests: `bash factory/test/classify.test.sh`. |
| 3. Errored ≠ pass | Every forward edge is `outcome=succeeded && fx_x=<good>`; crashes and unknown values take the unconditional edge, which is always a hold marker or abort. Judges must echo the packet id or their verdict is `none`. `decide()` in `steps.py` lists a hold reason for every missing piece of evidence (no report card, older head, missing check, timeout). |
| 4. Models only raise | Judges only run on edges reached after `fx_gates=pass` / `fx_spec_check=pass`; their only outputs are pass (continue), raise (back to the builder, then hold) or none (hold). Nothing routes from a judge to a stage after a red gate. |
| 5. Merge bar > block bar | `decide()` requires every non-neutral validator's report-card row to read `5/5 clear` plus both factory judges `pass`. **Limit:** see deviations — review-hub does not publish dissenting votes on a passing validator. |
| 6. Class C never earns out | `decide()` always holds class C ("human only"); `ledger.mjs` says so. |
| 7. Stage 0 never merges | Nothing in the workflow calls a merge API; `open_pr` refuses non-`factory/` branches; Fabro's `[run.pull_request]` (which can auto-merge) is disabled. The sandbox token *could* merge — see known limits. |

### Where the build differs from the original design (2026-11-20)

- **Spec shape.** `mtgibbs/jig:specs/TEMPLATE.md` is written for the ralph loop (per-task
  gates, mutant corpora, `scripts/new-spec.sh`), none of which exists in the target repo.
  The ideate prompt carries a condensed REASONS outline and the verify.sh rules instead,
  and the spec is the single `specs/<name>/{spec.md,tasks.txt,verify.sh}`.
- **Added `spec_check`** (deterministic, before the spec judge): files present, nothing
  written outside the spec dir, and red-before-green. A model is no longer the only thing
  asking "can verify.sh fail?".
- **A spec judge that keeps raising does not stop the human gate.** After two revisions the
  run still reaches `approve_spec` (the human can read the objection), but the verdict is
  hold whatever happens later.
- **"Judge is wrong" is logged, not a pass.** The override is recorded on the PR (and is
  the eval-feedback signal), but the verdict stays hold: rule 5 says a would-merge needs
  every judge clear, and a human overriding one is by definition not that.
- **Gate exhaustion has a human gate.** The design said "three rounds at most" without
  saying what next; `gates_escalate` offers one more round, open-the-PR-as-hold, or abandon.
- **Rule 5 is only as strong as review-hub's publication.** review-hub renders a passing
  validator as `passed · n/n clear` from the vote count, not the votes
  (`scripts/reviewhub/reporting.py` `_result_text`), so a 3-of-5 or 4-of-5 pass also reads
  "5/5 clear" and neither the report card nor the check run carries the vote vector. The
  factory requires the row to say 5/5 and cannot see dissent behind it. Fixing that is a
  review-hub change (publish the votes, or print `clear`=passing votes). Validators that
  report `neutral` (no matching change) are skipped, not counted as clear or as a hold.
- **Branches.** The PR branch is `factory/<spec>-<last 6 of run id>`; Fabro's
  `fabro/run/<id>` checkpoint branch stays inside the sandbox (`push = false`).

## Risk classes

Computed from the diff by `classify.sh` (a full-context `git diff` against the base, so a
tool file's whole content is visible). The highest class any changed path hits wins.

- **C — never auto-merged.** `package.json`, any lockfile, `Dockerfile*`, `.dockerignore`,
  `.github/**`, `.review-hub.yml`, `.fabro/**`, lint/prettier/ts/vitest/vite config,
  `k8s/**`, `deploy/**`, `charts/**`, any `kustomization.yaml` (RBAC and deploy
  manifests), `specs/validators/**` and any `contract.md` (judge contracts); a deleted test
  file; an added `.skip` / `.only` / `.todo` / `.fails` / `skipIf` / `runIf` / `xit` /
  `xdescribe` in a test file; a test case whose title disappears from its file; and
  `specs/<name>/verify.sh` differing from the blob locked at spec approval.
- **B — mutating surface.** `src/clients/**`, `src/utils/**`, any non-test `src/` path
  containing `auth`, any non-test `src/` line added or removed that mentions `readOnly`
  (the scope gate in `src/tools/index.ts` and friends), any deleted tool file, and any tool
  file in `src/tools/**` that defines a tool with `readOnly: false` or calls exec/SSH
  (`execOnNode`, `child_process`, `spawn(`, bare `exec(`, `*Exec(`, `ssh`).
- **A — everything else.** Docs, tests, specs, tool files whose tools are all read-only.

`classify.sh` exiting non-zero (empty or unparseable diff) is treated as class C and hold.

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

## Running it

```sh
export FABRO_URL=https://fabro.lab.mtgibbs.dev FABRO_DEV_TOKEN=...   # never commit the token
factory/submit.sh --spec pihole-secondary-stats --issue 45 "<idea text>"   # prints the run URL
node factory/ledger.mjs                                               # evidence table from GitHub
bash factory/test/classify.test.sh                                    # classifier unit tests
```

The run stops at `approve_spec`; answer it in the Fabro UI or with
`POST /api/v1/runs/<id>/questions/<qid>/answer {"kind":"selected","option_key":"A"}` (URL-encode
the `#` in the qid). `submit.sh` always sends `auto_approve: false`.

## Known limits of the engine

- Fabro has no GitHub triggers in token mode: runs start from the Fabro UI or API.
- No spend cap; visit and retry limits are the only bound.
- Sandbox CPU/memory limits are not enforced (rootless Docker without cgroups).
- The sandbox holds an all-repo token until a GitHub App replaces it.
- **One run at a time.** The server runs one run at a time, and a run holds its slot while it
  waits at a human gate or for CI (`wait_checks` can take up to 45 min; review-hub alone
  takes ~9). Queue depth is the throughput limit.
- **The token is visible to every stage, agents included.** `GITHUB_TOKEN` is set in the
  sandbox environment so `open_pr`/`wait_checks`/`verdict` can call GitHub; an agent stage
  could use it too (push, comment, even merge). Nothing in the workflow merges, but only a
  scoped GitHub App token (or moving the GitHub-facing stages out of the sandbox) closes
  this. Same for rule 7: it is enforced by what the workflow does, not by what it can do.
- **Context is writable by agents.** Fabro lets an agent's reply set any context key via
  `context_updates`. The deterministic stages overwrite their own keys right after each
  agent stage, but a deliberately adversarial builder could forge `fx` between stages.
  Every `fx` write is in the run's event log, so it is auditable after the fact, not
  prevented.
- **`auto_approve` skips human gates.** The run-create API accepts `args.auto_approve=true`,
  which answers every gate automatically. The workflow cannot detect that from inside the
  sandbox. `submit.sh` never sets it; anything else that creates runs must not either.
- **Fabro's own PR feature is unusable here.** `[run.pull_request]` needs a model with
  structured output to write the PR text (`hot-coder` has none: the run fails with
  `publish_failed`), and it only fires after the run ends, while the factory must open the
  PR mid-run to wait on CI. `open_pr` opens it with the REST API instead.
- **Workflow-defined environments do not work over the API.** `[environments.<id>]` in
  `workflow.toml` is ignored by run creation (`environment_id` must exist in the server
  catalog, else 404). The factory selects the GitOps-managed `gated-docker` environment
  and overrides its image sparsely (`[run.environment.image] docker = "node:20-bookworm"`),
  which does work, so no server change was needed.
- **`[run.checkpoint] exclude_globs` can fail a run (Fabro bug, not filed).** Repro on
  0.421.0-nightly.0: a repo whose `.gitignore` lists `dist/`; a workflow with
  `exclude_globs = ["dist/**"]`; a command stage that runs `mkdir dist && touch dist/x`. That
  stage's checkpoint fails with `checkpoint_failed: git add failed (non-zero exit): The
  following paths are ignored by one of your .gitignore files: dist`, and the run ends
  (`no route is taken`). Same workflow without `exclude_globs`: succeeds (runs
  `01M7WS14MQG7DYTYN3NAXCVKTE` vs `01M7WS1554HQ2VXXYCXPXXE8X5` on factory-trial). Cause:
  plain git, `git add -A -- . ':(glob,exclude)dist/**'` exits 1 when `dist` exists and is
  ignored; `':(glob,exclude)**/node_modules/**'` happens not to trip it, which is why setup's
  `node_modules/` never failed. Fabro should not let an exclude it adds itself fail the
  checkpoint (filter after `git add -A`, or tolerate this specific exit). The factory sets no
  `exclude_globs` and relies on the target's `.gitignore`.

