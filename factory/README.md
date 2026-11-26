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
(the six agent prompts: writer, builder and four judge panels), `steps.py` (every deterministic stage), `classify.sh` (risk
class), `submit.sh` (start a run), `ledger.mjs` (evidence table), `harvest.py` (judge verdicts →
candidate eval cases), `evals/` (those cases), `test/classify.test.sh`.

| # | Stage (node) | Kind | What it does |
|---|-------|------|--------------|
| 0 | setup | command | Unpacks the factory code and the idea (below), `npm ci`, records the base commit and the PR branch `factory/<spec>-<run>`. Refuses a spec name that already exists on main. |
| 1 | ideate | agent | Reads `CLAUDE.md` and the code, drafts `specs/<name>/{spec.md,tasks.txt,verify.sh}` in a condensed REASONS shape (see deviations). |
| 1b | spec_check | command | Deterministic: the three files exist, ideate wrote nothing outside `specs/<name>/`, and `STRICT=1 verify.sh` **fails on the unimplemented tree** (red-before-green: a gate that passes before the change exists cannot fail). Failure → back to ideate with the problems in `/tmp/factory/spec-feedback.md`, at most 2 retries (counted in `fx`), then abort. Echoes the review packet into the run log for `harvest.py`. |
| 2a | spec_intent → spec_intent_capture → spec_intent_vote | judge panel + commands | The **spec intent panel** (`spec_intent_votes` / `spec_intent_threshold`): does the spec capture the idea — all of it, nothing it does not ask for, at a size in proportion to the ask? Each vote reads `/tmp/factory/spec-intent-review.md` (INTENT-ID, the idea verbatim, spec.md, tasks.txt — not verify.sh) and may only raise `missing:` / `added:` / `oversized:` reasons. `pass` → `spec_intent_pass` → the rigor panel. `raise` → `spec_intent_raised` → ideate with `/tmp/factory/spec-intent-feedback.md` (≤ `spec_intent_rounds`, default 3; the rigor panel does not run that round), then the human gate marked `raise`. `none` → hold marker → gate. |
| 2b | spec_judge → spec_capture → spec_vote | judge panel + commands | The **spec rigor panel**, `spec_votes` same-model votes (see [Judge panels](#judge-panels)). Each vote: the judge reads the spec packet from a file and answers with a last-line JSON verdict that must echo the packet's SPEC-ID; `spec_capture` parses Fabro's recorded reply; `spec_vote` records it and tallies the round, looping back for another vote until the outcome is decided. `raise` → `spec_raised`, which counts the raise in `fx`, writes the raising voters' objections to `/tmp/factory/spec-feedback.md` and sends the spec back to ideate (≤ `spec_rounds`, default 4); the next raise goes to the human gate marked `raise`. A round with no decision (unparseable / absent / wrong-id votes) → hold marker, no revise. |
| 2c | lock | command | Writes the approved `verify.sh` into git's object store and records its blob id; prints the spec for the human, with every round and vote of both spec panels. |
| 3 | approve_spec | **human** | `[A]` approve / `[F]` send the judges' open objections back / `[X]` reject / **revise = type a note** instead of picking an option. Fabro does not render the freeform edge as a button; a typed answer follows it to `spec_note`, which saves the note for ideate, and the spec is checked and judged again. `[F]` (`spec_forward`) does the same with the objections of whichever spec panel raised last on the current spec version (intent or rigor), verbatim, as the note — no retyping; with nothing open it re-presents the gate. `lock` prints every round and vote of both spec panels first, plus any non-blocking minority objections on a pass (also written to `/tmp/factory/spec-notes.md` for the builder). |
| 4 | implement | agent | Works `tasks.txt`; told it may not touch `specs/<name>/`, deps, CI or config; runs the gates itself. Also the target of every fix round. |
| 5 | gates | command | Tamper check, then `npm ci`, `lint`, `typecheck`, `test`, `build`, `STRICT=1 verify.sh`. Red → implement while failures ≤ 3; then the `gates_escalate` human gate (one more round / open PR as hold / abandon). Green → writes the review diff to a file with a DIFF-ID and records the gated tree hash. |
| 6a | conf_intent → conf_intent_capture → conf_intent_vote | judge panel + commands | The **change intent panel**: does the change do what the idea asked, all of it and nothing more? Reads `/tmp/factory/change-intent-review.md` (CHANGE-ID, the idea verbatim, the diff with `specs/<name>/` left out) — not the spec's fine print. Same reason kinds. `raise` → `conf_intent_raised` → implement with `change-intent-feedback.md` (≤ `conf_intent_rounds`, default 3), then hold marker; `pass` → `conf_intent_pass` → conformance; `none` → hold marker. A raise or none here makes the verdict hold. |
| 6b | conf_judge → conf_capture → conf_vote | judge panel + commands | The **conformance panel**. Same contract as the spec panel (`conf_votes` / `conf_threshold`), on `/tmp/factory/review.diff`. `raise` → `conf_raised` (same counter and feedback file, `build-feedback.md`) → implement (≤ `conf_rounds`, default 4), then hold marker; undecided round → hold marker. A pass with minority raises puts those objections in the verdict comment as non-blocking notes. |
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

**How the idea is kept verbatim.** The intent panels judge against the idea exactly as it was
submitted, so it must not drift. `submit.sh` packs the idea text, byte for byte, into
`[run.inputs]` as `idea_b64`, and `code_sha` is `sha256(steps.py) + sha256(classify.sh) +
sha256(idea)`. `setup` writes it to `/tmp/factory/idea.md`; the same sha256 line every
deterministic stage already runs now hashes `idea.md` too, so an agent that edits the idea
stops the run exactly as one that edits `steps.py` would. The intent packet ids (INTENT-ID,
CHANGE-ID) hash the idea together with the spec or diff, so a vote cast on an older idea or
packet is `none`, and `vote` refuses a round whose packet file changed between votes (decided
`none`, never pass).

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
| 4. Models only raise | Judges only run on edges reached after `fx_gates=pass` / `fx_spec_check=pass`; their only outputs are pass (continue), raise (back to the builder, then hold) or none (hold). Nothing routes from a judge to a stage after a red gate. The rigor and conformance panels are reached only through `*_intent_pass`, whose forward edge tests `fx_<kind>_judge=pass`. |
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
- **A spec judge that keeps raising does not stop the human gate.** After `spec_rounds` revisions the
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

### Learning from gate results

Every gate result is evidence about some part of the factory. The loops below say where
each kind goes. Three rules hold for all of them: a model's output can only **raise**
(never clear a hold), **nothing that is judged writes what judges it** (cases, prompts and
contracts change only through a pull request a person reviews), and nothing merges on its
own in Stage 0.

| Signal | Feeds | How | State |
|---|---|---|---|
| Spec intent panel raises | the spec writer, same run | `spec_intent_raised` → `spec-intent-feedback.md` → ideate, `spec_intent_rounds` rounds; outranks rigor feedback | **built**, not yet exercised live |
| Spec rigor panel raises | the spec writer, same run | `spec_raised` → feedback file (per raising voter) → ideate, `spec_rounds` rounds | **built** |
| Human types a note at a gate, or picks `[F]` | the spec writer / builder, same run | `spec_note` / `spec_forward` / `build_note` | **built** (`[F]` not yet exercised live) |
| Change intent panel raises | the builder, same run | `conf_intent_raised` → `change-intent-feedback.md` → implement, `conf_intent_rounds` rounds | **built**, not yet exercised |
| Conformance judge panel raises | the builder, same run | `conf_raised` → feedback file → implement, `conf_rounds` rounds | **built**, not yet exercised |
| Every intent-panel vote | the intent panels' eval sets | `harvest.py` writes `evals/spec-intent/cases/` and `evals/change-intent/cases/` (`<run>-r<R>-v<V>.json`, packet includes the idea verbatim, `label: null`) | **built** (collection) |
| Every spec-judge vote + what the human did next | the spec judge's eval set | `harvest.py <run>` writes one case per vote, `evals/spec-judge/cases/<run>-r<round>-v<vote>.json` (packet, verdict, reasons, the round's outcome, human action, `label: null`; pre-panel runs keep `<run>-r<n>.json`); a person sets the label in the PR | **built** (collection). Scoring a judge against the set is not built |
| A lesson that recurs across cases | the ideate prompt | A person folds it into `prompts/ideate.md` ("Pin the assertions…" came from run 2's objections) | **manual**. Mining recurring objections and proposing the prompt PR is deferred until there are enough cases to tell a pattern from one run |
| "Judge is wrong" at `review_escalate` | that validator's `eval/expected.yaml` in review-hub | not built; the override is logged on the PR today | deferred (review-hub change) |
| Human merges/closes vs. the factory verdict | the earn-out ladder | `ledger.mjs` | built, no data yet |

The revise loop has a positive control (`test/loop-control.py`): the real graph with ideate
and the judges swapped for fixed stand-ins, the rigor judge always raising and the intent
judges always passing (`--intent-raise` makes the spec intent stand-in always raise instead). Observed on
2026-11-20 with the single judge and a 2-round cap (run `01M7X7SB1VMEYNKQCF4DWKKM90`): raise →
ideate twice, third raise → human gate, typed note → `spec_note` → ideate with both the
objections and the note in its input, fourth raise → straight to the gate. **Not yet re-run
since the judge panels landed**; the expected stage list for the vote loop is in the
script's docstring (`--panel "spec_votes=3 spec_threshold=2 spec_rounds=2"`: two votes per
round, the third never cast). **Neither control has been run since the intent panels landed**;
the intent-raise control is `--intent-raise` with `--panel "spec_intent_rounds=2"` (expected
stages in the docstring: the rigor panel is never visited). Re-run both after any change to
the spec half of the graph.
`test/panel.test.py` covers the tally, the vote/raised/forward/verdict stages and the
graph's shape locally, with no server.

A judge that runs out of time is "no verdict", which holds. Run 3's spec judge spent 35
minutes building a counter-example and timed out; the prompt now limits it to reading.
That trades away the kind of evidence run 2's judge produced (a wrong implementation that
really passed 12/12) for a judge that finishes.

What the first cases already show: runs 1 and 2 drafted near-identical specs for issue #45
with the same hole (test titles pinned, assertions not; the builder writes the tests). The
same judge, same model, passed run 1 and raised run 2. **One spec-judge vote is a coin
with a bias, not a gate** — it needs several votes or a second model before its `pass`
means anything, which is the same conclusion review-hub reached for its validators. The
judge panels below are the several-votes half of that; the second-model half is not built.

The structural fix the judge's objection points at, not built: have the spec ship the test
file itself, frozen with `verify.sh` at approval, so the builder writes only `src/`. Then
"the implementation authors its own tests" stops being possible instead of being judged.

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
factory/harvest.py <run-id>                                           # judge verdicts → evals/spec-judge/cases/ (then PR)
bash factory/test/classify.test.sh                                    # classifier unit tests
python3 factory/test/panel.test.py                                    # judge-panel tally + stage + graph-shape tests (local)
factory/submit.sh --dry-run --profile hybrid "<idea>"                 # resolve + validate profile and panels; contacts nothing
python3 factory/test/loop-control.py /tmp/loopctl && FACTORY_WORKFLOW_DIR=/tmp/loopctl factory/submit.sh --panel "spec_votes=3 spec_threshold=2 spec_rounds=2" --spec loop-control "CONTROL"   # no-model positive control for the vote + revise loops; never Approve its gate
python3 factory/test/loop-control.py /tmp/loopctl-intent --intent-raise && FACTORY_WORKFLOW_DIR=/tmp/loopctl-intent factory/submit.sh --panel "spec_intent_rounds=2" --spec loop-control-intent "CONTROL"   # intent panel always raises; rigor never runs
```

The run stops at `approve_spec`; answer it in the Fabro UI or with
`POST /api/v1/runs/<id>/questions/<qid>/answer {"kind":"selected","option_key":"A"}` (URL-encode
the `#` in the qid). To revise instead, type a note in the UI or send `{"kind":"text","text":"…"}`.
`submit.sh` always sends `auto_approve: false`.

## Known limits of the engine

- Fabro has no GitHub triggers in token mode: runs start from the Fabro UI or API.
- **`context.internal.node_visit_count` does not work in edge conditions.** The first build
  bounded its loops with `... && context.internal.node_visit_count < 3`; on the live server
  that was false on the first visit, so run 2's raised spec skipped the revise loop without
  any error. Loop bounds are now counters in `fx`, compared numerically (`fx_gate_fails <= 3`
  style conditions were verified with a no-model probe run).
- **A human gate's freeform edge is not shown as an option.** The gate lists only the
  labelled choices plus "allow freeform"; typed text takes the `freeform=true` edge and
  lands in `human.gate.text`, readable by the next stage via `stdin_source`.
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


## Model profiles: who writes, builds and judges

`factory/models.toml` names a model for each of the four model-driven roles and groups them
into profiles. Pick one per run:

```bash
factory/submit.sh --profile hybrid --issue 45 "<idea>"     # default: all-local
factory/report.py                                          # time, tokens and cost per run, by role
```

| Profile | writer | spec intent | spec rigor | builder | change intent | conformance |
|---|---|---|---|---|---|---|
| `all-local` | hot-coder | hot-coder (1/1) | hot-coder (1/1) | hot-coder | hot-coder (1/1) | hot-coder (1/1) |
| `hybrid` | hot-coder | claude-haiku (5/3) | claude-haiku (5/3) | hot-coder | claude-haiku (5/3) | claude-sonnet (3/2) |
| `hybrid-gemini` | hot-coder | gemini-flash-lite (5/3) | claude-haiku (5/3) | hot-coder | gemini-flash-lite (5/3) | claude-sonnet (3/2) |
| `cloud-builder` | claude-haiku | hot-coder (1/1) | hot-coder (1/1) | claude-haiku | hot-coder (1/1) | hot-coder (1/1) |
| `all-cloud` | claude-sonnet | claude-haiku (5/3) | claude-haiku (5/3) | claude-haiku | claude-haiku (5/3) | claude-sonnet (3/2) |

Judges are (votes/threshold). How it works: `submit.sh` writes the profile into `[run.inputs]`
(`m_writer`, `m_spec_intent`, `m_spec_judge`, `m_builder`, `m_conf_intent`, `m_conf_judge`,
`profile`, plus the panel keys `<kind>_votes`, `<kind>_threshold`, `<kind>_rounds` for each of
`spec_intent`, `spec`, `conf_intent`, `conf`), and the graph's `model_stylesheet` reads them, one
`#node { model: ... }` rule per role. The profile is therefore part of the uploaded workflow
version, is logged by `setup`, and is written into the verdict record on the PR.

`report.py` reads Fabro's recorded stages (model used, wall time, tokens) and the run's final
state (verdict, gate fails, CI red rounds, judge raises) and prices the tokens from
`models.toml`. That is the comparison: same idea, different profile, look at time, cost and
outcome side by side. Its dollar figure is an estimate with a no-cache worst case beside it;
LiteLLM's spend log for Fabro's key is the bill of record.

Proven with a no-model control run (`01M89Q3E58YXD65BP3TS47MAFF`, profile `hybrid`): the
spec-judge stage was routed to `claude-haiku`, failed because the server could not call it yet,
and the run held at the human gate with no verdict — the stylesheet takes effect and a model
that cannot answer is a hold, not a pass.

A hosted profile needs pi-cluster PR #283 merged: it lists `claude-haiku` and `claude-sonnet`
in Fabro's `settings.toml` (with pricing, so the portal's Usage tab shows cost) and switches
Fabro to its own LiteLLM key (alias `fabro`: those two plus `hot-coder`, $100 per 30 days).
`hot-coder` has no price in LiteLLM, so `all-local` runs do not draw on that budget.

Not covered: the review-hub panels. review-hub has one `JUDGE_MODEL` for every repo and no
per-PR switch, so the "tiny judges" cannot follow a factory profile until review-hub grows one.
Unverified: whether prompt caching survives the LiteLLM hop to Anthropic. An agent stage
re-sends its history every turn (run 4's builder read 7.3M cached tokens), so this decides
whether a Sonnet conformance pass costs about $0.80 or about $9.


## Judge panels

A live run showed the problem with one judge call per round: a strict judge (claude-haiku)
found something new every round, the 2-round cap was hit, and the human retyped the
judge's objections as a revise note five times. One sample is also not a consensus.

**Four panels, in this order:** spec **intent** → spec **rigor** → (human gate, build, gates) →
change **intent** → **conformance**. Each later panel runs only after the one before it passed
on the same spec version / the same change.

| Panel (kind, judge node) | Question | Reads | May raise | May NOT raise |
|---|---|---|---|---|
| spec intent (`spec_intent`) | Does the spec capture the idea — all of it, nothing it does not ask for, at a size in proportion to the ask? | the idea verbatim, `spec.md`, `tasks.txt`; a glance at the repo for terms | `missing:` an ask the spec does not deliver · `added:` behaviour, fields, exports, config or machinery the idea did not ask for and does not strictly need · `oversized:` what to cut | test rigor, verify.sh, code correctness |
| spec rigor (`spec`, node `spec_judge`) | Is the spec testable, and can `verify.sh` fail on a wrong implementation, checked against the real code? | the spec packet incl. `verify.sh`, the cited source | untestable criteria, a verify.sh that cannot fail | new fields, behaviour or scope; it says "define X or remove it" and prefers the fix that makes the spec smaller |
| change intent (`conf_intent`) | Does the change do what the idea asked, all of it and nothing more? | the idea verbatim, the diff (spec dir left out) | `missing:` · `added:` · `oversized:` | test strength, style, the spec's fine print |
| conformance (`conf`, node `conf_judge`) | Does the diff meet the approved spec, would its tests catch a wrong change, does it fail closed? | the review diff, the spec, source | unmet criteria, weak tests, fail-open, secrets, writes | anything the spec does not require |

Why the intent panels exist: a `hybrid` run on a small idea ("poll both Pi-hole instances, sum
totals, show per-instance health") did not converge in 6 rounds. The single spec judge asked
three questions at once; from round 4 it asked where a `summaryStatus` came from, the writer
answered by inventing an `ftlStatus` mechanism nobody asked for, and the spec grew to ~600
lines. Nothing compared the spec with the ORIGINAL idea each round, so "close every objection"
beat "build what was asked". Now an intent panel compares every revision with the idea itself
(never with earlier objections — it reads its own earlier feedback only to avoid repeating
itself), its raises outrank the rigor panel's in the writer's and builder's prompts, and the
rigor/conformance prompts may no longer ask for new scope. Writer and builder are told that
the smallest spec/change that delivers the idea is the goal, and that closing an objection by
removing the thing objected to beats adding machinery.

An intent vote must tag every raise reason `missing:`, `added:` or `oversized:`. `capture`
drops untagged reasons (logged), and a raise left with none is a `none` vote: it can hold,
never pass, and it cannot smuggle a rigor objection into the intent loop. `fx.judge_log`
records each intent vote's reason kinds; `report.py` sums them.

**What a vote is.** Each judge role (`spec_intent`, `spec_judge`, `conf_intent`, `conf_judge`) is a panel of N votes from
the role's one model. A vote is one fresh agent visit to the judge node, parsed by
`*_capture` into pass / raise / none, then recorded by `*_vote` in `fx.judge_log` with its
round and vote index. The graph is a counted loop: judge → capture → vote → judge while
`fx_<kind>_panel=more`. A sequential loop rather than Fabro's parallel fan-out
(`shape=component` / `for_each`) because N is per-profile data, the loop can stop early,
the tally stays one deterministic step, and the existing capture contract (one
`response.<judge>` at a time) is unchanged.

**The rule** (`tally()` in `steps.py`, deterministic):

- `raise` when raise-votes ≥ threshold;
- `pass` only when *actual* pass-votes ≥ N − threshold + 1 — a `none` vote (no reply,
  unparseable, wrong packet id, timeout) never counts as a pass;
- otherwise `none` → hold, as before.

Voting stops as soon as the outcome is decided (3 raises of 5 skip the last two votes; so
do 3 nones, since neither bar can then be reached). The two bars cannot both be met.
N=1, threshold=1 is exactly the old single judge.

**Independence.** Votes of one round cannot see each other: judges run with
`fidelity="truncate"` (Fabro's preamble is the goal and run id only: no stage outputs, no
context values; `response.*` keys are never in a preamble), no `thread_id` (no shared
session), and a vote's parsed reply exists in `/tmp/factory` only between its capture and
vote stages (`vote` deletes it). The feedback files a judge is told to read
(`spec-intent-feedback.md`, `spec-feedback.md`, `change-intent-feedback.md`,
`build-feedback.md`) are rewritten only by `spec_check`, `gates` and `*_raised` — between
rounds — so each voter sees earlier rounds' objections, never its own round's. The packet a
round reads is hashed when written; `vote` decides the round `none` if it changed between votes. Not proven: that a revisited Fabro agent node starts a fresh session without a
`thread_id` (Fabro's docs do not say), and a judge that broke its "do not modify any file"
instruction could leave a note for the next voter somewhere outside the checked packet.

**Feedback on a raise.** All objections from that round's raising voters, verbatim, grouped
per voter, under a header "k of N voters raised" (plus how many were cast when voting
stopped early). On a **pass with minority raises**, those objections are kept as
non-blocking notes: spec panels (intent and rigor) → printed by `lock` for the human and
written to `/tmp/factory/spec-notes.md`, which the builder's prompt reads; change intent and
conformance panels → a section of the verdict comment.

**`[F]` at the spec gate** forwards the objections of whichever spec panel raised last on the
current spec version — the rigor round if it ran and had raising voters, otherwise the intent
round — to the writer as the revise note (what typing them used to do). `spec_check` records
where each panel's rounds for the current version begin (`fx.spec_cycle`), so a stale raise on
an older version is never reopened. The freeform note is still there.
`review_escalate` has no `[F]`: its objections come from CI and review-hub, not a panel.

**Settings** (`models.toml`): `<kind>_votes`, `<kind>_threshold` per profile for each kind
`spec_intent`, `spec`, `conf_intent`, `conf` (default 1/1); `[loop] spec_rounds`, `conf_rounds`
(default 4) and `spec_intent_rounds`, `conf_intent_rounds` (default 3) cap each panel's
automatic revise rounds, counted separately. `submit.sh --panel "k=v ..."` overrides them for
one run. All are validated (1 ≤ threshold ≤ votes ≤ 15, rounds 0..10) by `steps.py`'s own
`parse_panel`, in `submit.sh` and again in `setup`; `submit.sh` also refuses votes × (rounds + 4)
above any panel node's `max_visits` (60), and the summed revise caps of the spec side (build
side) above `ideate`/`spec_check` (`implement`/`gates`) `max_visits`, so no loop can silently
run out of visits.

**Records.** `fx.judge_log` holds every vote (judge = panel kind, round, vote, of, verdict,
packet, reasons, why; intent votes also `kinds`); `fx.<kind>_tallies` every decided round; the
verdict record on the PR has `panel` (the settings), `panels` (per-round tallies of all four)
and `spec_intent_judge` / `conf_intent_judge` beside the old verdicts, and the comment lists
all four panels' tallies. `decide()` holds unless all four panels passed. `report.py` prints
model, time, visits, tokens, cost, votes and tallies for all six roles and counts intent raises
and their reason kinds; old runs without intent stages report as before (`profile_of` ignores
roles a run never used). `harvest.py` writes one eval case per vote: rigor cases where they
always were, intent cases under `evals/spec-intent/` and `evals/change-intent/`.

**Cost.** A judge's cost and time scale with the votes actually cast: a 5/3 Haiku spec panel
is 3–5 Haiku calls per round, a 3/2 Sonnet conformance panel 2–3 Sonnet calls per round. With
the 4-round cap a spec that never satisfies the panel costs up to 25 votes before the human
sees it. An intent vote is much cheaper than a rigor vote: it reads two documents (the idea and
the spec, or the idea and the diff) and is told not to crawl the repo. A 5/3 Haiku intent panel
adds 3–5 short calls per spec version, and up to 20 with its 3-round cap; an intent raise also
saves that round's rigor votes, since rigor does not run. That is why `all-local` and `cloud-builder` keep 1 vote: hot-coder is slow (one
conformance pass took 21 minutes) and the Beelink serves one request at a time.

**Not done in this version.** No cross-model blended vote (a panel is one model); no merging,
deduping or summarising of objections, within a panel or across intent and rigor (no model
touches them between judge and author); votes are sequential, not parallel; `review_escalate`
has no forward option. The intent panels have no eval score yet (cases are only collected) and
have not run live.
