"""Generate clusters/pi-k3s/n8n/workflows/agent-sec-researcher.json from src/agent-sec-*.js + nodes shared with
agent-alert.json. The workflow JSON is GENERATED: edit src/*.js (or this file), then re-run, then run the tests.
Usage: python3 clusters/pi-k3s/n8n/workflows/test/gen_agent_sec_researcher.py [<repo-root>]
       node clusters/pi-k3s/n8n/workflows/test/agent-sec-researcher.test.js
Deterministic ids (uuid5), so re-running on unchanged sources is a no-op diff. After a change, the n8n workflow
itself is updated by re-importing it (docs/agent-sandbox-n8n.md, "sec-researcher")."""
import json
import sys
import uuid

from pathlib import Path

root = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parents[5])
W = root + '/clusters/pi-k3s/n8n/workflows/'
alert = {n['name']: n for n in json.load(open(W + 'agent-alert.json'))['nodes']}
src = lambda f: open(W + 'src/' + f).read()
NS = uuid.UUID('6f1c1f0e-8a52-4c1e-9d55-000000005ec3')
uid = lambda s: str(uuid.uuid5(NS, s)).upper()
PG = {"postgres": {"id": "5bzmWi2TWDCyypLQ", "name": "intake-db"}}
GH = {"httpHeaderAuth": {"id": "REPLACE_ON_IMPORT_github_plans", "name": "github-plans"}}
GH_HEADERS = {"parameters": [{"name": "Accept", "value": "application/vnd.github+json"},
                             {"name": "X-GitHub-Api-Version", "value": "2022-11-28"},
                             {"name": "User-Agent", "value": "n8n-sec-researcher"}]}
FULL = {"response": {"response": {"fullResponse": True, "neverError": True}}}


def code(name, f, pos, **kw):
    n = {"id": uid(name), "name": name, "type": "n8n-nodes-base.code", "typeVersion": 2, "position": pos,
         "parameters": {"jsCode": src(f)}}
    n.update(kw)
    return n


def copy(name, pos, new=None):
    n = json.loads(json.dumps(alert[name]))
    n['name'] = new or name
    n['id'] = uid(n['name'])
    n['position'] = pos
    if 'webhookId' in n:
        n['webhookId'] = uid(n['name'] + '-webhook')
    return n


def pg(name, q, qr, pos, **kw):
    n = {"id": uid(name), "name": name, "type": "n8n-nodes-base.postgres", "typeVersion": 2.6, "position": pos,
         "parameters": {"operation": "executeQuery", "query": q, "options": {"queryReplacement": qr} if qr else {}},
         "credentials": PG}
    n.update(kw)
    return n


def if_node(name, expr, pos):
    return {"id": uid(name), "name": name, "type": "n8n-nodes-base.if", "typeVersion": 2.2, "position": pos,
            "parameters": {"conditions": {
                "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
                "conditions": [{"id": uid(name + '-cond'), "leftValue": expr,
                                "operator": {"type": "boolean", "operation": "true", "singleValue": True}}],
                "combinator": "and"}, "options": {}}}


def http(name, pos, method, url, creds=None, body=None, headers=GH_HEADERS, **kw):
    p = {"method": method, "url": url}
    if creds:
        p.update({"authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth"})
    p.update({"sendHeaders": True, "headerParameters": headers})
    if body:
        p.update({"sendBody": True, "specifyBody": "json", "jsonBody": body})
    p["options"] = dict(FULL, timeout=20000)
    n = {"id": uid(name), "name": name, "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": pos,
         "parameters": p, "onError": "continueRegularOutput"}
    if creds:
        n["credentials"] = creds
    n.update(kw)
    return n


ensure_q = alert['Ensure Tables']['parameters']['query'] + (
    " CREATE TABLE IF NOT EXISTS agent_plan_filings (run_id TEXT NOT NULL, fingerprint TEXT NOT NULL, rule TEXT,"
    " resource TEXT, severity TEXT, action TEXT NOT NULL, issue_number INT, issue_url TEXT, http_status INT,"
    " detail TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (run_id, fingerprint));"
    " CREATE INDEX IF NOT EXISTS agent_plan_filings_fp_idx ON agent_plan_filings (fingerprint, created_at DESC);")
# Atomic claim (same shape as agent-alert's) + the previous Flux revision seen, for the compare base.
claim_q = ("WITH s AS (SELECT $1::jsonb AS p), claim AS ("
           " INSERT INTO agent_dedupe AS d (dedupe_key, agent, subject, last_event_id, last_launched, cooldown_until)"
           " SELECT p->>'dedupe_key', 'sec-researcher', p->>'subject', NULL, now(),"
           " now() + make_interval(hours => GREATEST(COALESCE((p->>'cooldown_hours')::int, 1), 1)) FROM s"
           " WHERE COALESCE(p->>'dedupe_key', '') <> ''"
           " ON CONFLICT (dedupe_key) DO UPDATE SET last_launched = now(), cooldown_until = EXCLUDED.cooldown_until,"
           " subject = EXCLUDED.subject, launches = d.launches + 1"
           " WHERE d.cooldown_until <= now() RETURNING d.dedupe_key),"
           " base AS (SELECT d.subject FROM agent_dedupe d, s WHERE d.dedupe_key LIKE 'sec-researcher:flux-rev:%'"
           " AND d.dedupe_key <> s.p->>'dedupe_key' ORDER BY d.first_launched DESC LIMIT 1)"
           " SELECT EXISTS (SELECT 1 FROM claim) AS claimed, (SELECT subject FROM base) AS base;")
filings_q = ("INSERT INTO agent_plan_filings (run_id, fingerprint, rule, resource, severity, action, issue_number,"
             " issue_url, http_status, detail) SELECT f->>'run_id', f->>'fingerprint', f->>'rule', f->>'resource',"
             " f->>'severity', f->>'action', (f->>'issue_number')::int, f->>'issue_url', (f->>'http_status')::int,"
             " f->>'detail' FROM jsonb_array_elements($1::jsonb->'filings') AS f"
             " ON CONFLICT (run_id, fingerprint) DO NOTHING;")

BE = "$('Build Event').first().json"
launch = copy('Launch Run', [2420, 0])
launch['parameters']['jsonBody'] = ("={{ JSON.stringify({ agent: %s.agent, event: %s.event, callback: $json.callback }) }}"
                                    % (BE, BE))
wait = copy('Wait for Result', [2860, -100])
wait['parameters']['resumeAmount'] = 80
launched_if = copy('Launched?', [2640, 0])
launched_if['parameters']['conditions']['conditions'][0]['id'] = uid('Launched?-cond')
cb_if = copy('Callback?', [3080, -100])
cb_if['parameters']['conditions']['conditions'][0]['id'] = uid('Callback?-cond')
ledger = copy('Insert Ledger', [3520, 0])
push = copy('Push', [5280, 100])

nodes = [
    # --- trigger 1: Flux (event-driven)
    {"id": uid('Flux Webhook'), "name": "Flux Webhook", "type": "n8n-nodes-base.webhook", "typeVersion": 2,
     "position": [0, -200], "webhookId": uid('Flux Webhook-webhook'),
     "parameters": {"httpMethod": "POST", "path": "agent-sec-revision", "authentication": "headerAuth",
                    "responseMode": "onReceived", "options": {}},
     "credentials": {"httpHeaderAuth": {"id": "REPLACE_ON_IMPORT_agent_alert_token", "name": "agent-alert-token"}}},
    code('Flux Revision', 'agent-sec-flux-input.js', [220, -200]),
    # --- trigger 2: the one weekly sweep
    {"id": uid('Weekly Sweep'), "name": "Weekly Sweep", "type": "n8n-nodes-base.scheduleTrigger", "typeVersion": 1.2,
     "position": [0, 0], "parameters": {"rule": {"interval": [{"field": "cronExpression", "expression": "0 6 * * 0"}]}}},
    code('Sweep Input', 'agent-sec-sweep-input.js', [220, 0]),
    # --- trigger 3: Matt's form (LAN only)
    {"id": uid('Sec Form'), "name": "Sec Form", "type": "n8n-nodes-base.formTrigger", "typeVersion": 2.2,
     "position": [0, 200], "webhookId": uid('Sec Form-webhook'),
     "parameters": {"authentication": "none", "formTitle": "Run the security researcher",
                    "formDescription": "Starts a read-only sec-researcher run (access control). Findings are filed "
                                       "as issues in the private plans repo; a summary is pushed to ntfy topic agent-runs.",
                    "formFields": {"values": [{"fieldLabel": "What should it focus on? (optional)",
                                               "fieldType": "textarea"}]},
                    "responseMode": "onReceived",
                    "options": {"path": "agent-sec-run", "ignoreBots": True, "respondWithOptions": {"values": {
                        "respondWith": "text",
                        "formSubmittedText": "Started. The summary will arrive as an ntfy push (topic agent-runs)."}}}}},
    code('Form Input', 'agent-sec-form-input.js', [220, 200]),
    # --- common
    code('Trigger', 'agent-sec-trigger.js', [440, 0]),
    pg('Ensure Tables', ensure_q, None, [660, 0], alwaysOutputData=True),
    pg('Claim', claim_q, "={{ JSON.stringify($('Trigger').first().json) }}", [880, 0]),
    if_node('Claimed?', "={{ $json.claimed === true || $json.claimed === 't' }}", [1100, 0]),
    if_node('Is Flux?', "={{ $('Trigger').first().json.trigger === 'flux' }}", [1320, 0]),
    code('Compare URL', 'agent-sec-compare-url.js', [1540, -200]),
    http('Compare', [1760, -200], "GET", "={{ $json.url }}"),
    code('Path Filter', 'agent-sec-path-filter.js', [1980, -200]),
    if_node('Relevant?', "={{ $json.relevant === true }}", [2200, -200]),
    code('Build Event', 'agent-sec-build-event.js', [2200, 0]),
    code('Resume Callback', 'agent-resume-callback.js', [2310, 100]),
    launch, launched_if, wait, cb_if,
    code('Parse Result', 'agent-sec-parse-result.js', [3300, -200]),
    code('Timeout Row', 'agent-sec-timeout-row.js', [3300, 0]),
    code('Refusal Row', 'agent-sec-refusal-row.js', [3300, 200]),
    ledger,
    code('Plan Items', 'agent-sec-plan-items.js', [3740, 0]),
    if_node('Has Plans?', "={{ Array.isArray($json.plans) && $json.plans.length > 0 }}", [3960, 0]),
    code('Issue Pages', 'agent-sec-issue-pages.js', [4180, -200]),
    http('List Issues', [4400, -200], "GET", "={{ $json.url }}", creds=GH),
    code('Decide', 'agent-sec-decide.js', [4620, -200]),
    if_node('Any Actions?', "={{ Array.isArray($json.actions) && $json.actions.length > 0 }}", [4840, -200]),
    {"id": uid('Split Actions'), "name": "Split Actions", "type": "n8n-nodes-base.splitOut", "typeVersion": 1,
     "position": [5060, -300], "parameters": {"fieldToSplitOut": "actions", "options": {}}},
    http('Apply', [5280, -300], "={{ $json.method }}", "={{ $json.url }}", creds=GH,
         body="={{ JSON.stringify($json.payload) }}"),
    code('Summarize', 'agent-sec-summarize.js', [5060, 0]),
    pg('Record Filings', filings_q, "={{ JSON.stringify({ filings: $json.filings }) }}", [5280, -100]),
    push,
]
push['position'] = [5280, 100]

L = lambda *ts: {"main": [[{"node": t, "type": "main", "index": 0} for t in (b if isinstance(b, list) else [b])]
                          if b else [] for b in ts]}
conn = {
    "Flux Webhook": L("Flux Revision"), "Flux Revision": L("Trigger"),
    "Weekly Sweep": L("Sweep Input"), "Sweep Input": L("Trigger"),
    "Sec Form": L("Form Input"), "Form Input": L("Trigger"),
    "Trigger": L("Ensure Tables"), "Ensure Tables": L("Claim"), "Claim": L("Claimed?"),
    "Claimed?": L("Is Flux?", None), "Is Flux?": L("Compare URL", "Build Event"),
    "Compare URL": L("Compare"), "Compare": L("Path Filter"), "Path Filter": L("Relevant?"),
    "Relevant?": L("Build Event", None),
    "Build Event": L("Resume Callback"), "Resume Callback": L("Launch Run"),
    "Launch Run": L("Launched?", "Refusal Row"), "Launched?": L("Wait for Result", "Refusal Row"),
    "Wait for Result": L("Callback?"), "Callback?": L("Parse Result", "Timeout Row"),
    "Parse Result": L("Insert Ledger"), "Timeout Row": L("Insert Ledger"), "Refusal Row": L("Insert Ledger"),
    "Insert Ledger": L("Plan Items"), "Plan Items": L("Has Plans?"),
    "Has Plans?": L("Issue Pages", "Summarize"),
    "Issue Pages": L("List Issues"), "List Issues": L("Decide"), "Decide": L("Any Actions?"),
    "Any Actions?": L("Split Actions", "Summarize"), "Split Actions": L("Apply"), "Apply": L("Summarize"),
    "Summarize": L(["Record Filings", "Push"]),
}
wf = {"name": "Agent — sec-researcher (Flux revision / weekly sweep / form) → plans repo issues",
      "nodes": nodes, "connections": conn, "settings": {"executionOrder": "v1"}}
open(W + 'agent-sec-researcher.json', 'w').write(json.dumps(wf, indent=2, ensure_ascii=False) + '\n')
print('wrote', len(nodes), 'nodes')
