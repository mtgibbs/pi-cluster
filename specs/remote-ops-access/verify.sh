#!/usr/bin/env bash
# verify.sh — Remote-Ops Access spec gate.
# STATIC tier (offline, gates the change). LIVE tier is commented at the bottom (human-run from off-net).
#
# Cross-repo: the change lives in the beelink-ansible repo, not pi-cluster. We check it at its known
# local path; if that checkout isn't present we SKIP the static assertion (don't fail a clean machine).
set -uo pipefail

INV="${BEELINK_ANSIBLE_INVENTORY:-/Users/mtgibbs/dev/beelink-ansible/inventory.yml}"
TAILNET_IP="100.123.94.31"
fail=0
pass(){ echo "  PASS: $1"; }
bad(){ echo "  FAIL: $1"; fail=1; }

echo "== STATIC: beelink-ansible inventory addresses the Beelink over Tailscale =="
if [[ ! -f "$INV" ]]; then
  echo "  SKIP: $INV not found (beelink-ansible not checked out here) — re-run where it lives."
else
  # beelink-ai must have an ansible_host on the tailnet path (100.x IP or a *.ts.net MagicDNS name),
  # i.e. NOT relying solely on the LAN-only ssh alias (which resolves to 192.168.1.70).
  if grep -qE "ansible_host:\s*(${TAILNET_IP}|[a-z0-9-]+\.[a-z0-9.-]+\.ts\.net)" "$INV"; then
    pass "beelink-ai has a tailnet ansible_host (no per-run override needed)"
  else
    bad "beelink-ai lacks a tailnet ansible_host — remote deploy will hit 192.168.1.70 (unrouted)"
  fi
  # Safeguard: the committed inventory must not carry an inline secret.
  if grep -qiE "(password|token|api[_-]?key|secret)\s*[:=]" "$INV"; then
    bad "inventory.yml appears to contain an inline secret — creds belong in ssh-config + 1Password"
  else
    pass "no inline secret in inventory.yml"
  fi
fi

echo "== STATIC: spec self-consistency =="
SPEC="$(dirname "$0")/spec.md"
if grep -q "do NOT expose" "$SPEC" && grep -q "172.18.0.5:11434" "$SPEC"; then
  pass "spec keeps Ollama/LiteLLM internal + records the SSH break-glass path"
else
  bad "spec missing the internal-only invariant or the break-glass path"
fi

echo
if [[ $fail -eq 0 ]]; then echo "verify.sh: OK"; exit 0; else echo "verify.sh: FAILED"; exit 1; fi

# ---- LIVE tier (NOT gated — run by a human from off-net) ----
# Phase 1:  cd /Users/mtgibbs/dev/beelink-ansible && ansible -i inventory.yml inference -m ping
#           -> expect "ping: pong" with NO -e ansible_host override.
# Phase 1:  while ON the home LAN, re-run the same ping -> must still connect.
# Phase 2:  curl -fsS -H "Authorization: Bearer <litellm-virtual-key>" \
#                https://ai.lab.mtgibbs.dev/health   -> expect HTTP 200 from off-net.
# Safeguard: from off-net, a direct curl to the Beelink :11434 / :4000 MUST fail (stay internal).
