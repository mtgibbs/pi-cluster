// Build one push digest from a kid's due-soon rows. Empty input -> no notification.
const rows = $input.all().map(i => i.json);
if (!rows.length) return [];
const kid = rows[0].kid_label || 'Student';
const topic = rows[0].topic || 'deadlines';
// Format from the stored date COMPONENTS (floating local) — avoids the UTC-midnight
// shift that made an all-day "May 28" render as "May 27 8 PM".
const fmt = (s) => {
  const m = String(s).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!m) return String(s);
  const [, Y, Mo, D, H, Mi] = m;
  const wd = new Date(Date.UTC(+Y, +Mo - 1, +D)).toLocaleDateString('en-US', { weekday: 'short', timeZone: 'UTC' });
  const date = `${+Mo}/${+D}`;
  if (H === '00' && Mi === '00') return `${wd} ${date}`;            // all-day
  const h = +H, ap = h >= 12 ? 'PM' : 'AM', h12 = ((h + 11) % 12) + 1;
  return `${wd} ${date}, ${h12}:${Mi} ${ap}`;                       // timed
};
const lines = rows.map(r => `• ${r.type === 'due' ? 'DUE: ' : ''}${r.title} — ${fmt(r.due_at)}${r.amount ? ' (' + r.amount + ')' : ''}`);
return [{ json: { kid, topic, title: `${kid}: ${rows.length} upcoming`, message: lines.join('\n') } }];

