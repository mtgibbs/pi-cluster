#!/usr/bin/env bash
# verify.sh — gate for L1 scaffold of the Power Drawer.
# STATIC tier only; greps the L1 markers + safeguard anchors in index.html.
set -uo pipefail
HTML="${HTML:-clusters/pi-k3s/family-board/index.html}"
fail=0; ok(){ echo "  PASS  $1"; }; no(){ echo "  FAIL  $1" >&2; fail=1; }
[ -f "$HTML" ] || { echo "missing $HTML" >&2; exit 2; }

# AC1 — .shell wraps .wrap (the literal pattern; some leniency on whitespace)
grep -qE '<div class="shell">' "$HTML" && ok "markup:shell-open" || no "markup:shell-open"
# AC2 — .drawer aside (aria-hidden true)
grep -qE '<aside class="drawer"[^>]*aria-hidden="true"' "$HTML" && ok "markup:drawer-aside" || no "markup:drawer-aside"
# AC3 — .sliver div
grep -qE '<div class="sliver"[^>]*aria-hidden="true"' "$HTML" && ok "markup:sliver-div" || no "markup:sliver-div"

# AC4 — the three CSS rules (loose grep of the property each carries)
grep -qE '\.shell *\{[^}]*overflow-x: *hidden' "$HTML" && ok "css:.shell-overflow-hidden" || no "css:.shell-overflow-hidden"
grep -qE '\.drawer *\{[^}]*width: *360px'      "$HTML" && ok "css:.drawer-width-360px"   || no "css:.drawer-width-360px"
grep -qE '\.sliver *\{[^}]*position: *fixed'   "$HTML" && ok "css:.sliver-position-fixed" || no "css:.sliver-position-fixed"
grep -qE '\.sliver *\{[^}]*width: *4px'        "$HTML" && ok "css:.sliver-width-4px"     || no "css:.sliver-width-4px"
grep -qE '\.sliver *\{[^}]*var\(--gold\)'      "$HTML" && ok "css:.sliver-color-gold"    || no "css:.sliver-color-gold"

# AC5 — existing anchors still present (safeguard)
grep -q 'function quadHTML' "$HTML" && ok "intact:quadHTML"      || no "intact:quadHTML"
grep -q 'id="menu"'         "$HTML" && ok "intact:menu-widget"   || no "intact:menu-widget"
grep -q '// ack toggle'     "$HTML" && ok "intact:ack-handler"   || no "intact:ack-handler"
grep -qE 'e\.key *=== *"[Aa]"' "$HTML" && ok "intact:art-mode-A" || no "intact:art-mode-A"

# AC6 — no JS yet for the drawer (L1 is markup+css only). These tokens belong to L2/L3.
! grep -q 'drawerOpen' "$HTML"                && ok "no-js:drawerOpen-absent"    || no "no-js:drawerOpen-absent (L2's job, not L1)"
! grep -qE 'Backquote|EDGE_ZONE|COMMIT_THRESHOLD' "$HTML" && ok "no-js:gesture-keys-absent" || no "no-js:gesture-keys-absent (L2/L3's job)"

echo
if [ "$fail" = 0 ]; then echo "VERIFY: PASS"; else echo "VERIFY: FAIL"; exit 1; fi
