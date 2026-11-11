// Re-title the shared Format Push output (agent-format-push.js) for an alert-started run, so the push says it
// was AUTOMATIC and names the alert: "ops-investigator: <outcome> - <alertname>". The report title moves to the
// body (Format Push already puts "Report: <title>" there). No input items (duplicate callback) = no push.
// exit_reason queue_expired (the runner's queue was busy and the run never started) is not a failure of the
// agent: it gets a quiet, low-priority "not investigated" push instead of Format Push's priority-4 warning.
const header = (s, n) => String(s || '').replace(/[^\x20-\x7E]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, n);

let b = {}, row = {};
try { b = $('Build Event').first().json || {}; } catch (e) {}
try { row = $('Insert Ledger').first().json || {}; } catch (e) {}
const ev = b.event || {};
const alertname = b.alertname || String(ev.subject || 'alert').split('/')[0];
const n = Number(b.alerts_total) || 0;

return $input.all().map(it => {
  const j = it.json || {};
  if (row.exit_reason === 'queue_expired') {
    return { json: {
      ...j,
      title: header(`${row.agent || b.agent || 'agent'}: not investigated (queue busy) - ${alertname}`, 120),
      message: `Not investigated: other alert runs held every agent slot and this one expired in the runner's queue.\n`
        + `Alertmanager will re-send the group if it is still firing after its repeat interval.\n`
        + `Auto-started by Alertmanager: ${ev.subject || alertname}${n ? ` (${n} alert${n === 1 ? '' : 's'})` : ''}\n`
        + `run ${String(row.run_id || '?').slice(0, 128)} · queue_expired`,
      tags: 'hourglass,rotating_light',
      priority: '2',
    } };
  }
  return { json: {
    ...j,
    title: header(`${row.agent || b.agent || 'agent'}: ${row.outcome || 'failed'} - ${alertname}`, 120),
    message: `Auto-started by Alertmanager: ${ev.subject || alertname}${n ? ` (${n} alert${n === 1 ? '' : 's'})` : ''}\n` + String(j.message || ''),
    tags: [j.tags, 'rotating_light'].filter(Boolean).join(','),
  } };
});
