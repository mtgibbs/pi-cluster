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
# Writes, per failed attempt, to $RALPH_LOG_DIR/<repo>/<agent>-<pid>/:
#   <task>-attempt<n>.log    the executor's own stdout+stderr
#   <task>-attempt<n>.diff   the verify output, the tracked diff, and the untracked file list
#                            — captured BEFORE the reset that would otherwise erase it
#
# <task> is the TASK LABEL (T21), not the queue position. Those coincide on a cold start and
# diverge the moment anything is requeued: a single-task rerun and a fourteen-task run both
# used to write `T1-attempt1.log`, so the name collided across every run in the root and named
# a different task nearly every time. Twelve surviving T21 logs across five runs had to be
# re-attributed by parsing the PID out of the directory name (2026-08-24 observability brief,
# D1). The queue index still rides in the JSON status, where it is cheap and unambiguous.
#
# <repo> scopes the root per project (D2). One flat directory collected three unrelated
# repos' runs into one evidence bundle, distinguishable only by grepping the transcripts for
# a working directory — and a recycled PID would have merged two projects into one directory
# outright. An explicit RALPH_LOG_DIR is used verbatim; only the DEFAULT is scoped, so every
# gate that redirects this channel to a temp dir keeps working unchanged.
#
# Best-effort, same contract as ralph-status.sh: a full disk or a read-only mount can never fail
# the loop it is reporting on. RALPH_LOG=off disables.

log_init() {
  LOG_OK=0
  [ "${RALPH_LOG:-on}" = "on" ] || { echo "logs: off (RALPH_LOG=off)" >&2; return 0; }
  LOG_ROOT="${RALPH_LOG_DIR:-$HOME/.harness/logs/$(basename "$(git -C "${ROOT:-.}" rev-parse --show-toplevel 2>/dev/null || echo unknown-repo)")}"
  LOG_DIR="$LOG_ROOT/${HB_AGENT:-${RALPH_AGENT:-agent}}-$$"
  mkdir -p "$LOG_DIR" 2>/dev/null || { echo "logs: unavailable ($LOG_DIR not writable)" >&2; return 0; }
  # Cap accumulation the same way the heartbeat does — these hold whole model transcripts.
  # -mindepth 1: `find X -maxdepth 1 -type d` matches X itself, so without it a stale root
  # would delete the whole store. It has never fired (mkdir -p above refreshes the root's
  # mtime first), but the guard costs nothing and the failure mode is total.
  find "$LOG_ROOT" -mindepth 1 -maxdepth 1 -type d -mmin "+${RALPH_LOG_KEEP_MIN:-4320}" -exec rm -rf {} + 2>/dev/null || true
  LOG_OK=1
  echo "logs: $LOG_DIR" >&2
}

# log_task <task-line> — the filename-safe label for a task ("T21: do the thing" -> "T21").
# Callers pass the whole task line; this takes the label and guarantees it is a FILENAME. A task
# title containing a slash would otherwise produce a path, and one containing a space would
# produce two arguments. Anything not a bare word collapses to `Tx`.
# Note what this deliberately does NOT do: coerce a non-`T<n>` label into one. Every tasks.txt in
# this repo labels `T<n>:`, and a run that does not will surface in `loop-doctor` as `unparsed`
# rather than as a plausible wrong number. Visible beats tidy.
log_task() {
  local t="${1:-}"; t="${t%%:*}"; t="${t%%[[:space:]]*}"
  case "$t" in
    ''|*[!A-Za-z0-9_-]*) printf 'Tx' ;;
    *)                   printf '%s' "$t" ;;
  esac
}

# log_path <task-label> <attempt> [ext] — where this attempt's artefact goes.
# Prints /dev/null when logging is unavailable, so callers can redirect unconditionally.
log_path() {
  [ "${LOG_OK:-0}" = 1 ] || { printf '/dev/null'; return 0; }
  printf '%s/%s-attempt%s.%s' "$LOG_DIR" "$(log_task "${1:-T0}")" "${2:-0}" "${3:-log}"
}

# log_failure <task-label> <attempt> <verify-output>
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
