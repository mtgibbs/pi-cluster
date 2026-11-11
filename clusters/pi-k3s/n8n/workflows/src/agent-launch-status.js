// Turn the runner's answer to POST /runs into a push. Input is either the HTTP Request's full
// response ({statusCode, body}, neverError on) or its error output ({error}) when the runner was
// unreachable. In agent-run-manual.json only non-202 answers get here; in the async variant every
// answer does, and 202 means "launched, the result will arrive via agent-result".
const r = $input.first().json || {};
let agent = '', ev = {};
try { const b = $('Build Event').first().json; agent = b.agent || ''; ev = b.event || {}; } catch (e) {}

const code = Number(r.statusCode || 0);
const body = (r.body && typeof r.body === 'object') ? r.body : {};
const detail = String(typeof r.body === 'string' ? r.body : (body.error || body.detail || body.message || '')).slice(0, 300);
const WHY = {
  200: 'this event was already launched earlier; its result goes to the original requester',
  401: 'runner rejected the bearer token (check the agent-runner credential)',
  404: 'runner does not know this agent',
  422: 'runner rejected the manifest, event, or callback URL',
  429: 'daily run cap or cluster quota reached — try later',
  503: 'runner is paused (RUNNER_PAUSED=true)',
};

let title, message, tags = 'warning', priority = '4';
if (r.error) {
  const e = typeof r.error === 'object' ? (r.error.message || JSON.stringify(r.error)) : String(r.error);
  title = `${agent}: not started`;
  message = `Could not reach agent-runner: ${String(e).slice(0, 300)}`;
} else if (code === 202) {
  title = `${agent}: started`;
  message = `Run ${String(body.run_id || '?').slice(0, 128)} launched; the result will be pushed when it finishes.`;
  tags = 'hourglass_flowing_sand'; priority = '2';
} else {
  title = `${agent}: not started (HTTP ${code || '?'})`;
  message = (WHY[code] || 'unexpected runner response') + (detail ? `\n${detail}` : '');
}
message += `\nevent ${ev.id || '?'}`;
return [{ json: { title, message, tags, priority } }];
