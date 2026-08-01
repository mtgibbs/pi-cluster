#!/usr/bin/env bash
# scripts/gate-score.sh — score a verify.sh gate's output.
# §10 acceptance criteria + §8 safeguards compiled to runnable assertions: exit 0 = acceptable.
#
# PRESENCE-GATED, PER FEATURE (the ralph contract): runs after EVERY task and must pass, so a
# check for a not-yet-built feature is PEND, never FAIL. CRITICAL LESSON (2026-07-27, the first
# dogfood of this very spec): each block below keys its PEND on ITS OWN task's observable output —
# T1 on the `passed=` line, T2 on the `FAIL:`/`TODO:` lines, T3 on the guard markers. An earlier
# version keyed everything on "does any count line exist", so the moment T1 printed a partial
# score line the gate demanded T2+T3 work and T1 could never pass. A presence-gated check MUST key
# on its own task's output — see the identical warning in specs/harness-multi-repo/verify.sh.
#
# STATIC + SELF-CONTAINED: synthesizes throwaway fixture gates in a mktemp dir and runs the real
# scripts/gate-score.sh against them. No network, no cluster, no repo mutation.
set -uo pipefail

# ARG GUARD — if $1 is missing or is not a readable file, print a usage error to stderr naming the
# expected argument (a path to a readable verify.sh) and exit 2, before running anything.
if [ $# -ne 1 ] || [ ! -r "$1" ]; then
  echo "Usage: $0 <verify-path>" >&2
  exit 2
fi

V="$1"

# Run the target gate capturing stdout AND stderr COMBINED (bash "$V" 2>&1 — FAIL lines are emitted
# to stderr; a stdout-only capture scores every failing gate as passing).
run="$(bash "$V" 2>&1)"

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

# Print the sentinel line and score line
echo "---GATE-SCORE---"
echo "passed=$passed failed=$failed pending=$pending total=$total score=$score no_fail=$no_fail converged=$converged$extra"

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

# SCORE + EXIT: compute s EXACTLY as the "score line" WORKED EXAMPLE in section 6 — use awk float division
# (score="$(awk -v p="$passed" -v t="$total" 'BEGIN{printf "%.3f", p/t}')"), NOT bash $((p/t)) which is integer
# and always yields 0.000. When t>0, exit 0 when converged==1 else exit 1. When t==0 (the gate emitted no parseable checks)
# you MUST print score=0.000 LITERALLY (never blank), ALSO include error=no-checks-parsed and exit 2.
[ "$total" -eq 0 ] && exit 2 || [ "$converged" -eq 1 ] && exit 0 || exit 1