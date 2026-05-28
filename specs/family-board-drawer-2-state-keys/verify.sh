#!/usr/bin/env bash
# verify.sh — gate for L2 (state + keys + tap-close) of the Power Drawer.
set -uo pipefail
HTML="${HTML:-clusters/pi-k3s/family-board/index.html}"
fail=0; ok(){ echo "  PASS  $1"; }; no(){ echo "  FAIL  $1" >&2; fail=1; }
[ -f "$HTML" ] || { echo "missing $HTML" >&2; exit 2; }

# Extract the keydown handler block (existing) for scoped greps
kd=$(awk '/document\.addEventListener\("keydown"/{f=1} f{print} f&&/^  \}\);$/{exit}' "$HTML")

# AC1 — drawerOpen state var
grep -qE 'let +drawerOpen|const +drawerOpen|var +drawerOpen' "$HTML" && ok "state:drawerOpen-declared" || no "state:drawerOpen-declared"

# AC2 — .shell.open CSS with translateX(-360px)
grep -qE '\.shell\.open *\{[^}]*translateX\(-360px\)' "$HTML" && ok "css:.shell.open-translate" || no "css:.shell.open-translate"

# AC3 — .shell has a transition on transform
grep -qE '\.shell *\{[^}]*transition:[^}]*transform' "$HTML" && ok "css:.shell-transition-transform" || no "css:.shell-transition-transform"

# AC4 — Backquote handling inside the keydown listener
grep -qE 'Backquote|"`"' <<<"$kd" && ok "keydown:Backquote-branch" || no "keydown:Backquote-branch"

# AC5 — Escape close inside the keydown listener
grep -q 'Escape' <<<"$kd" && ok "keydown:Escape-branch" || no "keydown:Escape-branch"

# AC6 — .wrap click handler that references drawerOpen
grep -qE 'querySelector\("?\.wrap"?\)\.addEventListener\("?click"?|getElementsByClassName\("?wrap' "$HTML" && ok "wrap-click:listener-attached" || no "wrap-click:listener-attached"
grep -qE 'drawerOpen.*close|close.*drawer' "$HTML" && ok "wrap-click:references-state" || no "wrap-click:references-state"

# AC7 — existing keydown anchors still present
grep -qE 'e\.key *=== *"[Aa]"' <<<"$kd" && ok "intact:art-mode-A-key" || no "intact:art-mode-A-key"
grep -q 'poke()' <<<"$kd" && ok "intact:poke-fallthrough" || no "intact:poke-fallthrough"
grep -q 'matches("input, textarea")' <<<"$kd" && ok "intact:typing-guard" || no "intact:typing-guard"

# AC8 — existing ack handler still present
grep -q '// ack toggle' "$HTML" && ok "intact:ack-handler-comment" || no "intact:ack-handler-comment"

# AC9 — L3 markers must NOT be added in L2
! grep -qE 'EDGE_ZONE|COMMIT_THRESHOLD|DRAWER_WIDTH *=' "$HTML" && ok "scope:no-L3-constants-yet" || no "scope:no-L3-constants-yet (those land in L3)"
! grep -qE '\.(sliver|shell)\.grabbing' "$HTML" && ok "scope:no-grabbing-css-yet" || no "scope:no-grabbing-css-yet (L3)"

echo
if [ "$fail" = 0 ]; then echo "VERIFY: PASS"; else echo "VERIFY: FAIL"; exit 1; fi
