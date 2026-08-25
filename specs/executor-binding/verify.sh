#!/usr/bin/env bash
# specs/executor-binding/verify.sh — acceptance gate for the build-phase executor binding.
# Run from repo root:  bash specs/executor-binding/verify.sh   (STRICT=1 for the final pass)
#
# Three verdicts: PASS · FAIL (exists and is wrong) · pend (not built yet). STRICT=1 promotes.
# Classes: negative (absence, soundly searched) · exec (something ran) · presence (scaffolding).
#
# DELIBERATELY SMALL. This spec's §preamble makes gate bloat the thing being fixed — the harness
# carries 2,572 lines of gate inspecting itself against 1,830 protecting actual work. A 300-line
# gate for a seam would refute the spec it verifies. Behaviour is proven with ONE mock binding
# exercised three ways, not with a fixture per criterion.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 2

PASS=0; FAIL=0; PEND=0; N_NEG=0; N_EXEC=0; N_PRES=0
ok(){   printf '  PASS  %s\n' "$1"; PASS=$((PASS+1)); cls "${2:-presence}"; }
no(){   printf '  FAIL  %s — %s\n' "$1" "$2"; FAIL=$((FAIL+1)); cls "${3:-presence}"; }
pend(){ printf '  pend  %s (%s)\n' "$1" "$2"; PEND=$((PEND+1)); }
cls(){  case "$1" in negative) N_NEG=$((N_NEG+1));; exec) N_EXEC=$((N_EXEC+1));; *) N_PRES=$((N_PRES+1));; esac; }

BUILD=scripts/ralph-qwen.sh          # the build loop; §5 defers renaming it to ralph-build.sh
CODEX=scripts/ralph-codex.sh
XQ=scripts/exec-qwen.sh
XC=scripts/exec-codex.sh
ROOT_ABS="$(pwd)"
T="$(mktemp -d "${TMPDIR:-/tmp}/xb.XXXXXX")"; trap 'rm -rf "$T"' EXIT

# ---------------------------------------------------------------- scope / litter
stray="$(find specs/executor-binding -type f ! -name spec.md ! -name tasks.txt ! -name verify.sh \
  ! -path 'specs/executor-binding/evidence/*' 2>/dev/null)"
[ -z "$stray" ] && ok "scope:no-litter" negative || no "scope:no-litter" "$stray" negative

# ---------------------------------------------------------------- T1 the seam exists
echo "== AC-1/AC-2  the build loop is executor-agnostic"
if [ ! -f "$BUILD" ]; then
  pend "AC-1:default-binding-is-qwen" "$BUILD absent"
  pend "AC-2:no-executor-name-in-loop" "$BUILD absent"
else
  grep -q 'RALPH_EXEC_CMD' "$BUILD" \
    && grep -qE 'RALPH_EXEC_CMD:-.*exec-qwen\.sh' "$BUILD" \
    && ok "AC-1:default-binding-is-qwen" presence \
    || no "AC-1:default-binding-is-qwen" "no RALPH_EXEC_CMD defaulting to exec-qwen.sh" presence
  # SG-1: the moment the loop names an executor, the seam has leaked and the next one forks it.
  # Search code only — a comment may legitimately mention what a binding does.
  leak="$(sed 's/#.*//' "$BUILD" | grep -vE 'usage:' \
          | grep -nE '(^|[;&|[:space:]])(oc|codex|opencode)[[:space:]]|OC_[A-Z]|CODEX_[A-Z]' | head -3)"
  [ -z "$leak" ] && ok "AC-2:no-executor-name-in-loop" negative \
    || no "AC-2:no-executor-name-in-loop" "$(printf '%s' "$leak" | tr '\n' ' ')" negative
fi

for f in "$XQ" "$XC"; do
  [ -f "$f" ] && [ -x "$f" ] && ok "binding-present-$(basename "$f")" presence \
    || pend "binding-present-$(basename "$f")" "$f absent or not executable"
done

# ---------------------------------------------------------------- T3 the twin is gone
echo "== AC-6  nothing references a per-executor build loop (SG-4)"
[ ! -f "$CODEX" ] && ok "AC-6:codex-builder-deleted" negative \
  || no "AC-6:codex-builder-deleted" "$CODEX still exists" negative
refs="$(grep -rln 'ralph-codex' specs/*/verify.sh scripts/ 2>/dev/null \
        | grep -v '^specs/executor-binding/' | head -5)"
[ -z "$refs" ] && ok "AC-6:no-gate-references-a-twin" negative \
  || no "AC-6:no-gate-references-a-twin" "$(printf '%s' "$refs" | tr '\n' ' ')" negative
tw="$(grep -rln 'twins-do-not-drift\|twins-identical' specs/*/verify.sh 2>/dev/null \
      | grep -v '^specs/executor-binding/' | head -3)"
[ -z "$tw" ] && ok "AC-6:twin-symmetry-guards-removed" negative \
  || no "AC-6:twin-symmetry-guards-removed" "$(printf '%s' "$tw" | tr '\n' ' ')" negative

# ---------------------------------------------------------------- AC-7 the surface shrank
echo "== AC-7  the harness's gate surface is smaller than before"
# Scripts AND gates. Gate lines alone cannot satisfy this: the gate below adds 132 lines and
# the twin guards remove ~15, so gate surface goes UP by 117. The reduction is the 204-line
# duplicated loop this spec deletes. Measuring the wrong half would have set an impossible bar.
BASE=7465   # pre-change tree: 3063 script + 4402 gate
now=$(cat scripts/ralph-*.sh scripts/run-loop.sh scripts/supervise.sh scripts/gate-score.sh \
          scripts/loop-*.py scripts/loop-*.sh specs/*/verify.sh 2>/dev/null | wc -l | tr -d ' ')
[ "$now" -lt "$BASE" ] && ok "AC-7:harness-surface-shrank ($now < $BASE)" negative \
  || no "AC-7:harness-surface-shrank" "$now harness lines, was $BASE — this change must remove more than it adds" negative

# ---------------------------------------------------------------- AC-3/4/5 behaviour, one mock
echo "== AC-3/AC-4/AC-5  the loop drives a binding, bounds it, and rejects a stillborn one"
if [ ! -f "$BUILD" ]; then
  pend "AC-3:binding-receives-prompt" "$BUILD absent"
  pend "AC-4:binding-is-bounded"      "$BUILD absent"
  pend "AC-5:stillborn-aborts"        "$BUILD absent"
else
  mkrepo(){ # <dir> <verify-exit>
    mkdir -p "$1"; git -C "$1" init -q .; git -C "$1" commit -q --allow-empty -m init
    mkdir -p "$1/specs/f"; printf 'T1: only task\n' > "$1/specs/f/tasks.txt"
    printf '# spec\n' > "$1/specs/f/spec.md"
    printf '#!/usr/bin/env bash\nexit %s\n' "$2" > "$1/specs/f/verify.sh"
    git -C "$1" add -A; git -C "$1" commit -q -m base
  }
  drive(){ # <repo> <binding> -> prints rc
    # Logging stays ON, pointed into the fixture. RALPH_LOG=off makes log_path return
    # /dev/null, so the transcript measures 0 bytes and the stillborn check (rc!=0 AND <512B)
    # fires on ANY nonzero exit — the gate would then report a binding-plumbing failure for
    # every case. Turning off the thing under test is not isolation.
    ( cd "$1" && env RALPH_BUS=off RALPH_SHEET=off RALPH_RETRIES=0 \
        RALPH_LOG_DIR="$1/.lg" RALPH_STATUS_DIR="$1/.st" \
        RALPH_EXEC_CMD="$2" RALPH_EXEC_TIMEOUT=3 \
        bash "$ROOT_ABS/$BUILD" specs/f >"$1/out.txt" 2>&1; echo $? )
  }

  # AC-3 — the binding gets the prompt as $1, and its output becomes the transcript.
  R="$T/ac3"; mkrepo "$R" 0
  printf '#!/usr/bin/env bash\nprintf "PROMPT_LEN=%%s\\n" "${#1}"\nprintf "%%s\\n" "$1" > "%s/seen"\nyes padding | head -200\n' "$R" > "$T/b3.sh"
  rc="$(drive "$R" "bash $T/b3.sh")"
  if [ -s "$R/seen" ] && grep -q 'T1' "$R/seen"; then ok "AC-3:binding-receives-prompt" exec
  else no "AC-3:binding-receives-prompt" "binding did not receive the task prompt as \$1 (rc=$rc)" exec; fi

  # AC-4 — a binding that hangs is killed by the LOOP, not trusted to bound itself.
  R="$T/ac4"; mkrepo "$R" 1
  printf '#!/usr/bin/env bash\nyes padding | head -200\nsleep 60\n' > "$T/b4.sh"
  s=$(date +%s); rc="$(drive "$R" "bash $T/b4.sh")"; e=$(date +%s); el=$((e-s))
  # BOTH bounds. "under 30s" alone is satisfied by a binding that never ran — which is exactly
  # what happened while $TMPDIR was noexec: the mock died instantly on Permission denied and this
  # check went green having tested nothing. A timeout that fired must have WAITED.
  if [ "$el" -ge 3 ] && [ "$el" -lt 30 ]; then ok "AC-4:binding-is-bounded (${el}s)" exec
  elif [ "$el" -lt 3 ]; then no "AC-4:binding-is-bounded" "returned in ${el}s — the binding never ran, so nothing was bounded" exec
  else no "AC-4:binding-is-bounded" "a 60s hang ran ${el}s — RALPH_EXEC_TIMEOUT did not bound it" exec; fi

  # AC-5 — nonzero exit + a stub transcript is a broken container, not a failed attempt.
  R="$T/ac5"; mkrepo "$R" 0
  printf '#!/usr/bin/env bash\necho tiny\nexit 9\n' > "$T/b5.sh"
  rc="$(drive "$R" "bash $T/b5.sh")"
  # Distinguish "the loop rejected a stillborn binding" from "the binding could not start" —
  # both yield rc=3, and only the first is the behaviour under test.
  if [ "$rc" = 3 ] && grep -q 'exit 9' "$R/out.txt" 2>/dev/null; then ok "AC-5:stillborn-aborts (exit 3)" exec
  else no "AC-5:stillborn-aborts" "a stillborn binding gave rc=$rc, want 3 — it fell through to the gate" exec; fi
fi

# ---------------------------------------------------------------- self-application
for f in spec.md tasks.txt verify.sh; do
  [ -f "specs/executor-binding/$f" ] && ok "convention-self-applies-$f" presence \
    || no "convention-self-applies-$f" "missing" presence
done
gl=$(wc -l < specs/executor-binding/verify.sh)
[ "$gl" -le 200 ] && ok "gate-stays-small ($gl ≤ 200)" presence \
  || no "gate-stays-small" "$gl lines — a seam's gate must not grow like a subsystem's" presence

if [ "${STRICT:-0}" = 1 ] && [ "$PEND" -gt 0 ]; then
  echo; echo "STRICT=1: promoting $PEND pend to FAIL"; FAIL=$((FAIL+PEND)); PEND=0
fi
echo
echo "evidence: $N_NEG negative-invariant · $N_EXEC executing · $N_PRES presence"
echo "score: $PASS PASS / $FAIL FAIL / $PEND pend"
[ "$FAIL" -eq 0 ] || exit 1
