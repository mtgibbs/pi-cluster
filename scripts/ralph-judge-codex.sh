#!/usr/bin/env bash
# ralph-judge-codex.sh — the JUDGE_CMD binding for ralph-judge.sh: Codex as intent judge.
#
# Per the judge-loop spec §3 (amended after the first-run triage #3), command bindings live
# HERE at the operator layer, never as defaults inside the loop. Pairing:
#   JUDGE_CMD=scripts/ralph-judge-codex.sh EXECUTOR_CMD=scripts/ralph-judge-exec-qwen.sh \
#     scripts/ralph-judge.sh specs/<feature>
#
# Mode 1: ralph-judge-codex.sh <spec-dir>                 -> findings JSONL on stdout, nothing else
# Mode 2: ralph-judge-codex.sh --check-resolution <json>  -> {"id":...,"resolved":bool} on stdout
#
# Codex runs read-only; its final message IS the payload (--output-last-message), the streamed
# transcript is discarded, and markdown fences are stripped defensively. ralph-judge's JSONL
# validation stays the real guard — this wrapper never repairs content, only unwraps it.
set -uo pipefail
command -v codex >/dev/null 2>&1 || { echo "ralph-judge-codex: codex CLI not on PATH" >&2; exit 1; }
OUT="$(mktemp "${TMPDIR:-/tmp}/rj-codex.XXXXXX")"
trap 'rm -f "$OUT"' EXIT

strip_fences(){ sed -e 's/^```[a-z]*$//' -e 's/^```$//' "$1" | sed '/^[[:space:]]*$/d'; }

if [ "${1:-}" = "--check-resolution" ]; then
  F="${2:?finding json required}"
  codex exec --sandbox read-only --output-last-message "$OUT" "You are the resolution checker in an automated judge loop, running in a git worktree.
FINDING (already applied to the worktree as uncommitted changes): $F
Run 'git diff' and read the touched file. Decide: does the applied change actually resolve THIS finding's problem (not merely change something)?
Your ENTIRE final message must be exactly one JSON object, no prose, no code fences:
{\"id\":\"<the finding id>\",\"resolved\":true} or {\"id\":\"<the finding id>\",\"resolved\":false}" >/dev/null 2>&1
  strip_fences "$OUT"
  exit 0
fi

SPEC_DIR="${1:?usage: ralph-judge-codex.sh <spec-dir>}"
codex exec --sandbox read-only --output-last-message "$OUT" "You are the JUDGE in ralph-judge (see specs/judge-loop/spec.md §§3-4,7-8 for your role). The deterministic gate is already green; your job is quality the gate cannot see. Review the solution for spec '$SPEC_DIR' against its INTENT.

Read: $SPEC_DIR/spec.md — its Touches/Scope sections name the solution files; read those files, plus specs/constitution.md and $SPEC_DIR/verify.sh.

Emit findings ONLY within the conservative v1 surface: localized comments, naming, clarity, and literal spec-fidelity corrections. Anything bigger (refactors, dead code, missing gate checks) must be kind=gate-gap (report-only). Every finding MUST cite a real spec section or constitution principle as spec_anchor — no anchor, no finding. Do not propose changes to behavior.

OUTPUT CONTRACT — your ENTIRE final message is 0..5 lines, each line one JSON object, NO prose, NO code fences, NO trailing commentary:
{\"id\":\"<kebab-slug>\",\"file\":\"<repo-relative path>\",\"line\":<integer >=1>,\"category\":\"clarity|naming|spec-fidelity|gate-gap\",\"spec_anchor\":\"<§ or principle>\",\"problem\":\"<one sentence>\",\"suggested_change\":\"<concrete, small, applyable instruction>\",\"kind\":\"mutate|gate-gap\"}
Fields exactly as listed, no extras. id must match ^[a-z0-9][a-z0-9-]*$. An empty message means: nothing worth changing." >/dev/null 2>&1
strip_fences "$OUT"
exit 0
