// The one merge point of the three sec-researcher triggers (Flux Revision / Sweep Input / Form Input). Later
// nodes read $('Trigger'). It re-checks the record's shape, so nothing downstream (Claim's SQL parameter, the
// GitHub compare URL, the event) ever sees a value that did not come from one of the three input nodes.
const t = $input.first().json || {};
const KEY = /^sec-researcher:(flux-rev:[0-9a-f]{40}|sweep:\d{4}-W\d{2}|manual:[0-9A-Z]{26})$/;
if (!['flux', 'sweep', 'manual'].includes(t.trigger)) throw new Error('unknown trigger');
if (!KEY.test(String(t.dedupe_key || ''))) throw new Error('malformed dedupe_key');
if (t.trigger === 'flux' && !/^[0-9a-f]{40}$/.test(String(t.revision || ''))) throw new Error('flux trigger without a revision');
const hours = Number(t.cooldown_hours);
return [{ json: {
  trigger: t.trigger,
  dedupe_key: t.dedupe_key,
  subject: String(t.subject || '').slice(0, 64),
  cooldown_hours: Number.isInteger(hours) && hours >= 1 ? hours : 1,
  revision: t.trigger === 'flux' ? t.revision : null,
  week: t.trigger === 'sweep' ? String(t.week || '').slice(0, 8) : null,
  ask: t.trigger === 'manual' ? String(t.ask || '').slice(0, 4000) : null,
} }];
