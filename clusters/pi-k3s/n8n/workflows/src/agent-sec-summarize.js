// The end of every sec-researcher run that produced a ledger row: ONE ntfy push summarising it, and the
// filing rows for agent_plan_filings. Reached from three places (exactly one per execution):
//   Has Plans? false (no plans: a clean run, a failure, a refusal)  — input = Plan Items' item
//   Any Actions? false (plans, but nothing to create/update)        — input = Decide's item
//   Apply (one response per create/update, same order as Split Actions)
// Issue numbers/URLs come only from GitHub's response and are re-validated; agent text only goes in the body.
const header = (s, n) => String(s || '').replace(/[^\x20-\x7E]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, n);
const get = (name, all) => { try { return all ? $(name).all().map(i => i.json) : $(name).first().json; } catch (e) { return all ? [] : null; } };
const pi = get('Plan Items') || {};
const be = get('Build Event') || {};
const decide = get('Decide');
const sent = get('Split Actions', true);
const repo = String(pi.plans_repo || '');
const ISSUE_URL = new RegExp(`^https://github\\.com/${repo.replace(/[.]/g, '\\.')}/issues/(\\d+)$`);

const input = $input.all().map(i => i.json || {});
const applied = new Map();   // fingerprint -> {status, number, url}
if (sent.length && input.length === sent.length && input.every(r => 'statusCode' in r || 'error' in r)) {
  input.forEach((r, i) => {
    const a = sent[i], code = Number(r.statusCode || 0), b = (r.body && typeof r.body === 'object') ? r.body : {};
    const okCode = a.method === 'POST' ? 201 : 200;
    const m = typeof b.html_url === 'string' ? b.html_url.match(ISSUE_URL) : null;
    applied.set(a.fingerprint, { ok: code === okCode, status: code || null,
      number: m && Number.isInteger(b.number) && String(b.number) === m[1] ? b.number : (a.issue_number || null),
      url: m ? b.html_url : null, error: r.error ? String(r.error.message || r.error).slice(0, 200) : null });
  });
}

const filings = [], counts = { created: [], updated: [], unchanged: [], skip_accepted: [], not_filed: [], failed: [] };
for (const d of (decide && decide.decisions) || []) {
  let action = d.action, number = d.issue_number || null, url = null, status = null, detail = d.reason || null;
  if (action === 'create' || action === 'update') {
    const r = applied.get(d.fingerprint);
    if (!r || !r.ok) { status = r ? r.status : null; detail = r ? (r.error || `HTTP ${r.status}`) : 'not applied'; action = `${action}_failed`; }
    else { status = r.status; number = r.number; url = r.url; }
  }
  if (number && !url) url = `https://github.com/${repo}/issues/${number}`;
  filings.push({ run_id: pi.run_id, fingerprint: d.fingerprint, rule: d.rule, resource: d.resource, severity: d.severity,
                 action, issue_number: number, issue_url: url, http_status: status, detail });
  const key = { create: 'created', update: 'updated', unchanged: 'unchanged', skip_accepted: 'skip_accepted',
                not_filed: 'not_filed' }[action] || 'failed';
  counts[key].push({ n: number, title: d.title, sev: d.severity, why: detail });
}

const refused = /^refused_|^runner_unreachable$/.test(String(pi.exit_reason || ''));
const label = be.label || 'sec-researcher run';
const nums = xs => xs.map(x => (x.n ? `#${x.n}` : '?')).join(', ');
const lines = [`${refused ? 'Not started' : 'Run'}: ${label}`, String(pi.summary || '(no summary)').slice(0, 1000)];
const planned = (pi.plans || []).length;
if (planned || (decide && decide.decisions && decide.decisions.length)) {
  lines.push(`Plans: ${counts.created.length} created${counts.created.length ? ` (${nums(counts.created)})` : ''}, `
    + `${counts.updated.length} updated${counts.updated.length ? ` (${nums(counts.updated)})` : ''}, `
    + `${counts.unchanged.length} unchanged, ${counts.skip_accepted.length} skipped (accepted risk), `
    + `${counts.not_filed.length} not filed${counts.failed.length ? `, ${counts.failed.length} FAILED` : ''}.`);
  for (const x of counts.not_filed.slice(0, 5)) lines.push(`- not filed [${x.sev}] ${String(x.title).slice(0, 120)} (${x.why})`);
  if (counts.not_filed.length > 5) lines.push(`- …and ${counts.not_filed.length - 5} more not filed (agent_plan_filings)`);
  for (const x of counts.failed.slice(0, 3)) lines.push(`- FAILED [${x.sev}] ${String(x.title).slice(0, 120)} (${x.why})`);
}
if (pi.invalid || pi.duplicate) lines.push(`Dropped by n8n: ${pi.invalid || 0} malformed, ${pi.duplicate || 0} duplicate plan(s).`);
if (repo && (counts.created.length || counts.updated.length)) lines.push(`https://github.com/${repo}/issues?q=label%3Asec-researcher`);
lines.push(`run ${pi.run_id || '?'} · ${pi.exit_reason || '?'}`);

const sevNew = counts.created.map(x => x.sev);
const priority = counts.failed.length || pi.outcome === 'failed' ? (refused ? '3' : '4')
  : sevNew.some(s => s === 'critical' || s === 'high') ? '4' : counts.created.length ? '3' : '2';
const tags = counts.failed.length || pi.outcome === 'failed' ? 'warning,lock' : counts.created.length ? 'memo,lock' : 'lock';
const title = refused
  ? `sec-researcher: not started - ${label}`
  : `sec-researcher: ${pi.outcome || 'failed'} - ${counts.created.length} new, ${counts.updated.length} updated - ${label}`;

return [{ json: { title: header(title, 120), message: lines.join('\n'), tags, priority, filings } }];
