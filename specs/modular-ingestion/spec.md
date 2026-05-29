# Spec: Modular Ingestion Architecture (bronze → silver → gold)

> **This template is our REASONS Canvas** — **R**equirements · **E**ntities · **A**pproach ·
> **S**tructure · **O**perations · **N**orms · **S**afeguards — over EARS acceptance criteria
> + a `verify.sh` gate. Sections are ordered constraints-before-work; all seven dimensions
> are present and tagged.

- **Status:** Draft v0.1
- **Owner:** Matt Gibbs
- **Constitution:** `specs/constitution.md` (+ `/CLAUDE.md` Core Mandates)
- **Touches:** `clusters/pi-k3s/n8n/workflows/` (new sink + canvas-poller workflows),
  Postgres in n8n DB (new `intake_raw_events` table), `docs/data-architecture.md` (new),
  `docs/canvas-ingestion.md` (new), `op://pi-cluster/canvas/*` (already minted), n8n
  credentials (new `canvas-api` httpHeaderAuth).

---

## 1. Why · [R — Requirements]

We're going from one ingestion source (forwarded email) to several (Canvas now, future
SMS / Sonarr / RSS / civic feeds). Today's pipeline conflates *receiving*, *normalizing*,
and *projecting* in a single workflow per source. That works for N=1; at N≥3 it produces
duplicated Store/Cleanup/Ping wiring across workflows and — more importantly — **the raw
source data is thrown away** after the LLM extracts the normalized rows.

Two problems compound:

1. **Adding a source means re-implementing the persistence chain**, with the inherent risk
   of drift between sources (one uses the queryReplacement comma-split bug, another doesn't;
   one fires the digest ping, another forgets).
2. **No replay or hydration.** A future "grades dashboard," a smarter Qwen prompt, a
   point-in-time query — none can reconstruct what's not stored. The "current view" is
   the only artifact and it's lossy.

## 2. Outcomes (Definition of Done) · [R — Requirements]

1. A single Postgres table — `intake_raw_events` — holds every source payload verbatim,
   immutable, idempotent on content-hash.
2. A single n8n sub-workflow — **Intake Sink** — owns the silver+gold writes (UPSERT
   `intake_items`, optional batch Cleanup, Ping Digest). Source workflows call it via
   `Execute Workflow`.
3. The **Canvas Poller** is the first dogfood: a scheduled workflow that reads Canvas
   REST per-observee, writes one bronze row per Canvas object, hands normalized rows to
   the Sink. Canvas data lands in `intake_items` with `source_channel='canvas:fultonschools'`
   and appears in the digest highlights.
4. A canonical doc — `docs/data-architecture.md` — names the three tiers, the Sink
   contract, the naming/tag conventions, and shows the topology in one Mermaid diagram.
5. The existing `inbound-mail` workflow continues to function unchanged (refactor to the
   sink is **out of scope** for this spec — see §5).

## 3. Entities · [E — Entities]

### Table: `intake_raw_events` (bronze)

```sql
CREATE TABLE intake_raw_events (
  id              BIGSERIAL PRIMARY KEY,
  received_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  source_channel  TEXT        NOT NULL,
  source_msg_id   TEXT        NOT NULL,
  event_type      TEXT        NOT NULL,
  payload         JSONB       NOT NULL,
  payload_hash    TEXT        NOT NULL,                -- sha256(payload), hex
  attachments_r2  JSONB                                -- [{key, bucket, content_type, bytes}] or null
);
CREATE UNIQUE INDEX intake_raw_idem      ON intake_raw_events (source_channel, source_msg_id, payload_hash);
CREATE        INDEX intake_raw_recent    ON intake_raw_events (source_channel, received_at DESC);
CREATE        INDEX intake_raw_payload   ON intake_raw_events USING gin (payload jsonb_path_ops);
```

- **Immutable.** No workflow `UPDATE`s or `DELETE`s this table outside an explicit
  `ops: redact` workflow (does not exist yet; not in this spec).
- **Idempotent on (source_channel, source_msg_id, payload_hash).** Re-polling Canvas when
  nothing changed = zero new rows.

### Table: `intake_items` (silver) — **unchanged from existing schema**

Existing columns, with the addition (already shipped 2026-05-28) of `action_url` +
`action_target`. No schema changes in this spec.

### Sink contract (the only "API" the system depends on)

The Intake Sink sub-workflow accepts ONE invocation per source event:

```jsonc
// Input (passed via n8n Execute Workflow):
{
  "source_channel": "canvas:fultonschools",       // string, REQUIRED, format §7
  "source_msg_id":  "canvas:assignment:123:456",  // string, REQUIRED, stable per event
  "event_type":     "canvas.assignment",          // string, REQUIRED, format §7
  "payload":        { /* raw verbatim */ },       // object, REQUIRED, JSON-serializable
  "attachments_r2": [                             // array | null, optional
    { "key": "intake/2026-05-29/foo.pdf", "bucket": "intake", "content_type": "application/pdf", "bytes": 12345 }
  ],
  "normalized_rows": [                            // array (may be empty), each row = intake_items shape
    { "type": "assignment", "title": "...", "due_at": "2026-05-30T23:59:59Z",
      "student": "ronin", "action_required": true, "amount": null, "teacher": "...",
      "course": "...", "source_hint": "...", "confidence": 0.95,
      "action_url": null, "action_target": null,
      "item_key": "canvas:assignment:123:456|assignment|ronin|2026-05-30|||..." }
  ],
  "cleanup_msg_group": false                       // bool, default false
}
```

Behavior (in order):

1. `INSERT INTO intake_raw_events (source_channel, source_msg_id, event_type, payload, payload_hash, attachments_r2) VALUES (...) ON CONFLICT (source_channel, source_msg_id, payload_hash) DO NOTHING RETURNING id;`
2. For each `normalized_rows[i]`: UPSERT into `intake_items` using the existing
   single-JSON-param INSERT pattern (`ON CONFLICT (item_key) DO UPDATE`).
3. If `cleanup_msg_group: true`: `DELETE FROM intake_items WHERE source_msg_id = $1 AND
   item_key NOT IN (<provided item_keys>)`.
4. Fire-and-forget `POST /webhook/digest-rebuild` (`executeOnce`, `continueOnFail`,
   5s timeout — mirrors the existing `Ping Digest` from `inbound-mail`).

Output (returned to caller):
```jsonc
{ "raw_id": 12345 | null, "raw_was_new": true|false, "upserted": [<id>, …], "deleted": <int> }
```

## 4. Approach · [A — Approach]

Three tiers, all in Postgres, all wired by n8n:

- **Bronze** = `intake_raw_events`. The "we saw this happen" log.
- **Silver** = `intake_items` (existing). The "current view of the world."
- **Gold** = `board_summaries`, `board_acks`, `board_menu` (existing); future
  `grades_view`, `weekly_brief`, etc. Purpose-built projections.

Sources own only the *receive* and *normalize* steps. **Persistence is centralized in
the Intake Sink** — one workflow, one UPSERT pattern, one digest-ping. Adding a source
means: write the receiver, map to normalized rows, call the Sink. **No new SQL elsewhere.**

The Sink is invoked via n8n's `Execute Workflow` node (in-process, no HTTP hop) for
internal callers. Canvas Poller is a Schedule-triggered workflow. We do not adopt Canvas
Live Events / webhooks (paid/enterprise) — 30-minute polling is sufficient.

> Mirroring patterns: bronze write uses the same single-JSON-param INSERT trick as the
> digest builder's `Insert Summary` (per `feedback` from the comma-split bug). Silver
> upsert mirrors today's `inbound-mail.Store`. Ping mirrors today's `inbound-mail.Ping
> Digest`. There is **nothing structurally new** to test — only composition.

## 5. Scope · [S — Structure: boundary]

### In scope
- New table: `intake_raw_events` (created via inbound-mail's `Ensure Table` extension OR
  the Sink's own ensure step — preference: Sink owns it).
- New n8n workflow: **`silver: intake-sink`** (sub-workflow, Execute Workflow trigger).
- New n8n workflow: **`bronze: canvas-poller`** (Schedule + manual webhook trigger).
- New n8n credential: `canvas-api` (httpHeaderAuth, value from `op://pi-cluster/canvas/api-token`).
- New ExternalSecret in cluster (if needed for syncing the cred — or kept n8n-internal).
- New doc: `docs/data-architecture.md` — diagram + tier rules + Sink contract.
- New doc: `docs/canvas-ingestion.md` — Canvas-specific operator runbook (endpoints
  polled, scheduling, observee mapping, troubleshooting).

### Out of scope
- **Refactoring `inbound-mail` to use the sink.** It works as-is. Refactor is a follow-up
  spec once Canvas proves the sink in production.
- **A `replay` / `reproject` workflow.** Architectural prerequisite (the raw layer) ships
  here; the replay workflow itself is a follow-up spec.
- **Semantic event sourcing** (`AssignmentDueDateChanged` typed events). We store raw
  blobs; future projections can diff blob versions if they need transitions.
- **Multi-tenant support** (multiple families, schools). Single-family is the design point.
- **Canvas grades / submission scores.** First poller is upcoming/missing/announcements
  only. Grades = future spec.
- **Removing the `body` field on `board_summaries` (the legacy markdown).** Renderer still
  uses it; tier-name updates only.
- **Renaming existing workflows** (e.g., `inbound-mail` → `bronze: email-receiver`).
  Conventions apply to NEW workflows in this spec; back-rename is cosmetic and can wait.

## 6. Prior decisions / facts the implementer must know · [S — Structure: system fit & deps]

- **n8n DB host:** `n8n-postgresql.n8n.svc.cluster.local:5432`, db `n8n`, cred id
  `5bzmWi2TWDCyypLQ` (postgres cred named `intake-db`). Bronze table lives in this same DB.
- **Existing n8n workflow ids:** `inbound-mail` = `3dA8CadFdrCw7xrQ`; `feed-api` =
  `XW6Ie2Ui3AOLkjSu`; `digest-builder` = `1oRsTfeaTHKjBcDN`; `digest-api` =
  `Ix9sgTblfHOja8hd`; `intake-admin` = `mBk4ILTo3hoSrnNE`.
- **Existing httpHeaderAuth creds:** `Feed Token` (id `dgqc6ZiNll2avwOb`),
  `litellm-intake` (id `u8zjKkG1zwZt9Vr3`), `inbound-mail-token` (id `5oAV58zdOBeUJXO8`).
  Create a NEW `canvas-api` cred; name pattern: `<source>-api`.
- **Op item:** `op://pi-cluster/canvas/api-url` (text), `op://pi-cluster/canvas/api-token`
  (password). Both populated. Host: `fultonschools.instructure.com`.
- **Canvas REST API quirks:**
  - Pagination: `Link: <…>; rel="next"` header; pass `per_page=100`.
  - Rate limit: `X-Rate-Limit-Remaining` header; respect it. Soft limit, lenient for normal use.
  - Observees endpoint: `GET /api/v1/users/self/observees` returns `[{ id, name, … }]`.
  - Upcoming events: `GET /api/v1/users/self/upcoming_events` — events visible to self; for
    observees use `GET /api/v1/users/:observee_id/upcoming_events` if scope allows, or
    pull per-course from the observee's course list.
  - Missing submissions: `GET /api/v1/users/:user_id/missing_submissions?include[]=planner_overrides`.
  - Calendar events: `GET /api/v1/calendar_events?context_codes[]=user_:id&context_codes[]=course_:id&start_date=…&end_date=…`.
  - Always send `Authorization: Bearer <token>`.
- **Digest rebuild webhook:** `https://n8n.lab.mtgibbs.dev/webhook/digest-rebuild`
  (Header-Auth `Feed Token` — same cred the existing `Ping Digest` uses).
- **n8n queryReplacement bug** (resolved across the pipeline 2026-05-28): use the
  **single-JSON-param pattern** for any INSERT/UPDATE whose row may carry commas in text
  fields. The bronze INSERT MUST use this pattern; do not regress.
- **n8n `Execute Workflow` node** is the path for in-process sub-workflow calls. The Sink
  workflow has an **Execute Workflow Trigger** as its starting node (not Webhook/Schedule).
- **Postgres in n8n is on Postgres 16-alpine** (per memory: `clusters/pi-k3s/n8n/postgresql.yaml`).
  All SQL features (jsonb_path_ops, json_array_elements_text, ALTER TABLE ADD COLUMN IF NOT
  EXISTS) are supported.
- **R2 bucket for attachments:** `intake` (per existing inbound-mail Email Worker). Bronze
  rows carry refs to R2 keys; never blob into Postgres.

## 7. Norms · [N — Norms]

### Workflow naming + tagging (mandatory for new workflows in this spec)

| Tier   | Tag (n8n)  | Workflow name prefix    | Examples                                       |
|--------|------------|-------------------------|------------------------------------------------|
| Bronze | `bronze`   | `bronze: <source>`      | `bronze: canvas-poller`                        |
| Silver | `silver`   | `silver: <function>`    | `silver: intake-sink`                          |
| Gold   | `gold`     | `gold: <function>`      | `gold: digest-api`, `gold: feed-api`           |
| Ops    | `ops`      | `ops: <task>`           | `ops: intake-admin`, `ops: digest-rebuild`     |

Existing workflows are NOT renamed in this spec (see §5). Apply tags retroactively where
trivial; full rename is a cosmetic follow-up.

### `source_channel` format

`<source-type>:<provider-or-id>`

- `intake@mtgibbs.dev` (legacy email; keep as-is for backwards compat with existing rows)
- `canvas:fultonschools`
- Future: `sms:twilio`, `rss:<host>`, `sonarr:home`, etc.

### `event_type` format

`<source-type>.<kind>` — lower-snake_case kinds.

- `email.received`
- `canvas.assignment`, `canvas.announcement`, `canvas.calendar_event`, `canvas.missing_submission`
- Future: `sms.received`, `rss.item`, etc.

### `source_msg_id` format per source

- Email: the message-id header verbatim (`<…@mail.gmail.com>`).
- Canvas: `canvas:<kind>:<course_id>:<object_id>` — e.g., `canvas:assignment:12345:67890`.
- The combination `(source_channel, source_msg_id)` is the stable identity of an event.

### SQL discipline

- All INSERT/UPDATE with text fields that may contain commas → single-JSON-param pattern
  (`={{ JSON.stringify($json) }}` + `$1::json->>'field'`).
- All ADD COLUMN → `ADD COLUMN IF NOT EXISTS`.
- All CREATE INDEX → `IF NOT EXISTS`.

### Observability

- Each Sink invocation logs `raw_id`, `raw_was_new`, `upserted.length`, `deleted` to n8n's
  execution log (Code node `console.log` is enough; no metrics tier in v1).
- Canvas Poller logs the number of pages, items per endpoint, and the next-poll-eligible
  cursor (`updated_after`) if used.

## 8. Safeguards · [S — Safeguards]

- **Bronze is append-only.** No workflow may issue `UPDATE` or `DELETE` against
  `intake_raw_events` except an explicit `ops:` workflow created in a future spec with
  human approval at PR review.
- **Idempotency, content-addressed.** Bronze inserts are gated by the unique index
  `(source_channel, source_msg_id, payload_hash)`. Verify via §11.
- **No secrets in payloads.** Bronze stores source payloads verbatim. Source receivers
  must strip auth headers, cookies, and bearer tokens before handing the payload to the
  Sink. Verify via grep in §11.
- **Sources do NOT write directly to silver or gold tables.** Only the Sink writes silver.
  Only gold-tier workflows write gold tables.
- **R2 refs only — never base64-blob into Postgres.** Bronze's `attachments_r2` carries
  object metadata + R2 key; the bytes stay in R2 (`intake` bucket).
- **Canvas API token never leaves the n8n cred store.** No `Code` node may `console.log`
  the bearer header. No workflow may interpolate the token into a Code node response.
- **Per-source rate limits respected.** Canvas Poller honors `X-Rate-Limit-Remaining`
  (back-off when ≤ 50). Polling cadence: hourly cap of 4 runs (i.e., schedule every 15
  minutes, but back-off pushes effective interval up under load).
- **No destructive writes from the Sink without explicit `cleanup_msg_group: true`.**
  Default behavior is INSERT/UPSERT only. Deletes require explicit caller opt-in.
- **Digest ping is fire-and-forget.** A failed ping must not fail the Sink call
  (`continueOnFail: true`). The hourly digest schedule is the backstop.

## 9. Task breakdown · [O — Operations]

Tasks are ordered. Obey §7 Norms and §8 Safeguards throughout.

1. **DB migration** — `intake_raw_events` table + indexes via the Sink's `Ensure Table`
   step. (Idempotent CREATE IF NOT EXISTS; runs every Sink invocation.)
2. **`silver: intake-sink` workflow** — Execute Workflow Trigger, Ensure Table, Insert
   Raw (single-JSON-param), per-row UPSERT into `intake_items`, optional Cleanup, Ping
   Digest, Respond. Returns `{raw_id, raw_was_new, upserted, deleted}`.
3. **`canvas-api` n8n credential** — httpHeaderAuth named `canvas-api`, header `Authorization`,
   value `Bearer <op://pi-cluster/canvas/api-token>`. Mint via the n8n API.
4. **`bronze: canvas-poller` workflow** — Schedule (every 30 min) + manual webhook `POST
   /webhook/canvas-poll`. Fetches `users/self/observees`, then per-observee fetches
   `upcoming_events` + `missing_submissions`. Per Canvas object: normalize → call Sink
   with one bronze row + one or more silver rows.
5. **First successful Canvas ingest** — manually trigger the poller; verify rows in
   `intake_raw_events` and `intake_items`; verify digest highlights reflect new Canvas
   items.
6. **Docs** — `docs/data-architecture.md` (Mermaid diagram + Sink contract + tier rules);
   `docs/canvas-ingestion.md` (operator runbook). Land on `main` via worktree.
7. **Tag existing workflows** — apply `gold` / `bronze` / `silver` / `ops` tags via n8n
   API to existing workflows (cosmetic; do not rename).

## 10. Acceptance criteria (EARS) · [O — Operations made testable]

- **AC1 (Ubiquitous):** The `intake_raw_events` table shall exist in the n8n Postgres
  database with the columns and indexes specified in §3.
- **AC2 (Ubiquitous):** The `silver: intake-sink` workflow shall exist in n8n and shall
  be invokable via an `Execute Workflow` call from another workflow.
- **AC3 (Event-driven):** When the Sink is called with a payload whose
  `(source_channel, source_msg_id, payload_hash)` already exists, the Sink shall return
  `raw_was_new: false` AND shall not create a duplicate row in `intake_raw_events`.
- **AC4 (Event-driven):** When the Sink completes its writes successfully, the Sink shall
  fire-and-forget a POST to `https://n8n.lab.mtgibbs.dev/webhook/digest-rebuild` with
  the `X-Feed-Token` header from the `Feed Token` cred.
- **AC5 (State-driven):** While the Sink is invoked with `cleanup_msg_group: true`, the
  Sink shall DELETE rows from `intake_items` where `source_msg_id = $msg_id` AND
  `item_key` is NOT IN the set of `normalized_rows[].item_key` provided.
- **AC6 (Unwanted):** If the Canvas API returns a 401/403, the canvas-poller workflow
  shall log the error and exit without writing any bronze or silver rows.
- **AC7 (Unwanted):** If a digest-rebuild POST fails (timeout, non-2xx, network), the
  Sink shall still complete successfully (failure is logged, not propagated).
- **AC8 (Optional):** Where a Canvas object includes an attachment URL, the bronze row's
  `payload` may include the original URL — but no fetch/blob into Postgres in v1.
- **AC9 (Ubiquitous):** The `canvas-poller` workflow shall be tagged `bronze` and its
  name shall start with `bronze: ` per §7. The `intake-sink` shall be tagged `silver`
  and named `silver: intake-sink`.
- **AC10 (Ubiquitous):** A first real Canvas poll shall produce ≥ 1 row in
  `intake_raw_events` with `source_channel = 'canvas:fultonschools'`, and ≥ 1 row in
  `intake_items` with the same `source_channel` (assuming the observee has upcoming
  events or missing submissions).
- **AC11 (Ubiquitous):** No workflow in this spec shall log the value of the Canvas API
  token. Verify by grepping the workflow JSON for the substring `Bearer ` (only allowed
  inside the credential, never inline).

## 11. Verification (the harness) — SHIP A `verify.sh`

STATIC tier (gates each loop iteration; offline + deterministic):

- spec.md exists and contains every required section header (§1–§10, Norms, Safeguards).
- §3 contains the literal table `intake_raw_events`.
- §6 contains the literal cred id `5bzmWi2TWDCyypLQ`.
- §7's `source_channel` format rule is present.
- §10 contains ≥ 10 ACs (AC1..AC10 at minimum).
- §11b loop notes present.
- workflows/ does not contain a `canvas-` JSON yet (this is a *spec*, not an impl).

POST-IMPLEMENTATION (live tier; NOT gated in loop):

- `intake_raw_events` table exists in the n8n Postgres (check via a SELECT through any
  workflow with the postgres cred).
- The Sink workflow id is set (n8n API GET /workflows?tags=silver returns one row whose
  name starts with `silver: intake-sink`).
- The canvas-poller workflow id is set (n8n API GET /workflows?tags=bronze).
- AC3 verified by replaying the same Canvas object twice and observing `raw_was_new: true`
  then `raw_was_new: false`.
- AC11 verified by `grep -r "Bearer " <workflow JSON exports>` returning zero literal
  occurrences outside cred references.

## 11b. Loop execution (handing to a local model)

This spec is **architectural** and crosses workflow boundaries. **Do NOT hand whole-spec
implementation to qwen.** Instead:

- Claude (or a human) designs each n8n workflow JSON and PUTs it via API. The mechanical
  parts (writing the workflow JSON file from scratch) are not yet a clean ralph-loop fit
  because n8n's executions DB is the source of truth, not a file.
- qwen-ralph **could** handle the Mermaid diagram + the docs/data-architecture.md write-up
  as a bounded sub-task — one §9.6 (docs) task per iteration, with a verify.sh that
  checks for the literal headings, code blocks, and a non-empty Mermaid block.
- Each n8n workflow build is a "Claude orchestrates, human reviews PR" task, not a
  ralph-loop task. PR-gated per `feedback_agent_safety_pr_gated`.

## 12. Open questions

- **OQ1.** Per-observee `upcoming_events` may require the parent token to have observer
  scope. We don't know yet if the token works for `/api/v1/users/:observee_id/...` or
  only for `/api/v1/users/self/...` with `as_user_id=:observee_id`. Probe on first run;
  fold the answer into §6.
- **OQ2.** Should the Sink validate that every `normalized_rows[i].item_key` includes
  the `source_msg_id` as its prefix (enforcement of dedup-key shape)? Recommendation:
  yes, throw on violation; documented in Norms. Confirm at impl.
- **OQ3.** Do we want a `source_received_at` column on bronze (when the source claims the
  event occurred, vs `received_at` = when we received it)? Useful for replay accuracy.
  Recommendation: add `source_received_at TIMESTAMPTZ` nullable; populate when the source
  provides it (Canvas does — `updated_at`).
- **OQ4.** Bronze retention. v1 = forever. Revisit if the table crosses 1 GB. Not in
  scope here.

## Two-way sync rule (keep spec ⇄ code aligned)

- **LOGIC change** (Sink contract field added; tier rules change): fix THIS SPEC first,
  then update workflows + docs.
- **REFACTOR** (renaming an existing workflow without changing behavior): change the
  workflow, then sync the new name into §6 prior-facts.
- **HOTFIX** that bypasses the loop: post-mortem into §14 Tuning log + adjust the
  relevant §7 Norm or §8 Safeguard.

## Worked-example checklist (before handing this to an agent)

- [ ] Every linkable target is a LITERAL url/uid, not prose. — see §6.
- [ ] §3 Entities pin literal field names/types (intake_raw_events ✓).
- [ ] §4 Approach names the existing pattern being mirrored
      (digest builder's single-JSON-param INSERT, inbound-mail's Ping Digest) ✓.
- [ ] §7 Norms pull the taste/observability rules that apply ✓.
- [ ] §8 Safeguards state the non-negotiables ✓; each maps to a §11 verify.sh assertion ✓.
- [ ] Novel patterns have a copy-paste example block (the Sink contract JSON) ✓.
- [ ] Where an existing-but-different pattern could mislead (e.g., today's `inbound-mail.Store`
      doing both bronze-equivalent and silver in one workflow), the contrast is called out in §4 ✓.
- [ ] Operational facts the model can't infer are in §6 (cred ids, op paths, hostnames) ✓.
- [ ] Every §10 criterion is testable by §11 ✓.
