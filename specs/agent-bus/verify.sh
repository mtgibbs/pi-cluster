#!/usr/bin/env bash
# verify.sh — deterministic acceptance gate for specs/agent-bus (Phase 0).
# §10 acceptance criteria + §8 safeguards, compiled to runnable assertions: exit 0 = acceptable.
#
# PRESENCE-GATED (the ralph contract): this runs after EVERY task and must pass, so a check
# for a not-yet-built file is PEND (skipped), never FAIL. Once its file exists, the check is
# asserted for real. By the final task all files exist, so the full gate is active.
# STATIC tier only (no cluster). LIVE tier (Flux applies, /versions 200, Element login,
# bootstrap users) is spec §11 — checked post-merge by laptop-Claude, NOT gated here.
#
# Run from repo root:  ./specs/agent-bus/verify.sh
set -uo pipefail
DIR="${DIR:-clusters/pi-k3s/matrix}"
INFRA="${INFRA:-clusters/pi-k3s/flux-system/infrastructure.yaml}"
fail=0
ok(){   echo "  PASS  $1"; }
no(){   echo "  FAIL  $1" >&2; fail=1; }
pend(){ echo "  pend  $1 (not built yet)"; }
have(){ [ -f "$1" ]; }
# best-effort YAML validity: ruby → python3 → skip (qwen container may have neither;
# structural greps still gate, so a missing parser must not block the loop).
yaml_ok(){
  if command -v ruby >/dev/null 2>&1; then
    ruby -ryaml -e 'YAML.load_stream(File.read(ARGV[0])){}' "$1" 2>/dev/null
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c 'import yaml,sys;list(yaml.safe_load_all(open(sys.argv[1])))' "$1" 2>/dev/null
  else return 0; fi
}

# 0. YAML validity for every manifest that exists
if [ -d "$DIR" ]; then
  for f in "$DIR"/*.yaml; do [ -e "$f" ] || continue
    yaml_ok "$f" && ok "yaml:$(basename "$f")" || no "yaml:$(basename "$f")"
  done
fi

# 1. Synapse config (server identity + private-by-construction) — gate on the ConfigMap
SC="$DIR/synapse-config.yaml"
if have "$SC"; then
  grep -qE 'server_name:[[:space:]]*"?matrix\.lab\.mtgibbs\.dev"?' "$SC" && ok "server_name-exact" || no "server_name-exact"
  grep -Eq 'federation_domain_whitelist:[[:space:]]*\[[[:space:]]*\]' "$SC" && ok "federation-off"   || no "federation-off"
  grep -Eqi 'enable_registration:[[:space:]]*false'                   "$SC" && ok "registration-off" || no "registration-off"
else pend "synapse-config"; fi

# 2. No inbound federation listener anywhere (negative check — safe to always run)
if grep -rq '8448' "$DIR" 2>/dev/null; then no "no-8448-listener (found 8448!)"; else ok "no-8448-listener"; fi

# 3. Secrets only via ESO template, never literal — gate on external-secret.yaml
ES="$DIR/external-secret.yaml"
if have "$ES"; then
  grep -q 'kind: ClusterSecretStore' "$ES" && grep -q 'onepassword' "$ES" && ok "eso-onepassword" || no "eso-onepassword"
  leak=0
  while IFS= read -r line; do case "$line" in *'{{'*) : ;; *) leak=1 ;; esac; done \
    < <(grep -rhE 'registration_shared_secret:|macaroon_secret_key:|form_secret:' "$DIR" 2>/dev/null)
  [ "$leak" = 0 ] && ok "secrets-templated-only" || no "secrets-templated-only (literal secret!)"
else pend "external-secret"; fi

# 4. Ingress: both hosts, never chat.lab — gate on ingress.yaml
IG="$DIR/ingress.yaml"
if have "$IG"; then
  grep -q 'matrix.lab.mtgibbs.dev'  "$IG" && ok "ingress-matrix-host"  || no "ingress-matrix-host"
  grep -q 'element.lab.mtgibbs.dev' "$IG" && ok "ingress-element-host" || no "ingress-element-host"
  grep -q 'chat.lab' "$IG" && no "chat.lab-reused (forbidden!)" || ok "no-chat.lab-reuse"
else pend "ingress"; fi

# 5. Placement + resource bounds — gate on all three workloads existing
if have "$DIR/synapse.yaml" && have "$DIR/element.yaml" && have "$DIR/postgresql.yaml"; then
  n=$(grep -rc 'pi5-worker-2' "$DIR" 2>/dev/null | awk -F: '{s+=$2} END{print s+0}')
  [ "$n" -ge 3 ] && ok "worker2-pinned-x3" || no "worker2-pinned-x3 ($n<3)"
  m=$(grep -rc 'memory:' "$DIR" 2>/dev/null | awk -F: '{s+=$2} END{print s+0}')
  [ "$m" -ge 4 ] && ok "memory-limits-present" || no "memory-limits-present"
else pend "workload-placement"; fi

# 6. Kustomization lists each manifest that EXISTS (final task → all eight present)
K="$DIR/kustomization.yaml"
if have "$K"; then
  for m in namespace external-secret pvc postgresql synapse-config synapse element ingress; do
    have "$DIR/$m.yaml" && { grep -q "$m.yaml" "$K" && ok "kust:$m" || no "kust:$m-missing"; }
  done
else pend "kustomization"; fi

# 7. Flux registration — gate on the matrix path appearing in infrastructure.yaml
if grep -q 'path: ./clusters/pi-k3s/matrix' "$INFRA" 2>/dev/null; then
  yaml_ok "$INFRA" && ok "infra-yaml-valid" || no "infra-yaml-corrupted"
  for dep in external-secrets-config ingress cert-manager-config; do
    grep -q "$dep" "$INFRA" && ok "flux-dep:$dep" || no "flux-dep:$dep"
  done
else pend "flux-registration"; fi

echo
if [ "$fail" = 0 ]; then echo "VERIFY: PASS"; else echo "VERIFY: FAIL"; exit 1; fi

# --- LIVE tier (post-merge, laptop-Claude — NOT gated here) -------------------------------
#   - mint 1Password `matrix` item (db-password, registration-shared-secret, macaroon-secret,
#     form-secret); Flux reconciles; pods Running within limits on pi5-worker-2
#   - curl https://matrix.lab.mtgibbs.dev/_matrix/client/versions -> 200 JSON
#   - Element login at https://element.lab.mtgibbs.dev; register_new_matrix_user @matt + 4 bots
#   - delete synapse pod -> history survives (PVC)
