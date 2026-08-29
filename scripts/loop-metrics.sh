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
# $TASK-attempt*, NOT T*-attempt*. A run dir holds every task the process worked on, so the
# wildcard counted the whole queue and reported it as this task's cost: a 3-task run recorded
# "attempts: 3" against T1, T2 and T3 alike. Same defect as loop-index.py's per-dir totals,
# in the same file that exists to measure cost.
attempts=0; [ -d "$LOGDIR" ] && attempts="$(ls "$LOGDIR"/"$TASK"-attempt*.log 2>/dev/null | grep -c . || echo 0)"
failed_attempts=0; [ -d "$LOGDIR" ] && failed_attempts="$(ls "$LOGDIR"/"$TASK"-attempt*.diff 2>/dev/null | grep -c . || echo 0)"
# a stillborn attempt is one whose log never got past the banner
stillborn=0
if [ -d "$LOGDIR" ]; then
  for f in "$LOGDIR"/"$TASK"-attempt*.log; do
    [ -f "$f" ] || continue
    [ "$(stat -f %z "$f")" -le 40 ] && stillborn=$((stillborn + 1))
  done
fi
restarts=0
[ -n "$SUPLOG" ] && [ -f "$SUPLOG" ] && restarts="$(grep -c 'STILLBORN' "$SUPLOG" 2>/dev/null || echo 0)"

# --- what the task SPENT ----------------------------------------------------
#
# Nothing in this harness recorded tokens until now. This file measured "how many attempts a
# task costs" and called that cost; the 2026-08-25 five-spec run had to recover its spend
# after the fact from opencode's own SQLite store to answer "what did that actually consume".
# 1.87 M input tokens across 37 attempts, 62% of it on the one spec that STOPped three times
# — a number the loop could not report about itself.
#
# SOURCE, and its limits: ~/.local/share/opencode/opencode.db, whose `session` table carries
# tokens_input / tokens_output / tokens_cache_read / cost per session. That DB belongs to a
# different tool, is per-machine, and gets pruned — which is exactly why the numbers are
# copied HERE, into the repo's own record, at the moment they are still true.
#
# JOIN: `oc run` is one session per attempt, and the shell redirect creates
# T<label>-attempt<n>.log at the moment the session starts. So an attempt's log birth time
# and its session's time_created are the same event, and matching nearest-within-tolerance is
# exact rather than heuristic. Falls back to mtime where birthtime is unavailable (Linux).
#
# HONESTY RULE, same as everywhere else here: unavailable is null, never 0. A missing sqlite3
# or a pruned DB must read as "not measured", not as "measured zero".
OC_DB="${OC_DB:-$HOME/.local/share/opencode/opencode.db}"
TOK_TOLERANCE="${TOK_TOLERANCE:-180}"     # seconds between log birth and session creation
tok_in=null; tok_out=null; tok_cache=null; tok_cost=null; tok_sessions=null

if [ -d "$LOGDIR" ] && [ -f "$OC_DB" ] && command -v sqlite3 >/dev/null 2>&1; then
  # Birth time per attempt log for THIS task only. BSD stat has %B; GNU stat has %W (0 when
  # the filesystem does not track it) — fall back to mtime rather than drop the attempt.
  _stamps=""
  for f in "$LOGDIR"/"$TASK"-attempt*.log; do
    [ -f "$f" ] || continue
    _b="$(stat -f %B "$f" 2>/dev/null || stat -c %W "$f" 2>/dev/null || echo 0)"
    [ "${_b:-0}" -gt 0 ] 2>/dev/null || _b="$(stat -f %m "$f" 2>/dev/null || stat -c %Y "$f" 2>/dev/null || echo 0)"
    [ "${_b:-0}" -gt 0 ] 2>/dev/null && _stamps="$_stamps $_b"
  done
  if [ -n "$_stamps" ]; then
    _res="$(OC_DB="$OC_DB" WT="$WT" TOL="$TOK_TOLERANCE" STAMPS="$_stamps" python3 - <<'PY' 2>/dev/null || true
import os, sqlite3, sys
db, wt = os.environ["OC_DB"], os.path.realpath(os.environ["WT"])
tol = int(os.environ["TOL"]) * 1000
stamps = [int(s) * 1000 for s in os.environ["STAMPS"].split()]
try:
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    rows = con.execute(
        "select time_created, tokens_input, tokens_output, tokens_cache_read, cost "
        "from session where directory = ? or directory like ?",
        (wt, wt + "/%")).fetchall()
except Exception:
    sys.exit(1)
# Nearest session per attempt, each session claimed at most once — two attempts of the same
# task are two sessions, and double-counting one of them would inflate the row silently.
used, tot = set(), [0, 0, 0, 0.0, 0]
for s in stamps:
    best, bi = None, None
    for i, r in enumerate(rows):
        if i in used or r[0] is None:
            continue
        d = abs(r[0] - s)
        if d <= tol and (best is None or d < best):
            best, bi = d, i
    if bi is None:
        continue
    used.add(bi)
    r = rows[bi]
    tot[0] += r[1] or 0; tot[1] += r[2] or 0; tot[2] += r[3] or 0
    tot[3] += r[4] or 0.0; tot[4] += 1
if not tot[4]:
    sys.exit(1)          # matched nothing -> null, not zero
print("%d %d %d %.6f %d" % tuple(tot))
PY
)"
    if [ -n "$_res" ]; then
      set -- $_res
      tok_in="${1:-null}"; tok_out="${2:-null}"; tok_cache="${3:-null}"
      tok_cost="${4:-null}"; tok_sessions="${5:-null}"
    fi
  fi
fi

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
  # null, not 0, when the session store was unreadable or matched nothing — "not measured"
  # and "measured zero" are different claims and this file's honesty rule forbids conflating
  # them. `cost` is 0.0 against a local model with no pricing configured; that IS measured.
  "spend": {
    "sessions": $tok_sessions,
    "tokens_input": $tok_in,
    "tokens_output": $tok_out,
    "tokens_cache_read": $tok_cache,
    "cost_usd": $tok_cost,
    "source": "opencode-session-db",
  },
}
with open(sys.argv[1], "a") as f:
    f.write(json.dumps(row) + "\n")
print(json.dumps(row, indent=2))
PY
