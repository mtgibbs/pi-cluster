# Canvas Ingestion — Operator Runbook

> How `bronze: canvas-poller` pulls school data (assignments with due dates, missing
> submissions, announcements) from Canvas LMS into the family pipeline, attributed per
> kid, every 30 minutes. Plus the hard-won Canvas API gotchas — read these before
> changing the poller.

- **Architecture context:** [`docs/data-architecture.md`](./data-architecture.md)
- **Spec:** [`specs/modular-ingestion/spec.md`](../specs/modular-ingestion/spec.md)
- **Workflow:** `bronze: canvas-poller` (n8n id `NJV9pSpi4gerKqqx`)
- **Status:** live 2026-05-29; both kids flowing since fall enrollment 2026-09-16 (Ronin
  `200257` + Rory `472552`). Token migrated to mobile-OAuth capture 2026-09-16 (see
  "Credentials" — manual PATs were disabled by the district).

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

- **1Password:** `op://pi-cluster/canvas` — `api-url` (text), `api-token` (concealed),
  `ronin-canvas-id`, `rory-canvas-id`. The token authenticates as **Julia**, the
  **observer (parent)** account (Canvas user id `240637`).
- **n8n credential:** `canvas-api` (httpHeaderAuth, id `1avasNB9qofVhAG0`) — header
  `Authorization: Bearer <token>`, **domain-scoped** to `fultonschools.instructure.com`.
- Host: `fultonschools.instructure.com`. Summer FV courses live on
  `fultonvirtual.instructure.com` but proxy transparently via the `273100000000…` shard
  prefix — no separate cred needed.

> ⚠️ **The token is a Canvas-for-iOS OAuth token, not a manual PAT** (as of 2026-09-16).
> Fulton County **disabled manual access-token creation in the web UI** — the *only* way
> to mint a token now is through the mobile app's OAuth login. So rotation is no longer a
> point-and-click; it's the capture procedure below. The upside: the resulting token
> reports **Expires: never** in Canvas (Account → Settings → Approved Integrations →
> "Canvas for iOS"), so it lasts until the app is logged out or the integration is
> revoked there.

### Rotating the token (mobile OAuth capture)

Manual PATs are gone, so a new token is sniped from the iOS app's own OAuth login. This
is a legitimate capture of **our own account's** token — but it does hand a MITM proxy a
window onto the phone's traffic, so undo the phone changes afterward.

1. **Proxy up (laptop):** `brew install mitmproxy` once, then run the capture with the
   token-grabber addon (kept at `scripts/canvas/grab_token.py`, mirrored below):
   ```bash
   mitmdump --listen-host 0.0.0.0 --listen-port 8080 -s scripts/canvas/grab_token.py
   ```
2. **Phone onto the proxy:** Settings → Wi-Fi → (network) → Configure Proxy → Manual →
   `<laptop-LAN-IP>:8080`. Safari → `http://mitm.it` → install the **iOS** cert, then
   **Settings → General → About → Certificate Trust Settings** → full-trust it. *(Two
   separate steps — skip the trust toggle and you get TLS errors, no traffic.)*
3. **Log in as Julia:** Canvas web → **Account → QR for Mobile Login**, scan it *with the
   Canvas Parent app*. (The QR itself only drives a web-session login — it can't be
   exchanged for an API token without the app's embedded client secret, which we don't
   have. So the app must do the OAuth; the proxy captures the Bearer it receives.)
4. **The addon writes** the OAuth exchange's `access_token` to **`api_token.txt`** (and the
   full response to `oauth_response.json`) in `$CANVAS_CAPTURE_DIR` (default
   `<tempdir>/canvas-capture`, deliberately outside the repo). Use `api_token.txt` — the
   plain `Authorization: Bearer` header captured off later requests can be a different,
   sso-scoped JWT that 401s against the API. The real API token is ~70 chars; the addon
   already prefers the OAuth token and won't let a stray Bearer clobber it.
5. **Verify before trusting** (structure, not by eyeballing the value):
   ```bash
   TOK=$(op read op://pi-cluster/canvas/api-token)   # or the captured file
   curl -sS -H "Authorization: Bearer $TOK" \
     -H "Accept: application/json+canvas-string-ids" \
     https://fultonschools.instructure.com/api/v1/users/self/observees | jq '[.[].name]'
   ```
   A `200` listing the kids = good. `401 Invalid access token` = wrong token (see step 4).
6. **Store & wire:** `op item edit canvas --vault pi-cluster "api-token=$(cat token_file)"`,
   then update the value in the n8n `canvas-api` credential **in the UI** — the n8n public
   API cannot set a credential's value (create/delete only), and all five Canvas nodes
   reference the credential by id, so one in-place edit fixes them all.
7. **Tear down the phone:** remove the manual proxy and **delete the mitmproxy cert**
   (Settings → General → VPN & Device Management). Don't leave a MITM cert trusted.
8. **Shred** any local token files once they're in 1Password + n8n.

> The `X-Feed-Token` gate on the manual `/webhook/canvas-poll` trigger is unrelated to
> this token — it uses the n8n "Feed Token" credential (`op://pi-cluster/n8n-automation/
> feed-token`). A cold `op read` that returns empty will make that webhook 403 with
> "Authorization data is wrong!" — re-read the token, it's not a credential drift.

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
- **Current-term filter:** `Build Calendar URLs` keeps only courses whose term matches the
  **current academic year, computed at runtime** (drops archived prior-year courses).
  Fulton names terms `YYYY/YYYY+1 - S1…` (e.g. `2026/2027 - S1`); the node derives the
  year and flips it each July:
  ```js
  const startYear = now.getMonth() >= 6 ? now.getFullYear() : now.getFullYear() - 1;
  const ay = `${startYear}/${startYear + 1}`;           // e.g. "2026/2027"
  const cur = courses.filter(c => (c.term||'').includes(ay));
  ```
  > ⚠️ **This was hardcoded to `2025/2026` until 2026-09-16 and it silently rotted at the
  > school-year rollover:** every fall-2026 course fell outside the filter, so
  > `calendar_event_count` went to **0** — no dated assignments reached the board — while
  > announcements and missing-submissions (not term-filtered) kept flowing, so the failure
  > looked partial, not total. A green-ish poll that had quietly stopped delivering the main
  > signal. Reuse the existing `const now` in this node — don't redeclare it.
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

- **Both kids appear as of fall 2026** (2026-09-16): `/users/self/observees` returns
  **Ronin `200257`** and **Rory `472552`**. Rory surfaced automatically the moment his
  fall enrollment opened — the per-observee fan-out maps him by first-name substring in
  `Shape Observees`, no code change needed, exactly as predicted.
- Through summer 2026 only Ronin appeared: Rory was paired at the account level but had no
  current-term enrollment, so Canvas surfaced no observation link. That single-observee
  window was expected, not a bug — worth remembering the next time a kid is between terms.
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
