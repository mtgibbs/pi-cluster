// Deterministic gate: did this revision touch access control? Input = the GitHub compare/commit response
// (HTTP node, full response, never error). Two tests, either is enough:
//   1. the PATH looks access-control-shaped (RBAC, ServiceAccounts, NetworkPolicies, ExternalSecrets,
//      ingress, namespaces, the agent sandbox, Flux itself, the secrets overlay);
//   2. a YAML file under clusters/ ADDED OR REMOVED a line with an access-control keyword (only +/- lines of
//      the patch — context lines and image-tag bumps do not count).
// Fails toward reviewing: a failed/odd API answer, a truncated file list (GitHub caps at 300) or a YAML
// patch GitHub omitted (too large) all count as relevant. The daily cap and per-revision dedupe bound that.
const PATHS = [
  /(^|\/)[^/]*(rbac|role|rolebinding|clusterrole|serviceaccount|networkpolic|external-secret|secretstore|secret-store|ingress|namespace|pod-security|psa)[^/]*\.ya?ml$/i,
  /^clusters\/pi-k3s\/(agents|harness-fleet|flux-system|flux-notifications|external-secrets|external-secrets-config|cloudflare-tunnel|tailscale|tailscale-config|ingress|cert-manager-config)\//,
  /^docs\/secrets-overlay\.yaml$/,
];
const KEYWORD = new RegExp([
  'kind:\\s*(Role|ClusterRole|RoleBinding|ClusterRoleBinding|ServiceAccount|NetworkPolicy|Ingress|IngressRoute|ExternalSecret|SecretStore|ClusterSecretStore|Namespace)\\b',
  'securityContext', 'privileged', 'allowPrivilegeEscalation', 'runAs(NonRoot|User|Group)', 'readOnlyRootFilesystem',
  'host(Network|PID|IPC|Path|Port)', 'capabilities', 'seccompProfile', 'automountServiceAccountToken',
  'serviceAccountName', 'secretKeyRef', 'secretRef', 'envFrom', 'remoteRef', 'pod-security\\.kubernetes\\.io',
  'ipBlock', 'namespaceSelector', 'podSelector', 'policyTypes', '\\bverbs:', '\\bapiGroups:', 'subjects:', 'roleRef:',
  'ingressClassName', 'tls:', 'nginx\\.ingress\\.kubernetes\\.io/(auth|whitelist|allowlist)',
].join('|'));
const MAX_PATHS = 50;

const r = $input.first().json || {};
let cmp = {};
try { cmp = $('Compare URL').first().json || {}; } catch (e) {}
const out = (relevant, why, changed, files_total) => [{ json: {
  relevant, why, revision: cmp.revision || null, base: cmp.base || null,
  changed_paths: changed.slice(0, MAX_PATHS).map(c => c.path),
  reasons: changed.slice(0, MAX_PATHS).map(c => `${c.path}: ${c.reason}`),
  files_total,
} }];

if (Number(r.statusCode) !== 200 || !r.body || typeof r.body !== 'object' || !Array.isArray(r.body.files)) {
  return out(true, `compare unavailable (HTTP ${r.statusCode || (r.error ? 'error' : '?')}); reviewing to be safe`, [], null);
}
const files = r.body.files.filter(f => f && typeof f.filename === 'string');
const changed = [];
for (const f of files) {
  const names = [f.filename, typeof f.previous_filename === 'string' ? f.previous_filename : null].filter(Boolean);
  const pathHit = names.find(n => PATHS.some(re => re.test(n)));
  if (pathHit) { changed.push({ path: f.filename, reason: 'path' }); continue; }
  const yaml = names.some(n => /^clusters\/.*\.ya?ml$/.test(n));
  if (!yaml) continue;
  if (typeof f.patch !== 'string') { changed.push({ path: f.filename, reason: 'diff too large to inspect' }); continue; }
  const hit = f.patch.split('\n').find(l => /^[+-]/.test(l) && !/^(\+\+\+|---)/.test(l) && KEYWORD.test(l));
  if (hit) changed.push({ path: f.filename, reason: `changed line matches "${(hit.match(KEYWORD) || [''])[0]}"` });
}
if (files.length >= 300) {
  return out(true, `${files.length} files changed (GitHub truncates the list at 300); reviewing to be safe`, changed, files.length);
}
return out(changed.length > 0, changed.length ? `${changed.length} access-control file(s) changed` : 'no access-control change', changed, files.length);
