#!/usr/bin/env bash
# verify.sh — static, offline gate for specs/aimode-toggle (§7 → assertions).
# Exit 0 only if the work is acceptable. The loop runs THIS; the model never self-certifies.
#
#   ./verify.sh         # run both halves
#   ./verify.sh a       # service only (Task A loop)
#   ./verify.sh b       # homepage only (Task B loop)
#
# Override input paths per environment / worktree:
#   API=path/to/ai-controlpanel.py CM=path/to/configmap.yaml ./verify.sh
set -uo pipefail

API="${API:-../../../beelink-ansible/files/ai-controlpanel.py}"
CM="${CM:-../../clusters/pi-k3s/homepage/configmap.yaml}"
WHICH="${1:-all}"
fail=0
ok()   { printf '  ok   %s\n' "$1"; }
bad()  { printf '  FAIL %s\n' "$1"; fail=1; }
have() { grep -Eq "$1" "$2" 2>/dev/null; }

check_service() {
  echo "== A: ai-controlpanel.py =="
  [ -f "$API" ] || { bad "A: file not found: $API"; return; }
  python3 -m py_compile "$API" 2>/dev/null && ok "A: py_compile" || bad "A: py_compile failed"
  have '/aimode'                  "$API" && ok "A2: /aimode route"        || bad "A2: no /aimode route"
  have 'flip'                     "$API" && ok "A4: flip handler"         || bad "A4: no flip handler"
  have 'AI_CONTROLPANEL_TOKEN'    "$API" && ok "A5/A7: reads token env"   || bad "A5/A7: token env not read"
  have '403'                      "$API" && ok "A5: 403 branch"           || bad "A5: no 403 branch"
  have '400'                      "$API" && ok "A6: 400 branch"           || bad "A6: no 400 branch"
  have '/opt/ai-stack/.aimode_state' "$API" && ok "A2: reads state file" || bad "A2: state file not read"
  have 'AI_CONTROLPANEL_PORT|9110' "$API" && ok "A1: port/bind"          || bad "A1: port not configurable"
  have 'startswith|prefix|split|path\[' "$API" && ok "A8: prefix dispatch" || bad "A8: no prefix-based dispatch"
  # A7: no hardcoded secret (token literal or leaked sk- key)
  if grep -Eq 'AI_CONTROLPANEL_TOKEN\s*=\s*["'\''][^"'\'' ]+["'\'']|sk-[A-Za-z0-9]{8,}' "$API"; then
    bad "A7: looks like a hardcoded token/secret"
  else
    ok "A7: no hardcoded secret"
  fi
}

check_homepage() {
  echo "== B: homepage configmap =="
  [ -f "$CM" ] || { bad "B: file not found: $CM"; return; }
  # ruby ships with macOS + has bundled YAML (system python3 here has no pyyaml).
  # Validate the outer ConfigMap AND every embedded data document (the house pattern).
  ruby -ryaml -e 'd=YAML.load_file(ARGV[0]); d["data"].each{|_,v| YAML.load(v)}' "$CM" 2>/dev/null \
    && ok "B4: valid YAML (outer + embedded docs)" || bad "B4: YAML does not parse"
  have 'https://controlpanel\.lab\.mtgibbs\.dev/aimode' "$CM" && ok "B1: /aimode customapi url" || bad "B1: missing /aimode url"
  have 'type:\s*customapi'        "$CM" && ok "B1: customapi widget present" || bad "B1: no customapi widget"
  have 'https://controlpanel\.lab\.mtgibbs\.dev/?($|["'\'' ])' "$CM" && ok "B2: panel bookmark url" || bad "B2: missing panel bookmark"
  have 'HOMEPAGE_VAR_AI_CONTROLPANEL_TOKEN' "$CM" && ok "B2: token via HOMEPAGE_VAR" || bad "B2: token var not used"
  # exactly two references to the host (the /aimode url + the / bookmark) — guards scope creep
  n=$(grep -Eo 'controlpanel\.lab\.mtgibbs\.dev' "$CM" 2>/dev/null | wc -l | tr -d ' ')
  [ "$n" = "2" ] && ok "B3: exactly 2 host refs" || bad "B3: expected 2 host refs, found $n"
  # no literal token leaked into the homepage config
  if grep -Eq 'op://|[A-Za-z0-9]{24,}' "$CM" && ! have 'HOMEPAGE_VAR_AI_CONTROLPANEL_TOKEN' "$CM"; then
    bad "B2: possible literal token in config"
  else
    ok "B2: no literal token"
  fi
}

case "$WHICH" in
  a|A) check_service ;;
  b|B) check_homepage ;;
  *)   check_service; check_homepage ;;
esac

echo
[ "$fail" = 0 ] && echo "VERIFY: PASS" || echo "VERIFY: FAIL"
exit "$fail"
