#!/usr/bin/env bash
# verify.sh — STATIC gate for specs/homepage-retro-theme (spec.md §11)
# Exit 0 only if the work is acceptable. Deterministic, offline.
# Toolchain matches the house pattern (homepage-refresh/verify.sh): ruby -ryaml + grep
# + kubectl kustomize. Run from anywhere.
# LIVE-tier checks (post-deploy) are comments at the bottom — NOT gated here.
set -uo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
CM="$REPO/clusters/pi-k3s/homepage/configmap.yaml"
EXT_DIR="$REPO/clusters/pi-k3s/external-services"
KUMA="$REPO/clusters/pi-k3s/uptime-kuma/autokuma-monitors.yaml"
fail=0
ok(){ echo "  PASS  $1"; }
no(){ echo "  FAIL  $1" >&2; fail=1; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# 0. outer + embedded YAML parses; extract embedded docs for later checks
if ruby -ryaml -e '
  d = YAML.load_file(ARGV[0])["data"]
  %w[settings.yaml services.yaml].each { |k| YAML.load(d[k]) }
  File.write(ARGV[1] + "/settings.yaml", d["settings.yaml"])
  File.write(ARGV[1] + "/services.yaml", d["services.yaml"])
  File.write(ARGV[1] + "/custom.css",    d.fetch("custom.css", ""))
' "$CM" "$TMP" 2>/dev/null; then ok "yaml-parses+extracted"; else no "yaml-parses"; exit 1; fi
CSS="$TMP/custom.css"

# AC10. kustomize builds
for d in homepage external-services uptime-kuma; do
  kubectl kustomize "$REPO/clusters/pi-k3s/$d" >/dev/null 2>&1 \
    && ok "kustomize:$d" || no "kustomize:$d"
done

# AC1. deck set + ORDER in services.yaml
WANT="COMMAND|COMMS|AI CORE|REC DECK|ACQUISITION|CARGO BAY"
GOT="$(ruby -ryaml -e 'puts YAML.load_file(ARGV[0]).map { |g| g.keys.first }.join("|")' "$TMP/services.yaml")"
[ "$GOT" = "$WANT" ] && ok "deck-order" || no "deck-order: got [$GOT]"

# AC2. settings.yaml layout keys == services.yaml group set
LAYOUT="$(ruby -ryaml -e 'puts YAML.load_file(ARGV[0])["layout"].keys.sort.join("|")' "$TMP/settings.yaml")"
WANT_SORTED="$(printf '%s\n' "ACQUISITION" "AI CORE" "CARGO BAY" "COMMAND" "COMMS" "REC DECK" | paste -sd'|' -)"
[ "$LAYOUT" = "$WANT_SORTED" ] && ok "layout-keys" || no "layout-keys: got [$LAYOUT]"

# AC3. CARGO BAY tiles are link-only (no widget:)
CARGO_W="$(ruby -ryaml -e '
  g = YAML.load_file(ARGV[0]).find { |x| x.key?("CARGO BAY") }
  puts(g.nil? ? "-1" : g["CARGO BAY"].count { |t| t.values.first.key?("widget") })
' "$TMP/services.yaml")"
[ "$CARGO_W" = "0" ] && ok "cargo-bay-link-only" || no "cargo-bay has $CARGO_W widget(s)"

# AC4 / Safeguard 2. widget-type counts — zero regression
for c in pihole:2 unifi:1 tailscale:1 uptimekuma:1 prometheus:1 jellyfin:1 immich:1 \
         sonarr:1 radarr:1 bazarr:1 sabnzbd:1 prometheusmetric:1 customapi:2; do
  t="${c%%:*}"; want="${c##*:}"
  got="$(grep -cE "type: ${t}\$" "$TMP/services.yaml" || true)"
  [ "$got" = "$want" ] && ok "type:$t x$got" || no "type:$t got $got want $want"
done

# AC5. every group >= 3 tiles
MIN="$(ruby -ryaml -e 'puts YAML.load_file(ARGV[0]).map { |g| g.values.first.length }.min' "$TMP/services.yaml")"
[ "$MIN" -ge 3 ] && ok "min-tiles:$MIN" || no "a group has only $MIN tiles"

# AC6. :root token block, literal values; no hex outside :root
for tok in '--crt-bg: #050806' '--phosphor: #33ff66' '--phosphor-body: #9be8af' \
           '--phosphor-dim: #4d8a5e' '--amber: #ffb000' '--hal-red: #ff2a1f' \
           '--neon-cyan: #00e5ff' '--crt-border: #1d3a26'; do
  grep -qF -- "$tok" "$CSS" && ok "token ${tok%%:*}" || no "missing token: $tok"
done
ROOT_END="$(awk '/^:root/{f=1} f&&/^\}/{print NR; exit}' "$CSS")"
if [ -n "${ROOT_END:-}" ]; then
  if tail -n +"$((ROOT_END+1))" "$CSS" | grep -qE '#[0-9a-fA-F]{3,8}\b'; then
    no "hex color outside :root"; else ok "no-hex-outside-root"; fi
else no ":root block missing/not-first"; fi

# AC7. fonts: imports + fallback stacks
grep -q 'fonts.googleapis.com' "$CSS" && grep -q 'Michroma' "$CSS" \
  && grep -q 'Share+Tech+Mono\|Share Tech Mono' "$CSS" \
  && ok "font-imports" || no "font-imports"
grep -qF '"Michroma", "Eurostile", sans-serif' "$CSS" \
  && ok "header-font-stack" || no "header-font-stack"
grep -qF '"Share Tech Mono", ui-monospace, monospace' "$CSS" \
  && ok "mono-font-stack" || no "mono-font-stack"

# AC8. no animation
grep -qE '@keyframes|animation:' "$CSS" && no "animation-found" || ok "no-animation"

# AC9. status-state rules (marked blocks; selector chosen post-audit)
grep -q 'STATUS:DOWN' "$CSS" && grep -A10 'STATUS:DOWN' "$CSS" | grep -q 'var(--hal-red)' \
  && ok "status-down-rule" || no "status-down-rule (/* STATUS:DOWN */ + var(--hal-red))"
grep -q 'STATUS:WARN' "$CSS" && grep -A10 'STATUS:WARN' "$CSS" | grep -q 'var(--amber)' \
  && ok "status-warn-rule" || no "status-warn-rule (/* STATUS:WARN */ + var(--amber))"

# AC11 / Safeguard 1. no secret values; placeholders intact
grep -qE 'sk-[A-Za-z0-9]{16,}|[0-9a-f]{32,}' "$CM" && no "secret-looking-string" || ok "no-secrets"
PH="$(grep -c '{{HOMEPAGE_VAR_' "$CM" || true)"
[ "$PH" -ge 10 ] && ok "placeholders:$PH" || no "placeholders dropped to $PH"

# AC12. Synology teardown complete
[ ! -f "$EXT_DIR/synology.yaml" ] && ok "synology.yaml-deleted" || no "synology.yaml still exists"
grep -q 'synology' "$EXT_DIR/kustomization.yaml" \
  && no "kustomization still references synology" || ok "kustomization-clean"
grep -q 'nas\.lab\.mtgibbs\.dev' "$CM" "$KUMA" 2>/dev/null \
  && no "nas.lab reference remains" || ok "no-nas-lab-refs"
grep -q 'qnap\.lab\.mtgibbs\.dev' "$TMP/services.yaml" \
  && ok "tile→qnap.lab" || no "homepage tile not pointing at qnap.lab"
grep -q '"name": "QNAP NAS"' "$KUMA" && grep -q 'https://qnap\.lab\.mtgibbs\.dev/' "$KUMA" \
  && ok "kuma-monitor→qnap" || no "kuma synology.json not repointed"

# Regression guard: qnap.yaml stays correct (.61:8080) — out-of-scope file, must be untouched
ruby -ryaml -e '
  docs = YAML.load_stream(File.read(ARGV[0])).compact
  ep = docs.find { |d| d["kind"] == "Endpoints" }
  a = ep["subsets"][0]["addresses"][0]["ip"]; p0 = ep["subsets"][0]["ports"][0]["port"]
  exit(a == "192.168.1.61" && p0 == 8080 ? 0 : 1)
' "$EXT_DIR/qnap.yaml" 2>/dev/null && ok "qnap-endpoints" || no "qnap.yaml endpoints changed (must stay .61:8080)"

# §13b binding field decisions
grep -q 'blocked_percent' "$TMP/services.yaml" \
  && no "pihole blocked_percent should be dropped (§13b)" || ok "pihole-fields-trimmed"
grep -q 'showEpisodeNumber: true' "$TMP/services.yaml" \
  && ok "jellyfin-episode-numbers" || no "jellyfin showEpisodeNumber: true missing (§13b)"

# §13 settings theme keys
for kv in 'statusStyle: dot' 'fullWidth: true' 'iconStyle: theme' 'headerStyle: clean' 'color: green'; do
  grep -q "$kv" "$TMP/settings.yaml" && ok "settings:$kv" || no "settings missing: $kv"
done

# Norms. custom.css <= 20KB
B="$(wc -c < "$CSS" | tr -d ' ')"
[ "$B" -le 20480 ] && ok "css-size:${B}B" || no "css-size:${B}B > 20KB"

echo
if [ "$fail" -eq 0 ]; then echo "VERIFY: ALL STATIC CHECKS GREEN"; else echo "VERIFY: FAILURES PRESENT"; fi
exit "$fail"

# ── LIVE tier (post-deploy; human/MCP — NOT loop-gated) ──────────────────────
# 1. /deploy, then restart_deployment homepage (ConfigMap edits need a pod roll).
# 2. get_cluster_health: homepage pod Running/Ready.
# 3. curl_ingress https://home.lab.mtgibbs.dev → 200.
# 4. curl_ingress https://nas.lab.mtgibbs.dev → non-502 (AC12).
# 5. Human visual review: phosphor theme, deck order, no sparse bands, HAL-red on a
#    known-down tile. Taste boundary per specs/design-principles.md.
