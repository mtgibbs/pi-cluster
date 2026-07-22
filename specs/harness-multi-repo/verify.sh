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

# --- T1: optional flag, order-independent (AC5) ---
if has "--repo"; then
  ok "--repo flag present"
  # Order-independence means the flag is consumed in a loop/case over "$@", not read
  # positionally. A positional read would satisfy a naive grep but fail AC5.
  grep -qE 'while .*\$#|for .* in "\$@"|case "\$1" in' "$F" \
    && ok "flag is parsed by scanning arguments (AC5)" \
    || no "--repo looks positional — flag order must not matter (AC5)"
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
