#!/usr/bin/env bash
# Deterministic gate for specs/model-watch.
#
# Run from repo root:  bash specs/model-watch/verify.sh    (STRICT=1 for the final pass)
#
# Asserts OUTCOMES, not implementation — how the script discovers params/licence/
# derivative-ness is the executor's business; that the wrong models don't reach the
# `test` bucket is not.
#
# Uses the three-verdict contract (see specs/TEMPLATE.md §11). Checks are gated on the
# ARTIFACT existing, not on a task number, so each one arms itself the moment its target
# is written — in whatever order the model builds. STRICT=1 turns every remaining `pend`
# into a FAIL, so "every task passed" can't mean "half of it was never written".
set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1
D=clusters/pi-k3s/model-watch
S=$D/model-watch.py
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
  # The whole point is the HF sweep. A script that never contacts the Hub is a
  # different product, however well it runs (see the 2026-08-11 dogfood).
  grep -q 'huggingface.co' "$S" && ok "queries the HuggingFace API" \
    || no "never contacts huggingface.co — this is not the specified feature"
else pend "script hygiene checks"; fi

echo "== manifests =="
if [ -f "$D/external-secret.yaml" ]; then
  grep -q 'litellm-api-key'      "$D/external-secret.yaml" && ok "litellm key wired"      || no "no litellm-api-key"
  grep -q 'ntfy/family-password' "$D/external-secret.yaml" && ok "reuses family ntfy cred" || no "ntfy cred not reused (reuse-before-mint)"
  grep -q 'model-watch/litellm-key' "$D/external-secret.yaml" && ok "1P path correct"      || no "wrong 1P path"
else pend "external-secret assertions"; fi

if [ -f "$D/cronjob.yaml" ]; then
  grep -Eq 'schedule:[[:space:]]*"[^"]*\*[[:space:]]*\*"' "$D/cronjob.yaml" \
    && ok "monthly-ish schedule" || no "schedule not monthly (day-of-month pinned?)"
else pend "cronjob assertions"; fi

# Cross-cutting edits that live in OTHER files — the classic later-task work.
grep -q 'ntfy access family "model-watch"' clusters/pi-k3s/ntfy/deployment.yaml 2>/dev/null \
  && ok "ntfy ACL granted" || pend "ntfy ACL (deny-all default ⇒ publish would 403)"
grep -q 'path: ./clusters/pi-k3s/model-watch' clusters/pi-k3s/flux-system/infrastructure.yaml 2>/dev/null \
  && ok "registered with Flux" || pend "Flux registration in infrastructure.yaml"

echo "== behaviour (live HF, DRY_RUN) =="
if [ -f "$S" ]; then
  out=$(cd "$D" && DRY_RUN=1 WINDOW_DAYS=45 MIN_LIKES=40 VRAM_BUDGET_GB=96 \
        timeout 420 python3 model-watch.py 2>/dev/null); rc=$?
  [ $rc -eq 0 ] && ok "exits 0 with no LiteLLM/ntfy env set" \
                || no "exit $rc (DRY_RUN must need no creds)"
  lines=$(printf '%s\n' "$out" | grep -cE '^\[(test|consider|watch|skip)\] ')
  if [ "$lines" -ge 3 ]; then
    ok "emitted $lines classified candidates"
    # These two are only meaningful once there IS output — otherwise they pass vacuously.
    printf '%s\n' "$out" | grep -E '^\[test\] ' \
      | grep -Eqi 'deepseek-v4-flash|longcat|kimi-k3|glm-5\.2' \
      && no "an over-budget model reached the test bucket" || ok "over-budget models kept out of test"
    printf '%s\n' "$out" | grep -E '^\[test\] ' \
      | grep -Eqi 'gguf|abliterated|awq|-int4|bartowski|unsloth' \
      && no "a derivative/quant repo reached the test bucket" || ok "derivative repos kept out of test"
  else
    no "only $lines lines match the §10 output contract '[bucket] id - reason'"
    pend "bucket-content assertions (need output first)"
  fi
else pend "behaviour checks"; fi

echo
[ $fail -eq 0 ] && echo "VERIFY: PASS" || echo "VERIFY: FAIL"
exit $fail
