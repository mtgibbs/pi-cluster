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

hb_init; hb_write starting
# Keep the heartbeat alive through the long model calls, and make sure it stops when this
# loop does — a heartbeat that outlives its loop would make a dead agent look busy forever.
hb_tick_start
trap 'hb_tick_stop' EXIT INT TERM
bus_init; bus_open "$(basename "$SPEC_DIR")"

while IFS= read -r task || [ -n "$task" ]; do
  [ -z "${task// }" ] && continue
  echo "════════ TASK: $task ════════"
  HB_TASK="$task"; HB_TIDX=$((HB_TIDX + 1)); hb_write running
  feedback=""; passed=0
  for attempt in $(seq 1 $((RETRIES + 1))); do
    HB_ATTEMPT="$attempt"; hb_write running
    prompt="${SHEET:+$SHEET

}Read $SPEC. Implement ONLY this one task, nothing else: ${task}
Follow the spec's section 10 reference and section 7 acceptance criteria EXACTLY.
Do not touch anything outside this task's scope. Reuse existing patterns; never invent
URLs/UIDs. When done, stop.${feedback}"

    # Fresh session each attempt (no -c/--continue) = no context bloat. oc adds the
    # 1Password key + a watchdog timeout so a stalled stream can't hang for hours.
    # OC_SHEET=off: the sheet is already in the prompt (once, loop-stable) above.
    OC_SHEET=off OC_RUN_TIMEOUT="${OC_RUN_TIMEOUT:-480}" oc run --dir "$ROOT" "$prompt" >/dev/null 2>&1 || true

    # The gate: deterministic, external. The model does NOT get to say "done".
    hb_write verifying
    if out="$(cd "$ROOT" && bash "$VERIFY" 2>&1)"; then
      echo "  ✓ $task passed verify (attempt $attempt)"
      git -C "$ROOT" add -A
      git -C "$ROOT" commit -q -m "ralph(qwen): ${task%%:*} — ${task#*: }" || true
      passed=1; hb_write passed true
      bus_say "✓ ${task%%:*} passed verify (attempt $attempt/$((RETRIES + 1))) — ${HB_TIDX}/${HB_TOTAL:-?}"
      break
    fi
    echo "  ✗ verify failed (attempt $attempt); retrying with feedback" >&2
    hb_write failed false
    # Feed the failing checks back into the next fresh attempt — targeted, not vibes.
    feedback="
A previous attempt FAILED verification with:
$(printf '%s' "$out" | grep -E 'FAIL|VERIFY' | head -20)
Fix exactly those failures."
    git -C "$ROOT" checkout -- . 2>/dev/null || true   # reset tracked changes from the bad attempt
    git -C "$ROOT" clean -fd -- . 2>/dev/null || true  # ...and untracked files/dirs it created —
    # `checkout --` alone leaves these behind, letting an out-of-scope file from attempt N
    # survive into attempt N+1 (and even arm a later task's PEND-gated checks early — see
    # the rom-library-structure dogfood PR for the real failure this caused).
  done

  if [ "$passed" != 1 ]; then
    echo "✋ STOP: '$task' failed verify after $((RETRIES + 1)) attempts — needs a human." >&2
    hb_write stopped false
    bus_say "✋ STOP — '${task%%:*}' failed verify after $((RETRIES + 1)) attempts. Needs a human."
    exit 2
  fi
done < "$TASKS"

hb_write done true
bus_say "done — ${HB_TOTAL:-?}/${HB_TOTAL:-?} tasks passed verify on $(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null). Branch ready for PR review."
echo "════════ all tasks passed verify — branch ready for PR review ════════"
git -C "$ROOT" log --oneline -"$(grep -cve '^[[:space:]]*$' "$TASKS")"
