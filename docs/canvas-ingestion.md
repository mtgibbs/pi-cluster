# Canvas Ingestion — Operator Runbook

> How `bronze: canvas-poller` pulls school data (assignments with due dates, missing
> submissions, announcements) from Canvas LMS into the family pipeline, attributed per
> kid, every 30 minutes. Plus the hard-won Canvas API gotchas — read these before
> changing the poller.

- **Architecture context:** [`docs/data-architecture.md`](./data-architecture.md)
- **Spec:** [`specs/modular-ingestion/spec.md`](../specs/modular-ingestion/spec.md)
- **Workflow:** `bronze: canvas-poller` (n8n id `NJV9pSpi4gerKqqx`)
- **Status:** live 2026-05-29 (Ronin only — see "Roster" below)

---

## What it ingests

Three normalized `type`s, all `source_channel = canvas:fultonschools`, attributed to a
student slot (`ronin` / `rory` / `unknown`):

| `type` | Source endpoint | Meaning | `action_required` |
| :--- | :--- | :--- | :--- |
| `assignment` | `calendar_events?type=assignment` (per course) | dated assignment / quiz | `true` if due in the future |
| `missing` | `users/<observee>/missing_submissions` | overdue & not turned in | always `true` |
| `announcement` | `announcements?context_codes[]=course_<id>` | teacher post to the class | `false` |

`item_key` formats: `canvas:cal_assignment:<course>:<aid>`, `canvas:missing:<course>:<aid>`,
`canvas:announcement:<course>:<id>`.

---

## Credentials & secrets

- **1Password:** `op://pi-cluster/canvas` — `api-url` (text), `api-token` (concealed).
  The token is an **observer (parent) personal access token** — it belongs to **Julia**
  (Canvas user id `240637`).
- **n8n credential:** `canvas-api` (httpHeaderAuth, id `1avasNB9qofVhAG0`) — header
  `Authorization: Bearer <token>`, **domain-scoped** to `fultonschools.instructure.com`.
- Host: `fultonschools.instructure.com`. Summer FV courses live on
  `fultonvirtual.instructure.com` but proxy transparently via the `273100000000…` shard
  prefix — no separate cred needed.

To rotate the token: update `op://pi-cluster/canvas/api-token`, then update the value in
the n8n `canvas-api` credential (the credential is not yet ExternalSecret-synced).

---

## Poller shape

`Schedule(30 min)` + `POST /webhook/canvas-poll` (Header-Auth `Feed Token`) →

```
Get Observees ──▶ Shape Observees ──▶ Get Observee Courses (per-observee, include[]=term)
   ──▶ Collapse Course Map (course_id → slot + name + term)
   ──▶ Build Missing URLs ──▶ Get Missing Submissions (per-observee)
   ──▶ Build Calendar URLs (per current-term course) ──▶ Get Calendar Events (per-course)
   ──▶ Build Ann URL ──▶ Get Announcements
   ──▶ Build Envelopes (missing + calendar + announcements → Sink envelopes)
   ──▶ Real Envelope? ──┬─(true)─▶ Call Sink (silver: intake-sink) ──▶ Summarize ──▶ Respond
                        └─(false, sentinel)──────────────────────▶ Summarize ──▶ Respond
```

- **Per-observee fan-out:** observee IDs come from `/users/self/observees`; courses are
  fetched **per observee** (`/users/<id>/courses`) because that's the only reliable way to
  know which kid a course belongs to (see gotcha #4).
- **Current-term filter:** `Build Calendar URLs` keeps only courses whose term contains
  `2025/2026` (drops the 14 archived 2024-25 courses).
- **Calendar window:** −2 days (grace) → +120 days. Forward-looking on purpose — a wide
  back-window pulls already-done assignments as clutter (`missing_submissions` covers
  "past + not done").
- **Sentinel:** if there's nothing to ingest, `Build Envelopes` emits one `_sentinel` item
  so `Summarize`/`Respond` still fire (no dead air on an empty poll).

The `Summarize` response is the health snapshot:
```jsonc
{ "ok": true, "observees": [...], "course_count": 29, "calendar_event_count": 82,
  "missing_submission_count": 0, "announcement_count": 6, "envelope_count": 88,
  "sink_calls": 88, "new_raw_rows": 0, "upserted_silver_rows": 88 }
```

---

## Running it manually

```bash
TOKEN=$(op read "op://pi-cluster/n8n-automation/feed-token")
curl -sS -X POST "https://n8n.lab.mtgibbs.dev/webhook/canvas-poll" \
  -H "Content-Type: application/json" -H "X-Feed-Token: $TOKEN" -d '{}'
```

Inspect what landed:
```bash
curl -sS -H "X-Feed-Token: $TOKEN" "https://n8n.lab.mtgibbs.dev/webhook/feed" \
  | jq '[.[] | select(.source_channel|startswith("canvas"))] | group_by(.type)
        | map({type: .[0].type, n: length})'
```

---

## Canvas API gotchas (READ BEFORE EDITING)

These cost ~9 iterations to find. Every one is non-obvious.

1. **`planner/items` is the WRONG endpoint for an observer.** Returns `[]` even when the
   kid is actively working, and 403s on wide windows. Don't use it.

2. **Dated assignments come from `calendar_events`, NOT `/assignments`.** The
   `/courses/<id>/assignments` endpoint returns `due_at: null` for self-paced (pace-plan)
   courses. But
   `GET /calendar_events?type=assignment&context_codes[]=course_<id>&start_date=…&end_date=…&per_page=100`
   returns the same assignments **with resolved due dates**. Must be scoped **per-course**
   — the per-*user* form (`context_codes[]=user_<id>`) returns empty for an observer. Each
   event's `start_at` is the due date; `event.assignment` carries points/course_id.

3. **Always send `Accept: application/json+canvas-string-ids`.** Canvas course/assignment
   IDs are 18 digits — beyond JS safe-int. Without this header, n8n's JSON parser truncates
   them (`…2206` → `…2200`), silently breaking every `context_codes[]=course_<id>` query.

4. **`include[]=observed_users` on `/users/self/courses` is always null** (docs lie).
   Fetch **`/users/<observee_id>/courses`** per observee instead — reliable, and it builds
   the `course_id → student-slot` map directly. `enrollment_state=active` is also too
   narrow (current-term only); use `state[]=available`.

5. **n8n PUT silently corrupts a workflow if `connections` references a deleted node.**
   When you remove a node via the API, strip its key from `connections` AND any target
   entries pointing at it — otherwise the PUT "succeeds" but returns `nodes: []` (dead).

6. **`missing_submissions` is the clean "not turned in" signal** — one call per observee
   (`/users/<id>/missing_submissions?filter[]=submittable`). The observer-self variant
   (`/users/self/missing_submissions?observed_user_id=`) **403s** — use the direct
   per-user path.

---

## Roster / enrollment reality

- **Only Ronin appears today.** `/users/self/observees` returns one observee (Ronin,
  `200257`). Rory is paired at the account level but has **no current-term enrollment**, so
  Canvas surfaces no observation link for him. This is expected, not a bug.
- **When Rory enrolls (fall 2026), he appears automatically** — the per-observee fan-out
  maps him by first-name substring in `Shape Observees`; no code change needed.
- Both kids are boys (he/him).

---

## The native `.ics` alternative (for phones)

Canvas gives each user a personal **Calendar Feed** `.ics` URL (Canvas → Calendar →
"Calendar Feed", bottom-right of the sidebar). It's Canvas-hosted, so a phone reaches it
anywhere and it auto-refreshes — better than our LAN-only board for an on-the-go calendar.

- The feed URL is a **UI-only tokenized secret** — it is **not** retrievable via the REST
  API (`/users/self` has no calendar field). You must copy it from the Canvas UI.
- Treat the URL like a password — anyone with it can read the calendar, no login.
- Verified 2026-05-29: Ronin's student feed carries all 82 dated assignments (May 29 –
  Jun 29), matching what the poller ingests. Subscribe (don't import) to keep it live.

> The board/digest pipeline and the native `.ics` are complementary: the `.ics` is the
> phone calendar; the board fuses Canvas with email + dinners + the rest of family life in
> one place.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
| :--- | :--- | :--- |
| `calendar_event_count: 0` but kid has work | wrong endpoint or per-user scope | use `calendar_events` per-course (gotcha #2) |
| course IDs look truncated / announcements empty | missing string-ids header | add `Accept: application/json+canvas-string-ids` (gotcha #3) |
| everything `student: "unknown"` | reading `observed_users` (null) | fetch courses per-observee (gotcha #4) |
| PUT returns `nodes: []` | orphan connection ref | clean `connections` of deleted nodes (gotcha #5) |
| `missing_submissions` 403 | used observer-self+observed_user_id | use `/users/<id>/missing_submissions` direct (gotcha #6) |
| past-due clutter on board | back-window too wide | tighten `Build Calendar URLs` window (currently −2d) |

---

## Future increments (not built)

- **Graded pings** — re-add an activity-stream fetch filtered to "Assignment Graded" for
  the "Ronin got a 95" signal (dropped in v0.8 as noise; the Created/stale items weren't
  worth it).
- **Google Calendar push** (gold writer) — emit dated silver items as real calendar events.
- **inbound-mail → Sink refactor** — fold the email source onto the same Sink contract.
- **Per-student differentiated due dates** — current calendar fetch uses base course dates;
  per-student overrides would need `observed_user_id` resolution.
