#!/usr/bin/env bash
# ralph-qwen.sh — a bounded SDD loop for the local coding model.
#
# Philosophy (learned the hard way): qwen3-coder is a fast, faithful, literal STAMPER
# with no stamina, taste, or self-checking. So we don't make it smarter — we build the
# fixture around it. This loop is the conveyor belt + jig + inspector:
#
#   for each task in the spec:
#     fresh opencode session (no context accumulation)   <- bound the context
#     give it ONE task + the spec as source               <- bound the scope
#     timebox the run (oc's watchdog)                     <- a stall can't cost hours
#     run verify.sh — the DETERMINISTIC gate, not the model's self-report
#     pass -> commit ; fail -> retry with the failure fed back ; stuck -> stop for a human
#
# The model executes; the loop carries the rigor; the human reviews the PR at the end.
#
# Usage (run from inside a git worktree on a throwaway branch):
#   scripts/ralph-qwen.sh specs/<feature>
# spec dir must contain: spec.md, verify.sh, tasks.txt (one task per line, e.g. "T1: arr widgets")
set -uo pipefail

SPEC_DIR="${1:?usage: ralph-qwen.sh <spec-dir>}"
RETRIES="${RALPH_RETRIES:-2}"
SPEC="$SPEC_DIR/spec.md"; VERIFY="$SPEC_DIR/verify.sh"; TASKS="$SPEC_DIR/tasks.txt"
for f in "$SPEC" "$VERIFY" "$TASKS"; do [ -f "$f" ] || { echo "missing $f" >&2; exit 1; }; done
ROOT="$(git rev-parse --show-toplevel)"

# Durable heartbeat (see ralph-status.sh). Sourced so a dashboard can see live
# loop state without attaching tmux. No-op stubs if the helper is absent, so the
# loop never depends on it.
RALPH_AGENT="${RALPH_AGENT:-qwen}"
if [ -f "$(dirname "$0")/ralph-status.sh" ]; then
  . "$(dirname "$0")/ralph-status.sh"
else
  hb_init() { :; }; hb_write() { :; }; hb_tick_start() { :; }; hb_tick_stop() { :; }
fi

# Matrix bus narration — the discrete-event companion to the heartbeat's continuous
# state. Same optional-and-never-fatal contract. See scripts/ralph-bus.sh for why both
# exist rather than one.
if [ -f "$(dirname "$0")/ralph-bus.sh" ]; then
  . "$(dirname "$0")/ralph-bus.sh"
else
  bus_init() { :; }; bus_open() { :; }; bus_say() { :; }
fi
# Attempt artefacts. ralph discarded the model's output and then reset the tree, so a stopped
# loop left nothing to diagnose with. See scripts/ralph-log.sh.
if [ -f "$(dirname "$0")/ralph-log.sh" ]; then
  . "$(dirname "$0")/ralph-log.sh"
else
  log_init() { :; }; log_path() { printf '/dev/null'; }; log_failure() { :; }; log_where() { :; }
fi
# Retry contract — track regressions across attempts. See scripts/ralph-retry.sh.
if [ -f "$(dirname "$0")/ralph-retry.sh" ]; then
  . "$(dirname "$0")/ralph-retry.sh"
else
  retry_init() { :; }; retry_record() { :; }; retry_regressions() { :; }
fi

# Navigation codesheet (repo map + shape-appropriate reference sheet), generated
# ONCE for the whole loop: byte-stable across every task and retry, so after the
# first attempt it rides the Beelink's prefix cache for ~free. Deliberately not
# regenerated after commits — stability beats freshness for caching, and each
# task is bounded anyway. Measured: 20-56% less context at equal-or-better
# accuracy (docs/research/codemap-serena-token-efficiency.md). RALPH_SHEET=off
# disables. oc gets OC_SHEET=off below so the sheet isn't injected twice.
SHEET=""
SHEET_GEN="$(dirname "$0")/gen-codesheet.mjs"
if [ "${RALPH_SHEET:-on}" = "on" ] && [ -f "$SHEET_GEN" ] && command -v node >/dev/null 2>&1; then
  SHEET="$(node "$SHEET_GEN" "$ROOT" 2>/dev/null || true)"
  [ -n "$SHEET" ] && echo "codesheet: injected (~$(( ${#SHEET} / 4 )) tokens, stable for the whole loop)"
fi

hb_init; log_init; hb_write starting
# Keep the heartbeat alive through the long model calls, and make sure it stops when this
# loop does — a heartbeat that outlives its loop would make a dead agent look busy forever.
hb_tick_start
trap 'hb_tick_stop' EXIT INT TERM
bus_init; bus_open "$(basename "$SPEC_DIR")"

while IFS= read -r task || [ -n "$task" ]; do
  [ -z "${task// }" ] && continue
  echo "════════ TASK: $task ════════"
  HB_TASK="$task"; HB_TIDX=$((HB_TIDX + 1)); hb_write running
  feedback=""; passed=0; retry_init
  for attempt in $(seq 1 $((RETRIES + 1))); do
    HB_ATTEMPT="$attempt"; hb_write running
    prompt="${SHEET:+$SHEET

}Read $SPEC. Implement ONLY this one task, nothing else: ${task}
Follow the spec's section 10 acceptance criteria and section 7 norms EXACTLY.
Do not run git add, git commit, or git stash — the loop owns the index.
Do not touch anything outside this task's scope. Reuse existing patterns; never invent
URLs/UIDs. When done, stop.${feedback}"

    # Fresh session each attempt (no -c/--continue) = no context bloat. oc adds the
    # 1Password key + a watchdog timeout so a stalled stream can't hang for hours.
    # OC_SHEET=off: the sheet is already in the prompt (once, loop-stable) above.
    # Keep the transcript. This used to go to /dev/null, which made every STOP undiagnosable.
    OC_SHEET=off OC_RUN_TIMEOUT="${OC_RUN_TIMEOUT:-480}" oc run --dir "$ROOT" "$prompt" \
      > "$(log_path "$HB_TASK" "$attempt")" 2>&1; _rc=$?
    # An executor that never started is NOT a failed attempt — it is a broken container, and
    # letting it fall through to verify is how a no-op run reports success. Observed 2026-07-22:
    # oc died in <1s with "current working directory was deleted" on every attempt, each log 247
    # bytes, and the loop happily marked 3/3 done. A real attempt (even one the watchdog kills at
    # OC_RUN_TIMEOUT) leaves a substantial transcript; a stillborn one leaves a stub.
    _log="$(log_path "$HB_TASK" "$attempt")"
    _sz=$(wc -c < "$_log" 2>/dev/null || echo 0)
    if [ "$_rc" != 0 ] && [ "$_sz" -lt 512 ]; then
      echo "✋ ABORT: the executor did not start (exit $_rc, ${_sz}B of output) — the container needs attention, not another retry." >&2
      sed 's/^/    | /' "$_log" 2>/dev/null | head -4 >&2
      hb_write stopped false; log_where
      bus_say "✋ ABORT — executor did not start (exit $_rc). Container needs attention."
      exit 3
    fi


    # A run that changed NOTHING is not a pass. The stillborn-log guard above catches an
    # executor that never STARTED; this catches one that started, was blocked, and wrote
    # nothing. It matters because a pend-staged gate (specs/TEMPLATE.md §11) is satisfied
    # by an empty tree — every check pends — so a no-op attempt sails through and the task
    # after it inherits the work plus a spent retry budget. Observed 2026-08-12 on
    # specs/model-watch: opencode asked to Read `/specs/model-watch/spec.md` (absolute,
    # from filesystem root), opencode auto-rejected it as an external directory, the model
    # produced no file, and the staged gate passed T1 with "nothing to commit".
    if [ -z "$(git -C "$ROOT" status --porcelain -- . ':!.evidence' 2>/dev/null)" ]; then
      echo "  ✗ attempt $attempt changed nothing — a no-op is a failure, not a pass" >&2
      hb_write failed false
      feedback="
A previous attempt produced NO file changes at all. If a tool call was rejected, use
paths RELATIVE to the repo root (specs/... not /specs/...). Do the work this time."
      continue
    fi

    # The gate: deterministic, external. The model does NOT get to say "done".
    hb_write verifying
    if out="$(cd "$ROOT" && bash "$VERIFY" 2>&1)"; then
      echo "  ✓ $task passed verify (attempt $attempt)"
      git -C "$ROOT" add -A
      git -C "$ROOT" commit -q -m "ralph(qwen): ${task%%:*} — ${task#*: }" || true
      passed=1; hb_write passed true
      bus_say "✓ ${task%%:*} passed verify (attempt $attempt/$((RETRIES + 1))) — ${HB_TIDX}/${HB_TOTAL:-?}"
      retry_record "$out"
      # $(dirname $0), NOT a bare `scripts/…`: that path was relative to the TARGET
      # worktree, and a project that correctly owns only specs and gates has no scripts/
      # dir at all. notes-from-hearing#9 removed the harness from the product repo exactly
      # as the convention asks, and every task of every run after it printed
      # "scripts/loop-index.py: No such file or directory". The harness must reach its own
      # tools by its own location.
      "$(dirname "$0")/loop-index.py" --repo "$ROOT" --spec "$SPEC_DIR" 2>&1 \
        || { echo "WARN: loop-index.py failed" >&2; }
      # loop-metrics.sh had NO CALLERS. It was written to answer "how is the loop doing" —
      # attempts per task, whether cost is falling, how much of the gate is real evidence —
      # and nothing ever invoked it, so .evidence/metrics.jsonl went stale and the 2026-08-25
      # run had no cost record of any kind. Wiring it here, beside the indexer, on the same
      # best-effort contract: recording a run must never be able to fail the run.
      SPEC_DIR="$SPEC_DIR" "$(dirname "$0")/loop-metrics.sh" \
        "${HB_TASK%%:*}" "$ROOT" "${LOG_DIR:-}" \
        >/dev/null 2>&1 || { echo "WARN: loop-metrics.sh failed" >&2; }
      # "Did work happen" and "was evidence collected" are two questions. The guard above
      # now excludes .evidence/ from the first one — which would silently hide a broken
      # indexer, since loop-index.py is best-effort. So ask the second question directly:
      # the row for this task must exist. Warn, never fail: recording the run must not be
      # able to fail the run it is recording.
      _idx="$ROOT/.evidence/index-$(basename "$SPEC_DIR").jsonl"
      if [ ! -s "$_idx" ]; then
        echo "WARN: no $(basename "$_idx") after ${HB_TASK%% *} — the record was not collected" >&2
      elif ! grep -q "\"task\": *\"${HB_TASK%% *}\"" "$_idx" 2>/dev/null; then
        echo "WARN: $(basename "$_idx") has no row for ${HB_TASK%% *} — indexing ran but did not record this task" >&2
      fi
      break
    fi
    echo "  ✗ verify failed (attempt $attempt); retrying with feedback" >&2
    hb_write failed false
    log_failure "$HB_TASK" "$attempt" "$out"   # BEFORE the reset below erases the evidence
    retry_record "$out"
    # Feed the failing checks back into the next fresh attempt — targeted, not vibes.
    _regression_block=""
    if _rb="$(retry_regressions "$out")" && [ -n "$_rb" ]; then
      _regression_block="
REGRESSION — these checks PASSED in an earlier attempt of this same task and now do not:
$_rb
Keep them passing while you fix the failures above. Do not trade one check for another."
    fi
    feedback="
A previous attempt FAILED verification with:
$(printf '%s' "$out" | grep -E 'FAIL|VERIFY' | head -20)
Fix exactly those failures.${_regression_block}"
    git -C "$ROOT" reset -q -- . 2>/dev/null || true   # reset index to HEAD so checkout -- can drop staged files
    git -C "$ROOT" checkout -- . 2>/dev/null || true   # reset tracked changes from the bad attempt
    git -C "$ROOT" clean -fd -- . 2>/dev/null || true  # ...and untracked files/dirs it created —
    # `checkout --` alone leaves these behind, letting an out-of-scope file from attempt N
    # survive into attempt N+1 (and even arm a later task's PEND-gated checks early — see
    # the rom-library-structure dogfood PR for the real failure this caused).
  done

  if [ "$passed" != 1 ]; then
    echo "✋ STOP: '$task' failed verify after $((RETRIES + 1)) attempts — needs a human." >&2
    hb_write stopped false
    log_where
    bus_say "✋ STOP — '${task%%:*}' failed verify after $((RETRIES + 1)) attempts. Needs a human."
    exit 2
  fi
done < "$TASKS"

# Presence-gated checks pend until their target exists, so passing every task individually does
# NOT prove the work was done — see the STRICT note in verify.sh. Run the gate once more with
# pending treated as failure before declaring victory.
if ! _strict_out="$(cd "$ROOT" && STRICT=1 bash "$VERIFY" 2>&1)"; then
  echo "✋ STOP: every task passed, but the final STRICT gate found unbuilt work:" >&2
  printf '%s\n' "$_strict_out" | grep -E 'FAIL' | head -10 >&2
  hb_write stopped false; log_where
  bus_say "✋ STOP — tasks passed individually but the final strict gate found unbuilt work."
  exit 2
fi

hb_write done true
bus_say "done — ${HB_TOTAL:-?}/${HB_TOTAL:-?} tasks passed verify on $(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null). Branch ready for PR review."
echo "════════ all tasks passed verify — branch ready for PR review ════════"
git -C "$ROOT" log --oneline -"$(grep -cve '^[[:space:]]*$' "$TASKS")"
