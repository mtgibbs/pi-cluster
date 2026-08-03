#!/usr/bin/env bash
# scripts/gate-score.sh — score a verify.sh gate's output.
# Wraps any spec's verify.sh: reruns it, classifies its check lines, and prints a machine-readable
# score block after a ---GATE-SCORE--- sentinel. READ-ONLY — writes nothing into the tree.
# (The old header here described fixture-synthesis this script never did — copied from the wrong
# file, shipped at score 1.000, and became specs/judge-loop §1's founding example. Fixed.)
#
# THE PEND CONTRACT for the verify.sh gates this script scores (clarified 2026-08-03 after the
# specs/export incident — evidence in specs/judge-loop/evidence/): a PEND may key ONLY on a
# DEPENDENCY's observable (another task's deliverable, or an external precondition), NEVER on the
# task-under-test's own deliverable.
#   - MULTI-task spec: checks for not-yet-built tasks pend, each keyed on ITS OWN task's
#     observable (the 2026-07-27 lesson stands — never "does any count line exist", or T1 can
#     never pass before T2). The loop, not the gate, must demand progress between tasks.
#   - SINGLE-task spec: a missing deliverable is a hard FAIL, never PEND — pend-on-your-own-task
#     is exactly what scored "built nothing" as green (specs/export hole #1).
#   - EVERY shape: scope/litter checks run FIRST and are FATAL. An early exit-0 pend path ahead
#     of the scope check is the fail-open-ordering bug.
#   Reference implementation: specs/export/verify.sh in mtgibbs/new-horizons#25.
#
# FAIL-CLOSED (amendment 2026-08-03; judge-loop planning-check findings 2-3): the verifier's own
# exit status is captured and exposed as verify_rc=<n> on the score line, and this script exits
# nonzero whenever the verifier did — a gate that prints PASS lines and then crashes is a FAILING
# gate, not a converged one. NOTE for consumers (judge-loop et al.): also compare `total` against
# your own baseline; score alone cannot detect check-deletion (10/10 and 1/1 both read 1.000).
set -uo pipefail

# ARG GUARD — if $1 is missing or is not a readable file, print a usage error to stderr naming the
# expected argument (a path to a readable verify.sh) and exit 2, before running anything.
if [ $# -ne 1 ] || [ ! -r "$1" ]; then
  echo "Usage: $0 <verify-path>" >&2
  exit 2
fi

V="$1"

# Run the target gate capturing stdout AND stderr COMBINED (bash "$V" 2>&1 — FAIL lines are emitted
# to stderr; a stdout-only capture scores every failing gate as passing) AND its exit status —
# discarding $? here was fail-open bug #1: PASS lines + a crash during cleanup scored converged.
run="$(bash "$V" 2>&1)"; vrc=$?

# Print the raw captured output verbatim first (subtract nothing).
printf '%s\n' "$run"

# CLASSIFY each captured line by its LEADING TOKEN ONLY, case-insensitively (awk, 1-4 leading spaces
# then a word): PASS or OK -> passed; FAIL -> failed; PEND or PENDING -> pending; ANY other leading
# token is not a check and is ignored (do NOT treat NO as a fail token — "  No changes detected"
# must not count). NEVER substring-match a status word anywhere in a line, or a PASS whose message
# contains "fail" is miscounted. total=p+f+d; no_fail=1 iff f==0; converged=1 iff f==0 AND d==0 AND t>0.
counts="$(printf '%s\n' "$run" | awk '
  # $1 is the first whitespace-delimited field; leading indent is already stripped by awk.
  # Guard on a small original indent so column-0 headers are excluded.
  /^[[:space:]][[:space:]]?[[:space:]]?[[:space:]]?[A-Za-z]/ {
    t = toupper($1)
    if (t=="PASS"||t=="OK")            p++
    else if (t=="FAIL")               f++
    else if (t=="PEND"||t=="PENDING") d++
  }
  END { printf "%d %d %d", p, f, d }
')"

# Read passed failed pending back from $counts
passed=$(printf '%s\n' "$counts" | cut -d' ' -f1)
failed=$(printf '%s\n' "$counts" | cut -d' ' -f2)
pending=$(printf '%s\n' "$counts" | cut -d' ' -f3)

# Compute the score line (do NOT compute the score in bash)
total=$(( passed + failed + pending ))
no_fail=0;   [ "$failed"  -eq 0 ] && no_fail=1
converged=0; [ "$failed"  -eq 0 ] && [ "$pending" -eq 0 ] && [ "$total" -gt 0 ] && converged=1

if [ "$total" -eq 0 ]; then
  score="0.000"; extra=" error=no-checks-parsed"           # empty gate: literal 0.000 + marker, exit 2
else
  score="$(awk -v p="$passed" -v t="$total" 'BEGIN{ printf "%.3f", p/t }')"; extra=""
fi

# Print the sentinel line and score line (verify_rc = the wrapped verifier's own exit status)
echo "---GATE-SCORE---"
echo "passed=$passed failed=$failed pending=$pending total=$total score=$score no_fail=$no_fail converged=$converged verify_rc=$vrc$extra"

# After the score line, print one "FAIL: <message>" line for every failed check and one "TODO: <message>"
# line for every pending check, where <message> is the line with its leading token stripped (everything
# after the first indented word).
printf '%s\n' "$run" | awk '
  /^[[:space:]][[:space:]]?[[:space:]]?[[:space:]]?[A-Za-z]/ {
    t = toupper($1)
    if (t=="FAIL") {
      # Print the full line with leading token stripped, but keep the message part
      sub(/^ *[A-Za-z]+ */, "")
      print "FAIL: " $0
    }
    else if (t=="PEND"||t=="PENDING") {
      # Print the full line with leading token stripped, but keep the message part
      sub(/^ *[A-Za-z]+ */, "")
      print "TODO: " $0
    }
  }
'

# EXIT (fail-closed): t==0 -> exit 2 (no parseable checks — error=no-checks-parsed already on the
# score line). Otherwise exit 0 ONLY when converged==1 AND verify_rc==0: a verifier that printed
# green lines but exited nonzero is broken, not converged. Everything else -> exit 1.
if [ "$total" -eq 0 ]; then
  exit 2
elif [ "$converged" -eq 1 ] && [ "$vrc" -eq 0 ]; then
  exit 0
else
  exit 1
fi