# Spec: one loop driver, with the executor as a parameter

## 1. Why · [R]

`scripts/ralph-qwen.sh` and `scripts/ralph-codex.sh` are the same program twice. Strip
comments and blank lines and the qwen loop is 117 lines of code, of which **37 differ** —
and most of those 37 are not executor-specific either:

| Difference | Genuinely per-executor? |
|---|---|
| `usage: ralph-qwen.sh` vs `ralph-codex.sh` | no — a string |
| `RALPH_AGENT` default `qwen` vs `codex` | no — a default |
| `RALPH_SHEET` default `on` vs `off` | no — a default |
| `ralph(qwen):` vs `ralph(codex):` in the commit subject | no — derived from the agent |
| codex preflight: CLI on PATH, `codex login status` | **yes** |
| `run_codex()` — invocation plus its own watchdog | **yes** |
| `oc run --dir "$ROOT" "$prompt"` vs `run_codex "$prompt"` | **yes** — one call site |

Everything else — the task queue, the retry contract, the deterministic gate call, the
no-op guard, the stillborn-executor abort, `git add -A` + commit, the STRICT backstop, the
ledger wiring — is identical logic maintained in two places.

`ralph-codex.sh`'s own header says the abstraction out loud and then does not build it:

> *"Structurally identical to ralph-qwen.sh, and deliberately so: same spec-dir contract,
> same fresh-session-per-attempt, same DETERMINISTIC external gate, same
> retry-with-feedback, same stop-for-a-human exit 2. **The loop carries the rigor; only the
> executor swaps.**"*

### What the duplication has already cost — measured, not projected

- **`ac13:twins-identical` exists only to catch forgetting the second copy.** A check whose
  entire purpose is guarding against a copy-paste tax.
- **Four consecutive attempts at `specs/tasks-ledger` T3 failed on it.** Every one wired
  `ralph-qwen.sh` correctly and left `ralph-codex.sh` short the `ledger_record` call. The
  commit boundary sits at a different line in each file, so it is the one edit that cannot
  be mirrored positionally — and it is the one that keeps being dropped.
- **`pi-cluster#194` D1 had to be fixed twice.** The brief named `ralph-qwen.sh`; the
  implementer caught that `ralph-codex.sh` carried the identical defect at `:124`, `:130`
  and `:154`. That catch was luck, not process.
- Every future harness change pays this tax, forever, and every one needs a drift check.

The pattern already exists in this repo: `ralph-judge.sh` takes `JUDGE_CMD` and
`EXECUTOR_CMD` as swappable commands rather than forking the judge per model family.

## 2. Outcomes (Definition of Done) · [R]

- One driver, `scripts/ralph-loop.sh`, holds all loop logic.
- `ralph-qwen.sh` and `ralph-codex.sh` become thin adapters: set defaults, define the
  executor hooks, source the driver. Target under 30 lines each.
- Both entry points keep their exact current CLI — `scripts/ralph-<agent>.sh <spec-dir>` —
  and their current behaviour, defaults included.
- `ac13:twins-identical` in `specs/tasks-ledger/verify.sh` becomes vacuous, because there is
  no second copy to drift from. It is not deleted by this spec; it simply cannot fail.

## 3. Entities · [E]

**The adapter contract.** An adapter supplies exactly four things, then sources the driver:

| Name | Kind | Contract |
|---|---|---|
| `RALPH_AGENT` | variable | short agent name. Drives the log/status directory, the JSON `agent` field, and the `ralph(<agent>):` commit subject |
| `RALPH_SHEET` | variable | `on`/`off` default for the navigation codesheet |
| `executor_preflight` | function | exits non-zero with a message if the executor cannot run. May be a no-op. Called once, before the queue |
| `executor_run <prompt> <logfile>` | function | runs ONE attempt, writes the transcript to `<logfile>`, returns the executor's exit code. Owns its own timeout |

Nothing else may differ. An adapter that needs a fifth hook is a signal the driver is
holding something executor-specific that belongs in the adapter.

**The commit subject** is derived — `ralph(${RALPH_AGENT}): <task-label> — <task-text>` —
not written per adapter. It is currently the only place the two files disagree on output
format, and deriving it removes the disagreement by construction.

## 4. Approach · [A]

Extract, do not rewrite. `ralph-qwen.sh` is the more mature of the two and is the base:
move its body to `ralph-loop.sh`, replace its one `oc run` call site with
`executor_run "$prompt" "$(log_path ...)"`, and replace the two literal `qwen` strings with
`$RALPH_AGENT`. The codex adapter then supplies `run_codex`'s existing body verbatim as
`executor_run`.

The driver is **sourced**, not executed, so the adapter's functions are already defined
when it runs — the same shape `ralph-log.sh` and `ralph-status.sh` already use.

## 5. Scope · [S]

### In scope
- `scripts/ralph-loop.sh` (new), `scripts/ralph-qwen.sh`, `scripts/ralph-codex.sh`.

### Out of scope
- **Changing what the loop does.** Task selection, retry budget, gate semantics, the no-op
  guard, the stillborn abort, ledger behaviour: all move verbatim. This is a pure
  refactor, and a behaviour change smuggled inside it is a defect.
- `ralph-judge.sh` and its executor wrappers — already parameterised, already correct.
- Finishing `specs/tasks-ledger`. It is blocked behind this and lands afterwards, into one
  file instead of two.

## 6. Prior decisions the implementer must know · [S]

**Verified 2026-08-25 against `8080df4`.**

| Fact | Consequence |
|---|---|
| bash re-seeks in a running script | The loop cannot safely rewrite the driver it is executing. Run this spec from an ISOLATED COPY of `scripts/`, exactly as `specs/tasks-ledger` instructs |
| `ralph-qwen.sh` is 193 lines, `ralph-codex.sh` 199 | The codex file is not a superset; it has its own watchdog the qwen file lacks, since `oc` provides one |
| `oc` has `OC_RUN_TIMEOUT`; codex does not | `executor_run` owns its timeout. The driver must not impose one, or codex's watchdog and the driver's will fight |
| `hb_init`/`log_init` resolve their roots once, at startup | Adapters must set `RALPH_AGENT` BEFORE sourcing the driver, or the log and status directories carry the wrong agent name |
| `log_task()` handles both task-label dialects | Do not add label parsing to the driver; it already exists in `ralph-log.sh` |

## 7. Norms · [N]

- bash 3.2 (macOS): no `declare -A`, no `mapfile`, and never expand a possibly-empty array
  as `"${arr[@]}"` under `set -u`.
- The driver must not name any executor. **A grep for `qwen`, `codex`, `oc run` or
  `opencode` in `ralph-loop.sh` is a defect** — that is the whole point of the spec, and it
  is the one property a check can prove by absence.
- Adapters must not contain loop logic: no task queue, no retry counting, no gate
  invocation, no commit.

## 8. Acceptance criteria (EARS) · [O]

- **AC-1** THE SYSTEM SHALL provide `scripts/ralph-loop.sh` containing the task queue, the
  retry contract, the gate invocation and the commit.
- **AC-2** `scripts/ralph-loop.sh` SHALL contain no executor identifier — no `qwen`, no
  `codex`, no `oc run`, no `opencode`. *(negative; sound by absence)*
- **AC-3** Each adapter SHALL be under 30 lines of code excluding comments, and SHALL define
  `executor_preflight` and `executor_run`.
- **AC-4** WHEN either adapter is invoked as `scripts/ralph-<agent>.sh <spec-dir>`, THE
  SYSTEM SHALL behave as it does today — same defaults, same exit codes, same commit
  subject `ralph(<agent>): <label> — <text>`.
- **AC-5** THE SYSTEM SHALL derive the commit subject from `RALPH_AGENT` rather than a
  literal in either adapter.
- **AC-6** WHERE an adapter omits `executor_run`, THE SYSTEM SHALL fail loudly at startup
  rather than proceeding with no executor.
- **AC-7** THE two adapters SHALL share no loop logic: neither may contain a task-queue
  read, a retry counter, a `verify.sh` invocation, or a `git commit`. *(negative)*
- **AC-8** WHEN the driver runs a task end to end against a fixture repo, THE SYSTEM SHALL
  produce the same commits and the same exit code under both adapters, with the executor
  stubbed. *(executing — the only class that proves the refactor preserved behaviour)*
