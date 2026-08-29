#!/usr/bin/env bash
# exec-qwen.sh — the qwen executor binding for the build loop.
#
# Thin by contract (specs/executor-binding §3, §7): take the prompt as $1, read ROOT from the
# environment, run the tool, let stdout be the transcript. No retry, no gate, no evidence, no
# stopping logic — the loop owns all of that. If this file ever grows a decision, the decision
# belongs in the loop, or every future binding has to reimplement it.
#
# The watchdog is the LOOP's job (ralph-qwen.sh run_bounded), so no timeout here. OC_SHEET=off
# because ralph already injects the codesheet once per loop; letting oc add it again would put
# the same bytes in twice and break the prefix-cache stability that makes it ~free.
set -uo pipefail
exec env OC_SHEET=off oc run --dir "${ROOT:-$PWD}" "${1:?exec-qwen.sh <prompt>}"
