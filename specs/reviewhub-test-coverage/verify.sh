#!/usr/bin/env bash
# Deterministic gate for reviewhub-test-coverage (ralph-qwen runs this after each task).
#
# CUMULATIVE-SAFE: it checks pytest-green + the structural quality of EVERY validator
# test file that *currently exists*, so it passes incrementally as the loop adds one
# test file per task (it never demands files a later task will create).
#
# Gate is STRUCTURAL, not coverage-based: pytest-cov won't install on this
# externally-managed python (PEP 668), so instead of a gameable "tests pass" we require
# each test file to import its 1:1 module, carry >=10 tests, and exercise >=4 of the
# five pure functions. Depth/correctness is the human PR review's job.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || { echo "VERIFY FAIL: not in a git repo"; exit 1; }

VDIR="scripts/reviewhub/validators"
SURFACE="build_prompt parse aggregate _render_pr applies_files"
MIN_TESTS=10
MIN_SURFACE=4
fail=0

# 1) Whole suite green — engine tests stay passing AND every new validator test passes.
#    PYTHONPATH=scripts for the engine test; the validators' conftest.py adds its own paths.
if ! PYTHONPATH=scripts python3 -m pytest -q scripts/test_triggerable_judge.py "$VDIR" >/tmp/rh_verify.log 2>&1; then
  echo "VERIFY FAIL: pytest is not green"; tail -25 /tmp/rh_verify.log; exit 1
fi

# 2) Structural quality of each validator test file that EXISTS (cumulative-safe).
shopt -s nullglob
count=0
for tf in "$VDIR"/test_*.py; do
  count=$((count + 1))
  base=$(basename "$tf" .py); mod="${base#test_}"
  if ! grep -qE "(from|import) ${mod}\b" "$tf"; then
    echo "VERIFY FAIL: $tf does not import its module '${mod}'"; fail=1
  fi
  n=$(grep -cE '^[[:space:]]*def test_' "$tf")
  if [ "$n" -lt "$MIN_TESTS" ]; then
    echo "VERIFY FAIL: $tf has $n test(s) (need >=$MIN_TESTS)"; fail=1
  fi
  hits=0
  for fn in $SURFACE; do grep -qE "${fn}" "$tf" && hits=$((hits + 1)); done
  if [ "$hits" -lt "$MIN_SURFACE" ]; then
    echo "VERIFY FAIL: $tf exercises $hits/5 pure functions (need >=$MIN_SURFACE)"; fail=1
  fi
done

[ "$fail" -eq 0 ] || exit 1
echo "VERIFY OK: pytest green; $count validator test file(s) structurally sound"
