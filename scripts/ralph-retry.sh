# shellcheck shell=bash
# ralph-retry.sh — track regressions across attempts. SOURCED, not executed.
#
# WHY: a failed attempt's work is discarded before the next retry, but nothing told the next
# attempt what already passed in a prior attempt. If attempt 1 passes check `alpha` and attempt 2
# fails it (a regression), the loop must name that explicitly in the feedback. Without it, the
# model trades one check for another and stops for a human.
#
# Writes, per task, to ${RETRY_STATE_DIR:-${TMPDIR:-/tmp}}/ralph-retry-$$.passed:
#   one check name per line — all checks that ever passed in any prior attempt of this task.
#
# Best-effort contract: a full disk or unwritable temp dir never fails the loop. RETRY_OK=0
# means the helper is unavailable; all functions are no-ops. RETRY_OFF=on disables.

retry_init() {
  RETRY_OK=0
  [ "${RETRY_OFF:-off}" = "on" ] && return 0
  RETRY_STATE_DIR="${RETRY_STATE_DIR:-${TMPDIR:-/tmp}}"
  RETRY_STATE_FILE="$RETRY_STATE_DIR/ralph-retry-$$.passed"
  : > "$RETRY_STATE_FILE" 2>/dev/null || { RETRY_OK=0; return 0; }
  RETRY_OK=1
  return 0
}

retry_record() {
  [ "${RETRY_OK:-0}" = 1 ] || return 0
  [ -n "${1:-}" ] || return 0
  local line verdict name
  while IFS= read -r line; do
    verdict="$(printf '%s' "$line" | awk '{ t=toupper($1); if(t=="PASS"||t=="OK")print"PASS";else if(t=="FAIL")print"FAIL";else if(t=="PEND"||t=="PENDING")print"PEND";else print"" }')"
    [ "$verdict" = "PASS" ] || continue
    name="$(printf '%s' "$line" | awk '{ print $2 }')"
    [ -n "$name" ] || continue
    printf '%s\n' "$name" >> "$RETRY_STATE_FILE" 2>/dev/null || return 0
  done <<EOF
$1
EOF
  return 0
}

retry_regressions() {
  [ "${RETRY_OK:-0}" = 1 ] || return 0
  [ -f "$RETRY_STATE_FILE" ] || return 0
  [ -n "${1:-}" ] || return 0
  local line verdict name regressions=()
  while IFS= read -r line; do
    verdict="$(printf '%s' "$line" | awk '{ t=toupper($1); if(t=="PASS"||t=="OK")print"PASS";else if(t=="FAIL")print"FAIL";else if(t=="PEND"||t=="PENDING")print"PEND";else print"" }')"
    [ "$verdict" = "FAIL" ] || [ "$verdict" = "PEND" ] || continue
    name="$(printf '%s' "$line" | awk '{ print $2 }')"
    [ -n "$name" ] || continue
    if grep -qxF "$name" "$RETRY_STATE_FILE" 2>/dev/null; then
      regressions+=("$name")
    fi
  done <<EOF
$1
EOF
  local i count=0
  for i in "${regressions[@]}"; do
    printf '%s\n' "$i"
    count=$((count + 1))
    [ "$count" -lt 10 ] || break
  done
  return 0
}
