# Spec: loop-doctor — read the harness's own telemetry and name the fault

- **Status:** Done v1.0
- **Owner:** Matt (design by Claude; executor TBD)
- **Constitution:** `specs/constitution.md` + `specs/amendments.md` (v1.3.0) (+ `/CLAUDE.md` Core Mandates)
- **Touches:** new `scripts/loop-doctor.sh`; new `specs/loop-doctor/{tasks.txt,verify.sh,fixtures/}`.
  **No change** to `ralph-qwen.sh`, `ralph-status.sh`, `ralph-log.sh`, `gate-score.sh`, or `loop-report.sh`.

---

## 1. Why · [R]

Five telemetry channels already exist and each one works — `ralph-status.sh` (heartbeat JSON),
`ralph-log.sh` (per-attempt transcript + diff), `ralph-bus.sh` (Matrix events), `gate-score.sh`
(score line), `loop-report.sh` (one-screen branch summary). **Nothing consumes them together, so
the signals they carry are never read.**

Measured against the live corpus on 2026-08-18 (5 runs in `~/.harness`, all on repo
`notes-from-hearing`), three failed attempts had three *different* root causes, each decidable
from the first ~200 bytes of the transcript, and a human still had to `cat` five directories to
tell them apart:

| Observed artifact | Actual fault | Correct action |
|---|---|---|
| `qwen-8375/T3-attempt2.log`, 31 B, banner only | executor produced nothing | container needs attention |
| `qwen-14947/T4-attempt2.log`, 114 B, `Killed: 9` | watchdog kill | raise `OC_RUN_TIMEOUT` / split the task |
| `qwen-98608/T1-attempt{1,2,3}.log`, ~2 KB, `permission requested:` | the gitignored `opencode.json` is missing from the worktree | `cp opencode.json <worktree>/` |

All three are **harness faults wearing a model-fault costume**, which is why re-rolling never
fixes them. The third is already written up in `scripts/README.md` after it *"burned six
sessions"* during the loop-report race — and it recurred anyway, because the knowledge lives in
prose that nobody greps mid-run.

Worse, `ralph-status.sh` states a liveness rule in its own header — *"phase `running|verifying`
with `updated` more than a few minutes old is a DEAD loop"* — and **nothing applies it.** A
heartbeat 36 minutes stale still read `running`.

Finally, there is **no cross-run corpus**: `~/.harness/logs` is culled at 3 days
(`RALPH_LOG_KEEP_MIN` 4320) and heartbeats at 1 day, so no question of the form *"is strategy A
better than strategy B"* or *"did this get worse after that change"* can be answered at all. The
durable record today is "the branches."

## 2. Outcomes (Definition of Done) · [R]

1. `scripts/loop-doctor.sh` reads the existing heartbeat + log artifacts and prints **one line
   per run** naming the run, its phase, and its **classified fault** — replacing "cat five
   directories and squint".
2. Every classification **cites its evidence** (the literal marker matched, or the artifact named
   as absent). A classification that cannot cite is reported as `unknown`, never guessed.
3. `--json` emits one JSON object per run against the §3 schema, so the tool composes as a
   **tool-above-an-LLM** (any executor can shell out to it) and as a data source for
   `harness-console`.
4. `--ledger <file>` appends one row per run to an **append-only JSONL ledger** that survives the
   artifact cull, giving the first cross-run corpus. Re-running is idempotent: a run already in
   the ledger is not duplicated.
5. It **counts what it could not parse** (`unparsed`), so telemetry-format drift degrades the
   report instead of silently blinding it.
6. It is **strictly read-only**: it never runs a loop, never invokes `verify.sh` or
   `gate-score.sh`, never writes into a worktree, and never touches the network.
7. It is **deterministic and hermetic under test**: `--now` injects the clock so staleness is
   gate-testable.

## 3. Entities · [E]

### 3.1 Run key

A run is identified by the triple **`(repo, spec, run_id)`**. `spec` alone is NOT unique —
three runs in the live corpus all reported `specs/v1`. `run_id` is the heartbeat's
`<agent>-<pid>` basename (e.g. `qwen-23852`), which is already the log directory name.

### 3.2 Ledger row (JSONL, one object per line)

Field names and types are literal. `null` and `0` are **different values** and must not be
conflated — `0` says "measured, and it was zero"; `null` says "not measurable from the
artifacts available". (Borrowed from quill's `context_fraction` rule: *"zero says empty, None
says unknowable, and the resume gate treats the two differently"*.)

| field | type | meaning |
|---|---|---|
| `run_id` | string | `<agent>-<pid>`, e.g. `qwen-23852` |
| `agent` | string | from heartbeat `agent` |
| `repo` | string | from heartbeat `repo` |
| `spec` | string | from heartbeat `spec` |
| `branch` | string | from heartbeat `branch` |
| `task_index` | integer | from heartbeat |
| `total_tasks` | integer | from heartbeat |
| `attempt` | integer | from heartbeat |
| `max_attempts` | integer | from heartbeat |
| `phase` | string | heartbeat `phase` verbatim |
| `verify_pass` | `true\|false\|null` | heartbeat verbatim — `null` means "not yet verified", never `false` |
| `started` | integer | unix seconds |
| `updated` | integer | unix seconds |
| `duration_s` | integer | `updated - started` |
| `stale_s` | integer\|null | `now - updated`; `null` when no heartbeat exists |
| `fault` | string | one of §3.3 |
| `evidence` | string | the literal marker matched, or the named absence. Never empty. |
| `attempts_seen` | integer | count of `T*-attempt*.log` files found |
| `bytes_last` | integer\|null | size of the highest-numbered attempt log; `null` if no logs |
| `diffs_seen` | integer | count of `T*-attempt*.diff` files found |
| `unparsed` | integer | artifacts present that no rule could classify (§3.4) |

### 3.3 Fault classes (closed set)

Decided **in this order**; first match wins. The order matters — `dead` outranks the log-shape
rules because a killed loop cannot update its own file, so its last transcript is misleading.

| `fault` | Decision rule | Evidence string must name |
|---|---|---|
| `dead` | heartbeat `phase` ∈ {`running`,`verifying`} **and** `stale_s > STALE_S` | `heartbeat stale <n>s (phase=<p>)` |
| `running` | heartbeat `phase` ∈ {`running`,`verifying`} and not stale | `heartbeat fresh <n>s` |
| `done` | heartbeat `phase` = `done` | `phase=done` |
| `watchdog-kill` | last attempt log matches `Killed: 9` | the matched line |
| `permission-blocked` | last attempt log matches `permission requested:` **and** has no matching `.diff` | the matched line |
| `executor-stillborn` | last attempt log `< 512` bytes and no `Killed: 9` | `<n>B transcript, no kill marker` |
| `verify-fail` | a `.diff` exists for the last attempt | `<path>.diff present` |
| `no-op` | attempt log ≥ 512 bytes, no `.diff`, phase `stopped`/`failed` | `log <n>B, no .diff` |
| `unknown` | nothing above matched | what was looked for and not found |

> The `512` threshold and the `Killed: 9` marker are **not invented here** — they are the
> literals `ralph-qwen.sh:100-108` already uses for its stillborn guard. See §6.

### 3.4 `unparsed`

`unparsed` is **per-run**, never a global counter. It counts, for that run:

- any artifact under the run's log directory whose basename does not match
  `^T[0-9]+-attempt[0-9]+\.(log|diff)$`;
- the run's heartbeat file, if it exists but is not valid JSON or is missing a §3.2 source field.

A heartbeat file therefore still produces a row even when its *contents* are unreadable — the
`run_id` comes from the **filename** (`<agent>-<pid>.json`), which is parseable independently.
That row carries `unparsed: 1`, every heartbeat-sourced field `null`, and `fault: unknown`. A
heartbeat whose *filename* does not match `^[a-z0-9]+-[0-9]+\.json$` is not a run and is ignored.

**Counted, never fatal, never hidden.** A nonzero `unparsed` prints as a trailing
`(unparsed: N)` on that run's human-output line.

## 4. Approach · [A]

A single read-only bash script that walks two directories, joins them on `run_id`, applies an
ordered rule table, and prints. **No LLM, no daemon, no network, no state beyond the optional
ledger.**

Mirrors `scripts/loop-report.sh` in shape and style — bash, `set -uo pipefail`, macOS bash 3.2
(**no `declare -A`**), `jq` permitted, human-readable stdout, `usage:` to stderr on misuse. It is
the same species of tool: a read-only reporter over artifacts someone else produced.

**Rejected — invoking anything.** `loop-report.sh` §5 already names the hazard: *"no invoking
`gate-score.sh` (recursion hazard: the gate runs `verify.sh`, which runs this script)"*. The same
rule binds here and is stronger, because loop-doctor is intended to eventually run *inside* the
harness it measures. **The reader must never invoke the thing it measures.**

**Rejected — an MCP server for v1.** Three executors have three different MCP stories and one
(codex) cannot express the homelab servers' `X-API-Key` auth at all (`coding-agent-ops`
SKILL.md). Every executor can run a shell command. A CLI with a contract is the base form; an
MCP wrapper over it is a later, additive step.

**Rejected — instrumenting the driver instead** (quill's `StreamProgress` parses the agent CLI's
stdout live, tracking turns/tools/context-fraction/output-tokens). Richer, but it requires
editing `ralph-qwen.sh` and `ralph-codex.sh` and re-deploying containers, and it cannot read the
runs that already happened. Reading artifacts after the fact works on today's corpus with zero
changes to the loops. **Live-stream instrumentation is the natural v2** and §12/OQ3 keeps the
door open — the §3.2 schema deliberately leaves room for `tokens`/`turns`/`tools` columns.

## 5. Scope · [S]

### In scope
- `scripts/loop-doctor.sh` — the only script this spec may create or modify.
- `specs/loop-doctor/{tasks.txt,verify.sh,fixtures/}` — the gate and its fixtures.

### Out of scope — do NOT touch
- `scripts/ralph-*.sh`, `scripts/run-loop.sh`, `scripts/gate-score.sh`, `scripts/loop-report.sh`,
  `scripts/harness` — **no edits, no "small improvements"**, even where this spec's §1 names a
  defect in one of them (the `executor-stillborn` / `watchdog-kill` conflation, §6). Those are
  reported as findings for a human, not fixed here.
- `harness-console/index.html` — wiring the feed is a follow-on.
- Any `clusters/pi-k3s/**` manifest. Nothing is deployed by this spec.
- The Matrix bus. loop-doctor does not post.
- Any change to what the loops *write*. This spec only reads what already exists.

## 6. Prior decisions / facts the implementer must know · [S]

- **Artifact locations, literal.** Heartbeats:
  `${RALPH_STATUS_DIR:-$HOME/.harness/status/<repo>}/<agent>-<pid>.json`, written atomically
  (tmp + `mv`) by `scripts/ralph-status.sh`. Logs:
  `${RALPH_LOG_DIR:-$HOME/.harness/logs/<repo>}/<agent>-<pid>/<task>-attempt<n>.{log,diff}`,
  written by `scripts/ralph-log.sh`. **A run may have a log dir with no heartbeat, or a
  heartbeat with no log dir.** Both are normal; handle each.
- **The default roots carry a `<repo>` level; an explicit `--status-dir`/`--log-dir` does not**
  (2026-08-24; the roots were flat until then, and one evidence bundle collected three unrelated
  projects). So discovery walks `<root>/*/[<agent>-<pid>]` when the root is a default and
  `<root>/[<agent>-<pid>]` when it was given explicitly — and every gate fixture, which passes
  the directory explicitly, keeps the flat shape. Where a run has no heartbeat, the path's
  `<repo>` component is now the only source for the `repo` field; take it from there.
- **`<task>` in a log filename is the TASK LABEL, not the queue index** (same date). `T21` means
  the run implemented T21. It used to mean "21st in this invocation's queue", which collided
  across runs and named a different task nearly every time. The `^T[0-9]+-attempt[0-9]+` matcher
  is unchanged and still authoritative: a spec whose tasks are not labelled `T<n>` produces a
  name that does not match, and that is an honest `unparsed`, not a silent mislabel.
- **`.diff` is written on exactly one path.** `ralph-qwen.sh:140` calls `log_failure` *only*
  after a verify failure, deliberately *before* the tree reset that would erase the evidence.
  Therefore **`.diff` present ⇔ the gate ran and said no** — the healthy failure. Its absence is
  the discriminator for every harness-fault class. This is the single most load-bearing fact in
  the spec.
- **The `512` literal is ralph's own.** `ralph-qwen.sh:100-108` (the test is line 102):
  `if [ "$_rc" != 0 ] && [ "$_sz" -lt 512 ]` → prints *"the executor did not start"* and exits 3.
  Reuse the same threshold so loop-doctor agrees with the loop rather than inventing a second
  standard.
- **Known defect to REPORT, not fix (§5).** That same guard conflates two faults: a transcript of
  114 B containing `Killed: 9` is a *watchdog kill* (the executor ran and stalled), but ralph
  reports *"the executor did not start — the container needs attention"*. Different causes,
  different fixes. loop-doctor must classify `watchdog-kill` **before** `executor-stillborn`
  (§3.3 order) so it is right where ralph is wrong.
- **The no-op path writes no `.diff`.** `ralph-qwen.sh:119-125`: an attempt that leaves
  `git status --porcelain` empty is failed with `hb_write failed false` and `continue` — no
  `log_failure`. This is why the `permission requested:` corpus has three logs and zero diffs.
- **Staleness threshold.** `ralph-status.sh` sets `HB_TICK_SEC` default 20 and the console's
  documented collector rule is 120 s. Use `STALE_S` default **120**, overridable, and injectable
  via `--now` for tests.
- **`verify_pass` is a JSON literal**, unquoted, and is `null` while a task is in flight —
  `null` is not `false`. `ralph-status.sh` emits it correctly today; preserve the distinction.
- **`spec` is not a unique key** (three live runs all say `specs/v1`); key on `(repo, spec, run_id)`.
- **macOS bash 3.2.** No associative arrays, no `mapfile`, no `${var,,}`. `loop-report.sh` was
  written under the same constraint — copy its idioms.
- **Style + gate idiom to mirror:** `specs/loop-report/verify.sh` — hermetic, fixtures-only,
  `ok()`/`no()` helpers, existence checks are hard FAIL (single-deliverable spec), and an
  explicit comment naming the recursion hazard it refuses.

## 7. Norms · [N]

- **Evidence, not adjectives.** Every `fault` carries an `evidence` string naming the literal
  thing observed — the matched line, or *the artifact looked for and not found*. Adapted from
  quill's `rubric.md` rule: *"Firing one requires evidence, not a citation. Name the grep that
  returned nothing. 'This does not apply here' is not a qualification."* An empty `evidence` is
  a bug, and §10/AC7 gates it.
- **Measure your own blindness.** `unparsed` is a first-class field, printed in human mode when
  nonzero. A format change must degrade the report visibly, never silently. (quill's
  `unparsed_stream_lines`; same instinct as `ralph-log.sh`'s optional-and-never-fatal contract.)
- **`null` ≠ `0`.** Unknowable and zero are different values in both the JSON and the ledger.
- **Optional-and-never-fatal, inverted.** The loops treat telemetry as best-effort so it can
  never break a run. loop-doctor inherits the dual: a malformed or missing artifact degrades one
  row, never aborts the scan.
- **Human mode is the default**, one line per run, sorted newest-`updated` first. `--json` is
  opt-in. (Deliberate divergence from `loop-report.sh`, whose §5 lists "no JSON output mode" as a
  non-goal — that script targets a human at a terminal; this one is explicitly also a tool for a
  model, per §2.3.)
- Exit status is about **the tool**, not the health of what it read: `0` when the scan completed,
  `1` on usage error, `2` when a required directory is unreadable. Finding a `dead` run is a
  successful scan.

## 8. Safeguards · [S]

1. **Read-only, absolutely.** No writes anywhere except the file named by `--ledger`. No `git`
   mutations, no `mv`, no `rm`, no cull. It must be safe to run against a live loop's artifacts
   while that loop is mid-attempt.
2. **Never invoke the measured.** No call to `verify.sh`, `gate-score.sh`, `run-loop.sh`, or any
   `ralph-*.sh`. No `docker`, no `ssh`, no network. (§4 recursion hazard.)
3. **Ledger is append-only.** Never rewrite or truncate an existing ledger. Idempotency is by
   *skipping* a `run_id` already present, never by rewriting the file.
4. **No secrets.** Transcripts may contain tokens or keys. loop-doctor **never copies transcript
   content into the ledger or into `--json`** — `evidence` carries only the matched *marker*
   (a fixed literal from §3.3), never the surrounding line's payload, and never a byte of `.diff`.
5. **Bounded reads.** Only the **first 4 KB** of any transcript is scanned for markers; logs can
   be 68 KB+ and a scan must stay cheap enough to run inside a loop.
6. **No self-measurement.** loop-doctor must not source `ralph-status.sh` or otherwise create a
   heartbeat, or it appears in its own output. (Observer effect.)
7. **Closed fault set.** `fault` is always one of the nine §3.3 values. An unmatched run is
   `unknown` with evidence — never a new ad-hoc string.

## 9. Task breakdown · [O]

Compiled to `tasks.txt`. **Ordered so every task has its own observable** — each one is visible
in the `--json` output the task before it produced, so the §11 gate can pend on that task's own
artifact rather than on a later task's work (`specs/TEMPLATE.md` §11 three-verdict contract).

- **T1** — skeleton + arg parsing only. Observable: exit codes and `usage:` on stderr.
- **T2** — heartbeat/log-dir discovery (**union** of both) + the human one-line-per-run shape,
  sorted by `updated` descending. Observable: a line per run.
- **T3** — `--json` + every heartbeat-sourced §3.2 field, `duration_s`/`stale_s` from `--now`,
  `verify_pass` as a JSON literal. Observable: parseable JSON carrying `stale_s`.
- **T4** — log-directory reader: `attempts_seen`, `diffs_seen`, `bytes_last`, `unparsed`.
  Observable: those four keys.
- **T5** — the §3.3 classifier, replacing T2's placeholder. Observable: real `fault` + `evidence`.
- **T6** — `--ledger` append-only with skip-based idempotency. Observable: the ledger file.

**Rejected — splitting T1's argument parsing from its directory policy.** The `qwen-61568`
post-mortem flagged T1 as carrying two contracts, and the obvious remedy is two tasks. It does
not work here: T2 would have **no presence-gate**. A behaviour ("does it exit 2 on an unreadable
explicit dir?") has no artifact to arm a `pend` on, so its checks could only be hard FAILs — and
hard-failing T2's checks while T1 is being built is precisely the "T1 gated on a later task's
work" trap the three-verdict contract exists to prevent. The alternative presence-gate — grepping
the script for `exit 2` — tests for the fix rather than the behaviour. So the two stay one task,
and the real defect (§10 AC2/AC2b: the precedence was never stated) is fixed instead. Splitting a
task is only an improvement when each half can be observed independently.

## 10. Acceptance criteria (EARS) · [O]

- **AC1** (Ubiquitous) The system shall exist at `scripts/loop-doctor.sh`, be executable, and be
  `bash -n` clean.
- **AC2** (Unwanted) If invoked with **no directory flags** and neither default directory is
  readable, then the system shall print a line containing `usage:` to stderr and exit 1.
- **AC2b** (Unwanted) If a directory is given **explicitly** via `--status-dir` or `--log-dir`
  and is not a readable directory, then the system shall print to stderr and exit **2** — and
  shall do so whether the other directory is readable or not. The explicit-flag rule outranks
  AC2; the two overlap and the precedence is normative, not incidental.
- **AC2c** (Unwanted) If an unrecognised flag is given, then the system shall print a line
  containing `usage:` to stderr and exit 1.
- **AC3** (Event-driven) When given a fixture status dir and log dir, the system shall print
  exactly one output line per `run_id` found.
- **AC4** (Event-driven) When a run's heartbeat has `phase=running` and `updated` older than
  `--stale-s` relative to `--now`, the system shall classify it `dead`.
- **AC5** (Event-driven) When a run's heartbeat has `phase=running` and `updated` newer than
  `--stale-s` relative to `--now`, the system shall classify it `running` — the same fixture with
  a different `--now` must produce a different verdict, proving the clock is injected and the
  staleness rule is live.
- **AC6** (Event-driven) When the last attempt log contains `Killed: 9` and is under 512 bytes,
  the system shall classify it `watchdog-kill`, **not** `executor-stillborn`.
- **AC7** (Ubiquitous) The system shall emit a non-empty `evidence` value for every run in
  `--json` output.
- **AC8** (Event-driven) When a run's last attempt has a sibling `.diff`, the system shall
  classify it `verify-fail`.
- **AC9** (Event-driven) When a run's logs contain `permission requested:` and no `.diff`, the
  system shall classify it `permission-blocked`.
- **AC10** (Event-driven) When the log dir contains a file not matching
  `^T[0-9]+-attempt[0-9]+\.(log|diff)$`, the system shall increment `unparsed` for that run and
  shall still classify the run.
- **AC11** (Unwanted) If a heartbeat file is not valid JSON, then the system shall count it in
  `unparsed` and continue scanning, exiting 0.
- **AC12** (Event-driven) When `--json` is given, each line shall parse as JSON and carry every
  §3.2 field, with `verify_pass` as a JSON literal (`true`/`false`/`null`, never the string
  `"null"`).
- **AC13** (Event-driven) When `--ledger F` is given twice against the same fixtures, the second
  run shall add zero lines to `F`.
- **AC14** (Unwanted) If a fixture transcript contains a credential-shaped string, then it shall
  not appear anywhere in stdout or in the ledger — `evidence` carries the §3.3 marker only.
- **AC15** (Ubiquitous) The system shall not contain a call to `verify.sh`, `gate-score.sh`,
  `run-loop.sh`, `ralph-*.sh`, `docker`, `ssh`, `curl`, or `git commit` — asserted by grep over
  the script itself.

## 11. Verification (the harness)

`specs/loop-doctor/verify.sh`, **hermetic — fixtures only**, never invoking `gate-score.sh` or
any loop (§4). Mirrors `specs/loop-report/verify.sh`: `ok()`/`no()`/`pend()` per the three-verdict
preamble, existence checks as hard FAIL, and `--now` supplied on every staleness assertion so the
gate is deterministic on any day.

Fixtures to ship under `specs/loop-doctor/fixtures/`, each a **minimal reproduction of a real
observed shape** (§1 table):

```
fixtures/status/qwen-1001.json      phase=running,  updated = T-3600  -> dead   (AC4/AC5)
fixtures/status/qwen-1002.json      phase=stopped,  verify_pass=false -> verify-fail
fixtures/status/qwen-1003.json      phase=failed                      -> permission-blocked
fixtures/status/qwen-1004.json      phase=stopped                     -> watchdog-kill
fixtures/status/malformed.json      not JSON                          -> unparsed  (AC11)
fixtures/logs/qwen-1002/T1-attempt1.log   >512B
fixtures/logs/qwen-1002/T1-attempt1.diff  present                     -> verify-fail (AC8)
fixtures/logs/qwen-1003/T1-attempt{1,2,3}.log  ~2KB, "permission requested:"  (AC9)
fixtures/logs/qwen-1004/T4-attempt2.log   114B, "Killed: 9"           -> watchdog-kill (AC6)
fixtures/logs/qwen-1004/NOTES.txt         stray basename              -> unparsed (AC10)
fixtures/logs/qwen-1002/T1-attempt1.log   contains a fake key literal -> AC14
```

**Red-before-green (amendment "Gates must prove they can fail").** Each of AC4/AC5/AC6/AC9/AC13
must be shown RED against a deliberately wrong implementation before the gate is accepted; the
AC5 pair (same fixture, two `--now` values, two verdicts) is itself the proof that the staleness
check cannot pass vacuously. Record the red-before evidence in `specs/loop-doctor/evidence/`.

**Coverage runs both ways.** §11's usual instruction is that every §10 criterion maps to an
assertion. `qwen-61568` exposed the converse gap: `t1:unreadable-dir-exit-2` was asserted by the
gate and derived only from `tasks.txt` — **no §10 criterion covered it**, so the ambiguity behind
it was never forced into the open. Every assertion in this gate must name the AC (or the §-rule)
it enforces, and an assertion that can name none is either a missing AC or a gate that is testing
its author's assumptions.

**Blind spot, stated honestly** (evidence doc §5 lesson): a fixtures-only gate validates the
classifier against shapes we already know. It cannot prove the rule table covers a fault class
nobody has seen yet — that is exactly what `unknown` + `unparsed` exist to surface, and why both
are printed rather than swallowed.

## 11b. Loop execution

Standard: `scripts/run-loop.sh build-converge specs/loop-doctor` from a git worktree on a
throwaway branch. **Copy the gitignored `opencode.json` into the worktree first** — see
`scripts/README.md`; this spec exists partly because that step was missed again on 2026-08-17.

## 12. Open questions

- **OQ1 — Where does the ledger live?** A file path is a v1 answer, but the durable home matters:
  laptop-side (`~/.harness/ledger.jsonl`, per-machine, invisible to the containers) vs
  container-side (survives the cull but dies with the volume) vs a git-tracked path (durable,
  reviewable, but noisy and PR-gated). **Proposed:** default `~/.harness/ledger.jsonl`, with
  `--ledger` explicit for anything else, and the "promote a race's ledger into the repo as
  evidence" decision left to a human — matching how `loop/model-watch-run*` branches were kept as
  archival evidence.
- **OQ2 — Retention.** quill keeps runs as `-1` / `-latest` siblings and never culls, which is why
  it can compare. Should loop-doctor *also* raise `RALPH_LOG_KEEP_MIN`, or is the ledger row
  (which outlives the artifacts by design) sufficient? **Proposed:** ledger row is sufficient for
  v1; changing the cull touches `ralph-log.sh`, which §5 puts out of scope.
- **OQ3 — Live stream vs post-hoc.** quill's `StreamProgress` gets `turns`, `tools`,
  `context_fraction`, `output_tokens`, `compactions` — none of which survive into our artifacts,
  and all of which a race would want (cost per run, context pressure). Adding them means editing
  the drivers. **Proposed:** out of scope for v1, §3.2 leaves room, revisit once the ledger has
  real rows in it.
- **OQ4 — The third verdict.** quill carries a `docs/MANUAL_VERIFICATION.md` per-feature list and
  downgrades a finding to `partial` when no manual-verification entry exists. We have gated and
  judged, with no named "only a human at a machine can confirm this" bucket. Out of scope here;
  flagged because it belongs in `specs/TEMPLATE.md`, not in this tool.
- **OQ5 — The lessons ledger.** quill's evaluator reads `docs/CODE_REVIEW_LESSONS.md` and grades a
  **repeat offence** differently from a fresh discovery. Our analogue is `specs/amendments.md`,
  which judges already cite — but amendments are constitutional and slow. A per-run fault ledger
  is the raw material for the fast-moving version: *"this harness fault has now cost N runs."*
  Deliberately not built here; the ledger is the prerequisite, and this is the argument for it.

## Two-way sync rule

Logic change → fix this spec first, then the script. Refactor → change the script, sync the fact
back. If a new fault class is discovered in the wild, it is a **spec change** (§3.3 is a closed
set) before it is a code change.
