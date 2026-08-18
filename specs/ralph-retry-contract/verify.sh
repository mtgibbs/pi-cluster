#!/usr/bin/env bash
# verify.sh — deterministic acceptance gate for specs/ralph-retry-contract.
# Run from repo root:  ./specs/ralph-retry-contract/verify.sh   (STRICT=1 for the final pass)
#
# HERMETIC: every integration check runs a REAL ralph loop inside a throwaway git repo under
# $TMPDIR, driven by a mock `oc` placed first on PATH, with RALPH_STATUS_DIR / RALPH_LOG_DIR
# redirected into that temp dir and RALPH_BUS=off. It never touches the operator's ~/.harness
# corpus (which specs/loop-doctor reads) and never reaches the network.
#
# Why a real run: AC7/AC9/AC13 are about what the loop RESETS, SAYS, and COMMITS. Grepping the
# script for the fix would test for the fix, not the behaviour (spec §2.6). Precedent:
# specs/judge-loop/verify.sh drives the real ralph-judge.sh against mock commands.
#
# THREE-VERDICT: T1's deliverable is a new file, so its checks pend on that file. T2-T4 edit
# EXISTING files, which have no new artifact to arm on — so each pends on its own literal edit
# being present, and only then asserts the BEHAVIOUR that edit is supposed to produce. The
# presence-gate is the arming condition; the behavioural assertion is the real check.
set -uo pipefail

Q="scripts/ralph-qwen.sh"
C="scripts/ralph-codex.sh"
H="scripts/ralph-retry.sh"
FIX="specs/ralph-retry-contract/fixtures"
ROOT_ABS="$(pwd)"          # $OLDPWD is unreliable inside the nested subshells below
fail=0
ok(){   echo "  PASS  $1"; }
no(){   echo "  FAIL  $1" >&2; fail=1; }
pend(){ if [ "${STRICT:-0}" = 1 ]; then no "$1 — still unbuilt at the final check (STRICT)"
        else echo "  pend  $1 (not built yet)"; fi; }

# ------------------------------------------------------------- scope / litter (FIRST, FATAL)
stray="$(find specs/ralph-retry-contract -type f \
  ! -name spec.md ! -name tasks.txt ! -name verify.sh \
  ! -path 'specs/ralph-retry-contract/fixtures/*' \
  ! -path 'specs/ralph-retry-contract/evidence/*' 2>/dev/null)"
[ -z "$stray" ] && ok "scope:no-litter-in-spec-dir" \
  || { no "scope:no-litter-in-spec-dir"; echo "$stray" | sed 's/^/          /' >&2; }

BASE="${RETRY_BASE:-origin/main}"
if git rev-parse --verify --quiet "$BASE" >/dev/null 2>&1; then
  git diff --quiet "$BASE" -- scripts/ralph-judge.sh scripts/ralph-status.sh scripts/ralph-log.sh \
      scripts/ralph-bus.sh scripts/gate-score.sh scripts/loop-report.sh scripts/run-loop.sh \
      scripts/loops specs/TEMPLATE.md specs/loop-doctor 2>/dev/null \
    && ok "scope:out-of-scope-files-untouched" \
    || no "scope:out-of-scope-files-untouched — spec §5 forbids editing these"
else
  pend "scope:out-of-scope-files-untouched (base '$BASE' unresolvable)"
fi

# AC10 — the reset must never gain teeth it should not have (§8.1).
for f in "$Q" "$C"; do
  n="$(basename "$f")"
  if [ -f "$f" ]; then
    grep -Eq 'reset --hard|clean -fdx|clean .*-x' "$f" \
      && no "ac10:$n-no-dangerous-git" || ok "ac10:$n-no-dangerous-git"
  else
    no "ac10:$n-no-dangerous-git (missing $f)"
  fi
done

# ------------------------------------------------------------------------- shared test harness
# run_loop <scenario> <retries> -> echoes the temp dir; loop's stdout/stderr in $T/loop.log
run_loop() {
  local scen="$1" retries="${2:-2}" T
  T="$(mktemp -d -t rrc.XXXXXX)"
  mkdir -p "$T/bin" "$T/mock" "$T/repo" "$T/retry"
  cp "$FIX/mock-oc" "$T/bin/oc"; chmod +x "$T/bin/oc"
  cp -R "$FIX/mock-exec/$scen" "$T/mock/scenario"
  ( cd "$T/repo" && git init -q . && git config user.email t@t && git config user.name t
    cp -R "$ROOT_ABS/$FIX/inner-spec" spec
    printf 'opencode.json\n' > .gitignore
    printf '{}\n' > opencode.json          # gitignored, MUST survive the reset (AC8)
    git add -A && git commit -qm base ) >/dev/null 2>&1
  ( cd "$T/repo" && PATH="$T/bin:$PATH" MOCK_DIR="$T/mock" \
      RALPH_STATUS_DIR="$T/status" RALPH_LOG_DIR="$T/logs" RALPH_BUS=off RALPH_SHEET=off \
      RETRY_STATE_DIR="$T/retry" RALPH_RETRIES="$retries" OC_RUN_TIMEOUT=30 \
      bash "$ROOT_ABS/$Q" spec ) > "$T/loop.log" 2>&1
  echo "$T"
}

# ------------------------------------------------------------------- AC13 (hard — no regression)
# The happy path must be identical before and after this spec lands. Always live.
T13="$(run_loop pass-first-try 2)"
c13="$(git -C "$T13/repo" log --oneline | wc -l | tr -d ' ')"
[ "$c13" = "2" ] && ok "ac13:happy-path-one-commit" || no "ac13:happy-path-one-commit — $c13 commits, want 2"
git -C "$T13/repo" log -1 --pretty=%s | grep -q '^ralph(' \
  && ok "ac13:happy-path-commit-message" || no "ac13:happy-path-commit-message"
[ -f "$T13/repo/opencode.json" ] && ok "ac8:gitignored-file-survives" || no "ac8:gitignored-file-survives"
rm -rf "$T13"

# --------------------------------------------------------------------------------- T1 (pend)
if [ -f "$H" ]; then
  bash -n "$H" 2>/dev/null && ok "ac1:helper-bash-n-clean" || no "ac1:helper-bash-n-clean"
  grep -q 'declare -A' "$H" && no "ac1:helper-bash32" || ok "ac1:helper-bash32"
  ( set +u; . "$H" 2>/dev/null
    for fn in retry_init retry_record retry_regressions; do
      type "$fn" >/dev/null 2>&1 || exit 1; done ) \
    && ok "ac1:helper-defines-three-functions" || no "ac1:helper-defines-three-functions"

  RS="$(mktemp -d)"
  hres="$( set +u; RETRY_STATE_DIR="$RS"; export RETRY_STATE_DIR; . "$H" 2>/dev/null
    retry_init
    retry_record "$(cat "$FIX/gate-attempt1.txt")"
    retry_regressions "$(cat "$FIX/gate-attempt2.txt")" )"
  # AC2 — alpha passed in attempt 1 and fails in attempt 2: a regression.
  printf '%s\n' "$hres" | grep -qx 'alpha' && ok "ac2:regression-detected" || no "ac2:regression-detected"
  # AC3 — beta failed in attempt 1; failing again is not a regression.
  printf '%s\n' "$hres" | grep -qx 'beta' && no "ac3:prior-failure-is-not-regression" \
    || ok "ac3:prior-failure-is-not-regression"
  # AC4 — leading-token rule: a PASS whose message contains "fail" still counts as passed,
  # and it PENDs in attempt 2, so it must be reported.
  printf '%s\n' "$hres" | grep -qx 'gamma-must-not-fail-the-parser' \
    && ok "ac4:leading-token-rule" || no "ac4:leading-token-rule"
  # AC5 — retry_init clears state between tasks.
  hres2="$( set +u; RETRY_STATE_DIR="$RS"; export RETRY_STATE_DIR; . "$H" 2>/dev/null
    retry_init; retry_record "$(cat "$FIX/gate-attempt1.txt")"
    retry_init
    retry_regressions "$(cat "$FIX/gate-attempt2.txt")" )"
  [ -z "$(printf '%s' "$hres2" | tr -d '[:space:]')" ] \
    && ok "ac5:init-clears-state" || no "ac5:init-clears-state"
  # AC6 — unwritable state dir degrades to silence, never a nonzero exit.
  ( set +u; RETRY_STATE_DIR=/nonexistent/nope; export RETRY_STATE_DIR; . "$H" 2>/dev/null
    retry_init && retry_record "x" && retry_regressions "y" >/dev/null ) \
    && ok "ac6:unwritable-state-is-silent" || no "ac6:unwritable-state-is-silent"
  rm -rf "$RS"
else
  pend "ac1:helper-bash-n-clean"; pend "ac1:helper-bash32"
  pend "ac1:helper-defines-three-functions"; pend "ac2:regression-detected"
  pend "ac3:prior-failure-is-not-regression"; pend "ac4:leading-token-rule"
  pend "ac5:init-clears-state"; pend "ac6:unwritable-state-is-silent"
fi

# --------------------------------------------------------------------------------- T2 (pend)
# Presence-gate: the literal edit exists in BOTH twins. Then assert the behaviour.
if grep -q 'reset -q -- \.' "$Q" 2>/dev/null && grep -q 'reset -q -- \.' "$C" 2>/dev/null; then
  T7="$(run_loop stage-and-fail 1)"
  v="$(cat "$T7/mock/verdict" 2>/dev/null || echo MISSING)"
  [ "$v" = "CLEAN" ] && ok "ac7:staged-file-gone-next-attempt" \
    || no "ac7:staged-file-gone-next-attempt — attempt 2 saw '$v'"
  [ -f "$T7/repo/opencode.json" ] && ok "ac8:gitignored-survives-after-reset" \
    || no "ac8:gitignored-survives-after-reset"
  rm -rf "$T7"
else
  pend "ac7:staged-file-gone-next-attempt"; pend "ac8:gitignored-survives-after-reset"
fi

# --------------------------------------------------------------------------------- T3 (pend)
if grep -q 'section 10 acceptance criteria' "$Q" 2>/dev/null; then
  for f in "$Q" "$C"; do
    n="$(basename "$f")"
    grep -q "section 10 acceptance criteria and section 7 norms" "$f" \
      && ok "ac11:$n-section-pointers" || no "ac11:$n-section-pointers"
    grep -q 'Do not run git add, git commit, or git stash' "$f" \
      && ok "ac11:$n-index-prohibition" || no "ac11:$n-index-prohibition"
    grep -q "section 10 reference and section 7 acceptance criteria" "$f" \
      && no "ac11:$n-old-wording-removed" || ok "ac11:$n-old-wording-removed"
  done
  # AC12 — the twins must not drift: the shared clauses are byte-identical.
  a="$(grep -h 'section 10 acceptance criteria\|Do not run git add\|reset -q -- \.' "$Q" | sed 's/^[[:space:]]*//')"
  b="$(grep -h 'section 10 acceptance criteria\|Do not run git add\|reset -q -- \.' "$C" | sed 's/^[[:space:]]*//')"
  [ -n "$a" ] && [ "$a" = "$b" ] && ok "ac12:twins-do-not-drift" || no "ac12:twins-do-not-drift"
else
  pend "ac11:ralph-qwen.sh-section-pointers"; pend "ac11:ralph-qwen.sh-index-prohibition"
  pend "ac11:ralph-qwen.sh-old-wording-removed"; pend "ac11:ralph-codex.sh-section-pointers"
  pend "ac11:ralph-codex.sh-index-prohibition"; pend "ac11:ralph-codex.sh-old-wording-removed"
  pend "ac12:twins-do-not-drift"
fi

# --------------------------------------------------------------------------------- T4 (pend)
if grep -q 'ralph-retry.sh' "$Q" 2>/dev/null && grep -q 'ralph-retry.sh' "$C" 2>/dev/null; then
  T9="$(run_loop trade-checks 2)"
  P="$T9/mock/prompts.txt"
  # AC9 — attempt 2 regressed `alpha`; attempt 3's prompt must name it under a heading.
  third="$(awk '/===END-PROMPT-2===/{f=1;next} f' "$P" 2>/dev/null)"
  printf '%s' "$third" | grep -q 'REGRESSION' \
    && ok "ac9:regression-heading-in-next-prompt" || no "ac9:regression-heading-in-next-prompt"
  # The name must appear INSIDE the regression block, not merely somewhere in the prompt:
  # the ordinary FAIL feedback already contains "FAIL  alpha", so a whole-prompt grep passes
  # against the UNFIXED loop. Caught 2026-08-18 by running this gate against known-bad code —
  # the same false-positive class as specs/loop-doctor's ac15. Scope to the block.
  block="$(printf '%s' "$third" | awk '/REGRESSION —/{f=1;next} /Do not trade one check/{f=0} f')"
  printf '%s' "$block" | grep -q 'alpha' \
    && ok "ac9:regressed-check-named-inside-block" || no "ac9:regressed-check-named-inside-block"
  # The ordinary FAIL feedback must still be there — the block is additive, not a replacement.
  printf '%s' "$third" | grep -q 'A previous attempt FAILED verification with' \
    && ok "ac9:fail-feedback-preserved" || no "ac9:fail-feedback-preserved"
  # And attempt 2 saw NO regression block: nothing had regressed yet.
  second="$(awk '/===END-PROMPT-1===/{f=1;next} /===END-PROMPT-2===/{f=0} f' "$P" 2>/dev/null)"
  printf '%s' "$second" | grep -q 'REGRESSION' \
    && no "ac9:no-false-regression-on-first-retry" || ok "ac9:no-false-regression-on-first-retry"
  rm -rf "$T9"
else
  pend "ac9:regression-heading-in-next-prompt"; pend "ac9:regressed-check-named-inside-block"
  pend "ac9:fail-feedback-preserved"; pend "ac9:no-false-regression-on-first-retry"
fi

exit "$fail"
