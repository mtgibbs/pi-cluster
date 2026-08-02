#!/usr/bin/env python3
"""alerter — the Phase-3 push bridge (deploy-side, NOT part of the nh app).

Runs as a sidecar in the new-horizons pod (shares the store PVC). On a loop it calls
`nh alert --json` (which finds newly-qualifying leads and records them so they're not re-pinged),
and pushes any new leads to ntfy and/or Matrix. Best-effort: a push failure is logged, never fatal —
and critically, a failed push does NOT un-record the lead (nh alert already committed the state), so
this is an at-most-once notifier. Stdlib only (urllib).

Config (env):
  NH_ALERT_INTERVAL   seconds between cycles (default 900); ignored with --once
  NH_ALERT_MIN_SCORE  threshold passed to `nh alert` (default 8)
  NH_ALERT_STATE      state file for nh alert (default /data/nh-alerted.json)
  NTFY_URL            e.g. https://ntfy.lab.mtgibbs.dev  (unset -> skip ntfy)
  NTFY_TOPIC          e.g. new-horizons
  NTFY_TOKEN          optional bearer token for a protected topic
  MATRIX_URL          homeserver base, e.g. https://matrix.lab.mtgibbs.dev  (unset -> skip Matrix)
  MATRIX_ROOM_ID      e.g. !abc:lab.mtgibbs.dev
  MATRIX_TOKEN        bot access token
"""
import json, os, subprocess, sys, time, urllib.request, urllib.error

def _post(url, data, headers, method="POST"):
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status

def run_alert():
    """Call nh alert --json; return the parsed object (or None on error)."""
    cmd = ["nh", "alert", "--json",
           "--min-score", os.environ.get("NH_ALERT_MIN_SCORE", "8"),
           "--state", os.environ.get("NH_ALERT_STATE", "/data/nh-alerted.json")]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except Exception as e:
        print(f"alerter: nh alert failed to run: {e}", file=sys.stderr); return None
    if out.returncode != 0:
        print(f"alerter: nh alert exit {out.returncode}: {out.stderr.strip()}", file=sys.stderr); return None
    try:
        return json.loads(out.stdout or "{}")
    except ValueError:
        print(f"alerter: nh alert emitted non-JSON: {out.stdout[:120]!r}", file=sys.stderr); return None

def format_message(new, threshold):
    lines = [f"🎯 {len(new)} new lead(s) scoring ≥ {threshold} — dossiers ready:"]
    for l in new:
        lines.append(f"• {l['score']}  {l['company']} — {l['role']}\n  {l['url']}")
    return "\n".join(lines)

def push_ntfy(msg):
    url, topic = os.environ.get("NTFY_URL"), os.environ.get("NTFY_TOPIC")
    if not url or not topic:
        return
    headers = {"Title": "new-horizons", "Tags": "briefcase"}
    tok = os.environ.get("NTFY_TOKEN")
    if tok: headers["Authorization"] = "Bearer " + tok
    try:
        _post(f"{url.rstrip('/')}/{topic}", msg.encode("utf-8"), headers)
        print("alerter: pushed to ntfy")
    except (urllib.error.URLError, OSError) as e:
        print(f"alerter: ntfy push failed: {e}", file=sys.stderr)

def push_matrix(msg):
    url, room, tok = os.environ.get("MATRIX_URL"), os.environ.get("MATRIX_ROOM_ID"), os.environ.get("MATRIX_TOKEN")
    if not url or not room or not tok:
        return
    txn = str(int(time.time() * 1000))
    import urllib.parse
    endpoint = f"{url.rstrip('/')}/_matrix/client/v3/rooms/{urllib.parse.quote(room)}/send/m.room.message/{txn}"
    body = json.dumps({"msgtype": "m.text", "body": msg}).encode("utf-8")
    headers = {"Authorization": "Bearer " + tok, "Content-Type": "application/json"}
    try:
        _post(endpoint, body, headers, method="PUT")
        print("alerter: pushed to Matrix")
    except (urllib.error.URLError, OSError) as e:
        print(f"alerter: Matrix push failed: {e}", file=sys.stderr)

def cycle():
    res = run_alert()
    if not res or not res.get("new"):
        return
    msg = format_message(res["new"], res.get("threshold"))
    push_ntfy(msg)
    push_matrix(msg)

def main():
    once = "--once" in sys.argv
    interval = int(os.environ.get("NH_ALERT_INTERVAL", "900"))
    while True:
        cycle()
        if once:
            return
        time.sleep(interval)

if __name__ == "__main__":
    main()
