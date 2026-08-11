#!/bin/bash
set -uo pipefail

# Parse arguments
SPEC=""
BASE="origin/main"
JUDGE_STATE=""
GATE_LOG=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --spec)
      SPEC="$2"
      shift 2
      ;;
    --base)
      BASE="$2"
      shift 2
      ;;
    --judge-state)
      JUDGE_STATE="$2"
      shift 2
      ;;
    --gate-log)
      GATE_LOG="$2"
      shift 2
      ;;
    *)
      echo "usage:" >&2
      exit 1
      ;;
  esac
done

# Check if spec is provided
if [[ -z "$SPEC" ]]; then
  echo "usage:" >&2
  exit 1
fi

# Set default judge state path if not provided
if [[ -z "$JUDGE_STATE" ]]; then
  JUDGE_STATE="$(git rev-parse --git-path ralph-judge)"
fi

# Get current branch
BRANCH="$(git branch --show-current)"

# Count commits
COMMITS="$(git rev-list --count "$BASE..HEAD")"

# Process gate log
if [[ -n "$GATE_LOG" && -f "$GATE_LOG" ]]; then
  # Find the last occurrence of the sentinel and get the line after it
  GATE_PAYLOAD=$(awk '/---GATE-SCORE---/ {last=$0; line=NR} END {if (last != "") {getline; print}}' "$GATE_LOG")
  if [[ -z "$GATE_PAYLOAD" ]]; then
    GATE_PAYLOAD="none"
  fi
else
  GATE_PAYLOAD="none"
fi

# Process judge state
if [[ -f "$JUDGE_STATE/report.json" ]]; then
  # Simple extraction that works with bash 3.2
  JUDGE_PAYLOAD=$(jq -r '.accepted | length as $a | .rejected | length as $r | .gate_gaps | length as $g | .outcome as $o | "accepted=\($a) rejected=\($r) gate-gaps=\($g) outcome=\($o)"' "$JUDGE_STATE/report.json" 2>/dev/null)
  if [[ -z "$JUDGE_PAYLOAD" ]]; then
    JUDGE_PAYLOAD="none"
  fi
else
  JUDGE_PAYLOAD="none"
fi

# Output the report
echo "== loop report == "
echo "branch: $BRANCH"
echo "base: $BASE  commits: $COMMITS"
echo "gate: $GATE_PAYLOAD"
echo "judge: $JUDGE_PAYLOAD"