#!/usr/bin/env bash
# Deterministic gate for specs/model-watch.
#
#   bash specs/model-watch/verify.sh            # offline, deterministic (what the loop runs)
#   STRICT=1 bash specs/model-watch/verify.sh   # final pass: pending work becomes failure
#   LIVE=1   bash specs/model-watch/verify.sh   # adds the real-HuggingFace smoke (slow, flaky)
#
# Three verdicts (specs/TEMPLATE.md §11): ok / no / pend. Checks presence-gate on the
# ARTIFACT, so each arms itself as soon as its target exists, in whatever build order.
#
# WHY THE FIXTURES EXIST: a previous run passed a structure-only gate while shipping
# disabled TLS, malformed ntfy auth, an MoE parser that read 512/10 as 10/None, and a
# card fetcher that always threw. Every one of those greps fine. Shape checks certify
# shape — so the classifier is now exercised against recorded HF responses with known
# answers, and behaviour is asserted from the fixture server's request log.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1
D=clusters/pi-k3s/model-watch
S=$D/model-watch.py
SPEC=specs/model-watch
fail=0
ok(){   echo "  PASS  $1"; }
no(){   echo "  FAIL  $1" >&2; fail=1; }
pend(){ if [ "${STRICT:-0}" = 1 ]; then no "$1 — still unbuilt at the final check (STRICT)"
        else echo "  pend  $1 (not built yet)"; fi; }

echo "VERIFY specs/model-watch"

echo "== files =="
for f in model-watch.py namespace.yaml external-secret.yaml cronjob.yaml kustomization.yaml; do
  [ -f "$D/$f" ] && ok "$f exists" || pend "$D/$f"
done

echo "== script hygiene =="
if [ -f "$S" ]; then
  python3 -m py_compile "$S" 2>/dev/null && ok "compiles" || no "syntax error"
  if grep -Eq '^[[:space:]]*(import|from)[[:space:]]+(requests|httpx|yaml|aiohttp|bs4|pandas|numpy)\b' "$S"; then
    no "third-party import (stdlib only — there is no pip install at runtime)"
  else ok "stdlib only"; fi
  grep -q 'DRY_RUN' "$S" && ok "honours DRY_RUN" || no "no DRY_RUN support"
else pend "script hygiene checks"; fi

echo "== safeguards (§8) =="
if [ -f "$S" ]; then
  # §8 says safeguards map to assertions. These are the ones a plausible-looking
  # implementation gets wrong silently.
  if grep -Eq 'CERT_NONE|check_hostname[[:space:]]*=[[:space:]]*False|_create_unverified' "$S"; then
    no "TLS verification disabled — the LiteLLM call carries an API key"
  else ok "TLS verification intact"; fi
  if grep -qi 'ntfy' "$S"; then
    # ntfy wants Authorization: Basic base64("user:password"). Sending the raw password
    # 401s, and the failure is invisible until the monthly push silently stops.
    grep -q 'b64encode\|base64' "$S" && ok "ntfy auth base64-encoded" \
      || no "ntfy Basic auth not base64-encoded (would 401)"
    grep -q 'NTFY_USER' "$S" && ok "ntfy user configured" || no "no NTFY_USER — Basic auth needs user:password"
  else pend "ntfy publish assertions"; fi
  grep -Eq 'print\(.*(LITELLM_API_KEY|NTFY_PASSWORD)' "$S" \
    && no "prints a credential" || ok "no credential printed"
else pend "safeguard checks"; fi

echo "== manifests =="
if [ -f "$D/external-secret.yaml" ]; then
  grep -q 'litellm-api-key'         "$D/external-secret.yaml" && ok "litellm key wired"       || no "no litellm-api-key"
  grep -q 'ntfy/family-password'    "$D/external-secret.yaml" && ok "reuses family ntfy cred" || no "ntfy cred not reused (reuse-before-mint)"
  grep -q 'model-watch/litellm-key' "$D/external-secret.yaml" && ok "1P path correct"         || no "wrong 1P path"
else pend "external-secret assertions"; fi
if [ -f "$D/cronjob.yaml" ]; then
  grep -Eq 'schedule:[[:space:]]*"[^"]*\*[[:space:]]*\*"' "$D/cronjob.yaml" \
    && ok "monthly-ish schedule" || no "schedule not monthly (day-of-month pinned?)"
else pend "cronjob assertions"; fi
grep -q 'ntfy access family "model-watch"' clusters/pi-k3s/ntfy/deployment.yaml 2>/dev/null \
  && ok "ntfy ACL granted" || pend "ntfy ACL (deny-all default ⇒ publish would 403)"
grep -q 'path: ./clusters/pi-k3s/model-watch' clusters/pi-k3s/flux-system/infrastructure.yaml 2>/dev/null \
  && ok "registered with Flux" || pend "Flux registration in infrastructure.yaml"

echo "== classifier vs fixtures (offline, deterministic) =="
if [ -f "$S" ]; then
  PORT=8765; RL=$(mktemp)
  REQ_LOG="$RL" PORT=$PORT python3 "$SPEC/fixture_server.py" >/dev/null 2>&1 &
  SRV=$!
  for _ in $(seq 1 40); do
    python3 -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1',$PORT))==0 else 1)" 2>/dev/null && break
    sleep 0.25
  done
  out=$(cd "$D" && HF_BASE="http://127.0.0.1:$PORT" DRY_RUN=1 WINDOW_DAYS=36500 MIN_LIKES=0 \
        VRAM_BUDGET_GB=96 timeout 120 python3 model-watch.py 2>/dev/null)
  rc=$?
  kill $SRV 2>/dev/null; wait $SRV 2>/dev/null

  if [ $rc -ne 0 ]; then
    no "fixture run exited $rc (must honour HF_BASE and need no creds under DRY_RUN)"
  else
    ok "fixture run exits 0"
    miss=0
    while IFS=$'\t' read -r id want _; do
      case "$id" in \#*|"") continue;; esac
      got=$(printf '%s\n' "$out" | grep -F "] $id - " | head -1 | sed -E 's/^\[([a-z]+)\].*/\1/')
      if [ "$got" = "$want" ]; then ok "$id → $want"
      else no "$id → got '${got:-<no line>}', expected '$want'"; miss=1; fi
    done < "$SPEC/fixtures/EXPECTED.tsv"
    [ $miss -eq 0 ] && ok "all fixture buckets correct"
    # Behavioural, not grep-based: did it actually READ the model cards?
    if grep -q '/raw/main/README.md' "$RL"; then ok "fetched model card(s)"
    else no "never fetched a model card — the LLM has nothing to judge from"; fi
  fi
  rm -f "$RL"
else pend "classifier fixture checks"; fi

if [ "${LIVE:-0}" = 1 ] && [ -f "$S" ]; then
  echo "== live HuggingFace smoke (opt-in) =="
  lout=$(cd "$D" && DRY_RUN=1 WINDOW_DAYS=45 MIN_LIKES=40 VRAM_BUDGET_GB=96 \
         timeout 420 python3 model-watch.py 2>/dev/null)
  n=$(printf '%s\n' "$lout" | grep -cE '^\[(test|consider|watch|skip)\] ')
  [ "$n" -ge 3 ] && ok "live sweep classified $n candidates" || no "live sweep produced $n lines"
fi

echo
[ $fail -eq 0 ] && echo "VERIFY: PASS" || echo "VERIFY: FAIL"
exit $fail
