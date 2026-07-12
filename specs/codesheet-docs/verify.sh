#!/usr/bin/env bash
# verify.sh — deterministic gate for specs/codesheet-docs (pure bash + git).
set -uo pipefail
R="scripts/README.md"
fails=0
check() { # check <id> <desc> <cmd...>
  local id="$1" desc="$2"; shift 2
  if "$@" >/dev/null 2>&1; then echo "PASS $id: $desc"; else echo "FAIL $id: $desc"; fails=$((fails+1)); fi
}

check AC1  "codesheet heading exists"              grep -Eqi '^##+ .*codesheet' "$R"
check AC2  "names scripts/gen-codesheet.mjs"       grep -q 'scripts/gen-codesheet\.mjs' "$R"
check AC3  "documents OC_SHEET=off"                grep -q 'OC_SHEET=off' "$R"
check AC4  "documents OC_SHEET_GEN"                grep -q 'OC_SHEET_GEN' "$R"
check AC5  "documents RALPH_SHEET"                 grep -q 'RALPH_SHEET' "$R"
check AC6  "mentions ralph-qwen.sh"                grep -q 'ralph-qwen\.sh' "$R"
check AC7a "states symbol-graph layer"             grep -qi 'symbol' "$R"
check AC7b "states edge-index layer"               grep -qi 'edge index' "$R"
check AC8  "cites the research doc path"           grep -q 'docs/research/codemap-serena-token-efficiency\.md' "$R"
check AC9a "kept op://work-vault example"          grep -q 'op://work-vault/opencode/key' "$R"
check AC9b "kept oc bootstrap line"                grep -q 'cp scripts/oc ~/.local/bin/oc' "$R"
check AC10 "only scripts/README.md touched"        test -z "$(git status --porcelain | grep -v ' scripts/README\.md$')"

echo "VERIFY: $((12 - fails))/12 checks passed"
[ "$fails" -eq 0 ]
