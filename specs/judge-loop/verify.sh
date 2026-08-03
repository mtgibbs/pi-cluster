#!/usr/bin/env bash
# verify.sh — deterministic acceptance gate for specs/judge-loop.
# Spec §§4,8,9 + the gate-gap taxonomy compiled to runnable assertions: exit 0 = acceptable.
#
# PEND CONTRACT (per the 2026-08-03 clarification in scripts/gate-score.sh): multi-task spec —
# each task block keys its PEND on ITS OWN observable (T1: the script exists; T2: the ledger
# file appears; T3: the report file appears), never on another task's output. Scope check runs
# FIRST and is FATAL (fail-open-ordering is finding #1 of the evidence this spec carries).
#
# STATIC + SELF-CONTAINED: synthesizes a fixture git repo, a fixture spec gate, and MOCK
# JUDGE_CMD/EXECUTOR_CMD per case under mktemp, then runs the real scripts/ralph-judge.sh
# against them. No network, no cluster, no mutation of THIS repo. Every mock seam is exercised
# with data that CAN fail (no fixture coincidence: the id-style traps live in the fixtures).
#
# Run from repo root:  bash specs/judge-loop/verify.sh     (STRICT=1 for the final pass)
set -uo pipefail
RJ="${RJ:-scripts/ralph-judge.sh}"
GS="${GS:-scripts/gate-score.sh}"
fail=0
ok(){   echo "  PASS  $1"; }
no(){   echo "  FAIL  $1" >&2; fail=1; }
pend(){
  if [ "${STRICT:-0}" = 1 ]; then no "$1 — still unbuilt at the final check (STRICT)"; else
    echo "  pend  $1 (not built yet)"; fi
}

echo "VERIFY specs/judge-loop  ($RJ)"

# ---- scope first, fatal (fail-open-ordering guard) ----
outside="$(git status --porcelain 2>/dev/null | awk '{print $2}' | grep -vE '^(scripts/ralph-judge\.sh|specs/judge-loop/)' || true)"
if [ -n "$outside" ]; then
  no "changes outside scripts/ralph-judge.sh + specs/judge-loop/: $(echo "$outside" | tr '\n' ' ')(§5 — fixtures go in \$TMPDIR)"
else
  ok "change stayed in scope (§5)"
fi
[ -f "$GS" ] || { no "dependency scripts/gate-score.sh missing — cannot verify"; echo; echo "VERIFY: FAIL"; exit 1; }

if [ ! -f "$RJ" ]; then
  pend "T1: apply-cycle (scripts/ralph-judge.sh)"
  pend "T2: judge round + JSONL contract + ledger"
  pend "T3: terminate + report"
  echo
  [ "$fail" = 0 ] && { echo "VERIFY: PASS"; exit 0; } || { echo "VERIFY: FAIL"; exit 1; }
fi
bash -n "$RJ" 2>/dev/null && ok "ralph-judge.sh parses" || no "ralph-judge.sh has a syntax error"
RJ_ABS="$(cd "$(dirname "$RJ")" && pwd)/$(basename "$RJ")"

# =====================================================================================
# Fixture factory. Each case gets: a fresh git repo with solution.txt + specs/fx gate,
# a state dir OUTSIDE the repo, a mock judge + executor, and a calls log.
# The fixture gate's 3 checks key on markers A/B/C in solution.txt and EXIT nonzero on
# failure (verify_rc-honest). The mock protocol:
#   judge:    $1 == spec-dir        -> emits the case's round-$N.jsonl (N = call count)
#             $1 == --check-resolution -> emits the case's resolution.json
#   executor: $1 == finding JSON    -> applies suggested_change "swap|<file>|<old>|<new>"
#             modes via file exec-mode: normal | stage | sleep | commit
# =====================================================================================
FXROOT="$(mktemp -d "${TMPDIR:-/tmp}/judge-loop.XXXXXX")"
trap 'rm -rf "$FXROOT"' EXIT

mkcase(){ # $1 name -> sets CASE, REPO, STATE, sets up repo+mocks; caller then drops round files
  CASE="$FXROOT/$1"; REPO="$CASE/repo"; STATE="$CASE/state"
  mkdir -p "$REPO/specs/fx" "$STATE"
  ( cd "$REPO"
    git init -q -b judge-fx
    git config user.email fx@fx.local; git config user.name fx
    printf 'line A\nline B\nline C\njunk comment\n' > solution.txt
    cat > specs/fx/spec.md <<'EOS'
# fixture spec
EOS
    cat > specs/fx/verify.sh <<'EOS'
#!/usr/bin/env bash
f=0
grep -q 'line A' solution.txt && echo "  PASS  A present" || { echo "  FAIL  A missing" >&2; f=1; }
grep -q 'line B' solution.txt && echo "  PASS  B present" || { echo "  FAIL  B missing" >&2; f=1; }
grep -q 'line C' solution.txt && echo "  PASS  C present" || { echo "  FAIL  C missing" >&2; f=1; }
exit "$f"
EOS
    git add -A; git commit -qm fx-base
  )
  cat > "$CASE/judge.sh" <<EOS
#!/usr/bin/env bash
C="$CASE"
if [ "\${1:-}" = "--check-resolution" ]; then cat "\$C/resolution.json" 2>/dev/null; exit 0; fi
n=\$(( \$(cat "\$C/judge-calls" 2>/dev/null || echo 0) + 1 )); echo "\$n" > "\$C/judge-calls"
cat "\$C/round-\$n.jsonl" 2>/dev/null
exit 0
EOS
  cat > "$CASE/exec.sh" <<EOS
#!/usr/bin/env bash
C="$CASE"
echo "call \$*" >> "\$C/exec-calls"
mode="\$(cat "\$C/exec-mode" 2>/dev/null || echo normal)"
[ "\$mode" = sleep ] && sleep 30
f="\$1"
file="\$(printf '%s' "\$f" | /usr/bin/python3 -c 'import sys,json;print(json.loads(sys.stdin.read())["suggested_change"].split("|")[1])')"
old="\$(printf '%s' "\$f"  | /usr/bin/python3 -c 'import sys,json;print(json.loads(sys.stdin.read())["suggested_change"].split("|")[2])')"
new="\$(printf '%s' "\$f"  | /usr/bin/python3 -c 'import sys,json;print(json.loads(sys.stdin.read())["suggested_change"].split("|")[3])')"
/usr/bin/python3 - "\$file" "\$old" "\$new" <<'EOP'
import sys
p,o,n = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(p).read()
open(p,'w').write(s.replace(o,n))
EOP
[ "\$mode" = stage ]  && git add -A
[ "\$mode" = commit ] && { git add -A; git commit -qm rogue; }
exit 0
EOS
  chmod +x "$CASE/judge.sh" "$CASE/exec.sh"
  echo '{"id":"fx-1","resolved":true}' > "$CASE/resolution.json"
  echo normal > "$CASE/exec-mode"
}

finding(){ # $1 id, $2 kind, $3 suggested_change -> one JSONL line
  printf '{"id":"%s","file":"solution.txt","category":"clarity","spec_anchor":"§1","problem":"p","suggested_change":"%s","kind":"%s"}\n' "$1" "$3" "$2"
}

runjudge(){ # run ralph-judge in $REPO with the case mocks; stdout+stderr to $CASE/out, rc to $CASE/rc
  ( cd "$REPO" && JUDGE_CMD="$CASE/judge.sh" EXECUTOR_CMD="$CASE/exec.sh" \
      JUDGE_STATE_DIR="$STATE" GATE_SCORE="$(dirname "$RJ_ABS")/gate-score.sh" \
      MAX_ROUNDS="${MR:-5}" JUDGE_TIMEOUT=20 EXECUTOR_TIMEOUT=3 GATE_TIMEOUT=20 \
      bash "$RJ_ABS" specs/fx ) > "$CASE/out" 2>&1
  echo $? > "$CASE/rc"
}

# =====================================================================================
# T1 — the guardrail apply-cycle. Keyed on the script existing (checked above).
# =====================================================================================
# case 1: safe finding -> accepted, committed, message carries the id
mkcase c1
finding fx-1 mutate 'swap|solution.txt|junk comment|good comment' > "$CASE/round-1.jsonl"
: > "$CASE/round-2.jsonl"
runjudge
c1rc=$(cat "$CASE/rc")
if [ "$c1rc" = 0 ] && grep -q 'good comment' "$REPO/solution.txt" \
   && (cd "$REPO" && git log --oneline -1 | grep -q 'judge: fx-1'); then
  ok "AC-a1: safe finding applied + committed with the finding id (exit 0)"
else
  no "AC-a1: safe-finding case gave rc=$c1rc, log='$(cd "$REPO" && git log --oneline -1)' — want accept+commit 'judge: fx-1'"
fi
(cd "$REPO" && [ -z "$(git status --porcelain)" ]) && ok "AC-a2: tree clean after accept" || no "AC-a2: dirty tree after accept"

# case 2: gate-breaking finding (removes marker A) -> rejected, HEAD + tree restored exactly
mkcase c2
finding fx-1 mutate 'swap|solution.txt|line A|line X' > "$CASE/round-1.jsonl"
: > "$CASE/round-2.jsonl"
BEFORE=$(cd "$REPO" && git rev-parse HEAD)
runjudge
c2rc=$(cat "$CASE/rc")
AFTER=$(cd "$REPO" && git rev-parse HEAD)
if [ "$AFTER" = "$BEFORE" ] && grep -q 'line A' "$REPO/solution.txt" && (cd "$REPO" && [ -z "$(git status --porcelain)" ]); then
  ok "AC-b1: gate-breaking mutation restored to before_head (rc=$c2rc)"
else
  no "AC-b1: after gate-break HEAD=$AFTER (want $BEFORE), tree dirty or marker gone — the guardrail leaked"
fi

# case 3: THE STAGED-STATE TRAP — executor stages the bad edit; checkout-- would leak it
mkcase c3
finding fx-1 mutate 'swap|solution.txt|line A|line X' > "$CASE/round-1.jsonl"
: > "$CASE/round-2.jsonl"
echo stage > "$CASE/exec-mode"
runjudge
if grep -q 'line A' "$REPO/solution.txt" && (cd "$REPO" && [ -z "$(git status --porcelain)" ]); then
  ok "AC-b2: staged rejected edit fully purged (reset --hard, not checkout --)"
else
  no "AC-b2: staged-state leak — rejected content survived in index/worktree (spec §8.4)"
fi

# case 4: check-deletion — mutation guts the fixture gate to 1 check; score stays 1.000
mkcase c4
finding fx-1 mutate 'swap|specs/fx/verify.sh|grep -q .line B. solution.txt && echo \"  PASS  B present\" || { echo \"  FAIL  B missing\" >&2; f=1; }|true' > "$CASE/round-1.jsonl"
: > "$CASE/round-2.jsonl"
runjudge
if ! (cd "$REPO" && git log --oneline | grep -q 'judge: fx-1'); then
  ok "AC-b3: check-deleting mutation rejected (total==total_base enforced)"
else
  no "AC-b3: FAIL-OPEN — a mutation that deleted a gate check was ACCEPTED at score 1.000"
fi

# case 5: executor timeout -> restore + abort (exit 1)
mkcase c5
finding fx-1 mutate 'swap|solution.txt|junk comment|good comment' > "$CASE/round-1.jsonl"
echo sleep > "$CASE/exec-mode"
runjudge
c5rc=$(cat "$CASE/rc")
if [ "$c5rc" = 1 ] && (cd "$REPO" && [ -z "$(git status --porcelain)" ]); then
  ok "AC-b4: executor timeout -> restored + exit 1 (run_bounded works)"
else
  no "AC-b4: executor timeout gave rc=$c5rc / dirty tree — must restore and abort fail-closed"
fi

# case 6: resolution=false -> gate-green mutation still rejected
mkcase c6
finding fx-1 mutate 'swap|solution.txt|junk comment|good comment' > "$CASE/round-1.jsonl"
: > "$CASE/round-2.jsonl"
echo '{"id":"fx-1","resolved":false}' > "$CASE/resolution.json"
runjudge
if ! (cd "$REPO" && git log --oneline | grep -q 'judge: fx-1') && ! grep -q 'good comment' "$REPO/solution.txt"; then
  ok "AC-b5: resolved:false rejects a gate-neutral edit (accepted means on-point, not just safe)"
else
  no "AC-b5: an unresolved finding was committed — --check-resolution not enforced"
fi

# =====================================================================================
# T2 — judge round, JSONL fail-closed, ledger. Keyed on the ledger file (its observable).
# =====================================================================================
if [ -f "$FXROOT/c1/state/ledger.jsonl" ]; then
  grep -q '"id":"fx-1"' "$FXROOT/c1/state/ledger.jsonl" && grep -q '"decision":"accepted"' "$FXROOT/c1/state/ledger.jsonl" \
    && ok "AC-c1: accepted decision ledgered" || no "AC-c1: c1 ledger lacks accepted fx-1"

  # case 7: malformed JSONL -> exit 1, ZERO executor calls, no mutation
  mkcase c7
  printf '{"id":"fx-1"  broken\n' > "$CASE/round-1.jsonl"
  runjudge
  c7rc=$(cat "$CASE/rc")
  if [ "$c7rc" = 1 ] && [ ! -f "$CASE/exec-calls" ] && grep -q 'junk comment' "$REPO/solution.txt"; then
    ok "AC-c2: malformed JSONL -> fail-closed exit 1, executor never called"
  else
    no "AC-c2: malformed JSONL gave rc=$c7rc, exec-calls=$( [ -f "$CASE/exec-calls" ] && wc -l < "$CASE/exec-calls" || echo 0) — must reject the whole invocation BEFORE mutating"
  fi

  # case 8: gate-gap finding -> never applied, never executed, ledgered as gate-gap
  mkcase c8
  finding fx-gap gate-gap 'swap|solution.txt|junk comment|SHOULD NEVER APPLY' > "$CASE/round-1.jsonl"
  : > "$CASE/round-2.jsonl"
  runjudge
  if grep -q 'junk comment' "$REPO/solution.txt" && [ ! -f "$CASE/exec-calls" ] \
     && grep -q '"decision":"gate-gap"' "$STATE/ledger.jsonl" 2>/dev/null; then
    ok "AC-c3: gate-gap reported-not-applied (spec §4)"
  else
    no "AC-c3: gate-gap was executed/applied or not ledgered"
  fi

  # case 9: CROSS-RUN LEDGER — rejected id never replays on a second invocation
  mkcase c9
  finding fx-1 mutate 'swap|solution.txt|line A|line X' > "$CASE/round-1.jsonl"
  : > "$CASE/round-2.jsonl"
  runjudge                                   # run 1: rejects fx-1
  cp "$CASE/exec-calls" "$CASE/exec-calls.run1" 2>/dev/null || true
  rm -f "$CASE/judge-calls"                  # fresh judge counter; SAME state dir
  finding fx-1 mutate 'swap|solution.txt|line A|line X' > "$CASE/round-1.jsonl"
  runjudge                                   # run 2: must be dry, executor untouched
  r1=$(wc -l < "$CASE/exec-calls.run1" 2>/dev/null | tr -d ' ' || echo 0)
  r2=$(wc -l < "$CASE/exec-calls" 2>/dev/null | tr -d ' ' || echo 0)
  if [ "$r1" = 1 ] && [ "$r2" = "$r1" ] && [ "$(cat "$CASE/rc")" = 0 ]; then
    ok "AC-c4: rejected finding stays rejected across runs (persistent ledger)"
  else
    no "AC-c4: cross-run replay — run1 exec calls=$r1, after run2=$r2 (want equal, 1) rc=$(cat "$CASE/rc")"
  fi
else
  pend "T2: judge round + JSONL contract + ledger (ledger.jsonl not yet emitted)"
fi

# =====================================================================================
# T3 — terminate + report. Keyed on the report file (its observable).
# =====================================================================================
if [ -f "$FXROOT/c1/state/report.json" ]; then
  /usr/bin/python3 - "$FXROOT/c1/state/report.json" <<'EOP' && ok "AC-d1: report is valid JSON with the contract fields + accepted id" || no "AC-d1: report.json missing/invalid fields (want spec_dir/baseline/rounds_run/accepted/rejected/gate_gaps/outcome)"
import json,sys
r=json.load(open(sys.argv[1]))
assert set(["spec_dir","baseline","rounds_run","accepted","rejected","gate_gaps","outcome"])<=set(r)
assert "fx-1" in r["accepted"] and r["outcome"]=="dry"
EOP
  grep -q 'outcome=dry' "$FXROOT/c1/out" && ok "AC-d2: human summary line printed" \
    || no "AC-d2: no 'outcome=dry' summary line on stdout"

  # case 10: MAX_ROUNDS bounds a judge that never runs dry
  mkcase c10
  for i in 1 2 3 4 5 6 7 8; do
    finding "fx-r$i" mutate 'swap|solution.txt|junk comment|junk comment' > "$CASE/round-$i.jsonl"
  done
  MR=2 runjudge
  jc=$(cat "$CASE/judge-calls" 2>/dev/null || echo 0)
  if [ "$jc" -le 3 ] && [ "$(cat "$CASE/rc")" = 0 ] && grep -q '"outcome": *"rounds-exhausted"' "$STATE/report.json" 2>/dev/null; then
    ok "AC-d3: MAX_ROUNDS=2 bounds an endless judge (calls=$jc, outcome=rounds-exhausted)"
  else
    no "AC-d3: endless-judge case — judge calls=$jc rc=$(cat "$CASE/rc") report=$(cat "$STATE/report.json" 2>/dev/null | head -c 120)"
  fi

  # case 11: dirty preflight -> refuses to run
  mkcase c11
  echo dirt > "$REPO/untracked.txt"
  finding fx-1 mutate 'swap|solution.txt|junk comment|good comment' > "$CASE/round-1.jsonl"
  runjudge
  if [ "$(cat "$CASE/rc")" = 1 ] && [ ! -f "$CASE/exec-calls" ]; then
    ok "AC-d4: dirty worktree fails preflight (constitution: clean isolated worktree)"
  else
    no "AC-d4: ran against a dirty tree — preflight missing (rc=$(cat "$CASE/rc"))"
  fi
else
  pend "T3: terminate + report (report.json not yet emitted)"
fi

echo
[ "$fail" = 0 ] && { echo "VERIFY: PASS"; exit 0; } || { echo "VERIFY: FAIL"; exit 1; }
