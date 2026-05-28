# Spec: Family Board — Power Drawer · L4 Connect content

- **Status:** Planned (4 of 4)
- **Owner:** Matt
- **Constitution:** `specs/constitution.md` (+ `clusters/pi-k3s/family-board/CLAUDE.md`)
- **Touches:** `clusters/pi-k3s/family-board/index.html` (only).
- **Builds on:** L1 scaffold (assumes `.drawer` exists in the DOM).
- **Ships alongside (already on main):** `qr-cal-ronin.svg`, `qr-cal-rory.svg`,
  `kustomization.yaml` includes both. **Don't touch the assets — just reference them.**

## 1. Why · [R]
Walk-up phone buy-in: when the drawer opens, the user sees QR cards they can scan to
subscribe to the kids' calendars on their phone in one tap (`webcal://` → iOS prompts
"Subscribe to Calendar?").

## 2. Outcomes · [R]
1. Inside the previously-empty `<aside class="drawer">`, a single section is rendered:
   a `<div class="drawer-section">` with a header **"Connect"** and a subhead
   *"Scan to subscribe on a phone"*.
2. Inside that section, two `<div class="qr-card">` elements:
   - Ronin's: shows `<img src="/qr-cal-ronin.svg" alt="Ronin's calendar QR">`, a label
     "Ronin's calendar", a short instruction line, and the literal URL
     `webcal://n8n-hook.mtgibbs.dev/webhook/cal-ronin-dd5bef4b-4b18-4965-96af-c0b26117ee4a`
     in readable text below.
   - Rory's: same shape with `/qr-cal-rory.svg` and the literal Rory webcal URL.
3. The drawer's content lives inside the existing `.drawer` aside (do NOT change the
   aside's class, attributes, or position — just fill it).
4. Existing UI (acks, menu, lanes, art-mode, feed) is untouched.

## 3. Entities · [E]
Stateless — pure markup + CSS.

## 4. Approach · [A]
Add the section markup inside `<aside class="drawer">…</aside>`. Add a handful of CSS
rules for `.drawer-section`, `.qr-card`, and the URL line. Mirror the existing `.widget`
visual rhythm (rounded corners via `var(--r)`, padding, gradient bg already on `.drawer`
from L1).

## 5. Scope · [S]
**In scope:** `index.html` — drawer content markup + a few CSS rules.
**Out of scope:** L1/L2/L3 work (assume those are committed). The QR SVG files and the
kustomization entries are already on main — do not touch them. Don't touch any other
file, any other section of `index.html`.

## 6. Prior decisions / facts · [S]
- QR images at runtime paths `/qr-cal-ronin.svg` and `/qr-cal-rory.svg` (served by the
  board's nginx from the ConfigMap).
- **Literal URLs** to render as readable text under each QR (copy verbatim):
  - `webcal://n8n-hook.mtgibbs.dev/webhook/cal-ronin-dd5bef4b-4b18-4965-96af-c0b26117ee4a`
  - `webcal://n8n-hook.mtgibbs.dev/webhook/cal-rory-d4ba8436-1a91-46e8-ad42-d3a13c85f56e`
- Render QR images ~**180px** square (use `width: 180px; height: 180px;` on the `<img>`
  or its wrapper). White background behind the image so the QR contrasts at any device
  rotation.
- The instruction line goes between the label and the URL — recommended copy:
  "Scan with your phone's camera — tap Subscribe."

## 7. Norms · [N]
**Class names (gate greps them):** `drawer-section`, `qr-card`.
**Image src paths (literal):** `/qr-cal-ronin.svg`, `/qr-cal-rory.svg` (root-relative; the
board's nginx serves these from the ConfigMap).
**URL text:** the two literal `webcal://` URLs above must appear as visible text — they
are both the *meaning* of the QR (so a user can also type / share) and the human-readable
fallback.

## 8. Safeguards · [S]
- Don't touch the `<aside class="drawer">` opening/closing tags or its `aria-hidden`
  attribute (L1 set those; L2 flips `aria-hidden` when the drawer opens).
- Don't add JavaScript in this sub-spec. The drawer's open/close behavior already works
  from L2/L3.
- Don't touch the QR SVG files or `kustomization.yaml` — those are already on main.
- Existing UI behaviors invariant.

## 9. Task breakdown · [O]
- **T1.** Inside `<aside class="drawer" aria-hidden="true">…</aside>`, add the
  `<div class="drawer-section">` with the header, subhead, and the two `<div class="qr-card">`
  blocks (Ronin first, Rory second). Each card has: a `<h3>` label, the `<img>` with the
  matching `src`, a short instruction line, and the literal URL in a small monospaced /
  break-anywhere block.
- **T2.** Add a few CSS rules: `.drawer-section { padding: …; }`,
  `.drawer-section h2 { font-family: var(--display); … }`,
  `.qr-card { background: var(--surface); border-radius: var(--r); padding: …; margin-bottom: 14px; }`,
  `.qr-card img { background: white; width: 180px; height: 180px; … }`, and a URL-line
  rule (`font-size: .72em; color: var(--faint); word-break: break-all;`).

## 10. Acceptance criteria (EARS) · [O]
- **AC1** *(ubiquitous)* — `index.html` shall contain a `<div class="drawer-section">`
  *inside* the `<aside class="drawer"…>`.
- **AC2** *(ubiquitous)* — `index.html` shall contain exactly two `<div class="qr-card">`
  elements inside `.drawer-section`.
- **AC3** *(ubiquitous)* — One `qr-card` shall reference `src="/qr-cal-ronin.svg"`; the
  other `src="/qr-cal-rory.svg"`.
- **AC4** *(ubiquitous)* — Both literal `webcal://` URLs (Ronin and Rory) shall appear as
  text in `index.html`.
- **AC5** *(ubiquitous)* — A CSS rule for `.qr-card` and one for `.drawer-section` shall
  exist.
- **AC6** *(ubiquitous — safeguard)* — All L1/L2/L3 anchors remain intact (no rip-out):
  `.shell`, `.drawer`, `.sliver`, `drawerOpen`, `.shell.open`, the keydown handler with
  `A`/`Backquote`/`Escape`, the pointer handlers, the constants, the ack handler.

## 11. Verification · `verify.sh`
STATIC gate; greps markers + safeguard anchors.

## 11b. Loop execution
`scripts/ralph-qwen.sh specs/family-board-drawer-4-connect-content` — dedicated worktree.

## 12. Open questions
None.

## Two-way sync rule
If the muted-but-legible QR contrast or the URL wrap-style looks wrong at the diff gate,
fix the spec first.
