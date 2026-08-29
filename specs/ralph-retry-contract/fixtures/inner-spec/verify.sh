#!/usr/bin/env bash
set -uo pipefail
fail=0
ok(){ echo "  PASS  $1"; }
no(){ echo "  FAIL  $1" >&2; fail=1; }
[ -f a.txt ] && ok "alpha" || no "alpha"
[ -f b.txt ] && ok "beta"  || no "beta"
# A PASS line whose MESSAGE contains the word fail — the leading-token rule must not
# miscount this one (AC4).
ok "gamma-must-not-fail-the-parser"
exit "$fail"
