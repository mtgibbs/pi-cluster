#!/usr/bin/env bash
# verify.sh — deterministic acceptance gate for specs/loop-report.
# Run from repo root:  ./specs/loop-report/verify.sh
# Hermetic: fixtures only; never invokes gate-score.sh (recursion hazard, spec §5).
set -uo pipefail
F="scripts/loop-report.sh"
FIX="specs/loop-report/fixtures"
fail=0
ok(){ echo "  PASS  $1"; }
no(){ echo "  FAIL  $1" >&2; fail=1; }

# AC1 — single-task-style existence checks: missing deliverable is a hard FAIL, never PEND.
[ -f "$F" ] && ok "script:exists" || no "script:exists"
[ -x "$F" ] && ok "script:executable" || no "script:executable"
bash -n "$F" 2>/dev/null && ok "script:bash-n" || no "script:bash-n"

# Everything below needs the script; keep FAILing (not erroring) when it's absent.
run(){ [ -f "$F" ] && bash "$F" "$@" 2>/tmp/lr-err.txt || return $?; }

# AC2 — usage contract.
if [ -f "$F" ]; then
  bash "$F" >/dev/null 2>/tmp/lr-usage.txt; rc=$?
  [ "$rc" -eq 1 ] && ok "cli:no-args-exit-1" || no "cli:no-args-exit-1"
  grep -q 'usage:' /tmp/lr-usage.txt && ok "cli:usage-on-stderr" || no "cli:usage-on-stderr"
else
  no "cli:no-args-exit-1"; no "cli:usage-on-stderr"
fi

# AC3/AC4/AC6 — full fixture run.
OUT="$(run --spec specs/loop-report --base HEAD --judge-state "$FIX" --gate-log "$FIX/gate.log" || true)"
echo "$OUT" | sed -n '1p' | grep -qx '== loop report ==' && ok "out:header" || no "out:header"
echo "$OUT" | grep -q '^branch: ' && ok "out:branch-line" || no "out:branch-line"
echo "$OUT" | grep -Eq '^base: HEAD  commits: [0-9]+$' && ok "out:base-line" || no "out:base-line"
echo "$OUT" | grep -qx 'gate: passed=9 failed=0 pending=0 total=9 score=1.000 no_fail=1 converged=1 verify_rc=0' \
  && ok "gate:last-sentinel-verbatim" || no "gate:last-sentinel-verbatim"
echo "$OUT" | grep -q 'score=9.999' && no "gate:ignores-untrusted-above-sentinel" || ok "gate:ignores-untrusted-above-sentinel"
echo "$OUT" | grep -qx 'judge: accepted=2 rejected=1 gate-gaps=0 outcome=dry' \
  && ok "judge:fixture-counts" || no "judge:fixture-counts"

# AC3 — log with no sentinel.
OUT2="$(run --spec specs/loop-report --base HEAD --judge-state "$FIX" --gate-log specs/loop-report/spec.md || true)"
echo "$OUT2" | grep -qx 'gate: none' && ok "gate:none-without-sentinel" || no "gate:none-without-sentinel"

# AC5 — empty judge-state.
EMPTY="$(mktemp -d)"
OUT3="$(run --spec specs/loop-report --base HEAD --judge-state "$EMPTY" || true)"
rmdir "$EMPTY"
echo "$OUT3" | grep -qx 'judge: none' && ok "judge:none-when-absent" || no "judge:none-when-absent"

exit "$fail"
