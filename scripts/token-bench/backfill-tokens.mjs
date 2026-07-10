#!/usr/bin/env -S node --no-warnings
// backfill-tokens.mjs — repair results.jsonl rows whose token counts recorded
// as 0/null (idle-kill raced opencode's async token flush; the DB has the real
// numbers under the row's session_id). Rewrites results.jsonl in place.
import { readFileSync, writeFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const RESULTS = join(HERE, "results/results.jsonl");
const db = new DatabaseSync(join(process.env.HOME, ".local/share/opencode/opencode.db"), { readOnly: true });
const get = db.prepare(
  "select tokens_input, tokens_output, tokens_reasoning, tokens_cache_read, tokens_cache_write from session where id = ?"
);

const rows = readFileSync(RESULTS, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
let fixed = 0;
for (const r of rows) {
  const empty = !r.tokens_input && !r.tokens_cache_read;
  if (!empty || !r.session_id) continue;
  const s = get.get(r.session_id);
  if (!s || (!s.tokens_input && !s.tokens_cache_read)) continue;
  Object.assign(r, {
    tokens_input: s.tokens_input, tokens_output: s.tokens_output,
    tokens_reasoning: s.tokens_reasoning, tokens_cache_read: s.tokens_cache_read,
    tokens_cache_write: s.tokens_cache_write, backfilled: true,
  });
  fixed++;
}
writeFileSync(RESULTS, rows.map((r) => JSON.stringify(r)).join("\n") + "\n");
console.log(`backfilled ${fixed} rows (of ${rows.length})`);
