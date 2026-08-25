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
QWEN=scripts/ralph-qwen.sh
JUDGE=scripts/ralph-judge.sh

# STAGING, for MODIFICATION tasks. The three-verdict contract is written for creation —
# "pend = the artifact does not exist yet". These tasks edit files that always exist, so
# there is no artifact to presence-gate on and the naive reading makes every unmade change
# a FAIL. That is spec.md §11's own warning: "task 1 is gated on task 9's work, can never
# pass, burns its retries, and stops for a human on iteration one." It did, on iteration
# one — T1 was implemented CORRECTLY, both its checks went PASS, and the run still exited
# non-zero on T2's FAILs, so ralph reset the worktree and destroyed the work.
#
# The discriminator for a modification is therefore:
#   still the ORIGINAL known-good line  -> pend   (not built yet — a later task owns it)
#   changed to something unrecognised   -> FAIL   (exists and is wrong)
# STRICT=1 promotes the pends, so nothing hides at the end.
echo "== T1  status sweep is configurable (AC-4)"
if [ -f "$HB" ]; then
  if grep -qE 'mmin[[:space:]]+"?\+\$\{RALPH_STATUS_KEEP_MIN:-1440\}' "$HB"; then
    ok "status-sweep-configurable" presence
  elif grep -qE 'mmin[[:space:]]+\+1440' "$HB"; then
    pend "status-sweep-configurable" "still the original hardcoded -mmin +1440"
  else
    no "status-sweep-configurable" "neither the original sweep nor RALPH_STATUS_KEEP_MIN found — the sweep was changed to something unrecognised"
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
    # the ORIGINAL default — T2 has not run yet, and a later task owning the change is
    # never a FAIL. See the staging note above T1.
    *'$HOME/.harness'*)  pend "$var-defaults-to-repo" "still the original \$HOME/.harness default" ;;
    "")                  no "$var-defaults-to-repo" "no assignment to $var found in $file" ;;
    *)                   no "$var-defaults-to-repo" "changed to an unrecognised default: $line" ;;
  esac
  # The override seam is an INVARIANT, not a deliverable: it is true today and must stay
  # true through T2. Invariant negatives never pend — "not my task yet" is not a defence
  # for breaking something that already works.
  case "$line" in
    *'${RALPH_LOG_DIR:'*|*'${RALPH_STATUS_DIR:'*) ok "$var-override-preserved" negative ;;
    *) no "$var-override-preserved" "the explicit RALPH_*_DIR override was dropped; ralph-log.sh:28 promises it verbatim" negative ;;
  esac
done

echo "== T3  the record is distilled by the harness, not by the project (AC-2)"
for f in scripts/ralph-qwen.sh scripts/ralph-codex.sh; do
  if [ ! -f "$f" ]; then pend "$(basename "$f")-indexes-after-task" "$f absent"; continue; fi
  if ! grep -q 'loop-index.py' "$f"; then
    pend "$(basename "$f")-indexes-after-task" "no loop-index.py call"
  elif grep -q 'loop-index.py.*--spec' "$f"; then
    ok "$(basename "$f")-indexes-after-task" presence
  else
    # §6c: 25 tasks.txt in this repo define a T1. Indexing unscoped merges unrelated
    # features and flags all of them as requeued. The call exists and is wrong -> FAIL.
    no "$(basename "$f")-indexes-after-task" "calls loop-index.py without --spec; task labels are unique only within a spec dir (§6c)"
  fi
done
# §6b, and it is a real ordering constraint, not a style note: a task that rewrites the
# script bash is currently executing kills the run mid-flight. Keep it last.
if [ -f specs/evidence-convention/tasks.txt ]; then
  # Self-editing tasks must form a contiguous SUFFIX: bash reads the running script
  # incrementally, so any task after one that rewrites ralph-qwen.sh runs against a file
  # that moved under it. More than one such task is fine; a non-self-editing task after
  # them is not.
  first_self=$(grep -n 'ralph-qwen.sh' specs/evidence-convention/tasks.txt | head -1 | cut -d: -f1)
  last_other=$(grep -vn 'ralph-qwen.sh' specs/evidence-convention/tasks.txt | grep -c . >/dev/null; grep -n . specs/evidence-convention/tasks.txt | grep -v 'ralph-qwen.sh' | tail -1 | cut -d: -f1)
  if [ -z "$first_self" ]; then
    ok "self-editing-tasks-are-a-suffix" negative
  elif [ -z "$last_other" ] || [ "$last_other" -lt "$first_self" ]; then
    ok "self-editing-tasks-are-a-suffix" negative
  else
    no "self-editing-tasks-are-a-suffix" "task line $last_other does not edit ralph-qwen.sh but follows line $first_self which does; bash reads scripts incrementally (§6b)" negative
  fi
fi

echo "== T4  'did work happen' vs 'was evidence collected' are separate questions"
# The convention put the harness's own bookkeeping into the tree the harness measures.
# Two control-flow decisions broke on that, both by asking git status about EVERYTHING:
#   ralph-qwen.sh  no-op guard      -> its own status heartbeat counted as "work happened"
#   ralph-judge.sh clean preflight  -> its own index made the tree permanently dirty
# Presence of evidence is not proof of work. Scope the work question AND assert the
# evidence question separately — excluding .evidence/ on its own just moves the blind spot.
# Asserted as a NEGATIVE: no unscoped `git status --porcelain` may remain in either
# decider. The first version grepped for the PRESENCE of one scoped call and passed while
# two of ralph-judge.sh's three call sites were still unscoped — a presence check over a
# file with several call sites, which is the exact false-PASS class this gate exists to
# catch. Search proves absence; presence proves nothing about the other lines.
unscoped=""
for file in "$QWEN" "$JUDGE"; do
  [ -f "$file" ] || continue
  hits="$(grep -nE 'git .*status --porcelain' "$file" | grep -v ":\!\.evidence" | cut -d: -f1 | tr '\n' ',')"
  [ -n "$hits" ] && unscoped="$unscoped $file:${hits%,}"
done
if [ ! -f "$QWEN" ] || [ ! -f "$JUDGE" ]; then
  pend "work-question-excludes-evidence" "harness scripts absent"
elif [ -n "$unscoped" ]; then
  no "work-question-excludes-evidence" "unscoped git status --porcelain at$unscoped — every reader that DECIDES must exclude .evidence (§6d)" negative
else
  ok "work-question-excludes-evidence" negative
fi

# The positive half. Without it, excluding .evidence/ means a silent indexing failure looks
# exactly like a healthy run, because loop-index.py is invoked best-effort (`|| WARN`).
if [ -f "$QWEN" ]; then
  grep -qE 'index\.jsonl' "$QWEN" \
    && ok "evidence-collection-is-asserted" presence \
    || no "evidence-collection-is-asserted" "excluding .evidence from the work question without asserting collection just moves the blind spot (§6d)"
else pend "evidence-collection-is-asserted" "$QWEN absent"; fi

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
