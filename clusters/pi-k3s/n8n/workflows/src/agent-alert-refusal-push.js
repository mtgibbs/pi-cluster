// At most ONE quiet push per refusal kind per window: Insert Refusal returns prior_same = the number of earlier
// agent_runs rows with the same exit_reason and event_type inside the window. Anything but 0 = stay silent
// (the ledger row is the record). No input row (ON CONFLICT) = silent too.
const header = (s, n) => String(s || '').replace(/[^\x20-\x7E]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, n);
const out = [];
for (const item of $input.all()) {
  const r = item.json || {};
  if (!r.run_id || Number(r.prior_same) !== 0) continue;
  out.push({ json: {
    title: header(`${r.agent || 'agent'}: not started - ${String(r.subject || 'alert').split('/')[0]}`, 120),
    message: `${String(r.summary || '').slice(0, 1000)}\nFurther ${r.exit_reason} refusals for alert runs are recorded in agent_runs without a push for the next 6 hours.\n${r.run_id}`,
    tags: 'rotating_light,no_entry',
    priority: '2',
  } });
}
return out;
