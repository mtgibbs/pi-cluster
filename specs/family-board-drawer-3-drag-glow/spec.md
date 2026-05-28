# Spec: Family Board — Power Drawer · L3 drag mechanics + glow ramp

- **Status:** Planned (3 of 4)
- **Owner:** Matt
- **Constitution:** `specs/constitution.md` (+ `clusters/pi-k3s/family-board/CLAUDE.md`)
- **Touches:** `clusters/pi-k3s/family-board/index.html` (only).
- **Builds on:** L1 scaffold + L2 state/keys (assumes `.shell` / `.drawer` / `.sliver` /
  `drawerOpen` / `.shell.open` already exist).

## 1. Why · [R]
Make the drawer feel **physical** — swipe-from-edge pulls the whole shell left at 1:1
finger speed; release past a threshold snaps open; the sliver glows brighter as the user
drags (the "you've grabbed it" feedback). Reverse-swipe closes from open.

## 2. Outcomes · [R]
1. Three new constants exist: `DRAWER_WIDTH = 360`, `EDGE_ZONE = 32`,
   `COMMIT_THRESHOLD = 0.3`.
2. Unified `pointerdown` / `pointermove` / `pointerup` handlers on the document/window:
   - **CLOSED:** a `pointerdown` whose `clientX > window.innerWidth - EDGE_ZONE` starts a
     drag-open. Other `pointerdown`s do NOT start a drag.
   - **OPEN:** any `pointerdown` (mostly on the shifted `.wrap` area) starts a drag-close.
   - During drag: `.shell` transform follows the finger 1:1 (`translateX(-clamped delta)`);
     the `.sliver` (or `.shell`) takes the `grabbing` class with opacity/glow ramped by
     `min(1, abs(delta) / DRAWER_WIDTH)`.
   - On `pointerup`: commit to open if drag passed `COMMIT_THRESHOLD * DRAWER_WIDTH`,
     else snap back; clear the inline transform; add/remove `.open` on `.shell`.
3. New CSS rule: `.sliver.grabbing { opacity: 1; box-shadow: 0 0 24px var(--gold); }`
   (or `.shell.grabbing .sliver { … }` — either is acceptable).
4. `prefers-reduced-motion`: no glow ramp, no inline transform during drag; the drawer
   still opens/closes via key/tap (L2), but the drag motion is reduced to a snap.

## 3. Entities · [E]
Transient drag state in module scope: `{ dragging: boolean, startX: number, startedOpen: boolean }`.
No persisted entity.

## 4. Approach · [A]
Three unified `pointer*` listeners on the document. `pointerdown` decides whether to
start a drag based on `drawerOpen` and `clientX` proximity to the right edge. `pointermove`
(if `dragging`) updates `shell.style.transform` directly + the `grabbing` class's opacity
factor via a CSS custom property or inline style. `pointerup` decides commit-or-snap-back.
Use `pointercancel` to abort cleanly. Use `setPointerCapture` if needed; otherwise rely
on document-level listeners.

## 5. Scope · [S]
**In scope:** `clusters/pi-k3s/family-board/index.html` — three constants, pointer
handlers, `.sliver.grabbing` (or equivalent) CSS, prefers-reduced-motion adjustments.
**Out of scope:** content inside the drawer (L4); L2's keyboard/tap handlers (already
shipped); the existing main click handler (`// ack toggle`); art-mode; menu; lanes;
anything other than `index.html`.

## 6. Prior decisions / facts · [S]
- L1/L2 already shipped: `.shell` exists, `.drawer` exists, `.sliver` exists, `drawerOpen`
  exists, `.shell.open` CSS exists with `transform: translateX(-360px)`, and `.shell` has
  a `transition: transform .28s var(--pop)`.
- During drag we must **suppress the transition** (otherwise the finger-follow lags). A
  common approach: add a `dragging` class on `.shell` that has `transition: none`. Drop
  it on pointerup so the snap animates.
- `prefers-reduced-motion` block already exists in the CSS (search for it). Add an entry
  that disables `.sliver.grabbing`'s box-shadow / opacity-ramp.

## 7. Norms · [N]
**Constants (literal values pinned):**
- `DRAWER_WIDTH = 360`
- `EDGE_ZONE = 32`
- `COMMIT_THRESHOLD = 0.3`

**Class names:**
- Grabbing state: **`grabbing`** (applied to either `.sliver` or `.shell` — gate accepts
  either selector form).

**Events:** `pointerdown`, `pointermove`, `pointerup` (the Pointer Events API — unified
mouse + touch + pen).

## 8. Safeguards · [S]
- **Edge-zone gating preserved.** A `pointerdown` outside the right `EDGE_ZONE` while
  `drawerOpen` is false must NOT start a drag — this prevents accidental opens when
  someone taps an ack icon, the menu, a lane, etc.
- **Don't break the existing main click handler.** Pointer events at the document level
  must not intercept the bubble-up that `// ack toggle` relies on. The cleanest pattern:
  only `preventDefault` / capture pointer when we actually start a drag (significant
  `clientX` movement OR confirmed edge-zone start); otherwise let the click bubble.
- **Reduced motion respected.**
- **No new external deps.**
- Only `index.html`.

## 9. Task breakdown · [O]
- **T1.** Add constants `DRAWER_WIDTH`, `EDGE_ZONE`, `COMMIT_THRESHOLD` near other
  module-level constants (e.g. near `FEED_URL`/`REFRESH_MS`).
- **T2.** Add a transient drag-state object.
- **T3.** Add `pointerdown` / `pointermove` / `pointerup` (+ `pointercancel`) listeners
  with the edge-zone / threshold logic above.
- **T4.** Add CSS: `.shell.dragging { transition: none; }`, `.sliver.grabbing { … glow … }`
  (or `.shell.grabbing .sliver { … }`), plus the `prefers-reduced-motion` adjustment that
  disables the glow ramp.

## 10. Acceptance criteria (EARS) · [O]
- **AC1** *(ubiquitous)* — `index.html` shall declare `DRAWER_WIDTH`, `EDGE_ZONE`, and
  `COMMIT_THRESHOLD` as module-level constants with values `360`, `32`, and `0.3`.
- **AC2** *(state-driven)* — While `drawerOpen` is false and the user's `pointerdown`
  starts within the right `EDGE_ZONE`, a drag-open shall begin. A `pointerdown` elsewhere
  must NOT begin a drag.
- **AC3** *(state-driven)* — While dragging, the `.sliver` (or `.shell`) shall carry the
  `grabbing` class with opacity/glow ramped proportionally to drag distance.
- **AC4** *(event-driven)* — When the drag is released past
  `COMMIT_THRESHOLD * DRAWER_WIDTH`, the shell shall snap to the target state; otherwise
  it shall snap back.
- **AC5** *(ubiquitous)* — A CSS rule for the `grabbing` state (`.sliver.grabbing` or
  `.shell.grabbing`) shall exist with a glow effect (box-shadow + opacity).
- **AC6** *(ubiquitous)* — `prefers-reduced-motion: reduce` shall disable the glow ramp.
- **AC7** *(ubiquitous — safeguard)* — Existing handlers stay intact: keydown (with `A`,
  `Backquote`, `Escape`, typing guard, `poke()`); the `// ack toggle` listener on `main`;
  `.wrap` click-to-close from L2.

## 11. Verification · `verify.sh`
STATIC gate: constants present, pointer events wired, `grabbing` CSS exists with glow,
edge-zone reference in the pointerdown logic, prefers-reduced-motion adjustment, and the
L1/L2 anchors still intact.

## 11b. Loop execution
`scripts/ralph-qwen.sh specs/family-board-drawer-3-drag-glow` — dedicated worktree.

## 12. Open questions
None blocking. (The "which element carries the grabbing class" is left to the executor
between `.sliver` and `.shell` — the gate accepts either.)

## Two-way sync rule
If the loop fails on the gesture logic, capture exactly what tripped (e.g., qwen wired
events on `.shell` not document) in §14 here so the next decomposition learns.
