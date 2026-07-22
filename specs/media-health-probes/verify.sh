#!/usr/bin/env bash
# verify.sh — deterministic acceptance gate for specs/media-health-probes.
# §10 acceptance criteria + §8 safeguards compiled to runnable assertions: exit 0 = acceptable.
#
# PRESENCE-GATED (the ralph contract): a file that has not been edited yet PENDs, never FAILs.
# STRICT=1 turns every pend into a failure — ralph runs the gate once more that way after the
# last task, because presence-gating verifies "correct if present" and can never verify "done".
#
# This parses the manifests as YAML and asserts structure. It does NOT reach the cluster: the
# live checks (pods READY, restart counts unchanged) are spec §11 and are a human's job.
#
# Run from repo root:  ./specs/media-health-probes/verify.sh
set -uo pipefail
fail=0
ok(){   echo "  PASS  $1"; }
no(){   echo "  FAIL  $1" >&2; fail=1; }
pend(){ if [ "${STRICT:-0}" = 1 ]; then no "$1 — still unbuilt at the final check (STRICT)"; else
          echo "  pend  $1 (not built yet)"; fi }

echo "VERIFY specs/media-health-probes"
command -v python3 >/dev/null 2>&1 || { echo "  FAIL  python3 required" >&2; exit 1; }

# The whole contract in one place, mirroring spec §6. Kept here rather than derived from the
# manifests on purpose: the gate must know the INTENDED port, so a probe pointing at a port the
# executor also changed cannot agree with itself.
python3 - "${STRICT:-0}" <<'PY'
import sys, glob, os
try:
    import yaml
except ImportError:
    print("  pend  PyYAML unavailable — cannot parse manifests"); sys.exit(0)

STRICT = sys.argv[1] == "1"
HTTP = {  # file -> (port, path)
 "clusters/pi-k3s/media/sonarr.yaml":   (8989, "/ping"),
 "clusters/pi-k3s/media/radarr.yaml":   (7878, "/ping"),
 "clusters/pi-k3s/media/lidarr.yaml":   (8686, "/ping"),
 "clusters/pi-k3s/media/readarr.yaml":  (8787, "/ping"),
 "clusters/pi-k3s/media/prowlarr.yaml": (9696, "/ping"),
 "clusters/pi-k3s/media/sabnzbd.yaml":  (8080, "/api?mode=version"),
}
TCP = {
 "clusters/pi-k3s/media/bazarr.yaml": 6767,
 "clusters/pi-k3s/media/calibre-web.yaml": 8083,
 "clusters/pi-k3s/media/qbittorrent.yaml": 8080,
 "clusters/pi-k3s/media/lazylibrarian.yaml": 5299,
 "clusters/pi-k3s/media/jellyseerr.yaml": 5055,
 "clusters/pi-k3s/media/flaresolverr.yaml": 8191,
 "clusters/pi-k3s/pihole/pihole-exporter.yaml": 9617,
 "clusters/pi-k3s/pihole/pihole-secondary-exporter.yaml": 9617,
}
EXCLUDED = ["clusters/pi-k3s/uptime-kuma/autokuma-deployment.yaml",
            "clusters/pi-k3s/private-exit-node/deployment.yaml"]
ALLOWED_PATHS = {p for _, p in HTTP.values()}

fails = []
def ok(m):   print(f"  PASS  {m}")
def no(m):   print(f"  FAIL  {m}"); fails.append(m)
def pend(m):
    if STRICT: no(f"{m} — still unbuilt at the final check (STRICT)")
    else:      print(f"  pend  {m} (not built yet)")

def containers(path):
    """Every container of every Deployment in a (possibly multi-doc) manifest."""
    out = []
    try:
        docs = list(yaml.safe_load_all(open(path)))
    except Exception as e:
        no(f"{os.path.basename(path)}: YAML does not parse ({e})"); return out
    for d in docs or []:
        if isinstance(d, dict) and d.get("kind") == "Deployment":
            for c in (d.get("spec", {}).get("template", {})
                       .get("spec", {}).get("containers") or []):
                out.append(c)
    return out

def declared_ports(c):
    return {p.get("containerPort") for p in (c.get("ports") or []) if isinstance(p, dict)}

def check_timings(name, lp):
    # Safeguard 1: liveness must be slow. An aggressive probe turns a slow boot into a
    # crashloop, which is worse than having no probe at all.
    d, f = lp.get("initialDelaySeconds", 0), lp.get("failureThreshold", 0)
    if d >= 60 and f >= 3: ok(f"{name}: liveness is conservative (delay={d}s, failures={f}) (AC5)")
    else: no(f"{name}: liveness too aggressive (delay={d}s, failures={f}); need >=60 and >=3 (AC5, Safeguard 1)")

for path, (port, want_path) in HTTP.items():
    base = os.path.basename(path)
    if not os.path.exists(path): no(f"{base}: missing"); continue
    cs = containers(path)
    probed = [c for c in cs if c.get("readinessProbe") or c.get("livenessProbe")]
    if not probed: pend(base); continue
    for c in probed:
        rp, lp = c.get("readinessProbe"), c.get("livenessProbe")
        if not rp or not lp: no(f"{base}: needs BOTH readinessProbe and livenessProbe (AC1)"); continue
        for label, pr in (("readiness", rp), ("liveness", lp)):
            h = pr.get("httpGet")
            if not h: no(f"{base}: {label} must use httpGet (AC2)"); continue
            if h.get("path") != want_path: no(f"{base}: {label} path {h.get('path')!r}, expected {want_path!r} (AC2, AC8)")
            if h.get("port") != port:      no(f"{base}: {label} port {h.get('port')!r}, expected {port} (AC2, AC4)")
            if h.get("port") not in declared_ports(c):
                no(f"{base}: {label} port {h.get('port')!r} is not a declared containerPort (AC4)")
        if rp.get("httpGet", {}).get("path") == want_path and lp.get("httpGet", {}).get("path") == want_path:
            ok(f"{base}: httpGet {want_path} on {port}, both probes (AC1, AC2)")
        check_timings(base, lp)

for path, port in TCP.items():
    base = os.path.basename(path)
    if not os.path.exists(path): no(f"{base}: missing"); continue
    cs = containers(path)
    probed = [c for c in cs if c.get("readinessProbe") or c.get("livenessProbe")]
    if not probed: pend(base); continue
    for c in probed:
        rp, lp = c.get("readinessProbe"), c.get("livenessProbe")
        if not rp or not lp: no(f"{base}: needs BOTH readinessProbe and livenessProbe (AC1)"); continue
        bad = False
        for label, pr in (("readiness", rp), ("liveness", lp)):
            if pr.get("httpGet") is not None:
                no(f"{base}: {label} uses httpGet, but no health endpoint was verified for it — "
                   f"§6 requires tcpSocket (AC3, Safeguard 2)"); bad = True; continue
            t = pr.get("tcpSocket")
            if not t: no(f"{base}: {label} must use tcpSocket (AC3)"); bad = True; continue
            if t.get("port") != port: no(f"{base}: {label} port {t.get('port')!r}, expected {port} (AC3, AC4)"); bad = True
            elif t.get("port") not in declared_ports(c):
                no(f"{base}: {label} port {t.get('port')!r} is not a declared containerPort (AC4)"); bad = True
        if not bad: ok(f"{base}: tcpSocket {port}, both probes (AC1, AC3)")
        check_timings(base, lp)

# Safeguard 3 / AC6: the two non-HTTP workloads must stay bare.
for path in EXCLUDED:
    base = os.path.basename(path)
    if not os.path.exists(path): continue
    if any(c.get("readinessProbe") or c.get("livenessProbe") for c in containers(path)):
        no(f"{base}: gained a probe but declares no containerPort — out of scope (AC6, Safeguard 3)")
    else:
        ok(f"{base}: correctly left alone (AC6)")

# AC8: no invented HTTP paths anywhere in scope.
for path in list(HTTP) + list(TCP):
    if not os.path.exists(path): continue
    for c in containers(path):
        for pr in (c.get("readinessProbe"), c.get("livenessProbe")):
            if isinstance(pr, dict) and pr.get("httpGet"):
                p = pr["httpGet"].get("path")
                if p not in ALLOWED_PATHS:
                    no(f"{os.path.basename(path)}: path {p!r} is not one of the verified endpoints (AC8, Safeguard 2)")

print()
sys.exit(1 if fails else 0)
PY
rc=$?
[ "$rc" = 0 ] || fail=1

# AC7 / Safeguard 4: nothing outside the probe blocks may differ from main. A structural diff is
# the only honest way to check this — a grep cannot tell an added probe from a changed image tag.
if git rev-parse --verify -q main >/dev/null 2>&1; then
  changed="$(git diff --name-only main -- clusters/pi-k3s 2>/dev/null || true)"
  stray="$(printf '%s\n' "$changed" | grep -vE '^clusters/pi-k3s/(media/|pihole/pihole(-secondary)?-exporter\.yaml)' | grep -v '^$' || true)"
  [ -z "$stray" ] && ok "no manifests outside the in-scope set were touched (AC7)" \
    || no "files changed outside the in-scope set (AC7, Safeguard 4): $(echo $stray)"
  offending="$(git diff -U0 main -- clusters/pi-k3s 2>/dev/null \
    | grep -E '^[+-]' | grep -vE '^(\+\+\+|---)' \
    | grep -vE 'Probe:|httpGet:|tcpSocket:|path:|port:|initialDelaySeconds:|periodSeconds:|timeoutSeconds:|failureThreshold:|successThreshold:' || true)"
  [ -z "$offending" ] && ok "only probe fields were added or removed (AC7, Safeguard 4)" \
    || { no "non-probe lines changed (AC7, Safeguard 4):"; printf '%s\n' "$offending" | head -5 | sed 's/^/        /' >&2; }
else
  echo "  pend  main not available for the structural diff (AC7)"
fi

echo
[ "$fail" = 0 ] && echo "VERIFY: PASS" || echo "VERIFY: FAIL"
exit "$fail"
