# ralph-status.sh — durable heartbeat for ralph loops. SOURCED, not executed.
#
# Why: a ralph loop's live state (which task, which attempt, pass/fail) only
# ever existed in stdout → tmux scrollback. Nothing on disk, nothing a
# dashboard could read without attaching the tmux session. This writes one
# small JSON status file per running loop so a collector can answer "what is
# this agent doing right now?" over `docker exec cat` — no tmux, no guessing.
#
# Contract — file: $RALPH_STATUS_DIR/<spec-slug>/<agent>-<pid>.json (the root
# defaults to the target repo's own .evidence/status, scoped so two projects'
# loops cannot collide on a recycled PID; an explicit RALPH_STATUS_DIR is used
# verbatim). <spec-slug> is the spec directory's basename — the same level
# ralph-log.sh puts run dirs under, and the same key .evidence/judge/<spec>/ and
# .evidence/supervisor/<spec>/ already use, so the four stores walk alike.
#
# The slug is a DIRECTORY, not part of the filename: `scripts/harness` and
# loop-index.py both parse the pid out of the leaf, and both already handle one
# level of nesting (`status/*.json` and `status/*/*.json`; harness_roots()).
# Renaming the leaf would have broken those parsers; adding a level does not.
# Environment variables:
#   RALPH_STATUS_DIR — output root (default <target-repo>/.evidence/status)
#   RALPH_STATUS_KEEP_MIN — status file retention in minutes (default 1440)
# Written
# ATOMICALLY (tmp + mv) so a reader never sees a half-written object. Fields:
#   agent pid repo branch spec task task_index total_tasks attempt
#   max_attempts phase verify_pass last_commit started updated
# phase ∈ starting | running | verifying | passed | failed | stopped | done
#       | killed | stalled | timeout          (the last three: see hb_mark)
# verify_pass ∈ true | false | null   (JSON literals, unquoted)
# started/updated/… are unix seconds.
#
# Liveness rule for a collector: a file whose phase is running|verifying but
# whose `updated` is more than a few minutes old is a DEAD loop (a killed
# process can't update its own file) — treat it as stale, not active.
#
# That rule works LIVE and is worthless afterwards: at any later date every run
# is stale, so a killed run and a completed one read identically. Whoever ends a
# loop should therefore write its epitaph — see hb_mark, and the supervisor that
# calls it. Four killed runs sat at `running` permanently before this existed
# (2026-08-24 observability brief, D5).
#
# Best-effort by design: every write is guarded so a full disk, a missing
# $HOME, or a read-only mount can NEVER fail the loop it's reporting on.

# _ralph_slug <spec-dir> — the feature identifier: the spec directory's basename,
# lowercased and reduced to a single filename-safe path component
# ("specs/Asset Ladder/" -> "asset-ladder"). Falls back to "nospec" so the level is
# never empty and a status file can never land in the root.
#
# Deliberately duplicated verbatim in ralph-log.sh. Both files are best-effort
# helpers whose contract is that either may be absent without breaking the loop, so
# neither may depend on the other. Keep the two copies identical.
#
# Derived at runtime from SPEC_DIR — never a literal. specs/evidence-convention AC-5
# forbids any project's name appearing in a harness file, and that is the point: the
# harness learns the feature from the target repo it was pointed at.
_ralph_slug() {
  local s="${1:-}"
  s="${s%/}"; s="${s##*/}"
  s="$(printf '%s' "$s" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9._-' '-' \
        | sed -e 's/-\{2,\}/-/g' -e 's/^[-.]*//' -e 's/-*$//' | cut -c1-40)"
  printf '%s' "${s:-nospec}"
}

# Escape a string for embedding in a JSON double-quoted value.
_hb_esc() {
  printf '%s' "${1-}" \
    | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e ':a;N;$!ba;s/\n/\\n/g' -e 's/\t/\\t/g'
}

# hb_init — call once after ROOT / SPEC_DIR / TASKS / RETRIES are known.
hb_init() {
  HB_AGENT="${RALPH_AGENT:-qwen}"
  HB_ROOT="${ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
  # HB_REPO is now a PATH COMPONENT (HB_DIR below), not just a JSON field. A relative ROOT
  # would make it "." and silently un-scope the store back into the shared root — which is the
  # exact contamination the scoping exists to prevent. Resolve, then reject the degenerate cases.
  HB_REPO="$(basename "$(git -C "$HB_ROOT" rev-parse --show-toplevel 2>/dev/null \
                         || (cd "$HB_ROOT" 2>/dev/null && pwd) \
                         || printf '%s' "$HB_ROOT")" 2>/dev/null || echo '')"
  case "$HB_REPO" in ''|.|..|/) HB_REPO="unknown-repo" ;; esac
  HB_SPEC="${SPEC_DIR:-}"
  HB_TOTAL="$(grep -cve '^[[:space:]]*$' "${TASKS:-/dev/null}" 2>/dev/null || echo 0)"
  HB_MAX="$(( ${RETRIES:-2} + 1 ))"
  HB_STARTED="$(date +%s 2>/dev/null || echo 0)"
  HB_TASK=""; HB_TIDX=0; HB_ATTEMPT=0
  HB_SLUG="$(_ralph_slug "$HB_SPEC")"
  HB_DIR="${RALPH_STATUS_DIR:-$(git -C "${ROOT:-.}" rev-parse --show-toplevel 2>/dev/null || echo "$HOME/.harness")/.evidence/status}"
  # The root stays addressable: the sweeps below run from it so they still span every spec,
  # not just the one this loop happens to be running. HB_DIR then descends into this run's
  # feature. Assigned in this order deliberately — evidence-convention's AC-1 gate reads the
  # FIRST `HB_DIR=` line and requires the override seam and the .evidence default to be
  # visible on it, so the root keeps that shape and the slug is appended after.
  HB_STATUS_ROOT="$HB_DIR"
  HB_DIR="$HB_DIR/$HB_SLUG"
  HB_FILE="$HB_DIR/${HB_AGENT}-$$.json"
  # Cap accumulation: drop this agent's terminal files older than a day.
  #
  # BEFORE the mkdir below, not after: unlike ralph-log.sh — whose slug directory always holds
  # the run dir it just created — this store's file is not written until the first hb_write, so
  # a slug directory created here would still be empty when the -empty sweep ran and would be
  # deleted out from under it. Sweep first, then create.
  #
  # Swept from the ROOT, not from our own slug directory. The sweep has no -maxdepth, so
  # rooting it here keeps it reaching every spec's files the way it did when the store was
  # flat; rooted at $HB_DIR it would only ever reap the spec currently being run, and any
  # feature that finished would keep its files forever — an accumulation cap that stops
  # capping the moment you move on is worse than none, because it still looks like one.
  find "$HB_STATUS_ROOT" -name "${HB_AGENT}-*.json" -mmin "+${RALPH_STATUS_KEEP_MIN:-1440}" -delete 2>/dev/null || true
  # Slug directories emptied by that sweep, same as ralph-log.sh. Ours gets its file below.
  find "$HB_STATUS_ROOT" -mindepth 1 -maxdepth 1 -type d -empty -delete 2>/dev/null || true
  mkdir -p "$HB_DIR" 2>/dev/null || true
}

# hb_write <phase> [verify_pass]  — emit the current status. Never fails.
hb_write() {
  [ -n "${HB_FILE:-}" ] || return 0
  local phase="${1:-running}" verify="${2:-null}" now branch commit
  now="$(date +%s 2>/dev/null || echo 0)"
  branch="$(git -C "$HB_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
  commit="$(git -C "$HB_ROOT" rev-parse --short HEAD 2>/dev/null || echo '')"
  {
    printf '{"agent":"%s","pid":%s,"repo":"%s","branch":"%s","spec":"%s",' \
      "$(_hb_esc "$HB_AGENT")" "$$" "$(_hb_esc "$HB_REPO")" \
      "$(_hb_esc "$branch")" "$(_hb_esc "$HB_SPEC")"
    printf '"task":"%s","task_index":%s,"total_tasks":%s,"attempt":%s,"max_attempts":%s,' \
      "$(_hb_esc "$HB_TASK")" "${HB_TIDX:-0}" "${HB_TOTAL:-0}" "${HB_ATTEMPT:-0}" "${HB_MAX:-0}"
    printf '"phase":"%s","verify_pass":%s,"last_commit":"%s","started":%s,"updated":%s}\n' \
      "$phase" "$verify" "$(_hb_esc "$commit")" "${HB_STARTED:-0}" "$now"
  } > "$HB_FILE.tmp" 2>/dev/null && mv -f "$HB_FILE.tmp" "$HB_FILE" 2>/dev/null || true
}

# hb_mark <status-file> <phase> — stamp a TERMINAL phase on a file this process does NOT own.
#
# For a supervisor that has just killed a hung loop. The killed process cannot write its own
# final state, so the file freezes at whatever it last said — `running`, forever. The collector's
# staleness rule papers over that while the run is recent and stops meaning anything once it is
# not. A record whose last state was written by whoever ended it needs no heuristic to read.
#
# Call it AFTER the kill, so the victim's keep-alive ticker (which dies with its parent) cannot
# race the write back to `running`. Rewrites in place, atomically, and never fails: a supervisor
# must not die because it could not annotate a log.
hb_mark() {
  local f="${1:-}" phase="${2:-killed}" now
  [ -f "$f" ] || return 0
  now="$(date +%s 2>/dev/null || echo 0)"
  sed -e "s/\"phase\":\"[^\"]*\"/\"phase\":\"$phase\"/" \
      -e "s/\"updated\":[0-9]*/\"updated\":$now/" "$f" > "$f.mark" 2>/dev/null \
    && mv -f "$f.mark" "$f" 2>/dev/null || true
}

# --- keep-alive ticker -------------------------------------------------------------------
# hb_write only fires at TRANSITIONS: task start, attempt start, verify, pass/fail. Between
# them sits a single model call bounded at OC_RUN_TIMEOUT (480s by default). So the file went
# untouched for up to eight minutes while the agent was working hardest, the collector's
# 120s staleness rule marked it dead, and pulse drew a resting atom. Watched a real run against
# the live board on 2026-07-22 and the house looked asleep the entire time.
#
# The ticker refreshes only the `updated` field, re-reading the file each pass, so it always
# carries whatever phase hb_write last wrote — no stale copy of the loop's variables.
#
# It MUST die with the loop. If a killed loop kept its heartbeat fresh, "stale means dead" —
# the collector's only liveness signal — would stop meaning anything, and a crashed agent would
# glow on the board forever. Hence the kill -0 check on the parent, plus hb_tick_stop on exit.
hb_tick_stop() {
  # `wait` inside the redirected block swallows the shell's own "Terminated: 15" job-control
  # notice, which otherwise prints on every clean exit and looks like a crash in the tmux log.
  if [ -n "${HB_TICKER:-}" ]; then
    { kill "$HB_TICKER" 2>/dev/null; wait "$HB_TICKER" 2>/dev/null; } 2>/dev/null || true
  fi
  HB_TICKER=""
}

hb_tick_start() {
  [ -n "${HB_FILE:-}" ] || return 0
  hb_tick_stop
  (
    parent=$$
    while kill -0 "$parent" 2>/dev/null; do
      sleep "${HB_TICK_SEC:-20}"
      kill -0 "$parent" 2>/dev/null || break
      [ -f "$HB_FILE" ] || continue
      now="$(date +%s 2>/dev/null || echo 0)"
      sed "s/\"updated\":[0-9]*/\"updated\":$now/" "$HB_FILE" > "$HB_FILE.tick" 2>/dev/null \
        && mv -f "$HB_FILE.tick" "$HB_FILE" 2>/dev/null
    done
  ) &
  HB_TICKER=$!
}
