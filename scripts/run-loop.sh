#!/usr/bin/env bash
# run-loop.sh — run a named loop strategy against a spec.
#
#   scripts/run-loop.sh <strategy> specs/<feature>
#   scripts/run-loop.sh --list
#
# A strategy is scripts/loops/<name>.env: STRATEGY_PHASES plus operator-layer
# bindings (see scripts/loops/README.md for the contract). This script only
# sequences existing loops — it adds no stopping logic and no cleverness.
# Fail-closed: any phase's nonzero exit stops the run with that exit code.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOOPS_DIR="$SCRIPT_DIR/loops"

if [ "${1:-}" = "--list" ]; then
  for f in "$LOOPS_DIR"/*.env; do
    [ -f "$f" ] || continue
    name="$(basename "$f" .env)"
    desc="$(sed -n 's/^STRATEGY_DESC="\(.*\)"$/\1/p' "$f" | head -1)"
    printf '  %-20s %s\n' "$name" "$desc"
  done
  exit 0
fi

STRATEGY="${1:?usage: run-loop.sh <strategy> <spec-dir>  (or --list)}"
SPEC_DIR="${2:?usage: run-loop.sh <strategy> <spec-dir>}"
ENV_FILE="$LOOPS_DIR/$STRATEGY.env"

# Preflight, all fatal: known strategy, real spec, and never on main —
# the constitution's worktree rule applies to strategies same as hand runs.
[ -f "$ENV_FILE" ] || { echo "run-loop: unknown strategy '$STRATEGY' — try --list" >&2; exit 1; }
[ -f "$SPEC_DIR/spec.md" ] && [ -f "$SPEC_DIR/verify.sh" ] \
  || { echo "run-loop: $SPEC_DIR needs spec.md + verify.sh" >&2; exit 1; }
branch="$(git branch --show-current 2>/dev/null || true)"
[ -n "$branch" ] && [ "$branch" != "main" ] \
  || { echo "run-loop: refuse to run on '$branch' — use a worktree on a throwaway branch" >&2; exit 1; }

# shellcheck source=/dev/null
. "$ENV_FILE"
: "${STRATEGY_PHASES:?$ENV_FILE must set STRATEGY_PHASES}"

echo "strategy: $STRATEGY — ${STRATEGY_DESC:-}"
echo "spec:     $SPEC_DIR   branch: $branch"

for phase in $STRATEGY_PHASES; do
  echo
  echo "── phase: $phase ─────────────────────────────"
  case "$phase" in
    build)
      [ -f "$SPEC_DIR/tasks.txt" ] || { echo "run-loop: build phase needs $SPEC_DIR/tasks.txt" >&2; exit 1; }
      bash "${BUILD_CMD:-$SCRIPT_DIR/ralph-qwen.sh}" "$SPEC_DIR" ;;
    judge)
      bash "$SCRIPT_DIR/ralph-judge.sh" "$SPEC_DIR" ;;
    *)
      echo "run-loop: unknown phase '$phase' in $ENV_FILE — phases are: build judge" >&2
      exit 1 ;;
  esac
  rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "run-loop: phase '$phase' exited $rc — stopping (fail-closed)" >&2
    exit "$rc"
  fi
done

echo
echo "run-loop: all phases complete ($STRATEGY_PHASES)"
