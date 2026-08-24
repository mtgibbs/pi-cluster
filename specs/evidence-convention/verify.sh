#!/usr/bin/env bash
# specs/evidence-convention/verify.sh — STATIC gate for the evidence convention.
#
# Three verdicts, house convention: PASS satisfied · FAIL the artifact exists and is wrong
# · pend the artifact does not exist yet. STRICT=1 promotes every pend to FAIL.
# Presence-gate on the ARTIFACT, never on the task number, so each check arms itself the
# moment its target exists, in whatever order the executor builds.
#
# Scored by evidence class, because a count of green checks is not a measure of anything:
#   negative — a forbidden symbol is absent tree-wide (sound: search proves absence)
#   exec     — something actually ran
#   presence — a symbol appears somewhere (scaffolding, never proof)
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 2

PASS=0; FAIL=0; PEND=0
declare_cls=""; N_NEG=0; N_EXEC=0; N_PRES=0
ok(){   printf '  PASS  %s\n' "$1"; PASS=$((PASS+1)); cls "$2"; }
no(){   printf '  FAIL  %s — %s\n' "$1" "$2"; FAIL=$((FAIL+1)); cls "${3:-presence}"; }
pend(){ printf '  pend  %s (%s)\n' "$1" "$2"; PEND=$((PEND+1)); }
cls(){  case "$1" in negative) N_NEG=$((N_NEG+1));; exec) N_EXEC=$((N_EXEC+1));; *) N_PRES=$((N_PRES+1));; esac; }

LOG=scripts/ralph-log.sh
HB=scripts/ralph-status.sh
IDX=scripts/loop-index.py
MET=scripts/loop-metrics.sh
AUD=scripts/loop-meta-audit.py

echo "== T1  status sweep is configurable (AC-4)"
if [ -f "$HB" ]; then
  if grep -qE 'mmin[[:space:]]+"?\+\$\{RALPH_STATUS_KEEP_MIN:-1440\}' "$HB"; then
    ok "status-sweep-configurable" presence
  elif grep -qE 'mmin[[:space:]]+\+1440' "$HB"; then
    no "status-sweep-configurable" "still hardcoded -mmin +1440; committed status files would be deleted daily"
  else
    no "status-sweep-configurable" "neither the hardcoded sweep nor RALPH_STATUS_KEEP_MIN found — did the sweep move?"
  fi
  grep -q 'RALPH_STATUS_KEEP_MIN' "$HB" \
    && ok "status-keep-min-documented" presence \
    || pend "status-keep-min-documented" "RALPH_STATUS_KEEP_MIN not mentioned in the header contract"
else pend "status-sweep-configurable" "$HB absent"; fi

echo "== T2  roots default into the target repo (AC-1)"
for f in "$LOG:LOG_ROOT:runs" "$HB:HB_DIR:status"; do
  file="${f%%:*}"; rest="${f#*:}"; var="${rest%%:*}"; leaf="${rest##*:}"
  if [ ! -f "$file" ]; then pend "$var-defaults-to-repo" "$file absent"; continue; fi
  line="$(grep -m1 "^[[:space:]]*$var=" "$file")"
  case "$line" in
    *".evidence/$leaf"*) ok "$var-defaults-to-repo" presence ;;
    *'$HOME/.harness'*)  no "$var-defaults-to-repo" "still defaults to \$HOME/.harness; the record must live in the repo it describes" ;;
    "")                  no "$var-defaults-to-repo" "no assignment to $var found in $file" ;;
    *)                   no "$var-defaults-to-repo" "unrecognised default: $line" ;;
  esac
  # the override seam must survive: an explicit env var is still honoured verbatim
  case "$line" in
    *'${RALPH_LOG_DIR:'*|*'${RALPH_STATUS_DIR:'*) ok "$var-override-preserved" presence ;;
    *) no "$var-override-preserved" "the explicit RALPH_*_DIR override was dropped; ralph-log.sh:28 promises it verbatim" ;;
  esac
done

echo "== T3  the record is distilled by the harness, not by the project (AC-2)"
for f in scripts/ralph-qwen.sh scripts/ralph-codex.sh; do
  if [ ! -f "$f" ]; then pend "$(basename "$f")-indexes-after-task" "$f absent"; continue; fi
  grep -q 'loop-index.py' "$f" \
    && ok "$(basename "$f")-indexes-after-task" presence \
    || pend "$(basename "$f")-indexes-after-task" "no loop-index.py call"
done

echo "== the tools are generic (AC-3, AC-5) — negative, always armed"
# AC-5 is the whole point of the spec: a project name in harness tooling is the defect.
# Sound as a negative: grep genuinely proves absence. Kept as a literal list because these
# are the repos this harness has actually run against.
KNOWN='notes-from-hearing\|nfh-phase2\|voicecapture\|VoiceCapture\|pi-cluster-loopdoctor\|pi-cluster-retry'
found=""
for f in "$IDX" "$MET" "$AUD"; do
  [ -f "$f" ] || continue
  grep -qi "$KNOWN" "$f" && found="$found $f"
done
if [ -z "$(ls "$IDX" "$MET" "$AUD" 2>/dev/null)" ]; then
  pend "tools-carry-no-project-identifier" "no scripts/loop-* present"
elif [ -n "$found" ]; then
  no "tools-carry-no-project-identifier" "project identifiers in:$found" negative
else
  ok "tools-carry-no-project-identifier" negative
fi

# AC-3: spec dirs are discovered, not enumerated.
if [ -f "$IDX" ]; then
  if grep -qE '"specs/[a-z0-9_-]+/tasks' "$IDX"; then
    no "spec-dirs-discovered-not-enumerated" "a literal spec-dir path appears in $IDX"
  elif grep -q 'SPECS' "$IDX" && grep -q 'glob' "$IDX"; then
    ok "spec-dirs-discovered-not-enumerated" presence
  else
    no "spec-dirs-discovered-not-enumerated" "no glob over specs/*; how are features found?"
  fi
else pend "spec-dirs-discovered-not-enumerated" "$IDX absent"; fi

echo "== the tools actually run (exec — the only class that proves behaviour)"
if [ -f "$IDX" ]; then
  if python3 -c "import ast,sys;ast.parse(open('$IDX').read())" 2>/dev/null; then
    ok "loop-index-parses" exec
    # AC-6: a repo with .evidence/ and no harness must still index. Build a minimal
    # fixture rather than depending on any real project being checked out.
    T="$(mktemp -d)"; git -C "$T" init -q .
    git -C "$T" commit -q --allow-empty -m "T01 fixture: a task commit" 2>/dev/null
    mkdir -p "$T/specs/initial_implementation" "$T/.evidence/status" "$T/.evidence/runs"
    printf 'T01 fixture: a task\n' > "$T/specs/initial_implementation/tasks.txt"
    if HOME="$T" python3 "$IDX" --repo "$T" -o "$T/out.md" --jsonl "$T/out.jsonl" >/dev/null 2>&1 \
       && [ -s "$T/out.md" ]; then
      grep -q 'T01' "$T/out.md" \
        && ok "loop-index-runs-on-a-bare-convention-repo" exec \
        || no "loop-index-runs-on-a-bare-convention-repo" "produced output but never saw the queued task" exec
    else
      no "loop-index-runs-on-a-bare-convention-repo" "failed against a minimal specs/+.evidence/ repo with no harness present" exec
    fi
    rm -rf "$T"
  else
    no "loop-index-parses" "syntax error" exec
  fi
else pend "loop-index-parses" "$IDX absent"; fi

for f in "$MET"; do
  [ -f "$f" ] || { pend "loop-metrics-syntax" "$f absent"; continue; }
  bash -n "$f" 2>/dev/null && ok "loop-metrics-syntax" exec || no "loop-metrics-syntax" "bash -n failed" exec
done
if [ -f "$AUD" ]; then
  python3 -c "import ast,sys;ast.parse(open('$AUD').read())" 2>/dev/null \
    && ok "loop-meta-audit-parses" exec || no "loop-meta-audit-parses" "syntax error" exec
else pend "loop-meta-audit-parses" "$AUD absent"; fi

echo "== this spec directory follows the convention it proposes"
for f in spec.md tasks.txt verify.sh; do
  [ -f "specs/evidence-convention/$f" ] && ok "convention-self-applies-$f" presence \
    || no "convention-self-applies-$f" "missing"
done
gl=$(wc -l < specs/evidence-convention/verify.sh)
[ "$gl" -le 400 ] && ok "gate-under-400-lines ($gl)" presence \
  || no "gate-under-400-lines" "$gl lines — if a feature's gate needs more, it is two features"

if [ "${STRICT:-0}" = 1 ] && [ "$PEND" -gt 0 ]; then
  echo; echo "STRICT=1: promoting $PEND pend to FAIL"
  FAIL=$((FAIL+PEND)); PEND=0
fi
echo
echo "evidence: $N_NEG negative-invariant · $N_EXEC executing · $N_PRES presence"
echo "score: $PASS PASS / $FAIL FAIL / $PEND pend"
[ "$FAIL" -eq 0 ] || exit 1
