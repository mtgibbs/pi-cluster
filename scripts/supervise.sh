#!/usr/bin/env bash
# supervise.sh — run a loop strategy and auto-recover from the stillborn-stream hang.
#
# Observed 2026-08-19, three times, then a fourth: opencode logs one `stream` line, receives no
# first token, and never returns. The `oc` watchdog (sleep N; kill; sleep 3; kill -9) does not win
# against it — one run sat 53 minutes against a 2400 s budget — so the timeout cannot be relied on
# and detection has to live OUTSIDE the thing that failed to detect it. Four for four.
#
# Signature: the executor log stays at 31 bytes (banner only) while the model serves other clients
# in ~1 s. A plain relaunch clears it. The discriminator is SIZE, not staleness — an 82 KB log
# idle for 25 minutes is a healthy run buffering a long generation, and a staleness rule would
# kill it (lessons.md C2).
#
# This is a bounded restarter, NOT a retry loop: it never re-runs a task that FAILED verification.
# That is ralph's job and it burns attempts deliberately. This only restarts a process that never
# started. Any other nonzero exit is a real verdict and stops the run.
#
# Usage — from the target worktree root, same argument shape as run-loop.sh:
#   scripts/supervise.sh <strategy> <spec-dir>
#   OC_RUN_TIMEOUT=2400 RALPH_RETRIES=3 scripts/supervise.sh build-then-judge specs/v1
#
# Env: SUPERVISE_EVIDENCE_DIR (default ~/.harness/evidence/<repo>), SUPERVISE_RUNTAG (default
# `run`), STILLBORN_BYTES, STILLBORN_AFTER, MAX_RESTARTS, POLL. Everything else — OC_RUN_TIMEOUT,
# RALPH_RETRIES, MAX_ROUNDS, RALPH_* — is inherited by the child untouched.
#
# It lived as a single untracked copy inside an evidence bundle on one laptop until 2026-08-24:
# the only component of the loop with no version history, and the one that recovers the others.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STRATEGY="${1:?usage: supervise.sh <strategy> <spec-dir>}"
SPEC_DIR="${2:?usage: supervise.sh <strategy> <spec-dir>}"

WORKTREE="$(git rev-parse --show-toplevel 2>/dev/null)" \
  || { echo "supervise: not inside a git work tree" >&2; exit 1; }
REPO="$(basename "$WORKTREE")"

EVID="${SUPERVISE_EVIDENCE_DIR:-$HOME/.harness/evidence/$REPO}"
STATUS_DIR="${RALPH_STATUS_DIR:-$HOME/.harness/status/$REPO}"

# One tag per INVOCATION, not one per install. `attempt` resets to 1 every time supervise.sh
# is started, so a fixed RUNTAG means the second invocation's launch1 overwrites the first
# invocation's launch1. The comment below already records that a fixed name was silently
# overwritten by every relaunch — that was fixed for relaunches WITHIN one invocation and left
# broken ACROSS them. specs/asset-ladder needed four invocations on 2026-08-25 and three of its
# launch logs are gone. Seconds since epoch is enough to separate them and still sorts.
RUNTAG="${SUPERVISE_RUNTAG:-run-$(date +%s)}"
STILLBORN_BYTES="${STILLBORN_BYTES:-40}"    # 31 = banner only; anything real is far larger
STILLBORN_AFTER="${STILLBORN_AFTER:-300}"   # seconds with no growth before we call it dead
MAX_RESTARTS="${MAX_RESTARTS:-8}"
POLL="${POLL:-30}"

mkdir -p "$EVID/supervisor" "$EVID/killed-attempts" 2>/dev/null || true

# hb_mark, so a killed loop's heartbeat gets a terminal phase instead of freezing at `running`.
# shellcheck source=/dev/null
if ! . "$SCRIPT_DIR/ralph-status.sh" 2>/dev/null; then hb_mark(){ :; }; fi

log(){ printf '[supervise %s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

# BSD stat and GNU stat disagree on every flag; the loops run on both a macOS laptop and Linux
# containers, so ask both. Size goes through wc, which needs no dialect at all.
fsize(){ wc -c < "$1" 2>/dev/null | tr -d ' ' || echo 0; }
fmtime(){ stat -f %m "$1" 2>/dev/null || stat -c %Y "$1" 2>/dev/null || date +%s; }

kill_tree(){ # <pgid>
  # The job leader's process group first — scoped, and it reaches every descendant the shell
  # knows about. `set -m` below is what makes the child a group leader.
  kill -TERM -"$1" 2>/dev/null; sleep 2; kill -KILL -"$1" 2>/dev/null
  # Fallback sweep, deliberately broad: the hang being recovered from is opencode NOT responding,
  # and a detached or re-parented executor survives the group kill. This WILL take out any other
  # ralph loop on this host — acceptable because the supervisor is meant to own the machine's
  # loop, and a survivor holds the GPU lane the relaunch needs.
  for pat in 'run-loop.sh' 'ralph-qwen.sh' 'ralph-codex.sh' 'ralph-judge.sh' '/oc run'; do
    pgrep -f "$pat" 2>/dev/null | while read -r p; do kill -9 "$p" 2>/dev/null; done
  done
  pgrep -x opencode 2>/dev/null | while read -r p; do kill -9 "$p" 2>/dev/null; done
  pgrep -x opencode.exe 2>/dev/null | while read -r p; do kill -9 "$p" 2>/dev/null; done
  sleep 2
}

restarts=0
attempt=0
set -m   # each background job gets its own process group, so kill_tree can signal the tree

while [ "$restarts" -le "$MAX_RESTARTS" ]; do
  attempt=$((attempt + 1))
  # Named by tag and attempt under the durable dir. The job's own temp dir dies with the job,
  # and a fixed name (run-sup-1.log) was silently overwritten by every relaunch.
  RUNLOG="$EVID/supervisor/$RUNTAG-launch$attempt.log"

  # A killed attempt can leave the worktree dirty. ralph resets between its OWN attempts; after
  # an external kill nobody has. `git clean -fd` (no -x) leaves .gitignore'd build caches alone —
  # a cold SPM cache would surface as a build failure and read as a spec violation.
  #
  # SAY WHAT IT DISCARDS. This reset cannot tell a killed attempt's debris from an operator's
  # deliberate edit — and the spec dir is exactly where the documented recovery procedure tells
  # you to make one. `docs/NEXT-RUN.md` says to trim tasks.txt when a task is already done;
  # doing so and relaunching on 2026-08-25 silently reverted the trim, ran the completed T1
  # three times, and STOPped on "changed nothing". Nothing in the output said why, so it read
  # as operator error. Naming the spec-dir files it is about to throw away costs one git call
  # and turns a silent trap into a visible one.
  _dirty="$( cd "$WORKTREE" && git status --porcelain -- "$SPEC_DIR" 2>/dev/null )"
  if [ -n "$_dirty" ]; then
    log "NOTE: discarding uncommitted changes under $SPEC_DIR before launch:"
    printf '%s\n' "$_dirty" | sed 's/^/    /'
    log "      if that was a deliberate queue trim, COMMIT it — this reset runs every launch."
  fi
  ( cd "$WORKTREE" && git checkout -- . 2>/dev/null; git clean -fdq 2>/dev/null ) || true

  log "launching $STRATEGY on $SPEC_DIR (run $attempt, restarts used $restarts/$MAX_RESTARTS)"
  ( cd "$WORKTREE" && bash "$SCRIPT_DIR/run-loop.sh" "$STRATEGY" "$SPEC_DIR" ) > "$RUNLOG" 2>&1 &
  loop_pid=$!

  hung=0
  while kill -0 "$loop_pid" 2>/dev/null; do
    sleep "$POLL"
    D=$(grep -a '^logs: ' "$RUNLOG" 2>/dev/null | tail -1 | sed 's/^logs: //')
    [ -n "$D" ] && [ -d "$D" ] || continue
    L=$(ls -t "$D"/*.log 2>/dev/null | head -1)
    [ -n "$L" ] || continue
    SZ=$(fsize "$L")
    AGE=$(( $(date +%s) - $(fmtime "$L") ))
    [ "$SZ" -le "$STILLBORN_BYTES" ] && [ "$AGE" -gt "$STILLBORN_AFTER" ] || continue

    log "STILLBORN: $(basename "$L") ${SZ}B, no growth for ${AGE}s — killing and relaunching"
    # ralph writes its .diff evidence only when VERIFY fails. A killed attempt never reaches
    # verify, so every hang loses its diff unless someone snapshots first. That someone is here.
    snap="$EVID/killed-attempts/$RUNTAG-launch$attempt-$(basename "$D")"
    mkdir -p "$snap"
    cp -R "$D"/. "$snap/" 2>/dev/null || true
    ( cd "$WORKTREE" && git diff > "$snap/worktree.diff" 2>/dev/null
      git status --short > "$snap/worktree-status.txt" 2>/dev/null
      git ls-files --others --exclude-standard > "$snap/untracked.txt" 2>/dev/null ) || true
    printf 'killed: stillborn %sB after %ss at %s\n' "$SZ" "$AGE" "$(date -u +%FT%TZ)" > "$snap/why.txt"
    log "  evidence snapshotted -> $snap"

    hung=1
    kill_tree "$loop_pid"
    # AFTER the kill, so the victim's keep-alive ticker cannot race this back to `running`.
    # The log dir is named <agent>-<pid>, which is exactly the heartbeat's filename.
    hb_mark "$STATUS_DIR/$(basename "$D").json" killed
    break
  done

  if [ "$hung" -eq 1 ]; then
    restarts=$((restarts + 1))
    continue
  fi

  wait "$loop_pid" 2>/dev/null; rc=$?
  log "run-loop exited $rc"
  tail -30 "$RUNLOG"
  if [ "$rc" -eq 0 ]; then
    log "SUCCESS — all phases complete"
    exit 0
  fi
  # A nonzero exit that is NOT a hang is a real verdict (STOP after retries, a judge preflight
  # refusal, a run on the wrong branch). Do not paper over it by relaunching.
  log "STOP — nonzero exit with a live executor. This is a real failure, not a hang."
  exit "$rc"
done

log "gave up after $MAX_RESTARTS restarts — the stillborn hang is no longer transient"
exit 1
