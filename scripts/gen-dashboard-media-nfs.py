#!/usr/bin/env python3
"""Generate clusters/pi-k3s/monitoring/dashboard-media-nfs.yaml (Jellyfin / media-NFS health).

Usage: gen_dash.py <out.yaml>   — or  gen_dash.py --exprs  (print every expr, for validation)
"""
import json, sys

N = 'instance="192.168.1.55:9100"'  # pi-k3s node-exporter (Jellyfin is pinned here)
JF = 'namespace="jellyfin",container="jellyfin"'
DS = "Prometheus"

panels, _id, y = [], [0], [0]


def nid():
    _id[0] += 1
    return _id[0]


def row(title):
    panels.append({"type": "row", "id": nid(), "title": title, "collapsed": False,
                   "gridPos": {"h": 1, "w": 24, "x": 0, "y": y[0]}, "panels": []})
    y[0] += 1


def tgt(expr, legend, ref="A"):
    return {"datasource": DS, "expr": expr, "legendFormat": legend, "refId": ref, "interval": "30s"}


def thresholds(steps):
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for c, v in steps]}


def stat(title, expr, x, unit="short", steps=(("green", None),), desc="", decimals=0, w=4):
    panels.append({
        "type": "stat", "id": nid(), "title": title, "description": desc, "datasource": DS,
        "gridPos": {"h": 4, "w": w, "x": x, "y": y[0]},
        "targets": [tgt(expr, "")],
        "fieldConfig": {"defaults": {"unit": unit, "decimals": decimals, "color": {"mode": "thresholds"},
                                     "thresholds": thresholds(steps)}, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "colorMode": "background", "graphMode": "area", "textMode": "value", "justifyMode": "center"},
    })


def ts(title, targets, x, w, h=8, unit="short", desc="", steps=None, overrides=None, stack=False, minv=None,
       novalue=None):
    d = {"unit": unit, "custom": {"lineWidth": 1, "fillOpacity": 15, "showPoints": "never",
                                  "spanNulls": True, "stacking": {"mode": "normal" if stack else "none"}}}
    if minv is not None:
        d["min"] = minv
    if novalue:
        d["noValue"] = novalue
    if steps:
        d["thresholds"] = thresholds(steps)
        d["custom"]["thresholdsStyle"] = {"mode": "line+area"}
        d["color"] = {"mode": "palette-classic"}
    panels.append({
        "type": "timeseries", "id": nid(), "title": title, "description": desc, "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": y[0]},
        "targets": [tgt(e, l, chr(65 + i)) for i, (e, l) in enumerate(targets)],
        "fieldConfig": {"defaults": d, "overrides": overrides or []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
    })


def right_axis(name, unit):
    return {"matcher": {"id": "byName", "options": name},
            "properties": [{"id": "custom.axisPlacement", "value": "right"}, {"id": "unit", "value": unit}]}


# ── Row 1: verdict ────────────────────────────────────────────────────────────
row("Is Jellyfin locked up right now?")
stat("Jellyfin threads", f'sum(container_threads{{{JF}}})', 0,
     steps=(("green", None), ("yellow", 40), ("red", 50)),
     desc="Baseline ~22. Climbs when media reads block and the .NET thread pool injects replacements. "
          ">50 for 5m = JellyfinThreadPileup (the 2026-11-07 lockup hit 76). Nightly scheduled tasks peak ~44.")
stat("Probe failures (15m)",
     f'sum(increase(prober_probe_total{{{JF},result!="successful"}}[15m])) or vector(0)', 4,
     steps=(("green", None), ("yellow", 1), ("red", 6)),
     desc="Readiness/liveness /health probes that failed or timed out (1s timeout). "
          "Readiness failing = the pod is pulled from the Service = UI unreachable.")
stat("NFS READ ops/s (pi-k3s)",
     f'sum(rate(node_nfs_requests_total{{{N},method=~"Read|READ"}}[2m]))', 8, unit="ops", decimals=1,
     desc="0 while a stream is supposedly playing = stalled. 0 when nothing plays = idle (Infuse buffers big chunks, then coasts).")
stat("NFS retransmits (1h)",
     f'increase(node_nfs_rpc_retransmissions_total{{{N}}}[1h])', 12,
     steps=(("green", None), ("yellow", 1), ("red", 10)),
     desc="RPCs the client had to resend — under NFSv3 soft mounts, a server stall shows up here "
          "(and as 'not responding, timed out' in dmesg) instead of a silent hang.")
stat("pi-k3s load1", f'node_load1{{{N}}}', 16, decimals=1,
     steps=(("green", None), ("yellow", 8), ("red", 20)),
     desc="High load with idle CPU = threads stuck in uninterruptible I/O (D-state). Hit 51 on 2026-11-07.")
stat("Media alerts firing",
     'count(ALERTS{alertstate="firing",alertname=~"JellyfinThreadPileup|MediaNFSReadHang|NodeIOWaitSustained"}) or vector(0)',
     20, steps=(("green", None), ("red", 1)))
y[0] += 4

# ── Row 2: the lockup signature ───────────────────────────────────────────────
row("Lockup signature — stream reads stop, threads pile up, load climbs on an idle CPU")
ts("Jellyfin thread count", [(f'sum(container_threads{{{JF}}})', "threads")], 0, 12,
   steps=(("transparent", None), ("red", 50)), minv=0,
   desc="The best single lockup signal. Red band = JellyfinThreadPileup territory.")
ts("Media read throughput (pi-k3s ← QNAP)",
   [(f'sum(rate(node_nfs_requests_total{{{N},method=~"Read|READ"}}[1m]))', "NFS READ ops/s"),
    (f'rate(node_network_receive_bytes_total{{{N},device="eth0"}}[1m])', "eth0 rx")],
   12, 12, unit="ops", minv=0, overrides=[right_axis("eth0 rx", "Bps")],
   desc="Infuse reads in big bursts (~55 MB/s for minutes) then coasts on its buffer. "
        "A stall = reads drop to 0 mid-burst and stay there while playback is active.")
y[0] += 8
ts("pi-k3s load vs runnable vs blocked",
   [(f'node_load1{{{N}}}', "load1"), (f'node_procs_running{{{N}}}', "procs running"),
    (f'node_procs_blocked{{{N}}}', "procs blocked (D-state)")], 0, 12, minv=0,
   desc="load1 counts D-state *threads*; procs_blocked counts *processes*. One process with many stuck threads "
        "(Jellyfin) shows as load ≫ running with blocked = 1 — which is why MediaNFSReadHang (blocked ≥ 4) missed 11-07.")
ts("pi-k3s CPU busy vs iowait",
   [(f'(1 - avg(rate(node_cpu_seconds_total{{{N},mode="idle"}}[2m]))) * 100', "busy %"),
    (f'avg(rate(node_cpu_seconds_total{{{N},mode="iowait"}}[2m])) * 100', "iowait %")],
   12, 12, unit="percent", minv=0,
   desc="Context only — iowait over-reads on an idle node (2026-06-20 finding). A lockup shows CPU near idle.")
y[0] += 8

# ── Row 3: NFS client ─────────────────────────────────────────────────────────
row("NFS client (pi-k3s → QNAP 192.168.1.61)")
ts("RPC retransmits / auth refreshes",
   [(f'rate(node_nfs_rpc_retransmissions_total{{{N}}}[5m])', "retransmits/s"),
    (f'rate(node_nfs_rpc_authentication_refreshes_total{{{N}}}[5m])', "auth refreshes/s")], 0, 8, minv=0,
   desc="Non-zero retransmits = the server didn't answer within timeo (15s). Expected to be the visible symptom "
        "of a QNAP stall now that the media mount is NFSv3 soft.")
ts("NFS ops by type",
   [(f'sum by (method) (rate(node_nfs_requests_total{{{N}}}[5m])) > 0', "{{method}}")], 8, 8, unit="ops",
   stack=True, minv=0, novalue="no NFS traffic")
ts("Media reads by NFS version",
   [(f'sum by (proto) (rate(node_nfs_requests_total{{{N},method=~"Read|READ"}}[5m]))', "NFSv{{proto}}")],
   16, 8, unit="ops", minv=0,
   desc="Media mount pinned to NFSv3 on 2026-11-09 (was v4.1; the 11-07 lockup was a v4.1 session/lease stall).")
y[0] += 8

# ── Row 4: Jellyfin pod ───────────────────────────────────────────────────────
row("Jellyfin pod")
ts("Health probes by result",
   [(f'sum by (probe_type, result) (rate(prober_probe_total{{{JF}}}[5m])) * 60', "{{probe_type}} {{result}}")],
   0, 8, unit="short", minv=0, desc="Probes per minute. Any non-'successful' series = /health hung past 1s.")
ts("Jellyfin → clients (egress)",
   [('sum(rate(container_network_transmit_bytes_total{namespace="jellyfin"}[2m]))', "tx to clients")],
   8, 8, unit="Bps", minv=0,
   desc="What Jellyfin is actually serving. Pair with 'Media read throughput': reads stop + egress stops while "
        "a session is open = server-side stall; egress stops but reads were fine = client-side (Infuse).")
ts("Memory working set vs limit",
   [(f'sum(container_memory_working_set_bytes{{{JF}}})', "working set"),
    (f'max(kube_pod_container_resource_limits{{{JF},resource="memory"}})', "limit")], 16, 8, unit="bytes", minv=0)
y[0] += 8
ts("CPU usage + throttling",
   [(f'sum(rate(container_cpu_usage_seconds_total{{{JF}}}[2m]))', "cores used"),
    (f'sum(rate(container_cpu_cfs_throttled_periods_total{{{JF}}}[2m]))', "throttled periods/s")], 0, 12, minv=0)
ts("Container restarts",
   [(f'sum(kube_pod_container_status_restarts_total{{{JF}}})', "restarts (current pod)")], 12, 12, minv=0,
   desc="Resets when the pod is replaced. A rise = liveness killed it (3 failures × 30s) or the node rebooted.")
y[0] += 8

# ── Row 5: SD card ────────────────────────────────────────────────────────────
row("pi-k3s SD card — separate chronic issue (Jellyfin config/DB lives here)")
ts("SD card busy (mmcblk0)",
   [(f'rate(node_disk_io_time_seconds_total{{{N},device="mmcblk0"}}[2m]) * 100', "busy %")], 0, 12,
   unit="percent", minv=0,
   desc="Brief SD stalls stall local writes (k3s, pihole, Jellyfin's SQLite) for seconds. Proven NOT to kill streams; "
        "NVMe is the fix. If a lockup lines up with a spike here and NOT with NFS, it's the SD card.")
ts("SD card avg latency per op",
   [(f'rate(node_disk_write_time_seconds_total{{{N},device="mmcblk0"}}[2m]) / '
     f'rate(node_disk_writes_completed_total{{{N},device="mmcblk0"}}[2m])', "write"),
    (f'rate(node_disk_read_time_seconds_total{{{N},device="mmcblk0"}}[2m]) / '
     f'rate(node_disk_reads_completed_total{{{N},device="mmcblk0"}}[2m])', "read")], 12, 12, unit="s", minv=0)
y[0] += 8

dash = {
    "annotations": {"list": [
        {"builtIn": 1, "datasource": "-- Grafana --", "enable": True, "hide": True,
         "iconColor": "rgba(0, 211, 255, 1)", "name": "Annotations & Alerts", "type": "dashboard"},
        {"datasource": DS, "enable": True, "iconColor": "red", "name": "Media alerts firing",
         "expr": 'ALERTS{alertstate="firing",alertname=~"JellyfinThreadPileup|MediaNFSReadHang"}',
         "step": "60s", "titleFormat": "{{alertname}}", "textFormat": "{{instance}}", "useValueForTime": False},
    ]},
    "description": "Jellyfin lockup + media-NFS health. Built from the 2026-11-07 incident "
                   "(docs/incidents/2026-11-07-jellyfin-nfsv4-session-stall.md). Generated — edit "
                   "scripts/gen-dashboard-media-nfs.py, not this JSON.",
    "editable": True, "graphTooltip": 1, "id": None, "links": [], "panels": panels,
    "refresh": "30s", "schemaVersion": 39, "tags": ["jellyfin", "nfs", "media"],
    "time": {"from": "now-6h", "to": "now"}, "timepicker": {}, "timezone": "browser",
    "title": "Jellyfin / Media NFS Health", "uid": "media-nfs-health", "version": 2,
}

if sys.argv[1:] == ["--exprs"]:
    for p in panels:
        for t in p.get("targets", []):
            print(json.dumps({"title": p["title"], "expr": t["expr"]}))
    sys.exit(0)

body = json.dumps(dash, indent=2)
out = (
    "# GENERATED by scripts/gen-dashboard-media-nfs.py — edit the script, then re-run:\n"
    "#   python3 scripts/gen-dashboard-media-nfs.py clusters/pi-k3s/monitoring/dashboard-media-nfs.yaml\n"
    "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: grafana-dashboard-media-nfs\n"
    "  namespace: monitoring\n  labels:\n    grafana_dashboard: \"1\"\ndata:\n  media-nfs.json: |\n"
    + "\n".join("    " + l for l in body.splitlines()) + "\n"
)
open(sys.argv[1], "w").write(out)
print(f"wrote {sys.argv[1]}: {len(panels)} panels")
