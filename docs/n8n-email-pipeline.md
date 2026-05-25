# n8n Email Ingestion Pipeline

**Status:** 2026-05-25 — working end-to-end **through extraction**. Inbound mail →
Cloudflare → R2 + durable n8n queue → Qwen extraction → structured records. Storage +
PDF/docx + Peachjar/site branches are the remaining work (see [Remaining](#remaining-work)).

**What this is:** a *general* ingestion pipeline. Forward email to `intake@mtgibbs.dev`
(school is use case #1; ads/community/civic/bills to follow) → it's parsed at the edge,
durably queued, and a local LLM extracts structured "actionable item" records.

> ⚠️ **Why this doc exists:** most of this stack is GitOps, but the **Cloudflare edge,
> the secrets, the Worker, and the n8n workflow/credentials are NOT Flux-managed.** If we
> rebuild, those are manual. This is the runbook for the human/out-of-band parts.

---

## Architecture

```
Inbound mail → intake@mtgibbs.dev
  → Cloudflare Email Routing  (custom address → Worker)        [MANUAL/dashboard]
  → Email Worker (mtgibbs-mail-worker)                          [wrangler, NOT Flux]
       • parse RFC822 (postal-mime)
       • attachments → R2 bucket (refs only in payload)
       • POST refs-only JSON → n8n-hook + x-auth-token; throw on fail (sender retries)
  → Cloudflare Tunnel: n8n-hook.mtgibbs.dev                     [IaC: tunnel ConfigMap]
       • PATH-RESTRICTED to ^/webhook/inbound-mail.*$ (rest → 404)
  → n8n webhook tier → Valkey queue (Bull, AOF) → n8n worker    [IaC: clusters/pi-k3s/n8n]
       • Build Request → LiteLLM (Beelink Qwen) → Parse Records
  → (next) Postgres intake_items table → dashboard
PostgreSQL (n8n's own) backs executions/workflows/credentials.
R2 = attachment staging (48h lifecycle auto-delete).
Beelink LiteLLM = sovereign extraction (https://ai.lab.mtgibbs.dev/v1).
```

**Durability rings:** Worker `throw` → sender retries · Valkey AOF persistence · Bull
re-queue on worker death. Each execution runs start-to-finish on one worker.

---

## What's IaC (in this repo, Flux-managed)

| Path | What |
|---|---|
| `clusters/pi-k3s/n8n/` | namespace, external-secret, **configmap** (tinker knobs), postgresql, valkey, deployment (main), worker, webhook, service, ingress, servicemonitor |
| `clusters/pi-k3s/n8n/workflows/` | workflow JSON (IaC) + readable `src/*.js` Code-node sources |
| `clusters/pi-k3s/cloudflare-tunnel/config.yaml` | tunnel ingress rules (incl. n8n-hook path restriction, UI off-public) |
| `edge/email-worker/` | Worker source — **deployed via wrangler, NOT Flux** |

> n8n runs **queue mode**: main + worker(×1, concurrency 3) + webhook(×1) + valkey(AOF) +
> postgres. Knobs live in `configmap.yaml` (`n8n-config`, shared via `envFrom`).

---

## What's MANUAL / out-of-band — THE HUMAN RUNBOOK

Rebuild order. Each section is "you (or Claude driving op/CLI/API)", **not Flux**.

### A. 1Password secrets (vault `pi-cluster`)
Two items:
- **`n8n`** (cluster-synced via the `n8n-secret` ExternalSecret):
  `encryption-key` (KEEP forever — losing it = losing stored credentials), `db-password`
  (`openssl rand -hex 24`), `webhook-token` (`openssl rand -hex 32`), `r2-access-key-id`,
  `r2-secret-access-key`, `license-key` (n8n, optional/unused).
- **`n8n-automation`** (ops tokens, read directly — NOT synced): `cf-workers-token`,
  `n8n-api-key`, `litellm-key`.

### B. Cloudflare R2 (dashboard — `dash.cloudflare.com` → R2)
1. Create bucket **`mtgibbs-mail-attachments`** (location Automatic).
2. Settings → Object lifecycle rules → add `expire-inbound`: prefix `inbound/`, **Delete
   uploaded objects after 2 days**.
3. **Create Account API token** (R2 → Manage R2 API Tokens): name `n8n-binary-backend`,
   **Object Read & Write**, scoped to the bucket. Copy **Access Key ID** + **Secret** →
   1Password `n8n` (`r2-access-key-id`, `r2-secret-access-key`). Endpoint host =
   `<account-id>.r2.cloudflarestorage.com` (account `8b93ae435cb999b141bb950cb781ae67`).

### C. Cloudflare Email Routing (dashboard — domain `mtgibbs.dev` → Email → Email Routing)
1. **Get started** → add a destination address (a real inbox, e.g. a Gmail `+alias`) →
   **click the verification link** it emails.
2. **Enable Email Routing** → auto-adds apex MX + SPF + DKIM. (Doesn't touch
   `send.mtgibbs.dev` SES — that's a subdomain.)
3. **Email Workers / Routing rules:** create a **Custom address** `intake@mtgibbs.dev` →
   Action **Send to a Worker** → `mtgibbs-mail-worker`. (Use specific addresses, NOT
   catch-all — the recipient address doubles as a category tag.)

### D. Cloudflare API token for Workers (dashboard — My Profile → API Tokens)
The default `cloudflare` 1Password token is **DNS-only**. Mint a custom token:
`Workers Scripts:Edit` + `Workers R2 Storage:Edit` + `Account Settings:Read`. Store →
`n8n-automation/cf-workers-token`.

### E. Deploy the Email Worker (wrangler — `edge/email-worker/`)
```bash
cd edge/email-worker && npm install
export CLOUDFLARE_API_TOKEN=$(op read op://pi-cluster/n8n-automation/cf-workers-token)
export CLOUDFLARE_ACCOUNT_ID=8b93ae435cb999b141bb950cb781ae67
npx wrangler deploy            # workers_dev=false (email-triggered, no HTTP route)
printf '%s' "https://n8n-hook.mtgibbs.dev/webhook/inbound-mail" | npx wrangler secret put N8N_WEBHOOK_URL
op read op://pi-cluster/n8n/webhook-token | npx wrangler secret put N8N_TOKEN
```
The inbound route (Custom address → this Worker) is bound in the dashboard (step C3) —
`cf-workers-token` lacks Email Routing scope.

### F. n8n owner account (UI)
After deploy, browse `https://n8n.lab.mtgibbs.dev` (LAN only) → create the owner account
(fresh Postgres = first-run setup).

### G. n8n API key (UI → Settings → n8n API → Create) → `n8n-automation/n8n-api-key`.

### H. Beelink LiteLLM key for n8n (mint, don't reuse master)
```bash
MK=$(op read op://pi-cluster/litellm-master-key)   # field credential/password
curl -s -X POST https://ai.lab.mtgibbs.dev/key/generate -H "Authorization: Bearer $MK" \
  -d '{"key_alias":"n8n-intake"}' | jq -r .key      # → store n8n-automation/litellm-key
```

### I. n8n credentials + workflow (via n8n REST API, key from G)
Created programmatically (see commit history / `workflows/`):
- Credential `inbound-mail-token` (httpHeaderAuth, `x-auth-token` = webhook-token).
- Credential `litellm-intake` (httpHeaderAuth, `Authorization: Bearer <litellm-key>`,
  **`allowedHttpRequestDomains:"all"`** or schema rejects).
- Credential `intake-db` (postgres → `n8n-postgresql`, **`sshTunnel:false`** required).
- Workflow `Inbound Mail — Intake`: `POST /api/v1/workflows` then `/activate`.

---

## Operational runbooks ("publish" dances)

> Two components **do not hot-reload**. Treat changes to them as deployments.

### Tunnel config change → roll cloudflared
cloudflared reads `config.yaml` **only at process start**. After editing
`cloudflare-tunnel/config.yaml`, bump the `config.mtgibbs.dev/reloaded-at` annotation in
`cloudflare-tunnel/deployment.yaml`, commit, and reconcile so Flux rolls the pod.
*(Symptom of forgetting: new tunnel hostnames 404; removed ones still route.)*

### Activate/publish a workflow → roll the n8n webhook tier
n8n doesn't reliably push new workflow **activations** to dedicated webhook pods. On
publish, bump `n8n.mtgibbs.dev/restarted-at` in `n8n/webhook.yaml`, commit, reconcile.
Safe (queue persists in-flight work; incoming mail retries). **NOT needed for workflow
*body* edits** — workers read the workflow from the DB at execution time.

### Flux dependency cascade
Every commit re-gates `n8n` (and `cloudflare-tunnel`) behind `external-secrets-config` +
`cert-manager-config`. Reconcile **those two first**, wait ~30s, then reconcile the target
— don't reconcile all 29 at once (churns the whole graph). No local kubectl; cluster is
MCP-only (`mcp__homelab__*`), and n8n/cloudflared are NOT on the `restart_deployment`
whitelist (hence the annotation-bump restarts above).

### Swap the extraction model
Edit the `model` field in `workflows/src/build-request.js` → reimport the workflow via the
API. Must be an **`-instruct`** model (default `qwen3-30b-instruct`). A/B candidates:
`qwen3-4b-instruct` (fast) ↔ `qwen2.5-72b` (quality).

### Test without re-forwarding
Replay a captured execution's body to the production webhook:
```bash
KEY=$(op read op://pi-cluster/n8n-automation/n8n-api-key); TOK=$(op read op://pi-cluster/n8n/webhook-token)
curl -sk "https://n8n.lab.mtgibbs.dev/api/v1/executions/<ID>?includeData=true" -H "X-N8N-API-KEY: $KEY" \
 | jq '.data.resultData.runData."Inbound Mail Webhook"[0].data.main[0][0].json.body' > /tmp/replay.json
curl -sk -X POST https://n8n-hook.mtgibbs.dev/webhook/inbound-mail -H "x-auth-token: $TOK" \
 -H 'content-type: application/json' --data @/tmp/replay.json
```

---

## Gotchas / hard-won lessons

- **S3 binary mode = Enterprise license.** `N8N_DEFAULT_BINARY_DATA_MODE=s3` crash-loops
  community n8n fatally. We use default filesystem mode; attachments go to R2 via the
  *edge Worker* + an n8n S3 *credential*, not n8n's binary backend.
- **Hybrid-thinking models return empty content** via Ollama's OpenAI endpoint (`qwen3.5-9b`
  gave `""`). Use `-instruct` variants for extraction.
- **cloudflared / webhook-tier don't hot-reload** (see runbooks above).
- **n8n public API credential schemas** have conditional-required quirks: httpHeaderAuth
  needs `allowedHttpRequestDomains`, postgres needs `sshTunnel:false`.
- **n8n webhook node** nests the POST body under `.body` (`json.body.subject`, etc.).
- **DNS-only `cloudflare` token** can't touch R2/Email Routing/Workers — needs scoped tokens.

---

## Extraction schema (the data contract)

One inbound message → an array of records (multiple types per email):
```json
{ "type":"date|dues|assignment|event|site-pointer|info", "title":"", "dueAt":"ISO-8601|null",
  "student":"ronin|rory|both|unknown", "actionRequired":true, "amount":"|null",
  "teacher":"|null", "class":"|null", "source_hint":"verbatim quote", "confidence":0.0,
  "source_channel":"intake@…","source_subject":"","source_from":"" }
```
The `type` field is the **action router**. `dueAt` + `student` power the "deadlines feed."
**site-pointer = detect & surface, never auto-fetch** (sidesteps SSRF/SPA; accumulate to
find patterns). Canvas cross-check (via the separate **CARL** item's Canvas creds) is a
far-future enrichment, decoupled.

---

## Corpus (real specimens, for building/testing Phase 7)

Captured in n8n executions (replayable). Distribution (n≈10): **HTML-body newsletters
dominate**; text-based PDFs (incl. "see attached letter" where body is empty); a `.docx`;
a **Peachjar** email (flyers are remote JPGs at `flyers-bff.peachjar.com/.../flyer/N.jpg`
→ vision/OCR, deferred). No scanned/image PDFs yet. Build priority: HTML-body → PDF/docx →
Peachjar-vision → site-pointer.

---

## Storage (DONE 2026-05-25)

Records persist to **`intake_items`** (in n8n's Postgres). The workflow has `Ensure Table`
(CREATE TABLE IF NOT EXISTS) + `Store` (Postgres insert, autoMap). Deadline feed query:
```sql
SELECT id, due_at, type, title, student, action_required, source_subject
FROM intake_items WHERE due_at IS NOT NULL ORDER BY due_at;
```
Columns: id, received_at, type, title, due_at, student, action_required, amount, teacher,
course, source_hint, confidence, source_channel, source_subject, source_from.
> ⚠️ No dedup yet — replays/re-sends append duplicate rows. Add an idempotency key
> (e.g. unique on source_from+title+due_at, or hash) before heavy use.

## Exposed read API (for the dashboard / smart board)

`GET https://n8n.lab.mtgibbs.dev/webhook/feed` → JSON array of `intake_items`
(ordered by `due_at`, nulls last, limit 500). **LAN-only** (NOT on the public tunnel),
**CORS-open** (`Access-Control-Allow-Origin: *`) so a browser app can fetch it. Workflow
`Feed API (read intake_items)` (id `XW6Ie2Ui3AOLkjSu`), IaC in `workflows/feed-api.json`.
> ⚠️ **No auth** (LAN-trusted v1). Add a header token + CORS preflight (OPTIONS) handling
> before exposing beyond the LAN. This is the interim surface; the fuller Family Board API
> (`/event`/`/task`/`/note` writes, etc.) is a separate plan.

## Remaining work

1. ✅ ~~Storage~~ — done (see above).
2. ✅ ~~Read API exposed~~ — `GET /webhook/feed` (see above).
2. **PDF/docx branch** — fetch bytes from R2 (`r2Key`) → Extract-from-File → same extraction.
3. **Peachjar image flyers** — fetch JPG → vision model (deferred; recurring).
4. **Site-pointer** — detect & surface; filter signal links from tracking/footer noise.
5. **Dashboard** — read `intake_items`, render the deadline feed.
