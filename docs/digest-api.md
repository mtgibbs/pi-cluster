# Digest API — synthesized "what's going on" blob

**Status (2026-05-28):** ✅ live end-to-end. First real digest row inserted; `GET /webhook/digest` returns the latest summary. Hourly schedule + on-demand rebuild webhook both active.
**Audience:** the Family Board renderer / `board-designer` agent.

The digest is a **new layer alongside `intake_items`**. `intake_items` is the *ledger* —
every notice, structured, queryable. The digest is the **synthesis** — a 3-6 sentence
narrative ("here's what's going on at home right now") written by Qwen3-30B via LiteLLM,
inspired by Gemini's AI Overview but **produced on write, persisted, and self-hosted**.

---

## Endpoints (LAN-only)

```
GET  https://n8n.lab.mtgibbs.dev/webhook/digest
        Header:  X-Feed-Token: <op://pi-cluster/n8n-automation/feed-token>
        →  the latest synthesized summary (JSON, see Shape)

POST https://n8n.lab.mtgibbs.dev/webhook/digest-rebuild
        Header:  X-Feed-Token: <same>
        →  triggers a fresh build (LLM run + insert). 200 immediately; row lands ~10-30s later.
```

A scheduled trigger runs the builder **hourly on the hour**, so a row is always present
shortly after each top of hour. The rebuild webhook is for on-demand refresh.

The `inbound-mail` workflow **also pings the rebuild webhook after each `Cleanup`** (the
final node) — fire-and-forget, `executeOnce: true`, `continueOnFail: true`. So a new
forward shows up in the digest within ~30 seconds, not "up to an hour" worst-case. If the
ping fails for any reason (digest tier down, etc.) the intake flow is unaffected — the
hourly schedule still catches up.

### Same-origin via the board (when the proxy is in place)

The board's renderer should call `/api/digest` same-origin and let the board's nginx
proxy inject the token, mirroring `/api/feed` and `/api/ack`. *That proxy entry hasn't
been added to `clusters/pi-k3s/family-board/nginx.conf.template` yet — it's the same
pattern as `/api/feed`. The renderer can stub against the dev mock fixture below until it's wired.*

---

## Shape (the data contract)

**Updated 2026-05-28 (v5+):** the digest is now **two fields** — a dateless prose **`lead`**
plus a structured **`highlights[]`** array — so dates can't get misassigned in narrative.
A legacy `body` markdown is still returned (lead + bullet-rendered highlights) for any
client still consuming the markdown blob.

```json
{
  "as_of":          "2026-05-28T13:31:58Z",
  "as_of_human":    "Updated Thu, May 28, 9:31 AM",
  "window":         "last 24h received + upcoming 7d due",
  "item_count":     14,
  "lead":           "Ronin is diving into the new school year with a fresh course and a clear path ahead. The household is settling into the rhythm of required health forms and upcoming milestones …",
  "highlights": [
    {
      "item_id":         12,
      "title":           "Principal Kelly Parker's Retirement",
      "type":            "info",
      "due_at":          "2026-05-29T00:00:00.000Z",
      "when_human":      "Friday, May 29",
      "student":         "unknown",
      "action_required": false,
      "amount":          null,
      "teacher":         null,
      "course":          null
    },
    { "...": "..." }
  ],
  "body":           "<lead> + \n\n- **Friday, May 29** — Principal Kelly Parker's Retirement\n- ...",
  "model":          "qwen3-30b-instruct",
  "prompt_version": "v6-attribution-locked"
}
```

| Field            | Type           | Notes for the renderer |
|---|---|---|
| `as_of`          | ISO-8601 UTC   | When this digest was produced. `null` ⇒ none generated yet. |
| `as_of_human`    | string         | Pre-formatted **America/New_York** label. Use as-is for the "Updated ___" line. |
| `window`         | string         | Human description of what was summarized. Optional tooltip. |
| `item_count`     | int            | How many items the LLM saw. Useful as a footer chip ("from N items"). |
| **`lead`**       | markdown       | **The warm tone-setting narrative — DATELESS.** 2-3 short sentences. No dates, days, times, gendered pronouns, or fabricated attribution. See **Deterministic locks** below. |
| **`highlights`** | array          | **Structured truth.** Each item is an `intake_items` row in the hot window (`due_at` between `-1d` and `+7d`), sorted by `due_at`. Dates are pre-formatted as `when_human` (correct TZ + day-of-week, never invented). Render as chips/cards. |
| `body`           | markdown       | **Legacy** — `lead` + a bullet list of highlights. Use `lead`+`highlights` directly if you can; `body` is for clients that just drop a markdown blob. |
| `model`          | string \| null | Model used (for prompt-version A/B tracking). |
| `prompt_version` | string \| null | Prompt iteration id. Bumps when the prompt or lock rules change. |

### Highlights item shape

| Field            | Type           | Notes |
|---|---|---|
| `item_id`        | int            | Stable id from `intake_items` (React key). |
| `title`          | string         | Headline. |
| `type`           | enum           | `event` \| `due` \| `assignment` \| `site-pointer` \| `info` |
| `due_at`         | ISO-8601 UTC   | The canonical machine date (date-only items at `T00:00:00Z`). |
| `when_human`     | string         | Pre-formatted in **America/New_York**: `"Friday, May 29"` for all-day, `"Friday, May 29 at 7:00 AM"` for timed. **Use as-is** — TZ is already correct and day-of-week is always right. |
| `student`        | enum           | `ronin` \| `rory` \| `both` \| `unknown` |
| `action_required`| bool           | Show a "do something" badge. |
| `amount`         | string \| null | e.g. `"$25"` for `dues`. |
| `teacher`/`course` | string \| null | When extracted (assignments). |

### Rendering the markdown (legacy `body`)

`body` is tightly constrained: `**bold**` only, paragraph breaks via blank lines.
A minimal renderer (`**…**` → `<strong>`, blank line → `<p>`) is enough. If you already
have a markdown library, fine. **Prefer rendering `lead` + `highlights` directly.**

### Empty / not-yet-generated state

When no row exists in `board_summaries` yet:

```json
{
  "as_of":         null,
  "as_of_human":   "Not generated yet",
  "window":        "last 24h received + upcoming 7d due",
  "item_count":    0,
  "lead":          "No summary yet — the next hourly run will fill this in.",
  "highlights":    [],
  "body":          "No summary yet — the next hourly run will fill this in.",
  "model":         null,
  "prompt_version": null
}
```

Render `lead` (or `body`) verbatim, or just collapse the panel — your call.

---

## Deterministic locks — how the lead is kept honest

The lead is LLM-written prose; the LLM is good at tone, bad at facts. So the builder
workflow has a `Validate Digest` node that **rejects any output failing any of four
checks**, and the insert is **fail-closed** — a rejected output **never reaches
`board_summaries`**, so the API keeps returning the **last-good** digest. The schedule
retries hourly; the inbound-mail `Ping Digest` retries on every new forward.

| # | Lock | What it catches | How |
|---|---|---|---|
| 1 | **No date-shape tokens in `lead`** | Any month name, day-of-week, ISO date, `m/d/yyyy`, clock time, or "today"/"tomorrow"/"yesterday". | Regex sweep across 6 patterns. Dates live in `highlights` only. |
| 2 | **No gendered pronouns** | `he`, `him`, `his`, `himself`, `she`, `her`, `hers`, `herself`. | Regex on 8 tokens. Use names or singular `they`. |
| 3 | **Attribution allow-list** | Naming a kid (Ronin/Rory) alone when no item names them as the exclusive `student`; joint mention when the window has no `both`/multi items. | Build Prompt computes `allowed_solo` from items' `student` fields + a `joint_allowed` flag; the validator normalizes joint phrases (`"Ronin and Rory"`, `"both kids"`) → checks remaining solo mentions. |
| 4 | **Fail-closed insert** | Anything caught by 1–3 → `throw` in `Validate Digest` → workflow errors → no row inserted → API keeps serving last-good. | n8n surfaces the violation in the execution log for debugging. |

> **What this means in practice:** the LLM can no longer hallucinate "Friday, May 31" (date),
> "his retirement" (pronoun), "Rory is wrapping up the principal hiring" (attribution drift).
> Highlights' dates come from `intake_items.due_at` directly, formatted server-side in the
> right TZ with the right day-of-week — they can't drift either. The lead is reduced to *vibes*
> the renderer can trust.

### How the inbound extraction supports this

The intake's `Build Request` prompt now anchors relative-date resolution explicitly:

```
EMAIL DATE: 2026-05-28T13:55:27.000Z
EMAIL DATE (ISO): 2026-05-28T13:55:27.000Z
EMAIL DAY: Thursday
```

…with rules: *"this Friday → upcoming Friday from EMAIL DAY"*, *"5th of August (no year) → next August 5"*, etc. So a row's `due_at` reflects the calendar correctly, which means `highlights[].when_human` is honest too.

### Prompt-version history

| Version | What changed |
|---|---|
| `v1`            | Initial body-only digest. Caught fabricating "June 6" deadlines + wrong pronouns. |
| `v2-date-locked`| Added PERMITTED_DATES allow-list to the prompt + a date validator. |
| `v3-tz-fixed`   | Bug: my UTC-midnight detector was a narrow regex; date-only `"2026-04-13"` was being formatted in ET → shifted back a day → permitted_dates was *wrong* → validator passed bogus output. Replaced with `getUTCHours()===0 && getUTCMinutes()===0 && getUTCSeconds()===0`. |
| `v4-pronouns-locked` | Added gendered-pronoun ban + validator. |
| `v5-split-fields`    | **Architectural:** split `body` → dateless `lead` + structured `highlights`. The lead's date validator becomes "no dates at all"; highlights' dates come from `due_at`. |
| `v6-attribution-locked` | Added the attribution allow-list (solo + joint), keyed on items' `student`. |

---

## What goes into the digest (the LLM's input)

The builder selects items where:

```
received_at >= NOW() - INTERVAL '24 hours'
    OR (due_at IS NOT NULL
        AND due_at >= NOW() - INTERVAL '6 hours'
        AND due_at <= NOW() + INTERVAL '7 days')
```

So the digest reflects **what's NEW (last 24h of arrivals)** *plus* **what's COMING UP
(deadlines in the next 7 days)** — even if the latter arrived weeks ago.

System prompt (so you know what to expect in `body`):

> *Output 3-6 short sentences as plain markdown — bold is OK; no headings, no bullets
> unless absolutely needed. Tone: warm, brief, the "you should know" voice. Highlight what is
> NEW (received in the last 24 hours) and what is COMING UP (deadlines in the next 7 days).
> Mention dates in human form ("Thursday May 30", "tomorrow"). Name who is affected (Ronin,
> Rory, or both) when the item makes it clear. Call out anything `action_required`. Do NOT
> invent facts. If the window is empty or nothing material is happening, say so in one warm sentence.*

---

## Design suggestions (take or leave)

- A **"Pulse" panel** near the top of the board: the body markdown as hero copy, `as_of_human`
  underneath in muted type. Conveys *"the board is thinking about today"* even when no
  individual item is new.
- Poll on the same cadence as `/api/feed` — both are cheap reads (the digest reads one row).
- If the empty/null state shows up, collapse the panel; don't show a stub.
- The body comes back with manual line breaks that group sentences — a single block of text
  reads fine; preserving the breaks reads a touch better.

---

## Local dev fixture

Once the dev mock is wired (designer-side decision) the suggested pattern:

- `dev/digest.sample.json` returning the shape above with realistic copy.
- `dev/serve.py` adds `GET /api/digest` → that fixture.
- `DIGEST=dev/empty-digest.json` swap for designing the empty state.

A starter `digest.sample.json` body:

```
**Summer Term begins today, Thursday May 28** — Ronin and Rory should head out with their updated schedules. **Principal Kelly Parker's last day is tomorrow (Friday)** before retirement on June 1. **Two action items this week:** Ronin's **Band Trip Fee ($25) is due Tuesday June 2**, and Rory has overdue library books that need to come home. Nothing else new from school overnight.
```

---

## Backend details (informational)

- **Storage:** `board_summaries(id, as_of, body, item_count, time_window, model, prompt_version, lead, highlights JSONB, created_at)` in the n8n Postgres. Indexed `(as_of DESC)`. History is kept (no rotation yet). `lead` and `highlights` were added 2026-05-28; older rows have `NULL` there but `body` is always populated.
- **Builder workflow:** n8n id `1oRsTfeaTHKjBcDN` ("Digest Builder (board_summaries)"). Triggers: Schedule (hourly) + `POST /webhook/digest-rebuild` (Header-Auth). The Validate Digest node is between LiteLLM and Insert — that's where locks 1-4 enforce.
- **API workflow:** n8n id `Ix9sgTblfHOja8hd` ("Digest API (read board_summaries)"). `GET /webhook/digest` (Header-Auth) → JSON with `lead` + `highlights` + legacy `body`.
- **LLM:** Qwen3-30B-Instruct via LiteLLM (`https://ai.lab.mtgibbs.dev/v1/chat/completions`, n8n cred `litellm-intake`). Lead-only prompt at temperature 0.2, max_tokens 220.
- **Admin endpoint** (new): n8n id `mBk4ILTo3hoSrnNE` ("Intake Admin (delete by ids)"). `POST /webhook/intake-admin` with `{"ids":[…]}` (Header-Auth) → deletes by id, returns the deleted rows. Currently shares the Feed Token cred; mint a separate admin token if you want segregation.
- **Token rotation:** see `docs/n8n-email-pipeline.md` (same Feed Token mechanism as the feed API).

## Known limits

- The digest sees `intake_items` rows only — `title`, `source_hint`, dates, `student`. **It does not see full email bodies**, so it's slightly thinner than Gemini's. Future enhancement: a sibling `intake_email_bodies` table. **Not blocking.**
- **Schema gap — action targets / links.** The extraction can recognize an email address to send to (e.g. `TRMSResidency@…`) or a URL (e.g. a "Bookings" scheduling link), but `intake_items` has no `action_url` / `action_target` column — those values either collapse into `source_hint` or are lost. Highlights inherit this limit. Adding two nullable columns is on the backlog.
- **Soft attribution drift beyond lock 3.** Lock 3 catches *unjustified* solo mentions. The LLM can still narrate the right kids around the wrong items if multiple `student` values are present. The locks reduce mischief; visual review is still the human's last word.
- *(Resolved 2026-05-28)* Automatic refresh on new inbound mail is wired — `inbound-mail` pings the rebuild webhook after `Cleanup`.
- *(Resolved 2026-05-28)* Inbound `Build Request` includes `EMAIL DATE (ISO)` + `EMAIL DAY` as anchors for relative-date resolution (e.g. *"this Friday"*).
