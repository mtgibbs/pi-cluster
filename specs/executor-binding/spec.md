# Spec: the build phase takes an executor binding, like the judge phase already does

- **Status:** Draft v0.1
- **Owner:** mtgibbs
- **Constitution:** `specs/constitution.md` (+ `/CLAUDE.md` Core Mandates)
- **Touches:** `scripts/ralph-qwen.sh`, new `scripts/exec-{qwen,codex}.sh`,
  `scripts/run-loop.sh`, `scripts/loops/*.env`, **deletes** `scripts/ralph-codex.sh`;
  strikes the twin clauses in `specs/{run-regression-guard,tasks-ledger,ralph-retry-contract}`

> **This spec must leave the harness SMALLER than it found it.** The harness now carries 12
> specs and **2,572 lines of gate inspecting itself**, against 22 product specs and 1,830 lines
> of gate protecting actual work. The tool has grown heavier than the job, and a change that
> adds a thirteenth self-inspecting spec without removing more than it adds is making the
> problem worse while claiming to fix it. Shrinking is therefore an acceptance criterion (AC-7),
> not an aspiration — though see AC-7's own note: it took two corrections to state that in a way
> that measures this change rather than penalising every change that comes after.

---

## 1. Why · [R — Requirements]

`scripts/ralph-codex.sh` is 204 lines whose entire reason to exist is **one line** — the
executor invocation. `ralph-qwen.sh` calls `oc run`; `ralph-codex.sh` calls `codex exec`.
Everything else that differs is an environment knob (`CODEX_SANDBOX`, `CODEX_RUN_TIMEOUT`,
`RALPH_SHEET` defaulting off) plus a watchdog that `oc` already provides on the qwen side.

Because it is a whole file rather than a parameter, three specs have grown rules to keep the
two copies identical — `run-regression-guard` AC11, `tasks-ledger` AC13, and
`ralph-retry-contract` §230 ("any edit to one is made to the other in the same task"). Every
harness change now costs a second edit and is gated on the symmetry.

That tax buys nothing. **Nothing invokes the codex builder:** `run-loop.sh`'s `build` phase is
hardcoded to `ralph-qwen.sh`, all three strategies in `scripts/loops/` bind Codex as the
**judge** (`JUDGE_CMD=ralph-judge-codex.sh`) with qwen as executor, `scripts/loops/README.md`
does not count it among "the loops", and its container is documented *"Provisioned but not
activated."*

The judge phase already solved this. `ralph-judge.sh` takes `JUDGE_CMD` and `EXECUTOR_CMD`;
`scripts/ralph-judge-exec-qwen.sh` is a binding, not a fork of the judge loop. The build phase
simply never got the same treatment — and a duplicated 204-line file is what a missing
parameter looks like.

## 2. Outcomes (Definition of Done) · [R — Requirements]

1. Choosing an executor is a **binding**, not a file: one build loop, swappable executor.
2. A new executor costs one small `exec-*.sh` plus a strategy `.env` — no loop is copied.
3. `scripts/ralph-codex.sh` is gone, and with it every rule that existed to keep it in sync.
4. The executor layer is **smaller** than the duplicated loops it replaces.

## 3. Entities · [E — Entities]

**executor binding** — an executable taking one argument, the prompt, and writing the
executor's combined stdout+stderr to *its own* stdout. It knows nothing of tasks, attempts,
gates or evidence; the loop owns all of that.

```
scripts/exec-qwen.sh   "$prompt"     # oc run --dir "$ROOT"
scripts/exec-codex.sh  "$prompt"     # codex exec --cd "$ROOT" --sandbox "$CODEX_SANDBOX"
```

Contract, exactly mirroring `EXECUTOR_CMD` in `ralph-judge.sh` §3:

| | |
|---|---|
| invoked as | `$RALPH_EXEC_CMD "<prompt>"`, expanded **unquoted** — so a binding may carry arguments (`bash /path/x.sh`), exactly as `ralph-judge.sh` expands `$EXECUTOR_CMD` |
| reads | `ROOT` from the environment |
| writes | transcript to stdout |
| exit 0 | the executor ran (it does **not** mean the work is correct) |
| must not | commit, read `tasks.txt`, or touch `.evidence/` |

**strategy** — unchanged: `scripts/loops/<name>.env`, declaring `STRATEGY_PHASES` plus
bindings. Gains `RALPH_EXEC_CMD` as a build-phase binding alongside the judge's existing pair.

## 4. Approach · [A — Approach]

Replace the build loop's hardcoded `oc run` with `$RALPH_EXEC_CMD` under the loop's own
watchdog, and ship the two executors as bindings. `run-loop.sh`'s `build` phase gains `BUILD_CMD` the way `judge` already
has `JUDGE_CMD`. Then delete `ralph-codex.sh` and every rule that guarded its symmetry.

The watchdog moves **into the loop**. Today `oc` carries it for qwen and `ralph-codex.sh`
hand-rolls `run_codex()` for codex — so a third executor would have to bring its own, or
silently have none. `ralph-judge.sh` already contains the portable `run_bounded()` (macOS has no
coreutils `timeout`); reuse that shape so the bound is a property of the loop, not a favour each
binding remembers to do.

**Rejected: keep both loops and generate one from the other.** It removes the drift while
keeping the duplication, and adds a generator to guard.

**Rejected: delete `ralph-codex.sh` and stop there.** It removes today's tax but leaves the
missing parameter, so the next executor recreates the file. The point is that adding an executor
must stop being a copy.

## 5. Scope · [S — Structure: boundary]

### In scope
- `scripts/ralph-qwen.sh` — executor call becomes a binding (the file keeps its name; see below)
- new `scripts/exec-qwen.sh`, `scripts/exec-codex.sh`
- `scripts/run-loop.sh` — `BUILD_CMD` binding for the `build` phase
- `scripts/loops/` — `build-codex.env`; existing strategies keep working untouched
- **delete** `scripts/ralph-codex.sh`
- strike AC11 (`run-regression-guard`), AC13 (`tasks-ledger`), §230 (`ralph-retry-contract`)
  and the "deliberate twins" prose in all three

### Out of scope
- **Renaming `ralph-qwen.sh` → `ralph-build.sh`.** It is the right name — the file is the build
  loop, not the qwen loop — and it is deferred anyway, because the rename ripples into **seven**
  other specs' gates (`loop-doctor`, `codesheet-docs`, `evidence-convention`, `tasks-ledger`,
  `run-regression-guard`, `ralph-retry-contract`, `evidence-spec-nesting`), one of which gates on
  the README *mentioning the filename*. Paying seven spec edits for a cosmetic change, in the
  same PR that argues the harness is over-gated, would refute the argument. The seam is the
  substance. Rename once the cross-gating is smaller — and note that needing this paragraph is
  itself the evidence.
- The judge phase. It is already correct and is the model being copied.
- `ralph-retry.sh`, `ralph-ledger.sh`, `supervise.sh` behaviour — call sites move, semantics do not.
- `RALPH_STATUS_KEEP_MIN`'s 1440 default (`specs/status-retention`).
- Any behavioural change to the build loop. This is a seam, not a feature.

## 6. Prior decisions / facts the implementer must know · [S — Structure]

- `scripts/loops/README.md` already states the contract this extends: *"a strategy file may ONLY
  declare `STRATEGY_DESC`/`STRATEGY_PHASES` and export env knobs the loop scripts already
  accept."* `RALPH_EXEC_CMD` becomes such a knob; no strategy gains logic.
- `ralph-judge.sh:67` carries `run_bounded <seconds> <cmd...>` — returns 124 on timeout, else the
  command's code. Copy that shape; do not add a dependency on `timeout(1)`.
- **bash 3.2 is the floor** (macOS ships it; `docs/AGENTS.md`). No `mapfile`, no `${x^^}`, and an
  empty array expanded under `set -u` is an error — that exact defect was #196's D3.
- `ralph-qwen.sh` is referenced by `run-loop.sh`, `scripts/harness`, `supervise.sh`,
  `scripts/README.md` and seven specs' gates — which is why §5 defers the rename.
- The stillborn-executor check (`_rc != 0 && _sz < 512` → abort) must survive the seam. It is what
  stops a broken container from reporting 3/3 tasks green — observed 2026-07-22.

## 7. Norms · [N — Norms]

- Bindings are **thin**: exec the tool, pass the prompt, inherit stdout. No retry, no gate, no
  evidence, no cleverness. If a binding grows a decision, it belongs in the loop.
- Keep the loop's comment discipline: every non-obvious line says *why*, anchored to the failure
  that taught it. Comments explaining the twin rule are deleted along with the rule.
- One `git mv` for the rename so history follows the file.

## 8. Safeguards · [S — Safeguards]

- **SG-1 — no executor name may appear in the build loop.** The moment `ralph-build.sh` says
  `oc` or `codex`, the seam has leaked and the next executor forks the file again. → AC-2.
- **SG-2 — every attempt stays bounded.** A binding that hangs must be killed by the loop, not
  trusted to bound itself. → AC-4.
- **SG-3 — the stillborn-executor abort survives.** A binding that dies in under a second with a
  stub transcript must still abort the run, never fall through to verify. → AC-5.
- **SG-4 — no gate may reference a per-executor builder.** Otherwise deleting one turns a
  correct cleanup red — the defect this spec exists to remove. → AC-6.

## 9. Task breakdown · [O — Operations]

- **T1** — add `run_bounded`; replace the `oc run` line with the bounded `$RALPH_EXEC_CMD` call;
  add `scripts/exec-qwen.sh` as the default binding. No behaviour change for an unset
  `RALPH_EXEC_CMD`.
- **T2** — `scripts/exec-codex.sh` + `scripts/loops/build-codex.env`; `BUILD_CMD` in
  `run-loop.sh`; update `scripts/harness`, `supervise.sh`, `scripts/README.md` and the skill.
- **T3** — delete `scripts/ralph-codex.sh`; strike AC11, AC13, §230 and the twin prose from the
  three specs and their gates.

## 10. Acceptance criteria (EARS) · [O — Operations made testable]

- **AC-1** When `RALPH_EXEC_CMD` is unset, the build loop shall invoke the qwen binding, so an
  existing invocation behaves exactly as before.
- **AC-2** The build loop's executable code shall invoke no executor directly — no `oc`,
  `codex` or `opencode` command and no `OC_*`/`CODEX_*` variable. (Its filename is out of
  scope; see §5.) *(SG-1)*
- **AC-3** When a strategy exports `RALPH_EXEC_CMD`, the loop shall invoke that command with the
  prompt as its single argument and capture its output as the attempt transcript.
- **AC-4** If a binding exceeds `RALPH_EXEC_TIMEOUT`, then the loop shall kill it and treat the
  attempt as failed. *(SG-2)*
- **AC-5** If a binding exits non-zero having written less than 512 bytes, then the loop shall
  abort with exit 3 rather than run the gate. *(SG-3)*
- **AC-6** No file under `specs/*/verify.sh` or `scripts/` shall reference a per-executor build
  loop; `scripts/ralph-codex.sh` shall not exist. *(SG-4)*
- **AC-7** The build loop plus its executor bindings shall total **fewer lines than the two
  duplicated loops they replaced** (424 at `6d9dcb3^`: `ralph-qwen.sh` 220 + `ralph-codex.sh` 204).

  > **Twice-corrected, and worth keeping both corrections visible.** The first draft measured
  > *gate* lines only, a target this change provably cannot hit (+132 gate, −15 twin guard). The
  > second measured *total harness* lines against a frozen 7,465 — which asks "is the harness
  > forever smaller than the day this was written", not "did this change shrink things". It went
  > red the moment `specs/loop-doctor` landed ~250 lines of new capability, failing an unrelated
  > and entirely legitimate addition. A ratchet against an absolute number is a guard that fires
  > at strangers. Scope the claim to what this spec owns, and it stays true regardless of what
  > the harness grows next.

## 11. Verification (the harness)

`specs/executor-binding/verify.sh` — STATIC, three-verdict, `STRICT=1` promotes pend. Executing
checks drive the real `ralph-build.sh` in a throwaway repo with a **mock binding**, which is what
makes AC-3/AC-4/AC-5 provable without either real model.

Deliberately **small**. A gate for a seam does not need the surface of a gate for a subsystem,
and this spec's own §preamble makes gate bloat the thing being fixed — a 300-line gate here
would refute the spec it verifies.

Red-before-green against the pre-change tree: AC-1 through AC-6 all fail there (no binding seam
exists, `ralph-codex.sh` is present, three gates reference it). Recorded in `evidence/`.
