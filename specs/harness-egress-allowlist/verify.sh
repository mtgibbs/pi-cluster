#!/usr/bin/env bash
# verify.sh — deterministic acceptance gate for specs/harness-egress-allowlist.
# §10 acceptance criteria + §8 safeguards compiled to runnable assertions: exit 0 = acceptable.
#
# PRESENCE-GATED (the ralph contract): runs after EVERY task and must pass, so a check for a
# not-yet-written identifier is PEND, never FAIL. STRICT=1 (ralph's final pass) turns every pend
# into a failure — because presence-gating can verify "correct if present" but can NEVER verify
# "done": a run that changed nothing pends everything and would otherwise pass.
#
# TARGET REPO: the work lands in `beelink-ansible`, not here. Point this at a checkout:
#     ANSIBLE_REPO=../beelink-ansible ./specs/harness-egress-allowlist/verify.sh
# Default is `.` so it also works when a --repo loop runs it from inside that repo.
#
# STATIC tier only. It CANNOT prove traffic is actually blocked — that is spec §11's LIVE tier and
# a human's call after deploy. What it can prove is that the shape is right and the safeguards hold.
set -uo pipefail
R="${ANSIBLE_REPO:-.}"
fail=0
ok(){   echo "  PASS  $1"; }
no(){   echo "  FAIL  $1" >&2; fail=1; }
pend(){
  if [ "${STRICT:-0}" = 1 ]; then no "$1 — still unbuilt at the final check (STRICT)"; else
    echo "  pend  $1 (not built yet)"; fi
}

echo "VERIFY specs/harness-egress-allowlist  (ANSIBLE_REPO=$R)"

if [ ! -d "$R" ]; then
  pend "beelink-ansible checkout not found at '$R' — every check"
  echo; [ "$fail" = 0 ] && echo "VERIFY: PASS" || echo "VERIFY: FAIL"; exit "$fail"
fi

# Collect candidate files by CONTENT, not by a guessed path — the ansible repo layout is OQ1.
mapfile -t COMPOSE < <(grep -rl -- "coding-harness" "$R" \
  --include='*.yml' --include='*.yaml' --include='*.j2' 2>/dev/null | sort -u)
ALLOW="$(find "$R" -name 'allowlist.conf' 2>/dev/null | head -1)"
mapfile -t NFT < <(grep -rl -iE "nftables|DOCKER-USER|iptables" "$R" \
  --include='*.yml' --include='*.yaml' --include='*.j2' --include='*.conf' --include='*.sh' 2>/dev/null | sort -u)

incompose(){ [ "${#COMPOSE[@]}" -gt 0 ] && grep -qE -- "$1" "${COMPOSE[@]}" 2>/dev/null; }

# ---------- AC1: the proxy service exists ----------
if incompose 'harness-egress'; then ok "AC1: harness-egress service present"
else pend "AC1: harness-egress service"; fi

# ---------- AC2/AC3: proxy env wired into the harness containers ----------
if incompose 'HTTPS?_PROXY'; then
  ok "AC2: proxy env vars present"
  incompose 'NO_PROXY' && ok "AC2: NO_PROXY present" || no "AC2: NO_PROXY missing — without it, container-to-container traffic detours through the proxy"
  # AC3 is the single most likely thing to break the harness (spec §6).
  if incompose 'NO_PROXY[^\n]*litellm'; then ok "AC3: litellm excluded from proxying"
  else no "AC3: NO_PROXY does not name litellm — model traffic (http://litellm:4000) would be proxied and will break"; fi
else pend "AC2: proxy env vars"; fi

# ---------- AC4: the network declares a fixed subnet (DOCKER-USER must match on it) ----------
if incompose 'harness-egress|HTTPS?_PROXY'; then
  if incompose 'subnet:'; then ok "AC4: network declares a fixed subnet"
  else no "AC4: no 'subnet:' declared — container IPs are not stable, so phase-2 DOCKER-USER has nothing to match on"; fi

  # AC4b: OQ1 found ALL 18 services on the single shared `ai-internal` bridge. Confining that
  # subnet would confine ollama/litellm/postgres/caddy too, so the harness must move to its own
  # network — and litellm must join it, or `http://litellm:4000` stops resolving by name and every
  # loop on the box breaks. Both halves are checked because either alone is a broken state.
  if incompose 'harness-net'; then
    ok "AC4b: a dedicated harness-net is declared"
    # Extract the litellm service block BY NAME and indentation, then look inside it.
    # A whole-file `grep -qzE 'litellm:(.|\n)*?harness-net'` does NOT work: POSIX ERE has no lazy
    # quantifier, so it matches `litellm:` followed by `harness-net` ANYWHERE later — including the
    # bottom-level `networks:` declaration. That gave a false PASS on a fixture where litellm was
    # not on harness-net at all. Scope the search to the block.
    litellm_blk=""
    for f in "${COMPOSE[@]}"; do
      litellm_blk="$litellm_blk$(awk '
        /^[[:space:]]*litellm:[[:space:]]*$/ && !inblk { ind=match($0,/[^ ]/); inblk=1; next }
        inblk {
          if ($0 ~ /^[[:space:]]*$/) next
          if (match($0,/[^ ]/) <= ind) { inblk=0; next }
          print
        }' "$f" 2>/dev/null)"
    done
    if [ -z "$litellm_blk" ]; then
      pend "AC4b: litellm service block not found"
    elif printf '%s' "$litellm_blk" | grep -qE 'harness-net'; then
      ok "AC4b: litellm is attached to harness-net"
    else
      no "AC4b: litellm is NOT attached to harness-net — the harness would lose http://litellm:4000 by name and every loop breaks (spec §4)"
    fi
  else
    pend "AC4b: dedicated harness-net"
  fi
fi

# ---------- AC5/AC6/AC7: the allowlist file ----------
if [ -n "$ALLOW" ]; then
  ok "allowlist.conf present ($ALLOW)"

  # AC6: every active entry is preceded by a '#' reason comment.
  missing="$(awk '
    /^[[:space:]]*#/ { prev_comment=1; next }
    /^[[:space:]]*$/ { prev_comment=0; next }
    { if (!prev_comment) print FNR": "$0; prev_comment=0 }
  ' "$ALLOW")"
  if [ -z "$missing" ]; then ok "AC6: every allowlist entry has a reason comment"
  else no "AC6: entries with no preceding '# why' comment (§7): $(echo "$missing" | tr '\n' ' ')"; fi

  # AC7: no wildcard broader than a single label. '*.example.com' ok; '*.com' / '*' not.
  broad="$(grep -nE '(^|[[:space:]])\*([[:space:]]|$)|\*\.[A-Za-z]+([[:space:]]|$)' "$ALLOW" \
    | grep -v '^[[:space:]]*#' || true)"
  if [ -z "$broad" ]; then ok "AC7: no over-broad wildcard patterns"
  else no "AC7: over-broad wildcard(s): $(echo "$broad" | tr '\n' ' ')"; fi
else
  pend "allowlist.conf (AC6, AC7)"
fi

# AC5: phase 1 must be log-only. Once an enforce marker appears, an explicit phase-2 marker
# must appear with it — so enforcement cannot land silently inside an observation change.
if [ -n "$ALLOW" ] || incompose 'harness-egress'; then
  if grep -rqiE 'log[-_]?only|monitor[-_]?mode|permit[-_]?all' "$R" 2>/dev/null; then
    ok "AC5: log-only/monitor mode marker present"
  else
    pend "AC5: log-only marker"
  fi
fi

# ---------- AC8: no credential literals anywhere in what we added ----------
CRED='ghp_|github_pat_|x-access-token|sk-[A-Za-z0-9]{16,}|LITELLM_.*KEY[[:space:]]*=[[:space:]]*[A-Za-z0-9]'
hits=""
[ -n "$ALLOW" ] && hits="$hits$(grep -nEl "$CRED" "$ALLOW" 2>/dev/null || true)"
[ "${#COMPOSE[@]}" -gt 0 ] && hits="$hits$(grep -lE "$CRED" "${COMPOSE[@]}" 2>/dev/null || true)"
if [ -z "$hits" ]; then ok "AC8: no credential literals (Safeguard 1)"
else no "AC8: credential literal in $hits (Safeguard 1)"; fi

# ---------- AC9: harness confinement must not be relaxed ----------
if [ "${#COMPOSE[@]}" -gt 0 ]; then
  if grep -qE 'NET_ADMIN|privileged:[[:space:]]*true' "${COMPOSE[@]}" 2>/dev/null; then
    no "AC9: NET_ADMIN or privileged:true appears in a compose file — harness containers must not manage their own firewall (Safeguard 3)"
  else ok "AC9: no NET_ADMIN / privileged (Safeguard 3)"; fi

  # AC10 + Safeguard 4: nothing here earns the Docker socket, least of all a network appliance.
  if grep -qE '/var/run/docker\.sock' "${COMPOSE[@]}" 2>/dev/null; then
    no "AC10: a docker.sock mount appears in a compose file (Safeguard 4)"
  else ok "AC10: no docker.sock mount (Safeguard 4)"; fi
fi

# ---------- AC11: phase-2 firewall rules stay scoped to the harness subnet ----------
# Safeguard 7: a rule that catches the host's own egress costs remote access to the box.
if [ "${#NFT[@]}" -gt 0 ] && grep -rqE 'DOCKER-USER' "${NFT[@]}" 2>/dev/null; then
  ok "AC11: DOCKER-USER chain referenced"
  if grep -rqE '(-s|saddr)[[:space:]]*[0-9]{1,3}(\.[0-9]{1,3}){3}/[0-9]{1,2}' "${NFT[@]}" 2>/dev/null; then
    ok "AC11: rules are scoped to a source subnet"
  else
    no "AC11: DOCKER-USER rules present with no source-subnet scope — this can catch traffic beyond the harness (Safeguard 7)"
  fi
  # Match the port however it is spelled — `dport 22`, `--dport 22`, `:22`, or a named service.
  # An earlier version only matched `:22` and sailed past an nftables `tcp dport 22 accept`.
  grep -rqiE 'tailscale|tailscale0|(^|[^A-Za-z])ssh([^A-Za-z]|$)|-?-?dport[[:space:]]+22([^0-9]|$)|:22([^0-9]|$)' "${NFT[@]}" 2>/dev/null \
    && no "AC11: firewall rules reference SSH/Tailscale — out of scope and a lockout risk (Safeguard 7)" \
    || ok "AC11: rules do not touch SSH/Tailscale paths"

  # AC13 / Safeguard 8: ai-internal carries all 18 services. A rule naming it confines the whole box.
  grep -rqE 'ai-internal' "${NFT[@]}" 2>/dev/null \
    && no "AC13: a firewall rule references ai-internal — that subnet holds all 18 services, not just the harness (Safeguard 8)" \
    || ok "AC13: no firewall rule references ai-internal (Safeguard 8)"
else
  pend "AC11: phase-2 nftables rules"
fi

# ---------- AC12: no TLS interception, ever (Safeguard 2) ----------
if grep -rqiE 'mitmproxy|ssl[-_]?bump|ssl_?crtd|CAcert|rootCA\.(pem|crt)|update-ca-certificates' "$R" \
     --include='*.yml' --include='*.yaml' --include='*.j2' --include='*.conf' --include='*.sh' 2>/dev/null; then
  no "AC12: TLS-interception / custom-CA machinery detected — spec §4 rules this out (Safeguard 2)"
else
  ok "AC12: no TLS interception (Safeguard 2)"
fi

echo
[ "$fail" = 0 ] && echo "VERIFY: PASS" || echo "VERIFY: FAIL"
exit "$fail"
