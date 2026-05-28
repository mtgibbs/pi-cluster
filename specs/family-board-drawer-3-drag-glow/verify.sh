#!/usr/bin/env bash
# verify.sh — gate for L3 (drag + glow ramp) of the Power Drawer.
set -uo pipefail
HTML="${HTML:-clusters/pi-k3s/family-board/index.html}"
fail=0; ok(){ echo "  PASS  $1"; }; no(){ echo "  FAIL  $1" >&2; fail=1; }
[ -f "$HTML" ] || { echo "missing $HTML" >&2; exit 2; }

# AC1 — constants with exact literal values
grep -qE 'DRAWER_WIDTH *= *360'         "$HTML" && ok "const:DRAWER_WIDTH-360"      || no "const:DRAWER_WIDTH-360"
grep -qE 'EDGE_ZONE *= *32'             "$HTML" && ok "const:EDGE_ZONE-32"          || no "const:EDGE_ZONE-32"
grep -qE 'COMMIT_THRESHOLD *= *0\.3'    "$HTML" && ok "const:COMMIT_THRESHOLD-0.3"  || no "const:COMMIT_THRESHOLD-0.3"

# AC2/AC3/AC4 — pointer event handlers and edge-zone reference
grep -q 'pointerdown'        "$HTML" && ok "events:pointerdown" || no "events:pointerdown"
grep -q 'pointermove'        "$HTML" && ok "events:pointermove" || no "events:pointermove"
grep -q 'pointerup'          "$HTML" && ok "events:pointerup"   || no "events:pointerup"
grep -qE 'innerWidth *- *EDGE_ZONE|innerWidth *- *32' "$HTML" && ok "edge-zone:right-edge-gate" || no "edge-zone:right-edge-gate"

# AC5 — grabbing CSS rule with glow
grep -qE '\.(sliver|shell)\.grabbing *\{[^}]*box-shadow' "$HTML" && ok "css:grabbing-glow" || no "css:grabbing-glow"

# AC6 — prefers-reduced-motion adjustment touches the grabbing rule (loose)
grep -q 'prefers-reduced-motion' "$HTML" && ok "css:reduced-motion-present" || no "css:reduced-motion-present"

# AC7 — L1/L2 anchors still intact (safeguards)
grep -q '<div class="shell">'          "$HTML" && ok "intact:L1-shell"          || no "intact:L1-shell"
grep -q '<aside class="drawer"'        "$HTML" && ok "intact:L1-drawer"         || no "intact:L1-drawer"
grep -q '<div class="sliver"'          "$HTML" && ok "intact:L1-sliver"         || no "intact:L1-sliver"
grep -qE 'let +drawerOpen|const +drawerOpen' "$HTML" && ok "intact:L2-drawerOpen" || no "intact:L2-drawerOpen"
grep -qE '\.shell\.open *\{[^}]*translateX\(-360px\)' "$HTML" && ok "intact:L2-open-css" || no "intact:L2-open-css"
grep -qE 'Backquote|"`"'    "$HTML" && ok "intact:L2-backquote" || no "intact:L2-backquote"
grep -q 'Escape'           "$HTML" && ok "intact:L2-escape"    || no "intact:L2-escape"
grep -q '// ack toggle'    "$HTML" && ok "intact:ack-handler"  || no "intact:ack-handler"
grep -qE 'e\.key *=== *"[Aa]"' "$HTML" && ok "intact:art-mode-A" || no "intact:art-mode-A"

echo
if [ "$fail" = 0 ]; then echo "VERIFY: PASS"; else echo "VERIFY: FAIL"; exit 1; fi
