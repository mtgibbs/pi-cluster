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

# Lift a named function out by BRACE MATCHING, not by indentation. An awk range anchored on
# "^  }" silently fails the moment the code sits at a different depth, and a silent extraction
# failure is indistinguishable from a passing test — which is precisely the trap this gate was
# rewritten to escape. Prints the function source, or nothing.
lift() { # lift <file> <fnName>
  node -e '
    const fs=require("fs"), src=fs.readFileSync(process.argv[1],"utf8"), name=process.argv[2];
    const m=new RegExp("function\\s+"+name+"\\s*\\(").exec(src);
    if(!m){ process.exit(0); }
    let i=m.index, s=src.indexOf("{",i), d=0, j=s;
    for(;j<src.length;j++){ if(src[j]==="{")d++; else if(src[j]==="}"){d--; if(!d){j++;break;} } }
    process.stdout.write(src.slice(i,j));
  ' "$1" "$2" 2>/dev/null
}

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

# --- AC1/AC2/AC3/AC4: EXECUTE feedNext against the §6 truth table ---
# These are claims about behaviour under a sequence of observations. A grep for "pollFails >= 3"
# proves the digit 3 appears in the file, nothing more. Three specs in this repo have now shipped
# or nearly shipped defects that way, so the decision lives in a pure function and gets RUN.
#
# FAIL CLOSED: once feedState exists, a missing or unliftable feedNext is a failure. "I could not
# test this" must never read the same as "this is fine" — that exact leniency let a do-nothing
# parser pass in specs/harness-multi-repo.
if has "feedState"; then
  if ! grep -qE 'function +feedNext' "$F"; then
    no "AC1-AC4: feedNext() missing — see the WORKED EXAMPLE in spec §6"
  elif ! command -v node >/dev/null 2>&1; then
    pend "feedNext behavioural check (node absent)"
  else
    probe="$(mktemp -t fnext)"
    { grep -oE 'STREAM_STALE_MS *= *[0-9]+' "$F" | head -1 | sed 's/^/const /;s/$/;/'
      lift "$F" feedNext
      cat <<'JS'
const rows = [
  ["live", true,  0, 1000,  "live", false],
  ["live", false, 1, 1000,  "live", false],
  ["live", false, 2, 1000,  "live", false],
  ["live", false, 3, 1000,  "sim",  false],
  ["sim",  true,  0, 1000,  "live", false],
  ["live", true,  0, 60000, "live", true ],
  ["sim",  false, 9, 60000, "sim",  false],
];
let bad = [];
for (const [st, ok, f, ms, wSt, wRe] of rows) {
  let r; try { r = feedNext(st, ok, f, ms); } catch (e) { bad.push(`${st}/${ok}/${f}/${ms}: threw`); continue; }
  if (!r || r.state !== wSt || !!r.recycle !== wRe)
    bad.push(`${st},ok=${ok},fails=${f},ms=${ms} -> ${JSON.stringify(r)} want {state:"${wSt}",recycle:${wRe}}`);
}
console.log(bad.length ? "BAD:" + bad[0] : "OK");
JS
    } > "$probe"
    res="$(node "$probe" 2>/dev/null)"; rm -f "$probe"
    case "$res" in
      OK)   ok "AC1-AC4: feedNext matches the §6 truth table (hysteresis, instant recovery, wedged-stream rule)" ;;
      BAD*) no "${res#BAD:}" ;;
      *)    no "AC1-AC4: feedNext could not be lifted out and run — is it pure? (see §7 Norms)" ;;
    esac
  fi
else pend "feedState"; fi

# --- AC7/AC8: EXECUTE txAdmit — bounded queue, oldest dropped first ---
if has "txQueue"; then
  if ! grep -qE 'function +txAdmit' "$F"; then
    no "AC7/AC8: txAdmit() missing — see the WORKED EXAMPLE in spec §6"
  elif command -v node >/dev/null 2>&1; then
    probe="$(mktemp -t tadmit)"
    { lift "$F" txAdmit
      cat <<'JS'
let q = [];
for (let i = 0; i < 30; i++) q = txAdmit(q, i, 24);
const okLen = q.length === 24;
const okNew = q[q.length - 1] === 29;   // newest kept
const okOld = q[0] === 6;               // oldest dropped first
console.log(okLen && okNew && okOld ? "OK" : `BAD len=${q.length} first=${q[0]} last=${q[q.length-1]}`);
JS
    } > "$probe"
    res="$(node "$probe" 2>/dev/null)"; rm -f "$probe"
    case "$res" in
      OK)   ok "AC7/AC8: txAdmit caps the queue and drops oldest first" ;;
      BAD*) no "AC8: $res (expected len=24 first=6 last=29)" ;;
      *)    no "AC7/AC8: txAdmit could not be lifted out and run — is it pure?" ;;
    esac
  else pend "txAdmit behavioural check (node absent)"; fi
else pend "txQueue"; fi

# --- T3: single owned EventSource (Safeguard 3) ---
if has "openStream"; then
  ok "openStream() exists"
  grep -qE '\.close\(\)' "$F" && ok "previous stream is closed before reopening (Safeguard 3)" \
    || no "openStream() never closes the old EventSource — two streams can run (Safeguard 3)"
  has "lastStreamMsg" && ok "lastStreamMsg tracked" || no "lastStreamMsg missing (AC4)"
else pend "openStream"; fi

# --- the backfill guard must SURVIVE the refactor (§6) ---
if has "lastStreamMsg"; then
  grep -qE '\) > 30|> *30\)' "$F" && ok "30s backfill age guard still present (§6)" \
    || no "backfill age guard lost — a recycle will flash stale traffic (§6)"
fi

# --- AC9: recycle backoff is capped ---
if has "STREAM_STALE_MS"; then
  grep -qE 'Math\.min\(.*RECYCLE_MAX_MS|RECYCLE_MAX_MS.*Math\.min' "$F" \
    && ok "recycle delay is capped (AC9, Safeguard 3)" || no "no capped backoff on recycle (AC9)"
fi

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
