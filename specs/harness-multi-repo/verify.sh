#!/usr/bin/env bash
# verify.sh — deterministic acceptance gate for specs/harness-multi-repo.
# §10 acceptance criteria + §8 safeguards compiled to runnable assertions: exit 0 = acceptable.
#
# PRESENCE-GATED (the ralph contract): runs after EVERY task and must pass, so a check for a
# not-yet-written identifier is PEND, never FAIL.
#
# STATIC tier only. It does NOT ssh, does not touch the Beelink, and cannot prove the companion
# beelink-ansible change is deployed — that ordering is spec §6 and is a human's call before
# merge. What this CAN prove, and the thing most worth proving, is Safeguard 1: with no --repo
# flag the emitted command is byte-identical to today's.
#
# Run from repo root:  ./specs/harness-multi-repo/verify.sh
set -uo pipefail
F="${F:-scripts/harness}"
fail=0
ok(){   echo "  PASS  $1"; }
no(){   echo "  FAIL  $1" >&2; fail=1; }
pend(){ echo "  pend  $1 (not built yet)"; }
has(){  grep -q -- "$1" "$F" 2>/dev/null; }

echo "VERIFY specs/harness-multi-repo  ($F)"
[ -f "$F" ] || { echo "  FAIL  $F missing" >&2; exit 1; }
bash -n "$F" 2>/dev/null && ok "harness parses" || no "harness has a syntax error"

# --- T1/AC5: EXECUTE the flag helpers. Extract BY NAME, never by position. ---
# The previous version of this check sliced from `run)` to the first `target=` line. An executor
# then put its parsing AFTER `target=`, the slice came back empty, the check PENDed, and a
# parser that never set `repo` at all was reported as passing. Two lessons, both encoded here:
#   1. Extract by function NAME so placement cannot silently disable the check.
#   2. FAIL CLOSED. Once --repo appears in the file, a missing helper is a failure, not a pend —
#      "I could not test this" must never read the same as "this is fine".
if has "--repo"; then
  ok "--repo handled"
  for fn in harness_repo_flag harness_strip_repo; do
    grep -qE "^[[:space:]]*$fn\\(\\)" "$F" || no "AC5: $fn() missing — see the WORKED EXAMPLE in spec §6"
  done
  if grep -qE '^[[:space:]]*harness_repo_flag\(\)' "$F" && grep -qE '^[[:space:]]*harness_strip_repo\(\)' "$F"; then
    # Lift both helpers out by brace matching and run them standalone.
    probe="$(mktemp -t hflag)"
    awk '/^[[:space:]]*harness_repo_flag\(\)/,/^[[:space:]]*}/' "$F"  >  "$probe"
    awk '/^[[:space:]]*harness_strip_repo\(\)/,/^[[:space:]]*}/' "$F" >> "$probe"
    printf 'case "$1" in flag) shift; harness_repo_flag "$@";; strip) shift; harness_strip_repo "$@";; esac\n' >> "$probe"

    r0="$(bash "$probe" flag qwen specs/foo 2>/dev/null)"
    r1="$(bash "$probe" flag --repo beelink-ansible qwen specs/foo 2>/dev/null)"
    r2="$(bash "$probe" flag qwen specs/foo --repo beelink-ansible 2>/dev/null)"
    r3="$(bash "$probe" flag qwen specs/foo --repo=beelink-ansible 2>/dev/null)"
    st="$(bash "$probe" strip qwen specs/foo --repo beelink-ansible 2>/dev/null | tr '\n' ' ')"
    rm -f "$probe"

    [ -z "$r0" ] && ok "AC1: no flag yields no repo" || no "AC1: repo set to '$r0' with no flag present"
    [ "$r1" = beelink-ansible ] && ok "AC5: --repo works LEADING"  || no "AC5: leading --repo gave '$r1'"
    [ "$r2" = beelink-ansible ] && ok "AC5: --repo works APPENDED" || no "AC5: appended --repo gave '$r2' (a parser that stops at the first non-flag argument is leading-only)"
    [ "$r3" = beelink-ansible ] && ok "AC5: --repo=value form works" || no "AC5: --repo=value gave '$r3'"
    [ "$st" = "qwen specs/foo " ] && ok "AC2: stripping leaves the positionals intact" \
      || no "AC2: stripped args were '$st', expected 'qwen specs/foo '"
  fi
else pend "--repo flag"; fi

# --- T2: validation before any remote call (AC3, Safeguard 2) ---
if grep -qE 'A-Za-z0-9._-|A-Za-z0-9\._\-' "$F"; then
  ok "bare-name character class present (Safeguard 2)"
  grep -qE 'exit 1' "$F" && ok "invalid repo exits non-zero (AC3)" || no "no non-zero exit on invalid repo (AC3)"
else pend "repo validation"; fi

# The value is interpolated into a remote command. Rejecting is correct; escaping is not.
if has "--repo"; then
  grep -qE "repo.*(printf %q|sed 's/'|shell-?quote)" "$F" \
    && no "repo value appears to be escaped rather than rejected (Safeguard 2)" \
    || ok "repo is rejected, not escaped (Safeguard 2)"
fi

# --- T3 / Safeguard 1: the no-flag path must not drift ---
# Today's exact command shapes. These two strings are the compatibility contract; if a task
# rewrites them the default behaviour has changed and Safeguard 1 is broken.
if grep -q 'run-task.sh \$spec pi-cluster \$branch \$base_branch' "$F"; then
  ok "default workstation command preserved (AC1, Safeguard 1)"
else
  if has "--repo"; then
    no "default workstation command changed — no-flag runs must be byte-identical (AC1)"
  else
    pend "default workstation command"
  fi
fi
if grep -q 'run-task.sh \$spec \$branch \$base_branch' "$F"; then
  ok "default qwen command preserved (AC1, Safeguard 1)"
else
  if has "--repo"; then
    no "default qwen command changed — no-flag runs must be byte-identical (AC1)"
  else
    pend "default qwen command"
  fi
fi

# --- AC2: when supplied, repo goes to position 2 for EVERY agent (qwen included) ---
if has "--repo"; then
  # AC2: the flag is APPENDED. A positional form would shift qwen's args — see spec §6.
  grep -qE -- '--repo \$repo"?$|--repo \$repo ' "$F" \
    && ok "--repo appended, positionals unshifted (AC2)" \
    || no "repo is not appended as a --repo flag (AC2)"
  grep -qE 'run-task\.sh \$spec \$repo \$branch' "$F" \
    && no "repo passed positionally — this shifts qwen's branch argument (AC2, spec §6)" \
    || ok "no positional repo form (AC2)"
fi

# --- AC4: the operator can see which repo was targeted ---
if has "--repo"; then
  grep -qE 'echo "harness: sent.*repo|repo.*harness: sent' "$F" \
    && ok "run echoes the target repo (AC4)" \
    || no "the 'harness: sent' line does not name the repo (AC4)"
fi

# --- Safeguard 3: no credential ever appears in this file ---
grep -qiE 'x-access-token|ghp_|github_pat_|HARNESS_GITHUB_PAT *=' "$F" \
  && no "a credential or token literal appears in $F (Safeguard 3)" \
  || ok "no credential literals (Safeguard 3)"

# --- Scope: this spec touches scripts/harness only (§5) ---
outside="$(git status --porcelain 2>/dev/null | awk '{print $2}' | grep -vE '^(scripts/harness|specs/harness-multi-repo/)' || true)"
if [ -n "$outside" ]; then
  no "changes outside scripts/harness: $(echo "$outside" | tr '\n' ' ')(§5)"
else
  ok "change stayed in scripts/harness (§5)"
fi

echo
[ "$fail" = 0 ] && echo "VERIFY: PASS" || echo "VERIFY: FAIL"
exit "$fail"
