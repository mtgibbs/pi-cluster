// The Wait node resumed on its 80-minute limit, not on a callback. 80 = RUNNER_MAX_QUEUE_WAIT (45m) +
// sec-researcher's timeout (20m) + the runner's 5m deadline grace + ~10m for polling and callback retries.
// The Wait's output is its INPUT (the runner's 202), so run_id is known. A late callback can no longer resume
// this execution (409); the runner keeps its record at GET /runs/<run_id>. No plans are filed for it.
const r = $input.first().json || {};
const launched = (r.body && typeof r.body === 'object') ? r.body : {};
let ev = {}, agent = '';
try { const b = $('Build Event').first().json; ev = b.event || {}; agent = b.agent || ''; } catch (e) {}
const run_id = String(launched.run_id || '').slice(0, 128);
if (!run_id) throw new Error('Timed out, and the launch response had no run_id');
return [{ json: {
  run_id, agent, event_id: ev.id || null, event_type: ev.type || null, subject: ev.subject || null,
  started: null, finished: new Date().toISOString(), exit_reason: 'callback_timeout', outcome: 'failed',
  summary: 'No callback from agent-runner within 80 minutes. Check GET /runs/' + run_id
    + ' on the runner and the Job run-' + run_id + ' in namespace agents. No plans were filed.',
  outputs: [],
} }];
