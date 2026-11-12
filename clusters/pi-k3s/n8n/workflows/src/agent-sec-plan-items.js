// From the ledger row just written (Insert Ledger ... RETURNING; no row = duplicate callback = nothing runs):
// take the agent's `plan` outputs, re-validate them, and turn each into the exact issue it would become.
// Plain code, no model: the issue title/body are built from the structured fields only, and every piece of
// agent-written text is neutralised (no HTML, links, images, @-mentions, #-references, or a forged marker).
//
// THE PLANS REPO. The one place it is named; Issue Pages / Decide read it from this node's output.
const PLANS_REPO = 'mtgibbs/homelab-plans';
const AGENT = 'sec-researcher';
const SEVERITIES = ['critical', 'high', 'medium', 'low', 'info'];
const SECTIONS = [['found', 'What was found'], ['evidence', 'Evidence'], ['likely_cause', 'Likely cause'],
  ['proposed_change', 'Proposed change'], ['risk', 'Risk'], ['verify', 'How to verify'], ['rollback', 'How to roll back']];
const RULE = /^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/;
const RESOURCE = /^[a-z0-9][a-z0-9.-]{0,62}\/[A-Z][A-Za-z0-9]{0,62}\/[A-Za-z0-9][A-Za-z0-9._:-]{0,252}$/;
const SECTION_CAP = 6000, EVIDENCE_CAP = 12000;   // escaped chars; keeps a body well under GitHub's 65536
if (!/^[A-Za-z0-9-]+\/[A-Za-z0-9._-]+$/.test(PLANS_REPO)) throw new Error('PLANS_REPO is not owner/repo');

function sha256hex(str) {
  const b = [];                                  // UTF-8 encode
  for (const ch of str) {
    let c = ch.codePointAt(0);
    if (c < 0x80) b.push(c);
    else if (c < 0x800) b.push(0xc0 | c >> 6, 0x80 | c & 63);
    else if (c < 0x10000) b.push(0xe0 | c >> 12, 0x80 | c >> 6 & 63, 0x80 | c & 63);
    else b.push(0xf0 | c >> 18, 0x80 | c >> 12 & 63, 0x80 | c >> 6 & 63, 0x80 | c & 63);
  }
  const K = [];
  for (let n = 2, found = 0; found < 64; n++) {
    let prime = true;
    for (let d = 2; d * d <= n; d++) if (n % d === 0) { prime = false; break; }
    if (prime) { K.push((Math.pow(n, 1 / 3) % 1) * 4294967296 >>> 0); found++; }
  }
  const H = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
  const bitLen = b.length * 8;
  b.push(0x80);
  while (b.length % 64 !== 56) b.push(0);
  for (let i = 7; i >= 0; i--) b.push(i >= 4 ? 0 : (bitLen >>> (i * 8)) & 255);
  const r = (x, n) => (x >>> n) | (x << (32 - n));
  for (let o = 0; o < b.length; o += 64) {
    const w = new Array(64);
    for (let i = 0; i < 16; i++) w[i] = (b[o + 4 * i] << 24 | b[o + 4 * i + 1] << 16 | b[o + 4 * i + 2] << 8 | b[o + 4 * i + 3]) >>> 0;
    for (let i = 16; i < 64; i++) {
      const s0 = r(w[i - 15], 7) ^ r(w[i - 15], 18) ^ (w[i - 15] >>> 3);
      const s1 = r(w[i - 2], 17) ^ r(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
    }
    let [a, bb, c, d, e, f, g, h] = H;
    for (let i = 0; i < 64; i++) {
      const t1 = (h + (r(e, 6) ^ r(e, 11) ^ r(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i]) >>> 0;
      const t2 = ((r(a, 2) ^ r(a, 13) ^ r(a, 22)) + ((a & bb) ^ (a & c) ^ (bb & c))) >>> 0;
      h = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = bb; bb = a; a = (t1 + t2) >>> 0;
    }
    const v = [a, bb, c, d, e, f, g, h];
    for (let i = 0; i < 8; i++) H[i] = (H[i] + v[i]) >>> 0;
  }
  return H.map(x => x.toString(16).padStart(8, '0')).join('');
}

const ZW = '​';
// Prose: escape what GitHub would turn into markup that acts (HTML/comments, links, images, code spans,
// autolinks, mentions, issue references, headings). Formatting like * and _ is left alone: harmless.
const prose = (s, cap) => {
  let t = String(s || '').replace(/\r\n?/g, '\n').replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, '');
  t = t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/([\\`\[\]])/g, '\\$1')
    .replace(/:\/\//g, ':' + ZW + '//').replace(/www\./gi, m => m.slice(0, 3) + ZW + '.')
    .replace(/@/g, '@' + ZW).replace(/#/g, '#' + ZW);
  return t.length > cap ? t.slice(0, cap) + '\n\n_[truncated by n8n]_' : t;
};
// Evidence: verbatim inside a fence longer than any backtick run in it (nothing in a fence renders), with
// HTML-comment openers broken so the raw body can never carry a second marker.
const fenced = (s, cap) => {
  let t = String(s || '').replace(/\r\n?/g, '\n').replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, '').replace(/<!--/g, '<!' + ZW + '--');
  if (t.length > cap) t = t.slice(0, cap) + '\n[truncated by n8n]';
  const longest = Math.max(0, ...(t.match(/`+/g) || []).map(x => x.length));
  const fence = '`'.repeat(Math.max(3, longest + 1));
  return `${fence}text\n${t}\n${fence}`;
};
// Titles render as plain text on GitHub, but mentions/references still link: neutralise those, drop <>.
const oneLine = (s, n) => String(s || '').replace(/[\u0000-\u001f\u007f]+/g, ' ').replace(/[<>]/g, '').replace(/\s+/g, ' ').trim()
  .replace(/@/g, '@' + ZW).replace(/#/g, '#' + ZW).slice(0, n);

const row = $input.first().json || {};
if (!row.run_id) return [];
let outputs = row.outputs;
if (typeof outputs === 'string') { try { outputs = JSON.parse(outputs); } catch (e) { outputs = []; } }
let ev = {}, label = '';
try { const b = $('Build Event').first().json; ev = b.event || {}; label = b.label || ''; } catch (e) {}
const revision = /^[0-9a-f]{40}$/.test(String((ev.data || {}).revision || '')) ? ev.data.revision : null;

const plans = [], seen = new Set();
let invalid = 0, duplicate = 0;
for (const o of Array.isArray(outputs) ? outputs : []) {
  if (!o || o.kind !== 'plan') continue;
  const fp = o.fingerprint || {}, p = o.plan || {};
  const ok = RULE.test(String(fp.rule || '')) && RESOURCE.test(String(fp.resource || '')) && SEVERITIES.includes(o.severity)
    && typeof o.title === 'string' && o.title.trim() && SECTIONS.every(([k]) => typeof p[k] === 'string' && p[k].trim());
  if (!ok) { invalid++; continue; }
  const fingerprint = sha256hex(`${AGENT}|${fp.rule}|${fp.resource}`);
  if (seen.has(fingerprint)) { duplicate++; continue; }
  seen.add(fingerprint);
  const content = [`**Severity:** ${o.severity} · **Rule:** \`${fp.rule}\` · **Resource:** \`${fp.resource}\``, '',
    '> Filed by n8n from a sec-researcher run. The text below was written by a model from untrusted inputs (the repo,',
    '> cluster state): treat it as a proposal and check the evidence. This issue IS the plan; nothing changes until it',
    '> is approved.', '',
    ...SECTIONS.flatMap(([k, h]) => [`### ${h}`, k === 'evidence' ? fenced(p[k], EVIDENCE_CAP) : prose(p[k], SECTION_CAP), ''])].join('\n');
  const content_hash = sha256hex(content);
  const body = [`<!-- sec-researcher-fingerprint: ${fingerprint} -->`, `<!-- sec-researcher-content: ${content_hash} -->`,
    content, '<!-- sec-researcher-footer -->', '---',
    `Last seen: run \`${String(row.run_id).replace(/[^A-Za-z0-9._:-]/g, '')}\` · ${revision ? `revision \`${revision.slice(0, 12)}\`` : 'revision n/a'} · ${new Date().toISOString().slice(0, 10)} · ${oneLine(label, 60) || 'n/a'}`,
    `Fingerprint: \`${AGENT} | ${fp.rule} | ${fp.resource}\` (sha256 \`${fingerprint.slice(0, 16)}…\`).`,
    'To accept the risk, close this issue as **not planned** (or add the `accepted-risk` label); later runs then leave it alone.',
    'Add notes as comments: a re-run that finds different details rewrites this body.'].join('\n');
  plans.push({ fingerprint, content_hash, rule: fp.rule, resource: fp.resource, severity: o.severity,
               title: `[sec][${o.severity}] ${oneLine(o.title, 200)}`.slice(0, 256), body,
               labels: ['sec-researcher', `severity:${o.severity}`] });
}
const rank = s => SEVERITIES.indexOf(s);
plans.sort((a, b) => rank(a.severity) - rank(b.severity));   // stable: most severe first, then agent order

return [{ json: {
  plans_repo: PLANS_REPO,
  run_id: row.run_id, agent: row.agent, outcome: row.outcome, exit_reason: row.exit_reason,
  summary: String(row.summary || '').slice(0, 2048),
  revision, plans, invalid, duplicate,
} }];
