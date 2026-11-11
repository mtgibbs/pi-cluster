// Normalise a runner callback (CONTRACT.md §3) into one agent_runs ledger row.
// Shared by agent-run-manual.json (input = the Wait node's webhook item) and agent-result.json
// (input = the Webhook item, possibly via Ensure Table). Everything in the body is DATA: it is
// clipped, type-checked, and later bound as ONE jsonb parameter — never concatenated into SQL.
const OUTCOMES = ['done', 'nothing_to_do', 'needs_human', 'failed'];
const EXIT_REASONS = ['completed', 'deadline', 'job_failed', 'no_result', 'invalid_result'];

let body = ($input.first().json || {}).body;
if (!body || typeof body !== 'object') {
  try { body = $('Result Webhook').first().json.body; } catch (e) { /* not the agent-result workflow */ }
}
if (!body || typeof body !== 'object') throw new Error('Callback has no JSON body');

const str = (v, n) => (typeof v === 'string' ? v : (v === undefined || v === null ? '' : String(v))).slice(0, n);
const ts = (v) => {
  if (v === undefined || v === null || v === '') return null;
  let d;
  if (typeof v === 'number') d = new Date(v < 1e12 ? v * 1000 : v);   // epoch seconds or ms
  else d = new Date(String(v));
  return isNaN(d.getTime()) ? null : d.toISOString();
};

const run_id = str(body.run_id, 128).trim();
if (!/^[A-Za-z0-9._:-]{1,128}$/.test(run_id)) throw new Error('Callback run_id missing or malformed');

const result = (body.result && typeof body.result === 'object') ? body.result : {};
const exit_reason = EXIT_REASONS.includes(body.exit_reason) ? body.exit_reason : str(body.exit_reason || 'unknown', 64);
const outcome = OUTCOMES.includes(result.outcome) ? result.outcome : 'failed';
const outputs = (Array.isArray(result.outputs) ? result.outputs : [])
  .filter(o => o && typeof o === 'object')
  .slice(0, 20)
  .map(o => ({ kind: str(o.kind, 64), title: str(o.title, 300), body: str(o.body, 32768) }));

// event type/subject are not in the callback; take them from this execution's Build Event when
// it exists (manual/Wait flow), else from body.event if the runner ever includes it, else null.
let ev = null;
try { ev = $('Build Event').first().json.event; } catch (e) { ev = (body.event && typeof body.event === 'object') ? body.event : null; }

return [{ json: {
  run_id,
  agent: str(body.agent, 64),
  event_id: str(body.event_id || (ev && ev.id), 128) || null,
  event_type: ev ? str(ev.type, 128) : null,
  subject: ev ? str(ev.subject, 200) : null,
  started: ts(body.started),
  finished: ts(body.finished),
  exit_reason,
  outcome,
  summary: str(result.summary, 2048),
  outputs,
} }];
