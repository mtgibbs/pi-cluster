# Spec: Family Board — read-only acks outside your own marker

- **Status:** Planned (OQs resolved)
- **Owner:** Matt
- **Constitution:** `specs/constitution.md` (+ `clusters/pi-k3s/family-board/CLAUDE.md`)
- **Design / taste:** `clusters/pi-k3s/family-board/DESIGN.md`
- **Touches:** `clusters/pi-k3s/family-board/index.html` (only)

---

## 1. Why · [R]
On the Family Pulse board, the ack quadrant lets each of the four family members mark an
item "seen." When someone enters **their own view** (taps their avatar — the active
*viewer*), they can still tap *anyone's* seat, so Ronin can misclick and mark something as
seen for Julia. In a personal view there's no reason to touch anyone's marker but your own.

## 2. Outcomes (Definition of Done) · [R]
1. In a person's view, only **that person's** ack seat is tappable; the other three can't be toggled by tap or keyboard.
2. The other three seats still **show** who has seen the item — color preserved, just muted.
3. The viewer's own seat is visually obvious as the one live control.
4. The shared (no-viewer) board is **unchanged** — all four seats interactive.
5. Nothing outside the ack quadrant changes behavior.

## 3. Entities · [E]
Stateless UI change — no data model. Relevant in-memory shapes (already exist, do **not**
change them):
- `viewer` — string person id (`julia|matt|ronin|rory`) or `null` (shared board).
- `PEOPLE` — array of `{ id, name, short }`.
- `acks` — `id -> Set(person)`; read via `isSeen(id, person)`.

## 4. Approach · [A]
Mirror the **existing conditional-class pattern already in `quadHTML(id)`** — it appends a
`seen` class per seat based on `isSeen(...)`. Add two more conditional classes the same way,
gated on `viewer`:
- when a viewer is active, the viewer's own seat gets **`mine`**, the other three get **`locked`**;
- when `viewer` is null, neither class is added (current behavior).
Style `.seat.locked` like `.seat.seen` is styled (a sibling CSS rule) but muting via opacity
and disabling interaction; `.seat.mine` adds a highlight ring. Add a guard in the existing ack
click handler. **No new framework, no build step, no new files** — this is a vanilla single-file
edit, consistent with the rest of `index.html`.
*Rejected:* disabling via the HTML `disabled` attribute — it drops the `aria-pressed` state and
focus semantics; use `aria-disabled` + `tabindex="-1"` + `pointer-events:none` + a JS guard.

## 5. Scope · [S]
### In scope
- `clusters/pi-k3s/family-board/index.html`: the `.seat` CSS block, `quadHTML(id)`, and the
  ack click handler (the `document.querySelector("main").addEventListener("click", …)` one).
### Out of scope (do NOT touch)
- The dinner menu widget and its handlers; the family-bar avatar / view-switching handlers;
  the `/api/ack` POST + optimistic/rollback logic; the feed/render/fold logic; any
  `clusters/pi-k3s/family-board/*.yaml`, `nginx.conf.template`, `dev/`, or n8n workflows.

## 6. Prior decisions / facts the implementer must know · [S]
- File: `clusters/pi-k3s/family-board/index.html` — **vanilla HTML/CSS/JS, single file, no
  build/npm.** Ships as a hashed ConfigMap; editing it auto-rolls the pod (deploy is not your job).
- Current `quadHTML(id)` (the seat renderer):
  ```js
  function quadHTML(id) {
    return '<div class="acks"><div class="quad" data-id="'+id+'">' +
      PEOPLE.map(p => {
        const seen = isSeen(id, p.id) ? " seen" : "";
        return '<button class="seat s-'+p.id+seen+'" data-person="'+p.id+'" aria-pressed="'+(seen?'true':'false')+'" aria-label="'+esc(p.name)+'" title="'+esc(p.name)+'">'+p.short+'</button>';
      }).join("") + "</div></div>";
  }
  ```
- `viewer` is the module-level active-viewer var (`let viewer = null;`). `quadHTML` runs inside
  `render()`, which re-runs on every `viewer` change — so reading `viewer` in `quadHTML` is sufficient.
- Existing seat CSS to mirror: `.seat { … cursor: pointer; … }`, `.seat.seen { background: var(--c); … }`,
  per-person hue via `.seat.s-julia { --c: var(--julia); }` (… matt/ronin/rory). `--c` is the person color.
- The ack click handler begins at the comment `// ack toggle (event-delegated, optimistic, …)`
  and matches `const seat = e.target.closest(".seat"); if (!seat) return;`.
- People ids: `julia, matt, ronin, rory`.

## 7. Norms · [N]
- **Class names are fixed (so the gate is deterministic):** non-interactive seats use class
  **`locked`**; the viewer's own seat uses class **`mine`**. Do not invent other names.
- **Color is identity (DESIGN.md):** muting = lower opacity on the whole seat; keep the person
  hue legible at a glance. Do **not** desaturate to gray or drop the color.
- Match the surrounding code style: conditional class strings built the same way as `seen`;
  one-line sibling CSS rules like the other `.seat.*` rules.
- Accessibility: locked seats get `aria-disabled="true"` and `tabindex="-1"`; keep
  `aria-pressed` reflecting seen state. Large touch target unchanged (33px seat).

## 8. Safeguards · [S]
- **No-viewer behavior is invariant:** when `viewer` is null, no seat gets `locked`/`mine` and
  all four remain fully interactive. (Maps to AC5 + verify.)
- **Read-only blocks every activation path**, not just visuals: a `locked` seat must not toggle
  state or call `/api/ack` via tap *or* keyboard. The handler must early-return on `locked`.
- The viewer's own seat keeps the full existing toggle + optimistic-POST + rollback path.
- No secrets, no new network calls, no new dependencies, no files added.
- Touch only the three in-scope regions; leave menu/feed/fold logic byte-for-byte otherwise.

## 9. Task breakdown · [O]
- **T1 — CSS.** Add two sibling rules near `.seat.seen`: `.seat.locked` (mute + disable
  interaction) and `.seat.mine` (highlight ring). Example:
  ```css
  .seat.locked { opacity: .38; pointer-events: none; cursor: default; box-shadow: none; }
  .seat.mine   { box-shadow: 0 0 0 2px var(--text), 0 0 0 4px var(--bg); }
  ```
- **T2 — `quadHTML`.** Add, inside the `PEOPLE.map`: `const lockCls = viewer ? (p.id === viewer ? " mine" : " locked") : "";`
  and append `lockCls` to the seat class list; when locked, also emit `aria-disabled="true" tabindex="-1"`.
- **T3 — ack handler.** As the first line after resolving `seat`, guard:
  `if (seat.classList.contains("locked")) return;`

## 10. Acceptance criteria (EARS) · [O]
- **AC1** *(state-driven)* — While `viewer` is non-null, `quadHTML` shall mark exactly the
  viewer's seat `mine` and the other three `locked`.
- **AC2** *(unwanted)* — If a `locked` seat is activated (tap or key), then the board shall not
  change ack state and shall not call `/api/ack`.
- **AC3** *(ubiquitous)* — Locked seats shall keep their person color and be visually muted
  (reduced opacity), not grayed.
- **AC4** *(state-driven)* — While `viewer` is non-null, the viewer's own seat shall be visually
  highlighted as the live control (`mine`).
- **AC5** *(state-driven)* — While `viewer` is null, all four seats shall be interactive (no
  `locked`/`mine` classes emitted).
- **AC6** *(ubiquitous)* — The change shall affect only the ack quadrant; the dinner menu and
  view-switching shall remain interactive in every state.

## 11. Verification (the harness) — `verify.sh`
STATIC gate (offline, deterministic) in this dir; greps the implementation markers in
`index.html`. It gates each loop iteration. Maps: `.seat.locked`+`.seat.mine` CSS (AC3/AC4),
`quadHTML` viewer-conditional `mine`/`locked` (AC1/AC5), handler `locked` guard (AC2), and
that the menu/feed regions are untouched (AC6, via "no stray edits outside scope" — checked by
the human diff gate). **Visual correctness — muted-but-legible, the highlight looking right — is
the human PR (diff) gate; static greps can't see "looks right."**

## 11b. Loop execution
`scripts/ralph-qwen.sh` against the Beelink qwen executor — one §9 task per iteration, fresh
context (hand it §3–§9 + the seat region of `index.html`, not the whole 850-line file), gated on
`specs/family-board-ack-readonly/verify.sh`, retry-with-feedback, stop-for-human when stuck.
Reviewed at the PR boundary (`coding-agent-ops`).

## 12. Open questions
None blocking — all four decisions resolved with the user (mute-by-opacity keep-color; acks-only
scope; shared board unchanged; highlight the own seat). The exact highlight treatment in T1 is a
sensible default; refine at the human diff gate if it reads wrong (then sync back here).

## Two-way sync rule
Logic change → fix this spec first, regenerate. Refactor → sync the fact back. A taste fix made
at the diff gate (e.g. the `mine` ring) MUST be written back to §9/§7 or the executor repeats the miss.
