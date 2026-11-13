# Agent sandbox — the n8n side (slice 1)

> **Only the Wait variant (`agent-run-manual.json`) is in the repo.** The fallback workflows this doc describes
> (`agent-result.json`, `agent-run-manual-async.json`) were drafted and left out: they need a callback credential
> the runner does not send. Their sections are kept as the plan if Wait/resume proves unreliable live.

**Status:** 2026-11-11 — written, **not imported or deployed**. Pairs with the runner contract in
`scripts/agentrunner/CONTRACT.md` (§1 Event, §3 runner API + callback, §5 Result) and the design in
`docs/design/agent-sandbox.md`. n8n decides *when* an agent runs and what happens to its result; the
runner decides *how*.

## What it does

A person opens a LAN form, picks an agent, types what it should look into, and gets an ntfy push with
the outcome when the agent finishes.

```
Agent Form (LAN: https://n8n.lab.mtgibbs.dev/form/agent-run)
  → Ensure Table (agent_runs, idempotent)
  → Build Event        Event per CONTRACT §1: fresh ULID id, type manual.investigate, source matt, trust internal, data.ask
  → Resume Callback    callback = this execution's resume URL, re-homed onto the in-cluster webhook Service
  → Launch Run         POST http://agent-runner.agents.svc.cluster.local:8080/runs  {agent, event, callback}  (Bearer: agent-runner)
  → Launched? (202)
      yes → Wait for Result (resume on POST, 30 min limit)
              → Callback?  yes → Parse Result ┐
                           no  → Timeout Row  ┴→ Insert Ledger (ON CONFLICT DO NOTHING RETURNING) → Format Push → Push (ntfy agent-runs)
      no / unreachable → Launch Status (why it failed: 401/404/422/429/503/network) ──────────────────────────────→ Push
```

| File | What |
|---|---|
| `clusters/pi-k3s/n8n/workflows/agent-run-manual.json` | **Recommended.** Form → runner → Wait/resume → ledger → push. |
| `clusters/pi-k3s/n8n/workflows/agent-run-manual-async.json` | Fallback launcher: same form, callback = `agent-result` webhook, pushes "started". |
| `clusters/pi-k3s/n8n/workflows/agent-result.json` | Fallback receiver: `POST /webhook/agent-result` (header auth) → ledger → push. |
| `clusters/pi-k3s/n8n/workflows/agent-alert.json` | Slice 2: Alertmanager webhook → dedupe → ops-investigator → same tail. See [Alert → ops-investigator](#alert--ops-investigator-slice-2). |
| `clusters/pi-k3s/n8n/workflows/agent-sec-researcher.json` | Slice 3: Flux revision / weekly sweep / form → sec-researcher → **n8n files its plans as issues**. See [sec-researcher](#sec-researcher--plans-filed-by-n8n-slice-3). |
| `clusters/pi-k3s/n8n/workflows/src/agent-*.js` | Code-node sources (each is byte-identical to the `jsCode` in the JSON, the repo's `src/` convention). |

The push carries **outcome, summary, and report title only**. The report body stays in
`agent_runs.outputs`:

```sql
SELECT run_id, outcome, summary, o->>'title' AS title, o->>'body' AS report
FROM agent_runs, jsonb_array_elements(outputs) o
WHERE o->>'kind' = 'report' ORDER BY created_at DESC LIMIT 5;
```

Everything in a result is data. Form text only goes into `event.data.ask` inside the JSON body. Callback
fields are clipped, type-checked (unknown `outcome` becomes `failed`), and written as **one bound `$1::jsonb`
parameter**, the same pattern `digest-builder.json`'s `Insert Summary` uses. Nothing is concatenated into
SQL, and no result text goes into a URL. ntfy header values (`Title`) are cut down to single-line ASCII,
and the summary goes in the body.

## The callback question: Wait/resume in queue mode

**Finding (high confidence, read from the n8n `n8n@2.23.4` source; not yet run live):**

1. **URL shape.** `$execution.resumeUrl` = `<WEBHOOK_URL>/webhook-waiting/<executionId>?signature=<resumeToken>`
   (`packages/core/.../get-additional-keys.ts`; `WAITING_TOKEN_QUERY_PARAM = 'signature'` in
   `packages/core/src/constants.ts`). The base is `urlService.getWebhookBaseUrl()`, which is `WEBHOOK_URL`, so
   here it is `https://n8n-hook.mtgibbs.dev/webhook-waiting/...`. The tunnel only passes
   `^/webhook/inbound-mail.*`, so that host can't route it.
2. **The signature is required.** `resumeToken` is a random token created when the execution's run data is
   created (`createRunExecutionData` → `generateSecureToken()`), so it already exists *before* the Wait node
   runs. That means the HTTP Request node that hands the URL to the runner can include it. `WaitingWebhooks`
   compares the token timing-safely against the stored `resumeToken`. If it is missing or wrong, n8n returns
   **401 `{"error":"Invalid token"}`**. (HMAC signing applies only to send-and-wait nodes, not to this Wait
   node.) The Code-node task runner gets `resumeToken` through `data-request-response-builder.ts`, so
   `$execution.resumeUrl` in a Code node is signed too. `agent-resume-callback.js` checks for that anyway, and
   **fails the execution straight away** if `signature=` or the execution id is missing, so a run never waits
   30 minutes for a callback that can't arrive.
3. **Which process serves it.** `AbstractServer.start()` registers `/webhook-waiting/:path{/:suffix}` whenever
   production webhooks are enabled. That covers the **webhook pods** (`n8n webhook`) and the **main pod**,
   since `N8N_DISABLE_PRODUCTION_MAIN_PROCESS` is unset in `configmap.yaml`. The handler looks the execution up
   in Postgres by id, so no activation or registration is involved, and the webhook-tier "re-register on
   restart" problem doesn't apply. The resumed run is queued in Valkey and runs on a worker. While it waits,
   the execution holds **no** worker slot.
4. **Derivation.** Keep n8n's path and query, and swap the origin:
   `http://n8n-webhook.n8n.svc.cluster.local:5678` + `/webhook-waiting/<id>?signature=<token>`.
   Service names and ports come from the manifests: `n8n-webhook` (in `webhook.yaml`) and `n8n` (in
   `service.yaml`), both port 5678, namespace `n8n`. Both match the runner's allowed prefixes. The webhook tier
   is used because it is the designed inbound surface. `http://n8n.n8n.svc.cluster.local:5678` works the same
   way if needed (change `CALLBACK_ORIGIN`).
5. **Timeout and duplicates.** With `limitWaitTime`, `waitTill` = now + 30 min. When it passes, the main
   process's WaitTracker resumes the run (it polls about every 60 s, so the timeout fires at 30–31 min). The
   Wait node then outputs its *input*, which is the runner's 202 response. `Callback?` tells the two cases
   apart by checking `body.exit_reason`. Once the run has resumed, any further POST to the URL gets
   **409** ("running already" / "finished already"). So with Wait, n8n itself absorbs a duplicate callback, and
   `ON CONFLICT (run_id) DO NOTHING` is the second guard.
6. **Race.** If the runner calls back before the worker has saved the run as `waiting`, it gets 409 "running
   already". The runner's 3 retries cover that, as long as its backoff is at least a few seconds. In practice
   scheduling a Job pod alone takes longer than that.

**Recommendation: use the Wait variant (`agent-run-manual.json`).** It keeps the request, result and
notification in one execution. The per-execution `signature` is the callback auth, so no contract change and
no new shared secret are needed. Duplicates are rejected by n8n. It also works without the webhook-tier
restart dance.

The fallback (`agent-run-manual-async.json` + `agent-result.json`) is there in case live testing disproves
(1)–(3). Its costs: (a) **CONTRACT §3 defines no auth header on the callback**, so `agent-result`'s header-auth
needs a runner change (for example `Authorization: Bearer $RUNNER_CALLBACK_TOKEN`). Until then that webhook
can't be both authenticated and reachable. (b) It has no timeout detection. (c) It loses the event
type/subject, which aren't in the callback, unless the runner adds `event`. Its one advantage: a callback that
arrives after 30 minutes is still recorded. In the Wait variant a late result shows up only in the runner's
ledger (`GET /runs/<run_id>`).

Keep the Wait limit (30 min) comfortably above every manifest's `limits.timeout` (media-investigator: 15m)
plus Job start-up time. If a manifest's timeout goes up, raise the Wait limit with it.

**Known gap since runner 0.2.0 (burst queue):** a manual run can now answer 202 `"status":"queued"` and wait up
to `RUNNER_MAX_QUEUE_WAIT` (45m) for a slot before its 15m deadline starts, so this 30-minute Wait can give up
(`callback_timeout` row) on a run that later completes; its result is then only in `GET /runs/<run_id>`. The
manual workflow was deliberately left unchanged (it is live). To close the gap, raise its Wait to 75 minutes as
`agent-alert.json` does and re-import it.

## The "Run agent" recipe (copy into any workflow)

Three steps. Everything before step 1 just has to produce `{agent, event}`.

1. **Call the runner.** Add a Code node with `src/agent-resume-callback.js` (adds `callback`), then an HTTP
   Request (v4.2): `POST http://agent-runner.agents.svc.cluster.local:8080/runs`, credential
   `agent-runner` (httpHeaderAuth), JSON body
   `={{ JSON.stringify({ agent: $json.agent, event: $json.event, callback: $json.callback }) }}`, options
   *Full Response* + *Never Error*, and **Settings → On Error → Continue (using error output)**. Add an IF
   node `statusCode == 202`. The false branch and the error output are "not started" (`src/agent-launch-status.js`).
2. **Wait.** Wait node v1.1: *Resume = On Webhook Call*, *HTTP Method = POST*, *Respond = Immediately*,
   *Limit Wait Time = 30 minutes*. Follow it with an IF on
   `={{ !!($json.body && typeof $json.body === 'object' && typeof $json.body.exit_reason === 'string') }}`
   (boolean is true). True means the callback arrived, false means it timed out.
3. **Act on the result.** True → `src/agent-parse-result.js` (one ledger row) → `Insert Ledger` (query below)
   → whatever the workflow does with `outcome` and `outputs`. False → `src/agent-timeout-row.js` → the same
   insert.

Rules: the event `id` must be fresh for every logical request (the runner dedupes on `(event.id, agent)`,
and a 200 "already seen" never resumes *this* execution). Name the node that builds the event `Build Event`,
because parse-result and timeout-row read `$('Build Event')` for type/subject/agent. Never put result text
into a URL, a query string, or SQL text.

## `agent_runs` ledger (DDL)

Like the other intake tables (`intake_items`, `board_*`), the DDL lives in an idempotent **`Ensure Table`**
Postgres node at the top of each workflow. It runs on every execution, on the `intake-db` credential (n8n's
own Postgres, database `n8n`). For reference, or to create it by hand:

```sql
CREATE TABLE IF NOT EXISTS agent_runs (
  run_id      TEXT PRIMARY KEY,
  agent       TEXT NOT NULL,
  event_id    TEXT,
  event_type  TEXT,
  subject     TEXT,
  started     TIMESTAMPTZ,
  finished    TIMESTAMPTZ,
  exit_reason TEXT,      -- runner enum, plus n8n-side 'callback_timeout'
  outcome     TEXT,      -- done | nothing_to_do | needs_human | failed
  summary     TEXT,
  outputs     JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_runs_created_idx ON agent_runs (created_at DESC);
```

Insert (Postgres node v2.6, *Execute Query*, Query Parameters = `={{ JSON.stringify($json) }}`):

```sql
INSERT INTO agent_runs (run_id, agent, event_id, event_type, subject, started, finished, exit_reason, outcome, summary, outputs)
SELECT p->>'run_id', p->>'agent', p->>'event_id', p->>'event_type', p->>'subject', (p->>'started')::timestamptz,
       (p->>'finished')::timestamptz, p->>'exit_reason', p->>'outcome', p->>'summary', COALESCE(p->'outputs', '[]'::jsonb)
FROM (SELECT $1::jsonb AS p) AS s
ON CONFLICT (run_id) DO NOTHING
RETURNING run_id, agent, outcome, exit_reason, summary, outputs;
```

When the row already exists, `RETURNING` yields nothing and `Format Push` sends nothing. That is how a
retried callback in the fallback receiver avoids a second push.

## Import / activation (manual, same style as `n8n-email-pipeline.md` §I)

n8n workflows and credentials are **not Flux-managed**. They are created through the n8n REST API (key:
`op://pi-cluster/n8n-automation/n8n-api-key`) or the UI on `https://n8n.lab.mtgibbs.dev`.

**Prerequisites outside n8n (other slices/PRs):**
- The runner is deployed at `agent-runner.agents.svc:8080`, with `RUNNER_CALLBACK_PREFIXES` including
  `http://n8n-webhook.n8n.svc.cluster.local:5678/` (and `http://n8n.n8n.svc.cluster.local:5678/` for the
  fallback).
- NetworkPolicy allows **n8n worker → agent-runner:8080** and **agent-runner → n8n-webhook:5678 / n8n:5678**.
- **ntfy ACL:** the auth default is deny-all and `family` is granted topics one by one. Add
  `ntfy access family "agent-runs" rw` to `clusters/pi-k3s/ntfy/deployment.yaml` (postStart seed). Without it
  every push 403s.

**Credentials to create (by these exact names):**

| Name | Type | Value |
|---|---|---|
| `agent-runner` | httpHeaderAuth | Name `Authorization`, Value `Bearer <RUNNER_API_TOKEN>` (the same 1Password value the runner's ExternalSecret reads). The API needs `allowedHttpRequestDomains:"all"`. |
| `intake-db` | postgres | **exists**: the JSON keeps its current id `5bzmWi2TWDCyypLQ` |
| `ntfy-family` | httpBasicAuth | **exists**: the JSON keeps its current id `Gw4eOIEmkybwuctT` |
| `agent-result-token` | httpHeaderAuth | *fallback only*: needs the runner to send a callback auth header (see above) |

The new credentials use placeholder ids (`REPLACE_ON_IMPORT_agent_runner`,
`REPLACE_ON_IMPORT_agent_result_token`). **Re-link them on import:** either replace the id in the JSON with
the one the credential-create call returns before `POST /api/v1/workflows`, or open each HTTP/Webhook node in
the UI and pick the credential.

**Steps:**
1. Create `agent-runner` (and `agent-result-token` only for the fallback).
2. `POST /api/v1/workflows` with `agent-run-manual.json` (credential ids patched), then
   `POST /api/v1/workflows/<id>/activate`.
3. **No webhook-tier roll is needed for the recommended variant.** The form is served by **main**, which
   registers activations immediately. The LAN ingress `n8n.lab.mtgibbs.dev` → `n8n` Service is the same path
   the calendar feeds use. `/webhook-waiting/*` resumes are looked up by execution id and aren't registered.
   **For the fallback**, `agent-result` is a production webhook. Point the callback at **main**
   (`http://n8n.n8n.svc.cluster.local:5678/webhook/agent-result`, which `agent-run-manual-async.json` already
   does) so it works without the roll. If you ever point it at `n8n-webhook`, bump
   `n8n.mtgibbs.dev/restarted-at` in `n8n/webhook.yaml`, commit, and reconcile (the documented publish dance).
4. Open `https://n8n.lab.mtgibbs.dev/form/agent-run` (LAN/tailnet). Ignore the "production URL" the editor
   shows: it is built from `WEBHOOK_URL` (`n8n-hook.mtgibbs.dev`), and the tunnel 404s it, which is intended.
   Never add a tunnel rule for `/form/agent-run` or `/webhook-waiting/`: the form has no auth beyond being on
   the LAN, and each submission spends model budget.

## Test plan

Positive:
1. Submit the form with media-investigator and a small ask. You should get a push titled
   `media-investigator: <outcome> - <report title>`, one `agent_runs` row, and the execution history should
   show *waiting*, then *success*.
2. In that execution, read the Wait node's metadata `resumeUrl` and the `Resume Callback` output. Confirm the
   path and `signature` are identical and only the origin changed.

Negative:
3. **Runner 503:** set `RUNNER_PAUSED=true`. Expect a push "not started (HTTP 503) / runner is paused", no
   Wait, and no ledger row.
4. **Runner 429:** temporarily set the manifest's `runs_per_day` to the number already used today. Expect
   "not started (HTTP 429) / daily run cap…".
5. **Runner unreachable:** scale the runner to 0. Expect "not started / Could not reach agent-runner:
   ECONNREFUSED…" through the error output.
6. **Callback never arrives:** in a *copy* of the workflow, set the Wait limit to 2 min, then launch and scale
   the runner to 0 (or block runner → n8n egress) before the Job ends. After about 2–3 min expect a push
   `failed` with "No callback from agent-runner within 30 minutes…" (the text is fixed) and a ledger row with
   `exit_reason = callback_timeout`. A later manual POST to the resume URL should get **409**.
7. **Duplicate callback:** after test 1 succeeds, re-POST the same callback body to the same resume URL from
   inside the cluster. Expect **409**, no second push, and still one row. For the fallback receiver: POST the
   same body twice to `/webhook/agent-result`. Both get 200, there is one row, and only one push.
8. **Forged/unsigned resume:** POST to `http://n8n-webhook.n8n.svc.cluster.local:5678/webhook-waiting/<id>`
   **without** `?signature=`, or with a wrong one, while a run is waiting. Expect **401 `{"error":"Invalid
   token"}`**, and the run keeps waiting.
9. **Hostile result:** a callback whose `summary` and report title contain quotes, `'); DROP TABLE…`, newlines
   and emoji. Expect the row stored verbatim (bound parameter), a single-line ASCII push title, and the
   unknown `outcome` stored as `failed`.

## Alert → ops-investigator (slice 2)

**Status:** 2026-11-11 — written and unit-tested offline, **not imported**. `agent-alert.json` starts the
read-only `ops-investigator` agent for every warning/critical Alertmanager group (receiver `n8n-agents` in
`clusters/pi-k3s/monitoring/helmrelease.yaml`) and pushes the outcome to the same `agent-runs` topic. The route
already drops `InfoInhibitor` and every `Beelink*` / `LiteLLM*` alert (the agent has no Beelink tools), so those
never reach n8n.

```
Alert Webhook   POST /webhook/agent-alert, Header Auth (agent-alert-token), answers 200 at once
  → Build Event     src/agent-alert-build-event.js: ONE event per group; no items (silent end) if
                    status != firing or every alert is Watchdog / InfoInhibitor / KubeMemoryOvercommit
  → Ensure Tables   agent_runs (same DDL as the manual flow) + agent_dedupe
  → Claim           atomic cooldown claim on dedupe_key (6 h); returns {claimed}
  → Claimed?        false → end (silent: no ledger row, no push)
  → Resume Callback → Launch Run → Launched? (202 = launched OR queued) → Wait for Result (75 min)
    → Callback? → Parse Result / Timeout Row (src/agent-alert-timeout-row.js)
    → Insert Ledger → Format Push → Alert Title → Push   (Resume Callback, Parse Result, Format Push: shared
                                                         src/agent-*.js, unchanged)
  Launch Run error / Launched? false
    → Refusal Row (exit_reason refused_<HTTP> | refused_queue_full | runner_unreachable)
    → Insert Refusal (+ prior_same)
    → Refusal Push (only when prior_same = 0: one quiet push per refusal kind per 6 h) → Push
```

**Event** (CONTRACT §1): `type alert.firing`, `source alertmanager`, `trust internal`,
`subject <alertname>/<namespace or ->`, `dedupe_key alertmanager:<sha256(groupKey)>`, a fresh ULID `id` per launch,
`data {common_labels, common_annotations, alerts[≤10]{labels, annotations, startsAt, generatorURL}}`, plus
`alerts_total` and `truncated: true` when anything was cut (Alertmanager's own `truncatedAlerts` from
`max_alerts` is counted in). Strings are clipped and the event is shrunk until it is ≤ 24 KiB of UTF-8.

**Dedupe — who does what.** The runner dedupes only on (`event.id`, `agent`) and never reads `dedupe_key`.
n8n owns the cooldown: `agent_dedupe` holds one row per `dedupe_key` with `cooldown_until`; `Claim` is a single
`INSERT … ON CONFLICT DO UPDATE … WHERE cooldown_until <= now()`, so concurrent re-sends of one group (queue
mode runs them in parallel) claim at most once. The event `id` is deliberately *not* derived from the group:
the runner would answer every later legitimate run with 200 "already seen". The claim is kept even when the
runner refuses (429/503/unreachable): Alertmanager re-sends the group after its 12 h repeat, which is the
retry — nothing in n8n loops. To force a re-run now: `DELETE FROM agent_dedupe WHERE dedupe_key = '…';`

```sql
CREATE TABLE IF NOT EXISTS agent_dedupe (dedupe_key TEXT PRIMARY KEY, agent TEXT NOT NULL, subject TEXT,
  last_event_id TEXT, first_launched TIMESTAMPTZ NOT NULL DEFAULT now(), last_launched TIMESTAMPTZ NOT NULL DEFAULT now(),
  cooldown_until TIMESTAMPTZ NOT NULL, launches INT NOT NULL DEFAULT 1);
```

**Pushes.** Finished run: `ops-investigator: <outcome> - <alertname>`, body starting
`Auto-started by Alertmanager: <subject> (N alerts)`, then the summary and `Report: <title>`, tag
`rotating_light`. Refusal: `ops-investigator: not started - <alertname>`, priority 2, at most once per
`exit_reason` per 6 h (counted from `agent_runs`); every refusal still gets a ledger row with
`run_id nolaunch-<event id>`, `outcome failed`. Queue expired (below): `ops-investigator: not investigated
(queue busy) - <alertname>`, priority 2, tags `hourglass,rotating_light`, one per expired run.

### Bursts — the runner's queue (runner 0.2.0)

When Alertmanager flushes many groups at once (route enabled, Alertmanager restart, a node going down), the
runner starts at most `RUNNER_MAX_CONCURRENT` (2) agent Jobs and answers the rest 202 `"status":"queued"`
without creating a Job, so a run's 15-minute deadline only starts when it actually gets a slot. Knobs, all in
`clusters/pi-k3s/agents/deployment.yaml` (CONTRACT §3, §7a):

| Env | Default | Effect |
|---|---|---|
| `RUNNER_MAX_CONCURRENT` | 2 | Agent Jobs alive at once. Must equal the `agents` ResourceQuota `pods` − 1. |
| `RUNNER_MAX_QUEUE` | 8 | Runs waiting for a slot. Beyond it: 429 `{"error":"queue_full"}` → `refused_queue_full` row (its own push kind, so it never silences a later daily-cap `refused_429` push). |
| `RUNNER_MAX_QUEUE_WAIT` | 45m | A run still queued after this ends `exit_reason queue_expired` (`outcome failed`) with the normal callback → ledger row + the quiet "not investigated" push. |

The daily cap (`runs_per_day: 12`) still counts at accept, so a queued or expired run uses one of the 12.
`Claimed?` holds the group's 6 h cooldown either way; a still-firing group comes back on Alertmanager's 12 h
repeat. The Wait limit is **75 min** = 45m queue + 15m agent timeout + 5m runner grace + margin: raise it if
any of those go up. Queued runs survive a runner restart (spooled on the ledger PVC), and the callback still
reaches this execution.

### Must exist before activation

| What | Where | Notes |
|---|---|---|
| Credential **`agent-alert-token`** | n8n, type *Header Auth* (httpHeaderAuth) | Name `Authorization`, Value `Bearer <token>` — the token is 1Password `pi-cluster/n8n-agent-alert-webhook` field `token`, the value Alertmanager reads from Secret `alertmanager-n8n-agents`. Placeholder id `REPLACE_ON_IMPORT_agent_alert_token`. |
| Credential **`agent-runner`** | n8n | Already created for the manual flow; re-link placeholder `REPLACE_ON_IMPORT_agent_runner`. |
| `intake-db`, `ntfy-family` | n8n | Exist; ids kept in the JSON. |
| Tables `agent_runs`, `agent_dedupe` | n8n Postgres | Created by `Ensure Tables` on first execution. |
| Manifest `ops-investigator` | `clusters/pi-k3s/agents/manifests/` | Otherwise every launch is a quiet `refused_404`. |

The Webhook node fails closed: a missing or wrong `Authorization` header gets **403** and no execution;
past the trigger; with no credential linked the node errors and nothing runs. Keep the n8n Wait limit (75 min)
above `RUNNER_MAX_QUEUE_WAIT` (45 m) + the manifest's `limits.timeout` (15 m) + 300 s runner grace + Job start-up.

### Import

1. Create `agent-alert-token` (UI: Credentials → Header Auth; or `POST /api/v1/credentials` with
   `{"name":"agent-alert-token","type":"httpHeaderAuth","data":{"name":"Authorization","value":"Bearer …"}}`,
   value read from 1Password into a variable, never typed inline).
2. Patch both `REPLACE_ON_IMPORT_*` ids, `POST /api/v1/workflows` with `agent-alert.json`, then
   `POST /api/v1/workflows/<id>/activate`.
3. Alertmanager posts to the **webhook tier** (`http://n8n-webhook.n8n.svc.cluster.local:5678/webhook/agent-alert`),
   which does not pick up new activations by itself: bump `n8n.mtgibbs.dev/restarted-at` in `n8n/webhook.yaml`,
   PR, reconcile (the publish dance in `n8n-email-pipeline.md`). Until then the tier answers 404 and
   Alertmanager logs a failed notify (Discord delivery is unaffected — `continue: true`).

**Re-import after the burst-handling change (runner 0.2.0).** `agent-alert.json` changed (Wait 30 → 75 min;
Timeout Row, Alert Title and Refusal Row code). n8n does not read the file from Git: update the live workflow
in place — `PUT /api/v1/workflows/<id>` with the new JSON (re-patch the two `REPLACE_ON_IMPORT_*` credential
ids), or paste the changed nodes in the editor — then deactivate/activate it and do the webhook-tier
`restarted-at` bump from step 3. Executions already *waiting* keep their old 30-minute limit. Import it
**after** the 0.2.0 runner is live; the old runner never queues, so the new JSON is harmless with it.
`agent-run-manual.json` did not change and needs no re-import.

### Test plan

Run from a pod in the cluster or the LAN; the token comes from 1Password into an env var, never inline.

```bash
TOK=$(op read op://pi-cluster/n8n-agent-alert-webhook/token)
URL=https://n8n.lab.mtgibbs.dev/webhook/agent-alert      # main tier on the LAN; in-cluster: the n8n-webhook Service
cat > /tmp/am.json <<'JSON'
{"version":"4","status":"firing","receiver":"n8n-agents","groupKey":"{}/{severity=~\"warning|critical\"}:{alertname=\"AgentAlertSmokeTest\", namespace=\"agents\"}",
 "truncatedAlerts":0,"groupLabels":{"alertname":"AgentAlertSmokeTest","namespace":"agents"},
 "commonLabels":{"alertname":"AgentAlertSmokeTest","namespace":"agents","severity":"warning"},
 "commonAnnotations":{"summary":"Smoke test: nothing is broken. Report that and stop."},"externalURL":"http://alertmanager",
 "alerts":[{"status":"firing","labels":{"alertname":"AgentAlertSmokeTest","namespace":"agents","severity":"warning"},
   "annotations":{"summary":"Smoke test"},"startsAt":"2026-11-11T12:00:00Z","endsAt":"0001-01-01T00:00:00Z",
   "generatorURL":"http://prometheus/graph","fingerprint":"0"}]}
JSON
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$URL" -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' --data @/tmp/am.json
```

1. **Happy path:** expect `200` at once, an execution that goes *waiting* → *success*, one `agent_dedupe` row,
   one `agent_runs` row with `event_type alert.firing`, and a push `ops-investigator: <outcome> - AgentAlertSmokeTest`.
2. **Cooldown:** repeat the same curl. Expect `200`, an execution that ends at `Claimed?`, no launch, no push,
   `launches` still 1. Then `DELETE FROM agent_dedupe WHERE subject = 'AgentAlertSmokeTest/agents'` and repeat:
   a new run.
3. **Auth:** no header, `Bearer wrong`, and `Basic …` → **403**, no run (execution list unchanged).
4. **Filtered:** the same payload with `"status":"resolved"`, and one whose only alert is `Watchdog` →
   `200`, execution ends after `Build Event`, nothing else.
5. **Refusals:** with `RUNNER_PAUSED=true` post two *different* groupKeys. Expect two `agent_runs` rows with
   `exit_reason refused_503` and exactly one quiet push. Same for `runs_per_day` exhausted (`refused_429`).
5a. **Burst:** post 4 *different* groupKeys within a few seconds. Expect 2 `run-*` Jobs in `agents` and
   `GET /runs/<id>` → `"status":"queued"` for the other two, which start as the first two finish (no
   `FailedCreate … exceeded quota` events). For `queue_full`/`queue_expired` without waiting 45 minutes, set
   `RUNNER_MAX_QUEUE: "0"` (→ `refused_queue_full` rows, one quiet push) or `RUNNER_MAX_QUEUE_WAIT: "1m"`
   (→ `queue_expired` rows and "not investigated (queue busy)" pushes) in a throwaway PR, then revert.
6. **Real alert:** fire one through Alertmanager itself (it applies the real route, `group_wait 2m`):
   ```bash
   kubectl -n monitoring exec sts/alertmanager-kube-prometheus-stack-alertmanager -c alertmanager -- \
     amtool alert add AgentAlertSmokeTest severity=warning namespace=agents \
     --annotation=summary="Smoke test: nothing is broken" --end="$(date -u -v+15M +%Y-%m-%dT%H:%M:%SZ)" \
     --alertmanager.url=http://localhost:9093
   ```
   (laptop: `kubectl`; check the StatefulSet name with `kubectl -n monitoring get sts`). Expect the Discord
   warning as before **and**, about 2 min later, an `agent-alert` execution and the push.

## Verify against the live n8n (can't be settled from source)

- The real `$execution.resumeUrl` string (a trailing slash on `WEBHOOK_URL`, any `N8N_PATH`). The guard in
  `agent-resume-callback.js` fails loudly if the shape differs.
- That `n8n-webhook` pods answer `/webhook-waiting/<id>` (expect 404 "execution does not exist" for a fake
  id, not a 404 route miss), and that main does too.
- That the 30-min timeout actually resumes in queue mode, and that the Wait node then outputs the 202 item
  (so `Callback?` takes the false branch).
- That the runner treats Wait's immediate 200 as success, and that its retry backoff outlasts the
  running→waiting race.
- That the imported JSON loads cleanly: formTrigger **2.2** (`options.path`, `formFields.values[]`), wait
  **1.1**, IF **2.2** boolean operator, and HTTP Request `onError: continueErrorOutput` with
  `response.fullResponse/neverError`. The form's output keys are the field labels (`Agent`,
  `What should it look into?`, `Subject (optional)`).
- That the form page submits back to the LAN host it was loaded from, not to `WEBHOOK_URL`.
- That ntfy accepts the `agent-runs` topic once the ACL line is added.
- `agent-alert.json`: that the Postgres node returns `claimed` as a JS boolean (the IF also accepts `'t'`),
  that the webhook tier serves `/webhook/agent-alert` after the roll, and that a Code node returning no items
  (dropped group) ends the execution as *success*.

## sec-researcher → plans filed by n8n (slice 3)

**Status:** 2026-11-12 — written and unit-tested offline (`node clusters/pi-k3s/n8n/workflows/test/agent-sec-researcher.test.js`),
**not imported**. One workflow, three triggers, one exit point. The agent (`clusters/pi-k3s/agents/manifests/sec-researcher.yaml`)
is read-only and returns structured `plan` items (CONTRACT §5a); **this workflow, not the agent, writes to GitHub**,
with its own `github-plans` credential, from those fields only. No model is involved after the agent's result.

```
Flux Webhook  POST /webhook/agent-sec-revision, Header Auth (agent-alert-token, reused) ─→ Flux Revision  (info + GitRepository|Kustomization + 40-hex sha, else silent end)
Weekly Sweep  Schedule, cron "0 6 * * 0" (the ONE named sweep, design §10) ──────────────→ Sweep Input    (key per ISO week)
Sec Form      LAN form /form/agent-sec-run ──────────────────────────────────────────────→ Form Input     (fresh key per submission)
  → Trigger (re-validates; the merge point) → Ensure Tables (+ agent_plan_filings) → Claim (agent_dedupe; returns the previous flux revision)
  → Claimed?  false → end
  → Is Flux?  yes → Compare URL → Compare (GET api.github.com, public repo, NO token) → Path Filter → Relevant?  no → end
  → Build Event (security.flux_revision | security.sweep | security.manual) → Resume Callback → Launch Run → Launched?
      → Wait for Result (80 min) → Callback? → Parse Result (keeps plan structure) / Timeout Row ┐
      (not launched) → Refusal Row ─────────────────────────────────────────────────────────────┴→ Insert Ledger (agent_runs)
  → Plan Items (re-validate, fingerprint, issue title/body) → Has Plans?
      yes → Issue Pages (5) → List Issues (github-plans) → Decide → Any Actions?
              yes → Split Actions → Apply (POST/PATCH, github-plans) → Summarize
              no  → Summarize
      no  → Summarize
  → Summarize → Record Filings (agent_plan_filings) + Push (ntfy agent-runs, ONE per run)
```

### Triggers and dedupe

| Trigger | Event | Claim key (in `agent_dedupe`) | Hold |
|---|---|---|---|
| Flux stores a new revision (source-controller `NewArtifact` for GitRepository `flux-system`, forwarded by notification-controller `Provider` `n8n-agents` + `Alert` `sec-researcher-revisions`, `clusters/pi-k3s/flux-notifications/n8n-agents.yaml`) | `security.flux_revision`, `data {revision, base, changed_paths, reasons}` | `sec-researcher:flux-rev:<sha>` | a year — once per revision, however many events report it |
| Weekly sweep, Sunday 06:00 (n8n timezone) | `security.sweep` | `sec-researcher:sweep:<YYYY-Www>` | 6 days |
| Form | `security.manual`, `data {ask}` | `sec-researcher:manual:<ulid>` | 1 h (never collides) |

**Flux auth (fails closed).** notification-controller sends `Authorization: Bearer <token>` from Secret
`flux-system/n8n-agent-flux-webhook`, built by an ExternalSecret from **`pi-cluster/n8n-agent-alert-webhook/token`** —
reused, not minted: it is the existing "in-cluster sender → n8n agent webhook" identity (Alertmanager holds it for
`agent-alert`), and the receiving credential is the same n8n `agent-alert-token`. Whoever holds it can start
read-only agent runs, bounded by dedupe and `runs_per_day`; that is true for both senders, so one identity per role.
It is deliberately not `n8n/webhook-token` (held at the public edge). No header → 403; no Secret → the Provider is not
Ready and sends nothing.

**Path filter (deterministic, `src/agent-sec-path-filter.js`).** Once per revision, GitHub's public compare API
(`/repos/mtgibbs/pi-cluster/compare/<previous seen>...<sha>`, or `/commits/<sha>` the first time; unauthenticated,
60 requests/h is ample at one per revision) lists the changed files. Relevant when a file *path* is access-control
shaped (rbac/role/serviceaccount/networkpolicy/external-secret/secretstore/ingress/namespace/pod-security YAML; the
`agents`, `harness-fleet`, `flux-system`, `flux-notifications`, `external-secrets*`, `cloudflare-tunnel`,
`tailscale*`, `ingress`, `cert-manager-config` directories; `docs/secrets-overlay.yaml`), or when an added/removed line
of a YAML file under `clusters/` carries an access-control keyword (`kind: Role…`, `securityContext`, `privileged`,
`host*`, `capabilities`, `automountServiceAccountToken`, `serviceAccountName`, `secretKeyRef`/`secretRef`/`envFrom`/
`remoteRef`, `ipBlock`/`namespaceSelector`/`podSelector`, `verbs:`, `subjects:`, …). An image-tag bump is not.
It **fails toward review**: a non-200 answer, a list of ≥ 300 files, or a YAML patch GitHub omitted all count as
relevant (bounded by `runs_per_day: 6`). Why GitHub and not the cluster: the repo is public, the call needs no
credential, and n8n already has internet egress; the alternative (diffing two source-controller artifacts inside
n8n) needs a tar reader in a Code node and a policy hole from n8n to source-controller. Known gap: a refused run
(cap, pause) is not retried for that revision — the next relevant revision compares from it, and the weekly sweep
covers the whole tree.

**Model per trigger.** The manifest's `model.by_event_type` gives `security.sweep` `[claude-sonnet, claude-haiku]`;
every other type uses `allow: [claude-haiku]`. The runner resolves it per event (CONTRACT §2/§4), so n8n chooses the
model only by choosing the event type.

### The exit point (`src/agent-sec-plan-items.js`, `agent-sec-decide.js`, `agent-sec-summarize.js`)

- **The plans repo** is the constant `PLANS_REPO = 'mtgibbs/homelab-plans'` at the top of `agent-sec-plan-items.js`;
  `Issue Pages` and `Decide` take it from that node's output. Change it there only, then regenerate the JSON.
- **Fingerprint**: `sha256("sec-researcher|<rule>|<resource>")`, written as the **first line** of the issue body,
  `<!-- sec-researcher-fingerprint: <hex> -->`, plus a content hash on line 2. Only a marker at the very start counts,
  and agent text cannot produce one (prose has `<` escaped; evidence has `<!--` broken).
- **Lookup**: `GET /repos/<PLANS_REPO>/issues?state=all&per_page=100&sort=created&direction=asc&page=1..5` (PRs
  ignored). If any page fails, nothing is filed and the push says so; if all 5 pages are full (> 500 issues),
  nothing *new* is filed (updates still are).
- **Decision per plan, most severe first**: labelled `accepted-risk` (any state) → **skip**; open → **update** the body
  (PATCH `body` only — never title, state or labels) when the content hash differs, else **unchanged** (no call);
  closed as *not planned* → **skip**; otherwise (none, or only closed as *completed*, i.e. it came back — the new
  issue links the old one) → **create** with labels `sec-researcher`, `severity:<s>`, at most **5** per run; the
  rest are **not filed** and listed in the push.
- **Issue text** comes from the structured fields only: `[sec][<severity>] <title>`; severity/rule/resource line; a
  "written by a model from untrusted inputs" note; the seven sections; a footer with run id, revision and how to
  accept the risk. Agent prose is neutralised (HTML escaped; brackets, backslashes and backticks escaped; `@` and `#` broken with a zero-width
  space so there are no mentions or cross-references; `://` and `www.` broken so nothing autolinks); evidence goes
  verbatim inside a fence longer than any backtick run in it. Bodies stay under GitHub's 65,536-char limit.
- **Ledger**: `agent_runs` as for every agent (plan items stored in `outputs`), plus one row per plan per run in
  `agent_plan_filings (run_id, fingerprint, rule, resource, severity, action, issue_number, issue_url, http_status,
  detail)`; `action` ∈ create, update, unchanged, skip_accepted, not_filed, create_failed, update_failed. Issue
  numbers/URLs come from GitHub's response and are re-validated against `https://github.com/<PLANS_REPO>/issues/<n>`.
- **Push**: one per run, `sec-researcher: <outcome> - <N> new, <M> updated - <trigger>`; body: the agent's summary,
  the counts, up to 5 "not filed" titles with the reason, failures. Priority 4 for a new high/critical or a failure,
  3 for other new issues, 2 otherwise. A refused launch is one `sec-researcher: not started - …` push.

```sql
-- what happened to each finding
SELECT created_at, run_id, action, severity, rule, resource, issue_url, detail
FROM agent_plan_filings ORDER BY created_at DESC LIMIT 20;
```

### Must exist before activation

| What | Where | Notes |
|---|---|---|
| Private repo **`mtgibbs/homelab-plans`** | GitHub | Issues enabled. Not created by this PR. Until it exists, `List Issues` gets 404 and every run reports "not filed: issue lookup failed (HTTP 404)". |
| Credential **`github-plans`** | n8n, Header Auth | Name `Authorization`, value `Bearer <token>`; token = fine-grained PAT, **Issues read/write on `mtgibbs/homelab-plans` only**. Keep the source of truth in 1Password (e.g. `pi-cluster/github-plans/token`). Set the credential's allowed domains to `api.github.com`. Placeholder id `REPLACE_ON_IMPORT_github_plans`. |
| Credential **`agent-alert-token`** | n8n | Exists from slice 2 (same value Flux now sends). Placeholder `REPLACE_ON_IMPORT_agent_alert_token`. |
| Credential **`agent-runner`** | n8n | Exists. Placeholder `REPLACE_ON_IMPORT_agent_runner`. |
| `intake-db`, `ntfy-family` | n8n | Exist; ids kept. |
| Tables `agent_runs`, `agent_dedupe`, `agent_plan_filings` | n8n Postgres | Created by `Ensure Tables`. |
| Runner ≥ 0.4.0 (+ Role `flux-system/agent-runner-checkout-source`), runtime ≥ 0.2.1, manifest `sec-researcher`, LiteLLM key `agent-sec-researcher` | cluster | `clusters/pi-k3s/agents/README.md` checklist. A runner < 0.3.0 answers 422 → a "not started" push; runner 0.3.0 launches form/sweep runs that fail "latest artifact not found (HTTP 404)". |

### Import (manual rollout, in order)

1. **Create the private repo** `mtgibbs/homelab-plans` (GitHub UI or `gh repo create mtgibbs/homelab-plans --private`).
2. **Mint the GitHub token** (fine-grained, that one repo, Issues: read and write) and **store it in 1Password**.
3. **Mint the LiteLLM key** `agent-sec-researcher` (`[claude-haiku, claude-sonnet]`, $3/day) into
   `homelab-agent/agent-sec-researcher/litellm-key` — before merging (the `agents` Kustomization waits on it).
4. **Merge** this PR; let CI push the images and Flux roll the runner (agents README, step 5).
5. **Create the n8n credential** `github-plans` (Header Auth; value read from 1Password into a variable, never typed
   inline): `POST /api/v1/credentials` `{"name":"github-plans","type":"httpHeaderAuth","data":{"name":"Authorization","value":"Bearer …"}}`.
6. **Import the workflow**: patch the three `REPLACE_ON_IMPORT_*` ids in `agent-sec-researcher.json`,
   `POST /api/v1/workflows`, then `POST /api/v1/workflows/<id>/activate`.
7. **Roll the webhook tier** so `/webhook/agent-sec-revision` is registered there (bump `n8n.mtgibbs.dev/restarted-at`
   in `n8n/webhook.yaml`, PR, reconcile — the publish dance). Until then Flux's POSTs get 404 (notification-controller
   logs a failed send; nothing else is affected). The form and the schedule run on main and work right after step 6.

### Test plan

1. **Form** (`https://n8n.lab.mtgibbs.dev/form/agent-sec-run`, focus "the agents namespace NetworkPolicies"): one
   execution waiting → success, one `agent_runs` row, `agent_plan_filings` rows, issues in `homelab-plans` with the
   marker on line 1, one push.
2. **Re-run the same focus**: rows say `unchanged` or `update`; no new issues for the same findings.
3. **Accepted risk**: close one issue as *not planned* (or add `accepted-risk`), re-run: `skip_accepted`, the issue
   stays closed and unedited.
4. **Cap**: a broad manual focus that yields > 5 findings: exactly 5 created, the rest listed as "not filed" in the
   push and `not_filed` in the table.
5. **Flux, not relevant**: merge an image-tag-only PR. Expect ONE `agent-sec-researcher` execution (the
   GitRepository's `NewArtifact` event; a failure-recovery `Succeeded` event for the same sha would end at
   `Claimed?`), ending at `Relevant?` (false); no run. With no merges, no executions at all.
6. **Flux, relevant**: merge a PR touching a `networkpolicies.yaml`. Expect exactly one run, event
   `security.flux_revision` with that file in `data.changed_paths`, and the checkout init container log
   `"served": "<sha>.tar.gz"`. `checkout_attempt` lines before it with `outcome: "error"` mean the pod's first
   connections were refused and retried (agent-runtime ≥ 0.2.1); more than a couple on every run is worth a look.
7. **Auth**: POST `/webhook/agent-sec-revision` without the header, or with `Bearer wrong` → 403, no execution.
8. **Lookup failure**: temporarily revoke the token → the push says "not filed: issue lookup failed (HTTP 401)",
   nothing is created.
9. **Weekly sweep**: run the workflow's schedule node by hand once; a second manual fire the same week ends at
   `Claimed?`. The sweep's run uses Sonnet (`model_reply` log lines in the Job show `claude-sonnet`).

### Verify against the live n8n (can't be settled offline)

- That HTTP Request v4.2 accepts an expression for `method` (`Apply` uses `={{ $json.method }}`), and that
  `List Issues` returns one output per page item with `fullResponse` (array body intact).
- That `$('Split Actions').all()` in Summarize lines up with Apply's outputs (both in item order).
- That the GitRepository event arrives as read from source (source-controller v1.7.4 `notify()`, notification-controller
  v1.7.5 `combineEventMetadata`): `involvedObject.kind: GitRepository`, `severity: info`, `reason: NewArtifact`,
  `message: "stored artifact for commit '…'"`, `metadata.revision: main@sha1:<sha>` (group prefix trimmed). The
  parser also accepts the prefixed key, a bare sha and the old Kustomization shape; anything else is ignored
  silently — check an execution's input if Flux runs never start.

**Why the Alert watches the GitRepository, not Kustomizations (fixed 2026-11-13).** The first Alert matched
`Kustomization *`. kustomize-controller emits `ReconciliationSucceeded` ("Reconciliation finished in …, next run in
10m0s") on every reconcile, changed or not: 42 Kustomizations ≈ 250 POSTs/hour, 707 executions in under 3 h, every
one dropped at `Claim`. source-controller emits an info event for a GitRepository only on a new artifact (or on
recovery from a failure), so the Alert now names `GitRepository flux-system` with `inclusionList: ["^stored artifact
for commit"]` (which also keeps fetch-failure error events out). The per-sha `Claim` stays as defence in depth.

**Checkout revision for form/sweep runs.** These events carry no revision. The runner (≥ 0.4.0) reads the sha
source-controller currently serves from the GitRepository and checks that out; source-controller has no
`latest.tar.gz` (a form run on runner 0.3.0 failed "latest artifact not found (HTTP 404)"). n8n passes nothing
extra. If the runner cannot read it, the launch answers 502 "no repository revision to check out …" and the push
says "not started" with that text (`scripts/agentrunner/CONTRACT.md` §4a).

