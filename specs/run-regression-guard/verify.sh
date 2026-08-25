#!/usr/bin/env bash
# verify.sh — deterministic acceptance gate for specs/run-regression-guard.
# Run from repo root:  ./specs/run-regression-guard/verify.sh   (STRICT=1 for the final pass)
#
# HERMETIC: every integration check runs a REAL ralph loop in a throwaway git repo under $TMPDIR
# with a mock `oc` first on PATH, RALPH_STATUS_DIR / RALPH_LOG_DIR / RETRY_STATE_DIR redirected
# into that temp dir and RALPH_BUS=off. It never touches the operator's ~/.harness corpus.
#
# CREATE EVERY DIRECTORY THE LOOP IS POINTED AT. specs/ralph-retry-contract's gate failed a
# CORRECT implementation for three attempts because run_loop set RETRY_STATE_DIR to a directory
# it never made, so the helper degraded to silence exactly as its own AC demanded. A gate that
# models a degraded mode must not accidentally create that mode in its own fixtures.
#
# THREE-VERDICT: T1's deliverables are new FUNCTIONS in an existing file, so T1 pends on those
# functions existing. T2/T3 edit existing files with no new artifact, so each pends on its own
# literal edit and only then asserts behaviour — the grep arms the check, it never is the check.
set -uo pipefail

Q="scripts/ralph-qwen.sh"
H="scripts/ralph-retry.sh"
FIX="specs/run-regression-guard/fixtures"
ROOT_ABS="$(pwd)"
fail=0
ok(){   echo "  PASS  $1"; }
no(){   echo "  FAIL  $1" >&2; fail=1; }
pend(){ if [ "${STRICT:-0}" = 1 ]; then no "$1 — still unbuilt at the final check (STRICT)"
        else echo "  pend  $1 (not built yet)"; fi; }

# The defect under test is bash-3.2-specific, so exercise it on the real /bin/bash, not on
# whatever `bash` resolves to on PATH (Homebrew ships bash 5, where the bug does not reproduce).
B32=/bin/bash
[ -x "$B32" ] || B32=bash

# ------------------------------------------------------------- scope / litter (FIRST, FATAL)
stray="$(find specs/run-regression-guard -type f \
  ! -name spec.md ! -name tasks.txt ! -name verify.sh \
  ! -path 'specs/run-regression-guard/fixtures/*' \
  ! -path 'specs/run-regression-guard/evidence/*' 2>/dev/null)"
[ -z "$stray" ] && ok "scope:no-litter-in-spec-dir" \
  || { no "scope:no-litter-in-spec-dir"; echo "$stray" | sed 's/^/          /' >&2; }

BASE="${RRG_BASE:-origin/main}"
if git rev-parse --verify --quiet "$BASE" >/dev/null 2>&1; then
  git diff --quiet "$BASE" -- specs/TEMPLATE.md scripts/gate-score.sh scripts/loop-report.sh \
      scripts/run-loop.sh scripts/loops scripts/ralph-judge.sh scripts/ralph-status.sh \
      scripts/ralph-log.sh scripts/ralph-bus.sh specs/loop-doctor 2>/dev/null \
    && ok "scope:out-of-scope-files-untouched" \
    || no "scope:out-of-scope-files-untouched — spec §5 forbids editing these"
else
  pend "scope:out-of-scope-files-untouched (base '$BASE' unresolvable)"
fi

# §5 — the final STRICT backstop must survive untouched in the build loop.
for f in "$Q"; do
  n="$(basename "$f")"
  grep -q 'STRICT=1 bash "\$VERIFY"' "$f" 2>/dev/null \
    && ok "scope:$n-strict-backstop-intact" || no "scope:$n-strict-backstop-intact"
done

# ------------------------------------------------------------------------- shared test harness
# run_loop <scenario> <retries> -> echoes the temp dir
run_loop() {
  local scen="$1" retries="${2:-1}" T
  T="$(mktemp -d -t rrg.XXXXXX)"
  mkdir -p "$T/bin" "$T/mock" "$T/repo" "$T/retry" "$T/status" "$T/logs"   # ALL of them (see header)
  cp "$FIX/mock-oc" "$T/bin/oc"; chmod +x "$T/bin/oc"
  cp -R "$FIX/mock-exec/$scen" "$T/mock/scenario"
  ( cd "$T/repo" && git init -q . && git config user.email t@t && git config user.name t
    cp -R "$ROOT_ABS/$FIX/inner-spec" spec
    printf 'opencode.json\n' > .gitignore
    printf '{}\n' > opencode.json
    git add -A && git commit -qm base ) >/dev/null 2>&1
  ( cd "$T/repo" && PATH="$T/bin:$PATH" MOCK_DIR="$T/mock" \
      RALPH_STATUS_DIR="$T/status" RALPH_LOG_DIR="$T/logs" RALPH_BUS=off RALPH_SHEET=off \
      RETRY_STATE_DIR="$T/retry" RALPH_RETRIES="$retries" OC_RUN_TIMEOUT=30 \
      bash "$ROOT_ABS/$Q" spec ) > "$T/loop.log" 2>&1
  echo "$T"
}

# ---------------------------------------------------- AC10 (hard — the happy path is sacred)
# Always live: it must pass BEFORE the fix too, which is what proves the harness drives the loop.
T10="$(run_loop clean-two-task 1)"
c10="$(git -C "$T10/repo" log --oneline | wc -l | tr -d ' ')"
[ "$c10" = "3" ] && ok "ac10:clean-run-commits-both-tasks" \
  || no "ac10:clean-run-commits-both-tasks — $c10 commits, want 3 (base + T1 + T2)"
git -C "$T10/repo" log -1 --pretty=%s | grep -q '^ralph(' \
  && ok "ac10:clean-run-commit-prefix" || no "ac10:clean-run-commit-prefix"
[ -f "$T10/repo/a.txt" ] && [ -f "$T10/repo/b.txt" ] \
  && ok "ac10:clean-run-both-artifacts" || no "ac10:clean-run-both-artifacts"
rm -rf "$T10"

# --------------------------------------------------------------------------------- T1 (pend)
if grep -q 'retry_run_regressions' "$H" 2>/dev/null; then
  "$B32" -n "$H" 2>/dev/null && ok "ac1:helper-bash-n-clean" || no "ac1:helper-bash-n-clean"
  ( set +u; . "$H" 2>/dev/null
    for fn in retry_run_init retry_run_record retry_run_regressions; do
      type "$fn" >/dev/null 2>&1 || exit 1; done ) \
    && ok "ac1:three-run-scoped-functions" || no "ac1:three-run-scoped-functions"

  RS="$(mktemp -d)"
  # AC2 — the bash 3.2 empty-array defect. STDERR must be EMPTY, not merely stdout: the broken
  # version emits correct stdout and an "unbound variable" on stderr, so a stdout-only
  # assertion passes against it. This check is the whole reason B32 is /bin/bash.
  cat > "$RS/t-ac2.sh" <<EOS
set -uo pipefail
. "$ROOT_ABS/$H"
RETRY_STATE_DIR="$RS"; export RETRY_STATE_DIR
retry_init; retry_record "  PASS  alpha"
retry_regressions "  FAIL  beta" >/dev/null
echo "rc=\$?"
EOS
  a2e="$("$B32" "$RS/t-ac2.sh" 2>&1 >/dev/null)"
  a2r="$("$B32" "$RS/t-ac2.sh" 2>/dev/null | tail -1)"
  [ -z "$a2e" ] && ok "ac2:no-regressions-silent-on-stderr" \
    || no "ac2:no-regressions-silent-on-stderr — got '$a2e'"
  [ "$a2r" = "rc=0" ] && ok "ac2:no-regressions-returns-0" || no "ac2:no-regressions-returns-0 — $a2r"

  # AC3 — a PEND counts as a regression, not only a FAIL. This is the qwen-10668 signature.
  cat > "$RS/t-ac3.sh" <<EOS
set -uo pipefail
. "$ROOT_ABS/$H"
RETRY_STATE_DIR="$RS"; export RETRY_STATE_DIR
retry_run_init
retry_run_record "\$(cat "$ROOT_ABS/$FIX/gate-t1.txt")" T1
retry_run_regressions "\$(cat "$ROOT_ABS/$FIX/gate-t2-destroyed.txt")"
EOS
  a3="$("$B32" "$RS/t-ac3.sh" 2>/dev/null)"
  printf '%s\n' "$a3" | grep -q '^alpha' && ok "ac3:pend-counts-as-regression" \
    || no "ac3:pend-counts-as-regression — got '$a3'"
  printf '%s\n' "$a3" | grep -q 'T1' && ok "ac3:names-the-task-that-held-it-green" \
    || no "ac3:names-the-task-that-held-it-green"

  # AC4 — a check that never passed is not a regression.
  cat > "$RS/t-ac4.sh" <<EOS
set -uo pipefail
. "$ROOT_ABS/$H"
RETRY_STATE_DIR="$RS"; export RETRY_STATE_DIR
retry_run_init
retry_run_record "\$(cat "$ROOT_ABS/$FIX/gate-t1.txt")" T1
retry_run_regressions "  FAIL  gamma"
EOS
  [ -z "$("$B32" "$RS/t-ac4.sh" 2>/dev/null)" ] && ok "ac4:never-passed-is-not-a-regression" \
    || no "ac4:never-passed-is-not-a-regression"

  # AC5 — the two scopes must not clear each other.
  cat > "$RS/t-ac5.sh" <<EOS
set -uo pipefail
. "$ROOT_ABS/$H"
RETRY_STATE_DIR="$RS"; export RETRY_STATE_DIR
retry_run_init
retry_run_record "\$(cat "$ROOT_ABS/$FIX/gate-t1.txt")" T1
retry_init                                    # a NEW TASK starts — must not wipe run scope
retry_run_regressions "\$(cat "$ROOT_ABS/$FIX/gate-t2-destroyed.txt")"
EOS
  "$B32" "$RS/t-ac5.sh" 2>/dev/null | grep -q '^alpha' \
    && ok "ac5:retry_init-does-not-clear-run-scope" || no "ac5:retry_init-does-not-clear-run-scope"

  # AC6 — unwritable state dir: silent, rc 0, nothing on stderr.
  cat > "$RS/t-ac6.sh" <<EOS
set -uo pipefail
. "$ROOT_ABS/$H"
RETRY_STATE_DIR=/nonexistent/nope; export RETRY_STATE_DIR
retry_run_init; retry_run_record "  PASS  alpha" T1; retry_run_regressions "  FAIL  alpha"
echo "rc=\$?"
EOS
  a6e="$("$B32" "$RS/t-ac6.sh" 2>&1 >/dev/null)"
  a6o="$("$B32" "$RS/t-ac6.sh" 2>/dev/null)"
  [ -z "$a6e" ] && ok "ac6:unwritable-silent-on-stderr" || no "ac6:unwritable-silent-on-stderr"
  [ "$a6o" = "rc=0" ] && ok "ac6:unwritable-returns-0-no-output" \
    || no "ac6:unwritable-returns-0-no-output — got '$a6o'"
  rm -rf "$RS"
else
  pend "ac1:helper-bash-n-clean"; pend "ac1:three-run-scoped-functions"
  pend "ac2:no-regressions-silent-on-stderr"; pend "ac2:no-regressions-returns-0"
  pend "ac3:pend-counts-as-regression"; pend "ac3:names-the-task-that-held-it-green"
  pend "ac4:never-passed-is-not-a-regression"; pend "ac5:retry_init-does-not-clear-run-scope"
  pend "ac6:unwritable-silent-on-stderr"; pend "ac6:unwritable-returns-0-no-output"
fi

# ----------------------------------------------------------------------------- T2/T3 (pend)
if grep -q 'retry_run_regressions' "$Q" 2>/dev/null; then
  T7="$(run_loop destroy-earlier 1)"
  # AC7 — the destroying task must NOT be committed. base + T1 only.
  c7="$(git -C "$T7/repo" log --oneline | wc -l | tr -d ' ')"
  [ "$c7" = "2" ] && ok "ac7:destroying-task-not-committed" \
    || no "ac7:destroying-task-not-committed — $c7 commits, want 2 (base + T1)"
  # AC8 — the next attempt's prompt names the check AND the task that last held it green.
  P="$T7/mock/prompts.txt"
  third="$(awk '/===END-PROMPT-2===/{f=1;next} f' "$P" 2>/dev/null)"
  printf '%s' "$third" | grep -q 'CROSS-TASK REGRESSION' \
    && ok "ac8:regression-heading-in-next-prompt" || no "ac8:regression-heading-in-next-prompt"
  blk="$(printf '%s' "$third" | awk '/CROSS-TASK REGRESSION/{f=1;next} /Do not delete or disable/{f=0} f')"
  printf '%s' "$blk" | grep -q 'alpha' && ok "ac8:names-regressed-check" || no "ac8:names-regressed-check"
  printf '%s' "$blk" | grep -q 'T1' && ok "ac8:names-owning-task" || no "ac8:names-owning-task"
  # AC9 — STOP names the DESTROYING task, and the run exits non-zero.
  # The task label must be ON the STOP line itself, not merely somewhere in the log: every task
  # banner already echoes "T2", so a whole-log grep passes against the UNFIXED loop. Caught
  # 2026-08-18 by running this gate against known-bad code — the third time this exact
  # false-positive class has appeared (loop-doctor ac15; retry-contract ac9). Scope the grep.
  stopline="$(grep 'CROSS-TASK REGRESSION' "$T7/loop.log" | head -1)"
  [ -n "$stopline" ] && ok "ac9:stop-message-names-the-cause" || no "ac9:stop-message-names-the-cause"
  printf '%s' "$stopline" | grep -q 'T2' \
    && ok "ac9:stop-line-names-destroying-task" || no "ac9:stop-line-names-destroying-task"
  # The evidence must survive the reset, same as an ordinary failure.
  ls "$T7"/logs/*/T2-attempt*.diff >/dev/null 2>&1 \
    && ok "ac9:evidence-preserved" || no "ac9:evidence-preserved"
  rm -rf "$T7"

  # AC11 (twin symmetry) removed by specs/executor-binding: the codex builder it compared
  # against is deleted — one build loop, executor is a binding. Behaviour checks above are intact.
else
  pend "ac7:destroying-task-not-committed"; pend "ac8:regression-heading-in-next-prompt"
  pend "ac8:names-regressed-check"; pend "ac8:names-owning-task"
  pend "ac9:stop-message-names-the-cause"; pend "ac9:stop-line-names-destroying-task"
  pend "ac9:evidence-preserved"
fi

exit "$fail"
