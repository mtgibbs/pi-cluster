#!/usr/bin/env bash
# verify.sh — deterministic acceptance gate for specs/scored-gate.
# §10 acceptance criteria + §8 safeguards compiled to runnable assertions: exit 0 = acceptable.
#
# PRESENCE-GATED, PER FEATURE (the ralph contract): runs after EVERY task and must pass, so a
# check for a not-yet-built feature is PEND, never FAIL. CRITICAL LESSON (2026-07-27, the first
# dogfood of this very spec): each block below keys its PEND on ITS OWN task's observable output —
# T1 on the `passed=` line, T2 on the `FAIL:`/`TODO:` lines, T3 on the guard markers. An earlier
# version keyed everything on "does any count line exist", so the moment T1 printed a partial
# score line the gate demanded T2+T3 work and T1 could never pass. A presence-gated check MUST key
# on its own task's output — see the identical warning in specs/harness-multi-repo/verify.sh.
#
# STATIC + SELF-CONTAINED: synthesizes throwaway fixture gates in a mktemp dir and runs the real
# scripts/gate-score.sh against them. No network, no cluster, no repo mutation.
#
# Run from repo root:  ./specs/scored-gate/verify.sh
set -uo pipefail
GS="${GS:-scripts/gate-score.sh}"
fail=0
ok(){   echo "  PASS  $1"; }
no(){   echo "  FAIL  $1" >&2; fail=1; }
pend(){
  if [ "${STRICT:-0}" = 1 ]; then no "$1 — still unbuilt at the final check (STRICT)"; else
    echo "  pend  $1 (not built yet)"; fi
}

echo "VERIFY specs/scored-gate  ($GS)"

if [ ! -f "$GS" ]; then
  pend "T1 core: scripts/gate-score.sh + score line"
  pend "T2: itemized FAIL:/TODO: lines"
  pend "T3: empty-gate + arg guards"
  echo
  [ "$fail" = 0 ] && echo "VERIFY: PASS" || echo "VERIFY: FAIL"
  exit "$fail"
fi

# ---- gate-score.sh exists ----
bash -n "$GS" 2>/dev/null && ok "gate-score.sh parses" || no "gate-score.sh has a syntax error"

# Safeguard 4 (§8): read-only. The tool must never mutate the tree.
grep -qE 'git (add|commit|checkout|clean|reset|rm|stash)\b' "$GS" \
  && no "gate-score.sh contains a tree-mutating git command (Safeguard 4: must be read-only)" \
  || ok "no tree-mutating git commands (Safeguard 4)"

# Scope (§5): this spec touches scripts/gate-score.sh only. Out-of-scope files (test fixtures,
# scratch scripts) fail fast with a clean message rather than silently riding along.
outside="$(git status --porcelain 2>/dev/null | awk '{print $2}' | grep -vE '^(scripts/gate-score\.sh|specs/scored-gate/)' || true)"
if [ -n "$outside" ]; then
  no "changes outside scripts/gate-score.sh: $(echo "$outside" | tr '\n' ' ')(§5 — build fixtures in \$TMPDIR, not the tree)"
else
  ok "change stayed in scripts/gate-score.sh (§5 scope)"
fi

# ---- fixtures (synthesized; cover every spelling the fleet emits) ----
FX="$(mktemp -d "${TMPDIR:-/tmp}/scored-gate.XXXXXX")"
trap 'rm -rf "$FX"' EXIT

# mixed: PASS, the `ok` 3-space lowercase outlier, FAIL on STDERR, pend, PEND, AND a PASS whose
# body contains "fail" (the AC7 substring trap). Expected: p=3 f=1 d=2 t=6 score=0.500 exit 1.
cat > "$FX/mixed.sh" <<'FIX'
#!/usr/bin/env bash
echo "VERIFY fixture header (must be ignored)"
echo "  PASS  alpha is fine"
echo "  ok   bravo lowercase three-space outlier"
echo "  PASS  invalid repo exits non-zero (message says fail but this is a PASS)"
echo "  FAIL  charlie is broken" >&2
echo "  pend  echo not built yet"
echo "  PEND  foxtrot uppercase pend"
echo "  No changes detected — informational, NOT a check"
echo "VERIFY: FAIL"
FIX

# allpass: nothing failing, nothing pending -> converged, exit 0.
cat > "$FX/allpass.sh" <<'FIX'
#!/usr/bin/env bash
echo "  PASS  one"
echo "  PASS  two"
echo "VERIFY: PASS"
FIX

# empty: no parseable checks at all -> must be a loud error, never score 1.000.
cat > "$FX/empty.sh" <<'FIX'
#!/usr/bin/env bash
echo "VERIFY nothing to see here"
FIX

field(){ printf '%s\n' "$1" | sed -n "s/.*${2}=\\([^ ]*\\).*/\\1/p" | head -1; }

m_out="$(bash "$GS" "$FX/mixed.sh" 2>&1)"; m_rc=$?
a_out="$(bash "$GS" "$FX/allpass.sh" 2>&1)"; a_rc=$?
e_out="$(bash "$GS" "$FX/empty.sh" 2>&1)"; e_rc=$?
g_out="$(bash "$GS" /no/such/file/here 2>&1)"; g_rc=$?

# =====================================================================================
# T1 — the core score line. Keyed on the `passed=` marker: absent => T1 unbuilt => PEND.
# =====================================================================================
if printf '%s' "$m_out" | grep -q 'passed='; then
  mp=$(field "$m_out" passed); mf=$(field "$m_out" failed); md=$(field "$m_out" pending)
  mt=$(field "$m_out" total);  ms=$(field "$m_out" score)
  mnf=$(field "$m_out" no_fail); mcv=$(field "$m_out" converged)
  [ "$mp" = 3 ] && ok "AC1/AC2/AC7: passed=3 (PASS + 3-space 'ok' + fail-in-body PASS all counted)" \
    || no "AC1/AC2/AC7: passed=$mp, expected 3 — count the 3-space 'ok' and the 'fail'-in-body PASS"
  [ "$mf" = 1 ] && ok "AC3: failed=1 (FAIL captured from STDERR)" \
    || no "AC3: failed=$mf, expected 1 — FAIL is on stderr; capture 2>&1 (and don't count 'No changes')"
  [ "$md" = 2 ] && ok "AC2: pending=2 (lowercase 'pend' + uppercase 'PEND')" \
    || no "AC2: pending=$md, expected 2 — both 'pend' and 'PEND' must count"
  [ "$mt" = 6 ] && ok "AC1: total=6" || no "AC1: total=$mt, expected 6"
  [ "$ms" = "0.500" ] && ok "AC1: score=0.500 (3/6 at three decimals)" \
    || no "AC1: score=$ms, expected 0.500 (printf '%.3f' of passed/total)"
  [ "$mnf" = 0 ] && ok "AC4: no_fail=0 with a failing check" || no "AC4: no_fail=$mnf, expected 0"
  [ "$mcv" = 0 ] && ok "AC4: converged=0 with work outstanding" || no "AC4: converged=$mcv, expected 0"
  [ "$m_rc" = 1 ] && ok "AC4: exit 1 when not converged" || no "AC4: exit was $m_rc, expected 1"
  # all-pass fixture -> the converged path
  anf=$(field "$a_out" no_fail); acv=$(field "$a_out" converged); as=$(field "$a_out" score)
  [ "$anf" = 1 ] && [ "$acv" = 1 ] && [ "$a_rc" = 0 ] && [ "$as" = "1.000" ] \
    && ok "AC4: all-pass -> no_fail=1 converged=1 score=1.000 exit 0" \
    || no "AC4: all-pass gave no_fail=$anf converged=$acv score=$as exit=$a_rc (want 1/1/1.000/0)"
  # AC7 guard as its own line
  [ "$mf" = 1 ] && ok "AC7: a PASS whose body says 'fail' did not inflate failed" \
    || no "AC7: substring leak — failed=$mf should be 1"
else
  pend "T1 core: passed=/failed=/pending=/total=/score= line + no_fail/converged + exit codes"
fi

# =====================================================================================
# T2 — itemized remaining work. Keyed on a `FAIL:`/`TODO:` line at column 0 (the scorer's
# emission, NOT the fixture's own indented "  FAIL  " passthrough).
# =====================================================================================
if printf '%s\n' "$m_out" | grep -qE '^(FAIL|TODO): '; then
  printf '%s\n' "$m_out" | grep -qE '^FAIL: .*charlie' \
    && ok "AC5: FAIL: line carries the failing check's message" \
    || no "AC5: no 'FAIL: ...charlie...' line — the failing message must be itemized"
  printf '%s\n' "$m_out" | grep -qE '^TODO: .*(echo|foxtrot)' \
    && ok "AC5: TODO: line carries a pending check's message" \
    || no "AC5: no 'TODO: ...' line — pending checks must be itemized as TODO"
else
  pend "T2: FAIL:/TODO: itemized lines"
fi

# =====================================================================================
# T3 — hardening. Empty-gate guard keyed on the 'no-checks-parsed' marker; arg guard on exit 2.
# =====================================================================================
if printf '%s' "$e_out" | grep -q 'no-checks-parsed'; then
  es=$(field "$e_out" score)
  [ "$e_rc" = 2 ] && ok "AC6: empty gate exits 2" || no "AC6: empty gate exit was $e_rc, expected 2"
  [ "$es" = "0.000" ] && ok "AC6/Safeguard1: empty gate score=0.000" \
    || no "AC6/Safeguard1: empty gate printed score='$es' — must be exactly score=0.000 (never blank, never 1.000)"
else
  pend "T3: empty-gate guard (error=no-checks-parsed, score 0.000, exit 2)"
fi

if [ "$g_rc" = 2 ]; then
  ok "T3/AC8-arg: unreadable gate path exits 2 with a usage error"
else
  pend "T3: argument guard (missing/unreadable path -> exit 2)"
fi

echo
[ "$fail" = 0 ] && echo "VERIFY: PASS" || echo "VERIFY: FAIL"
exit "$fail"
