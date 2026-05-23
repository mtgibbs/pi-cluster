#!/usr/bin/env bash
# verify.sh — deterministic acceptance gate for specs/homepage-refresh.
# This IS §7 (acceptance criteria) compiled into runnable assertions: exit 0 = acceptable.
#
# STATIC tier only (no deploy needed) — this is what gates each ralph loop iteration:
# YAML validity + structural/semantic assertions. The LIVE tier (widgets actually render
# with data, ExternalSecrets synced, ai.lab/dewey/chat health green) needs a cluster and
# is checked post-merge by a human / Flux — noted at the bottom, NOT gated here.
#
# Run from the repo root.  ./specs/homepage-refresh/verify.sh
set -uo pipefail
CM="${CM:-clusters/pi-k3s/homepage/configmap.yaml}"
fail=0
ok(){ echo "  PASS  $1"; }
no(){ echo "  FAIL  $1" >&2; fail=1; }

# 0. valid YAML (outer ConfigMap + the embedded services.yaml document)
if ruby -ryaml -e 'd=YAML.load_file(ARGV[0]); YAML.load(d["data"]["services.yaml"])' "$CM" 2>/dev/null; then
  ok "yaml-parses"; else no "yaml-parses"; fi

# 1. all required groups present, no missing surfaces (AC#1)
for g in DNS Cluster Beelink Network Monitoring AI Media Downloads Logs Automation Web; do
  grep -q "^    - $g:" "$CM" && ok "group:$g" || no "group:$g"
done

# 2. arr widgets wired with in-cluster URLs + key vars (AC#2/#3)
grep -q 'type: sonarr'  "$CM" && grep -q 'sonarr.media.svc.cluster.local:8989'  "$CM" && ok "sonarr-widget"  || no "sonarr-widget"
grep -q 'type: radarr'  "$CM" && ok "radarr-widget"  || no "radarr-widget"
grep -q 'type: sabnzbd' "$CM" && ok "sabnzbd-widget" || no "sabnzbd-widget"
grep -q 'HOMEPAGE_VAR_SONARR_API_KEY' "$CM" && ok "sonarr-key-var" || no "sonarr-key-var"

# 3. link-only services must have NO widget (AC#6 + active-use rule)
awk '/- Jellyseerr:/{f=1} f&&/^        - /&&!/Jellyseerr/{f=0} f&&/type:/{print}' "$CM" | grep -q . \
  && no "jellyseerr-link-only (has a widget!)" || ok "jellyseerr-link-only"
awk '/- qBittorrent:/{f=1} f&&/^        - /&&!/qBittorrent/{f=0} f&&/type: qbittorrent/{print}' "$CM" | grep -q . \
  && no "qbittorrent-link-only (has a widget!)" || ok "qbittorrent-link-only"

# 4. Beelink customapi correctness — the two gotchas the model gets wrong
grep -q 'field: data.result.0.value.1' "$CM" && ok "beelink-nested-field" || no "beelink-nested-field"
grep -q 'query=round(100' "$CM" && no "beelink-percent-x100 (must be 0-1 fraction!)" || ok "beelink-percent-fraction"

# 5. never invent links / leak secrets (AC#7)
grep -qE 'sk-[A-Za-z0-9]{16,}' "$CM" && no "leaked-secret-key" || ok "no-leaked-secrets"

echo
if [ "$fail" = 0 ]; then echo "VERIFY: PASS"; else echo "VERIFY: FAIL"; exit 1; fi

# --- LIVE tier (post-merge, human/Flux — NOT gated here) ---------------------------
#   - Flux applies; homepage pod healthy; new homepage-* ExternalSecrets SecretSynced
#   - arr widgets render queue/health; Beelink tiles show real % (not 6100%); AI health green
