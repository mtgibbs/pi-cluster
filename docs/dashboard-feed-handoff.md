# Dashboard / Smart-Board UI — Backend Handoff Brief

**For:** the agent planning the family display (iPad / smart-board kiosk).
**You are building the RENDERER.** The backend is done and stable — you only **read** an
HTTP JSON feed. Per house philosophy: *the renderer is disposable, the backend is the
product.* Hold no business logic; if the display dies, reflash and lose nothing.

---

## The one endpoint you consume

```
GET  https://n8n.lab.mtgibbs.dev/webhook/feed
```
- **LAN-only** (home network / the wired board). NOT public internet. The board lives on
  the LAN, so this resolves and is reachable there.
- **CORS-open** (`Access-Control-Allow-Origin: *`) — a browser PWA can `fetch()` it directly.
- **Read-only.** No writes/auth yet (see [Constraints](#constraints--what-NOT-to-assume)).
- Returns a **JSON array** of "items" extracted from inbound family email
  (school notices, community flyers, bills, events…). Poll it (e.g. every few minutes).

---

## Item shape (the data contract)

Each array element:

| field | type | meaning / display use |
|---|---|---|
| `id` | int | stable row id (use as React key) |
| `type` | enum | **the router** — see types below; drives how you render the item |
| `title` | string | short human label — the headline |
| `due_at` | ISO-8601 string or `null` | the date/time the item happens or is due. **This powers the calendar/deadline view.** `null` = undated (show in a side list, not the calendar) |
| `student` | `ronin`\|`rory`\|`both`\|`unknown` | who it's for — use for filtering/color-coding |
| `action_required` | bool | needs a human to *do* something (highlight these) |
| `amount` | string or null | for `due` (money) items, e.g. "$25" |
| `teacher` | string or null | for `assignment` items |
| `course` | string or null | for `assignment` items |
| `source_hint` | string or null | the verbatim quote the item was extracted from (good for a "details/why" tooltip) |
| `confidence` | float 0–1 or null | extraction confidence — optionally de-emphasize low values |
| `source_subject` | string | subject of the email it came from (provenance) |
| `source_from` | string | who forwarded/sent it (provenance) |
| `source_channel` | string | the intake address (e.g. `intake@mtgibbs.dev`) |

### `type` values and suggested treatment
- **`event`** — something happening on `due_at` (PTA meeting, term start). → calendar/agenda.
- **`due`** — a deadline, often with `amount` (form due, fee due). → deadline list, emphasize.
- **`assignment`** — schoolwork; has `teacher`/`course`/`student`. → per-student view.
- **`site-pointer`** — "go look at this site/portal" (Canvas, a sign-up). → a "links to check" tile. *(The backend deliberately does NOT auto-fetch these.)*
- **`info`** — FYI, usually `due_at: null` (instructions, flyer titles). → low-priority feed.

### Sample response (real, abridged)
```json
[
  {"id":2,"type":"event","title":"Summer Term Begins","due_at":"2026-05-28T00:00:00.000Z",
   "student":"both","action_required":true,"amount":null,"teacher":null,"course":null,
   "source_hint":"Summer Term Begins: May 28, 2026","confidence":1,
   "source_subject":"Welcome to Summer Term 2026","source_from":"mtgibbs21@gmail.com",
   "source_channel":"intake@mtgibbs.dev"},
  {"id":9,"type":"due","title":"Course Verification & Elective Choice Form Due",
   "due_at":"2026-02-13T00:00:00.000Z","student":"both","action_required":true,
   "amount":null,"source_subject":"TRMS Course Verification","confidence":0.9, ...},
  {"id":15,"type":"site-pointer","title":"Canvas Access Restoration",
   "due_at":"2026-05-27T00:00:00.000Z","student":"both","action_required":true, ...}
]
```

---

## Constraints / what NOT to assume

- **Read-only for now.** There is **no write-back** endpoint yet (no "mark done", no create).
  Don't design flows that require writing — or flag it and we'll add `POST` endpoints.
- **No auth yet.** It's open on the LAN. Don't ship the board anywhere public against it as-is.
- **The feed returns UPCOMING + undated items** (past dates filtered server-side, in progress).
  So you generally don't need to filter out old dates client-side — but be defensive.
- **No dedup guarantees historically** (being fixed). Be tolerant of an occasional repeat;
  keying on `id` is safe.
- **Times are ISO-8601 UTC** (`...Z`). Convert to America/New_York for display.
- **`student` may be `unknown`** when the email didn't make it clear. Handle gracefully.

---

## Target device & shape (from the family-board plan)
- First client: **iPad in Safari → Add to Home Screen** (fullscreen standalone PWA). A Pi 5
  touch panel may replace it later — so keep it a **plain responsive web app**, framework-light,
  talking only to this documented API. Large touch targets, landscape + portrait.
- The board is mostly a **display of what phones handle badly** (deadlines/tasks) plus,
  eventually, a quick-add input. For v1, **read + display the feed** is the whole job.

## Good first cut for the UI
A **single board** with: an **agenda/calendar** of `event`+`due`+`assignment` sorted by
`due_at`, deadlines/`action_required` emphasized, a small **"links to check"** strip for
`site-pointer`s, and a low-key **info** list. Color or filter by `student` (ronin/rory/both).

> Questions about the data or wanting more fields/endpoints (filters, write-back, a
> `?from=` window)? Those are quick backend adds — list them and they'll be wired.
