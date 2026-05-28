# Spec: Family Board — auto-ack items older than 7 days

- **Status:** Planned (OQs resolved)
- **Owner:** Matt
- **Constitution:** `specs/constitution.md` (+ `clusters/pi-k3s/family-board/CLAUDE.md`)
- **Design / taste:** `clusters/pi-k3s/family-board/DESIGN.md`
- **Touches:** `clusters/pi-k3s/n8n/workflows/feed-api.json` (only — one query string).

## 1. Why · [R]
The kitchen wall accumulates stale items that nobody bothered to ack. Treating anything
older than 7 days as "everybody's already seen this" makes those items fold into every
viewer's *Seen by you* group → restores focus to what's actually fresh — without writing
anything to `board_acks` or running scheduled jobs.

## 2. Outcomes (Definition of Done) · [R]
1. `/api/feed` returns `acks: ["julia","matt","ronin","rory"]` for any item where
   `received_at` is older than 7 days (regardless of `board_acks` state).
2. Items with `received_at` within the last 7 days return the **real** acks from
   `board_acks` (empty `[]` when none), exactly as today.
3. `board_acks` is **not written** — synthesis is read-time only. Real acks for stale
   items remain in the table untouched (just shadowed by the synthesis).
4. The feed contract is otherwise unchanged — every other column comes through identically.

## 3. Entities · [E]
Read-only query change. Existing entities used (no schema change):
- `intake_items.received_at` — `TIMESTAMPTZ NOT NULL DEFAULT now()`. Every row has it.
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
- `received_at` is `TIMESTAMPTZ NOT NULL DEFAULT now()` — never null, comparisons are safe.
- The n8n Postgres node executes this query (no params, no `queryReplacement`); the file
  stores it as a single-line string in `parameters.query`. Keep it single-line.

## 7. Norms · [N]
**Use exactly these tokens (the gate greps them):**
- `CASE WHEN i.received_at < now() - interval '7 days' THEN`
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
- **AC1** *(ubiquitous)* — While `i.received_at < now() - interval '7 days'`, the query
  shall project `acks` as the literal JSON `["julia","matt","ronin","rory"]` (the four
  person ids, alphabetical).
- **AC2** *(ubiquitous)* — While `i.received_at >= now() - interval '7 days'`, the query
  shall project `acks` as `COALESCE(a.acks, '[]'::json)` (the real value from `board_acks`,
  or empty `[]`).
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
