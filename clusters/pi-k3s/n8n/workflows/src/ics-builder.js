// Build one ICS document from the input rows (one kid's event/due items + 'both').
const rows = $input.all().map(i => i.json);
const calname = (rows[0] && rows[0].calname) || 'School';
const esc = s => String(s == null ? '' : s).replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n');
const parse = s => { const m = String(s || '').match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/); return m ? { Y: m[1], Mo: m[2], D: m[3], H: m[4], Mi: m[5] } : null; };
const stamp = new Date().toISOString().replace(/[-:]/g, '').split('.')[0] + 'Z';

const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//mtgibbs//intake//EN', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH', 'X-WR-CALNAME:' + esc(calname), 'X-WR-TIMEZONE:America/New_York'];
for (const r of rows) {
  const d = parse(r.due_at);
  if (!d) continue;                       // undated items don't go on the calendar
  const ymd = d.Y + d.Mo + d.D;
  const midnight = (d.H === '00' && d.Mi === '00');   // LLM emits T00:00 for date-only
  let dtstart;
  if (r.type === 'due') {
    // deadlines are timed: bare date -> 23:59 (end of day); otherwise the stated time.
    // Floating local time (no Z/TZID) renders at wall-clock — avoids the UTC-shift bug.
    const hm = midnight ? '2359' : (d.H + d.Mi);
    dtstart = 'DTSTART:' + ymd + 'T' + hm + '00';
  } else if (midnight) {
    dtstart = 'DTSTART;VALUE=DATE:' + ymd;            // all-day event
  } else {
    dtstart = 'DTSTART:' + ymd + 'T' + d.H + d.Mi + '00';
  }
  const uidseed = (r.source_msg_id || '') + '|' + (r.title || '') + '|' + ymd;
  const uid = Buffer.from(uidseed).toString('base64').replace(/[^a-zA-Z0-9]/g, '').slice(0, 32) + '@mtgibbs.dev';
  let summary = r.title || '(untitled)';
  if (r.type === 'due') summary = 'Due: ' + summary + (r.amount ? ' (' + r.amount + ')' : '');
  const desc = 'From: ' + (r.source_subject || '') + (r.source_hint ? ' — ' + r.source_hint : '');
  lines.push('BEGIN:VEVENT', 'UID:' + uid, 'DTSTAMP:' + stamp, dtstart, 'SUMMARY:' + esc(summary), 'DESCRIPTION:' + esc(desc), 'END:VEVENT');
}
lines.push('END:VCALENDAR');
const ics = lines.join('\r\n') + '\r\n';
return [{ json: { calname, events: rows.length }, binary: { data: { data: Buffer.from(ics).toString('base64'), mimeType: 'text/calendar', fileName: 'cal.ics' } } }];
