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

while IFS= read -r task || [ -n "$task" ]; do
  [ -z "${task// }" ] && continue
  echo "════════ TASK: $task ════════"
  feedback=""; passed=0
  for attempt in $(seq 1 $((RETRIES + 1))); do
    prompt="Read $SPEC. Implement ONLY this one task, nothing else: ${task}
Follow the spec's section 10 reference and section 7 acceptance criteria EXACTLY.
Do not touch anything outside this task's scope. Reuse existing patterns; never invent
URLs/UIDs. When done, stop.${feedback}"

    # Fresh session each attempt (no -c/--continue) = no context bloat. oc adds the
    # 1Password key + a watchdog timeout so a stalled stream can't hang for hours.
    OC_RUN_TIMEOUT="${OC_RUN_TIMEOUT:-480}" oc run --dir "$ROOT" "$prompt" >/dev/null 2>&1 || true

    # The gate: deterministic, external. The model does NOT get to say "done".
    if out="$(cd "$ROOT" && bash "$VERIFY" 2>&1)"; then
      echo "  ✓ $task passed verify (attempt $attempt)"
      git -C "$ROOT" add -A
      git -C "$ROOT" commit -q -m "ralph(qwen): ${task%%:*} — ${task#*: }" || true
      passed=1; break
    fi
    echo "  ✗ verify failed (attempt $attempt); retrying with feedback" >&2
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
    exit 2
  fi
done < "$TASKS"

echo "════════ all tasks passed verify — branch ready for PR review ════════"
git -C "$ROOT" log --oneline -"$(grep -cve '^[[:space:]]*$' "$TASKS")"
