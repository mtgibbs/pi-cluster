# Spec: Family Board — Power Drawer · L1 scaffold

- **Status:** **Archived — SDD overreach** (see §14 Tuning log). Drawer hand-built directly on main.
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

## 14. Tuning log — SDD OVERREACH (archived 2026-05-28)

### Outcome
3 attempts failed verify; loop stopped for human. Diff after each attempt was clean
(no commits made; the loop's reset reverted qwen's work). The L2–L4 sub-specs were
**archived without running** alongside this one.

### Why this spec didn't earn its keep
This spec was meant to test the lower bound — "how small can a sub-spec be and still
have the loop reliably one-shot it?" The answer it gave was the **upper bound on
specificity** instead:

- §7 (Norms) pinned every class name (`shell`, `drawer`, `sliver`) **and** the exact CSS
  property values **and** the attribute names (`aria-hidden="true"`).
- The verify gate then grepped for those literal strings — including
  `<div class="shell">` with no attribute-tolerant `[^>]*`.
- §9 (Task breakdown) literally dictated the markup nesting and the three CSS rule
  bodies, character-for-character.

At that level of detail, **the spec IS the source.** The executor's only job is to
re-type what the spec already wrote. The gate then enforces that re-typing happened
*verbatim*, which means any reasonable formatting variation (multi-line CSS instead of
single-line, attribute reordering on a `<div>`, single vs double quotes) reads as a
failure. You're not testing the executor's ability to satisfy a contract — you're
testing whether it can dictate-faithfully.

The user named it plainly: **"if we're building SUUUUUCH a strict outcome, aren't we
basically just coding it already?"** Yes. At this granularity, SDD is two writes for the
price of one, with a fragile gate as the friction tax.

### The pattern that actually held today
The SDD loop won on **behavioral changes** where the gate could test a *contract*:

| Feature | Gate tested | Result |
|---|---|---|
| `family-board-ack-readonly` | seat receives `locked` class when viewer set; click handler refuses locked | ✓ |
| `family-board-auto-ack-stale` v0.1 + v0.2 | SQL `CASE` projects synthesized acks; LEFT JOIN preserved | ✓ |
| `family-board-power-drawer` (monolith) | grab-bag of "implement everything" | ✗ drift |
| **`family-board-drawer-1-scaffold` (this one)** | "Is `<div class="shell">` in the file? Is `width: 360px` in the CSS?" | ✗ over-pinned |

### Lessons banked
1. **Static-grep gates are only suitable when the implementation tokens are intrinsic
   to the behavior** — e.g., `aria-disabled` on a button that *must not* receive focus,
   a SQL `interval '7 days'` that *is* the rule. Class names chosen for the gate's
   convenience cross the line into dictation.
2. **For UI scaffold** (HTML structure + presentational CSS), no static grep can express
   "this renders correctly." A behavioral gate would need a headless browser (Playwright
   etc.) — not justified for a vanilla-single-file kiosk.
3. **The right move when a spec must over-prescribe to be testable is to skip SDD and
   build it directly.** That's what L2–L4 *would* have hit too, just slower.
4. **The decomposition itself wasn't wrong.** Smaller scope helps. But each "tiny task"
   that's pure-typing isn't a SDD win — it's just bureaucracy around an edit.

### Decision
Drawer hand-built directly on main. The 4 sub-spec dirs are preserved as the lesson
artifact (durable, version-controlled — the SDD discipline applied to itself). Future
SDD use targets **behavioral contracts** (database, API, business rules, validation),
not structural UI work.
