# Spec: Extract `original_from` from forwarded emails

- **Status:** **Hand-built after the loop stalled** (3 attempts) — see §14 Tuning log.
- **Owner:** Matt
- **Constitution:** `specs/constitution.md` (+ `clusters/pi-k3s/family-board/CLAUDE.md`)
- **Design / taste:** `clusters/pi-k3s/family-board/DESIGN.md`
- **Touches:**
  - `clusters/pi-k3s/n8n/workflows/inbound-mail.json` (Ensure Table · Build Request jsCode · Parse Records jsCode · Store SQL + queryReplacement)
  - `clusters/pi-k3s/n8n/workflows/src/build-request.js` (readable mirror — keep in sync)
  - `clusters/pi-k3s/n8n/workflows/src/parse-records.js` (readable mirror — keep in sync)
  - `clusters/pi-k3s/n8n/workflows/feed-api.json` (Get Feed)
  - `clusters/pi-k3s/family-board/index.html` (`detailsHTML`)

---

## 1. Why · [R]
Forwarded family emails carry the original school/community sender *inside the body* (e.g.
`From: principal@school.edu` inside a quoted block). Today the intake stores only the
*forwarder* (Matt/Julia) in `source_from` — which is why the board's drill-in dropped its
misleading "Sent by" row. Extracting the original sender lets us put **honest provenance**
back on each card.

This is the resolution of `clusters/pi-k3s/family-board/BACKEND-ASKS.md` **#5**.

## 2. Outcomes (Definition of Done) · [R]
1. New column **`intake_items.original_from TEXT`** (nullable) is added idempotently by
   the existing `Ensure Table` node.
2. The intake LLM extracts an optional **`originalFrom`** field per record; the workflow
   stores it in the new column.
3. `/api/feed` emits `original_from` per item.
4. The board's drill-in shows an **"Originally from"** row when `original_from` is set;
   the row is omitted when null (no dishonest fallback).
5. Existing behaviors invariant — `item_key` formula unchanged; `source_from` still
   stored (it's the forwarder, which is a separate concept and may surface differently
   later); every other column, the upsert semantics, and the cleanup node behavior all
   intact.

## 3. Entities · [E]
- `intake_items.original_from` — `TEXT`, **nullable** (null for direct mail, and for
  forwarded mail where the LLM couldn't parse a `From:` from the body).
- LLM JSON output per record gains optional field `originalFrom: string | null`.

## 4. Approach · [A]
**LLM-extract.** The intake LLM (`qwen3-30b-instruct` via LiteLLM) already reads the full
body to extract the other fields; it's the right place to read forwarded-header blocks
too. They come in many flavors (Gmail's *"---------- Forwarded message ----------"*,
Outlook's *"From: … Sent: … To: …"*, Apple Mail's *"Begin forwarded message:"*), and a
single regex is brittle — let the model recognize them, with the prompt pinning the
output shape. *Considered + rejected:* a deterministic regex parser in a Code node — keep
in reserve as a v0.2 fallback if LLM extraction proves unreliable.

**Insert at the end.** The existing `Store` node uses 15 positional params (`$1..$15`,
`$15 = item_key`). To minimize churn, **append** `original_from` as the new column +
value at position **16** — the existing $1..$15 stay byte-identical.

**Don't change the identity key.** `item_key` is a content-derived hash used as the upsert
key. `original_from` is *metadata*, not identity — its presence or absence shouldn't mint
new rows on re-extraction. The key formula stays unchanged.

## 5. Scope · [S]
### In scope
The five files in the **Touches** section, edited surgically:
- `inbound-mail.json`: append one ALTER statement; append two characters to the SQL
  column list + one $-param + one ON CONFLICT clause; one queryReplacement expression;
  one sentence + one schema field in the prompt; one return-object field.
- `feed-api.json`: one column added to the SELECT list.
- `index.html`: one row added to `detailsHTML`.

### Out of scope (do NOT touch)
- Node graphs (no new nodes, no removed nodes, no connection changes).
- Item-key derivation in `parse-records.js`.
- `Delete Prior` semantics (the workflow already replaces this with the upsert + cleanup
  pair — leave it alone).
- Other workflows (`menu-api.json`, `ack-api.json`, `digest-*.json`, `calendar-ics.json`,
  `reminders-ntfy.json`).
- kustomization, deployment, nginx, Flux config.
- Drawer, ack quadrant, menu widget, art mode, fold logic, feed/render — nothing in
  `index.html` outside `detailsHTML`.

## 6. Prior decisions / facts the implementer must know · [S]
- **Current Ensure Table query** (in `inbound-mail.json`) already does
  `ALTER TABLE intake_items ADD COLUMN IF NOT EXISTS …` for `item_key` and `source_msg_id`,
  followed by `CREATE UNIQUE INDEX IF NOT EXISTS intake_items_itemkey_uq ON intake_items(item_key);`.
  **Mirror the same pattern:** append `ALTER TABLE intake_items ADD COLUMN IF NOT EXISTS original_from TEXT;` **before** the `CREATE UNIQUE INDEX` line so column order in the
  query is consistent.
- **Current Store SQL** (in `inbound-mail.json`'s `Store` node) — fully reproduced for reference:
  ```sql
  INSERT INTO intake_items
    (source_msg_id, type, title, due_at, student, action_required, amount, teacher,
     course, source_hint, confidence, source_channel, source_subject, source_from, item_key)
  VALUES
    ($1, $2, $3, $4::timestamptz, $5, $6::boolean, $7, $8, $9, $10, $11::real, $12, $13, $14, $15)
  ON CONFLICT (item_key) DO UPDATE SET
    type = EXCLUDED.type, title = EXCLUDED.title, due_at = EXCLUDED.due_at,
    student = EXCLUDED.student, action_required = EXCLUDED.action_required,
    amount = EXCLUDED.amount, teacher = EXCLUDED.teacher, course = EXCLUDED.course,
    source_hint = EXCLUDED.source_hint, confidence = EXCLUDED.confidence,
    source_channel = EXCLUDED.source_channel, source_subject = EXCLUDED.source_subject,
    source_from = EXCLUDED.source_from, received_at = now()
  RETURNING id, item_key;
  ```
  And the `queryReplacement` is a comma-separated list of 15 `={{ $json.<field> }}` expressions, in column order.
  **Append** `original_from` at position 16 — column list, `$16` in VALUES, an `original_from = EXCLUDED.original_from` line in the SET clause, and `={{ $json.original_from }}` as the 16th queryReplacement expression. *Don't renumber $1..$15.*
- **Current Parse Records jsCode** (in `inbound-mail.json` `Parse Records` node AND in
  `src/parse-records.js`) returns an object with snake_case field names mapped from the
  LLM's camelCase output. Add: `original_from: r.originalFrom || null,` — once in the
  workflow JSON's `jsCode` and **once in `src/parse-records.js`** (mirror; keep in sync).
- **Current Build Request jsCode** (in `inbound-mail.json` `Build Request` node AND in
  `src/build-request.js`) builds the system prompt with a JSON schema listing the
  expected fields. Add `,"originalFrom":string|null` to that schema and one prose line:
  *"If the body shows the email was forwarded (e.g. a 'From:' header inside a quoted
  block), set originalFrom to that sender's email address; otherwise null."* — in both
  places (mirror).
- **Current Get Feed SELECT** (in `feed-api.json` `Get Feed`) — column list begins:
  `SELECT i.id, i.received_at, i.type, i.title, i.due_at, i.student, i.action_required,
  i.amount, i.teacher, i.course, i.source_hint, i.confidence, i.source_channel,
  i.source_subject, i.source_from, COALESCE(a.acks, '[]'::json) AS acks FROM ...`.
  Insert `i.original_from,` **between `i.source_from,` and `COALESCE(...)`**.
- **`detailsHTML(it)`** in `index.html` currently emits three rows: `Quoted from email`,
  `Email subject`, `Confidence`. Add a fourth row, **between `Email subject` and
  `Confidence`**, only when `it.original_from` is truthy:
  ```js
  if (it.original_from) rows.push('<div class="d-row"><span class="d-lab">Originally from</span><span class="d-val">'+esc(it.original_from)+'</span></div>');
  ```

## 7. Norms · [N]
**Pinned literal markers (the gate greps for these):**
- Column type declaration: `original_from TEXT`
- LLM JSON field (camelCase): `originalFrom`
- Stored / fed field (snake_case): `original_from`
- Upsert clause: `original_from = EXCLUDED.original_from`
- queryReplacement expression: `={{ $json.original_from }}`
- Drill-in label: `Originally from`

**Mirror-keep rule:** any Code-node change to `inbound-mail.json` MUST be reflected in
the matching `src/*.js` file (`parse-records.js` or `build-request.js`) — they're
documentation-grade mirrors of the embedded jsCode and they should not drift.

## 8. Safeguards · [S]
- **Backward compatibility.** The new column is nullable. Pre-existing rows have NULL
  `original_from`. The board treats null as "omit the row" — never falls back to
  `source_from`, never shows a placeholder.
- **`item_key` formula is unchanged.** Confirmed by leaving `src/parse-records.js`'s key
  derivation byte-identical except for the new `original_from` mapping.
- **`source_from` storage is unchanged.** It still captures the forwarder; it's just no
  longer displayed in the drill-in.
- **No node graph changes.** The workflow's nodes, connections, credentials, and the
  cleanup node all stay identical.
- **JSON validity.** Both workflow files remain parseable JSON after the edits.
- **No new dependencies, no new endpoints, no new tables.** Single column add.
- **Only the 5 files listed in §1 are modified.** No `kustomization.yaml`, no
  `nginx.conf.template`, no other workflow, no other CSS/HTML region.

## 9. Task breakdown · [O]
- **T1 — Schema.** In `inbound-mail.json`'s `Ensure Table` node's `query`, append
  `ALTER TABLE intake_items ADD COLUMN IF NOT EXISTS original_from TEXT;` before the
  `CREATE UNIQUE INDEX` line.
- **T2 — LLM prompt.** In `src/build-request.js` AND the matching `Build Request` jsCode
  in `inbound-mail.json`: add `,"originalFrom":string|null` to the JSON schema in the
  system prompt and one sentence describing when to populate it.
- **T3 — Parse records.** In `src/parse-records.js` AND the matching `Parse Records`
  jsCode in `inbound-mail.json`: in the returned object, add
  `original_from: r.originalFrom || null,` near the other snake_case mappings.
- **T4 — Store SQL + bind.** In `inbound-mail.json`'s `Store` node:
  - column list: append `, original_from`
  - VALUES: append `, $16`
  - ON CONFLICT DO UPDATE SET: append `, original_from = EXCLUDED.original_from`
  - queryReplacement: append `,={{ $json.original_from }}`
- **T5 — Feed.** In `feed-api.json`'s `Get Feed` query, add `i.original_from,` between
  `i.source_from,` and `COALESCE(a.acks, '[]'::json) AS acks`.
- **T6 — Board drill-in.** In `index.html`'s `detailsHTML`, push the new
  `<div class="d-row">...Originally from...</div>` row only when `it.original_from` is
  truthy, between the `Email subject` row and the `Confidence` row.

## 10. Acceptance criteria (EARS) · [O]
- **AC1** *(ubiquitous)* — `inbound-mail.json`'s `Ensure Table` query shall contain
  `ADD COLUMN IF NOT EXISTS original_from TEXT`.
- **AC2** *(ubiquitous, mirror)* — `inbound-mail.json` (Build Request jsCode) AND
  `src/build-request.js` shall both contain the token `originalFrom`.
- **AC3** *(ubiquitous, mirror)* — `inbound-mail.json` (Parse Records jsCode) AND
  `src/parse-records.js` shall both contain `original_from: r.originalFrom`.
- **AC4** *(ubiquitous)* — `inbound-mail.json`'s `Store` node shall contain `original_from`
  in its column list AND `$16` in its VALUES AND
  `original_from = EXCLUDED.original_from` in its ON CONFLICT SET AND
  `={{ $json.original_from }}` in its `queryReplacement`.
- **AC5** *(ubiquitous)* — `feed-api.json`'s `Get Feed` query shall contain
  `i.original_from` in its SELECT list, positioned after `i.source_from` and before
  `COALESCE(a.acks`.
- **AC6** *(ubiquitous)* — `index.html` shall contain the string `Originally from`
  inside `detailsHTML` (the row only renders when `it.original_from` is truthy — the gate
  greps the string in the source).
- **AC7** *(ubiquitous, safeguard)* — The `item_key` derivation in `src/parse-records.js`
  shall be unchanged byte-for-byte (gate greps for the exact existing formula).
- **AC8** *(ubiquitous, safeguard)* — `inbound-mail.json` and `feed-api.json` shall
  remain valid JSON.

## 11. Verification (the harness) — `verify.sh`
STATIC gate, deterministic, scoped to the five files. Greps the §7 literal markers and
the safeguard anchors. LIVE-tier (after publish): replay a captured forwarded execution
("Test without re-forwarding") and confirm the resulting `intake_items` row has
`original_from` populated (or NULL when the LLM couldn't parse), and that
`/api/feed` returns the new field — that's the human diff gate.

## 11b. Loop execution
`scripts/ralph-qwen.sh specs/family-board-original-from-extraction` — one bounded task,
fresh context, **dedicated git worktree** per the constitution's "Git discipline — one
worktree per agent" rule. Watchdog 5 min/attempt (the spec touches more files than the
prior small specs — give the model a moment).

## 12. Open questions
None blocking. *Future:* if LLM extraction is unreliable in practice, a v0.2 spec can add
a deterministic regex fallback in a Code node — but only after we see real-world miss
patterns from a few weeks of forwarded mail.

## Two-way sync rule
If the LLM proves inconsistent at this and we add a regex fallback / change the schema /
rename `originalFrom`, fix this spec first and regenerate. Tuning lessons from this run
go in §14 here.

## 14. Tuning log — loop stalled at 5-file behavioral scope (2026-05-28)

### Outcome
3 attempts failed verify; loop stopped for a human. Working tree clean after each reset
(qwen's edits were rolled back; no commits made). All 12 new markers stayed FAIL.
**Hand-built afterward** — the feature ships, this entry banks the lesson.

### Why this spec didn't earn the loop
This was a genuine **behavioral** spec (data-flow plumbing — column add, LLM-prompt
field, parse mapping, upsert bind, feed projection, drill-in row) — exactly the kind we
ran the auto-ack-stale loops on and won. So the failure isn't "SDD doesn't fit
behavioral work."

What broke it was **scope × coordination**:
- **5 files** edited surgically in one fresh-context turn.
- A **mirror-keep rule**: changes to the `Code` node `jsCode` in `inbound-mail.json` must
  also appear in `src/parse-records.js` and `src/build-request.js`. That's *one change,
  two files, must match.*
- The Store SQL edit required **four coordinated changes inside one query string**:
  column list, `VALUES $16`, ON CONFLICT SET, queryReplacement. Editing a long
  parameterized SQL string consistently is a precision task.

Working-spec scores so far:

| spec | files | result |
|---|---|---|
| ack-readonly | 1 | ✓ attempt 2 |
| auto-ack-stale v0.1 / v0.2 | 1 | ✓ attempts 2 / 1 |
| **original-from-extraction** | **5 (with mirror-keep)** | **✗ 3 attempts** |
| power-drawer monolith | 1 (large) | ✗ 3 attempts |
| drawer-L1 scaffold (over-pinned) | 1 (UI) | ✗ 3 attempts |

The clean wins are **1 file, ≤1 cohesive edit**. Above that, the loop pays a
coordination tax bigger than the leverage gained.

### Lesson banked
**SDD/qwen reliable scope, today, is ~1 file, ~1 coordinated edit, behavioral.** Beyond
that — multi-file, mirror-keep, multi-edit-within-one-query — the executor stalls and
hand-building is faster than another loop cycle. Decomposition is *available* (split this
into schema-add, prompt-update, store-bind, feed-projection, board-row — 4-5 sub-loops),
but in this run the user wanted shipping speed, not more loop overhead.

For the next behavioral-but-multi-file spec, two paths to try:
1. **Decompose** to one file per sub-spec (each gate green before the next).
2. **Stay hand-built**, with the spec as the durable record of intent and the gate as
   the post-merge truth check. (Exactly what we did here.)
