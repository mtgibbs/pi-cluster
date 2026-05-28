# Spec: Family Board — Power Drawer · L2 state + keys + tap-close

- **Status:** **Archived (never ran)** — see `family-board-drawer-1-scaffold/spec.md` §14 Tuning log for the SDD-overreach lesson that retired L1–L4.
- **Owner:** Matt
- **Constitution:** `specs/constitution.md` (+ `clusters/pi-k3s/family-board/CLAUDE.md`)
- **Design / taste:** `clusters/pi-k3s/family-board/DESIGN.md`
- **Touches:** `clusters/pi-k3s/family-board/index.html` (only).
- **Builds on:** L1 scaffold (assumes `.shell`/`.drawer`/`.sliver` already exist).

## 1. Why · [R]
Make the drawer actually open and close — via **state + `.shell.open` CSS** + **keyboard
toggle** (`` ` `` / `Esc`) + **tap on the shifted main area when open**. No drag gesture
yet (L3 adds that). Visible result: pressing `` ` `` slides the shell over to reveal the
drawer; `Esc` or a tap on the visible main closes it.

## 2. Outcomes · [R]
1. New module-level state: `let drawerOpen = false;`
2. New CSS rule: `.shell.open { transform: translateX(-360px); }` plus a `transition` on
   `.shell` for `transform`.
3. **Pressing the backtick/tilde key** (`event.code === "Backquote"` or `event.key === "\`"`)
   toggles `drawerOpen` → adds/removes `.open` on `.shell` + sets `.drawer`'s
   `aria-hidden` accordingly. **Not** when the user is typing in an input/textarea.
4. **Pressing `Escape`** while `drawerOpen` is true closes the drawer.
5. **Clicking on `.wrap`** (the shifted main area) while `drawerOpen` is true closes the drawer.
6. The existing `A`-key art-mode shortcut, the existing `poke()`, and the existing
   typing-in-input guard all still work.
7. Existing main click handler (`// ack toggle`) is untouched and continues to handle
   ack-seat taps when the drawer is closed.

## 3. Entities · [E]
Stateless UI in terms of persisted data — just a module-level boolean. No schema.

## 4. Approach · [A]
- Add `let drawerOpen = false;` near the other state vars (`viewer`, `acks`, `menu`).
- Add the `.shell.open` CSS rule + a `transition: transform .28s var(--pop)` on `.shell`
  (or `cubic-bezier(.34,1.56,.64,1)` if `--pop` isn't usable for transitions; `--pop` is
  already defined as a cubic-bezier, so it works).
- Add a tiny helper `setDrawer(open)` that flips the state, toggles `.open` on `.shell`,
  flips `.drawer`'s `aria-hidden`. Use it from the key handlers + tap handler.
- **Extend the existing keydown handler** — find it via the `document.addEventListener("keydown"`
  string (it currently handles `a/A` for art mode). Add the Backquote/Escape branches
  **before** the `poke()` fall-through, and *gate* the Backquote branch with the same
  typing-in-input check (`!typing`) so `` ` `` doesn't toggle while typing a meal name.
- Add a click handler on the `.wrap` element (NOT on `main`) that, when `drawerOpen`,
  closes the drawer. This deliberately attaches to `.wrap` and not `main` so it doesn't
  intercept ack-seat clicks (those are delegated on `main` — see the existing
  `// ack toggle` listener).

## 5. Scope · [S]
**In scope:** `clusters/pi-k3s/family-board/index.html` — one CSS rule, one state var, one
helper function, two key-handler branches added inside the existing keydown listener,
and one new `.wrap` click listener.
**Out of scope:** L3's pointer drag + constants + glow. The drawer's *content* (L4).
Everything else in the codebase.

## 6. Prior decisions / facts · [S]
- L1 already added `.shell`, `.drawer`, `.sliver`. Don't redefine them.
- The existing `keydown` handler (search index.html for `document.addEventListener("keydown"`)
  currently does:
  ```js
  document.addEventListener("keydown", e => {
    const typing = e.target.matches && e.target.matches("input, textarea");
    if (!typing && (e.key === "a" || e.key === "A")) { /* art-mode toggle */ return; }
    poke();
  });
  ```
  **Extend it; do not replace.** Add Backquote/Escape branches that respect the same
  `typing` guard (Backquote only; Escape is allowed even while typing because Escape
  closing the drawer is friendly — though tying to `!typing` is also fine, pick one and be
  consistent).
- The existing main click handler (search for `// ack toggle`) is delegated on `main` and
  must not be touched. Drawer tap-close attaches on `.wrap` instead — different element,
  no event-listener collision.

## 7. Norms · [N]
- State var: **`drawerOpen`** (exact name; gate greps it).
- Open class: **`open`** on `.shell` (CSS selector `.shell.open`).
- Helper fn (recommended): **`setDrawer(open)`** — gate is loose on the name; what's
  pinned is *that something* flips `.open` and `aria-hidden`.
- Backquote handling: use either `event.code === "Backquote"` or `event.key === "\`"`.
- Escape handling: `event.key === "Escape"`.
- CSS transition on `.shell`: include `transform` in the transition; the existing `--pop`
  cubic-bezier is fine, or any standard ease.

## 8. Safeguards · [S]
- Existing `A`-key art-mode shortcut **continues to work** (`e.key === "a"` / `"A"`).
- Existing `poke()` is still called for non-handled keys.
- Existing typing-in-input guard (`e.target.matches("input, textarea")`) still applies to
  the `A` shortcut and the new Backquote branch.
- Existing main click listener (`// ack toggle`) is byte-identical.
- No new constants or pointer events in this sub-spec (those are L3).
- No content inside the drawer in this sub-spec (that's L4).

## 9. Task breakdown · [O]
- **T1.** Add `let drawerOpen = false;` near other state vars.
- **T2.** Add CSS: `.shell { transition: transform .28s var(--pop); }` and
  `.shell.open { transform: translateX(-360px); }`.
- **T3.** Add helper that toggles/sets the open state (class + aria-hidden + state var).
- **T4.** Extend the existing `keydown` listener: Backquote (toggle, guarded by `!typing`),
  Escape (close-if-open). **Do not remove or replace the `A` branch or the trailing
  `poke()`.**
- **T5.** Add `document.querySelector(".wrap").addEventListener("click", …)` that closes
  the drawer when `drawerOpen` is true. **Do not** add it to `main` (would collide with
  ack toggle).

## 10. Acceptance criteria (EARS) · [O]
- **AC1** *(ubiquitous)* — `index.html` shall declare `let drawerOpen` (or `const`/`var`
  with that exact name as a module-level binding).
- **AC2** *(ubiquitous)* — `index.html` shall contain a CSS rule for `.shell.open` whose
  declaration includes `transform: translateX(-360px)`.
- **AC3** *(ubiquitous)* — `index.html` shall contain a CSS `transition` on `.shell` that
  includes `transform`.
- **AC4** *(state-driven)* — Pressing `Backquote` (when not typing) shall toggle
  `drawerOpen` and the `.open` class on `.shell`. (The gate greps for a Backquote/`` ` ``
  branch in the keydown handler.)
- **AC5** *(state-driven)* — Pressing `Escape` shall close the drawer when `drawerOpen`.
  (Gate greps for `Escape` in the keydown handler.)
- **AC6** *(state-driven)* — A click on `.wrap` shall close the drawer when `drawerOpen`.
  (Gate greps for a `.wrap` click listener that references `drawerOpen`.)
- **AC7** *(ubiquitous — safeguard)* — The existing `A`-key art-mode shortcut and `poke()`
  fall-through shall be intact in the keydown listener.
- **AC8** *(ubiquitous — safeguard)* — The existing `// ack toggle` click listener on
  `main` shall be intact (byte-identical).
- **AC9** *(ubiquitous — safeguard)* — No new pointer/touch handlers, no
  `DRAWER_WIDTH`/`EDGE_ZONE`/`COMMIT_THRESHOLD` constants, no `.sliver.grabbing` or
  `.shell.grabbing` CSS in this sub-spec (those land in L3).

## 11. Verification · `verify.sh`
STATIC gate; greps for the L2 markers + safeguard anchors + the negative checks for L3 markers.

## 11b. Loop execution
`scripts/ralph-qwen.sh specs/family-board-drawer-2-state-keys` — dedicated worktree.

## 12. Open questions
None.

## Two-way sync rule
If extending the keydown handler turns out to step on something we missed, fix the spec
first.
