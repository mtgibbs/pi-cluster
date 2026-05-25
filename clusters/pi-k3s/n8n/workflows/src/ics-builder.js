// Build an ICS string from this kid's event/due rows (returned as text, not a file).
const rows = $input.all().map(i => i.json);
const calname = (rows[0] && rows[0].calname) || 'School';
const esc = s => String(s == null ? '' : s).replace(/\\/g, '\\\\').replace(/;/g, '\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n');
const parse = s => { const m = String(s || '').match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/); return m ? { Y: m[1], Mo: m[2], D: m[3], H: m[4], Mi: m[5] } : null; };
const stamp = new Date().toISOString().replace(/[-:]/g, '').split('.')[0] + 'Z';
const lines = ['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//mtgibbs//intake//EN','CALSCALE:GREGORIAN','METHOD:PUBLISH','X-WR-CALNAME:' + esc(calname),'X-WR-TIMEZONE:America/New_York'];
for (const r of rows) {
  const d = parse(r.due_at); if (!d) continue;
  const ymd = d.Y + d.Mo + d.D, midnight = (d.H === '00' && d.Mi === '00');
  let dtstart;
  if (r.type === 'due') { const hm = midnight ? '2359' : (d.H + d.Mi); dtstart = 'DTSTART:' + ymd + 'T' + hm + '00'; }
  else if (midnight) dtstart = 'DTSTART;VALUE=DATE:' + ymd;
  else dtstart = 'DTSTART:' + ymd + 'T' + d.H + d.Mi + '00';
  const uid = Buffer.from((r.source_msg_id||'')+'|'+(r.title||'')+'|'+ymd).toString('base64').replace(/[^a-zA-Z0-9]/g,'').slice(0,32)+'@mtgibbs.dev';
  let summary = r.title || '(untitled)'; if (r.type === 'due') summary = 'Due: ' + summary + (r.amount ? ' (' + r.amount + ')' : '');
  lines.push('BEGIN:VEVENT','UID:'+uid,'DTSTAMP:'+stamp,dtstart,'SUMMARY:'+esc(summary),'DESCRIPTION:'+esc('From: '+(r.source_subject||'')+(r.source_hint?' — '+r.source_hint:'')),'END:VEVENT');
}
lines.push('END:VCALENDAR');
return [{ json: { calname, events: rows.length, ics: lines.join('\r\n') + '\r\n' } }];
