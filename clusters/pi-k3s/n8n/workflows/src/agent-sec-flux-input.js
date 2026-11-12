// sec-researcher trigger 1/3: ONE Flux notification-controller event (Provider type generic, POSTed by the
// `n8n-agents` Provider in clusters/pi-k3s/flux-notifications/n8n-agents.yaml) → the trigger record for
// `Trigger`. Returns NO items (the execution ends quietly) unless it is an info event from a Kustomization
// that names a commit sha. Every Kustomization sends its own event for the same revision; `Claim` keeps
// exactly one per sha (key sec-researcher:flux-rev:<sha>, held for a year). Nothing from the payload except
// the validated 40-hex sha is used.
const item = $input.first().json || {};
const p = (item.body && typeof item.body === 'object') ? item.body : item;   // webhook item, or a bare payload in tests
const obj = v => (v && typeof v === 'object' && !Array.isArray(v)) ? v : {};

if (p.severity !== 'info') return [];
if (obj(p.involvedObject).kind !== 'Kustomization') return [];
const meta = obj(p.metadata);
// notification-controller trims the involved object's group prefix from metadata keys; accept both forms.
const raw = String(meta.revision || meta['kustomize.toolkit.fluxcd.io/revision'] || '');
const m = raw.match(/(?:^|[@:])([0-9a-f]{40})$/);
if (!m) return [];
const revision = m[1];

return [{ json: {
  trigger: 'flux',
  revision,
  dedupe_key: `sec-researcher:flux-rev:${revision}`,
  subject: revision,
  cooldown_hours: 24 * 365,
} }];
