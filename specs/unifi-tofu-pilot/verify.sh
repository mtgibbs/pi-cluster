#!/usr/bin/env bash
# verify.sh — UniFi OpenTofu pilot gate.
# STATIC tier (offline, gates the PR). LIVE tier is human-run from the laptop (see spec §11).
# Before Phase 1 lands, infra/unifi/ and clusters/pi-k3s/iac-unifi/ don't exist: those checks SKIP,
# so this gate is honest about "not built" vs "built and broken" (it reports SKIP, never PASS, for absent work).
set -uo pipefail

ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
TF="$ROOT/infra/unifi"
CR="$ROOT/clusters/pi-k3s/iac-unifi"
SPEC="$(dirname "$0")/spec.md"
fail=0
pass(){ echo "  PASS: $1"; }
bad(){ echo "  FAIL: $1"; fail=1; }
skip(){ echo "  SKIP: $1"; }

echo "== STATIC: OpenTofu code =="
if [[ ! -d "$TF" ]]; then
  skip "infra/unifi/ not present (pre-Phase 1)"
else
  if command -v tofu >/dev/null; then
    tofu -chdir="$TF" fmt -check -recursive >/dev/null && pass "tofu fmt" || bad "tofu fmt -check failed"
    if tofu -chdir="$TF" init -backend=false -input=false >/dev/null 2>&1; then
      tofu -chdir="$TF" validate >/dev/null && pass "tofu validate" || bad "tofu validate failed"
    else
      skip "tofu init failed (offline?) — validate not run"
    fi
  else
    skip "tofu not installed — fmt/validate not run"
  fi
  # Provider must be pinned exactly (v0.60.0 shipped a breaking attribute reshape).
  grep -rqE 'version\s*=\s*"=?\s*[0-9]+\.[0-9]+\.[0-9]+"' "$TF"/*.tf \
    && pass "provider pinned to an exact version" || bad "provider not pinned exactly"
  # No credential literals — the API key comes from env (UNIFI_API_KEY) via the runner Secret.
  if grep -rqiE '(api_key|password|passphrase)\s*=\s*"[^"$]' "$TF"; then
    bad "credential literal in infra/unifi/"
  else
    pass "no credential literal in infra/unifi/"
  fi
  # The 2026-06-29 invariant: infra block always exempt.
  for m in '192.168.1.48/28' '192.168.1.70'; do
    grep -rqF "\"$m\"" "$TF" && pass "fw-dns-infra keeps $m" || bad "fw-dns-infra missing $m (deadlock invariant)"
  done
  # Never adopt a predefined zone policy (dropping one later would plan a destroy of a zone default).
  if grep -rqE '[0-9a-f-]{36}[0-9a-f-]{36}[0-9]+' "$TF"; then
    bad "import of a predefined (zone-pair-composite) policy id"
  else
    pass "no predefined policy ids imported"
  fi
fi

echo "== STATIC: executor manifests =="
if [[ ! -d "$CR" ]]; then
  skip "clusters/pi-k3s/iac-unifi/ not present (pre-Phase 2)"
else
  if grep -rqE 'approvePlan:\s*"?auto' "$CR"; then bad "approvePlan: auto — every apply must be PR-approved"; else pass "manual approval mode"; fi
  grep -rq 'infra.contrib.fluxcd.io/v1alpha2' "$CR" && pass "Terraform CR on v1alpha2" || bad "Terraform CR not on v1alpha2 (v1alpha1 removed in 0.17)"
  grep -rq 'kind: ExternalSecret' "$CR" && pass "credential via ExternalSecret" || bad "no ExternalSecret for the UniFi key"
fi

echo "== STATIC: spec self-consistency =="
grep -q "never auto-revert\|Never auto-revert" "$SPEC" && grep -q "192.168.1.48/28" "$SPEC" \
  && pass "spec keeps the no-auto-revert rule + infra invariant" || bad "spec lost a safeguard"

echo
[[ $fail -eq 0 ]] && echo "verify: PASS" || echo "verify: FAIL"
exit $fail

# ---- LIVE tier (human, laptop) ----
# 1. First plan after Phase 3 merge:  24 to import, 0 to add, 0 to change, 0 to destroy.
# 2. Drift positive control (Phase 4): edit one ALLOW policy name in the UI -> held plan + ntfy alert within one interval; revert.
# 3. DNS checks from unifi-ops SKILL.md (exit node OFF): dig @8.8.8.8 times out; dig @192.168.1.55 resolves;
#    source-controller logs show no "server misbehaving".
