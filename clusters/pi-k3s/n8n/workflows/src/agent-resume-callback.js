// Derive an IN-CLUSTER resume URL for the "Wait for Result" node and attach it as `callback`.
//
// $execution.resumeUrl is "<WEBHOOK_URL>webhook-waiting/<executionId>?signature=<resumeToken>".
// WEBHOOK_URL is the PUBLIC tunnel host, which only passes ^/webhook/inbound-mail.* — so we
// keep n8n's path + query (the signature IS the per-execution auth; n8n 2.x rejects a resume
// without it: 401 {"error":"Invalid token"}) and swap the origin for the webhook tier's
// in-cluster Service. Both the main and the webhook process serve /webhook-waiting/*
// (N8N_DISABLE_PRODUCTION_MAIN_PROCESS is unset); waiting executions are looked up in
// Postgres by id, so no activation/registration is involved and no webhook-tier roll is needed.
const CALLBACK_ORIGIN = 'http://n8n-webhook.n8n.svc.cluster.local:5678';

const resumeUrl = String($execution.resumeUrl || '');
const m = resumeUrl.match(/^https?:\/\/[^/]+(\/.*)$/);
if (!m) throw new Error(`Unexpected $execution.resumeUrl shape: "${resumeUrl}"`);
const pathAndQuery = m[1];

// Fail now, not 30 minutes from now: the URL must be /webhook-waiting/<this execution>?…signature=…
const shape = pathAndQuery.match(/^\/webhook-waiting\/([^/?#]+)\?(?:[^#]*&)?signature=[^&#]+/);
if (!shape) {
  throw new Error('resumeUrl is not "/webhook-waiting/<id>?signature=<token>" at the root of WEBHOOK_URL — '
    + 'n8n changed its resume-URL shape or WEBHOOK_URL gained a path; see docs/agent-sandbox-n8n.md');
}
if (String(shape[1]) !== String($execution.id)) {
  throw new Error(`resumeUrl execution id ${shape[1]} != $execution.id ${$execution.id}`);
}

const item = $input.first().json;
return [{ json: { ...item, callback: CALLBACK_ORIGIN + pathAndQuery } }];
