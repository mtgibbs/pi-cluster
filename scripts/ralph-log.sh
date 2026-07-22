# shellcheck shell=bash
# ralph-log.sh — keep the evidence from a failed attempt. SOURCED, not executed.
#
# WHY: ralph sent the model's entire output to /dev/null, and resets the working tree after
# EVERY failed attempt — including the last one. So a loop that stopped left a stopped loop, an
# empty diff, and nothing else. On 2026-07-22 a run failed all three attempts on one task and it
# was impossible to tell whether the model had written the wrong code, or written the right code
# in the wrong place. Those point at completely different fixes; without the artefact you can
# only re-roll and hope.
#
# A gate that says "no" without saying what it saw is only half an inspector.
#
# Writes, per failed attempt, to $RALPH_LOG_DIR/<agent>-<pid>/:
#   T<idx>-attempt<n>.log    the executor's own stdout+stderr
#   T<idx>-attempt<n>.diff   the verify output, the tracked diff, and the untracked file list
#                            — captured BEFORE the reset that would otherwise erase it
#
# Best-effort, same contract as ralph-status.sh: a full disk or a read-only mount can never fail
# the loop it is reporting on. RALPH_LOG=off disables.

log_init() {
  LOG_OK=0
  [ "${RALPH_LOG:-on}" = "on" ] || { echo "logs: off (RALPH_LOG=off)" >&2; return 0; }
  LOG_ROOT="${RALPH_LOG_DIR:-$HOME/.harness/logs}"
  LOG_DIR="$LOG_ROOT/${HB_AGENT:-${RALPH_AGENT:-agent}}-$$"
  mkdir -p "$LOG_DIR" 2>/dev/null || { echo "logs: unavailable ($LOG_DIR not writable)" >&2; return 0; }
  # Cap accumulation the same way the heartbeat does — these hold whole model transcripts.
  find "$LOG_ROOT" -maxdepth 1 -type d -mmin "+${RALPH_LOG_KEEP_MIN:-4320}" -exec rm -rf {} + 2>/dev/null || true
  LOG_OK=1
  echo "logs: $LOG_DIR" >&2
}

# log_path <task-index> <attempt> [ext] — where this attempt's artefact goes.
# Prints /dev/null when logging is unavailable, so callers can redirect unconditionally.
log_path() {
  [ "${LOG_OK:-0}" = 1 ] || { printf '/dev/null'; return 0; }
  printf '%s/T%s-attempt%s.%s' "$LOG_DIR" "${1:-0}" "${2:-0}" "${3:-log}"
}

# log_failure <task-index> <attempt> <verify-output>
# MUST be called before `git checkout -- .` / `git clean -fd`, which is the whole point: after
# the reset the evidence is gone.
log_failure() {
  [ "${LOG_OK:-0}" = 1 ] || return 0
  local f; f="$(log_path "$1" "$2" diff)"
  {
    printf '=== verify output ===\n%s\n\n' "${3:-（none captured）}"
    printf '=== tracked changes (git diff) ===\n'
    git -C "${ROOT:-.}" diff 2>/dev/null
    printf '\n=== untracked files created ===\n'
    git -C "${ROOT:-.}" ls-files --others --exclude-standard 2>/dev/null
  } > "$f" 2>/dev/null || true
}

# log_where — one line telling a human where to look. Called on STOP.
log_where() {
  [ "${LOG_OK:-0}" = 1 ] || return 0
  echo "   evidence: $LOG_DIR  (.log = what the model did, .diff = what it changed + why verify said no)" >&2
}
