# Family Pulse — Design Decisions

> The locked design for the board renderer, captured from the design sessions. The design
> is **implemented in `index.html`** (the deployed renderer); this doc is the source of
> truth for *why*. Backend dependencies live in `BACKEND-ASKS.md`.

## Product framing
- **The renderer is disposable; the backend is the product.** The board reads endpoints
  and renders them. No business logic on the client.
- It is the **"Family Pulse"** — a living, ambient pulse of the family's day, private to
  the home. **Art when idle, a control surface when touched.** It should earn a place on
  the wall.
- Targets: iPad (Safari → Add to Home Screen, fullscreen PWA) first; a wall-mounted Pi
  touch panel later. Landscape **and** portrait. Readable across a kitchen.

## Aesthetic — "hearth at dusk"
- Warm near-black canvas (`#14110d`), **not** a cold dashboard.
- A slow **aurora** of four person-colored blobs breathing underneath everything — *that
  drift is the "pulse."* Plus a faint grain so flats aren't dead. Respects
  `prefers-reduced-motion`.
- **Dyslexia-first type (hard constraint):** Atkinson Hyperlegible for reading, Lexend for
  display numerals. Generous tracking/leading, short line lengths, high contrast.

## The family (roster)
- Four people, **aged order: Julia, Matt, Ronin, Rory.**
- Default colors — **Julia green, Matt orange, Ronin blue, Rory purple.** Per-person color
  choice is a later backend feature (`BACKEND-ASKS.md #3`); these are the defaults.

## Two distinct "who" axes (keep them separate)
1. **Who an item is _about_** — the feed's `student` field (`ronin | rory | both |
   unknown`). Shown as the card's **left edge color + a tag**. (ronin = blue, rory =
   purple, both = "Both kids", unknown = "Whole family?")
2. **Who has _seen_ it** — the **4-person ack quadrant.** Independent of #1.

## Acknowledgement (the heartbeat)
- An ack is the shallowest possible signal: **"I've seen this."** No status beyond
  seen/unseen. Purpose: **frictionless self-reporting** — mostly so a person tracks their
  own checks; others read it as "they've seen it." Does not change anyone's habits.
- UI: **four touchable icons in the card's top-right corner** (2×2, aged order, each their
  color). Tap to toggle with a satisfying **flip-pop**. **No audio.**

## Active viewer — "tap to be me"
- Default: the **shared board** — nothing hidden (the wall view).
- **Tap your avatar → you're the active viewer** (it glows; a note appears). Items **you've
  marked** collapse into a **"Seen by you (N)"** fold at the bottom of each lane — faded,
  one tap to reopen. Tap your avatar again, or let it idle into art mode, to leave.
- **Folding is per-viewer only.** Marking something seen never hides it for anyone else or
  on the shared wall.

## Lanes (the main column)
- **Happening** — dated agenda (`event`/`due`/`assignment`), grouped by day, Today &
  Overdue emphasized, `action_required` highlighted.
- **Good to Know** — `info` + undated items.
- **Read Later** — `site-pointer`s (the backend deliberately does not auto-fetch these).
- **Every card carries a date:** `due_at` when present, else the email's `received_at`.
  Flat lanes sort newest-first.

## Dinners — "On the Menu" (side widget)
- A **meal TODO**, *not* a dated calendar and *not* a Paprika planner sync. The family
  keeps recipes in Paprika's list and plans on paper; this is the running list, digitized.
- A checklist of meals; **check off what you've eaten** (progress: "2 of 5 eaten"). Add via
  an input, edit/delete via a sheet. Each meal has an **optional recipe link** (just a URL
  — Paprika share link or any site — opened in a new tab).
- The first uneaten meal surfaces in art mode as "Up next for dinner."

## Layout
- A **centered content panel (~1140px max) floating on the aurora** — ambient light fills
  the margins; the board does not sprawl across a wall-wide canvas.
- Masthead (wordmark + clock/status) and the **family bar** above; below, a two-column
  **board**: a width-capped **main column (~640px, single-column cards)** + the **menu
  sidebar (~320px)**. Stacks to one column in portrait.

## Time handling (non-negotiable)
- **All-day trap:** items at `T00:00:00.000Z` are date-only — render as that date, never
  time-zone-convert (that shifts them a day back).
- Timed items → **America/New_York**.

## Art / idle mode
- After ~90s untouched: the board fades out; the aurora swells and slows; a **living
  poster crossfades through scenes** (~11s each) — giant clock, "Coming up" next event,
  "Tonight's dinner", the day's pulse ("N need a grown-up") — with the four family orbs
  floating below. Any touch wakes it.

## Resilience & honesty
- **Framework-light, vanilla, single file, no build/npm.** Polls `/api/feed` every 3 min;
  shows last-known data on failure. **Screen Wake Lock** keeps the display awake (paired
  with iOS Auto-Lock = Never).
- **Honest states:** `student: unknown`, `due_at: null`, low `confidence`, and an empty
  feed must all look intentional, never broken.

## Out of scope for the client (→ backend, see BACKEND-ASKS.md)
Ack persistence/sync, the dinners store + writes, the people roster, per-person color
prefs, confirming `received_at` in the contract. Anything requiring a write or a new field
is a backend change — never faked client-side.
