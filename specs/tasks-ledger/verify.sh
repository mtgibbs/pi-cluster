#!/usr/bin/env bash
# verify.sh — deterministic acceptance gate for specs/tasks-ledger.
# Run from repo root:  ./specs/tasks-ledger/verify.sh   (STRICT=1 for the final pass)
#
# HERMETIC, TWICE OVER. Every integration check runs a REAL ralph loop in a throwaway git repo
# under $TMPDIR with a mock `oc` first on PATH and RALPH_STATUS_DIR / RALPH_LOG_DIR / RALPH_BUS
# redirected. On top of that, this gate sets BOTH $HOME and $RALPH_LEDGER_DIR into the temp dir,
# because the artefact under test is by design a file in the operator's home. A gate that wrote
# the real ~/.harness/ledger would corrupt the very corpus this feature exists to build.
#
# CREATE EVERY DIRECTORY THE LOOP IS POINTED AT. specs/ralph-retry-contract's gate failed a
# CORRECT implementation for three attempts because run_loop set RETRY_STATE_DIR to a directory
# it never made, so the helper degraded to silence exactly as its own AC demanded. A gate that
# models a degraded mode must not accidentally create that mode in its own fixtures.
#
# ANCHORING. Per the dilemma recorded 2026-08-18: every check presence-gates on ITS OWN task's
# narrowest deliverable. T1 creates the ledger DIRECTORY, so nothing here may gate on the
# directory — that would arm T2/T3/T4's checks during T1 and make T1 impossible to pass.
set -uo pipefail

L="scripts/ralph-ledger.sh"
Q="scripts/ralph-qwen.sh"
C="scripts/ralph-codex.sh"
FIX="specs/tasks-ledger/fixtures"
ROOT_ABS="$(pwd)"
fail=0
ok(){   echo "  PASS  $1"; }
no(){   echo "  FAIL  $1" >&2; fail=1; }
pend(){ if [ "${STRICT:-0}" = 1 ]; then no "$1 — still unbuilt at the final check (STRICT)"
        else echo "  pend  $1 (not built yet)"; fi; }

# bash 3.2 is the target (AGENTS.md). Homebrew's bash 5 hides the empty-array defect entirely,
# so drive the helper on the real /bin/bash.
B32=/bin/bash
[ -x "$B32" ] || B32=bash

TAB="$(printf '\t')"

# ------------------------------------------------------------- scope / litter (FIRST, FATAL)
stray="$(find specs/tasks-ledger -type f \
  ! -name spec.md ! -name tasks.txt ! -name verify.sh \
  ! -path 'specs/tasks-ledger/fixtures/*' \
  ! -path 'specs/tasks-ledger/evidence/*' 2>/dev/null)"
[ -z "$stray" ] && ok "scope:no-litter-in-spec-dir" \
  || { no "scope:no-litter-in-spec-dir"; echo "$stray" | sed 's/^/          /' >&2; }

BASE="${TL_BASE:-origin/main}"
if git rev-parse --verify --quiet "$BASE" >/dev/null 2>&1; then
  git diff --quiet "$BASE" -- specs/TEMPLATE.md scripts/gate-score.sh scripts/loop-report.sh \
      scripts/run-loop.sh scripts/loops scripts/ralph-judge.sh scripts/ralph-status.sh \
      scripts/ralph-log.sh scripts/ralph-bus.sh scripts/ralph-retry.sh \
      specs/loop-doctor specs/run-regression-guard 2>/dev/null \
    && ok "scope:out-of-scope-files-untouched" \
    || no "scope:out-of-scope-files-untouched — spec §5 forbids editing these"
else
  pend "scope:out-of-scope-files-untouched (base '$BASE' unresolvable)"
fi

# §8.4 — the final STRICT backstop must survive untouched in both twins. A resumed run is held
# to the whole spec or the resume is just a way to launder unbuilt work.
for f in "$Q" "$C"; do
  n="$(basename "$f")"
  grep -q 'STRICT=1 bash "\$VERIFY"' "$f" 2>/dev/null \
    && ok "scope:$n-strict-backstop-intact" || no "scope:$n-strict-backstop-intact"
done

# ================================================================== AC10 — tasks.txt read-only
# Structural, and deliberately checked against ALL THREE files including the helper. Nothing in
# scripts/ writes tasks.txt today; this preserves that property, it does not establish it.
w=""
for f in "$L" "$Q" "$C"; do
  [ -f "$f" ] || continue
  # strip comments first — a comment mentioning redirection must not trip this (the loop-doctor
  # ac15 lesson: the third gate defect in this repo's history was a grep that matched a comment)
  body="$(sed 's/[[:space:]]*#.*$//' "$f")"
  printf '%s\n' "$body" | grep -Eq '>[[:space:]]*"?\$(TASKS|\{TASKS)' && w="$w $f:redirect"
  printf '%s\n' "$body" | grep -Eq 'sed[^|]*-i[^|]*\$TASKS|tee[^|]*\$TASKS' && w="$w $f:inplace"
done
[ -z "$w" ] && ok "ac10:tasks.txt-never-written" || no "ac10:tasks.txt-never-written —$w"

# ====================================================================== UNIT TIER (T1 / T2)
if [ ! -f "$L" ]; then
  for c in ac1:functions-defined ac1:bash-n-clean ac1:executable \
           ac2:key-stable-across-worktrees ac2:key-differs-across-repos \
           ac3:records-passed-only ac3:one-line-per-record ac4:degrades-silently \
           ac4:resume-index-zero-when-unwritable ac14:malformed-row-stops-walk \
           ac11:bare-invocation-lists ac11:bare-invocation-no-ledger-ok \
           ac12:forget-removes-only-that-task; do
    pend "$c"
  done
else
  # --------------------------------------------------------------------------- AC1
  miss=""
  for fn in ledger_dir ledger_key ledger_file ledger_record ledger_resume_index; do
    grep -Eq "^[[:space:]]*(function[[:space:]]+)?$fn[[:space:]]*\(\)" "$L" || miss="$miss $fn"
  done
  [ -z "$miss" ] && ok "ac1:functions-defined" || no "ac1:functions-defined — missing:$miss"
  "$B32" -n "$L" 2>/dev/null && ok "ac1:bash-n-clean" || no "ac1:bash-n-clean"
  [ -x "$L" ] && ok "ac1:executable" || no "ac1:executable — chmod +x (T2)"

  # ------------------------------------------------------------------- AC2 (key identity)
  # Two halves, both required. A constant-returning ledger_key satisfies the first alone.
  KT="$(mktemp -d -t tlkey.XXXXXX)"
  mkdir -p "$KT/led"
  ( cd "$KT" && git init -q proj-a && cd proj-a \
      && git config user.email t@t && git config user.name t \
      && git remote add origin https://example.invalid/widgets.git \
      && mkdir -p specs/foo && echo x > specs/foo/spec.md \
      && git add -A && git commit -qm base \
      && git worktree add -q ../wt-differently-named HEAD ) >/dev/null 2>&1
  # Source the helper THE WAY THE LOOPS DO — from inside another script — so that $0 is the
  # caller and BASH_SOURCE[0] is the helper. `bash -c '. "$0"; fn' <helper>` sets $0 TO the
  # helper, which fires a correct sourced-vs-executed guard and runs the CLI instead of the
  # function. That idiom made an earlier draft of this gate test the CLI while claiming to test
  # ledger_key, and every downstream check inherited the garbage.
  WRAP="$(mktemp -t tlwrap.XXXXXX)"
  printf '#!/usr/bin/env bash\n. "%s"\n"$@"\n' "$ROOT_ABS/$L" > "$WRAP"
  keyof(){ ( cd "$1" && SPEC_DIR="specs/foo" RALPH_LEDGER_DIR="$KT/led" \
             "$B32" "$WRAP" ledger_key 2>/dev/null ); }
  k1="$(keyof "$KT/proj-a")"; k2="$(keyof "$KT/wt-differently-named")"
  if [ -n "$k1" ] && [ "$k1" = "$k2" ]; then ok "ac2:key-stable-across-worktrees"
  else no "ac2:key-stable-across-worktrees — '$k1' vs '$k2' (must not be the directory name)"; fi

  for d in b c; do
    ( cd "$KT" && mkdir -p "side-$d" && cd "side-$d" && git init -q proj && cd proj \
        && git config user.email t@t && git config user.name t \
        && git remote add origin "https://example.invalid/$d-thing.git" \
        && mkdir -p specs/foo && echo x > specs/foo/spec.md \
        && git add -A && git commit -qm base ) >/dev/null 2>&1
  done
  kb="$(keyof "$KT/side-b/proj")"; kc="$(keyof "$KT/side-c/proj")"
  if [ -n "$kb" ] && [ "$kb" != "$kc" ]; then ok "ac2:key-differs-across-repos"
  else no "ac2:key-differs-across-repos — both '$kb' (same dirname must not collide)"; fi

  # ------------------------------------------------------------------- AC3 (record format)
  # Driven with all three verdicts. Asserted in BOTH directions: the PASS name present AND the
  # FAIL/PEND names absent. A pend line reads "  pend  gamma (not built yet)" and CONTAINS the
  # name, so a grep-the-name implementation records it — and a one-directional assertion cannot
  # tell the difference. This is the fourth check in this repo's history written to defeat that
  # exact family of false pass.
  RT="$(mktemp -d -t tlrec.XXXXXX)"; mkdir -p "$RT/led"
  gout="$(cat "$FIX/gate-three-verdicts.txt")"
  ( cd "$KT/proj-a" && SPEC_DIR="specs/foo" RALPH_LEDGER_DIR="$RT/led" \
      "$B32" "$WRAP" ledger_record "T1" "deadbee" "1" "$gout" ) >/dev/null 2>"$RT/err"
  lf="$(find "$RT/led" -name '*.tsv' -type f 2>/dev/null | head -1)"
  if [ -n "$lf" ]; then
    names="$(awk -F'\t' 'NR==1{print $6}' "$lf")"
    hasA=0; hasB=0; hasG=0
    case ",$names," in *,alpha,*) hasA=1;; esac
    case ",$names," in *,beta,*)  hasB=1;; esac
    case ",$names," in *,gamma,*) hasG=1;; esac
    if [ "$hasA" = 1 ] && [ "$hasB" = 0 ] && [ "$hasG" = 0 ]; then ok "ac3:records-passed-only"
    else no "ac3:records-passed-only — field 6 was '$names', want exactly 'alpha'"; fi
    n="$(wc -l < "$lf" | tr -d ' ')"
    f="$(awk -F'\t' 'NR==1{print NF}' "$lf")"
    [ "$n" = 1 ] && [ "$f" = 6 ] && ok "ac3:one-line-per-record" \
      || no "ac3:one-line-per-record — $n line(s), $f field(s), want 1 line of 6"
  else
    no "ac3:records-passed-only — ledger_record wrote no .tsv under RALPH_LEDGER_DIR"
    no "ac3:one-line-per-record — no ledger file"
  fi

  # --------------------------------------------------------------- AC4 (degraded = silent)
  # Point RALPH_LEDGER_DIR at a path that cannot be created. Every function must stay quiet and
  # resume_index must say 0 — degraded means DO NOT SKIP, i.e. do all the work.
  UNW="/dev/null/nope"
  ( cd "$KT/proj-a" && SPEC_DIR="specs/foo" RALPH_LEDGER_DIR="$UNW" \
      "$B32" "$WRAP" ledger_record "T1" "deadbee" "1" "  PASS  alpha" ) \
      >"$RT/o4" 2>"$RT/e4"; rc4=$?
  [ "$rc4" = 0 ] && [ ! -s "$RT/e4" ] && ok "ac4:degrades-silently" \
    || no "ac4:degrades-silently — rc=$rc4, stderr=$(head -c 120 "$RT/e4" 2>/dev/null)"
  printf '  PASS  alpha\n' > "$RT/g4"
  ri="$( cd "$KT/proj-a" && SPEC_DIR="specs/foo" RALPH_LEDGER_DIR="$UNW" \
      "$B32" "$WRAP" ledger_resume_index "$ROOT_ABS/$FIX/inner-spec/tasks.txt" "$RT/g4" 2>/dev/null )"
  [ "$ri" = 0 ] && ok "ac4:resume-index-zero-when-unwritable" \
    || no "ac4:resume-index-zero-when-unwritable — got '$ri'"

  # --------------------------------------------------------------- AC14 (malformed row)
  MT="$(mktemp -d -t tlmal.XXXXXX)"; mkdir -p "$MT/led"
  mk="$( cd "$KT/proj-a" && SPEC_DIR="specs/foo" RALPH_LEDGER_DIR="$MT/led" \
        "$B32" "$WRAP" ledger_key 2>/dev/null )"
  if [ -n "$mk" ]; then
    printf 'this is not a ledger row at all\n' > "$MT/led/$mk.tsv"
    printf '  PASS  alpha\n  PASS  beta\n  PASS  gamma\n' > "$MT/g"
    ri2="$( cd "$KT/proj-a" && SPEC_DIR="specs/foo" RALPH_LEDGER_DIR="$MT/led" \
        "$B32" "$WRAP" ledger_resume_index "$ROOT_ABS/$FIX/inner-spec/tasks.txt" "$MT/g" 2>"$MT/e" )"
    [ "$ri2" = 0 ] && [ ! -s "$MT/e" ] && ok "ac14:malformed-row-stops-walk" \
      || no "ac14:malformed-row-stops-walk — index '$ri2', stderr=$(head -c 80 "$MT/e" 2>/dev/null)"
  else
    pend "ac14:malformed-row-stops-walk"
  fi

  # ------------------------------------------------------------------- AC11 / AC12 (the CLI)
  CT="$(mktemp -d -t tlcli.XXXXXX)"; mkdir -p "$CT/led"
  ck="$( cd "$KT/proj-a" && SPEC_DIR="specs/foo" RALPH_LEDGER_DIR="$CT/led" \
        "$B32" "$WRAP" ledger_key 2>/dev/null )"
  if [ -n "$ck" ]; then
    # bare invocation with NO ledger: exit 0, says "no ledger", never a usage error
    o="$( cd "$KT/proj-a" && SPEC_DIR="specs/foo" RALPH_LEDGER_DIR="$CT/led" \
          "$B32" "$ROOT_ABS/$L" 2>&1 )"; rc=$?
    if [ "$rc" = 0 ] && printf '%s' "$o" | grep -qi 'no ledger'; then
      ok "ac11:bare-invocation-no-ledger-ok"
    else no "ac11:bare-invocation-no-ledger-ok — rc=$rc, out='$(printf '%s' "$o" | head -1)'"; fi

    printf 'T1%sc1%s1%s1%s1%salpha\n' "$TAB" "$TAB" "$TAB" "$TAB" "$TAB"  > "$CT/led/$ck.tsv"
    printf 'T2%sc2%s2%s1%s1%sbeta\n'  "$TAB" "$TAB" "$TAB" "$TAB" "$TAB" >> "$CT/led/$ck.tsv"
    printf 'T3%sc3%s3%s1%s1%sgamma\n' "$TAB" "$TAB" "$TAB" "$TAB" "$TAB" >> "$CT/led/$ck.tsv"
    cp "$CT/led/$ck.tsv" "$CT/before.tsv"

    o="$( cd "$KT/proj-a" && SPEC_DIR="specs/foo" RALPH_LEDGER_DIR="$CT/led" \
          "$B32" "$ROOT_ABS/$L" 2>&1 )"; rc=$?
    if [ "$rc" = 0 ] && printf '%s' "$o" | grep -q 'T2'; then ok "ac11:bare-invocation-lists"
    else no "ac11:bare-invocation-lists — rc=$rc, rows not shown"; fi

    ( cd "$KT/proj-a" && SPEC_DIR="specs/foo" RALPH_LEDGER_DIR="$CT/led" \
        "$B32" "$ROOT_ABS/$L" forget T2 ) >/dev/null 2>&1
    gone=1; grep -q '^T2	' "$CT/led/$ck.tsv" 2>/dev/null && gone=0
    kept=1
    grep -q '^T1	c1	1	1	1	alpha$' "$CT/led/$ck.tsv" 2>/dev/null || kept=0
    grep -q '^T3	c3	3	1	1	gamma$' "$CT/led/$ck.tsv" 2>/dev/null || kept=0
    [ "$gone" = 1 ] && [ "$kept" = 1 ] && ok "ac12:forget-removes-only-that-task" \
      || no "ac12:forget-removes-only-that-task — T2 gone=$gone, others byte-intact=$kept"
  else
    pend "ac11:bare-invocation-no-ledger-ok"
    pend "ac11:bare-invocation-lists"
    pend "ac12:forget-removes-only-that-task"
  fi
  rm -rf "$KT" "$RT" "$MT" "$CT"; rm -f "$WRAP"
fi

# ============================================================ INTEGRATION TIER (T3 / T4)
# mk_repo <T>   : throwaway repo + inner spec, base commit
# run_in  <T> …: one ralph run inside it, HOME and RALPH_LEDGER_DIR both inside $T
mk_repo() {
  local T="$1"
  mkdir -p "$T/bin" "$T/mock" "$T/repo" "$T/status" "$T/logs" "$T/home" "$T/led"
  cp "$FIX/mock-oc" "$T/bin/oc"; chmod +x "$T/bin/oc"
  cp -R "$FIX/mock-exec/build-all" "$T/mock/scenario"
  ( cd "$T/repo" && git init -q . && git config user.email t@t && git config user.name t
    cp -R "$ROOT_ABS/$FIX/inner-spec" spec
    printf 'opencode.json\n' > .gitignore
    printf '{}\n' > opencode.json
    git add -A && git commit -qm base ) >/dev/null 2>&1
}
run_in() {
  local T="$1" resume="${2:-0}"
  rm -f "$T/mock/attempt" "$T/mock/prompts.txt"
  ( cd "$T/repo" && PATH="$T/bin:$PATH" MOCK_DIR="$T/mock" HOME="$T/home" \
      RALPH_LEDGER_DIR="$T/led" RALPH_RESUME="$resume" \
      RALPH_STATUS_DIR="$T/status" RALPH_LOG_DIR="$T/logs" RALPH_BUS=off RALPH_SHEET=off \
      RALPH_RETRIES=1 OC_RUN_TIMEOUT=30 \
      bash "$ROOT_ABS/$Q" spec ) > "$T/loop.log" 2>&1
  echo $?
}
# How many tasks did the executor actually get asked to do?
# ANCHOR ON THE PROMPT'S OWN PHRASE. The label is NOT at line start — ralph's prompt reads
# "Read $SPEC. Implement ONLY this one task, nothing else: T1: create a.txt". An earlier draft
# grepped '^T[0-9]:' here, never matched anything, and so reported "0 tasks executed" for EVERY
# run — which made ac6 (want 0) pass against a loop that skipped nothing at all. Fourth instance
# in this repo of a check passing for the wrong reason; found by running the gate against a
# near-correct implementation.
_MARK='nothing else: '
# `grep -c` on a MISSING file prints nothing and exits 2, so an unguarded $(...) yields the
# empty string — which compares unequal to 0 and fails a check that should pass. A fully-skipped
# resume run never creates prompts.txt at all, so this is the normal case, not the edge case.
executed(){ local n; n="$(grep -c "$_MARK"'T[0-9]' "$1/mock/prompts.txt" 2>/dev/null)"
            [ -n "$n" ] || n=0; echo "$n"; }
ran_task(){ grep -q "$_MARK$2:" "$1/mock/prompts.txt" 2>/dev/null; }

# ------------------------------------------------- AC5 — the happy path is sacred, always live
# Must pass BEFORE any implementation exists. That is what proves this harness really drives the
# loop, so a later green cannot be an artefact of a broken fixture.
T5="$(mktemp -d -t tlac5.XXXXXX)"; mk_repo "$T5"
rc5="$(run_in "$T5" 0)"
c5="$(git -C "$T5/repo" log --oneline | wc -l | tr -d ' ')"
[ "$rc5" = 0 ] && [ "$c5" = "4" ] && ok "ac5:baseline-three-tasks-commit" \
  || no "ac5:baseline-three-tasks-commit — rc=$rc5, $c5 commits, want rc=0 and 4 (base + 3)"
git -C "$T5/repo" log -1 --pretty=%s | grep -q '^ralph(' \
  && ok "ac5:baseline-commit-prefix" || no "ac5:baseline-commit-prefix"
[ -f "$T5/repo/a.txt" ] && [ -f "$T5/repo/b.txt" ] && [ -f "$T5/repo/c.txt" ] \
  && ok "ac5:baseline-all-artifacts" || no "ac5:baseline-all-artifacts"

# AC5's other half: with a FULL ledger present but RESUME OFF, the loop must still hand T1 to
# the executor. Asserted on T1 alone, deliberately. A second run over an already-built tree makes
# every task a no-op, ralph correctly refuses a no-op attempt (ralph-qwen.sh:126) and stops at
# T1 — so "all three executed" is unreachable here and would be a fixture artefact, not the AC.
# What AC5 actually forbids is SKIPPING, and T1 being asked for is exactly that observable.
if [ -f "$L" ]; then
  run_in "$T5" 0 >/dev/null
  ran_task "$T5" T1 && ok "ac5:resume-off-still-executes" \
    || no "ac5:resume-off-still-executes — T1 was never handed to the executor with RALPH_RESUME unset"
else
  pend "ac5:resume-off-still-executes"
fi
rm -rf "$T5"

# ---------------------------------------------------------------- AC6 / AC7 / AC8 / AC9 / AC13
if [ ! -f "$L" ] || ! grep -q 'ledger_record' "$Q" 2>/dev/null; then
  for c in ac6:resume-skips-proven-tasks ac6:skip-line-names-task-and-commit \
           ac7:not-ancestor-not-skipped ac8:reverted-not-skipped \
           ac9:walk-stops-at-first-gap ac13:twins-identical; do
    pend "$c"
  done
else
  # ---- AC6: run to green, then resume. Nothing should be executed at all.
  T6="$(mktemp -d -t tlac6.XXXXXX)"; mk_repo "$T6"
  run_in "$T6" 0 >/dev/null
  run_in "$T6" 1 >/dev/null
  [ "$(executed "$T6")" = 0 ] && ok "ac6:resume-skips-proven-tasks" \
    || no "ac6:resume-skips-proven-tasks — executed $(executed "$T6") task(s), want 0"
  # The skip must be announced, with the task AND the commit it trusted. Scoped to the skip
  # line only: the task banner already echoes every label, so grepping the whole log for "T1"
  # passes against a loop that skips silently.
  sl="$(grep -i 'skip' "$T6/loop.log" | head -5)"
  if printf '%s' "$sl" | grep -q 'T1' && printf '%s' "$sl" | grep -Eq '[0-9a-f]{7}'; then
    ok "ac6:skip-line-names-task-and-commit"
  else no "ac6:skip-line-names-task-and-commit — skip lines were: $(printf '%s' "$sl" | tr '\n' '|')"; fi
  rm -rf "$T6"

  # ---- AC7: ledger valid, but HEAD is a branch that never carried the commits.
  T7="$(mktemp -d -t tlac7.XXXXXX)"; mk_repo "$T7"
  base7="$(git -C "$T7/repo" rev-parse HEAD)"
  run_in "$T7" 0 >/dev/null
  ( cd "$T7/repo" && git checkout -q -b fresh "$base7" ) >/dev/null 2>&1
  run_in "$T7" 1 >/dev/null
  [ "$(executed "$T7")" = 3 ] && ok "ac7:not-ancestor-not-skipped" \
    || no "ac7:not-ancestor-not-skipped — executed $(executed "$T7")/3 on a branch lacking the commits"
  rm -rf "$T7"

  # ---- AC8: THE REVERT CASE. T1's commit is still an ancestor of HEAD; a.txt is gone.
  # An ancestry-only implementation passes every other check and fails exactly here.
  T8="$(mktemp -d -t tlac8.XXXXXX)"; mk_repo "$T8"
  run_in "$T8" 0 >/dev/null
  t1sha="$(git -C "$T8/repo" log --format='%H %s' | grep -m1 'T1' | cut -d' ' -f1)"
  ( cd "$T8/repo" && git revert --no-edit "$t1sha" ) >/dev/null 2>&1
  anc=0; git -C "$T8/repo" merge-base --is-ancestor "$t1sha" HEAD 2>/dev/null && anc=1
  run_in "$T8" 1 >/dev/null
  if [ "$anc" = 1 ] && [ ! -f "$T8/repo/a.txt" ] && ran_task "$T8" T1; then
    ok "ac8:reverted-not-skipped"
  else
    no "ac8:reverted-not-skipped — ancestor=$anc a.txt-absent=$([ -f "$T8/repo/a.txt" ] && echo no || echo yes) T1-rerun=$(ran_task "$T8" T1 && echo yes || echo no)"
  fi
  rm -rf "$T8"

  # ---- AC9: T2 broken in the middle. T1 skips; T2 AND T3 must both run even though T3's own
  # entry would qualify on its own. The resume point is one index, not a set.
  T9="$(mktemp -d -t tlac9.XXXXXX)"; mk_repo "$T9"
  run_in "$T9" 0 >/dev/null
  t2sha="$(git -C "$T9/repo" log --format='%H %s' | grep -m1 'T2' | cut -d' ' -f1)"
  ( cd "$T9/repo" && git revert --no-edit "$t2sha" ) >/dev/null 2>&1
  run_in "$T9" 1 >/dev/null
  if ! ran_task "$T9" T1 && ran_task "$T9" T2 && ran_task "$T9" T3; then
    ok "ac9:walk-stops-at-first-gap"
  else
    no "ac9:walk-stops-at-first-gap — T1-rerun=$(ran_task "$T9" T1 && echo yes || echo no) T2-rerun=$(ran_task "$T9" T2 && echo yes || echo no) T3-rerun=$(ran_task "$T9" T3 && echo yes || echo no); want no/yes/yes"
  fi
  rm -rf "$T9"

  # ---- AC13: the twins cannot drift. Compare the extracted ledger call sites, not a count.
  qs="$(grep -n 'ledger_' "$Q" 2>/dev/null | sed 's/^[0-9]*://' | sed 's/^[[:space:]]*//')"
  cs="$(grep -n 'ledger_' "$C" 2>/dev/null | sed 's/^[0-9]*://' | sed 's/^[[:space:]]*//')"
  if [ -n "$qs" ] && [ "$qs" = "$cs" ]; then ok "ac13:twins-identical"
  else no "ac13:twins-identical — ralph-qwen.sh and ralph-codex.sh ledger lines differ"; fi
fi

echo
if [ "$fail" = 0 ]; then echo "VERIFY: ok"; else echo "VERIFY: FAILED" >&2; fi
exit "$fail"
