#!/usr/bin/env bash
# verify.sh — deterministic acceptance gate for specs/immich-resume.
# This IS §10 (acceptance criteria) compiled into runnable assertions: exit 0 = acceptable.
#
# STATIC tier only (no cluster) — this is what gates each ralph loop iteration. The LIVE tier
# (pods Ready, ingress/TLS back, photo library intact) needs the cluster and is checked
# post-merge by Claude/MCP + Flux — listed at the bottom, NOT gated here.
#
# Run from the repo root.  ./specs/immich-resume/verify.sh
set -uo pipefail
HR="${HR:-clusters/pi-k3s/immich/helmrelease.yaml}"
PG="${PG:-clusters/pi-k3s/immich/postgresql.yaml}"
fail=0
ok(){ echo "  PASS  $1"; }
no(){ echo "  FAIL  $1" >&2; fail=1; }

# 0. both manifests still parse as YAML (all docs in each file)
for f in "$HR" "$PG"; do
  if ruby -ryaml -e 'YAML.load_stream(File.read(ARGV[0])){}' "$f" 2>/dev/null; then
    ok "yaml-parses:$(basename "$f")"; else no "yaml-parses:$(basename "$f")"; fi
done

# 1. block-scoped enabled flags (AC server/valkey/ml). awk tracks the 4-space top-level key and
#    prints the value of its immediately-nested 6-space `enabled:`. ingress/persistence `enabled`
#    keys are deeper-indented (8-10 spaces) and intentionally ignored.
states="$(awk '
  /^    [a-zA-Z-]+:/ { sec=$1; sub(/:.*/,"",sec) }
  /^      enabled:/  { print sec"="$2 }
' "$HR")"
echo "$states" | grep -qx 'server=true'            && ok "server-enabled"    || no "server-enabled (got: $(echo "$states" | grep '^server=' || echo none))"
echo "$states" | grep -qx 'valkey=true'            && ok "valkey-enabled"    || no "valkey-enabled (got: $(echo "$states" | grep '^valkey=' || echo none))"
echo "$states" | grep -qx 'machine-learning=false' && ok "ml-stays-disabled" || no "ml-stays-disabled (SAFEGUARD: ML must NOT be enabled on Pi 5)"

# 2. postgres scaled back to 1 (AC replicas). single replicas key in this file.
grep -qE '^  replicas: 1$' "$PG" && ok "postgres-replicas-1" || no "postgres-replicas-1"

# 3. stale park markers removed — a live service must not carry a "parked" lie (Norm/AC)
grep -q 'PARKED 2026-06-17' "$HR" "$PG" && no "park-comments-removed (PARKED 2026-06-17 still present)" || ok "park-comments-removed"

# 4. secrets still via ExternalSecret refs, never inlined (Safeguard)
grep -q 'secretKeyRef' "$HR" && grep -q 'name: immich-secret' "$HR" && ok "secrets-via-ref" || no "secrets-via-ref"

echo
if [ "$fail" = 0 ]; then echo "VERIFY: PASS"; else echo "VERIFY: FAIL"; exit 1; fi

# --- LIVE tier (post-merge, Claude/MCP + Flux — NOT gated here) ----------------------
#   1. immich-postgresql pod Ready (pg_isready), then immich-valkey Ready
#   2. immich-server pod Ready; /data NFS mount present; reads /cluster/photos
#   3. immich-tls re-issued (Let's Encrypt); https://immich.lab.mtgibbs.dev 200 + login
#   4. metrics scrape resumes on :8081/:8082; immich PrometheusRule not firing
#   5. photo library + DB intact (counts match pre-park)
