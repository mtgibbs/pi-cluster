#!/usr/bin/env bash
# ralph-judge.sh — the post-convergence judge loop (specs/judge-loop, v0.3).
#
# Runs AFTER a spec's deterministic gate is green: an independent judge (JUDGE_CMD, default
# posture: a different model family than the executor) proposes findings against the spec's
# INTENT; an executor (EXECUTOR_CMD, typically qwen) applies one mutation per round; the
# deterministic gate arbitrates every mutation. The gate is inviolable: a mutation that breaks
# it, lowers the score, or shrinks the check count is restored, full stop.
#
# Usage (from the TARGET repo root, on a clean throwaway branch):
#   JUDGE_CMD=... EXECUTOR_CMD=... scripts/ralph-judge.sh <spec-dir>
# Exit: 0 = completed (dry or rounds-exhausted; see the report)
#       1 = aborted fail-closed (preflight/judge/executor/gate/JSONL error; tree restored)
#       2 = gate-unstable (flake detected; tree restored; needs a human)
set -uo pipefail

SPEC_DIR="${1:?usage: ralph-judge.sh <spec-dir>}"
: "${JUDGE_CMD:?JUDGE_CMD is required (the independent reviewer)}"
: "${EXECUTOR_CMD:?EXECUTOR_CMD is required (applies one finding)}"
GATE_SCORE="${GATE_SCORE:-$(cd "$(dirname "$0")" && pwd)/gate-score.sh}"
MAX_ROUNDS="${MAX_ROUNDS:-5}"
MAX_FINDINGS_PER_ROUND="${MAX_FINDINGS_PER_ROUND:-10}"
JUDGE_TIMEOUT="${JUDGE_TIMEOUT:-900}"
EXECUTOR_TIMEOUT="${EXECUTOR_TIMEOUT:-600}"
GATE_TIMEOUT="${GATE_TIMEOUT:-300}"

outcome="aborted"; rounds_run=0; s_base=""; total_base=""
LEDGER=""; REPORT=""

# ---- report on every exit path; the ledger is the source of truth ----------------------
write_report(){
  [ -n "$LEDGER" ] && [ -d "${JUDGE_STATE_DIR:-/nonexistent}" ] || return 0
  local tmp; tmp="$(mktemp "${TMPDIR:-/tmp}/rj-report.XXXXXX")"
  jq -n --slurpfile L <(cat "$LEDGER" 2>/dev/null) \
    --arg sd "$SPEC_DIR" --arg oc "$outcome" --arg sb "$s_base" --arg tb "$total_base" \
    --argjson rr "$rounds_run" '
    { spec_dir: $sd,
      baseline: { score: (if $sb=="" then null else ($sb|tonumber) end),
                  total: (if $tb=="" then null else ($tb|tonumber) end) },
      rounds_run: $rr,
      accepted:  [$L[]? | select(.decision=="accepted")  | .id],
      rejected:  [$L[]? | select(.decision=="rejected")  | .id],
      gate_gaps: [$L[]? | select(.decision=="gate-gap")  | .id],
      outcome: $oc }' > "$tmp" && mv "$tmp" "$REPORT"
}
trap write_report EXIT

die(){ echo "ralph-judge: $2" >&2; outcome="${3:-aborted}"; exit "$1"; }

# ---- preflight (constitution: clean isolated worktree) ---------------------------------
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die 1 "not inside a git work tree"
[ -z "$(git status --porcelain)" ] || die 1 "worktree not clean (untracked included) — refusing to run"
[ -f "$SPEC_DIR/spec.md" ] && [ -f "$SPEC_DIR/verify.sh" ] || die 1 "$SPEC_DIR lacks spec.md/verify.sh"
command -v jq >/dev/null 2>&1 || die 1 "jq is required"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
JUDGE_STATE_DIR="${JUDGE_STATE_DIR:-$(git rev-parse --git-path ralph-judge)}"
mkdir -p "$JUDGE_STATE_DIR" || die 1 "cannot create JUDGE_STATE_DIR"
LEDGER="$JUDGE_STATE_DIR/ledger.jsonl"; REPORT="$JUDGE_STATE_DIR/report.json"
touch "$LEDGER"

ledger_add(){ printf '%s\n' "$1" >> "$LEDGER"; }
ledger_has(){ grep -q "\"id\":\"$1\"" "$LEDGER"; }

# ---- portable watchdog (macOS has no coreutils timeout) --------------------------------
run_bounded(){ # <seconds> <cmd...>  -> 124 on timeout, else the command's exit code
  local secs="$1"; shift
  "$@" & local pid=$! waited=0
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$waited" -ge "$secs" ]; then
      kill -TERM "$pid" 2>/dev/null; sleep 1; kill -KILL "$pid" 2>/dev/null
      wait "$pid" 2>/dev/null; return 124
    fi
    sleep 1; waited=$((waited+1))
  done
  wait "$pid"
}

# ---- the gate: run gate-score on the spec's verify.sh, trust ONLY the sentinel block ----
# Sets G_score G_total G_no_fail G_converged G_vrc and G_tuple. Returns 1 on any parse/run error.
gate(){
  local out line f
  out="$(STRICT=1 run_bounded "$GATE_TIMEOUT" bash "$GATE_SCORE" "$SPEC_DIR/verify.sh" 2>&1)"
  local rc=$?
  [ "$rc" = 124 ] && { echo "ralph-judge: gate timed out" >&2; return 1; }
  # last sentinel wins; the raw verifier output above it is untrusted
  line="$(printf '%s\n' "$out" | awk '/^---GATE-SCORE---$/{ getline l } END{ print l }')"
  [ -n "$line" ] || { echo "ralph-judge: no gate sentinel found" >&2; return 1; }
  G_score="";G_total="";G_no_fail="";G_converged="";G_vrc=""
  G_score="$(printf '%s' "$line" | sed -n 's/.*score=\([0-9.]*\).*/\1/p')"
  G_total="$(printf '%s' "$line" | sed -n 's/.*total=\([0-9]*\).*/\1/p')"
  G_no_fail="$(printf '%s' "$line" | sed -n 's/.*no_fail=\([0-9]*\).*/\1/p')"
  G_converged="$(printf '%s' "$line" | sed -n 's/.*converged=\([0-9]*\).*/\1/p')"
  G_vrc="$(printf '%s' "$line" | sed -n 's/.*verify_rc=\([0-9]*\).*/\1/p')"
  for f in "$G_score" "$G_total" "$G_no_fail" "$G_converged" "$G_vrc"; do
    [ -n "$f" ] || { echo "ralph-judge: gate line missing a required field: $line" >&2; return 1; }
  done
  G_tuple="$G_score $G_total $G_no_fail $G_converged $G_vrc"
}

restore(){ # <before_head> — exact restore incl. staged + untracked state
  git reset --hard "$1" >/dev/null && git clean -fd >/dev/null
  [ -z "$(git status --porcelain)" ] || die 1 "restore left a dirty tree — refusing to continue"
}

# ---- baseline: two consecutive identical converged runs (flake rule) --------------------
gate || die 1 "baseline gate run failed"
t1="$G_tuple"
gate || die 1 "baseline gate run failed"
[ "$t1" = "$G_tuple" ] || die 2 "gate-unstable" "gate-unstable"
[ "$G_vrc" = 0 ] && [ "$G_converged" = 1 ] && [ "$G_no_fail" = 1 ] && [ "$G_total" -gt 0 ] \
  || die 1 "baseline gate is not green (need verify_rc=0 converged=1 no_fail=1 total>0) — run the builder loop first"
s_base="$G_score"; total_base="$G_total"

# ---- one finding through the guardrail cycle --------------------------------------------
apply_cycle(){ # <finding-json> <round> -> 0 accepted, 1 rejected-continue; may die
  local f="$1" round="$2" id problem before_head erc res
  id="$(printf '%s' "$f" | jq -r .id)"; problem="$(printf '%s' "$f" | jq -r .problem)"
  before_head="$(git rev-parse HEAD)"
  run_bounded "$EXECUTOR_TIMEOUT" $EXECUTOR_CMD "$f"; erc=$?
  if [ "$erc" != 0 ]; then
    restore "$before_head"
    ledger_add "{\"id\":\"$id\",\"decision\":\"rejected\",\"reason\":\"executor-error\",\"round\":$round}"
    die 1 "executor failed/timed out (rc=$erc) — aborting fail-closed"
  fi
  if [ "$(git rev-parse HEAD)" != "$before_head" ]; then
    restore "$before_head"
    ledger_add "{\"id\":\"$id\",\"decision\":\"rejected\",\"reason\":\"executor-committed\",\"round\":$round}"
    die 1 "executor committed — it must never commit"
  fi
  gate || { restore "$before_head"; ledger_add "{\"id\":\"$id\",\"decision\":\"rejected\",\"reason\":\"gate-error\",\"round\":$round}"; die 1 "post-mutation gate failed to run"; }
  local p1="$G_tuple"
  gate || { restore "$before_head"; ledger_add "{\"id\":\"$id\",\"decision\":\"rejected\",\"reason\":\"gate-error\",\"round\":$round}"; die 1 "post-mutation gate failed to run"; }
  if [ "$p1" != "$G_tuple" ]; then
    restore "$before_head"
    ledger_add "{\"id\":\"$id\",\"decision\":\"rejected\",\"reason\":\"gate-unstable\",\"round\":$round}"
    die 2 "gate-unstable after mutation — needs a human" "gate-unstable"
  fi
  if ! { [ "$G_vrc" = 0 ] && [ "$G_converged" = 1 ] && [ "$G_no_fail" = 1 ] \
         && [ "$G_total" = "$total_base" ] \
         && awk -v a="$G_score" -v b="$s_base" 'BEGIN{exit !(a>=b)}'; }; then
    restore "$before_head"
    ledger_add "{\"id\":\"$id\",\"decision\":\"rejected\",\"reason\":\"gate-regressed\",\"round\":$round}"
    return 1
  fi
  res="$(run_bounded "$JUDGE_TIMEOUT" $JUDGE_CMD --check-resolution "$f")"
  if ! printf '%s' "$res" | jq -e --arg id "$id" 'type=="object" and .id==$id and .resolved==true' >/dev/null 2>&1; then
    restore "$before_head"
    ledger_add "{\"id\":\"$id\",\"decision\":\"rejected\",\"reason\":\"not-resolved\",\"round\":$round}"
    return 1
  fi
  [ "$(git rev-parse --abbrev-ref HEAD)" = "$BRANCH" ] || die 1 "branch changed mid-run — refusing to commit"
  git add -A && git commit -q -m "judge: $id — $problem" || die 1 "commit failed"
  ledger_add "{\"id\":\"$id\",\"decision\":\"accepted\",\"round\":$round,\"before_head\":\"$before_head\",\"after_head\":\"$(git rev-parse HEAD)\",\"score\":$G_score}"
  return 0
}

# ---- JSONL contract: fail-closed, whole invocation ---------------------------------------
validate_findings(){ # stdin: raw judge output; stdout: the validated lines; rc 1 = invalid
  local dupdir; dupdir="$(mktemp -d "${TMPDIR:-/tmp}/rj-dup.XXXXXX")"
  local rc=0 line id
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    printf '%s' "$line" | jq -e '
      type=="object"
      and (keys|sort == ["category","file","id","kind","problem","spec_anchor","suggested_change"])
      and (.kind=="mutate" or .kind=="gate-gap")
      and (.category=="clarity" or .category=="naming" or .category=="spec-fidelity" or .category=="gate-gap")
      and (.file|type=="string" and (startswith("/")|not) and (split("/")|index("..")==null))
      and (.problem|type=="string") and (.spec_anchor|type=="string") and (.suggested_change|type=="string")
    ' >/dev/null 2>&1 || { rc=1; break; }
    id="$(printf '%s' "$line" | jq -r .id)"
    [[ "$id" =~ ^[a-z0-9][a-z0-9-]*$ ]] || { rc=1; break; }
    if [ -f "$dupdir/$id" ]; then
      [ "$(cat "$dupdir/$id")" = "$line" ] || { rc=1; break; }
    else
      printf '%s' "$line" > "$dupdir/$id"
      printf '%s\n' "$line"
    fi
  done
  rm -rf "$dupdir"
  return "$rc"
}

# ---- the rounds ---------------------------------------------------------------------------
for round in $(seq 1 "$MAX_ROUNDS"); do
  rounds_run="$round"
  raw="$(run_bounded "$JUDGE_TIMEOUT" $JUDGE_CMD "$SPEC_DIR")"; jrc=$?
  [ "$jrc" = 0 ] || die 1 "judge failed (rc=$jrc)"
  if ! valid="$(printf '%s\n' "$raw" | validate_findings)"; then
    echo "judge-output-invalid" >&2
    die 1 "judge emitted malformed/invalid JSONL — rejecting the whole invocation"
  fi
  mutated=0 processed=0
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    id="$(printf '%s' "$line" | jq -r .id)"
    ledger_has "$id" && continue
    processed=$((processed+1)); [ "$processed" -gt "$MAX_FINDINGS_PER_ROUND" ] && break
    kind="$(printf '%s' "$line" | jq -r .kind)"
    if [ "$kind" = "gate-gap" ]; then
      ledger_add "{\"id\":\"$id\",\"decision\":\"gate-gap\",\"round\":$round}"
      continue
    fi
    # first fresh mutate finding only; later ones wait for a future round against new HEAD
    apply_cycle "$line" "$round" || true
    mutated=1
    break
  done <<EOF
$valid
EOF
  if [ "$mutated" = 0 ]; then outcome="dry"; break; fi
done
[ "$outcome" = dry ] || outcome="rounds-exhausted"

# ---- summary ------------------------------------------------------------------------------
n_a="$(grep -c '"decision":"accepted"' "$LEDGER" 2>/dev/null | tr -d ' ')" || n_a=0
n_r="$(grep -c '"decision":"rejected"' "$LEDGER" 2>/dev/null | tr -d ' ')" || n_r=0
n_g="$(grep -c '"decision":"gate-gap"' "$LEDGER" 2>/dev/null | tr -d ' ')" || n_g=0
echo "judge: $n_a accepted, $n_r rejected, $n_g gate-gaps, outcome=$outcome, report=$REPORT"
exit 0
