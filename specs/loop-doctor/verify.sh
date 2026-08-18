#!/usr/bin/env bash
# verify.sh — deterministic acceptance gate for specs/loop-doctor.
# Run from repo root:  ./specs/loop-doctor/verify.sh   (STRICT=1 for the final convergence pass)
#
# HERMETIC: fixtures only. Never invokes gate-score.sh, run-loop.sh, or any ralph-*.sh —
# loop-doctor is a reader of the harness and this gate must not become a way to run it
# (spec §4, same recursion hazard loop-report/verify.sh names).
#
# THREE-VERDICT (specs/TEMPLATE.md §11): T1's deliverable — the script itself — is a hard FAIL
# when absent, because pend-on-your-own-first-deliverable is what scores "built nothing" as
# green. T2-T6 pend, each keyed on ITS OWN observable, never on a later task's work.
# Scope/litter checks run FIRST and are FATAL.
set -uo pipefail

F="scripts/loop-doctor.sh"
FIX="specs/loop-doctor/fixtures"
S="$FIX/status"
L="$FIX/logs"
NOW=1787000000          # fixed clock: qwen-1001 updated=1786996400 -> stale 3600s
NOW_FRESH=1786996430    # same fixture, 30s after its heartbeat -> not stale
fail=0
ok(){   echo "  PASS  $1"; }
no(){   echo "  FAIL  $1" >&2; fail=1; }
pend(){ if [ "${STRICT:-0}" = 1 ]; then no "$1 — still unbuilt at the final check (STRICT)"
        else echo "  pend  $1 (not built yet)"; fi; }

command -v jq >/dev/null 2>&1 || { echo "  FAIL  env:jq-required" >&2; exit 1; }

# §8.1 read-only proof: fingerprint the fixtures BEFORE anything runs. Comparing against git
# would only ask "is the repo clean" — which is false for untracked fixtures and says nothing
# about whether the scan wrote. This asks the actual question.
fixprint(){ find "$FIX" -type f -exec shasum {} \; 2>/dev/null | sort | shasum | cut -d' ' -f1; }
FIX_BEFORE="$(fixprint)"

# ---------------------------------------------------------------- scope / litter (FIRST, FATAL)
# Litter: nothing may appear under specs/loop-doctor/ outside the allowed set.
stray="$(find specs/loop-doctor -type f \
  ! -name spec.md ! -name tasks.txt ! -name verify.sh \
  ! -path 'specs/loop-doctor/fixtures/*' ! -path 'specs/loop-doctor/evidence/*' 2>/dev/null)"
[ -z "$stray" ] && ok "scope:no-litter-in-spec-dir" \
  || { no "scope:no-litter-in-spec-dir"; echo "$stray" | sed 's/^/          /' >&2; }

# Scope: the out-of-scope scripts (spec §5) must be untouched. Needs a base ref; when none
# resolves we PEND rather than skip silently — under STRICT that becomes a FAIL (fail-closed).
BASE="${LOOP_DOCTOR_BASE:-origin/main}"
if git rev-parse --verify --quiet "$BASE" >/dev/null 2>&1; then
  if git diff --quiet "$BASE" -- \
       scripts/ralph-qwen.sh scripts/ralph-codex.sh scripts/ralph-judge.sh \
       scripts/ralph-status.sh scripts/ralph-log.sh scripts/ralph-bus.sh \
       scripts/run-loop.sh scripts/gate-score.sh scripts/loop-report.sh \
       scripts/harness harness-console 2>/dev/null; then
    ok "scope:out-of-scope-files-untouched"
  else
    no "scope:out-of-scope-files-untouched — spec §5 forbids editing these"
  fi
else
  pend "scope:out-of-scope-files-untouched (base '$BASE' unresolvable)"
fi

# AC15 — the reader must never invoke the measured, and never reach the network.
# COMMENTS ARE STRIPPED FIRST. Matching raw file text made this check fire on a header comment
# that merely NAMED verify.sh — a false negative in the gate, caught 2026-08-18 by running it
# against a known-good reference implementation. Same class of bug gate-score.sh warns about
# ("NEVER substring-match a status word anywhere in a line"), and the reason the amendment
# demands a gate be exercised in BOTH directions.
code(){ sed -e 's/#.*//' "$F"; }
if [ -f "$F" ]; then
  if code | grep -Eq '(gate-score\.sh|run-loop\.sh|ralph-[a-z]*\.sh|verify\.sh|\bdocker\b|\bssh\b|\bcurl\b|\bwget\b|git +commit)'; then
    no "ac15:no-forbidden-invocations"
  else
    ok "ac15:no-forbidden-invocations"
  fi
  # §8.6 — must not create its own heartbeat (observer effect).
  code | grep -q 'ralph-status\.sh' && no "safeguard:no-self-heartbeat" || ok "safeguard:no-self-heartbeat"
else
  no "ac15:no-forbidden-invocations"; no "safeguard:no-self-heartbeat"
fi

# ------------------------------------------------------------------------ fixture sanity (FATAL)
[ -d "$S" ] && [ -d "$L" ] && ok "fixtures:present" || no "fixtures:present"
[ "$(wc -c < "$L/qwen-1004/T4-attempt2.log" 2>/dev/null || echo 0)" -lt 512 ] \
  && ok "fixtures:1004-under-512B" || no "fixtures:1004-under-512B"
grep -q 'Killed: 9' "$L/qwen-1004/T4-attempt2.log" 2>/dev/null \
  && ok "fixtures:1004-has-kill-marker" || no "fixtures:1004-has-kill-marker"

# --------------------------------------------------------------------------------- T1 (hard)
[ -f "$F" ] && ok "t1:script-exists" || no "t1:script-exists"
[ -x "$F" ] && ok "t1:script-executable" || no "t1:script-executable"
if [ -f "$F" ]; then
  bash -n "$F" 2>/dev/null && ok "t1:bash-n-clean" || no "t1:bash-n-clean"
  grep -q 'declare -A' "$F" && no "t1:no-declare-A-bash32" || ok "t1:no-declare-A-bash32"

  bash "$F" --definitely-not-a-flag >/dev/null 2>/tmp/ld-flag.txt; rc=$?
  [ "$rc" -eq 1 ] && ok "ac2:unknown-flag-exit-1" || no "ac2:unknown-flag-exit-1"
  grep -q 'usage:' /tmp/ld-flag.txt && ok "ac2:usage-on-stderr" || no "ac2:usage-on-stderr"

  bash "$F" --status-dir /nonexistent/nope --log-dir /nonexistent/nope >/dev/null 2>&1; rc=$?
  [ "$rc" -eq 2 ] && ok "t1:unreadable-dir-exit-2" || no "t1:unreadable-dir-exit-2"
else
  no "t1:bash-n-clean"; no "t1:no-declare-A-bash32"
  no "ac2:unknown-flag-exit-1"; no "ac2:usage-on-stderr"; no "t1:unreadable-dir-exit-2"
fi

# Shared invocations. Never let a crashing script abort the gate.
run(){ [ -f "$F" ] && bash "$F" --status-dir "$S" --log-dir "$L" --now "$NOW" "$@" 2>/dev/null; }
HUMAN="$(run || true)"
JSON="$(run --json || true)"
j(){ printf '%s\n' "$JSON" | jq -r "select(.run_id==\"$1\") | $2" 2>/dev/null | head -1; }

# --------------------------------------------------------------------------------- T2 (pend)
if printf '%s' "$HUMAN" | grep -q 'qwen-1004'; then
  # AC3 — exactly one line per run; the union of status + logs is 8 runs (1001-1008, no 1007
  # heartbeat and no 1007-less log dir; 1007 is logs-only, 1006 is heartbeat-only).
  n="$(printf '%s\n' "$HUMAN" | grep -c 'qwen-100')"
  [ "$n" -eq 8 ] && ok "ac3:one-line-per-run(8)" || no "ac3:one-line-per-run(8) — got $n"
  printf '%s\n' "$HUMAN" | head -1 | grep -q 'qwen-1002' \
    && ok "t2:sorted-newest-updated-first" || no "t2:sorted-newest-updated-first"
  printf '%s\n' "$HUMAN" | grep -q 'qwen-1007' \
    && ok "t2:logdir-without-heartbeat-listed" || no "t2:logdir-without-heartbeat-listed"
  printf '%s\n' "$HUMAN" | grep -q 'qwen-1006' \
    && ok "t2:heartbeat-without-logdir-listed" || no "t2:heartbeat-without-logdir-listed"
else
  pend "ac3:one-line-per-run(8)"; pend "t2:sorted-newest-updated-first"
  pend "t2:logdir-without-heartbeat-listed"; pend "t2:heartbeat-without-logdir-listed"
fi

# --------------------------------------------------------------------------------- T3 (pend)
if printf '%s\n' "$JSON" | head -1 | jq -e 'has("stale_s")' >/dev/null 2>&1; then
  bad="$(printf '%s\n' "$JSON" | grep -c -v '^{' || true)"
  [ "$bad" -eq 0 ] && ok "ac12:every-line-is-json" || no "ac12:every-line-is-json"
  [ "$(j qwen-1001 .stale_s)" = "3600" ] && ok "t3:stale_s-from-now" || no "t3:stale_s-from-now"
  [ "$(j qwen-1001 .duration_s)" = "3600" ] && ok "t3:duration_s" || no "t3:duration_s"
  # AC12 — verify_pass is a JSON literal, never the string "null".
  [ "$(j qwen-1001 '.verify_pass|type')" = "null" ] \
    && ok "ac12:verify_pass-null-is-literal" || no "ac12:verify_pass-null-is-literal"
  [ "$(j qwen-1002 '.verify_pass|type')" = "boolean" ] \
    && ok "ac12:verify_pass-false-is-boolean" || no "ac12:verify_pass-false-is-boolean"
  # AC11 — an unparseable heartbeat still yields a row, and does not abort the scan.
  [ -n "$(j qwen-1008 .run_id)" ] && ok "ac11:malformed-heartbeat-still-a-row" \
    || no "ac11:malformed-heartbeat-still-a-row"
  run --json >/dev/null 2>&1; [ $? -eq 0 ] && ok "ac11:exit-0-despite-malformed" \
    || no "ac11:exit-0-despite-malformed"
  [ "$(j qwen-1007 .stale_s)" = "null" ] && ok "t3:stale_s-null-without-heartbeat" \
    || no "t3:stale_s-null-without-heartbeat"
else
  pend "ac12:every-line-is-json"; pend "t3:stale_s-from-now"; pend "t3:duration_s"
  pend "ac12:verify_pass-null-is-literal"; pend "ac12:verify_pass-false-is-boolean"
  pend "ac11:malformed-heartbeat-still-a-row"; pend "ac11:exit-0-despite-malformed"
  pend "t3:stale_s-null-without-heartbeat"
fi

# --------------------------------------------------------------------------------- T4 (pend)
if printf '%s\n' "$JSON" | head -1 | jq -e 'has("attempts_seen")' >/dev/null 2>&1; then
  [ "$(j qwen-1003 .attempts_seen)" = "3" ] && ok "t4:attempts_seen" || no "t4:attempts_seen"
  [ "$(j qwen-1002 .diffs_seen)" = "1" ] && ok "t4:diffs_seen" || no "t4:diffs_seen"
  [ "$(j qwen-1004 .bytes_last)" = "114" ] && ok "t4:bytes_last" || no "t4:bytes_last"
  [ "$(j qwen-1006 .bytes_last)" = "null" ] && ok "t4:bytes_last-null-without-logs" \
    || no "t4:bytes_last-null-without-logs"
  # AC10 — a stray basename is counted, and the run is still classified.
  [ "$(j qwen-1004 .unparsed)" = "1" ] && ok "ac10:stray-file-counted" || no "ac10:stray-file-counted"
  [ "$(j qwen-1008 .unparsed)" = "1" ] && ok "ac10:malformed-heartbeat-counted" \
    || no "ac10:malformed-heartbeat-counted"
  [ "$(j qwen-1002 .unparsed)" = "0" ] && ok "t4:unparsed-zero-when-clean" \
    || no "t4:unparsed-zero-when-clean"
  printf '%s' "$HUMAN" | grep -q 'qwen-1004.*(unparsed: 1)' \
    && ok "t4:unparsed-shown-in-human" || no "t4:unparsed-shown-in-human"
else
  pend "t4:attempts_seen"; pend "t4:diffs_seen"; pend "t4:bytes_last"
  pend "t4:bytes_last-null-without-logs"; pend "ac10:stray-file-counted"
  pend "ac10:malformed-heartbeat-counted"; pend "t4:unparsed-zero-when-clean"
  pend "t4:unparsed-shown-in-human"
fi

# --------------------------------------------------------------------------------- T5 (pend)
if [ -n "$(j qwen-1004 .fault)" ] && [ "$(j qwen-1004 .fault)" != "unknown" ]; then
  # AC6 — the conflation ralph-qwen.sh:100-108 gets wrong: 114B + kill marker is NOT stillborn.
  [ "$(j qwen-1004 .fault)" = "watchdog-kill" ] && ok "ac6:watchdog-kill-beats-stillborn" \
    || no "ac6:watchdog-kill-beats-stillborn — got '$(j qwen-1004 .fault)'"
  [ "$(j qwen-1002 .fault)" = "verify-fail" ] && ok "ac8:verify-fail-on-diff" \
    || no "ac8:verify-fail-on-diff"
  [ "$(j qwen-1003 .fault)" = "permission-blocked" ] && ok "ac9:permission-blocked" \
    || no "ac9:permission-blocked"
  [ "$(j qwen-1005 .fault)" = "no-op" ] && ok "s33:no-op" || no "s33:no-op"
  [ "$(j qwen-1006 .fault)" = "done" ] && ok "s33:done" || no "s33:done"
  [ "$(j qwen-1007 .fault)" = "unknown" ] && ok "s33:unknown-when-no-rule-matches" \
    || no "s33:unknown-when-no-rule-matches"

  # AC4/AC5 — THE SAME FIXTURE, TWO CLOCKS, TWO VERDICTS. This pair is the red-before-green
  # proof for the staleness rule: neither verdict can pass vacuously while the other holds.
  [ "$(j qwen-1001 .fault)" = "dead" ] && ok "ac4:stale-heartbeat-is-dead" \
    || no "ac4:stale-heartbeat-is-dead"
  FRESH="$(bash "$F" --status-dir "$S" --log-dir "$L" --now "$NOW_FRESH" --json 2>/dev/null || true)"
  fv="$(printf '%s\n' "$FRESH" | jq -r 'select(.run_id=="qwen-1001") | .fault' 2>/dev/null | head -1)"
  [ "$fv" = "running" ] && ok "ac5:fresh-heartbeat-is-running" \
    || no "ac5:fresh-heartbeat-is-running — got '$fv'"

  # AC7 — every run cites evidence. An empty evidence string is a bug, not a style issue.
  empty="$(printf '%s\n' "$JSON" | jq -r 'select((.evidence//"")=="") | .run_id' 2>/dev/null | wc -l | tr -d ' ')"
  [ "$empty" = "0" ] && ok "ac7:evidence-non-empty-for-every-run" \
    || no "ac7:evidence-non-empty-for-every-run — $empty empty"
  printf '%s' "$(j qwen-1004 .evidence)" | grep -q 'Killed: 9' \
    && ok "ac7:evidence-names-the-marker" || no "ac7:evidence-names-the-marker"

  # AC14 — transcripts carry secrets; evidence carries markers. The fixture key must not leak.
  printf '%s%s' "$HUMAN" "$JSON" | grep -q 'sk-FIXTUREFAKE' \
    && no "ac14:no-transcript-payload-in-output" || ok "ac14:no-transcript-payload-in-output"
else
  pend "ac6:watchdog-kill-beats-stillborn"; pend "ac8:verify-fail-on-diff"
  pend "ac9:permission-blocked"; pend "s33:no-op"; pend "s33:done"
  pend "s33:unknown-when-no-rule-matches"; pend "ac4:stale-heartbeat-is-dead"
  pend "ac5:fresh-heartbeat-is-running"; pend "ac7:evidence-non-empty-for-every-run"
  pend "ac7:evidence-names-the-marker"; pend "ac14:no-transcript-payload-in-output"
fi

# --------------------------------------------------------------------------------- T6 (pend)
LED="$(mktemp -t ld-ledger.XXXXXX)"; rm -f "$LED"
run --ledger "$LED" >/dev/null 2>&1
if [ -f "$LED" ]; then
  a="$(wc -l < "$LED" | tr -d ' ')"
  run --ledger "$LED" >/dev/null 2>&1
  b="$(wc -l < "$LED" | tr -d ' ')"
  [ "$a" -gt 0 ] && ok "t6:ledger-written" || no "t6:ledger-written"
  [ "$a" = "$b" ] && ok "ac13:ledger-idempotent" || no "ac13:ledger-idempotent — $a then $b"
  head -1 "$LED" | jq -e 'has("fault") and has("evidence")' >/dev/null 2>&1 \
    && ok "t6:ledger-rows-are-schema-rows" || no "t6:ledger-rows-are-schema-rows"
  grep -q 'sk-FIXTUREFAKE' "$LED" && no "ac14:no-secret-in-ledger" || ok "ac14:no-secret-in-ledger"
else
  pend "t6:ledger-written"; pend "ac13:ledger-idempotent"
  pend "t6:ledger-rows-are-schema-rows"; pend "ac14:no-secret-in-ledger"
fi
rm -f "$LED"

# §8.1 — the tool must have written nothing into the fixtures it read.
[ "$(fixprint)" = "$FIX_BEFORE" ] \
  && ok "safeguard:fixtures-unmodified-by-scan" || no "safeguard:fixtures-unmodified-by-scan"

exit "$fail"
