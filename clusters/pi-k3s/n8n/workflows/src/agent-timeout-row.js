// The Wait node resumed on its 30-minute limit, not on a callback. Its output is then its INPUT
// (the runner's 202 response), so we still know run_id. Record the give-up in the ledger so the
// run is visible; a late callback can no longer resume this execution (n8n answers 409), but the
// runner keeps its own record: GET /runs/<run_id>.
const r = $input.first().json || {};
const launched = (r.body && typeof r.body === 'object') ? r.body : {};
let ev = {}, agent = '';
try { const b = $('Build Event').first().json; ev = b.event || {}; agent = b.agent || ''; } catch (e) {}

const run_id = String(launched.run_id || '').slice(0, 128);
if (!run_id) throw new Error('Timed out, and the launch response had no run_id');

return [{ json: {
  run_id,
  agent,
  event_id: ev.id || null,
  event_type: ev.type || null,
  subject: ev.subject || null,
  started: null,
  finished: new Date().toISOString(),
  exit_reason: 'callback_timeout',
  outcome: 'failed',
  summary: 'No callback from agent-runner within 30 minutes. Check GET /runs/' + run_id
    + ' on the runner and the Job run-' + run_id + ' in namespace agents.',
  outputs: [],
} }];
