#!/usr/bin/env bash
# verify.sh — deterministic acceptance gate for specs/pulse-threads.
# §10 acceptance criteria + §8 safeguards compiled to runnable assertions: exit 0 = acceptable.
#
# PRESENCE-GATED (the ralph contract): runs after EVERY task and must pass, so a check for a
# not-yet-written identifier is PEND, never FAIL.
#
# AC3 is EXECUTED, not grepped. "It is an arc, not a straight line" is a claim about behaviour,
# and the last spec farmed out in this repo shipped a real defect precisely because a
# behavioural criterion was compiled into a shape-grep (specs/harness-multi-repo, pi-cluster#86).
# arcPoint is required to be pure so it can be lifted out and run.
#
# Run from repo root:  ./specs/pulse-threads/verify.sh
set -uo pipefail
F="${F:-harness-console/index.html}"
fail=0
ok(){   echo "  PASS  $1"; }
no(){   echo "  FAIL  $1" >&2; fail=1; }
pend(){ echo "  pend  $1 (not built yet)"; }
has(){  grep -q -- "$1" "$F" 2>/dev/null; }

echo "VERIFY specs/pulse-threads  ($F)"
[ -f "$F" ] || { echo "  FAIL  $F missing" >&2; exit 1; }

# --- the page must stay loadable at all (Norms) ---
JS=/tmp/_threads_js
python3 - "$F" > "$JS" 2>/dev/null <<'PY'
import re,sys
print("\n".join(re.findall(r'<script[^>]*>(.*?)</script>', open(sys.argv[1]).read(), re.S)))
PY
if command -v node >/dev/null 2>&1 && [ -s "$JS" ]; then
  node --check "$JS" 2>/dev/null && ok "inline script parses" || no "inline script has a syntax error"
else
  pend "node or script extraction unavailable"
fi

# --- T1: constants, with AC5's range asserted rather than assumed ---
for c in TRAVEL_MS STRAND_FADE_MS STRAND_MAX ARC_BULGE ARC_JITTER; do
  has "$c" && ok "$c defined" || pend "$c"
done
if has STRAND_FADE_MS; then
  v="$(grep -oE 'STRAND_FADE_MS *= *[0-9]+' "$F" | grep -oE '[0-9]+$' | head -1)"
  if [ -n "$v" ] && [ "$v" -ge 30000 ] && [ "$v" -le 60000 ]; then
    ok "STRAND_FADE_MS=$v is within 30000..60000 (AC5)"
  else
    no "STRAND_FADE_MS='$v' outside the 30s..60s window the design calls for (AC5)"
  fi
fi

# --- AC3: EXECUTE arcPoint. This is the check that matters. ---
if has "arcPoint"; then
  ok "arcPoint present"
  if command -v node >/dev/null 2>&1; then
    # Lift the function out by brace-matching from its declaration. If it cannot be isolated we
    # PEND rather than FAIL: a brittle gate that cries wolf gets ignored, which is worse than a
    # blind spot you have written down.
    node -e '
      const fs=require("fs");
      const src=fs.readFileSync(process.argv[1],"utf8");
      const i=src.indexOf("function arcPoint");
      if(i<0){ console.log("PEND"); process.exit(0); }
      let d=0,s=src.indexOf("{",i),j=s;
      for(;j<src.length;j++){ if(src[j]==="{")d++; else if(src[j]==="}"){d--; if(!d){j++;break;} } }
      let fn; try{ fn=eval("("+src.slice(i,j)+")"); }catch(e){ console.log("PEND"); process.exit(0); }
      const A=[100,100], B=[400,300];
      const p0=fn(A[0],A[1],B[0],B[1],0,0.28);
      const p1=fn(A[0],A[1],B[0],B[1],1,0.28);
      const pm=fn(A[0],A[1],B[0],B[1],0.5,0.28);
      if(!p0||!p1||!pm||typeof p0.x!=="number"){ console.log("SHAPE"); process.exit(0); }
      const near=(p,q)=>Math.hypot(p.x-q[0],p.y-q[1])<0.001;
      if(!near(p0,A)){ console.log("START"); process.exit(0); }
      if(!near(p1,B)){ console.log("END"); process.exit(0); }
      // distance from the midpoint of the arc to the straight chord
      const dx=B[0]-A[0], dy=B[1]-A[1], L=Math.hypot(dx,dy);
      const dev=Math.abs((pm.x-A[0])*dy-(pm.y-A[1])*dx)/L;
      console.log(dev/L >= 0.06 ? "ARC" : "FLAT:"+(dev/L).toFixed(4));
    ' "$JS" > /tmp/_arcres 2>/dev/null
    case "$(cat /tmp/_arcres 2>/dev/null)" in
      ARC)   ok "AC3: arcPoint starts at A, ends at B, and bows off the chord" ;;
      START) no "AC3: arcPoint(t=0) is not the sender's position" ;;
      END)   no "AC3: arcPoint(t=1) is not the receiver's position" ;;
      FLAT*) no "AC3: arcPoint traces a straight line — $(cat /tmp/_arcres) deviation, needs >= 0.06" ;;
      SHAPE) no "AC3: arcPoint did not return an {x,y} point" ;;
      *)     pend "AC3 behavioural check (arcPoint not isolatable — is it pure?)" ;;
    esac
  else pend "AC3 behavioural check (node absent)"; fi
else pend "arcPoint"; fi

# --- T2: strands, and Safeguard 3 (a broadcast forms no rope) ---
if has "strands"; then
  ok "strands array present"
  grep -qE 'strands\.push' "$F" && ok "strands are recorded (AC1)" || no "nothing pushes a strand (AC1)"
  grep -qE 'born' "$F" && ok "strand records its birth (AC4)" || no "strand has no birth time (AC4)"
  grep -qE 'seed' "$F" && ok "strand carries a seed (AC6)" || no "no per-strand seed — threads would overlap exactly (AC6)"
  # AC8: the no-target path must not create a strand. In emit(), the broadcast branch returns
  # before any strand push — assert the push sits after the targets check.
  awk '/function emit/,/^  }/' "$F" | grep -qE 'targets\.length' \
    && ok "emit still distinguishes broadcast from directed (AC8)" \
    || no "emit no longer branches on targets — a broadcast may be forming rope (AC8, Safeguard 3)"
else pend "strands"; fi

# --- T3: bounded and decaying (AC7, Safeguards 1 & 2) ---
if has "stepStrands"; then
  ok "stepStrands present"
  grep -qE 'STRAND_MAX' "$F" && ok "cap referenced (AC7, Safeguard 1)" || no "strands never capped (Safeguard 1)"
  grep -qE 'strands\.(shift|splice)' "$F" && ok "old strands are removed (Safeguard 2)" \
    || no "strands are never removed — the board could never look quiet (Safeguard 2)"
else pend "stepStrands"; fi

# --- T4: drawn from LIVE positions so the rope stays tied to drifting atoms (§4) ---
if has "drawStrands"; then
  ok "drawStrands present"
  awk '/function drawStrands/,/^  }/' "$F" | grep -qE '\.from\.x|s\.from\.x' \
    && ok "arcs read live atom positions (§4)" \
    || no "drawStrands does not read from.x — a stored-coordinate rope detaches as atoms drift (§4)"
else pend "drawStrands"; fi

# --- T5 / AC9: reduced motion keeps the thread, drops the orbit ---
if has "drawStrands" || has "arcPoint"; then
  grep -qE 'reduce' "$F" && ok "reduced-motion flag still honoured (AC9)" || no "reduce flag lost (AC9)"
fi

# --- the arrival reaction must survive the refactor (§6) ---
if has "strands"; then
  grep -qE 'to\.gust' "$F" && ok "receiver still gusts on arrival (§6)" \
    || no "arrival gust lost — cause and effect stop reading (§6)"
fi

rm -f "$JS" /tmp/_arcres
echo
[ "$fail" = 0 ] && echo "VERIFY: PASS" || echo "VERIFY: FAIL"
exit "$fail"
