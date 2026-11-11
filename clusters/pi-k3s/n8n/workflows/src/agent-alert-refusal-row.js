// The runner did not start the run (non-202, or unreachable via the HTTP node's error output). Turn that into
// ONE agent_runs ledger row so the refusal is visible, instead of retrying: Alertmanager re-sends anyway and the
// Claim cooldown already holds this group for its window. exit_reason names the refusal KIND
// (refused_429, refused_queue_full, refused_503, …, runner_unreachable); Insert Refusal counts earlier rows of the
// same kind so Refusal Push sends at most one quiet push per kind per window. A 429 whose body is
// {"error":"queue_full"} (runner 0.2.0+: every agent slot busy AND the wait queue full) is its own kind, so a
// burst-time queue_full does not silence the push for a later daily-cap 429 in the same window.
const r = $input.first().json || {};
let agent = '', ev = {};
try { const b = $('Build Event').first().json; agent = b.agent || ''; ev = b.event || {}; } catch (e) {}

const code = Number(r.statusCode || 0);
const body = (r.body && typeof r.body === 'object') ? r.body : {};
const detail = String(typeof r.body === 'string' ? r.body : (body.error || body.detail || body.message || '')).slice(0, 300);
const WHY = {
  200: 'this event id was already launched earlier (unexpected: alert event ids are fresh per launch)',
  401: 'runner rejected the bearer token (check the agent-runner credential)',
  404: 'runner does not know this agent (is the ops-investigator manifest deployed?)',
  422: 'runner rejected the manifest, event, or callback URL',
  429: 'daily run cap or cluster quota reached',
  queue_full: 'runner queue is full (every agent slot busy and the wait queue at its limit) - alert not investigated',
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
  summary = `Not started (HTTP 429): ${WHY.queue_full}${body.detail ? ` - ${String(body.detail).slice(0, 300)}` : ''}`;
} else {
  exit_reason = `refused_${code || 'unknown'}`;
  summary = `Not started (HTTP ${code || '?'}): ${WHY[code] || 'unexpected runner response'}${detail ? ` - ${detail}` : ''}`;
}

return [{ json: {
  run_id: `nolaunch-${String(ev.id || Date.now())}`.slice(0, 128),
  agent,
  event_id: ev.id || null,
  event_type: ev.type || null,
  subject: ev.subject || null,
  started: null,
  finished: new Date().toISOString(),
  exit_reason,
  outcome: 'failed',
  summary: summary.slice(0, 2048),
  outputs: [],
} }];
