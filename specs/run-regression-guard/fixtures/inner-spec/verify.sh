#!/usr/bin/env bash
set -uo pipefail
fail=0
ok(){   echo "  PASS  $1"; }
no(){   echo "  FAIL  $1" >&2; fail=1; }
pend(){ if [ "${STRICT:-0}" = 1 ]; then no "$1 — still unbuilt at the final check (STRICT)"
        else echo "  pend  $1 (not built yet)"; fi; }
# Presence-gated: absent target PENDS. That is the whole point of this fixture.
[ -f a.txt ] && ok "alpha" || pend "alpha"
[ -f b.txt ] && ok "beta"  || pend "beta"
exit "$fail"
