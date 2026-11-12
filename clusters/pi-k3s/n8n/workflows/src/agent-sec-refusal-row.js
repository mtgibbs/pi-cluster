// The runner did not start the run (non-202, or unreachable via the HTTP node's error output): ONE agent_runs
// row so it is visible, then the normal tail (one push). No retry: sec-researcher runs are few, a Flux revision
// is claimed once, and the weekly sweep re-covers anything a refused run missed.
const r = $input.first().json || {};
let agent = '', ev = {};
try { const b = $('Build Event').first().json; agent = b.agent || ''; ev = b.event || {}; } catch (e) {}
const code = Number(r.statusCode || 0);
const body = (r.body && typeof r.body === 'object') ? r.body : {};
const detail = String(typeof r.body === 'string' ? r.body : (body.error || body.detail || body.message || '')).slice(0, 300);
const WHY = {
  200: 'this event id was already launched earlier (unexpected: event ids are fresh per launch)',
  401: 'runner rejected the bearer token (check the agent-runner credential)',
  404: 'runner does not know this agent (is the sec-researcher manifest deployed?)',
  422: 'runner rejected the manifest, event, or callback URL (a runner older than 0.3.0 rejects the checkout/by_event_type keys)',
  429: 'daily run cap or cluster quota reached',
  502: 'runner hit a Kubernetes error launching the Job',
  503: 'runner is paused (RUNNER_PAUSED=true)',
};
let exit_reason, summary;
if (r.error) {
  const e = typeof r.error === 'object' ? (r.error.message || JSON.stringify(r.error)) : String(r.error);
  exit_reason = 'runner_unreachable';
  summary = `Not started: could not reach agent-runner: ${String(e).slice(0, 300)}`;
} else if (code === 429 && body.error === 'queue_full') {
  exit_reason = 'refused_queue_full';
  summary = `Not started (HTTP 429): runner queue is full${body.detail ? ` - ${String(body.detail).slice(0, 300)}` : ''}`;
} else {
  exit_reason = `refused_${code || 'unknown'}`;
  summary = `Not started (HTTP ${code || '?'}): ${WHY[code] || 'unexpected runner response'}${detail ? ` - ${detail}` : ''}`;
}
return [{ json: {
  run_id: `nolaunch-${String(ev.id || Date.now())}`.slice(0, 128),
  agent, event_id: ev.id || null, event_type: ev.type || null, subject: ev.subject || null,
  started: null, finished: new Date().toISOString(), exit_reason, outcome: 'failed',
  summary: summary.slice(0, 2048), outputs: [],
} }];
