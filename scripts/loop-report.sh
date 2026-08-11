#!/bin/bash
# loop-report.sh — one-screen summary of a strategy run.
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

# Set default judge state path
if [[ -z "$JUDGE_STATE" ]]; then
  JUDGE_STATE="$(git rev-parse --git-path ralph-judge)"
fi

# Get current branch
BRANCH="$(git branch --show-current)"

# Count commits
COMMITS="$(git rev-list --count "$BASE..HEAD")"

# Process gate log
if [[ -n "$GATE_LOG" ]] && [[ -f "$GATE_LOG" ]]; then
  # Find the last occurrence of ---GATE-SCORE--- and get the line after it
  GATE_PAYLOAD=""
  while IFS= read -r line; do
    if [[ "$line" == "---GATE-SCORE---" ]]; then
      # This is a sentinel, we'll read the next line as payload
      read -r next_line
      GATE_PAYLOAD="$next_line"
    fi
  done < "$GATE_LOG"
  
  if [[ -z "$GATE_PAYLOAD" ]]; then
    GATE_PAYLOAD="none"
  fi
else
  GATE_PAYLOAD="none"
fi

# Process judge state
if [[ -d "$JUDGE_STATE" ]] && [[ -f "$JUDGE_STATE/report.json" ]]; then
  if jq -e . "$JUDGE_STATE/report.json" >/dev/null 2>&1; then
    JUDGE_PAYLOAD=""
    # Extract the required values from report.json using jq
    ACCEPTED_COUNT=$(jq -r '.accepted | length' "$JUDGE_STATE/report.json")
    REJECTED_COUNT=$(jq -r '.rejected | length' "$JUDGE_STATE/report.json")
    GATE_GAPS_COUNT=$(jq -r '.gate_gaps | length' "$JUDGE_STATE/report.json")
    OUTCOME=$(jq -r '.outcome' "$JUDGE_STATE/report.json")
    
    JUDGE_PAYLOAD="accepted=$ACCEPTED_COUNT rejected=$REJECTED_COUNT gate-gaps=$GATE_GAPS_COUNT outcome=$OUTCOME"
  else
    JUDGE_PAYLOAD="none"
  fi
else
  JUDGE_PAYLOAD="none"
fi

# Output the report
echo "== loop report ==" 
echo "branch: $BRANCH"
echo "base: $BASE  commits: $COMMITS"
echo "gate: $GATE_PAYLOAD"
echo "judge: $JUDGE_PAYLOAD"