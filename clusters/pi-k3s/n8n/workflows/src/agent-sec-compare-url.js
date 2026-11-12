// Which files did this revision change? Ask GitHub's PUBLIC API for the public pi-cluster repo (no token):
// compare <previous revision seen>...<this revision>, or, for the first revision ever seen, the commit itself
// (its diff against its first parent). The previous revision comes from Claim (the newest earlier
// sec-researcher:flux-rev row). Only validated 40-hex shas are put in the URL.
const REPO = 'mtgibbs/pi-cluster';
const SHA = /^[0-9a-f]{40}$/;
const t = $('Trigger').first().json;
const claim = $input.first().json || {};
const revision = String(t.revision || '');
if (!SHA.test(revision)) throw new Error('no revision to compare');
const base = SHA.test(String(claim.base || '')) && claim.base !== revision ? claim.base : null;
return [{ json: {
  revision,
  base,
  url: base
    ? `https://api.github.com/repos/${REPO}/compare/${base}...${revision}`
    : `https://api.github.com/repos/${REPO}/commits/${revision}`,
} }];
