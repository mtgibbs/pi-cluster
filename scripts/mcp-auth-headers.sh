#!/usr/bin/env bash
# Claude Code MCP `headersHelper` for the homelab HTTP MCP servers (.mcp.json).
#
# Claude Code runs this on each connect with CLAUDE_CODE_MCP_SERVER_NAME set and expects a JSON
# object of headers on stdout — nothing else — within 10s. Replaces the old `.zshrc` `mcp-auth`
# env-var dance, which the desktop app never runs.
#
# Two auth paths, by vault (see docs/secrets-map.md "Vaults"):
#   homelab-agent  Tier 1, read-only creds. Read with the `homelab-agent-laptop` service-account
#                  token from macOS Keychain (service `homelab-agent-op-token`). No prompt.
#   pi-cluster     Everything else. Plain `op read` via the 1Password app (Touch ID).
#
# Runs from the project dir (relative path in .mcp.json), only once the folder is trusted.
# Claude Code strips TOKEN/KEY-looking env vars from project helpers, hence Keychain, not env.
# References use vault/item IDs, not names, so renames don't break auth.
# Never prints a secret anywhere but the stdout JSON; errors name the server, never the value.
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

VAULT_HOMELAB_AGENT="kiabi5jm2l2p6w6wnnowmwoxxm"
VAULT_PI_CLUSTER="4gyjexiqw5fzm4ucpcryl6k4wi"
KEYCHAIN_SERVICE="homelab-agent-op-token"
OP_TIMEOUT_SECS=9

die() { echo "mcp-auth-headers: $*" >&2; exit 1; }

server="${CLAUDE_CODE_MCP_SERVER_NAME:-}"
[ -n "$server" ] || die "CLAUDE_CODE_MCP_SERVER_NAME is not set"

case "$server" in
  local-llm) vault="$VAULT_HOMELAB_AGENT"; ref="op://$VAULT_HOMELAB_AGENT/gdqku6lz7ohyuhlh4khr67howq/password" ;;
  homelab)   vault="$VAULT_PI_CLUSTER";    ref="op://$VAULT_PI_CLUSTER/mkxiuzs5i3pvsvecgbdcfu65m4/api-key" ;;
  *) die "no credential mapping for MCP server '$server'" ;;
esac

# No op on this host (e.g. the coding-harness container, which gets keys as env vars): emit no
# dynamic headers so the static `headers` fallback in .mcp.json applies.
command -v op >/dev/null || { echo '{}'; exit 0; }
command -v jq >/dev/null || die "jq not found"

# op can hang on a Touch ID prompt nobody answers; stay inside Claude Code's 10s budget.
op_read() { perl -e 'alarm shift; exec @ARGV' "$OP_TIMEOUT_SECS" op read --no-newline "$1" 2>/dev/null; }

if [ "$vault" = "$VAULT_HOMELAB_AGENT" ]; then
  token="$(security find-generic-password -s "$KEYCHAIN_SERVICE" -w 2>/dev/null)" \
    || die "Keychain item '$KEYCHAIN_SERVICE' not found (see docs/secrets-map.md)"
  value="$(OP_SERVICE_ACCOUNT_TOKEN="$token" op_read "$ref")" \
    || die "op read failed for '$server' (service-account path)"
  unset token
else
  # A stray service-account token in the env would make op skip the app (and fail: wrong vault).
  value="$(unset OP_SERVICE_ACCOUNT_TOKEN; op_read "$ref")" \
    || die "op read failed for '$server' (1Password app / Touch ID path)"
fi

[ -n "$value" ] || die "empty credential for '$server'"
# Via stdin, not --arg, so the value never shows up in a process listing.
printf '%s' "$value" | jq -Rsc '{"X-API-Key": .}'
