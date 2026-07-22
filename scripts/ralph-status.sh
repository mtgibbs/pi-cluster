# ralph-status.sh — durable heartbeat for ralph loops. SOURCED, not executed.
#
# Why: a ralph loop's live state (which task, which attempt, pass/fail) only
# ever existed in stdout → tmux scrollback. Nothing on disk, nothing a
# dashboard could read without attaching the tmux session. This writes one
# small JSON status file per running loop so a collector can answer "what is
# this agent doing right now?" over `docker exec cat` — no tmux, no guessing.
#
# Contract — file: $RALPH_STATUS_DIR/<agent>-<pid>.json (default dir
# ~/.harness/status). Written ATOMICALLY (tmp + mv) so a reader never sees a
# half-written object. Fields:
#   agent pid repo branch spec task task_index total_tasks attempt
#   max_attempts phase verify_pass last_commit started updated
# phase ∈ starting | running | verifying | passed | failed | stopped | done
# verify_pass ∈ true | false | null   (JSON literals, unquoted)
# started/updated/… are unix seconds.
#
# Liveness rule for a collector: a file whose phase is running|verifying but
# whose `updated` is more than a few minutes old is a DEAD loop (a killed
# process can't update its own file) — treat it as stale, not active.
#
# Best-effort by design: every write is guarded so a full disk, a missing
# $HOME, or a read-only mount can NEVER fail the loop it's reporting on.

# Escape a string for embedding in a JSON double-quoted value.
_hb_esc() {
  printf '%s' "${1-}" \
    | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e ':a;N;$!ba;s/\n/\\n/g' -e 's/\t/\\t/g'
}

# hb_init — call once after ROOT / SPEC_DIR / TASKS / RETRIES are known.
hb_init() {
  HB_AGENT="${RALPH_AGENT:-qwen}"
  HB_ROOT="${ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
  HB_REPO="$(basename "$HB_ROOT" 2>/dev/null || echo '?')"
  HB_SPEC="${SPEC_DIR:-}"
  HB_TOTAL="$(grep -cve '^[[:space:]]*$' "${TASKS:-/dev/null}" 2>/dev/null || echo 0)"
  HB_MAX="$(( ${RETRIES:-2} + 1 ))"
  HB_STARTED="$(date +%s 2>/dev/null || echo 0)"
  HB_TASK=""; HB_TIDX=0; HB_ATTEMPT=0
  HB_DIR="${RALPH_STATUS_DIR:-$HOME/.harness/status}"
  mkdir -p "$HB_DIR" 2>/dev/null || true
  HB_FILE="$HB_DIR/${HB_AGENT}-$$.json"
  # Cap accumulation: drop this agent's terminal files older than a day.
  find "$HB_DIR" -name "${HB_AGENT}-*.json" -mmin +1440 -delete 2>/dev/null || true
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
