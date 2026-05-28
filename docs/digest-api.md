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

### Same-origin via the board (when the proxy is in place)

The board's renderer should call `/api/digest` same-origin and let the board's nginx
proxy inject the token, mirroring `/api/feed` and `/api/ack`. *That proxy entry hasn't
been added to `clusters/pi-k3s/family-board/nginx.conf.template` yet — it's the same
pattern as `/api/feed`. The renderer can stub against the dev mock fixture below until it's wired.*

---

## Shape (the data contract)

```json
{
  "as_of":          "2026-05-28T11:00:00Z",
  "as_of_human":    "Updated Thu, May 28 7:00 AM",
  "window":         "last 24h received + upcoming 7d due",
  "item_count":     7,
  "body":           "**Summer Term begins today, Thursday May 28** — Ronin and Rory …",
  "model":          "qwen3-30b-instruct",
  "prompt_version": "v1"
}
```

| Field            | Type           | Notes for the renderer |
|---|---|---|
| `as_of`          | ISO-8601 UTC   | When this digest was produced. `null` ⇒ none generated yet. |
| `as_of_human`    | string         | Pre-formatted **America/New_York** label. Use as-is for the "Updated ___" line. |
| `window`         | string         | Human description of what was summarized. Optional tooltip. |
| `item_count`     | int            | How many items the LLM saw. Useful as a footer chip ("from 7 items"). |
| `body`           | markdown       | The narrative. Bold + paragraph breaks only — no headings, no bullets. 3-6 short sentences. |
| `model`          | string \| null | Model used (for prompt-version A/B tracking). Display only if you want. |
| `prompt_version` | string \| null | Prompt iteration id (same use). |

### Rendering the markdown

The body is tightly constrained markdown. A minimal renderer is enough:

- `**bold**` → `<strong>` (the most common emphasis)
- `*italic*` → `<em>` (rare; usually not produced)
- blank line → paragraph break
- single newline → soft break (or normalize to space)

If you already use a markdown library, fine — but you don't need one.

### Empty / not-yet-generated state

When no row exists in `board_summaries` yet:

```json
{
  "as_of":         null,
  "as_of_human":   "Not generated yet",
  "window":        "last 24h received + upcoming 7d due",
  "item_count":    0,
  "body":          "No summary yet — the next hourly run will fill this in.",
  "model":         null,
  "prompt_version": null
}
```

Render `body` verbatim, or just collapse the panel — your call.

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

- **Storage:** `board_summaries(id, as_of, body, item_count, time_window, model, prompt_version, created_at)` in the n8n Postgres. Indexed `(as_of DESC)`. History is kept (no rotation yet).
- **Builder workflow:** n8n id `1oRsTfeaTHKjBcDN` ("Digest Builder (board_summaries)"). Triggers: Schedule (hourly) + `POST /webhook/digest-rebuild` (Header-Auth).
- **API workflow:** n8n id `Ix9sgTblfHOja8hd` ("Digest API (read board_summaries)"). `GET /webhook/digest` (Header-Auth) → JSON.
- **LLM:** Qwen3-30B-Instruct via LiteLLM (`https://ai.lab.mtgibbs.dev/v1/chat/completions`, n8n cred `litellm-intake`). Temperature 0.3, max_tokens 600.
- **Token rotation:** see `docs/n8n-email-pipeline.md` (same Feed Token mechanism as the feed API).

## Known limits

- The digest sees `intake_items` rows only — `title`, `source_hint`, dates, `student`. **It does not see full email bodies**, so it's slightly thinner than Gemini's (which has the entire mailbox). Future enhancement: a sibling `intake_email_bodies` table for richer summarization. **Not blocking** the v1 digest.
- An automatic refresh on new inbound mail (so the digest updates within seconds of a forward, not up to an hour) is a planned 1-line addition to the inbound-mail workflow — also not blocking.
