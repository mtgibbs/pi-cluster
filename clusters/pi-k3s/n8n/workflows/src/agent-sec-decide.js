// The exit point's decision, in plain code: for each plan (most severe first), find issues in the plans repo
// whose body STARTS with its fingerprint marker, then
//   - any match labelled `accepted-risk` (open or closed)   -> skip_accepted (do nothing)
//   - an open match                                         -> update its body if the content changed, else unchanged
//   - a match closed as "not planned"                       -> skip_accepted
//   - otherwise (none, or only closed-as-fixed = it came back) -> create, at most MAX_NEW per run;
//                                                             the rest are not_filed (reported in the push)
// If the issue listing failed, or was incomplete (5 full pages), nothing is created: a partial view would
// duplicate issues. Updates of issues that WERE seen still go ahead on an incomplete listing.
// Input: List Issues responses (one per page, full response, never error). Output: ONE item
// {actions: [create/update, with method/url/payload for Apply], decisions: [every plan's outcome]}.
const MAX_NEW = 5;
const pi = $('Plan Items').first().json;
const repo = pi.plans_repo;
if (!/^[A-Za-z0-9-]+\/[A-Za-z0-9._-]+$/.test(String(repo))) throw new Error('bad plans repo');
const API = `https://api.github.com/repos/${repo}/issues`;
const FP = /^<!-- sec-researcher-fingerprint: ([0-9a-f]{64}) -->/;
const CONTENT = /^<!-- sec-researcher-content: ([0-9a-f]{64}) -->$/m;

const pages = $input.all().map(i => i.json || {});
let lookup = 'complete', issues = [];
if (!pages.length) lookup = 'failed';
for (const p of pages) {
  if (Number(p.statusCode) !== 200 || !Array.isArray(p.body)) { lookup = 'failed'; break; }
  issues = issues.concat(p.body);
}
if (lookup === 'complete' && !pages.some(p => p.body.length < 100)) lookup = 'incomplete';
if (lookup === 'failed') issues = [];
const lookupError = lookup === 'failed'
  ? `issue lookup failed (HTTP ${(pages.find(p => Number(p.statusCode) !== 200) || {}).statusCode || 'error'})` : null;

const byFp = new Map();
for (const i of issues) {
  if (!i || typeof i !== 'object' || i.pull_request || !Number.isInteger(i.number)) continue;
  const m = String(i.body || '').match(FP);
  if (!m) continue;
  const cm = String(i.body || '').match(CONTENT);
  const rec = { number: i.number, state: i.state, state_reason: i.state_reason || null,
                labels: (Array.isArray(i.labels) ? i.labels : []).map(l => (typeof l === 'string' ? l : (l && l.name) || '')),
                content: cm ? cm[1] : null };
  if (!byFp.has(m[1])) byFp.set(m[1], []);
  byFp.get(m[1]).push(rec);
}

const actions = [], decisions = [];
let created = 0;
for (const p of pi.plans || []) {
  const base = { fingerprint: p.fingerprint, rule: p.rule, resource: p.resource, severity: p.severity, title: p.title };
  if (lookup === 'failed') { decisions.push({ ...base, action: 'not_filed', reason: lookupError }); continue; }
  const matches = (byFp.get(p.fingerprint) || []).sort((a, b) => a.number - b.number);
  const labelled = matches.find(m => m.labels.includes('accepted-risk'));
  if (labelled) { decisions.push({ ...base, action: 'skip_accepted', issue_number: labelled.number }); continue; }
  const open = matches.find(m => m.state === 'open');
  if (open) {
    if (open.content === p.content_hash) { decisions.push({ ...base, action: 'unchanged', issue_number: open.number }); continue; }
    const d = { ...base, action: 'update', issue_number: open.number };
    decisions.push(d);
    actions.push({ ...d, method: 'PATCH', url: `${API}/${open.number}`, payload: { body: p.body } });
    continue;
  }
  const notPlanned = matches.find(m => m.state === 'closed' && m.state_reason === 'not_planned');
  if (notPlanned) { decisions.push({ ...base, action: 'skip_accepted', issue_number: notPlanned.number }); continue; }
  if (lookup === 'incomplete') {
    decisions.push({ ...base, action: 'not_filed', reason: 'issue lookup incomplete (over 500 issues); nothing new filed' });
    continue;
  }
  if (created >= MAX_NEW) { decisions.push({ ...base, action: 'not_filed', reason: `cap of ${MAX_NEW} new issues per run` }); continue; }
  created++;
  const fixed = matches.filter(m => m.state === 'closed').map(m => m.number);
  const body = fixed.length
    // The footer marker cannot occur in agent text (Plan Items escapes '<' in prose and breaks '<!--' in evidence).
    ? p.body.replace('\n<!-- sec-researcher-footer -->\n', `\n> Previously closed as fixed: ${fixed.map(n => `#${n}`).join(', ')}. It has come back.\n\n<!-- sec-researcher-footer -->\n`)
    : p.body;
  const d = { ...base, action: 'create', previously_fixed: fixed };
  decisions.push(d);
  actions.push({ ...d, method: 'POST', url: API, payload: { title: p.title, body, labels: p.labels } });
}
return [{ json: { lookup, lookup_error: lookupError, issues_seen: issues.length, actions, decisions } }];
