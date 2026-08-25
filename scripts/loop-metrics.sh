#!/usr/bin/env bash
# loop-metrics.sh — record one JSONL row per loop task, for later review.
#
# The raw evidence (ralph's per-attempt .log/.diff, the judge ledger, git history)
# answers "what happened in this attempt". None of it answers "how is the loop
# doing" — how many attempts a task costs, whether cost is falling, how much of the
# gate is real evidence versus names, and whether the judge still finds things after
# the gate goes green. That is what this emits.
#
#   loop-metrics.sh <Tnn> <worktree> <harness-log-dir> [supervisor-log]
#
# Appends to $EVID/metrics.jsonl. Safe to re-run; rows are append-only and stamped.
set -uo pipefail

TASK="${1:?usage: loop-metrics.sh <Tnn> <worktree> <harness-log-dir> [supervisor-log]}"
WT="${2:?worktree}"
LOGDIR="${3:?harness log dir}"
SUPLOG="${4:-}"
# THE CONVENTION: the record belongs to the repo it describes, not to a dated folder in
# $HOME. EVID still overrides for a one-off.
EVID="${EVID:-$WT/.evidence}"
OUT="$EVID/metrics.jsonl"
mkdir -p "$EVID"

cd "$WT" || exit 1

# grep -c prints its count AND exits nonzero when the count is 0, so `|| echo 0`
# yields "0\n0" and the JSON below became a syntax error. Take the first integer.
num(){ printf '%s' "${1:-0}" | tr -dc '0-9\n' | head -n1 | grep -E '^[0-9]+$' || printf '0'; }

# --- attempts and their verdicts -------------------------------------------
attempts=0; [ -d "$LOGDIR" ] && attempts="$(ls "$LOGDIR"/T*-attempt*.log 2>/dev/null | grep -c . || echo 0)"
failed_attempts=0; [ -d "$LOGDIR" ] && failed_attempts="$(ls "$LOGDIR"/T*-attempt*.diff 2>/dev/null | grep -c . || echo 0)"
# a stillborn attempt is one whose log never got past the banner
stillborn=0
if [ -d "$LOGDIR" ]; then
  for f in "$LOGDIR"/T*-attempt*.log; do
    [ -f "$f" ] || continue
    [ "$(stat -f %z "$f")" -le 40 ] && stillborn=$((stillborn + 1))
  done
fi
restarts=0
[ -n "$SUPLOG" ] && [ -f "$SUPLOG" ] && restarts="$(grep -c 'STILLBORN' "$SUPLOG" 2>/dev/null || echo 0)"

# --- the commit this task produced -----------------------------------------
sha="$(git log --format='%h' -1 -E --grep="^(ralph\\([a-z]+\\): )?$TASK " 2>/dev/null | head -n1)"
files=0; ins=0; del=0; when=""
if [ -n "$sha" ]; then
  when="$(git log -1 --format='%aI' "$sha")"
  set -- $(git show --numstat --format= "$sha" 2>/dev/null | awk '{f++; i+=$1; d+=$2} END {print f+0, i+0, d+0}')
  files="${1:-0}"; ins="${2:-0}"; del="${3:-0}"
fi

# --- the gate, as it stands now --------------------------------------------
gate_out="$("${SPEC_DIR:-specs/v1}/verify.sh" 2>&1 || true)"
pass="$(printf '%s\n' "$gate_out" | grep -c '^  PASS' || echo 0)"
fail="$(printf '%s\n' "$gate_out" | grep -c '^  FAIL' || echo 0)"
pend="$(printf '%s\n' "$gate_out" | grep -c '^  pend' || echo 0)"
ev="$(printf '%s\n' "$gate_out" | grep '^evidence:' | head -n1)"
ev_neg="$(printf '%s' "$ev" | sed -nE 's/.* ([0-9]+) negative-invariant.*/\1/p')"
ev_exec="$(printf '%s' "$ev" | sed -nE 's/.* ([0-9]+) executing.*/\1/p')"
ev_body="$(printf '%s' "$ev" | sed -nE 's/.* ([0-9]+) test-body.*/\1/p')"
ev_del="$(printf '%s' "$ev" | sed -nE 's/.* ([0-9]+) named-test delegation.*/\1/p')"
ev_wire="$(printf '%s' "$ev" | sed -nE 's/.* ([0-9]+) wiring.*/\1/p')"
ev_pres="$(printf '%s' "$ev" | sed -nE 's/.* ([0-9]+) presence-only.*/\1/p')"

# --- the judge round that followed -----------------------------------------
JR="$(git -C "$WT" rev-parse --git-path ralph-judge 2>/dev/null)/report.json"
[ -f "$JR" ] || JR="$WT/.evidence/judge-report.json"
j_acc=0; j_rej=0; j_gaps=0; judged=False
if [ -f "$JR" ]; then
  j_acc="$(python3 -c "import json;d=json.load(open('$JR'));print(len(d.get('accepted',[])))" 2>/dev/null || echo 0)"
  j_rej="$(python3 -c "import json;d=json.load(open('$JR'));print(len(d.get('rejected',[])))" 2>/dev/null || echo 0)"
  j_gaps="$(python3 -c "import json;d=json.load(open('$JR'));print(len(d.get('gate_gaps',[])))" 2>/dev/null || echo 0)"
fi
# Python booleans, not shell ones — `true` interpolated into the heredoc below is a
# NameError, and the script died reporting the metric instead of recording it.
if [ -n "$SUPLOG" ] && grep -q 'all phases complete' "$SUPLOG" 2>/dev/null; then judged=True; fi

attempts="$(num "$attempts")"; failed_attempts="$(num "$failed_attempts")"
stillborn="$(num "$stillborn")"; restarts="$(num "$restarts")"
files="$(num "$files")"; ins="$(num "$ins")"; del="$(num "$del")"
pass="$(num "$pass")"; fail="$(num "$fail")"; pend="$(num "$pend")"
j_acc="$(num "$j_acc")"; j_rej="$(num "$j_rej")"; j_gaps="$(num "$j_gaps")"

python3 - "$OUT" <<PY
import json, sys, datetime
row = {
  "task": "$TASK",
  "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
  "commit": "$sha" or None,
  "committed_at": "$when" or None,
  "attempts": $attempts,
  "failed_attempts": $failed_attempts,
  "stillborn_attempts": $stillborn,
  "supervisor_restarts": $restarts,
  "diff": {"files": $files, "insertions": $ins, "deletions": $del},
  "gate": {"pass": $pass, "fail": $fail, "pend": $pend},
  "evidence": {
    "negative": ${ev_neg:-0}, "exec": ${ev_exec:-0}, "body": ${ev_body:-0},
    "delegate": ${ev_del:-0}, "wiring": ${ev_wire:-0}, "presence": ${ev_pres:-0}
  },
  "judged": $judged,
  "judge_cumulative": {"accepted": $j_acc, "rejected": $j_rej, "gate_gaps": $j_gaps},
}
with open(sys.argv[1], "a") as f:
    f.write(json.dumps(row) + "\n")
print(json.dumps(row, indent=2))
PY
