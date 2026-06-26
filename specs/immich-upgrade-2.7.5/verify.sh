#!/usr/bin/env bash
# verify.sh — deterministic acceptance gate for specs/immich-upgrade-2.7.5.
# This IS §10 (acceptance criteria) compiled into runnable assertions: exit 0 = acceptable.
#
# STATIC tier only (no cluster) — gates each ralph loop iteration. The LIVE tier (migrations run
# clean, DB not rejected, ping 200, library intact) needs the cluster and is checked post-merge by
# Claude/MCP + Flux — listed at the bottom, NOT gated here.
#
# Run from the repo root.  ./specs/immich-upgrade-2.7.5/verify.sh
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

# 1. THE change — server image tag bumped to v2.7.5, old tag gone (AC tag)
grep -qE '^[[:space:]]+tag: v2\.7\.5$' "$HR" && ok "server-tag-2.7.5" || no "server-tag-2.7.5"
grep -q 'tag: v2.4.1' "$HR" && no "old-tag-removed (v2.4.1 still present)" || ok "old-tag-removed"

# 2. SAFEGUARD — Postgres image stays vectorchord0.3.0, never 0.4.x (the Pi 16k-page jemalloc landmine)
grep -q 'postgres:14-vectorchord0.3.0' "$PG"  && ok "postgres-pinned-0.3.0" || no "postgres-pinned-0.3.0 (DB image changed!)"
grep -qE 'vectorchord0\.4'             "$PG"  && no "postgres-no-0.4 (0.4.x = Pi crash!)" || ok "postgres-no-0.4"

# 3. SAFEGUARD — chart version unchanged (out of scope)
grep -q 'version: "0.10.3"' "$HR" && ok "chart-0.10.3" || no "chart-0.10.3 (chart version moved!)"

# 4. SAFEGUARD — resume + ML state unchanged. awk prints each 4-space block's 6-space `enabled:`.
states="$(awk '
  /^    [a-zA-Z-]+:/ { sec=$1; sub(/:.*/,"",sec) }
  /^      enabled:/  { print sec"="$2 }
' "$HR")"
echo "$states" | grep -qx 'server=true'            && ok "server-enabled"    || no "server-enabled (got: $(echo "$states" | grep '^server=' || echo none))"
echo "$states" | grep -qx 'valkey=true'            && ok "valkey-enabled"    || no "valkey-enabled (got: $(echo "$states" | grep '^valkey=' || echo none))"
echo "$states" | grep -qx 'machine-learning=false' && ok "ml-stays-disabled" || no "ml-stays-disabled (must NOT enable ML on Pi 5)"

# 5. SAFEGUARD — secrets still via ExternalSecret refs, never inlined
grep -q 'secretKeyRef' "$HR" && grep -q 'name: immich-secret' "$HR" && ok "secrets-via-ref" || no "secrets-via-ref"

echo
if [ "$fail" = 0 ]; then echo "VERIFY: PASS"; else echo "VERIFY: FAIL"; exit 1; fi

# --- LIVE tier (post-merge, Claude/MCP + Flux — NOT gated here) ----------------------
#   1. immich-server rolls out on v2.7.5; DB migrations run clean in the startup log
#   2. server does NOT reject the 0.3.0 DB ("extension version below minimum") — if it does: ROLLBACK
#   3. https://immich.lab.mtgibbs.dev/api/server/ping -> 200; /api/server/version reports 2.7.5
#   4. library + DB intact; postgres still vectorchord0.3.0, 0 restarts
#   5. ROLLBACK on failure: revert tag -> v2.4.1, restore .../2026-06-26/postgres/immich-postgres.dump
