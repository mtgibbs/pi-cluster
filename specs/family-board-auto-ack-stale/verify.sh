#!/usr/bin/env bash
# verify.sh — deterministic acceptance gate for specs/family-board-auto-ack-stale.
# Compiles §10 into runnable assertions: exit 0 = acceptable.
#
# STATIC tier only (no deploy) — gates each ralph loop iteration. Parses the
# workflow JSON, extracts the `Get Feed` node's query, and greps the literal
# tokens the spec pins (§7). LIVE diff gate (after re-import: old items return
# all four acks; recent items return their real acks) is the human check.
#
# Run from repo root.  ./specs/family-board-auto-ack-stale/verify.sh
set -uo pipefail
WF="${WF:-clusters/pi-k3s/n8n/workflows/feed-api.json}"
fail=0
ok(){ echo "  PASS  $1"; }
no(){ echo "  FAIL  $1" >&2; fail=1; }

[ -f "$WF" ] || { echo "missing $WF" >&2; exit 2; }

# AC5 (a) — JSON still parses
python3 -c "import json; json.load(open('$WF'))" 2>/dev/null && ok "json:feed-api.json-valid" || { no "json:feed-api.json-valid"; }

# Extract the Get Feed query for scoped greps
Q=$(python3 - <<PY
import json
wf=json.load(open("$WF"))
for n in wf["nodes"]:
    if n["name"]=="Get Feed":
        print(n["parameters"]["query"])
        break
PY
)
[ -n "$Q" ] && ok "extract:Get-Feed-query" || { no "extract:Get-Feed-query"; echo "VERIFY: FAIL"; exit 1; }

# AC1/AC2 — the CASE projection with the exact pinned tokens (§7)
grep -q "CASE WHEN i.received_at < now() - interval '7 days' THEN" <<<"$Q" && ok "case:stale-branch-condition" || no "case:stale-branch-condition"
grep -q "'\\[\"julia\",\"matt\",\"ronin\",\"rory\"\\]'::json"        <<<"$Q" && ok "case:synthesized-acks-literal"  || no "case:synthesized-acks-literal"
grep -q "ELSE COALESCE(a.acks, '\\[\\]'::json) END AS acks"          <<<"$Q" && ok "case:fresh-branch-fallback"   || no "case:fresh-branch-fallback"

# AC3 — LEFT JOIN to board_acks aggregation still present
grep -q 'LEFT JOIN' <<<"$Q" && grep -q 'board_acks' <<<"$Q" && grep -q 'json_agg(person ORDER BY person)' <<<"$Q" \
  && ok "join:board_acks-intact" || no "join:board_acks-intact"

# AC4 — the other columns and ORDER BY / LIMIT still there (sample of the long list)
for col in i.id i.received_at i.type i.title i.due_at i.student i.action_required i.amount i.teacher i.course i.source_hint i.confidence i.source_channel i.source_subject i.source_from; do
  grep -q "$col" <<<"$Q" || { no "select:column-$col"; continue; }
done && ok "select:columns-intact"
grep -q 'ORDER BY (i.due_at IS NULL), i.due_at' <<<"$Q" && ok "select:order-by-intact" || no "select:order-by-intact"
grep -q 'LIMIT 500'                              <<<"$Q" && ok "select:limit-500-intact" || no "select:limit-500-intact"

# AC5 (b) — no other node in feed-api.json changed (their identity markers stay)
python3 - <<'PY' && ok "feed-api:other-nodes-untouched" || no "feed-api:other-nodes-untouched"
import json,sys
wf=json.load(open("clusters/pi-k3s/n8n/workflows/feed-api.json"))
names=[n["name"] for n in wf["nodes"]]
expected={"Feed Webhook","Ensure Board Acks","Get Feed","Respond"}
sys.exit(0 if set(names)==expected else 1)
PY

# AC6 — read-only: query must NOT contain a write verb
grep -qiE '\binsert\b|\bupdate\b|\bdelete\b|\btruncate\b|\balter\b|\bdrop\b' <<<"$Q" && no "safeguard:no-writes" || ok "safeguard:no-writes"

echo
if [ "$fail" = 0 ]; then echo "VERIFY: PASS"; else echo "VERIFY: FAIL"; exit 1; fi

# --- LIVE / human diff gate (NOT gated here) ------------------------------------
#   - Re-import feed-api.json into the live n8n via the API (body edit, no roll).
#   - GET /api/feed: pick an item with received_at > 7d → acks == ["julia","matt","ronin","rory"]
#   - Pick a recent item → acks reflects board_acks (whatever's persisted; [] if none).
#   - board_acks rowcount unchanged before/after (this is read-only).
#   - On the board: in any viewer's view, stale items fold into "Seen by you".
