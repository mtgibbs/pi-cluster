// Normalise ONE Alertmanager webhook (v4) call into ONE runner request {agent, event} (CONTRACT.md §1).
// One run per alert GROUP, never per alert. Returns NO items (= the execution ends quietly) when the
// group is resolved or is only noise. Everything from the payload is DATA: it only ever lands inside
// event.data / event.subject (a JSON POST body) and, via Claim, a bound $1::jsonb — never a URL or SQL text.
const AGENT = 'ops-investigator';
const NOISE = ['Watchdog', 'InfoInhibitor', 'KubeMemoryOvercommit'];
const COOLDOWN_HOURS = 6;          // Claim skips a group launched within this window (Alertmanager repeat is 12h)
const MAX_ALERTS = 10;             // alerts carried in event.data; the rest are counted in alerts_total
const MAX_EVENT_BYTES = 24 * 1024; // contract caps are 32 KiB (body) / 64 KiB (event); stay well under
const MAX_KEYS = 40;               // labels/annotations per map
const MAX_SUBJECT = 200;

const item = $input.first().json || {};
const p = (item.body && typeof item.body === 'object') ? item.body : item;   // webhook item, or a bare payload in tests

if (p.status !== 'firing') return [];
const all = (Array.isArray(p.alerts) ? p.alerts : []).filter(a => a && typeof a === 'object' && (a.status === undefined || a.status === 'firing'));
// Alertmanager's max_alerts drops alerts from the payload and counts them in truncatedAlerts.
const dropped = Number.isInteger(p.truncatedAlerts) && p.truncatedAlerts > 0 ? p.truncatedAlerts : 0;
const total = all.length + dropped;
const nameOf = a => String((a.labels && a.labels.alertname) || '');
if (!all.length || all.every(a => NOISE.includes(nameOf(a)))) return [];

const obj = v => (v && typeof v === 'object' && !Array.isArray(v)) ? v : {};
let cut = false;                   // set by clip(): something was shortened
const clip = (v, n) => { const s = typeof v === 'string' ? v : (v === undefined || v === null ? '' : String(v)); if (s.length <= n) return s; cut = true; return s.slice(0, n) + '…[truncated]'; };
const clipMap = (m, n) => {
  const out = {};
  for (const k of Object.keys(obj(m)).sort().slice(0, MAX_KEYS)) out[clip(k, 128)] = clip(m[k], n);
  return out;
};
const line = s => String(s).replace(/[\u0000-\u001f\u007f]+/g, ' ').trim();

const groupLabels = obj(p.groupLabels), commonLabels = obj(p.commonLabels);
const alertname = line(commonLabels.alertname || groupLabels.alertname || nameOf(all.find(a => !NOISE.includes(nameOf(a))) || all[0]) || 'unknown').slice(0, 120) || 'unknown';
const namespace = line(commonLabels.namespace || groupLabels.namespace || '').slice(0, 63) || '-';
const subject = `${alertname}/${namespace}`.slice(0, MAX_SUBJECT);

// --- stable dedupe key: SHA-256 of groupKey (the Code sandbox has no `crypto`, so a small pure-JS one).
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
// groupKey is Alertmanager's own stable id for the group; fall back to receiver + sorted groupLabels.
const groupKey = typeof p.groupKey === 'string' && p.groupKey
  ? p.groupKey
  : `${p.receiver || ''}:${JSON.stringify(Object.keys(groupLabels).sort().map(k => [k, groupLabels[k]]))}`;
const dedupe_key = 'alertmanager:' + sha256hex(groupKey);

// --- event id: fresh ULID-shaped id per launch (as in agent-build-event.js). The runner dedupes on
// (event.id, agent) forever, so a deterministic id would block the next legitimate run after the cooldown.
const B32 = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
let t = Date.now(), time = '';
for (let i = 0; i < 10; i++) { time = B32[t % 32] + time; t = Math.floor(t / 32); }
let rand = '';
for (let i = 0; i < 16; i++) rand += B32[Math.floor(Math.random() * 32)];
const id = time + rand;

// --- data, shrunk until the whole event fits MAX_EVENT_BYTES (UTF-8).
const utf8 = s => { let n = 0; for (const ch of s) { const c = ch.codePointAt(0); n += c < 0x80 ? 1 : c < 0x800 ? 2 : c < 0x10000 ? 3 : 4; } return n; };
const build = (nAlerts, labelLen, annLen) => {
  cut = false;
  const data = {
    common_labels: clipMap(commonLabels, labelLen),
    common_annotations: clipMap(p.commonAnnotations, annLen),
    alerts: all.slice(0, nAlerts).map(a => ({
      labels: clipMap(a.labels, labelLen),
      annotations: clipMap(a.annotations, annLen),
      startsAt: clip(a.startsAt, 64),
      generatorURL: clip(a.generatorURL, 512),
    })),
  };
  if (cut || nAlerts < total) { data.alerts_total = total; data.truncated = true; }
  return { id, type: 'alert.firing', source: 'alertmanager', subject, dedupe_key, trust: 'internal', data };
};
let nAlerts = Math.min(all.length, MAX_ALERTS), labelLen = 256, annLen = 2000;
let event = build(nAlerts, labelLen, annLen);
while (utf8(JSON.stringify(event)) > MAX_EVENT_BYTES) {
  if (annLen > 200) annLen = Math.floor(annLen / 2);
  else if (nAlerts > 1) nAlerts--;
  else if (labelLen > 64) labelLen = Math.floor(labelLen / 2);
  else if (annLen > 20) annLen = Math.floor(annLen / 2);
  else break;                                    // absurd payload; the runner's own 422 is the backstop
  event = build(nAlerts, labelLen, annLen);
}

return [{ json: { agent: AGENT, event, alertname, alerts_total: total, cooldown_hours: COOLDOWN_HOURS } }];
