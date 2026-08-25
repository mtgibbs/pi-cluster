#!/usr/bin/env bash
# specs/evidence-spec-nesting/verify.sh — acceptance gate for the slug-nested evidence layout.
# Run from repo root:  bash specs/evidence-spec-nesting/verify.sh   (STRICT=1 for the final pass)
#
# Three verdicts, house convention: PASS satisfied · FAIL the artifact exists and is wrong
# · pend the artifact does not exist yet. STRICT=1 promotes every pend to FAIL.
#
# Scored by evidence class, because a count of green checks is not a measure of anything:
#   negative — a forbidden shape is absent (sound: the search proves absence)
#   exec     — something actually ran and was observed
#   presence — a symbol appears somewhere (scaffolding, never proof)
#
# HERMETIC. Every executing check builds a throwaway git repo under $TMPDIR, sources the two
# helpers directly, and redirects RALPH_LOG_DIR / RALPH_STATUS_DIR into it. It never reads or
# writes the operator's real .evidence/ or ~/.harness/ — a gate that sweeps the corpus it is
# meant to be protecting would be its own worst defect.
#
# WHY IT SOURCES THE HELPERS RATHER THAN DRIVING A LOOP: these are path and sweep behaviours,
# not loop behaviours. specs/ralph-retry-contract and specs/run-regression-guard already drive
# real ralph loops with a mock `oc` for the things that need it; duplicating that here would buy
# minutes of runtime and no additional coverage.
#
# RED-BEFORE-GREEN (specs/amendments.md, "Gates must prove they can fail"): AC-4, AC-5, AC-8 and
# AC-9 fail at e669455, the commit before the implementation. Transcript in
# evidence/2026-08-25-red-before-green.md. AC-3, AC-7 and AC-10 are invariant guards — green
# both before and after — and are scored `negative` rather than counted as proof of this change.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 2

PASS=0; FAIL=0; PEND=0; N_NEG=0; N_EXEC=0; N_PRES=0
ok(){   printf '  PASS  %s\n' "$1"; PASS=$((PASS+1)); cls "${2:-presence}"; }
no(){   printf '  FAIL  %s — %s\n' "$1" "$2"; FAIL=$((FAIL+1)); cls "${3:-presence}"; }
pend(){ printf '  pend  %s (%s)\n' "$1" "$2"; PEND=$((PEND+1)); }
cls(){  case "$1" in negative) N_NEG=$((N_NEG+1));; exec) N_EXEC=$((N_EXEC+1));; *) N_PRES=$((N_PRES+1));; esac; }

LOG=scripts/ralph-log.sh
HB=scripts/ralph-status.sh
IDX=scripts/loop-index.py
QWEN=scripts/ralph-qwen.sh
CODEX=scripts/ralph-codex.sh
ROOT_ABS="$(pwd)"
SLUG=asset-ladder                       # the fixture's spec dir basename
TMPROOT="$(mktemp -d "${TMPDIR:-/tmp}/esn.XXXXXX")"
trap 'rm -rf "$TMPROOT"' EXIT

# ---------------------------------------------------------------- scope / litter (FIRST)
stray="$(find specs/evidence-spec-nesting -type f \
  ! -name spec.md ! -name tasks.txt ! -name verify.sh \
  ! -path 'specs/evidence-spec-nesting/fixtures/*' \
  ! -path 'specs/evidence-spec-nesting/evidence/*' 2>/dev/null)"
[ -z "$stray" ] && ok "scope:no-litter-in-spec-dir" negative \
  || { no "scope:no-litter-in-spec-dir" "unexpected files" negative; echo "$stray" | sed 's/^/          /'; }

# ---------------------------------------------------------------- fixture builder
# mkrepo <dir> — a git repo with one spec dir and one task commit, ready to be logged into.
mkrepo() {
  local d="$1"
  mkdir -p "$d" && git -C "$d" init -q . 2>/dev/null
  git -C "$d" commit -q --allow-empty -m "init" 2>/dev/null
  mkdir -p "$d/specs/$SLUG"
  printf 'T1: first thing\nT2: second thing\n' > "$d/specs/$SLUG/tasks.txt"
  git -C "$d" add -A 2>/dev/null && git -C "$d" commit -q -m "ralph(qwen): T1 — first thing" 2>/dev/null
}

# runloop <repo> <agent> [logroot] [statusroot] — source the helpers and simulate one attempt.
# Emits nothing; the filesystem is the observation.
runloop() {
  local repo="$1" agent="$2" lr="${3:-}" sr="${4:-}"
  env -u RALPH_LOG_DIR -u RALPH_STATUS_DIR \
      RALPH_AGENT="$agent" RALPH_BUS=off \
      ${lr:+RALPH_LOG_DIR="$lr"} ${sr:+RALPH_STATUS_DIR="$sr"} \
      bash -c '
    ROOT="'"$repo"'"; SPEC_DIR="specs/'"$SLUG"'"; TASKS="$ROOT/$SPEC_DIR/tasks.txt"; RETRIES=2
    . "'"$ROOT_ABS"'/'"$HB"'" 2>/dev/null
    . "'"$ROOT_ABS"'/'"$LOG"'" 2>/dev/null
    hb_init 2>/dev/null; log_init >/dev/null 2>&1
    HB_TASK="T1: first thing"; HB_TIDX=1; hb_write running 2>/dev/null
    p="$(log_path "T1: first thing" 1 2>/dev/null)"
    [ -n "$p" ] && [ "$p" != /dev/null ] && echo transcript-body > "$p"
    log_failure "T1: first thing" 1 "FAIL: a check" 2>/dev/null
  ' >/dev/null 2>&1
}

if [ ! -f "$LOG" ] || [ ! -f "$HB" ]; then
  pend "helpers-present" "$LOG / $HB absent"
  echo; echo "score: $PASS PASS / $FAIL FAIL / $PEND pend"; exit 1
fi

# ================================================================ AC-1 / AC-2  the layout
echo "== AC-1/AC-2  artefacts are filed under the spec slug"
R1="$TMPROOT/ac12"; mkrepo "$R1"; runloop "$R1" qwen
rundir="$(find "$R1/.evidence/runs" -mindepth 2 -maxdepth 2 -type d -name 'qwen-*' 2>/dev/null | head -1)"
statf="$(find "$R1/.evidence/status" -mindepth 2 -maxdepth 2 -name 'qwen-*.json' 2>/dev/null | head -1)"

if [ -n "$rundir" ] && [ "$(basename "$(dirname "$rundir")")" = "$SLUG" ]; then
  ok "AC-1:runs-nested-under-slug" exec
elif find "$R1/.evidence/runs" -mindepth 1 -maxdepth 1 -type d -name 'qwen-*' 2>/dev/null | grep -q .; then
  no "AC-1:runs-nested-under-slug" "run dir is still flat in the root — no spec level" exec
else
  no "AC-1:runs-nested-under-slug" "no run directory was created at all" exec
fi

if [ -n "$statf" ] && [ "$(basename "$(dirname "$statf")")" = "$SLUG" ]; then
  ok "AC-2:status-nested-under-slug" exec
elif find "$R1/.evidence/status" -mindepth 1 -maxdepth 1 -name 'qwen-*.json' 2>/dev/null | grep -q .; then
  no "AC-2:status-nested-under-slug" "status file is still flat in the root — no spec level" exec
else
  no "AC-2:status-nested-under-slug" "no status file was written at all" exec
fi

# ================================================================ AC-3  SG-1, the leaf name
# The invariant that protects every downstream pid parser. Green before this change too — it is
# a guard on the design, not evidence for it.
echo "== AC-3  the leaf name is <agent>-<pid> and carries no slug (SG-1)"
# Deliberately layout-AGNOSTIC: search at any depth rather than reusing AC-1's nested find.
# This is an invariant, true before this change and after, and it must fail only when the leaf
# name is actually wrong. Reusing the depth-2 find made it report `leaf 'none'` on a flat tree —
# a red mark for "the layout is flat", which is AC-1's job to say, in a check whose entire
# purpose is to be independent of the layout.
anyrun="$(find "$R1/.evidence/runs" -type d -name 'qwen-*' 2>/dev/null | head -1)"
anystat="$(find "$R1/.evidence/status" -name 'qwen-*.json' 2>/dev/null | head -1)"
leaf="$(basename "${anyrun:-none}")"
sleaf="$(basename "${anystat:-none.json}" .json)"
bad=""
case "$leaf"  in *"$SLUG"*) bad="run dir leaf '$leaf'" ;; esac
case "$sleaf" in *"$SLUG"*) bad="${bad:+$bad, }status leaf '$sleaf'" ;; esac
if [ -n "$bad" ]; then
  no "AC-3:leaf-carries-no-slug" "$bad — pid parsers split on the first dash and will read the slug as part of the pid" negative
elif printf '%s' "$leaf" | grep -qE '^(qwen|codex)-[0-9]+$' \
  && printf '%s' "$sleaf" | grep -qE '^(qwen|codex)-[0-9]+$'; then
  ok "AC-3:leaf-carries-no-slug" negative
else
  no "AC-3:leaf-carries-no-slug" "leaf '$leaf' / '$sleaf' is not exactly <agent>-<pid>" negative
fi

# ================================================================ AC-4 / AC-8 / AC-9  the index
echo "== AC-4/AC-8/AC-9  the index reads the nested tree, both executors, real names"
if [ ! -f "$IDX" ]; then
  pend "AC-4:index-recovers-pid"   "$IDX absent"
  pend "AC-8:index-sees-codex"     "$IDX absent"
  pend "AC-9:index-names-real-dir" "$IDX absent"
elif ! command -v python3 >/dev/null 2>&1; then
  pend "AC-4:index-recovers-pid"   "python3 unavailable"
  pend "AC-8:index-sees-codex"     "python3 unavailable"
  pend "AC-9:index-names-real-dir" "python3 unavailable"
else
  R2="$TMPROOT/idx"; mkrepo "$R2"
  runloop "$R2" qwen; runloop "$R2" codex
  qdir="$(find "$R2/.evidence/runs" -type d -name 'qwen-*'  2>/dev/null | head -1)"
  cdir="$(find "$R2/.evidence/runs" -type d -name 'codex-*' 2>/dev/null | head -1)"
  qpid="${qdir##*-}"; cpid="${cdir##*-}"
  HOME="$R2" python3 "$ROOT_ABS/$IDX" --repo "$R2" --spec "specs/$SLUG" \
       -o "$R2/out.md" --jsonl "$R2/out.jsonl" >/dev/null 2>&1
  if [ ! -s "$R2/out.jsonl" ]; then
    no "AC-4:index-recovers-pid"   "the indexer produced no rows for a nested tree" exec
    no "AC-8:index-sees-codex"     "the indexer produced no rows for a nested tree" exec
    no "AC-9:index-names-real-dir" "the indexer produced no rows for a nested tree" exec
  else
    # AC-4 — the pid must come back as the bare number, with its attempt log attributed.
    got="$(python3 - "$R2/out.jsonl" "$qpid" <<'PY' 2>/dev/null
import json,sys
rows=[json.loads(l) for l in open(sys.argv[1]) if l.strip()]
for r in rows:
    for run in (r.get("runs") or []):
        if str(run.get("pid")) == sys.argv[2] and (run.get("attempt_logs") or 0) >= 1:
            print("yes"); sys.exit()
print("no")
PY
)"
    [ "$got" = yes ] \
      && ok "AC-4:index-recovers-pid" exec \
      || no "AC-4:index-recovers-pid" "no row carries pid=$qpid with an attempt log — the nested run was not enumerated, or the pid was mis-parsed" exec

    # AC-8 — the codex run must be enumerated on equal terms.
    gotc="$(python3 - "$R2/out.jsonl" "$cpid" <<'PY' 2>/dev/null
import json,sys
rows=[json.loads(l) for l in open(sys.argv[1]) if l.strip()]
for r in rows:
    for run in (r.get("runs") or []):
        if str(run.get("pid")) == sys.argv[2] and (run.get("attempt_logs") or 0) >= 1:
            print("yes"); sys.exit()
print("no")
PY
)"
    [ "$gotc" = yes ] \
      && ok "AC-8:index-sees-codex" exec \
      || no "AC-8:index-sees-codex" "the codex run (pid=$cpid) has no attempt logs in the index — store 3 enumeration is executor-specific" exec

    # AC-9 — the rendered name must be the directory that exists, never a composed one.
    if [ -s "$R2/out.md" ] && grep -q "codex-$cpid" "$R2/out.md" && ! grep -q "qwen-$cpid" "$R2/out.md"; then
      ok "AC-9:index-names-real-dir" exec
    elif grep -q "qwen-$cpid" "$R2/out.md" 2>/dev/null; then
      no "AC-9:index-names-real-dir" "rendered the codex run as qwen-$cpid — a path that does not exist" exec
    else
      no "AC-9:index-names-real-dir" "the codex run's directory name never appears in the rendered index" exec
    fi
  fi
fi

# ================================================================ AC-5  SG-2, per-run expiry
echo "== AC-5  an aged spec directory does not take its fresh runs with it (SG-2)"
R3="$TMPROOT/reap"; mkrepo "$R3"
mkdir -p "$R3/.evidence/runs/$SLUG/qwen-111" "$R3/.evidence/runs/$SLUG/qwen-222"
echo a > "$R3/.evidence/runs/$SLUG/qwen-111/T1-attempt1.log"
echo b > "$R3/.evidence/runs/$SLUG/qwen-222/T1-attempt1.log"
# Only the SPEC dir is aged; both runs inside are fresh. This is what a feature looks like a
# few days after its last run, because a directory's mtime tracks its newest child.
touch -d '10 days ago' "$R3/.evidence/runs/$SLUG" 2>/dev/null \
  || touch -t "$(date -v-10d +%Y%m%d0000 2>/dev/null || echo 202001010000)" "$R3/.evidence/runs/$SLUG" 2>/dev/null
runloop "$R3" qwen
survivors=0
[ -d "$R3/.evidence/runs/$SLUG/qwen-111" ] && survivors=$((survivors+1))
[ -d "$R3/.evidence/runs/$SLUG/qwen-222" ] && survivors=$((survivors+1))
if [ "$survivors" = 2 ]; then
  ok "AC-5:aged-spec-keeps-fresh-runs" exec
else
  no "AC-5:aged-spec-keeps-fresh-runs" "$((2-survivors)) of 2 fresh runs were deleted because their SPEC directory aged out — the sweep is reaping at the feature level" exec
fi

# ================================================================ AC-6  prune, and don't self-delete
echo "== AC-6  emptied slug dirs are pruned; the live one is never a candidate"
R4="$TMPROOT/prune"; mkrepo "$R4"
mkdir -p "$R4/.evidence/runs/dead-spec/qwen-333" "$R4/.evidence/status/dead-spec"
echo x > "$R4/.evidence/runs/dead-spec/qwen-333/T1-attempt1.log"
echo '{}' > "$R4/.evidence/status/dead-spec/qwen-333.json"
for p in "$R4/.evidence/runs/dead-spec/qwen-333" "$R4/.evidence/runs/dead-spec" \
         "$R4/.evidence/status/dead-spec/qwen-333.json"; do
  touch -d '10 days ago' "$p" 2>/dev/null \
    || touch -t "$(date -v-10d +%Y%m%d0000 2>/dev/null || echo 202001010000)" "$p" 2>/dev/null
done
runloop "$R4" qwen
gone=0; [ ! -d "$R4/.evidence/runs/dead-spec" ] && gone=1
# Layout-agnostic for the same reason as AC-3: this asserts "the sweep did not eat the file the
# live run is about to write", which must hold whatever the layout is. Scoping the probe to
# $SLUG made a flat store report the self-deletion bug it does not have.
live=0; find "$R4/.evidence/status" -name 'qwen-*.json' 2>/dev/null | grep -q . && live=1
if [ "$gone" = 1 ] && [ "$live" = 1 ]; then
  ok "AC-6:prunes-empty-keeps-live" exec
elif [ "$live" != 1 ]; then
  no "AC-6:prunes-empty-keeps-live" "the live run's own status file is missing — the -empty prune ran before the file was written and deleted its directory" exec
else
  no "AC-6:prunes-empty-keeps-live" "a wholly-expired spec directory was left behind as an empty husk" exec
fi

# ================================================================ AC-7  SG-3, the override seam
echo "== AC-7  an explicit RALPH_*_DIR is used verbatim as the root (SG-3)"
R5="$TMPROOT/ovr"; mkrepo "$R5"; O="$TMPROOT/ovr-out"
runloop "$R5" qwen "$O/lg" "$O/st"
if [ -d "$O/lg/$SLUG" ] && find "$O/st/$SLUG" -name 'qwen-*.json' 2>/dev/null | grep -q .; then
  ok "AC-7:override-root-verbatim" negative
elif [ -d "$O/lg" ] || [ -d "$O/st" ]; then
  no "AC-7:override-root-verbatim" "the override root was used but the slug level is missing beneath it" negative
else
  no "AC-7:override-root-verbatim" "RALPH_LOG_DIR/RALPH_STATUS_DIR were ignored — every gate in this repo redirects these" negative
fi

# ================================================================ AC-10 SG-4, twins don't drift
echo "== AC-10  both loops take this from the shared helpers (SG-4)"
drift=""
for f in "$QWEN" "$CODEX"; do
  [ -f "$f" ] || { drift="${drift:+$drift }$f(absent)"; continue; }
  grep -q 'ralph-log.sh'    "$f" || drift="${drift:+$drift }$f(no-log-helper)"
  grep -q 'ralph-status.sh' "$f" || drift="${drift:+$drift }$f(no-status-helper)"
  # Neither loop may compute its own evidence path — that is how the twins drift apart.
  grep -qE '^[[:space:]]*(LOG_DIR|HB_DIR|LOG_ROOT)=' "$f" && drift="${drift:+$drift }$f(defines-own-pathing)"
done
[ -z "$drift" ] && ok "AC-10:twins-share-the-helpers" negative \
  || no "AC-10:twins-share-the-helpers" "$drift" negative

# ================================================================ this spec follows the convention
echo "== the spec directory follows the convention it documents"
for f in spec.md tasks.txt verify.sh; do
  [ -f "specs/evidence-spec-nesting/$f" ] && ok "convention-self-applies-$f" presence \
    || no "convention-self-applies-$f" "missing" presence
done
gl=$(wc -l < specs/evidence-spec-nesting/verify.sh)
[ "$gl" -le 400 ] && ok "gate-under-400-lines ($gl)" presence \
  || no "gate-under-400-lines" "$gl lines — if a feature's gate needs more, it is two features" presence

if [ "${STRICT:-0}" = 1 ] && [ "$PEND" -gt 0 ]; then
  echo; echo "STRICT=1: promoting $PEND pend to FAIL"
  FAIL=$((FAIL+PEND)); PEND=0
fi
echo
echo "evidence: $N_NEG negative-invariant · $N_EXEC executing · $N_PRES presence"
echo "score: $PASS PASS / $FAIL FAIL / $PEND pend"
[ "$FAIL" -eq 0 ] || exit 1
