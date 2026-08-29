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
# Writes, per failed attempt, to $RALPH_LOG_DIR/<spec-slug>/<agent>-<pid>/:
#   <task>-attempt<n>.log    the executor's own stdout+stderr
#   <task>-attempt<n>.diff   the verify output, the tracked diff, and the untracked file list
#                            — captured BEFORE the reset that would otherwise erase it
#
# <spec-slug> is the spec directory's basename (`specs/asset-ladder` -> `asset-ladder`), and it
# is a DIRECTORY LEVEL rather than part of the leaf name. Two reasons, in order:
#
#   1. A flat root grows without bound and without shape. Five specs over one night produced
#      48 sibling `qwen-<pid>` directories; at a few hundred runs `ls` alone is unreadable and
#      every consumer pays to enumerate the whole store to answer a question about one spec.
#      A level you can walk down costs nothing and bounds every listing to one feature.
#   2. It keeps the leaf EXACTLY `<agent>-<pid>`, which is what every existing reader parses.
#      `loop-index.py` takes the pid with `basename(d).split("-", 1)[1]`; folding the slug into
#      the leaf instead (`qwen-asset-ladder-37173`) yields "asset-ladder-37173", a pid that
#      matches no status file — the index would still generate, with every run unattributed.
#      Nesting changes the path and leaves the name alone, so nothing downstream has to know.
#
# `harness_roots()` in loop-index.py already descends exactly one level and already skips
# entries prefixed `qwen-`/`codex-` as run dirs rather than scopes, so it discovers this layout
# unchanged. `.evidence/judge/<spec>/` and `.evidence/supervisor/<spec>/` are keyed the same
# way, so all four subtrees now group on one identifier.
#
# <task> is the TASK LABEL (T21), not the queue position. Those coincide on a cold start and
# diverge the moment anything is requeued: a single-task rerun and a fourteen-task run both
# used to write `T1-attempt1.log`, so the name collided across every run in the root and named
# a different task nearly every time. Twelve surviving T21 logs across five runs had to be
# re-attributed by parsing the PID out of the directory name (2026-08-24 observability brief,
# D1). The queue index still rides in the JSON status, where it is cheap and unambiguous.
#
# The ROOT is scoped per project by living inside the target repo's own `.evidence/` (D2).
# One shared directory collected three unrelated repos' runs into a single evidence bundle,
# distinguishable only by grepping the transcripts for a working directory — and a recycled
# PID would have merged two projects into one directory outright. An explicit RALPH_LOG_DIR is
# used verbatim; only the DEFAULT is scoped, so every gate that redirects this channel to a
# temp dir keeps working unchanged. Project scope is the root, feature scope is the slug level
# below it, and the PID identifies the process — three questions, three levels, no overloading.
#
# Best-effort, same contract as ralph-status.sh: a full disk or a read-only mount can never fail
# the loop it is reporting on. RALPH_LOG=off disables.

# _ralph_slug <spec-dir> — the feature identifier: the spec directory's basename, lowercased
# and reduced to a single filename-safe path component ("specs/Asset Ladder/" -> "asset-ladder").
# Falls back to "nospec" so the level is never empty and a run can never land in the root.
#
# Deliberately duplicated verbatim in ralph-status.sh. Both files are best-effort helpers whose
# contract is that either may be absent without breaking the loop, so neither may depend on the
# other. Keep the two copies identical.
#
# Derived at runtime from SPEC_DIR — never a literal. specs/evidence-convention AC-5 forbids any
# project's name appearing in a harness file, and that is the whole point: the harness learns the
# feature from the target repo it was pointed at.
_ralph_slug() {
  local s="${1:-}"
  s="${s%/}"; s="${s##*/}"
  s="$(printf '%s' "$s" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9._-' '-' \
        | sed -e 's/-\{2,\}/-/g' -e 's/^[-.]*//' -e 's/-*$//' | cut -c1-40)"
  printf '%s' "${s:-nospec}"
}

log_init() {
  LOG_OK=0
  [ "${RALPH_LOG:-on}" = "on" ] || { echo "logs: off (RALPH_LOG=off)" >&2; return 0; }
  LOG_ROOT="${RALPH_LOG_DIR:-$(git -C "${ROOT:-.}" rev-parse --show-toplevel 2>/dev/null || echo "$HOME/.harness")/.evidence/runs}"
  # Prefer the heartbeat's slug when ralph-status.sh is loaded, so the two stores can never
  # disagree about which feature a run belongs to; derive our own when it is absent.
  LOG_SLUG="${HB_SLUG:-$(_ralph_slug "${SPEC_DIR:-}")}"
  LOG_DIR="$LOG_ROOT/$LOG_SLUG/${HB_AGENT:-${RALPH_AGENT:-agent}}-$$"
  mkdir -p "$LOG_DIR" 2>/dev/null || { echo "logs: unavailable ($LOG_DIR not writable)" >&2; return 0; }
  # Cap accumulation the same way the heartbeat does — these hold whole model transcripts.
  #
  # DEPTH 2, not 1: a run directory now lives at <root>/<slug>/<agent>-<pid>, so depth 1 is the
  # SPEC. Reaping there would delete a feature's entire run history in one stroke the moment the
  # spec went quiet — and a directory's mtime tracks its newest child, so an active spec would
  # look immortal right up until it didn't. Expiry is per run; only whole runs age out.
  #
  # -mindepth is also what keeps `find X -maxdepth N -type d` from matching X itself, which
  # would rm -rf the entire store. That has never fired (the mkdir -p above refreshes the root's
  # mtime first), but the guard costs nothing and the failure mode is total.
  find "$LOG_ROOT" -mindepth 2 -maxdepth 2 -type d -mmin "+${RALPH_LOG_KEEP_MIN:-4320}" -exec rm -rf {} + 2>/dev/null || true
  # …then sweep up the slug directories the reap just emptied, so a finished feature leaves no
  # husk behind. Ours always holds the run dir created above, so it is never a candidate.
  find "$LOG_ROOT" -mindepth 1 -maxdepth 1 -type d -empty -delete 2>/dev/null || true
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
    # …and their CONTENTS, not just their names.
    #
    # `git diff` covers tracked files only, so for any task whose deliverable is a NEW file —
    # which is most net-new work — this evidence recorded a filename and nothing else, and
    # `git clean -fd` then deleted the file. Observed 2026-08-25 on specs/asset-ladder T3:
    # three attempts each wrote VoiceCapture/SpeechAssetProbe.swift, the gate reported 16 of
    # 20 checks passing, and the run could not be replayed or salvaged because the only
    # surviving trace was the path.
    printf '\n=== untracked file contents ===\n'
    git -C "${ROOT:-.}" ls-files --others --exclude-standard -z 2>/dev/null \
    | while IFS= read -r -d '' _p; do
        case "$_p" in .evidence/*) continue ;; esac   # our own record, not the model's work
        _abs="${ROOT:-.}/$_p"
        [ -f "$_abs" ] || continue
        # Skip anything that is not text, and cap each file: this is diagnostic evidence, not
        # a backup, and one stray binary would make the whole .diff unreadable.
        if LC_ALL=C grep -qI . "$_abs" 2>/dev/null; then
          printf -- '--- %s ---\n' "$_p"
          head -c 65536 "$_abs" 2>/dev/null
          [ "$(wc -c < "$_abs" 2>/dev/null || echo 0)" -gt 65536 ] \
            && printf '\n[truncated at 64 KiB]\n'
          printf '\n'
        else
          printf -- '--- %s --- [binary, not captured]\n' "$_p"
        fi
      done
  } > "$f" 2>/dev/null || true
}

# log_where — one line telling a human where to look. Called on STOP.
log_where() {
  [ "${LOG_OK:-0}" = 1 ] || return 0
  echo "   evidence: $LOG_DIR  (.log = what the model did, .diff = what it changed + why verify said no)" >&2
}
