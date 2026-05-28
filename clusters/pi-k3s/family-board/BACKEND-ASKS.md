# Family Board — Backend Asks

> Running list of things the **renderer wants** that are **backend changes** (per the
> board's boundary rule: new fields, write-back, filters, prefs = backend, not faked
> client-side). The frontend prototype stubs these so we can design the feel; this file
> is the handoff to the operator / n8n + feed work to make them real.

Status legend: 🔵 designed-against (stubbed in client) · 🟡 needs decision · 🟢 shipped

---

## 1. Acknowledgement write-back  🔵
**What:** Each item can be marked "seen" by each family member. Four people:
`julia`, `matt`, `ronin`, `rory`. An ack is just **"I've seen this"** — the shallowest
possible signal. No status beyond seen/unseen. Purpose: frictionless self-reporting —
mostly so a person can check *their own* checks, and so others read it as "they've seen it."

**Needs from backend:**
- A place to persist acks: `{ item_id, person_id, seen_at }`. Survives feed refresh and
  is **shared across devices** (the iPad and the future wall panel see the same acks).
- `POST /api/ack` (and an un-ack / toggle) — the board's first write path. Same
  same-origin + nginx-token pattern as `/api/feed`.
- Acks echoed back on the feed (e.g. `acks: ["matt","ronin"]` per item) so a freshly
  loaded board shows current state without a second call.

**Why it matters more now:** the board now **folds away each person's seen items in
their own context** ("tap to be me" → my marked items collapse into a *Seen by you*
fold). For that to feel right across the iPad and the wall panel, acks **must persist
server-side and be echoed on the feed** — otherwise my fold resets every reload and
differs per device.

**Client stub today:** acks live in `localStorage` so the flip-pop + fold are real in
the prototype. This resets per-device and is throwaway — replace with the real write path.

---

## 1b. `received_at` as a documented, stable field  🟡
**What:** Every card now shows a date — `due_at` when present, else **`received_at`** —
so the undated lanes (Good to Know, Read Later) sort newest-first and fold sensibly.
`received_at` is present in the live sample but is **not in the documented data contract**
table (`docs/dashboard-feed-handoff.md`). Please confirm it's stable and add it to the
contract so the renderer can rely on it.

---

## 2. Family roster as first-class people  🟡
**What:** The quadrant is about **people** (Julia, Matt, Ronin, Rory — the whole family),
which is a *different axis* from the feed's existing `student` field (`ronin | rory | both
| unknown`, i.e. *which kid an item is about*). Today the board only learns people by
hardcoding them.

**Needs from backend:** a small roster the board can read — `id`, `display name`, sort
order. Aged ordering is the default: **Julia, Matt, Ronin, Rory**.

**Client stub today:** roster hardcoded in the prototype JS.

---

## 3. Per-person color preference service  🟡
**What:** Let each person pick their own color instead of us assigning it. Defaults
(from the design convo):

| Person | Default color |
|---|---|
| Julia  | green  |
| Matt   | orange |
| Ronin  | blue   |
| Rory   | purple |

**Needs from backend:** persist `person_id -> color`. Tiny key/value; could ride along
with the roster (#2).

**Client stub today:** colors hardcoded as CSS variables.

---

## 4. Dinners menu — a meal TODO  🔵
**What:** A **"On the Menu" side widget** — a simple checklist of dinners (no dates). The
family lists the meals they plan to make and **checks off what they've eaten** (a progress
count: "2 of 5 eaten"). Each meal can carry an optional **recipe link**. *Not* a
Paprika meal-planner sync and *not* a dated calendar — they keep recipes in Paprika's
list, and this is just the running "what's for dinner" list, digitized. The first uneaten
meal shows on the art-mode screen ("Up next for dinner").

**Needs from backend:**
- Persist an ordered list: `[{ id, meal, recipe_url, eaten (bool) }]`. Shared across
  devices (add it on the iPad, check it off on the wall panel).
- Write paths: add a meal, toggle `eaten`, edit/delete. Same same-origin + token pattern.
  This is the **second write surface** after acks (#1) — design them together as one small
  "board state" store.
- **Recipe link is just a URL** the user pastes (Paprika share link, original recipe site,
  anything). The board opens it in a new tab; backend stores it verbatim. No Paprika API
  integration needed for v1. *(One-tap into the Paprika app would be a separate ask once we
  confirm Paprika's per-recipe URL scheme.)*

**Client stub today:** the menu lives in `localStorage`, seeded with demo meals; the
checklist + add-input + edit sheet write there. Throwaway — replace with the real store.

---

## 5. Extract the *original* sender from forwarded emails  🟡
**What:** `intake_items.source_from` today is the `From:` header of whatever email landed
in the intake — which, for forwarded family mail, is the **forwarder** (Matt/Julia), not
the original school/community sender. The board's drill-in had a "Sent by" row that
exposed this misleadingly; it's been removed (2026-05-28) until we can surface the real
originator.

**Needs from backend:** during n8n intake (`inbound-mail.json`), detect forwarded mail
(common markers: `Subject:` begins with `Fwd:` / `FWD:`; body contains a "Begin forwarded
message:" block or an Outlook-style `From: … Sent: … To:` quote header) and parse the
**original `From:`** out of the forwarded body. Store as a **new column**
`intake_items.original_from TEXT` (nullable when we can't parse). Add it to the feed.

**On the board:** when present, the drill-in shows it as **"Originally from"**. When
absent, the row is omitted (don't lie with the forwarder address).

**Why it matters:** lets a viewer tell at a glance whether a notice came from the principal,
the PTA, a teacher, the district office, etc. — which is half the context behind a
"Technical Support Contact"-type info item.

**Client stub today:** none — the row is just hidden. No fallback fakery.

---

## Frontend infra notes (not backend — for the operator/cluster-ops)
- **Self-host the fonts.** The prototype loads Atkinson Hyperlegible + Lexend from Google
  Fonts CDN for speed of iteration. The real kiosk is LAN-only and resilience-first, so
  production should **bundle the font files** into the ConfigMap (no external fetch on
  boot). Flag when we promote a design to `index.html`.

---

## Appendix A — proposed API surface (a starting point for cluster-ops)
All same-origin behind the existing nginx token-proxy pattern; LAN-only; no client auth.

```
GET  /api/feed                      # (exists) JSON array of items
                                    #  → add `acks: ["matt","ronin"]` per item (#1)
                                    #  → confirm/keep `received_at` per item (#1b)

GET  /api/roster                    # [{id,name,order,color}]  (#2 + #3)

POST /api/ack    {item_id, person}  # toggle "person has seen item" (#1)
                                    #  → 200 with new state; idempotent toggle

GET  /api/menu                      # [{id, meal, recipe_url, eaten}]  (#4)
POST /api/menu   {meal, recipe_url} # add → returns the new row
PATCH /api/menu/:id {meal?, recipe_url?, eaten?}
DELETE /api/menu/:id
```

> Acks (#1) and the dinner menu (#4) are the two write surfaces — design them as **one
> small "board-state" store** (sqlite/postgres table or two) behind n8n, rather than two
> bespoke flows. Roster + colors (#2/#3) can be a static config the board reads.

## Appendix B — cutover checklist (prototype → production `index.html`)
1. Port `index-preview.html` → `index.html` (the deployed renderer).
2. **Self-host fonts** (drop the Google CDN `<link>`; add local `@font-face`).
3. Swap each `localStorage` stub for its real endpoint **as it lands**:
   - acks → `POST /api/ack` + read from `feed[].acks`
   - dinner menu → `/api/menu` CRUD
   - roster/colors → `/api/roster` (until then, hardcoded defaults are fine)
4. Operator: add nginx proxy entries for the new `/api/*` paths (token injection).
5. Remove dev-only affordances (e.g. the `A` art-mode keyboard shortcut) if desired.
6. Deploy/verify is the operator/cluster-ops job (hashed ConfigMap auto-rolls the pod).
