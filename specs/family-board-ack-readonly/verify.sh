#!/usr/bin/env bash
# verify.sh — deterministic acceptance gate for specs/family-board-ack-readonly.
# §10 acceptance criteria compiled into runnable assertions: exit 0 = acceptable.
#
# STATIC tier only (no deploy) — gates each ralph loop iteration. The board is a vanilla
# single HTML file, so the gate greps the implementation MARKERS the spec pins (the `locked`
# / `mine` classes, the viewer-conditional rendering, the handler guard). Visual correctness
# (muted-but-legible, the highlight looking right) is the human PR/diff gate — see §11.
#
# Run from repo root.  ./specs/family-board-ack-readonly/verify.sh
set -uo pipefail
HTML="${HTML:-clusters/pi-k3s/family-board/index.html}"
fail=0
ok(){ echo "  PASS  $1"; }
no(){ echo "  FAIL  $1" >&2; fail=1; }

[ -f "$HTML" ] || { echo "missing $HTML" >&2; exit 2; }

# Extract the two regions the change lives in, so greps are scoped (not whole-file).
quad=$(awk '/function quadHTML\(id\)/{f=1} f{print} f&&/^  \}$/{exit}' "$HTML")
ackh=$(awk '/\/\/ ack toggle/{f=1} f{print} f&&/^  \}\);$/{exit}' "$HTML")
lockcss=$(grep -E '\.seat\.locked' "$HTML" | head -1)

# AC3 — locked seats muted via opacity, interaction off, color kept (no gray/desaturate).
[ -n "$lockcss" ] && grep -q 'opacity' <<<"$lockcss" && ok "css:.seat.locked-opacity" || no "css:.seat.locked-opacity"
grep -q 'pointer-events' <<<"$lockcss" && grep -q 'none' <<<"$lockcss" && ok "css:.seat.locked-pointer-events-none" || no "css:.seat.locked-pointer-events-none"
grep -Eq 'filter:[^;]*grayscale|color: *var\(--muted\)|background: *var\(--(line|muted)\)' <<<"$lockcss" && no "css:locked-must-not-gray-out-color" || ok "css:locked-keeps-color"

# AC4 — viewer's own seat highlighted.
grep -Eq '\.seat\.mine *\{' "$HTML" && ok "css:.seat.mine-highlight" || no "css:.seat.mine-highlight"

# AC1 / AC5 — quadHTML classes seats conditionally on the active viewer.
grep -q 'viewer' <<<"$quad" && ok "quad:reads-viewer"   || no "quad:reads-viewer"
grep -q 'mine'   <<<"$quad" && ok "quad:marks-mine"     || no "quad:marks-mine"
grep -q 'locked' <<<"$quad" && ok "quad:marks-locked"   || no "quad:marks-locked"
grep -q 'aria-disabled' <<<"$quad" && ok "quad:locked-aria-disabled" || no "quad:locked-aria-disabled"
grep -q 'class="seat s-' <<<"$quad" && ok "quad:base-intact" || no "quad:base-intact"

# AC2 — the ack handler refuses to act on a locked seat (no toggle / no /api/ack).
grep -q 'locked' <<<"$ackh" && ok "handler:guards-locked" || no "handler:guards-locked"

echo
if [ "$fail" = 0 ]; then echo "VERIFY: PASS"; else echo "VERIFY: FAIL"; exit 1; fi

# --- LIVE / human diff gate (NOT gated here) ---------------------------------------
#   - In a person's view: only your seat is tappable; others visibly muted but color-legible.
#   - Your own seat reads as the live control; taps on others do nothing (tap + keyboard).
#   - Shared (no-viewer) board unchanged — all four interactive.
#   - Menu + view-switching still interactive. (AC6 — confirm no stray edits in the diff.)
