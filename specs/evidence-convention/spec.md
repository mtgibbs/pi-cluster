# Spec: a project brings specs and gates; the harness owns everything else

## 1. Why · [R]

A project that wants to be looped currently has to understand the harness. To answer *"how
did T21 go"* in `notes-from-hearing`, that repo grew **1,033 lines of loop machinery** —
`run-index.py` (853), `loop-metrics.sh` (107), `loop-meta-audit.py` (73) — with a combined
**five** references to anything about hearing aids or Swift. The rest was knowledge of
`~/.harness/logs`, `~/.harness/status`, `qwen-<pid>` directory naming, `T<n>-attempt<n>.log`
filename grammar, two storage layouts either side of #194, the judge ledger's git-dir hiding
spot, and a 3-day/1-day deletion timer it had to race.

Two of those files were sitting inside `specs/v1/` — a *spec directory*, which is supposed
to hold the contract for a feature.

That is backwards. **The harness is the engine; the project is the chassis.** A project
should declare its specs and its gates and know nothing about qwen, PIDs, TTLs, or ledgers.

The cost was not theoretical. Because the record lived in `$HOME` on a timer, 14 of that
project's 42 runs had already lost their status file before anyone noticed — the entire
2026-08-17/18 cohort, deleted mid-run by the 1-day sweep. Three runs remain unattributable
to any task, permanently.

## 2. Outcomes (Definition of Done) · [R]

- A repo containing `specs/<name>/{spec.md,tasks.txt,verify.sh}` is loopable with no
  harness-specific files of its own.
- The harness writes that repo's record into `<repo>/.evidence/`, and the repo commits it.
- `scripts/loop-index.py`, `scripts/loop-metrics.sh` and `scripts/loop-meta-audit.py` live
  here, take a target repo, and contain zero project-specific identifiers.
- `notes-from-hearing` deletes its three copies and keeps only specs, gates and `.evidence/`
  as data.

## 3. Entities · [E]

**The convention.** One layout, no configuration:

```
<any repo>/
├── specs/
│   ├── constitution.md          inherited by every spec; never copied into one
│   └── <name>/                  "initial_implementation" for a first build,
│       ├── spec.md              otherwise the feature's own name
│       ├── tasks.txt
│       └── verify.sh
└── .evidence/                   the harness writes here
    ├── index.md / index.jsonl   distilled record — COMMITTED
    ├── metrics.jsonl            one row per task — COMMITTED
    ├── status/                  pid → task heartbeats — COMMITTED
    ├── judge-ledger.jsonl       findings + decisions — COMMITTED
    └── runs/                    raw transcripts — GITIGNORED
```

A spec directory may be named for a feature or `initial_implementation`. The distinction is
naming only; the harness treats them identically. `specs/*/` is discovered, never enumerated.

**Why `.evidence/` is a dotfolder in the repo.** It is metadata *about* the project rather
than part of it, so it is hidden — but it is *in the repo*, because a record that does not
travel with the clone it describes is not a record.

**The committed/ignored split.** `runs/` is bulk (8.6 MB at 28 tasks) and git never forgets;
everything else is ~190 KB and is what makes the history reconstructible. Lose `runs/` and
you keep every task, attempt count, verdict, timing and judge finding. Lose the rest and
`runs/` is unlabelled transcripts.

## 4. Approach · [A]

The harness already has the seam: `RALPH_LOG_DIR` and `RALPH_STATUS_DIR` are honoured
verbatim (`ralph-log.sh:28`). This spec makes the target repo's `.evidence/` the **default**
for a run against that repo, rather than something an operator must remember to export.

Distillation happens at the end of every task, in the harness, not as a step a project is
trusted to run. That is the mechanism the whole record depends on: once `index.jsonl` is
written, `runs/` is free to expire.

## 5. Scope · [S]

### In scope (this repo, this spec's `tasks.txt`)
- Move and de-project the three tools into `scripts/`.
- Default the log and status roots to `<target>/.evidence/` when running against a repo.
- Add `RALPH_STATUS_KEEP_MIN` so the status sweep is configurable.
- Run `loop-index.py` after each task.

### Out of scope entirely
- The `notes-from-hearing` deletion — a companion PR in that repo, sequenced after this one.
- Changing what the loop *does*: task selection, retry contract, judge protocol, gate
  semantics. This is about where the record goes.
- Migrating existing `~/.harness` content. Pre-convention runs stay where they are.

## 6. Prior decisions the implementer must know · [S]

**Verified 2026-08-24 against `44c2270` + #194.**

| Fact | Where | Consequence |
|---|---|---|
| `RALPH_LOG_DIR` / `RALPH_STATUS_DIR` are used verbatim when set | `ralph-log.sh:37`, `ralph-status.sh:55` | the seam exists; do not add a second one |
| the log sweep is configurable | `ralph-log.sh:44` — `${RALPH_LOG_KEEP_MIN:-4320}` | pointing it at `.evidence/runs/` is safe |
| **the status sweep is NOT** | `ralph-status.sh:59` — hardcoded `-mmin +1440 -delete` | pointing `RALPH_STATUS_DIR` at committed files today would delete them daily and show phantom deletions in git. **This must be fixed first.** |
| the status JSON already records `spec` | `ralph-status.sh` `hb_write` | per-feature attribution needs no new field |
| `log_task()` handles both task-line dialects | `ralph-log.sh` | `T1: …` and `T01 kit-package: …` both yield a clean label |
| the judge ledger sits at `git rev-parse --git-path ralph-judge` | `ralph-judge.sh:58` | resolves differently in a linked worktree than in the main checkout; search both |

## 7. Norms · [N]

- bash 3.2 (macOS): no `declare -A`, no `mapfile`.
- The tools take a target repo and derive everything from it. **A project identifier
  appearing in `scripts/loop-*` is a defect**, and is the specific thing this spec exists to
  remove.
- Best-effort, same contract as `ralph-log.sh`: a full disk can never fail the loop it is
  reporting on.
- `loop-index.py`'s honesty rule stands: a field that cannot be derived renders `—`, never
  `0`. It reported "0 findings" over a 31 KB ledger once already.

## 8. Safeguards · [S]

- Never write outside the target repo's `.evidence/`.
- Never commit on the project's behalf. The harness writes; the project's own PR flow
  commits.
- The convention is discovered, not configured. If a repo has no `specs/*/`, say so and exit
  — do not invent a location.

## 9. Acceptance criteria (EARS) · [O]

- **AC-1** WHEN a loop runs against repo R, THE SYSTEM SHALL write attempt logs to
  `R/.evidence/runs/` and status to `R/.evidence/status/` without the operator exporting
  anything.
- **AC-2** WHEN a task completes, THE SYSTEM SHALL regenerate `R/.evidence/index.md` and
  `index.jsonl` before the run exits.
- **AC-3** THE SYSTEM SHALL discover spec directories by globbing `R/specs/*/tasks.txt`; no
  spec directory name SHALL appear as a literal in any `scripts/loop-*` file.
- **AC-4** THE SYSTEM SHALL honour `RALPH_STATUS_KEEP_MIN`, defaulting to 1440, exactly as
  `RALPH_LOG_KEEP_MIN` is honoured for logs.
- **AC-5** No file under `scripts/loop-*` SHALL contain the name of any project this harness
  has ever run against — grep-verifiable.
- **AC-6** WHEN `loop-index.py` runs against a repo whose `.evidence/` exists but whose
  harness is absent, THE SYSTEM SHALL produce the identical index. *(Verified: with `HOME`
  pointed at an empty directory, `notes-from-hearing` indexes byte-identically — 28 tasks,
  36 runs, 56 findings.)*
- **AC-7** WHERE a run under `R/.evidence/` belongs to another repo, THE SYSTEM SHALL report
  it. Under the convention this should be structurally impossible; a non-zero count means
  pre-convention leftovers.
