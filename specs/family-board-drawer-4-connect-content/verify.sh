#!/usr/bin/env bash
# verify.sh — gate for L4 (Connect content) of the Power Drawer.
set -uo pipefail
HTML="${HTML:-clusters/pi-k3s/family-board/index.html}"
fail=0; ok(){ echo "  PASS  $1"; }; no(){ echo "  FAIL  $1" >&2; fail=1; }
[ -f "$HTML" ] || { echo "missing $HTML" >&2; exit 2; }

# AC1 — .drawer-section inside the drawer aside
grep -qE '<div class="drawer-section">' "$HTML" && ok "markup:.drawer-section" || no "markup:.drawer-section"

# AC2 — two .qr-card elements (count them)
n=$(grep -c '<div class="qr-card">' "$HTML" || echo 0)
[ "$n" -eq 2 ] && ok "markup:qr-card-x2 (count=$n)" || no "markup:qr-card-x2 (count=$n, want 2)"

# AC3 — each QR src wired
grep -q 'src="/qr-cal-ronin.svg"' "$HTML" && ok "img:cal-ronin"  || no "img:cal-ronin"
grep -q 'src="/qr-cal-rory.svg"'  "$HTML" && ok "img:cal-rory"   || no "img:cal-rory"

# AC4 — literal webcal URLs visible
grep -q 'webcal://n8n-hook.mtgibbs.dev/webhook/cal-ronin-dd5bef4b-4b18-4965-96af-c0b26117ee4a' "$HTML" && ok "url:cal-ronin-text" || no "url:cal-ronin-text"
grep -q 'webcal://n8n-hook.mtgibbs.dev/webhook/cal-rory-d4ba8436-1a91-46e8-ad42-d3a13c85f56e'   "$HTML" && ok "url:cal-rory-text"  || no "url:cal-rory-text"

# AC5 — CSS for the new classes
grep -qE '\.drawer-section *\{' "$HTML" && ok "css:.drawer-section" || no "css:.drawer-section"
grep -qE '\.qr-card *\{'        "$HTML" && ok "css:.qr-card"        || no "css:.qr-card"

# AC6 — L1/L2/L3 anchors intact
grep -q '<div class="shell">'              "$HTML" && ok "intact:L1-shell"        || no "intact:L1-shell"
grep -q '<aside class="drawer"'            "$HTML" && ok "intact:L1-drawer"       || no "intact:L1-drawer"
grep -q '<div class="sliver"'              "$HTML" && ok "intact:L1-sliver"       || no "intact:L1-sliver"
grep -qE 'let +drawerOpen|const +drawerOpen' "$HTML" && ok "intact:L2-drawerOpen" || no "intact:L2-drawerOpen"
grep -qE '\.shell\.open *\{[^}]*translateX\(-360px\)' "$HTML" && ok "intact:L2-open-css" || no "intact:L2-open-css"
grep -qE 'DRAWER_WIDTH *= *360'  "$HTML" && ok "intact:L3-DRAWER_WIDTH" || no "intact:L3-DRAWER_WIDTH"
grep -q 'pointerdown'                      "$HTML" && ok "intact:L3-pointerdown" || no "intact:L3-pointerdown"
grep -q '// ack toggle'                    "$HTML" && ok "intact:ack-handler"    || no "intact:ack-handler"
grep -q 'function quadHTML'                "$HTML" && ok "intact:quadHTML"        || no "intact:quadHTML"

echo
if [ "$fail" = 0 ]; then echo "VERIFY: PASS"; else echo "VERIFY: FAIL"; exit 1; fi
