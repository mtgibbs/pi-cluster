# loop-report — one-screen summary of a strategy run

## §1 Intent

After `run-loop.sh` finishes, the evidence of what happened is scattered: commits on the
branch, a gate score printed to a log, judge state in `ledger.jsonl`/`report.json`. Racing
two strategies on one spec needs those on one screen per branch, diffable by eye.

## §2 Touches / Scope

- **Creates:** `scripts/loop-report.sh` — the only file this spec may create or modify.
- Read-only over everything else. No network. No writes anywhere.
- Style: match `scripts/ralph-qwen.sh` — bash, `set -uo pipefail`, macOS bash 3.2 (no `declare -A`).
- `jq` may be used (already a ralph prerequisite).

## §3 Contract (literal — checks grep for these exact tokens)

Usage:

    scripts/loop-report.sh --spec <dir> [--base <ref>] [--judge-state <dir>] [--gate-log <file>]

- Missing `--spec` → print a line containing `usage:` to **stderr**, exit **1**.
- `--base` defaults to `origin/main`. `--judge-state` defaults to
  `$(git rev-parse --git-path ralph-judge)`.

Output to stdout, exactly these five lines in this order:

    == loop report ==
    branch: <git branch --show-current>
    base: <ref>  commits: <count of base..HEAD>
    gate: <payload>
    judge: <payload>

- `gate:` payload — if `--gate-log` was given and the file contains a line that is exactly
  `---GATE-SCORE---`, print the single line immediately after the **last** such sentinel,
  verbatim. Otherwise print `none`. Never grep above the sentinel — untrusted output.
- `judge:` payload — if `<judge-state>/report.json` exists and parses, print
  `accepted=<n> rejected=<n> gate-gaps=<n> outcome=<outcome>` where the counts are the
  lengths of the `accepted`/`rejected`/`gate_gaps` arrays. Otherwise print `none`.

## §4 Acceptance criteria

AC1 script exists, is executable, `bash -n` clean.
AC2 no-args invocation exits 1 with `usage:` on stderr.
AC3 gate-log fixture: last-sentinel payload line printed verbatim; log without sentinel → `gate: none`.
AC4 judge fixture (`specs/loop-report/fixtures/`): `accepted=2 rejected=1 gate-gaps=0 outcome=dry`.
AC5 empty judge-state dir → `judge: none`.
AC6 header + branch + base lines present per §3.

## §5 Non-goals

No color, no JSON output mode, no writing reports to disk, no invoking gate-score.sh
(recursion hazard: the gate runs verify.sh, which runs this script). The gate line comes
from a log file only.
