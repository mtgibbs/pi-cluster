#!/usr/bin/env bash
# verify.sh — deterministic acceptance gate for specs/modular-ingestion.
#
# This IS the spec's acceptance criteria (§10) + safeguards (§8) compiled into runnable
# assertions: exit 0 == acceptable. The model never self-certifies "done"; the gate does.
#
# STATIC tier (offline + deterministic) — what's gated every loop iteration:
#   - the spec doc itself contains the required REASONS sections and key literals.
#   - no implementation has snuck into specs/ (this is a spec, not code).
# The LIVE tier (table exists, workflow exists, end-to-end Canvas poll lands rows, etc.)
# is checked post-deploy by a human / via the n8n MCP — listed at the bottom, NOT gated.

set -uo pipefail
ROOT="${ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
SPEC="$ROOT/specs/modular-ingestion/spec.md"
fail=0
ok(){ echo "  PASS  $1"; }
no(){ echo "  FAIL  $1" >&2; fail=1; }

# --- 0. file exists
[ -f "$SPEC" ] && ok "spec exists" || { no "spec exists: $SPEC"; echo "verify: FAIL"; exit 1; }

# --- 1. REASONS sections all present (the canvas dimensions, in our overlay order)
for hdr in \
  "## 1. Why · [R — Requirements]" \
  "## 2. Outcomes (Definition of Done) · [R — Requirements]" \
  "## 3. Entities · [E — Entities]" \
  "## 4. Approach · [A — Approach]" \
  "## 5. Scope · [S — Structure: boundary]" \
  "## 6. Prior decisions / facts the implementer must know · [S — Structure: system fit & deps]" \
  "## 7. Norms · [N — Norms]" \
  "## 8. Safeguards · [S — Safeguards]" \
  "## 9. Task breakdown · [O — Operations]" \
  "## 10. Acceptance criteria (EARS) · [O — Operations made testable]" \
  "## 11. Verification (the harness) — SHIP A " \
  "## 11b. Loop execution"
do
  if grep -Fq "$hdr" "$SPEC"; then ok "section: ${hdr:0:40}…"; else no "missing: $hdr"; fi
done

# --- 2. Key entity names present
for tok in \
  "intake_raw_events" \
  "intake_items" \
  "Intake Sink" \
  "Execute Workflow" \
  "single-JSON-param"
do
  grep -Fq "$tok" "$SPEC" && ok "entity-token: $tok" || no "missing entity-token: $tok"
done

# --- 3. Prior facts pin literal IDs (the model can't invent these)
for lit in \
  "5bzmWi2TWDCyypLQ" \
  "3dA8CadFdrCw7xrQ" \
  "1oRsTfeaTHKjBcDN" \
  "dgqc6ZiNll2avwOb" \
  "fultonschools.instructure.com" \
  "op://pi-cluster/canvas/api-token"
do
  grep -Fq "$lit" "$SPEC" && ok "literal: $lit" || no "missing literal: $lit"
done

# --- 4. Norms / Safeguards key rules present
for rule in \
  "bronze: <source>" \
  "silver: <function>" \
  "gold: <function>" \
  "ops: <task>" \
  "append-only" \
  "Sources do NOT write directly"
do
  grep -Fq "$rule" "$SPEC" && ok "rule: $rule" || no "missing rule: $rule"
done

# --- 5. At least 10 ACs in §10 (EARS contract is the heart)
ac_count=$(grep -cE "^\- \*\*AC[0-9]+ \(" "$SPEC" || echo 0)
if [ "$ac_count" -ge 10 ]; then ok "ACs: $ac_count >= 10"; else no "ACs: $ac_count < 10"; fi

# --- 6. Sink contract example JSON present (a copy-pasteable contract)
grep -Fq '"source_channel":' "$SPEC" \
  && grep -Fq '"normalized_rows":' "$SPEC" \
  && grep -Fq '"cleanup_msg_group":' "$SPEC" \
  && ok "sink-contract JSON example present" \
  || no "sink-contract JSON example incomplete"

# --- 7. Two-way sync rule + checklist present
grep -Fq "Two-way sync rule" "$SPEC" && ok "two-way sync rule present" || no "missing two-way sync rule"
grep -Fq "Worked-example checklist" "$SPEC" && ok "worked-example checklist present" || no "missing checklist"

# --- 8. NO implementation has snuck in (this is a SPEC dir; no workflows JSON here)
if find "$ROOT/specs/modular-ingestion" -type f \( -name "*.json" -o -name "*.yaml" -o -name "*.py" \) -mindepth 1 | grep -q .; then
  no "implementation files snuck into specs/modular-ingestion/ (spec-only dir)"
else
  ok "spec-only dir (no impl files)"
fi

echo
if [ "$fail" -eq 0 ]; then echo "verify: PASS"; else echo "verify: FAIL"; fi
exit "$fail"

# --- LIVE tier (post-implementation; NOT gated here) -----------------------------------
#
# These checks require the cluster + n8n MCP + populated op vault and are run by a human
# or in CI against the live system. They're listed for completeness — NOT executed in the
# static loop gate above. The model never self-certifies these either; the operator does.
#
#  * AC1: `intake_raw_events` table exists in n8n Postgres (check via psql exec or a
#         one-shot SELECT through an n8n Postgres node).
#  * AC2: n8n GET /workflows?tags=silver returns the `silver: intake-sink` workflow.
#  * AC3: Replay the same Canvas object payload twice via the Sink; first call returns
#         raw_was_new=true, second returns raw_was_new=false; bronze row count for that
#         (source_channel, source_msg_id, payload_hash) tuple = 1.
#  * AC4: After a Sink success, an entry appears in digest-builder execution history
#         within 30s of the Sink completing.
#  * AC5: Sink call with cleanup_msg_group=true removes stale silver rows; verified by
#         pre/post counts of intake_items for that source_msg_id.
#  * AC6: Canvas-poller with an invalid token logs "401" or "403" and writes 0 rows.
#  * AC7: Sink call with digest-rebuild endpoint unreachable still returns success.
#  * AC10: After first real Canvas poll, SELECT FROM intake_raw_events WHERE
#          source_channel='canvas:fultonschools' returns ≥ 1 row, AND SELECT FROM
#          intake_items WHERE source_channel='canvas:fultonschools' returns ≥ 1 row.
#  * AC11: grep -r "Bearer " (n8n workflow JSON exports) returns 0 inline occurrences
#          (the token is only in the cred store, never inline in a workflow definition).
