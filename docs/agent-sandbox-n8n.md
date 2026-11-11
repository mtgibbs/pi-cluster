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
`clusters/pi-k3s/monitoring/helmrelease.yaml`) and pushes the outcome to the same `agent-runs` topic.

```
Alert Webhook   POST /webhook/agent-alert, Header Auth (agent-alert-token), answers 200 at once
  → Build Event     src/agent-alert-build-event.js: ONE event per group; no items (silent end) if
                    status != firing or every alert is Watchdog / InfoInhibitor / KubeMemoryOvercommit
  → Ensure Tables   agent_runs (same DDL as the manual flow) + agent_dedupe
  → Claim           atomic cooldown claim on dedupe_key (6 h); returns {claimed}
  → Claimed?        false → end (silent: no ledger row, no push)
  → Resume Callback → Launch Run → Launched? → Wait for Result → Callback? → Parse Result / Timeout Row
    → Insert Ledger → Format Push → Alert Title → Push            (shared src/agent-*.js, unchanged)
  Launch Run error / Launched? false
    → Refusal Row (exit_reason refused_<HTTP> | runner_unreachable) → Insert Refusal (+ prior_same)
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
`run_id nolaunch-<event id>`, `outcome failed`.

### Must exist before activation

| What | Where | Notes |
|---|---|---|
| Credential **`agent-alert-token`** | n8n, type *Header Auth* (httpHeaderAuth) | Name `Authorization`, Value `Bearer <token>` — the token is 1Password `pi-cluster/n8n-agent-alert-webhook` field `token`, the value Alertmanager reads from Secret `alertmanager-n8n-agents`. Placeholder id `REPLACE_ON_IMPORT_agent_alert_token`. |
| Credential **`agent-runner`** | n8n | Already created for the manual flow; re-link placeholder `REPLACE_ON_IMPORT_agent_runner`. |
| `intake-db`, `ntfy-family` | n8n | Exist; ids kept in the JSON. |
| Tables `agent_runs`, `agent_dedupe` | n8n Postgres | Created by `Ensure Tables` on first execution. |
| Manifest `ops-investigator` | `clusters/pi-k3s/agents/manifests/` | Otherwise every launch is a quiet `refused_404`. |

The Webhook node fails closed: a missing or wrong `Authorization` header gets **403** and no execution;
past the trigger; with no credential linked the node errors and nothing runs. Keep the n8n Wait limit (30 min)
above the manifest's `limits.timeout` (15 m) + 300 s runner grace + Job start-up.

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
