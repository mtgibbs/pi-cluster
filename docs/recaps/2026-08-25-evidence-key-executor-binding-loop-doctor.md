# Recap — one unidentifiable run directory, and the four layers underneath it (2026-08-25 → 2026-08-26)

Five PRs (#197–#201), `e669455 → 4fe1a92`, 29 files, +1752 / −319. The arc started as a naming
complaint about last night's `notes-from-hearing` runs — *"the runs are all hard to know what
feature or task it was against, it's just `qwen-37173`"* — and every fix exposed the layer under
it: the layout was a symptom of a missing key, the key change had no gate, the gate work exposed
a duplicated loop, deleting the duplicate exposed a diagnostic tool that had never been built,
and building it tripped a guard written three PRs earlier.

The through-line, named by Matt mid-arc and worth keeping as the frame:

> *During dogfooding of our harness we have a TON of guards that protect the loop that builds
> the loop and it's twisted up on itself. It should just be easy to define "this is the harness
> I want to use" and those are composable.*

Measured, that reads: **12 harness-about-harness specs against 22 product specs, and 2,572 lines
of gate inspecting the harness against 1,830 protecting actual work.** The tool had grown heavier
than the job.

## 0. Two process failures, before any code

Both worth recording because they cost more than any bug in the arc.

- **Sixty-four commits behind.** The container's checkout was at `8cd0fe2` while `origin/main`
  was at `e669455`. Every edit in the first hour was against superseded files, including a fix
  for a "bug" that had already been fixed. The prompt that caught it was Matt's, mid-turn:
  *"you may also need to look at any open PRs to see if someone tried to change this before you
  go working."* Two branches (`feat/evidence-convention`, `loop/evidence-convention`) turned out
  to be **superseded dead wood** — `main` was strictly ahead of both — and were deleted.
- **A full `/tmp`.** The container's `/tmp` is a 256 MB `tmpfs` and it was at 100%, filled by ~44
  stale 5.5 MB `.so` files from Aug 11–12. Gates that drive real loops in `$TMPDIR` were failing
  on `No space left on device` and reporting it as `rc=128`, which then got **cited as evidence**
  in #197's PR body that certain failures were pre-existing. The conclusion held; the number was
  an artifact. Corrected on the PR.

## 1. The layout: a spec key, not a longer name (#197)

Run artefacts were keyed by PID alone in one flat directory. Five specs over one night left **48
sibling `qwen-<pid>` dirs** whose only link to a feature lived in a *different* store —
`.evidence/status/`, swept on a 1-day fuse while the transcripts it indexes live for 3.
`loop-index.py`'s own docstring already recorded the cost: *"14 of this project's 42 runs had
already lost their status file to it before anyone noticed."*

Now `runs/<spec-slug>/<agent>-<pid>/` and `status/<spec-slug>/…`, matching the key
`judge/<spec>/` and `supervisor/<spec>/` already used.

- **The slug is a DIRECTORY LEVEL, not part of the leaf — and that was Matt's call, not mine.**
  My first proposal folded it into the name (`qwen-asset-ladder-37173`). `loop-index.py` recovers
  the pid with `basename(d).split("-", 1)[1]`, so that would have yielded a "pid" of
  `asset-ladder-37173`, matching no status file. **The index would still have generated, with
  every run silently unattributed.** Nesting changes the path and leaves every parser alone;
  `harness_roots()` already descended exactly one level and needed no change at all.
- **A trap the nesting would have introduced, caught before merge.** The reaper ran
  `-mindepth 1 -maxdepth 1`, correct for a flat store and wrong the moment depth 1 becomes the
  *spec*. A directory's mtime tracks its newest child, so an active feature looks immortal and
  then loses its entire run history the moment it goes quiet. Reproduced against the nested
  layout first: a spec dir stamped 10 days old took **both of its fresh runs** with it. Now
  `-mindepth 2 -maxdepth 2` plus a prune of emptied slug dirs.

## 2. The gate that change should have shipped with (#198)

#197 changed harness behaviour and was proved with throwaway bash fixtures in a tmp dir that
were then deleted — so two real defects it caught had **no durable guard**. That violates a
ratified amendment (`specs/amendments.md`, *"Gates must prove they can fail"*, 2026-08-10) and,
more importantly, the north star Matt set during the arc:

> Every unit of work brings a **spec** (the generative expectation) and an **eval** (the rules
> that must pass). The harness executes; it does not decompose.

`specs/evidence-spec-nesting/` retrofits both, written *generatively* — rebuildable from §9 + §10
rather than describing what already happened. Red-proven against `e669455`: **6 FAIL → 0**, with
the transcript in `specs/evidence-spec-nesting/evidence/2026-08-25-red-before-green.md`.

- **Four checks are labelled invariant guards, not evidence.** AC-3/4/6/10 are green on both
  sides; counting them would be the false-green the amendment exists to prevent. **AC-4 is the
  counter-intuitive one** — it's tempting to assume "the index can read a nested tree" must be
  red beforehand, but `harness_roots()` already handled one level, so the old indexer read a
  nested *qwen* tree correctly.
- **The first draft produced 8 red marks, not 6 — and two were wrong.** AC-3 and AC-6 reused the
  nested fixture's depth-2 lookup, so on a flat tree they failed reporting `leaf 'none'` and a
  self-deletion bug that does not exist at `e669455`. Both were red for *"the layout is flat"*,
  which is AC-1's sentence to speak. **A gate that fails for the wrong reason is worse than one
  that never fails: it teaches the reader to discount it.**

## 3. The twin was a missing parameter (#199)

`scripts/ralph-codex.sh` was **204 lines whose entire reason to exist was one line** — the
executor invocation. Everything else that differed was an env knob (`CODEX_SANDBOX`,
`CODEX_RUN_TIMEOUT`, `RALPH_SHEET` off) plus a watchdog `oc` already provided on the qwen side.

Because it was a file rather than a parameter, three specs had grown rules to keep the copies
identical — `run-regression-guard` AC11, `tasks-ledger` AC13, `ralph-retry-contract` §230
(*"any edit to one is made to the other in the same task"*). **Every harness change cost a second
edit and was gated on the symmetry.**

The tax bought nothing. Nothing invoked the codex builder: `run-loop.sh`'s build phase was
hardcoded to `ralph-qwen.sh`, all three strategies in `scripts/loops/` bind Codex as the
**judge**, `scripts/loops/README.md` doesn't count it among "the loops", and its container is
documented *"Provisioned but not activated."*

The judge phase had already solved this — `ralph-judge.sh` takes `JUDGE_CMD`/`EXECUTOR_CMD` and
`ralph-judge-exec-qwen.sh` is a *binding*, not a fork. The build phase simply never got the same
treatment.

```bash
scripts/run-loop.sh build-codex specs/<feature>   # scripts/loops/build-codex.env — 4 lines
```

- `RALPH_EXEC_CMD`, expanded **unquoted** exactly as the judge expands `EXECUTOR_CMD`, with
  `run_bounded` moved *into* the loop so every attempt is bounded whichever executor it drives.
- **`RALPH_AGENT` must be set per strategy.** With one loop the agent no longer follows from
  which script was invoked, so without it a Codex run is filed as `qwen-<pid>` in `.evidence/`.
- **Not renaming `ralph-qwen.sh` → `ralph-build.sh`**, though that is the right name. The rename
  ripples into **seven** other specs' gates, one of which asserts the README *mentions the
  filename*. Paying seven spec edits for a cosmetic change, in the PR arguing the harness is
  over-gated, would refute the argument. That a paragraph is needed to explain this is itself
  the evidence.

## 4. A spec with a gate and no tool (#200)

`specs/loop-doctor` had a full spec, six tasks, a 254-line gate and fixtures — and no
`scripts/loop-doctor.sh`. The gate reported **12 FAIL / 35 pend** on main and had never been
green.

**The gate was not at fault**, and this recap corrects how it was first raised (*"a spec gating
an unbuilt tool"*). Its own header says why T1's deliverable is a hard FAIL rather than a pend:
*"pend-on-your-own-first-deliverable is what scores 'built nothing' as green."* Those 12 FAILs
were the gate correctly reporting that nothing had been built, for however long nobody looked.

Built: joins the heartbeat and log stores on `run_id` and applies the ordered classifier —
`dead` · `running` · `done` · `watchdog-kill` · `permission-blocked` · `executor-stillborn` ·
`verify-fail` · `no-op` · `unknown`. `dead` outranks every log-shape rule because a killed loop
cannot update its own file. Every row cites the literal marker matched; anything that cannot cite
is `unknown`, never guessed. **51 PASS / 0 pend.**

**On the live corpus, first run:**

```
qwen-19312  loop-model-watch  specs/model-watch  phase=running  fault=dead  heartbeat stale 1193879s
qwen-17812  loop-model-watch  specs/model-watch  phase=running  fault=dead  heartbeat stale 1195372s
```

Two loops whose heartbeats have read `running` for **fourteen days**. `ralph-status.sh` states
the liveness rule in its own header and nothing had ever applied it.

> **The dogfood that failed, and proved the point.** The intended route was to hand
> `specs/loop-doctor` to the loop — spec + eval already existed, which is exactly what the north
> star says the harness should just execute. `oc` is installed and keyed, so a smoke test ran
> first: it **hung and produced nothing**, verified over 8+ minutes. That is
> `fault: executor-stillborn` — one of the nine classes the tool being built exists to name. The
> harness's own diagnostic gap ate the attempt to build the harness's diagnostic. Built directly
> instead.
>
> **The cause, corrected 2026-08-26 (the first diagnosis in this recap was wrong).** It is *not*
> an egress block. The inference plane is healthy from this container: `http://litellm:4000/v1`
> — the exact `baseURL` in `~/.config/opencode/opencode.jsonc` — answers `/v1/models` in **8 ms**
> and completes `hot-coder` in **0.5 s**, streaming and non-streaming both. The original test hit
> the *public* ingress `ai.lab.mtgibbs.dev`, which is unreachable from here, and concluded the
> plane was down. **Testing the wrong URL and generalising from it is the same error as trusting
> a green check that never ran** (§6).
>
> The real stall is inside opencode. `~/.local/share/opencode/log/opencode.log` shows it reach
> `stream providerID=beelink modelID=hot-coder … agent=build` and emit nothing after. So the
> ralph loop **cannot currently be driven from `coding-harness-claude`**, which is why "run a real
> overnight loop against this" (§9) is not something this container can do unaided. Container-level
> fault → report, don't self-patch (`[[feedback_container_config_from_outside]]`).

## 5. My own guard fired at a stranger (#201)

After merging, re-running every gate on `main` — rather than trusting the merges — found
`executor-binding` red:

```
FAIL  AC-7:harness-surface-shrank — 7683 harness lines, was 7465
```

`AC-7` compared **total harness lines** against a frozen number. That does not ask *"did this
change shrink things"*; it asks *"is the harness forever smaller than the day this was written."*
`loop-doctor` added ~250 lines of genuinely new capability and tripped a gate belonging to an
unrelated spec.

Rescoped to what the spec owns — the build loop plus its bindings (300) against the two
duplicated loops they replaced (424) — which stays true regardless of what the harness grows
next.

**This was AC-7's second correction, and the spec keeps both**, because the pattern is the
lesson: draft one measured *gate* lines, a target the change provably could not hit (+132 gate,
−15 twin guard); draft two measured the right direction on the wrong scope. Both read fine in a
PR. Only running them revealed what they actually assert.

## 6. What the gates caught inside the gates

Three of this arc's defects were in the verification, not the code — each passed a casual reading
first.

| Defect | Consequence |
|---|---|
| **`/tmp` is `noexec`** — mock bindings `chmod +x`'d there died instantly on *Permission denied* | `AC-4` ("under 30s") and `AC-5` ("exit 3") were both satisfied by a binding that never ran. **Two of three executing checks were false green.** Fixed by invoking via `bash <path>`, requiring elapsed **≥ 3s** as well as < 30s, and grepping the transcript for the binding's own output |
| **`RALPH_LOG=off` in a fixture** made `log_path` return `/dev/null` | Transcript measured 0 bytes, so the stillborn check fired on any nonzero exit. Turning off the mechanism under test is not isolation |
| **Deleting `C="scripts/ralph-codex.sh"`** left four dangling `"$C"` refs | Under `set -u` that killed `ralph-retry-contract` at line 50 and **six behavioural checks silently stopped running**. The failure count fell **7 → 1** and read as an improvement |

> **A falling failure count is not evidence of progress.** Verify that checks *pass*, not that
> they stop failing — the two are identical in a summary line. Caught by asking why an unrelated
> gate had got *better*, then finding the check names absent rather than passing.

## 7. Defects found in shipped code

- **Every codex run was invisible to `loop-index.py`.** It hardcoded `qwen-*` at all three
  enumeration sites — the dirs were written and nothing ever listed them. The twins were supposed
  to be interchangeable; `run-regression-guard` AC11 existed to stop them drifting and could
  never have caught this, because the drift was *inside one file*.
- **`load_status` dropped `agent` and `spec`**, and three render sites rebuilt names as
  `f"qwen-{pid}"` — printing a path that does not exist for any codex run. Worse than invisible:
  it sends a reader somewhere real-looking and wrong.
- **`ralph-log.sh`'s reaper could `rm -rf` the entire store.** `find X -maxdepth 1 -type d`
  matches `X` itself; it was kept safe only by the `mkdir -p` above it refreshing the root's
  mtime. Guarded with `-mindepth 1`, and `_`-prefixed archive dirs (`_snapshot-*`) excluded.
- **Retention mismatch** (24 h status vs 72 h logs) explained the 35-vs-48 drift Matt spotted in
  the tree. Not fixed — `RALPH_STATUS_KEEP_MIN`'s 1440 default is pinned by
  `evidence-convention` AC-4 and asserted literally by its gate. Filed as `specs/status-retention`.

## 8. Corrections issued during the arc

Recorded because the pattern — confident, wrong, corrected by evidence — recurred four times.

| Claim | Correction |
|---|---|
| *"AC11 `twins-do-not-drift` may be the highest-leverage unbuilt thing in the harness"* | Backwards. It was the highest-leverage thing to **delete** — reached for because of a drift that had just bitten, which AC11 could not have caught |
| *"loop-doctor is a spec gating an unbuilt tool"* | The gate was right; it was correctly reporting "built nothing" |
| *"`tasks-ledger` `rc=128` reproduces on control"* | True but the number was a full-`/tmp` artifact, not a signal |
| AC-7 as written | Wrong twice — see §5 |

## 9. State, and what's open

Gates on `main` after the arc:

| gate | FAIL | note |
|---|---|---|
| `evidence-spec-nesting` · `executor-binding` · `loop-doctor` | **0** | new |
| `evidence-convention` | 2 | pre-existing, unchanged |
| `ralph-retry-contract` · `run-regression-guard` | 6 · 3 | pre-existing, unchanged |
| `tasks-ledger` | 2 | was 3 |
| `judge-loop` | 10 | pre-existing, timing-flaky, untriaged |

Every `scope:out-of-scope-files-untouched` cleared on merge, as designed.

**Open:**

- `specs/status-retention` — `.evidence/status/` is committed to git *and* swept daily by
  default, so the store `loop-index.py` joins on still expires 3× faster than the transcripts it
  indexes. Needs its own spec, eval and red-before-green.
- The `ralph-build.sh` rename, once the cross-gating is smaller.
- `judge-loop`'s 10 failures — untriaged, and its subprocess checks are timing-flaky, which is
  its own problem.
- **`scope:out-of-scope-files-untouched` fires by construction on any branch touching the shared
  harness.** It was red on four gates across this entire arc and was correct to ignore every
  time. A check that is always red on legitimate work trains you to ignore red checks.

**The honest next step is running a real overnight loop against this before building anything
else on top of it.** Five PRs of harness change have been verified against fixtures and one
static corpus; none of it has yet driven a real spec to green.

## Trail

| Piece | Where |
|---|---|
| Layout + reaper depth | #197 · `scripts/ralph-{log,status}.sh` |
| Its spec + eval | #198 · `specs/evidence-spec-nesting/` |
| Executor binding, twin deleted | #199 · `scripts/exec-{qwen,codex}.sh`, `scripts/loops/build-codex.env`, `specs/executor-binding/` |
| The diagnostic | #200 · `scripts/loop-doctor.sh` |
| AC-7 rescoped | #201 |
| Red-before-green records | `specs/{evidence-spec-nesting,executor-binding,loop-doctor}/evidence/` |
