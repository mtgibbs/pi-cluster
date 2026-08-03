#!/usr/bin/env bash
# ralph-judge-exec-qwen.sh — the EXECUTOR_CMD binding for ralph-judge.sh: qwen applies one finding.
#
# Per the judge-loop spec §3 (amended after the first-run triage #3), command bindings live
# HERE at the operator layer. Receives the finding JSON as its single argument; must not
# commit (the loop commits after the full accept predicate) and must touch only the finding's
# file (the loop rejects anything else as scope-violation).
#
# Runs via `oc run` (Keychain-first key resolution — see scripts/README.md; a fresh worktree
# also needs the gitignored opencode.json copied in, or headless oc auto-rejects every tool).
set -uo pipefail
command -v oc >/dev/null 2>&1 || { echo "ralph-judge-exec-qwen: oc not on PATH" >&2; exit 1; }
F="${1:?finding json required}"
FILE="$(printf '%s' "$F" | jq -r .file)"
LINE="$(printf '%s' "$F" | jq -r .line)"
PROBLEM="$(printf '%s' "$F" | jq -r .problem)"
CHANGE="$(printf '%s' "$F" | jq -r .suggested_change)"
OC_RUN_TIMEOUT="${OC_RUN_TIMEOUT:-480}" exec oc run "Apply exactly ONE small change and nothing else.
File: $FILE (around line $LINE)
Problem: $PROBLEM
Change to make: $CHANGE
Rules: touch ONLY $FILE. Do NOT run git add or git commit. Do NOT create new files. Make the smallest edit that implements the change, then stop."
