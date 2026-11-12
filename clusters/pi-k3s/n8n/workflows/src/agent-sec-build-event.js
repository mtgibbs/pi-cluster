// Build the runner request {agent, event} for sec-researcher (CONTRACT §1) from `Trigger` (and, for a Flux
// revision, `Path Filter`). Event types pick the agent's behaviour AND its model (the manifest's
// model.by_event_type: security.sweep runs on Sonnet, the rest on Haiku):
//   security.flux_revision  data {revision, base, changed_paths, reasons, files_total}  source flux
//   security.sweep          data {scope, week}                                         source schedule
//   security.manual         data {ask}                                                 source matt
// event.data.revision (flux only, 40 hex) is the ONE event field the runner reads: it picks the Flux
// artifact the checkout fetches. trust is internal for all three (Flux events and the schedule are in-cluster;
// the form is LAN-only); the repo content the agent reads is still data, and its prompt says so.
const AGENT = 'sec-researcher';
const t = $('Trigger').first().json;
let pf = null;
try { pf = $('Path Filter').first().json; } catch (e) { pf = null; }

const B32 = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
let ms = Date.now(), time = '';
for (let i = 0; i < 10; i++) { time = B32[ms % 32] + time; ms = Math.floor(ms / 32); }
let rand = '';
for (let i = 0; i < 16; i++) rand += B32[Math.floor(Math.random() * 32)];
const id = time + rand;
const line = s => String(s || '').replace(/[\u0000-\u001f\u007f]+/g, ' ').trim();

let type, source, subject, data;
if (t.trigger === 'flux') {
  if (!pf || !pf.relevant) throw new Error('flux trigger reached Build Event without a relevant Path Filter result');
  type = 'security.flux_revision'; source = 'flux';
  subject = `rev:${t.revision.slice(0, 12)}`;
  data = {
    revision: t.revision,
    base: /^[0-9a-f]{40}$/.test(String(pf.base || '')) ? pf.base : null,
    changed_paths: (pf.changed_paths || []).slice(0, 50).map(p => line(p).slice(0, 300)),
    reasons: (pf.reasons || []).slice(0, 50).map(p => line(p).slice(0, 400)),
    files_total: Number.isInteger(pf.files_total) ? pf.files_total : null,
    why: line(pf.why).slice(0, 300),
  };
} else if (t.trigger === 'sweep') {
  type = 'security.sweep'; source = 'schedule';
  subject = `sweep:${t.week}`;
  data = { scope: 'clusters/pi-k3s/', week: t.week };
} else {
  type = 'security.manual'; source = 'matt';
  subject = 'manual';
  data = { ask: String(t.ask || '').slice(0, 4000) };
}

const label = t.trigger === 'flux' ? `Flux revision ${t.revision.slice(0, 7)}` : t.trigger === 'sweep' ? `weekly sweep ${t.week}` : 'manual run';
return [{ json: {
  agent: AGENT,
  trigger: t.trigger,
  label,
  event: { id, type, source, subject, dedupe_key: t.dedupe_key, trust: 'internal', data },
} }];
