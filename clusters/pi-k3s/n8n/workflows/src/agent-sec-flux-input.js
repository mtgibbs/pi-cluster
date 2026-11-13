// sec-researcher trigger 1/3: ONE Flux notification-controller event (Provider type generic, POSTed by the
// `n8n-agents` Provider in clusters/pi-k3s/flux-notifications/n8n-agents.yaml) → the trigger record for
// `Trigger`. Returns NO items (the execution ends quietly) unless it is an info event that names a commit sha
// and comes from one of the two shapes below. Nothing from the payload except the validated 40-hex sha is used.
//
// - GitRepository (what the Alert sends now): source-controller's `NewArtifact` event, emitted once per new
//   artifact ("stored artifact for commit '…'"), metadata.revision = "main@sha1:<sha>" — the artifact the agent's
//   checkout downloads exists at that moment.
// - Kustomization (the old Alert, still accepted): one `ReconciliationSucceeded` per Kustomization per reconcile,
//   same metadata.revision shape.
// `Claim` keeps exactly one run per sha (key sec-researcher:flux-rev:<sha>, held for a year) whichever shape (and
// however many copies) arrive — the dedupe is the defence in depth, not the only filter.
const item = $input.first().json || {};
const p = (item.body && typeof item.body === 'object') ? item.body : item;   // webhook item, or a bare payload in tests
const obj = v => (v && typeof v === 'object' && !Array.isArray(v)) ? v : {};
const GROUP = { GitRepository: 'source.toolkit.fluxcd.io', Kustomization: 'kustomize.toolkit.fluxcd.io' };

if (p.severity !== 'info') return [];
const kind = obj(p.involvedObject).kind;
if (!Object.prototype.hasOwnProperty.call(GROUP, kind)) return [];
const meta = obj(p.metadata);
// notification-controller trims the involved object's group prefix from metadata keys; accept both forms.
const raw = String(meta.revision || meta[`${GROUP[kind]}/revision`] || '');
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
