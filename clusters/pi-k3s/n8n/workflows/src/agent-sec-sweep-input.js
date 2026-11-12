// sec-researcher trigger 2/3: the ONE named weekly sweep (design §10: the only scheduled poll). One run per ISO
// week: Claim holds sec-researcher:sweep:<YYYY-Www> for 6 days, so a re-fired schedule (n8n restart, a
// manual "execute") in the same week does nothing.
const now = new Date();
// ISO week of `now` (UTC): Thursday of this week decides the year.
const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
const dow = d.getUTCDay() || 7;
d.setUTCDate(d.getUTCDate() + 4 - dow);
const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
const week = Math.ceil(((d - yearStart) / 86400000 + 1) / 7);
const isoWeek = `${d.getUTCFullYear()}-W${String(week).padStart(2, '0')}`;

return [{ json: {
  trigger: 'sweep',
  week: isoWeek,
  dedupe_key: `sec-researcher:sweep:${isoWeek}`,
  subject: `sweep:${isoWeek}`,
  cooldown_hours: 24 * 6,
} }];
