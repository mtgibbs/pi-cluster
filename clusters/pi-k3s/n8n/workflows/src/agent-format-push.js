// Build the ntfy push from the ledger row that was just written (Insert Ledger ... RETURNING).
// No row = duplicate callback (ON CONFLICT DO NOTHING) = no push.
// The push carries outcome + summary + report TITLE only; the report body stays in agent_runs.outputs.
const EMOJI = { done: 'white_check_mark', nothing_to_do: 'zzz', needs_human: 'raising_hand', failed: 'warning' };
const PRIO = { done: '3', nothing_to_do: '2', needs_human: '4', failed: '4' };

// Header values must be single-line ASCII; the full text goes in the body.
const header = (s, n) => String(s || '').replace(/[^\x20-\x7E]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, n);

const out = [];
for (const item of $input.all()) {
  const r = item.json || {};
  if (!r.run_id) continue;
  let outputs = r.outputs;
  if (typeof outputs === 'string') { try { outputs = JSON.parse(outputs); } catch (e) { outputs = []; } }
  const report = (Array.isArray(outputs) ? outputs : []).find(o => o && o.kind === 'report');
  const reportTitle = report ? String(report.title || '') : '';
  const outcome = String(r.outcome || 'failed');

  const lines = [String(r.summary || '(no summary)').slice(0, 3000)];
  if (reportTitle) lines.push(`Report: ${reportTitle.slice(0, 300)}`);
  lines.push(`run ${r.run_id} · ${r.exit_reason || '?'}`);

  out.push({ json: {
    title: header(`${r.agent || 'agent'}: ${outcome}${reportTitle ? ' - ' + reportTitle : ''}`, 120),
    message: lines.join('\n'),
    tags: EMOJI[outcome] || 'robot',
    priority: PRIO[outcome] || '3',
  } });
}
return out;
