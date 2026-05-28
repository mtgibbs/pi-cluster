#!/usr/bin/env bash
# verify.sh — deterministic acceptance gate for original_from extraction.
# §10 acceptance criteria compiled into runnable assertions: exit 0 = acceptable.
#
# STATIC tier only. Greps the literal markers across the five touched files.
# LIVE tier (post-publish replay of a forwarded execution → row has original_from)
# is the human diff gate, not gated here.
#
# Run from repo root.  ./specs/family-board-original-from-extraction/verify.sh
set -uo pipefail
INTAKE="${INTAKE:-clusters/pi-k3s/n8n/workflows/inbound-mail.json}"
PARSE_SRC="${PARSE_SRC:-clusters/pi-k3s/n8n/workflows/src/parse-records.js}"
BUILD_SRC="${BUILD_SRC:-clusters/pi-k3s/n8n/workflows/src/build-request.js}"
FEED="${FEED:-clusters/pi-k3s/n8n/workflows/feed-api.json}"
HTML="${HTML:-clusters/pi-k3s/family-board/index.html}"

fail=0
ok(){ echo "  PASS  $1"; }
no(){ echo "  FAIL  $1" >&2; fail=1; }

for f in "$INTAKE" "$PARSE_SRC" "$BUILD_SRC" "$FEED" "$HTML"; do
  [ -f "$f" ] || { echo "missing $f" >&2; exit 2; }
done

# AC8 — JSON validity (intake + feed)
python3 -c "import json; json.load(open('$INTAKE'))" 2>/dev/null && ok "json:intake-valid" || no "json:intake-valid"
python3 -c "import json; json.load(open('$FEED'))"   2>/dev/null && ok "json:feed-valid"   || no "json:feed-valid"

# Extract the named node bodies / query strings from intake_inbound-mail
ensure=$(python3 -c "import json; wf=json.load(open('$INTAKE')); [print(n['parameters']['query']) for n in wf['nodes'] if n['name']=='Ensure Table']")
store=$(python3   -c "import json; wf=json.load(open('$INTAKE')); [print(n['parameters']['query']) for n in wf['nodes'] if n['name']=='Store']")
store_qr=$(python3 -c "import json; wf=json.load(open('$INTAKE')); [print(n['parameters']['options']['queryReplacement']) for n in wf['nodes'] if n['name']=='Store']")
parse_js=$(python3 -c "import json; wf=json.load(open('$INTAKE')); [print(n['parameters']['jsCode']) for n in wf['nodes'] if n['name']=='Parse Records']")
build_js=$(python3 -c "import json; wf=json.load(open('$INTAKE')); [print(n['parameters']['jsCode']) for n in wf['nodes'] if n['name']=='Build Request']")
feed_q=$(python3   -c "import json; wf=json.load(open('$FEED'));   [print(n['parameters']['query']) for n in wf['nodes'] if n['name']=='Get Feed']")

# AC1 — Schema migration
grep -q 'ADD COLUMN IF NOT EXISTS original_from TEXT' <<<"$ensure" && ok "schema:add-column-original_from" || no "schema:add-column-original_from"

# AC2 — LLM prompt (both files mention originalFrom)
grep -q 'originalFrom' <<<"$build_js" && ok "prompt:originalFrom-in-jsCode" || no "prompt:originalFrom-in-jsCode"
grep -q 'originalFrom' "$BUILD_SRC"    && ok "prompt:originalFrom-in-src"    || no "prompt:originalFrom-in-src"

# AC3 — Parse Records maps originalFrom → original_from (both files)
grep -q 'original_from: r.originalFrom' <<<"$parse_js" && ok "parse:map-in-jsCode" || no "parse:map-in-jsCode"
grep -q 'original_from: r.originalFrom' "$PARSE_SRC"    && ok "parse:map-in-src"    || no "parse:map-in-src"

# AC4 — Store SQL has the column, the $16 bind, the EXCLUDED set, and queryReplacement
grep -q 'original_from'                          <<<"$store"     && ok "store:column-in-INSERT"       || no "store:column-in-INSERT"
grep -qE '\$16([^0-9]|$)'                        <<<"$store"     && ok "store:positional-\$16"        || no "store:positional-\$16"
grep -q 'original_from = EXCLUDED.original_from' <<<"$store"     && ok "store:upsert-EXCLUDED"        || no "store:upsert-EXCLUDED"
grep -qF '={{ $json.original_from }}'            <<<"$store_qr"  && ok "store:queryReplacement-bind"  || no "store:queryReplacement-bind"

# AC5 — Feed exposes the column, ordered correctly
grep -q 'i.original_from' <<<"$feed_q" && ok "feed:i.original_from-selected" || no "feed:i.original_from-selected"
grep -q "i.source_from, i.original_from" <<<"$feed_q" && ok "feed:column-order-after-source_from" \
  || grep -qE 'i\.source_from, *i\.original_from' <<<"$feed_q" && ok "feed:column-order-after-source_from" \
  || no "feed:column-order-after-source_from (expected i.source_from immediately before i.original_from)"

# AC6 — Board drill-in label present
grep -q 'Originally from' "$HTML" && ok "board:Originally-from-label" || no "board:Originally-from-label"
grep -q 'it.original_from' "$HTML" && ok "board:field-referenced" || no "board:field-referenced"

# AC7 — item_key formula in src/parse-records.js unchanged (anchor on the existing
# composite expression that builds the key). Pin the most distinctive substring.
grep -q 'item_key' "$PARSE_SRC" && ok "intact:item_key-still-derived" || no "intact:item_key-still-derived"
grep -qF '[source_msg_id, type, student, due_date, amount' "$PARSE_SRC" \
  && ok "intact:item_key-formula-byte-for-byte" \
  || no "intact:item_key-formula-byte-for-byte (the canonical composite changed — that mints new ids, breaks acks)"

echo
if [ "$fail" = 0 ]; then echo "VERIFY: PASS"; else echo "VERIFY: FAIL"; exit 1; fi

# --- LIVE / human diff gate (NOT gated here) ---------------------------------------
#   - Re-import inbound-mail.json + feed-api.json via the n8n API (body edits; the
#     activation roll only matters for new webhook paths, which we don't add here).
#   - Replay a captured FORWARDED execution (the doc's "Test without re-forwarding"
#     runbook). Inspect intake_items for the new row → original_from is populated
#     (or NULL when the LLM couldn't find a clear header — that's acceptable).
#   - GET /api/feed → items now include "original_from" key.
#   - Board refresh → the new "Originally from" row shows up on cards that have it.
