#!/usr/bin/env bash
# Deterministic gate for specs/model-watch. Asserts OUTCOMES, not implementation —
# how the script discovers params/licence/derivative-ness is the executor's business;
# that the wrong models don't reach the `test` bucket is not.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1
D=clusters/pi-k3s/model-watch
fail=0
ok(){ echo "  PASS  $1"; }
no(){ echo "  FAIL  $1"; fail=1; }

echo "== files =="
for f in model-watch.py namespace.yaml external-secret.yaml cronjob.yaml kustomization.yaml; do
  [ -f "$D/$f" ] && ok "$f exists" || no "$D/$f missing"
done

echo "== script hygiene =="
python3 -m py_compile "$D/model-watch.py" 2>/dev/null && ok "compiles" || no "syntax error"
if grep -Eq '^[[:space:]]*(import|from)[[:space:]]+(requests|httpx|yaml|aiohttp|bs4|pandas|numpy)\b' "$D/model-watch.py"; then
  no "third-party import found (stdlib only)"
else ok "stdlib only"; fi
grep -q 'DRY_RUN' "$D/model-watch.py" && ok "honours DRY_RUN" || no "no DRY_RUN support"

echo "== manifests =="
grep -Eq 'schedule:[[:space:]]*"[^"]*\*[[:space:]]*\*"' "$D/cronjob.yaml" \
  && ok "monthly-ish schedule" || no "cronjob schedule not monthly (day-of-month pinned?)"
grep -q 'litellm-api-key' "$D/external-secret.yaml" && ok "litellm key wired" || no "no litellm-api-key"
grep -q 'ntfy/family-password' "$D/external-secret.yaml" && ok "reuses family ntfy cred" || no "ntfy cred not reused"
grep -q 'model-watch/litellm-key' "$D/external-secret.yaml" && ok "1P path correct" || no "wrong 1P path"
grep -q 'ntfy access family "model-watch"' clusters/pi-k3s/ntfy/deployment.yaml \
  && ok "ntfy ACL granted" || no "missing ntfy ACL (publish would 403)"
grep -q 'path: ./clusters/pi-k3s/model-watch' clusters/pi-k3s/flux-system/infrastructure.yaml \
  && ok "registered with Flux" || no "not registered in infrastructure.yaml"

echo "== behaviour (live HF, DRY_RUN) =="
out=$(cd "$D" && DRY_RUN=1 WINDOW_DAYS=45 MIN_LIKES=40 VRAM_BUDGET_GB=96 \
      timeout 420 python3 model-watch.py 2>/dev/null)
rc=$?
[ $rc -eq 0 ] && ok "exits 0 with no LiteLLM/ntfy env set" || { no "exit $rc (must not need creds in DRY_RUN)"; }
lines=$(printf '%s\n' "$out" | grep -cE '^\[(test|consider|watch|skip)\] ')
[ "$lines" -ge 3 ] && ok "emitted $lines classified candidates" || no "only $lines lines match the output contract"

# A model far over budget must never be offered as testable.
if printf '%s\n' "$out" | grep -E '^\[test\] ' | grep -Eqi 'deepseek-v4-flash|longcat|kimi-k3|glm-5\.2'; then
  no "an over-budget model reached the test bucket"
else ok "over-budget models kept out of test"; fi

# Derivative repos are noise, not releases.
if printf '%s\n' "$out" | grep -E '^\[test\] ' | grep -Eqi 'gguf|abliterated|awq|-int4|bartowski|unsloth'; then
  no "a derivative/quant repo reached the test bucket"
else ok "derivative repos kept out of test"; fi

echo
[ $fail -eq 0 ] && echo "VERIFY: PASS" || echo "VERIFY: FAIL"
exit $fail
