# Spec: Family Board — auto-ack items older than 7 days

- **Status:** v0.3 — server synthesis reverted; rule moved to the client (see §14 v0.3 entry)
- **Owner:** Matt
- **Constitution:** `specs/constitution.md` (+ `clusters/pi-k3s/family-board/CLAUDE.md`)
- **Design / taste:** `clusters/pi-k3s/family-board/DESIGN.md`
- **Touches:** `clusters/pi-k3s/n8n/workflows/feed-api.json` (only — one query string).

## 1. Why · [R]
The kitchen wall accumulates items whose *due date* has passed — homework due last week,
events that already happened — and nobody bothered to ack them. Treating anything **whose
`due_at` is more than 7 days in the past** as "everybody's already seen this" makes those
items fold into every viewer's *Seen by you* group → restores focus to what's actually
upcoming, without writing anything to `board_acks` or running scheduled jobs.

> *Why `due_at`, not `received_at`:* forwarded emails carry old content with a *fresh*
> ingestion timestamp — `received_at` lies. The actual deadline/event date is what makes a
> thing old. **Undated items** (`info` / `site-pointer` with `due_at = null`) have no
> calendar notion of "stale" — they are **not auto-acked** by this rule and remain visible
> until manually marked.

## 2. Outcomes (Definition of Done) · [R]
1. `/api/feed` returns `acks: ["julia","matt","ronin","rory"]` for any item where
   `due_at` is **strictly more than 7 days in the past** (regardless of `board_acks`).
2. Items where `due_at` is within the last 7 days, or in the future, return the **real**
   acks from `board_acks` (empty `[]` when none), exactly as today.
3. Items with `due_at IS NULL` (`info` / `site-pointer`) return the **real** acks only —
   they are never auto-synthesized. (SQL `null < anything` is false → the CASE falls
   through to the real-acks branch; no special null-handling code needed.)
4. `board_acks` is **not written** — synthesis is read-time only. Real acks for stale
   items remain in the table untouched (just shadowed by the synthesis).
5. The feed contract is otherwise unchanged — every other column comes through identically.

## 3. Entities · [E]
Read-only query change. Existing entities used (no schema change):
- `intake_items.due_at` — `TIMESTAMPTZ` (**nullable**; `info` / `site-pointer` items have
  no due date). The criterion compares it against `now() - interval '7 days'`; a NULL
  `due_at` makes the comparison false → the CASE falls through to real acks. No
  null-handling code needed.
- `intake_items.received_at` — still present in the SELECT list (returned to the board);
  NOT used as the staleness criterion (it lies about forwarded emails).
- `board_acks(item_id BIGINT, person TEXT CHECK IN ('julia','matt','ronin','rory'))` —
  unchanged, never written by this spec.

## 4. Approach · [A]
Replace the existing `COALESCE(a.acks, '[]'::json) AS acks` projection in the **`Get Feed`**
node's query with a `CASE WHEN … THEN … ELSE COALESCE(…) END AS acks` that synthesizes the
full four-person ack list for stale items, and falls through to the real acks otherwise.
Mirror the existing query shape exactly (whitespace, single-line, no params); only the
`acks` projection changes. The LEFT JOIN to `board_acks` stays — we still need it for the
fresh-items branch.

*Rejected:* a scheduled job that inserts real ack rows for old items (writes to the
canonical table, harder to undo, needs a cron). The read-time synthesis is reversible and
zero-state.

## 5. Scope · [S]
**In scope:** `clusters/pi-k3s/n8n/workflows/feed-api.json` — the `Get Feed` node's
`parameters.query` string. **Only that field.**
**Out of scope (do NOT touch):** every other node (`Feed Webhook`, `Ensure Board Acks`,
`Respond`); every other workflow file (`ack-api.json`, `menu-api.json`, `inbound-mail.json`,
`digest-api.json`, `digest-builder.json`, `calendar-ics.json`, `reminders-ntfy.json`);
the family-board frontend (`index.html`); kustomization / nginx / any YAML.

## 6. Prior decisions / facts the implementer must know · [S]
- The current `Get Feed` query (verbatim — the only thing you change is the `acks` projection):
  ```sql
  SELECT i.id, i.received_at, i.type, i.title, i.due_at, i.student, i.action_required,
         i.amount, i.teacher, i.course, i.source_hint, i.confidence, i.source_channel,
         i.source_subject, i.source_from,
         COALESCE(a.acks, '[]'::json) AS acks
  FROM intake_items i
  LEFT JOIN (
    SELECT item_id, json_agg(person ORDER BY person) AS acks
    FROM board_acks GROUP BY item_id
  ) a ON a.item_id = i.id
  ORDER BY (i.due_at IS NULL), i.due_at
  LIMIT 500;
  ```
- The four person ids, **in alphabetical order** (matches `json_agg(person ORDER BY person)`):
  `julia`, `matt`, `ronin`, `rory`.
- Postgres standard syntax: `now() - interval '7 days'`.
- `due_at` is `TIMESTAMPTZ` and **nullable**; null comparisons evaluate to null → the CASE
  branch is not taken → real acks are used (the intended behavior for undated items). No
  special null guard needed in the SQL.
- The n8n Postgres node executes this query (no params, no `queryReplacement`); the file
  stores it as a single-line string in `parameters.query`. Keep it single-line.

## 7. Norms · [N]
**Use exactly these tokens (the gate greps them):**
- `CASE WHEN i.due_at < now() - interval '7 days' THEN`
- `'["julia","matt","ronin","rory"]'::json`
- `ELSE COALESCE(a.acks, '[]'::json) END AS acks`

(Other equivalent phrasings — `older(...)`, `>=`/`<=` flips, different quoting — fail the
gate by design; specificity is the lever.)

## 8. Safeguards · [S]
- **Read-only:** the change is a query rewrite. No `INSERT`/`UPDATE`/`DELETE`; no schema
  change. `board_acks` is not written.
- **Don't break the LEFT JOIN.** The fresh-items branch still needs real `a.acks`.
- **Don't break the feed contract.** Every other column comes through unchanged; the
  shape of `acks` is still a JSON array of person strings — just synthesized when stale.
- **Single-statement, no-param.** Keep it usable by the existing n8n Postgres `executeQuery`
  node without introducing `queryReplacement` or other config changes.
- **Don't touch other nodes/files.** The diff should be one string change in one node.

## 9. Task breakdown · [O]
- **T1 — Replace the `acks` projection in the `Get Feed` query** in
  `clusters/pi-k3s/n8n/workflows/feed-api.json` with the literal tokens from §7. The
  surrounding `SELECT`/`FROM`/`LEFT JOIN`/`ORDER BY`/`LIMIT` stay byte-identical.

## 10. Acceptance criteria (EARS) · [O]
- **AC1** *(ubiquitous)* — While `i.due_at < now() - interval '7 days'`, the query shall
  project `acks` as the literal JSON `["julia","matt","ronin","rory"]` (the four person
  ids, alphabetical).
- **AC2** *(ubiquitous)* — While `i.due_at IS NULL` OR `i.due_at >= now() - interval '7 days'`,
  the query shall project `acks` as `COALESCE(a.acks, '[]'::json)` (the real value from
  `board_acks`, or empty `[]`). Null `due_at` falls through naturally via SQL three-valued
  logic; no explicit null guard needed.
- **AC3** *(ubiquitous — safeguard)* — The LEFT JOIN to the `board_acks` aggregation shall
  remain intact in the query.
- **AC4** *(ubiquitous — safeguard)* — The other 15 columns in the SELECT and the
  `ORDER BY` / `LIMIT 500` shall be unchanged.
- **AC5** *(ubiquitous — safeguard)* — No node in `feed-api.json` other than `Get Feed`
  shall change. `feed-api.json` shall remain valid JSON.
- **AC6** *(ubiquitous — safeguard)* — No other file in the repo shall be modified.

## 11. Verification (the harness) — `verify.sh`
STATIC gate. Parses `feed-api.json`, extracts the `Get Feed` node's `query`, and greps for
the §7 tokens. Also confirms the LEFT JOIN, the unchanged surrounding columns, the JSON
validity, and that no other node was touched. The LIVE check (after re-import: hit
`/api/feed` and confirm an old item returns all four acks; a recent item returns its real
acks) is the human diff gate.

## 11b. Loop execution
`scripts/ralph-qwen.sh specs/family-board-auto-ack-stale` — one tiny task, fresh context,
run **in a git worktree** (lesson from the drawer eval: prevent the model from wandering
into unrelated untracked files in the main tree). Reviewed at the PR boundary.

## 12. Open questions
None. The 7-day threshold is the explicit ask; future tweaks can adjust the literal here
and re-import. (Anything beyond a number — per-person threshold, configurable via UI —
would be a separate spec.)

## Two-way sync rule
If we later change the threshold or person set, fix this spec first and regenerate, don't
hand-edit the live workflow.

## 14. Tuning log

### v0.2 — 2026-05-28 — criterion corrected: `received_at` → `due_at`
The v0.1 ship (commit `13fd352`) synthesized acks based on
`intake_items.received_at < now() - 7d`. After deploy, the user pointed out that
`received_at` is **just metadata** — forwarded emails carry old content with a *fresh*
ingestion timestamp, so received_at lies about how old a thing actually is. The data
point that matters is **`due_at`** — when the event happens or the thing is owed.

v0.2 swaps the criterion to `due_at`. **Undated items** (`info`/`site-pointer` with
`due_at = null`) are now explicitly *not* auto-acked — they have no calendar notion of
stale; they remain visible until manually ack'd. SQL three-valued logic handles the null
case for free (no explicit guard needed in the CASE).

**Lesson banked for future "what's stale" specs:** identify the *semantic* timestamp
(`due_at`, event date, deadline), not the *ingestion* one — and state the null-handling
behavior explicitly in §3 and §10, even when it falls out of SQL semantics.

*(Live re-deploy of v0.2 follows the same path as v0.1: PUT `feed-api.json` to the n8n API
+ activate. board_acks is still never written.)*

### v0.3 — 2026-05-28 — server synthesis reverted; rule moved to the client
The v0.2 SQL `CASE` synthesized `acks: ["julia","matt","ronin","rory"]` on the server for
stale items. User-reported defect: **the toggle semantics broke.** When someone tapped a
synthesized ack to de-ack, the client's optimistic flip rolled back instantly — because
the toggle endpoint's "delete-if-exists else insert" found no real row, INSERTed one, and
returned `seen:true`. Net effect: the seat blipped and reverted; the user couldn't
override the synthesis. The user also noted that the **all-view** (no viewer) had no
"everyone seen" fold at all — synthesized acks just sat visible, ack'd but stuck.

Root cause: synthesis was conflated with persistence. `board_acks` should be the only
source of truth; "treat stale items as everyone-seen" is a *presentation rule* on the
read side, not a data rewrite. Moved it client-side:

- **Server (`feed-api.json` `Get Feed`):** reverted to `COALESCE(a.acks, '[]'::json) AS acks`.
  `board_acks` is the only ack source.
- **Client (`index.html`):**
  - New `isAutoStale(item)` (`due_at > 7d ago`) and `isEveryoneSeen(item)`.
  - `quadHTML(item)`: for a stale item, **all four seats render as `seen` + `locked`**
    (reusing the locked-seat behavior from the ack-readonly feature). They're visually
    acked-but-muted; the ack-click handler already early-returns on `.locked` so taps do
    nothing → no more blip-and-revert.
  - New `folded(item)` rule: with a viewer → fold what *they* have seen (real or
    synthesized); **without** a viewer → fold what **everyone** has seen (the new
    "Seen by everyone" group covers both real all-four-acked and stale items).
  - `unseenCountFor(person)` excludes stale items (everyone is implicitly caught up).

**Lesson banked for read-time synthesis rules:** if it's a presentation rule, keep it on
the renderer. The server should only own *facts* (what's persisted); synthesized states
mixed into the response confuse write-side semantics. If we ever want this rule for *other*
consumers of the feed, lift it back to a synthesis layer (a view, a separate endpoint) —
don't bake it into the canonical read.
