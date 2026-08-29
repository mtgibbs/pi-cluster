#!/usr/bin/env bash
# exec-codex.sh — the Codex executor binding for the build loop.
#
# Same contract as exec-qwen.sh: prompt in $1, ROOT from the environment, transcript on stdout.
# This file plus scripts/loops/build-codex.env is the ENTIRE cost of adding an executor — it
# replaced a 204-line copy of the whole loop, which three specs then had to police for drift.
#
# --skip-git-repo-check: the loop already guarantees a git worktree on a throwaway branch.
# Sandboxing is left to the container, which is the real boundary here; CODEX_SANDBOX overrides
# it for a laptop run, where there is no outer sandbox.
set -uo pipefail
exec codex exec --cd "${ROOT:-$PWD}" \
  --sandbox "${CODEX_SANDBOX:-danger-full-access}" \
  --skip-git-repo-check "${1:?exec-codex.sh <prompt>}"
