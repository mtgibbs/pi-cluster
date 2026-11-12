// sec-researcher's copy of agent-parse-result.js: the same ledger row, but `plan` outputs keep their STRUCTURE
// (severity, fingerprint, the seven sections) instead of being flattened to kind/title/body — n8n files issues
// from those fields. Everything is clipped and type-checked here; Plan Items re-validates before filing.
const OUTCOMES = ['done', 'nothing_to_do', 'needs_human', 'failed'];
const EXIT_REASONS = ['completed', 'deadline', 'job_failed', 'no_result', 'invalid_result', 'queue_expired'];
const SECTIONS = ['found', 'evidence', 'likely_cause', 'proposed_change', 'risk', 'verify', 'rollback'];

const body = ($input.first().json || {}).body;
if (!body || typeof body !== 'object') throw new Error('Callback has no JSON body');
const str = (v, n) => (typeof v === 'string' ? v : (v === undefined || v === null ? '' : String(v))).slice(0, n);
const ts = (v) => {
  if (v === undefined || v === null || v === '') return null;
  const d = typeof v === 'number' ? new Date(v < 1e12 ? v * 1000 : v) : new Date(String(v));
  return isNaN(d.getTime()) ? null : d.toISOString();
};
const run_id = str(body.run_id, 128).trim();
if (!/^[A-Za-z0-9._:-]{1,128}$/.test(run_id)) throw new Error('Callback run_id missing or malformed');

const result = (body.result && typeof body.result === 'object') ? body.result : {};
const exit_reason = EXIT_REASONS.includes(body.exit_reason) ? body.exit_reason : str(body.exit_reason || 'unknown', 64);
const outcome = OUTCOMES.includes(result.outcome) ? result.outcome : 'failed';
const obj = v => (v && typeof v === 'object' && !Array.isArray(v)) ? v : {};
const outputs = (Array.isArray(result.outputs) ? result.outputs : [])
  .filter(o => o && typeof o === 'object')
  .slice(0, 20)
  .map(o => {
    if (o.kind !== 'plan') return { kind: str(o.kind, 64), title: str(o.title, 300), body: str(o.body, 32768) };
    const fp = obj(o.fingerprint), plan = obj(o.plan);
    const sections = {};
    for (const k of SECTIONS) sections[k] = str(plan[k], k === 'evidence' ? 8192 : 4096);
    return { kind: 'plan', title: str(o.title, 200), severity: str(o.severity, 16),
             fingerprint: { rule: str(fp.rule, 64), resource: str(fp.resource, 320) }, plan: sections };
  });

let ev = null;
try { ev = $('Build Event').first().json.event; } catch (e) { ev = null; }
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
