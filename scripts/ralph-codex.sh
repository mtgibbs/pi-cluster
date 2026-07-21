#!/usr/bin/env bash
# ralph-codex.sh — the bounded SDD loop, driven by the OpenAI Codex CLI.
#
# Structurally identical to ralph-qwen.sh, and deliberately so: same spec-dir
# contract (spec.md / verify.sh / tasks.txt), same fresh-session-per-attempt,
# same DETERMINISTIC external gate, same retry-with-feedback, same stop-for-a-
# human exit 2. The loop carries the rigor; only the executor swaps.
#
# What differs from the qwen loop, and why:
#
#   * Executor is `codex exec` (headless), not `oc run`. Codex reads AGENTS.md
#     natively — the same lean brief qwen already uses — so there's no second
#     brief to maintain.
#   * The navigation codesheet defaults OFF here. Its 20-56% context saving was
#     measured against a 30B with a small window (docs/research/codemap-serena-
#     token-efficiency.md); codex has its own repo navigation and prompt cache,
#     so the same win is UNMEASURED for it. RALPH_SHEET=on turns it on if you
#     want to A/B that — don't assume the qwen result transfers.
#   * Sandboxing is left to the container, not to codex. See CODEX_SANDBOX below.
#
# Usage (run from inside a git worktree on a throwaway branch):
#   scripts/ralph-codex.sh specs/<feature>
set -uo pipefail

SPEC_DIR="${1:?usage: ralph-codex.sh <spec-dir>}"
RETRIES="${RALPH_RETRIES:-2}"
SPEC="$SPEC_DIR/spec.md"; VERIFY="$SPEC_DIR/verify.sh"; TASKS="$SPEC_DIR/tasks.txt"
for f in "$SPEC" "$VERIFY" "$TASKS"; do [ -f "$f" ] || { echo "missing $f" >&2; exit 1; }; done
ROOT="$(git rev-parse --show-toplevel)"

# Durable heartbeat (see ralph-status.sh) — same status-file contract as
# ralph-qwen, tagged agent=codex. No-op stubs if the helper is absent.
RALPH_AGENT="${RALPH_AGENT:-codex}"
if [ -f "$(dirname "$0")/ralph-status.sh" ]; then
  . "$(dirname "$0")/ralph-status.sh"
else
  hb_init() { :; }; hb_write() { :; }
fi

command -v codex >/dev/null 2>&1 || { echo "ralph-codex: codex CLI not on PATH" >&2; exit 1; }
codex login status >/dev/null 2>&1 || {
  echo "ralph-codex: codex isn't logged in — run 'codex login --device-auth' first" >&2; exit 1; }

# The container IS the sandbox boundary (read-only rootfs, cap_drop ALL,
# non-root, no docker socket / kubeconfig / NAS, output PR-gated), so codex's
# own nested landlock+seccomp layer buys little and is unreliable under
# cap_drop: ALL. `danger-full-access` here means "trust the outer sandbox,"
# which is exactly the case codex's own help text describes for that flag.
# Running this on a LAPTOP instead? Override it — there's no outer sandbox:
#   CODEX_SANDBOX=workspace-write scripts/ralph-codex.sh specs/<feature>
SANDBOX="${CODEX_SANDBOX:-danger-full-access}"
TIMEOUT="${CODEX_RUN_TIMEOUT:-900}"

# Off by default — see the header. Byte-stable across every task and retry when
# enabled, so it rides the prefix cache rather than being regenerated per task.
SHEET=""
SHEET_GEN="$(dirname "$0")/gen-codesheet.mjs"
if [ "${RALPH_SHEET:-off}" = "on" ] && [ -f "$SHEET_GEN" ] && command -v node >/dev/null 2>&1; then
  SHEET="$(node "$SHEET_GEN" "$ROOT" 2>/dev/null || true)"
  [ -n "$SHEET" ] && echo "codesheet: injected (~$(( ${#SHEET} / 4 )) tokens, stable for the whole loop)"
fi

# Watchdog, ported from scripts/oc: a stalled stream should get killed, not
# hang for hours. Not `timeout(1)` — that isn't on stock macOS, and this script
# has to run identically on the laptop and in the container.
run_codex() {
  codex exec --cd "$ROOT" --sandbox "$SANDBOX" --skip-git-repo-check "$1" >/dev/null 2>&1 &
  local pid=$! rc
  ( sleep "$TIMEOUT"
    if kill -0 "$pid" 2>/dev/null; then
      echo "  ! codex exec exceeded ${TIMEOUT}s — killing (likely a stalled session)." >&2
      kill "$pid" 2>/dev/null; sleep 3; kill -9 "$pid" 2>/dev/null
    fi ) &
  local watchdog=$!
  wait "$pid"; rc=$?
  kill "$watchdog" 2>/dev/null
  return "$rc"
}

hb_init; hb_write starting

while IFS= read -r task || [ -n "$task" ]; do
  [ -z "${task// }" ] && continue
  echo "════════ TASK: $task ════════"
  HB_TASK="$task"; HB_TIDX=$((HB_TIDX + 1)); hb_write running
  feedback=""; passed=0
  for attempt in $(seq 1 $((RETRIES + 1))); do
    HB_ATTEMPT="$attempt"; hb_write running
    prompt="${SHEET:+$SHEET

}Read $SPEC. Implement ONLY this one task, nothing else: ${task}
Follow the spec's section 10 reference and section 7 acceptance criteria EXACTLY.
Do not touch anything outside this task's scope. Reuse existing patterns; never invent
URLs/UIDs. When done, stop.${feedback}"

    # Fresh session each attempt (no `codex exec resume`) = no context bloat.
    run_codex "$prompt" || true

    # The gate: deterministic, external. The model does NOT get to say "done".
    hb_write verifying
    if out="$(cd "$ROOT" && bash "$VERIFY" 2>&1)"; then
      echo "  ✓ $task passed verify (attempt $attempt)"
      git -C "$ROOT" add -A
      git -C "$ROOT" commit -q -m "ralph(codex): ${task%%:*} — ${task#*: }" || true
      passed=1; hb_write passed true; break
    fi
    echo "  ✗ verify failed (attempt $attempt); retrying with feedback" >&2
    hb_write failed false
    # Feed the failing checks back into the next fresh attempt — targeted, not vibes.
    feedback="
A previous attempt FAILED verification with:
$(printf '%s' "$out" | grep -E 'FAIL|VERIFY' | head -20)
Fix exactly those failures."
    git -C "$ROOT" checkout -- . 2>/dev/null || true   # reset tracked changes from the bad attempt
    git -C "$ROOT" clean -fd -- . 2>/dev/null || true  # ...and untracked files/dirs it created —
    # `checkout --` alone leaves these behind, letting an out-of-scope file from attempt N
    # survive into attempt N+1 (and even arm a later task's PEND-gated checks early — see
    # the rom-library-structure dogfood PR for the real failure this caused).
  done

  if [ "$passed" != 1 ]; then
    echo "✋ STOP: '$task' failed verify after $((RETRIES + 1)) attempts — needs a human." >&2
    hb_write stopped false
    exit 2
  fi
done < "$TASKS"

hb_write done true
echo "════════ all tasks passed verify — branch ready for PR review ════════"
git -C "$ROOT" log --oneline -"$(grep -cve '^[[:space:]]*$' "$TASKS")"
