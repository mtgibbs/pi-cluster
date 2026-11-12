// Offline tests for the sec-researcher n8n workflow's Code nodes (src/agent-sec-*.js) and its JSON.
// Run: node clusters/pi-k3s/n8n/workflows/test/agent-sec-researcher.test.js
// Each src file is executed the way n8n runs a Code node: as a function body with $input / $ / $execution.
const fs = require('fs'), path = require('path'), assert = require('assert'), crypto = require('crypto');
const WF = path.resolve(__dirname, '..');
const SRC = path.join(WF, 'src');

function run(file, input, nodes = {}) {
  const items = (Array.isArray(input) ? input : [input]).map(j => ({ json: j }));
  const $input = { first: () => items[0], all: () => items };
  const $ = name => {
    if (!(name in nodes)) throw new Error(`Referenced node is unexecuted: ${name}`);
    const its = [].concat(nodes[name]).map(j => ({ json: j }));
    return { first: () => its[0], all: () => its };
  };
  return new Function('$input', '$', '$execution', fs.readFileSync(path.join(SRC, file), 'utf8'))($input, $, {});
}
const one = (...a) => { const o = run(...a); assert.strictEqual(o.length, 1); return o[0].json; };
const sha = s => crypto.createHash('sha256').update(s).digest('hex');
const SHA1 = '0123456789abcdef0123456789abcdef01234567';
const SHA0 = 'fedcba9876543210fedcba9876543210fedcba98';
let n = 0;
const ok = name => { n++; console.log('ok', name); };

// ---------------------------------------------------------------- triggers
{
  const ev = (o = {}) => ({ headers: {}, body: { involvedObject: { kind: 'Kustomization', namespace: 'flux-system', name: 'agents' },
    severity: 'info', reason: 'ReconciliationSucceeded', message: 'Reconciliation finished', metadata: { revision: `main@sha1:${SHA1}` }, ...o } });
  const t = one('agent-sec-flux-input.js', ev());
  assert.deepStrictEqual(t, { trigger: 'flux', revision: SHA1, dedupe_key: `sec-researcher:flux-rev:${SHA1}`, subject: SHA1, cooldown_hours: 8760 });
  assert.strictEqual(one('agent-sec-flux-input.js', ev({ metadata: { 'kustomize.toolkit.fluxcd.io/revision': `main@sha1:${SHA1}` } })).revision, SHA1);
  assert.strictEqual(one('agent-sec-flux-input.js', ev({ metadata: { revision: SHA1 } })).revision, SHA1);
  assert.deepStrictEqual(run('agent-sec-flux-input.js', ev({ severity: 'error' })), []);
  assert.deepStrictEqual(run('agent-sec-flux-input.js', ev({ involvedObject: { kind: 'HelmRelease' } })), []);
  for (const bad of ['main@sha1:abc', `main@sha1:${SHA1}x`, `main@sha1:${SHA1.toUpperCase()}`, `../${SHA1}/x`, '', null])
    assert.deepStrictEqual(run('agent-sec-flux-input.js', ev({ metadata: { revision: bad } })), [], String(bad));
  assert.strictEqual(one('agent-sec-flux-input.js', ev().body).revision, SHA1);   // bare payload
  // Trigger re-validates the merge point
  assert.strictEqual(one('agent-sec-trigger.js', t).dedupe_key, t.dedupe_key);
  assert.throws(() => run('agent-sec-trigger.js', { ...t, dedupe_key: "x'; DROP TABLE agent_dedupe;--" }), /malformed/);
  assert.throws(() => run('agent-sec-trigger.js', { ...t, trigger: 'evil' }), /unknown trigger/);
  assert.throws(() => run('agent-sec-trigger.js', { ...t, revision: 'main' }), /revision/);
  const sw = one('agent-sec-sweep-input.js', {});
  assert.match(sw.dedupe_key, /^sec-researcher:sweep:\d{4}-W\d{2}$/); assert.strictEqual(sw.cooldown_hours, 144);
  assert.strictEqual(one('agent-sec-trigger.js', sw).week, sw.week);
  const fm = one('agent-sec-form-input.js', {}, { 'Sec Form': { 'What should it focus on? (optional)': '  the agents namespace  ' } });
  assert.strictEqual(fm.ask, 'the agents namespace'); assert.match(fm.dedupe_key, /^sec-researcher:manual:[0-9A-Z]{26}$/);
  assert.ok(one('agent-sec-form-input.js', {}, { 'Sec Form': {} }).ask.length > 10);   // blank -> default ask
  ok('triggers');
}

// ---------------------------------------------------------------- compare URL + path filter
{
  const T = { 'Trigger': { trigger: 'flux', revision: SHA1 } };
  let c = one('agent-sec-compare-url.js', { claimed: true, base: SHA0 }, T);
  assert.strictEqual(c.url, `https://api.github.com/repos/mtgibbs/pi-cluster/compare/${SHA0}...${SHA1}`);
  for (const base of [null, '', SHA1, 'main', `${SHA0}/../x`])
    assert.strictEqual(one('agent-sec-compare-url.js', { claimed: true, base }, T).url, `https://api.github.com/repos/mtgibbs/pi-cluster/commits/${SHA1}`);

  const C = { 'Compare URL': c };
  const resp = (files, code = 200) => ({ statusCode: code, body: { files } });
  const f = (filename, patch, extra = {}) => ({ filename, status: 'modified', patch, ...extra });
  const pf = (files, code) => one('agent-sec-path-filter.js', resp(files, code), C);
  // image-tag bump by the automation bot: not access control
  let r = pf([f('clusters/pi-k3s/agents/deployment.yaml', '@@ -1 +1 @@\n-          image: ghcr.io/x:0.2.0\n+          image: ghcr.io/x:0.3.0'),
              f('docs/secrets-map.md', '+ rbac securityContext')]);
  // agents/ is an access-control path as a whole -> relevant; use a non-sandbox namespace for the bump case
  assert.strictEqual(r.relevant, true);
  r = pf([f('clusters/pi-k3s/media/sonarr.yaml', '@@ -1 +1 @@\n-        image: x:1\n+        image: x:2'), f('docs/secrets-map.md', '+ rbac')]);
  assert.strictEqual(r.relevant, false); assert.strictEqual(r.files_total, 2);
  // context line mentioning securityContext does not count; an added one does
  r = pf([f('clusters/pi-k3s/media/sonarr.yaml', '@@ -1,3 +1,3 @@\n       securityContext:\n-        image: x:1\n+        image: x:2')]);
  assert.strictEqual(r.relevant, false);
  r = pf([f('clusters/pi-k3s/media/sonarr.yaml', '@@ -1,3 +1,4 @@\n+        securityContext:\n+          privileged: true')]);
  assert.strictEqual(r.relevant, true); assert.deepStrictEqual(r.changed_paths, ['clusters/pi-k3s/media/sonarr.yaml']);
  assert.match(r.reasons[0], /securityContext/);
  // path-shaped files, renames out of an RBAC file, removed lines
  for (const [file, extra] of [['clusters/pi-k3s/foo/rbac.yaml', {}], ['clusters/pi-k3s/foo/networkpolicy.yaml', {}],
    ['clusters/pi-k3s/foo/external-secret.yaml', {}], ['clusters/pi-k3s/foo/ingress.yaml', {}],
    ['clusters/pi-k3s/foo/thing.yaml', { previous_filename: 'clusters/pi-k3s/foo/serviceaccounts.yaml' }],
    ['clusters/pi-k3s/flux-system/infrastructure.yaml', {}], ['docs/secrets-overlay.yaml', {}]])
    assert.strictEqual(pf([f(file, '+x', extra)]).relevant, true, file);
  assert.strictEqual(pf([f('clusters/pi-k3s/media/a.yaml', '-  hostNetwork: true')]).relevant, true);
  // fail toward review: GitHub omitted the patch, truncated list, or the API failed
  assert.strictEqual(pf([f('clusters/pi-k3s/media/a.yaml', undefined)]).relevant, true);
  assert.strictEqual(pf(Array.from({ length: 300 }, (_, i) => f(`docs/x${i}.md`, '+a'))).relevant, true);
  for (const bad of [{ statusCode: 403, body: { message: 'rate limit' } }, { statusCode: 404, body: {} }, { error: { message: 'ETIMEDOUT' } }]) {
    const x = one('agent-sec-path-filter.js', bad, C);
    assert.strictEqual(x.relevant, true); assert.match(x.why, /unavailable/);
  }
  // non-YAML / non-cluster files never match on content
  assert.strictEqual(pf([f('scripts/x.py', '+ securityContext privileged')]).relevant, false);
  ok('compare url + path filter');
}

// ---------------------------------------------------------------- build event
{
  const flux = { trigger: 'flux', revision: SHA1, dedupe_key: `sec-researcher:flux-rev:${SHA1}` };
  const P = { relevant: true, base: SHA0, revision: SHA1, changed_paths: ['clusters/pi-k3s/a/rbac.yaml'], reasons: ['clusters/pi-k3s/a/rbac.yaml: path'], files_total: 3, why: 'x' };
  let b = one('agent-sec-build-event.js', {}, { Trigger: flux, 'Path Filter': P });
  assert.strictEqual(b.agent, 'sec-researcher');
  assert.deepStrictEqual(Object.keys(b.event).sort(), ['data', 'dedupe_key', 'id', 'source', 'subject', 'trust', 'type']);
  assert.strictEqual(b.event.type, 'security.flux_revision'); assert.strictEqual(b.event.data.revision, SHA1);
  assert.strictEqual(b.event.data.base, SHA0); assert.strictEqual(b.event.trust, 'internal');
  assert.match(b.event.id, /^[0-9A-HJKMNP-TV-Z]{26}$/); assert.strictEqual(b.label, `Flux revision ${SHA1.slice(0, 7)}`);
  assert.throws(() => run('agent-sec-build-event.js', {}, { Trigger: flux, 'Path Filter': { ...P, relevant: false } }), /relevant/);
  b = one('agent-sec-build-event.js', {}, { Trigger: { trigger: 'sweep', week: '2026-W46', dedupe_key: 'sec-researcher:sweep:2026-W46' } });
  assert.strictEqual(b.event.type, 'security.sweep'); assert.strictEqual(b.event.source, 'schedule'); assert.ok(!('revision' in b.event.data));
  b = one('agent-sec-build-event.js', {}, { Trigger: { trigger: 'manual', ask: 'agents ns', dedupe_key: 'k' } });
  assert.strictEqual(b.event.type, 'security.manual'); assert.strictEqual(b.event.data.ask, 'agents ns');
  ok('build event');
}

// ---------------------------------------------------------------- parse result keeps plan structure
const PLAN = (o = {}) => ({ kind: 'plan', title: 'Role grants * verbs', severity: 'high',
  fingerprint: { rule: 'rbac-wildcard', resource: 'agents/Role/agent-runner' },
  plan: { found: 'wildcard', evidence: "clusters/pi-k3s/agents/rbac.yaml:3  - verbs: ['*']", likely_cause: 'c',
          proposed_change: 'list verbs', risk: 'r', verify: 'v', rollback: 'rb' }, ...o });
const BE = one('agent-sec-build-event.js', {}, { Trigger: { trigger: 'flux', revision: SHA1, dedupe_key: `sec-researcher:flux-rev:${SHA1}` },
  'Path Filter': { relevant: true, changed_paths: [], reasons: [] } });
{
  const row = one('agent-sec-parse-result.js', { body: { run_id: 'r1', agent: 'sec-researcher', event_id: 'e', started: '2026-11-12T00:00:00Z',
    finished: '2026-11-12T00:10:00Z', exit_reason: 'completed', result: { outcome: 'needs_human', summary: 's', outputs: [PLAN(), { kind: 'plan', junk: 1 }] } } }, { 'Build Event': BE });
  assert.deepStrictEqual(row.outputs[0], PLAN());
  assert.strictEqual(row.event_type, 'security.flux_revision');
  assert.strictEqual(row.outputs[1].fingerprint.rule, '');   // malformed stays malformed; Plan Items drops it
  ok('parse result');
}

// ---------------------------------------------------------------- plan items: fingerprint, body, escaping
const LEDGER = (outputs, o = {}) => ({ run_id: 'r1', agent: 'sec-researcher', outcome: 'needs_human', exit_reason: 'completed', summary: 'two findings', outputs, ...o });
const items = (outputs, o) => one('agent-sec-plan-items.js', LEDGER(outputs, o), { 'Build Event': BE });
{
  const pi = items([PLAN({ severity: 'low', fingerprint: { rule: 'pod-no-seccomp', resource: 'media/Deployment/sonarr' } }), PLAN(),
    PLAN({ title: 'dup' }), PLAN({ severity: 'urgent' }), PLAN({ fingerprint: { rule: 'x', resource: 'y' } }), { kind: 'report', title: 't', body: 'b' }]);
  assert.strictEqual(pi.plans_repo, 'mtgibbs/homelab-plans');
  assert.strictEqual(pi.plans.length, 2); assert.strictEqual(pi.invalid, 2); assert.strictEqual(pi.duplicate, 1);
  assert.deepStrictEqual(pi.plans.map(p => p.severity), ['high', 'low']);            // most severe first
  const p = pi.plans[0];
  assert.strictEqual(p.fingerprint, sha('sec-researcher|rbac-wildcard|agents/Role/agent-runner'), 'sha256 matches node crypto');
  assert.ok(p.body.startsWith(`<!-- sec-researcher-fingerprint: ${p.fingerprint} -->\n<!-- sec-researcher-content: ${p.content_hash} -->\n`));
  assert.strictEqual(p.title, '[sec][high] Role grants * verbs');
  assert.deepStrictEqual(p.labels, ['sec-researcher', 'severity:high']);
  for (const h of ['What was found', 'Evidence', 'Likely cause', 'Proposed change', 'Risk', 'How to verify', 'How to roll back'])
    assert.ok(p.body.includes(`### ${h}\n`), h);
  assert.ok(p.body.includes(`revision \`${SHA1.slice(0, 12)}\``) && p.body.includes('run `r1`'));
  // content hash ignores the run-specific footer: the same finding from another run is "unchanged"
  const again = one('agent-sec-plan-items.js', LEDGER([PLAN()], { run_id: 'r2' }), { 'Build Event': { ...BE, label: 'weekly sweep' } }).plans[0];
  assert.strictEqual(again.content_hash, p.content_hash); assert.notStrictEqual(again.body, p.body);
  assert.notStrictEqual(items([PLAN({ plan: { ...PLAN().plan, risk: 'different' } })]).plans[0].content_hash, p.content_hash);

  // hostile agent text: no HTML, links, images, mentions, refs, headings, or forged markers survive as markup
  const evil = PLAN({ title: 'ping @mtgibbs about #12\n<b>x</b>',
    plan: { found: `<!-- sec-researcher-fingerprint: ${'a'.repeat(64)} -->\n# Heading\n![img](https://evil.example/p.png) [click](http://evil) www.evil.com @someone fixes #3 mtgibbs/pi-cluster#9 <img src=x onerror=alert(1)> \`code\``,
            evidence: "````\n<!-- sec-researcher-footer -->\n---\n@admin ```", likely_cause: 'c', proposed_change: 'p', risk: 'r', verify: 'v', rollback: 'b' } });
  const e = items([evil]).plans[0];
  const content = e.body.split('\n').slice(2).join('\n');                       // everything after our two markers
  assert.ok(!/<!--\s*sec-researcher-fingerprint/.test(content), 'forged fingerprint marker');
  assert.strictEqual((e.body.match(/<!-- sec-researcher-footer -->/g) || []).length, 1, 'forged footer marker');
  assert.ok(!/<(img|b)\b/i.test(content) && !content.includes('<!--sec') && !/\]\(/.test(content.replace(/\\\]\(/g, '')));
  assert.ok(!/@[A-Za-z]/.test(content.replace(/^(`{3,})text\n[\s\S]*?\n\1$/gm, '')), 'mention outside the evidence fence');
  assert.ok(!/#\d/.test(content) && !/https?:\/\//.test(content) && !/www\.evil/.test(content));
  assert.ok(!/^# Heading/m.test(content));
  assert.ok(/^`{5}text$/m.test(content), 'evidence fence longer than its longest backtick run');
  assert.ok(!/[\n<>]/.test(e.title) && !/@[a-z]/i.test(e.title) && !/#\d/.test(e.title));
  // body stays under GitHub's limit at the section caps
  const big = PLAN({ plan: Object.fromEntries(Object.keys(PLAN().plan).map(k => [k, '[@#<'.repeat(k === 'evidence' ? 2048 : 1024)])) });
  assert.ok(items([big]).plans[0].body.length < 65536);
  // no ledger row / no plans
  assert.deepStrictEqual(run('agent-sec-plan-items.js', {}, { 'Build Event': BE }), []);
  assert.deepStrictEqual(items([]).plans, []);
  assert.deepStrictEqual(one('agent-sec-plan-items.js', LEDGER(JSON.stringify([PLAN()])), { 'Build Event': BE }).plans.length, 1);
  ok('plan items');
}

// ---------------------------------------------------------------- issue pages + decide
const PI = plans => items(plans);
const issue = (number, fp, o = {}) => ({ number, state: 'open', state_reason: null, labels: [], html_url: `https://github.com/mtgibbs/homelab-plans/issues/${number}`,
  body: `<!-- sec-researcher-fingerprint: ${fp} -->\n<!-- sec-researcher-content: ${o.content || '0'.repeat(64)} -->\nbody`, ...o });
const page = (arr, code = 200) => ({ statusCode: code, body: arr });
const decide = (pi, pages) => one('agent-sec-decide.js', pages, { 'Plan Items': pi });
{
  const pages = run('agent-sec-issue-pages.js', {}, { 'Plan Items': { plans_repo: 'mtgibbs/homelab-plans' } }).map(i => i.json);
  assert.strictEqual(pages.length, 5);
  assert.strictEqual(pages[0].url, 'https://api.github.com/repos/mtgibbs/homelab-plans/issues?state=all&per_page=100&sort=created&direction=asc&page=1');
  assert.throws(() => run('agent-sec-issue-pages.js', {}, { 'Plan Items': { plans_repo: 'evil.com/x/../y' } }), /bad plans repo/);

  const mk = (rule, sev) => PLAN({ severity: sev, fingerprint: { rule, resource: `agents/Role/${rule}` } });
  const pi = PI([mk('r-open', 'high'), mk('r-same', 'high'), mk('r-notplanned', 'medium'), mk('r-label', 'medium'),
    mk('r-fixed', 'low'), mk('r-new', 'critical'), mk('r-pr', 'info')]);
  const fp = Object.fromEntries(pi.plans.map(p => [p.rule, p]));
  const list = [
    issue(1, fp['r-open'].fingerprint),
    issue(2, fp['r-same'].fingerprint, { content: fp['r-same'].content_hash }),
    issue(3, fp['r-notplanned'].fingerprint, { state: 'closed', state_reason: 'not_planned' }),
    issue(4, fp['r-label'].fingerprint, { state: 'closed', state_reason: 'completed', labels: [{ name: 'accepted-risk' }] }),
    issue(5, fp['r-fixed'].fingerprint, { state: 'closed', state_reason: 'completed' }),
    issue(6, fp['r-pr'].fingerprint, { pull_request: {} }),                       // a PR, not an issue: ignored
    issue(7, 'f'.repeat(64), { body: `notes\n<!-- sec-researcher-fingerprint: ${fp['r-new'].fingerprint} -->` }),  // marker not at the start: ignored
  ];
  const d = decide(pi, [page(list), page([])]);
  const act = Object.fromEntries(d.decisions.map(x => [x.rule, x]));
  assert.strictEqual(d.lookup, 'complete');
  assert.strictEqual(act['r-open'].action, 'update'); assert.strictEqual(act['r-open'].issue_number, 1);
  assert.strictEqual(act['r-same'].action, 'unchanged');
  assert.strictEqual(act['r-notplanned'].action, 'skip_accepted'); assert.strictEqual(act['r-notplanned'].issue_number, 3);
  assert.strictEqual(act['r-label'].action, 'skip_accepted');
  assert.strictEqual(act['r-fixed'].action, 'create'); assert.deepStrictEqual(act['r-fixed'].previously_fixed, [5]);
  assert.strictEqual(act['r-new'].action, 'create'); assert.strictEqual(act['r-pr'].action, 'create');
  const upd = d.actions.find(a => a.rule === 'r-open');
  assert.strictEqual(upd.method, 'PATCH'); assert.strictEqual(upd.url, 'https://api.github.com/repos/mtgibbs/homelab-plans/issues/1');
  assert.deepStrictEqual(Object.keys(upd.payload), ['body']);                    // never touches title/state/labels
  const cr = d.actions.find(a => a.rule === 'r-fixed');
  assert.strictEqual(cr.method, 'POST'); assert.strictEqual(cr.url, 'https://api.github.com/repos/mtgibbs/homelab-plans/issues');
  assert.ok(cr.payload.body.includes('Previously closed as fixed: #5'));
  assert.ok(cr.payload.body.indexOf('Previously closed') < cr.payload.body.indexOf('<!-- sec-researcher-footer -->'));
  assert.deepStrictEqual(cr.payload.labels, ['sec-researcher', 'severity:low']);
  assert.strictEqual(d.actions.length, 4);
  // an open issue labelled accepted-risk is also left alone
  assert.strictEqual(decide(PI([mk('a-b-c', 'high')]), [page([issue(9, PI([mk('a-b-c', 'high')]).plans[0].fingerprint, { labels: ['accepted-risk'] })])]).decisions[0].action, 'skip_accepted');
  ok('decide: create / update / unchanged / skip');

  // the 5-cap, most severe first
  const seven = PI(['low', 'info', 'critical', 'medium', 'high', 'high', 'low'].map((s, i) => mk(`rule-${i}`, s)));
  const c = decide(seven, [page([])]);
  const created = c.decisions.filter(x => x.action === 'create');
  assert.strictEqual(created.length, 5); assert.strictEqual(c.actions.length, 5);
  assert.deepStrictEqual(created.map(x => x.severity), ['critical', 'high', 'high', 'medium', 'low']);
  const nf = c.decisions.filter(x => x.action === 'not_filed');
  assert.strictEqual(nf.length, 2); assert.ok(nf.every(x => /cap of 5/.test(x.reason)));
  assert.deepStrictEqual(nf.map(x => x.severity).sort(), ['info', 'low']);
  // updates do not count against the cap
  const withOpen = decide(seven, [page(seven.plans.slice(0, 3).map((p, i) => issue(i + 1, p.fingerprint)))]);
  assert.strictEqual(withOpen.decisions.filter(x => x.action === 'create').length, 4);
  assert.strictEqual(withOpen.decisions.filter(x => x.action === 'update').length, 3);
  ok('decide: 5-cap');

  // lookup failed -> nothing filed at all; incomplete (5 full pages) -> no creates, updates of seen issues still go
  for (const pages2 of [[page([], 404)], [{ error: { message: 'ECONNREFUSED' } }], [page([]), page({ message: 'x' })], []]) {
    const f = decide(seven, pages2);
    assert.strictEqual(f.lookup, 'failed'); assert.strictEqual(f.actions.length, 0);
    assert.ok(f.decisions.every(x => x.action === 'not_filed' && /lookup failed/.test(x.reason)));
  }
  const full = Array.from({ length: 5 }, (_, pg) => page(Array.from({ length: 100 }, (_, i) => issue(pg * 100 + i + 10, 'e'.repeat(64)))));
  full[0].body[0] = issue(1, seven.plans[0].fingerprint);
  const inc = decide(seven, full);
  assert.strictEqual(inc.lookup, 'incomplete');
  assert.deepStrictEqual(inc.actions.map(a => a.method), ['PATCH']);
  assert.ok(inc.decisions.filter(x => x.action === 'not_filed').every(x => /incomplete/.test(x.reason)));
  ok('decide: fail closed on lookup');
}

// ---------------------------------------------------------------- summarize
{
  const pi = PI([PLAN(), PLAN({ severity: 'low', fingerprint: { rule: 'sa-token-automount', resource: 'media/Deployment/sonarr' } })]);
  const d = decide(pi, [page([issue(4, pi.plans[1].fingerprint)])]);
  const split = d.actions;                              // what Split Actions emits, in order
  const resp = [{ statusCode: 201, body: { number: 12, html_url: 'https://github.com/mtgibbs/homelab-plans/issues/12' } },
                { statusCode: 200, body: { number: 4, html_url: 'https://github.com/mtgibbs/homelab-plans/issues/4' } }];
  const s = one('agent-sec-summarize.js', resp, { 'Plan Items': pi, 'Build Event': BE, Decide: d, 'Split Actions': split });
  assert.strictEqual(s.title, `sec-researcher: needs_human - 1 new, 1 updated - Flux revision ${SHA1.slice(0, 7)}`);
  assert.ok(s.message.includes('Plans: 1 created (#12), 1 updated (#4), 0 unchanged, 0 skipped (accepted risk), 0 not filed.'));
  assert.strictEqual(s.priority, '4'); assert.ok(/^[\x20-\x7E]+$/.test(s.title));
  assert.deepStrictEqual(s.filings.map(f => [f.action, f.issue_number, f.issue_url]),
    [['create', 12, 'https://github.com/mtgibbs/homelab-plans/issues/12'], ['update', 4, 'https://github.com/mtgibbs/homelab-plans/issues/4']]);
  // a failed create and an html_url pointing elsewhere are not trusted
  const bad = one('agent-sec-summarize.js', [{ statusCode: 422, body: { message: 'Validation Failed' } },
    { statusCode: 200, body: { number: 4, html_url: 'https://evil.example/issues/4' } }], { 'Plan Items': pi, 'Build Event': BE, Decide: d, 'Split Actions': split });
  assert.deepStrictEqual(bad.filings.map(f => f.action), ['create_failed', 'update']);
  assert.strictEqual(bad.filings[1].issue_url, 'https://github.com/mtgibbs/homelab-plans/issues/4');
  assert.ok(bad.message.includes('1 FAILED')); assert.strictEqual(bad.priority, '4');
  // capped findings are listed as not filed
  const seven = PI(Array.from({ length: 7 }, (_, i) => PLAN({ title: `finding ${i}`, fingerprint: { rule: `rule-${i}`, resource: 'agents/Role/x' } })));
  const d7 = decide(seven, [page([])]);
  const s7 = one('agent-sec-summarize.js', d7.actions.map((a, i) => ({ statusCode: 201, body: { number: 20 + i, html_url: `https://github.com/mtgibbs/homelab-plans/issues/${20 + i}` } })),
    { 'Plan Items': seven, 'Build Event': BE, Decide: d7, 'Split Actions': d7.actions });
  assert.ok(s7.message.includes('5 created (#20, #21, #22, #23, #24)') && s7.message.includes('2 not filed'));
  assert.strictEqual((s7.message.match(/^- not filed /gm) || []).length, 2);
  // no plans (clean run) -> quiet push; refusal -> "not started"
  const clean = PI([]);
  const c = one('agent-sec-summarize.js', clean, { 'Plan Items': { ...clean, outcome: 'nothing_to_do' }, 'Build Event': BE });
  assert.strictEqual(c.priority, '2'); assert.deepStrictEqual(c.filings, []); assert.ok(!c.message.includes('Plans:'));
  const refused = { ...clean, outcome: 'failed', exit_reason: 'refused_429', summary: 'Not started (HTTP 429): daily run cap' };
  const rf = one('agent-sec-summarize.js', refused, { 'Plan Items': refused, 'Build Event': BE });
  assert.ok(rf.title.startsWith('sec-researcher: not started - ')); assert.strictEqual(rf.priority, '3');
  // lookup failed -> every plan reported not filed, nothing claimed as created
  const lf = decide(pi, [page([], 404)]);
  const sl = one('agent-sec-summarize.js', lf, { 'Plan Items': pi, 'Build Event': BE, Decide: lf });
  assert.ok(sl.message.includes('0 created') && sl.message.includes('2 not filed') && sl.message.includes('lookup failed (HTTP 404)'));
  ok('summarize');
}

// ---------------------------------------------------------------- workflow JSON
{
  const w = JSON.parse(fs.readFileSync(path.join(WF, 'agent-sec-researcher.json'), 'utf8'));
  const byName = Object.fromEntries(w.nodes.map(x => [x.name, x]));
  assert.strictEqual(Object.keys(byName).length, w.nodes.length, 'duplicate node names');
  for (const [from, c] of Object.entries(w.connections))
    for (const outs of c.main) for (const t of outs || []) assert.ok(byName[t.node], `${from} -> ${t.node}`);
  const want = { 'Flux Revision': 'agent-sec-flux-input.js', 'Sweep Input': 'agent-sec-sweep-input.js', 'Form Input': 'agent-sec-form-input.js',
    Trigger: 'agent-sec-trigger.js', 'Compare URL': 'agent-sec-compare-url.js', 'Path Filter': 'agent-sec-path-filter.js',
    'Build Event': 'agent-sec-build-event.js', 'Resume Callback': 'agent-resume-callback.js', 'Parse Result': 'agent-sec-parse-result.js',
    'Timeout Row': 'agent-sec-timeout-row.js', 'Refusal Row': 'agent-sec-refusal-row.js', 'Plan Items': 'agent-sec-plan-items.js',
    'Issue Pages': 'agent-sec-issue-pages.js', Decide: 'agent-sec-decide.js', Summarize: 'agent-sec-summarize.js' };
  const codeNodes = w.nodes.filter(x => typeof (x.parameters || {}).jsCode === 'string');
  assert.deepStrictEqual(codeNodes.map(x => x.name).sort(), Object.keys(want).sort());
  for (const x of codeNodes) assert.strictEqual(x.parameters.jsCode, fs.readFileSync(path.join(SRC, want[x.name]), 'utf8'), x.name);
  // auth: the Flux webhook fails closed with the reused agent-alert-token credential
  const wh = byName['Flux Webhook'];
  assert.strictEqual(wh.parameters.authentication, 'headerAuth'); assert.strictEqual(wh.parameters.path, 'agent-sec-revision');
  assert.strictEqual(wh.credentials.httpHeaderAuth.name, 'agent-alert-token');
  // GitHub: only List Issues and Apply hold github-plans; Compare (public repo) holds nothing
  const gh = w.nodes.filter(x => x.credentials && x.credentials.httpHeaderAuth && x.credentials.httpHeaderAuth.name === 'github-plans').map(x => x.name).sort();
  assert.deepStrictEqual(gh, ['Apply', 'List Issues']);
  assert.ok(!byName.Compare.credentials);
  assert.strictEqual(byName['Wait for Result'].parameters.resumeAmount, 80);
  assert.strictEqual(byName['Weekly Sweep'].parameters.rule.interval[0].expression, '0 6 * * 0');
  assert.strictEqual(byName['Sec Form'].parameters.options.path, 'agent-sec-run');
  // exactly one scheduled trigger in the workflow (design §10)
  assert.strictEqual(w.nodes.filter(x => /scheduleTrigger|cron/i.test(x.type)).length, 1);
  // Summarize is the only fan-in of the filing branch, and it fans out to the ledger and the push
  assert.deepStrictEqual(w.connections.Summarize.main[0].map(t => t.node).sort(), ['Push', 'Record Filings']);
  ok('workflow json');
}
console.log(`ALL PASS (${n} groups)`);
