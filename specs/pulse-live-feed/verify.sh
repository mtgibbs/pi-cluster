#!/usr/bin/env bash
# verify.sh — deterministic acceptance gate for specs/pulse-live-feed.
# §10 acceptance criteria + §8 safeguards compiled to runnable assertions: exit 0 = acceptable.
#
# PRESENCE-GATED (the ralph contract): this runs after EVERY task and must pass, so a check for
# a not-yet-written identifier is PEND (skipped), never FAIL. Once the identifier exists, its
# behaviour is asserted for real. By the final task every check is active.
#
# STATIC tier only — no browser, no network. The LIVE tier (restart the collector, sleep the
# laptop, stop the container and confirm it says SIMULATED) is spec §11 and is a human's job
# after merge; a grep cannot prove "recovered without a refresh".
#
# Run from repo root:  ./specs/pulse-live-feed/verify.sh
set -uo pipefail
F="${F:-harness-console/index.html}"
fail=0
ok(){   echo "  PASS  $1"; }
no(){   echo "  FAIL  $1" >&2; fail=1; }
pend(){ echo "  pend  $1 (not built yet)"; }
has(){  grep -q -- "$1" "$F" 2>/dev/null; }

echo "VERIFY specs/pulse-live-feed  ($F)"
[ -f "$F" ] || { echo "  FAIL  $F missing" >&2; exit 1; }

# --- the file must stay loadable at all: one inline script, no build step (Norms) ---
if command -v node >/dev/null 2>&1; then
  python3 - "$F" > /tmp/_pulse_js 2>/dev/null <<'PY'
import re,sys
s=open(sys.argv[1]).read()
print("\n".join(re.findall(r'<script[^>]*>(.*?)</script>', s, re.S)))
PY
  if [ -s /tmp/_pulse_js ]; then
    node --check /tmp/_pulse_js 2>/dev/null && ok "inline script parses" || no "inline script has a syntax error"
  else
    pend "could not extract inline script"
  fi
  rm -f /tmp/_pulse_js
else
  pend "node absent — skipping syntax check"
fi

# --- T1: state machine + constants (§3, AC6) ---
if has "feedState"; then
  ok "feedState exists"
  has "setFeedState" && ok "setFeedState() exists" || no "setFeedState() missing"
  has "SIMULATED"    && ok "sim indicator text present (AC6)" || no "no SIMULATED indicator (AC6)"
  has "RECONNECTING" && ok "stale indicator text present"     || no "no RECONNECTING indicator"
else pend "feedState"; fi

for c in STREAM_STALE_MS TX_MIN_GAP_MS TX_QUEUE_MAX RECYCLE_MIN_MS RECYCLE_MAX_MS; do
  if has "$c"; then ok "$c defined"; else pend "$c"; fi
done

# --- T2: poll hysteresis (AC1, AC2, AC3) ---
if has "pollFails"; then
  ok "pollFails exists"
  # AC2 is specifically "3 or more" — a threshold of 1 would be the bug we are fixing.
  grep -qE 'pollFails[^;]*(>=|>) *[3-9]' "$F" && ok "flip requires >=3 consecutive failures (AC2)" \
    || no "no >=3 failure threshold found — a single blip must not flip the display (AC1/AC2)"
  grep -qE 'pollFails *= *0' "$F" && ok "pollFails resets on success (AC3)" || no "pollFails never resets (AC3)"
else pend "pollFails"; fi

# --- T3: single owned EventSource (Safeguard 3) ---
if has "openStream"; then
  ok "openStream() exists"
  grep -qE '\.close\(\)' "$F" && ok "previous stream is closed before reopening (Safeguard 3)" \
    || no "openStream() never closes the old EventSource — two streams can run (Safeguard 3)"
  has "lastStreamMsg" && ok "lastStreamMsg tracked" || no "lastStreamMsg missing (AC4)"
else pend "openStream"; fi

# --- the backfill guard must SURVIVE the refactor (§6) ---
# Every recycle re-delivers the collector's ring buffer. Lose this and each reconnect
# repaints a burst of history as if it had just happened.
if has "lastStreamMsg"; then
  grep -qE '\) > 30|> *30\)' "$F" && ok "30s backfill age guard still present (§6)" \
    || no "backfill age guard lost — a recycle will flash stale traffic (§6)"
fi

# --- T4: wedged-stream watchdog (AC4, AC9) ---
if has "STREAM_STALE_MS"; then
  grep -qE 'lastStreamMsg' "$F" && ok "watchdog compares against lastStreamMsg (AC4)" || no "AC4 not implemented"
  grep -qE 'Math\.min\(.*RECYCLE_MAX_MS|RECYCLE_MAX_MS.*Math\.min' "$F" \
    && ok "recycle delay is capped (AC9, Safeguard 3)" || no "no capped backoff on recycle (AC9)"
else pend "watchdog"; fi

# --- T5: revalidate on becoming visible (AC5) ---
if has "visibilitychange"; then
  ok "visibilitychange handler present (AC5)"
  has "visibilityState" && ok "checks visibilityState" || no "visibilitychange handler ignores visibilityState"
else pend "visibilitychange"; fi

# --- T6: paced release + bounded queue (AC7, AC8, Safeguard 2) ---
if has "txQueue"; then
  ok "txQueue exists"
  grep -qE 'txQueue\.push' "$F" && ok "events are enqueued (AC7)" || no "txQueue never filled (AC7)"
  grep -qE 'txQueue\.shift' "$F" && ok "queue is drained one at a time (AC7)" || no "txQueue never drained (AC7)"
  grep -qE 'txQueue\.length *> *TX_QUEUE_MAX|TX_QUEUE_MAX' "$F" && ok "queue is bounded (AC8, Safeguard 2)" \
    || no "txQueue is unbounded — a long-open page grows forever (Safeguard 2)"
else pend "txQueue"; fi

# --- Safeguard 1: sim generator and the sim badge are the same condition ---
if has "feedState" && has "stepSimTrans"; then
  grep -qE "feedState *[!=]== *['\"]sim['\"]" "$F" \
    && ok "sim generator is gated on feedState (Safeguard 1)" \
    || no "sim traffic is not tied to feedState — the page can invent data while claiming live (Safeguard 1)"
fi

# --- Scope: this spec may not touch the collector (it is in another repo, §5) ---
if [ -n "$(git status --porcelain -- files/ 2>/dev/null)" ]; then
  no "changes outside harness-console/ — the collector lives in beelink-ansible (§5)"
else
  ok "change stayed inside this repo's scope (§5)"
fi

echo
[ "$fail" = 0 ] && echo "VERIFY: PASS" || echo "VERIFY: FAIL"
exit "$fail"
