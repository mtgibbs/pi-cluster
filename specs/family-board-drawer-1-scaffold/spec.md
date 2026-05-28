# Spec: Family Board — Power Drawer · L1 scaffold

- **Status:** Planned (1 of 4 sub-specs decomposed from the v0.1 monolithic `family-board-power-drawer` that stalled the loop)
- **Owner:** Matt
- **Constitution:** `specs/constitution.md` (+ `clusters/pi-k3s/family-board/CLAUDE.md`)
- **Design / taste:** `clusters/pi-k3s/family-board/DESIGN.md`
- **Touches:** `clusters/pi-k3s/family-board/index.html` (only).
- **Builds on:** nothing — first of the chain. Subsequent: L2 state+keys → L3 drag+glow → L4 connect-content.

## 1. Why · [R]
Foundation for the hidden right-edge "power surface" drawer. This sub-spec ships *just the
structural pieces* (markup + minimal positioning CSS) — a visible 4px gold sliver at the
right edge, and a hidden 360px drawer aside ready to receive content. No gestures, no
state, no JS. Visual proof: the sliver is on the page; the drawer exists in the DOM but
sits offscreen.

## 2. Outcomes (Definition of Done) · [R]
1. The existing `<div class="wrap">…</div>` is wrapped inside a new `<div class="shell">`.
2. After the `.wrap`, a new `<aside class="drawer" aria-hidden="true"></aside>` exists in
   the DOM (empty for now — content lands in L4).
3. A new `<div class="sliver" aria-hidden="true"></div>` exists, fixed to the right edge,
   4px wide, full viewport height, in the gold accent color at baseline opacity.
4. The page renders unchanged at default state (the drawer is offscreen-right; nothing
   visibly shifts; the existing UI is byte-identical visually).
5. Existing behavior (acks, dinner menu, lanes, art mode, feed load) is unaffected.

## 3. Entities · [E]
Stateless UI — no data model. Pure markup + CSS.

## 4. Approach · [A]
Mirror the existing one-file vanilla pattern in `index.html`. The `.shell` is a flexbox
row with `.wrap` (the existing viewport-width container) at index 0 and `.drawer` at
index 1; `.shell` has `overflow-x: hidden` so the drawer is hidden by default. The
`.sliver` is `position: fixed; right: 0; top: 0; bottom: 0; width: 4px;` in
`var(--gold)`. No transitions yet — L2/L3 add those. No JS.

## 5. Scope · [S]
**In scope:** `clusters/pi-k3s/family-board/index.html` — three CSS rules + three small
markup additions (wrap + aside + sliver). One file.
**Out of scope (do NOT touch):** All JS (no state, no event handlers, no constants in
this sub-spec); acks; dinner menu; lanes; art mode; family bar; feed/render; any other
file (yaml, nginx, n8n workflows, dev/).

## 6. Prior decisions / facts the implementer must know · [S]
- Existing top-level layout in `index.html`:
  ```html
  <body>
    <div class="aurora">…</div>
    <div class="grain"></div>
    <div class="wrap">…(masthead, family bar, lanes, board)…</div>
    <div id="sheet" class="sheet" hidden></div>
    <div id="art" aria-hidden="true"></div>
    <div class="idle-hint">touch to wake</div>
    <script>…</script>
  </body>
  ```
  The `<div class="wrap">` is the wrapper we wrap. **Wrap it and ONLY it** — don't touch
  `.aurora`, `.grain`, `#sheet`, `#art`, or `.idle-hint`.
- Existing CSS variables to reuse: `var(--gold)` (the sliver color), `var(--surface)` /
  `var(--bg-2)` (drawer gradient bg, for L1 just a baseline so the drawer isn't pure
  black if briefly visible). `var(--r)` for radius.
- DRAWER_WIDTH = **360** (px). Encode it as the literal `360px` in the L1 CSS for `.drawer`
  width; the JS constant arrives in L3.

## 7. Norms · [N]
**Class names are fixed (gate greps them):**
- Wrapper: `shell`
- Aside: `drawer`
- Edge hint: `sliver`

**CSS shape (be specific so the gate is deterministic):**
- `.shell { display: flex; flex-direction: row; overflow-x: hidden; }`
- `.drawer { width: 360px; min-height: 100vh; background: linear-gradient(180deg, var(--surface), var(--bg-2)); }`
- `.sliver { position: fixed; top: 0; bottom: 0; right: 0; width: 4px; background: var(--gold); opacity: .22; z-index: 4; pointer-events: none; }`

**Accessibility:** `aria-hidden="true"` on both `.drawer` (empty/offscreen) and `.sliver`
(decorative).

## 8. Safeguards · [S]
- The page must look **byte-for-byte identical** at default state — nothing visible shifts;
  the drawer is offscreen-right via `.shell`'s `overflow-x: hidden`.
- Existing UI behaviors are invariant — acks, dinner menu, lanes, art-mode, feed load,
  `quadHTML`, the `A` art-mode shortcut. (Gate greps for their anchors.)
- No JS in this sub-spec. **Do not** add `drawerOpen`, pointer handlers, key handlers,
  click handlers, or any event listener.
- Only `index.html` changes. No other file in the repo.

## 9. Task breakdown · [O]
- **T1 — Scaffold.** In `clusters/pi-k3s/family-board/index.html`:
  1. Wrap `<div class="wrap">…</div>` in `<div class="shell">` (the closing `</div>` of
     `.wrap` is followed by `</div>` for `.shell`, before `<div id="sheet" class="sheet"…>`).
  2. Append `<aside class="drawer" aria-hidden="true"></aside>` *inside* the `.shell`,
     immediately after the `.wrap`'s closing `</div>`.
  3. Append `<div class="sliver" aria-hidden="true"></div>` somewhere top-level inside
     `<body>` (outside `.shell` is fine — it's `position:fixed` so DOM position doesn't
     affect layout, but keep it near `.idle-hint` for proximity-to-overlays).
  4. Add the three CSS rules from §7, near the other layout rules (e.g. close to where
     `.wrap` is defined).

## 10. Acceptance criteria (EARS) · [O]
- **AC1** *(ubiquitous)* — `index.html` shall contain `<div class="shell">` wrapping
  `<div class="wrap">`.
- **AC2** *(ubiquitous)* — `index.html` shall contain `<aside class="drawer"` with
  `aria-hidden="true"`.
- **AC3** *(ubiquitous)* — `index.html` shall contain `<div class="sliver"` with
  `aria-hidden="true"`.
- **AC4** *(ubiquitous)* — The CSS shall include rules for `.shell` (with
  `overflow-x: hidden`), `.drawer` (with `width: 360px`), and `.sliver` (with
  `position: fixed`, `width: 4px`, `var(--gold)`).
- **AC5** *(ubiquitous — safeguard)* — Existing markers shall remain present:
  `function quadHTML`, `id="menu"`, the `// ack toggle` comment, the `A`-key art-mode
  shortcut, the `function render()` (or similar) — none ripped out.
- **AC6** *(ubiquitous — safeguard)* — No JS in this sub-spec: NO new `addEventListener`
  call (existing ones remain), NO `drawerOpen` variable, NO `pointerdown` handler tied to
  the drawer, NO `Backquote`/`Escape` handling tied to the drawer. (L2 + L3 add those.)

## 11. Verification (the harness) — `verify.sh`
STATIC gate. Greps `index.html` for the L1 markers + the safeguard anchors. Visual check
(page looks unchanged; sliver is visible as a thin gold line on the right edge) is the
human diff gate.

## 11b. Loop execution
`scripts/ralph-qwen.sh specs/family-board-drawer-1-scaffold` — one task, fresh context,
**dedicated worktree** per the constitution's "one worktree per agent" rule.

## 12. Open questions
None.

## Two-way sync rule
If L2/L3 reveal that the §7 class/CSS shapes don't compose (e.g., `.shell` needs
`min-height: 100vh` for the gradient to fill), fix the spec first, re-loop.
