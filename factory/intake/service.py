#!/usr/bin/env python3
"""service.py — the factory intake: research agents (via n8n) hand the factory a problem.

  service.py serve                       # the in-cluster service (env below)
  service.py dry-run <request.json>      # validate + render + resolve the submission; contacts nothing
  service.py reset-pause <origin>        # Matt lifts an automatic pause on an origin (kubectl exec)

Design: docs/design/factory-intake.md. n8n decides WHEN (route a plan here, ledger, push); this
service decides HOW: target allowlist (factory/targets/), idea rendering (render.py, code only),
admission (max_open, runs_per_day, dedupe, cooldown) and submission through factory/submit.py — the
same code the laptop runs — always with gate_mode=auto and auto_approve=false. It is the only
in-cluster holder of the Fabro token. Fabro's own scheduler is the run queue (FIFO, one at a time);
requests over the cap are PARKED here and released on events, never on a timer:
  * a new request arrives;
  * a tracked Fabro run reaches a terminal state, heard on Fabro's server-sent event stream
    (GET /api/v1/attach — a watch). On every (re)connect the submitted runs are reconciled once,
    so an event missed while disconnected is not lost.
When a run ends the result goes to n8n (FACTORY_RESULT_URL): verdict, PR, held-spec objections.

HTTP (bearer FACTORY_INTAKE_TOKEN on everything but /healthz):
  POST /requests        202 {state: submitted|parked} · 200 {state: duplicate} · 409 cooldown ·
                        422 invalid · 404 unknown target · 403 origin not allowed · 423 origin paused
  GET  /requests/<key>  the request's row
  GET  /healthz         200

Env: FABRO_URL, FABRO_DEV_TOKEN, FACTORY_INTAKE_TOKEN, FACTORY_INTAKE_DB (sqlite path),
FACTORY_RESULT_URL (optional n8n webhook; sent with the same bearer), FACTORY_INTAKE_PORT (8080).
"""
import hmac, json, os, pathlib, re, sqlite3, sys, threading, time, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
import render                      # noqa: E402
import submit as factory_submit    # noqa: E402

TERMINAL = ("succeeded", "failed", "dead", "cancelled", "canceled")
PAUSE_WINDOW, PAUSE_HELD = 10, 6   # >= 6 of an origin's last 10 finished requests ended "spec held" -> pause
MAX_BODY = 64 * 1024


def now():
    return datetime.now(timezone.utc)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def spec_name(req):
    """Kebab, <= 49 chars, unique per request: the title's first words + the key's first 6 hex."""
    words = re.sub(r"[^a-z0-9]+", "-", req["title"].lower()).strip("-").split("-")[:5]
    base = "-".join(w for w in words if w)[:40].strip("-") or "request"
    return f"{base}-{req['dedupe_key'][:6]}"


# ---------------------------------------------------------------- store
class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL, target TEXT NOT NULL, origin TEXT NOT NULL,
            state TEXT NOT NULL,              -- parked | submitted | done
            request TEXT NOT NULL, idea TEXT NOT NULL, spec TEXT NOT NULL,
            run_id TEXT, run_status TEXT, verdict TEXT, pr_url TEXT, result TEXT, last_error TEXT,
            created TEXT NOT NULL, submitted TEXT, finished TEXT);
          CREATE INDEX IF NOT EXISTS requests_key ON requests(key);
          CREATE TABLE IF NOT EXISTS pause_resets (origin TEXT PRIMARY KEY, at TEXT NOT NULL);""")

    def q(self, sql, *a):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, a).fetchall()]

    def x(self, sql, *a):
        with self.lock:
            return self.db.execute(sql, a).lastrowid


# ---------------------------------------------------------------- the intake
class Intake:
    """All decisions. Network effects are injected so tests can run it with fakes:
    fabro_submit(prep) -> {"run_id", "url"}; fabro_run(run_id) -> (status, fx);
    open_factory_prs(repo) -> int; notify(payload) -> None."""

    def __init__(self, store, fabro_submit, fabro_run, open_factory_prs, notify, clock=now):
        self.s, self.fabro_submit, self.fabro_run = store, fabro_submit, fabro_run
        self.open_factory_prs, self.notify, self.clock = open_factory_prs, notify, clock
        self.lock = threading.RLock()

    # ---- admission
    def paused(self, origin):
        if origin == "human":
            return False
        reset = (self.s.q("SELECT at FROM pause_resets WHERE origin=?", origin) or [{"at": ""}])[0]["at"]
        rows = self.s.q("SELECT verdict FROM requests WHERE origin=? AND state='done' AND finished>? "
                        "ORDER BY finished DESC LIMIT ?", origin, reset, PAUSE_WINDOW)
        return len(rows) == PAUSE_WINDOW and sum(r["verdict"] == "spec held" for r in rows) >= PAUSE_HELD

    def receive(self, body):
        """One request from n8n. Returns (http status, response dict)."""
        try:
            req = render.validate(body)
            idea = render.render(req)
        except render.RequestError as e:
            return 422, {"error": "invalid", "detail": str(e)}
        try:
            tgt = factory_submit.load_target(req["target"])
        except factory_submit.SubmitError as e:
            return 404, {"error": "unknown_target", "detail": str(e)}
        origins = tgt.get("origins", ["human"])
        if req["origin"] not in origins and not (req["origin"].startswith("agent:") and "agent:*" in origins):
            return 403, {"error": "origin_not_allowed", "detail": f"{req['origin']} may not hand {tgt['name']} work"}
        with self.lock:
            live = self.s.q("SELECT state, run_id FROM requests WHERE key=? AND target=? AND state IN ('parked','submitted')",
                            req["dedupe_key"], tgt["name"])
            if live:
                return 200, {"state": "duplicate", "of": live[0]}
            last = self.s.q("SELECT * FROM requests WHERE key=? AND target=? AND state='done' ORDER BY id DESC LIMIT 1",
                            req["dedupe_key"], tgt["name"])
            if last:                        # whatever it ended as, the same problem waits out the cooldown
                fin = datetime.strptime(last[0]["finished"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                until = fin + timedelta(days=int(tgt.get("cooldown_days", 14)))
                if until > self.clock():
                    return 409, {"error": "cooldown", "until": iso(until), "last_verdict": last[0]["verdict"],
                                 "pr": last[0]["pr_url"]}
            if self.paused(req["origin"]):
                return 423, {"error": "paused", "detail": f"{req['origin']}: {PAUSE_HELD}+ of its last {PAUSE_WINDOW} "
                             "requests ended with the spec held; Matt lifts it with `service.py reset-pause`"}
            self.s.x("INSERT INTO requests (key, target, origin, state, request, idea, spec, created) "
                     "VALUES (?,?,?,?,?,?,?,?)", req["dedupe_key"], tgt["name"], req["origin"], "parked",
                     json.dumps(req), idea, spec_name(req), iso(self.clock()))
            self.pump()
            row = self.s.q("SELECT state, run_id, last_error FROM requests WHERE key=? AND target=? ORDER BY id DESC LIMIT 1",
                           req["dedupe_key"], tgt["name"])[0]
        return 202, row

    def pump(self):
        """Submit parked requests, oldest first, while each target is under its caps."""
        with self.lock:
            for row in self.s.q("SELECT * FROM requests WHERE state='parked' ORDER BY id"):
                try:
                    tgt = factory_submit.load_target(row["target"])
                except factory_submit.SubmitError as e:
                    self.s.x("UPDATE requests SET last_error=? WHERE id=?", str(e), row["id"])
                    continue
                running = self.s.q("SELECT count(*) n FROM requests WHERE target=? AND state='submitted'", row["target"])[0]["n"]
                day = iso(self.clock())[:10]
                today = self.s.q("SELECT count(*) n FROM requests WHERE target=? AND submitted LIKE ?",
                                 row["target"], day + "%")[0]["n"]
                if today >= int(tgt.get("runs_per_day", 3)):
                    self.s.x("UPDATE requests SET last_error=? WHERE id=?", f"runs_per_day {tgt.get('runs_per_day', 3)} spent", row["id"])
                    continue
                try:
                    open_prs = self.open_factory_prs(tgt["repo"])
                except Exception as e:      # cannot count -> do not admit (fail closed)
                    self.s.x("UPDATE requests SET last_error=? WHERE id=?", f"open PR count failed: {e}", row["id"])
                    continue
                if running + open_prs >= int(tgt.get("max_open", 2)):
                    self.s.x("UPDATE requests SET last_error=? WHERE id=?",
                             f"max_open {tgt.get('max_open', 2)}: {running} running + {open_prs} open PRs", row["id"])
                    continue
                req = json.loads(row["request"])
                try:
                    prep = factory_submit.prepare(row["idea"], target=row["target"], profile=tgt.get("intake_profile", "all-local"),
                                                  gate_mode="auto", origin=row["origin"], request=row["key"][:64],
                                                  spec=row["spec"])
                    r = self.fabro_submit(prep)
                except Exception as e:
                    self.s.x("UPDATE requests SET last_error=? WHERE id=?", f"submit failed: {e}", row["id"])
                    continue
                self.s.x("UPDATE requests SET state='submitted', run_id=?, submitted=?, last_error=NULL WHERE id=?",
                         r["run_id"], iso(self.clock()), row["id"])
                self.notify({"event": "submitted", "key": row["key"], "target": row["target"], "origin": row["origin"],
                             "source": req["source"], "title": req["title"], "run_id": r["run_id"], "run_url": r.get("url")})

    # ---- run end
    def tracked(self):
        return [r["run_id"] for r in self.s.q("SELECT run_id FROM requests WHERE state='submitted'")]

    def on_run_event(self, run_id):
        """A Fabro event mentioned this run: if it has ended, record it, tell n8n, admit the next."""
        rows = self.s.q("SELECT * FROM requests WHERE run_id=? AND state='submitted'", run_id)
        if not rows:
            return False
        status, fx = self.fabro_run(run_id)
        if status not in TERMINAL:
            return False
        row, v = rows[0], (fx.get("verdict") or {})
        verdict = v.get("verdict") or ("failed" if status != "succeeded" else "no verdict")
        pr = (fx.get("pr") or {}).get("url")
        result = {"event": "finished", "key": row["key"], "target": row["target"], "origin": row["origin"],
                  "source": json.loads(row["request"])["source"], "title": json.loads(row["request"])["title"],
                  "run_id": run_id, "run_status": status, "verdict": verdict, "reasons": v.get("reasons") or [],
                  "objections": v.get("objections", ""), "pr": pr, "class": fx.get("class")}
        with self.lock:
            self.s.x("UPDATE requests SET state='done', run_status=?, verdict=?, pr_url=?, result=?, finished=? WHERE id=?",
                     status, verdict, pr, json.dumps(result), iso(self.clock()), row["id"])
        try:
            self.notify(result)
        except Exception as e:
            self.s.x("UPDATE requests SET last_error=? WHERE id=?", f"result callback failed: {e}", row["id"])
        self.pump()
        return True

    def reconcile(self):
        for rid in self.tracked():
            self.on_run_event(rid)
        self.pump()


# ---------------------------------------------------------------- real clients
def _http(method, url, headers=None, body=None, timeout=60):
    req = urllib.request.Request(url, method=method, headers=dict(headers or {}, **{"Content-Type": "application/json"}),
                                 data=None if body is None else json.dumps(body).encode())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        t = r.read().decode()
        return json.loads(t) if t.strip() else {}


def real_clients():
    url, tok = os.environ["FABRO_URL"].rstrip("/"), os.environ["FABRO_DEV_TOKEN"]
    auth = {"Authorization": "Bearer " + tok}
    import report                                              # reads FABRO_URL / FABRO_DEV_TOKEN

    def fabro_submit(prep):
        return factory_submit.submit(prep, url=url, tok=tok)

    def fabro_run(run_id):
        run = _http("GET", f"{url}/api/v1/runs/{run_id}", auth)
        status = ((run.get("lifecycle") or {}).get("status") or {}).get("kind") or (run.get("status") or {}).get("kind")
        fx = {}
        if status in TERMINAL:
            fx = report.last_fx(run_id, _http("GET", f"{url}/api/v1/runs/{run_id}/stages", auth)["data"])
        return status, fx

    def open_factory_prs(repo):                                # public repo: unauthenticated read
        prs = _http("GET", f"https://api.github.com/repos/{repo}/pulls?state=open&per_page=100",
                    {"Accept": "application/vnd.github+json", "User-Agent": "factory-intake"})
        return sum(any(l["name"] == "factory" for l in p.get("labels", [])) for p in prs)

    def notify(payload):
        dest = os.environ.get("FACTORY_RESULT_URL")
        print(json.dumps({"notify": payload.get("event"), "key": payload.get("key"), "run": payload.get("run_id"),
                          "verdict": payload.get("verdict")}), flush=True)
        if dest:
            _http("POST", dest, {"Authorization": "Bearer " + os.environ["FACTORY_INTAKE_TOKEN"]}, payload)

    def watch(intake):
        """Hold Fabro's event stream open; any frame naming a tracked run re-checks that run."""
        backoff = 5
        while True:
            try:
                intake.reconcile()                             # on (re)connect: catch what was missed
                req = urllib.request.Request(f"{url}/api/v1/attach", headers=dict(auth, Accept="text/event-stream"))
                with urllib.request.urlopen(req, timeout=3600) as r:
                    backoff = 5
                    for raw in r:
                        line = raw.decode(errors="replace")
                        if not line.startswith("data:"):
                            continue
                        for rid in intake.tracked():
                            if rid in line:
                                intake.on_run_event(rid)
            except Exception as e:
                print(json.dumps({"watch": "disconnected", "error": str(e)[:200], "retry_s": backoff}), flush=True)
            time.sleep(backoff)
            backoff = min(backoff * 2, 300)

    return fabro_submit, fabro_run, open_factory_prs, notify, watch


# ---------------------------------------------------------------- HTTP
def make_handler(intake, token):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, obj):
            b = json.dumps(obj).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

        def _authed(self):
            got = self.headers.get("Authorization", "")
            return bool(token) and hmac.compare_digest(got.encode(), ("Bearer " + token).encode())

        def do_GET(self):
            if self.path == "/healthz":
                return self._send(200, {"ok": True})
            if not self._authed():
                return self._send(403, {"error": "forbidden"})
            m = re.fullmatch(r"/requests/([a-f0-9]{64})", self.path)
            if not m:
                return self._send(404, {"error": "not_found"})
            rows = intake.s.q("SELECT key, target, origin, state, spec, run_id, run_status, verdict, pr_url, last_error, "
                              "created, submitted, finished FROM requests WHERE key=? ORDER BY id DESC", m.group(1))
            return self._send(200 if rows else 404, {"requests": rows})

        def do_POST(self):
            if not self._authed():
                return self._send(403, {"error": "forbidden"})
            if self.path != "/requests":
                return self._send(404, {"error": "not_found"})
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAX_BODY:
                return self._send(413, {"error": "body size"})
            try:
                body = json.loads(self.rfile.read(n))
            except json.JSONDecodeError:
                return self._send(422, {"error": "invalid", "detail": "not JSON"})
            code, obj = intake.receive(body)
            return self._send(code, obj)

        def log_message(self, fmt, *a):
            print(json.dumps({"http": fmt % a}), flush=True)
    return H


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "dry-run" and len(argv) == 3:
        try:
            req = render.validate(json.load(open(argv[2])))
            tgt = factory_submit.load_target(req["target"])
            prep = factory_submit.prepare(render.render(req), target=req["target"], profile=tgt.get("intake_profile", "all-local"),
                                          gate_mode="auto", origin=req["origin"], request=req["dedupe_key"], spec=spec_name(req))
        except (render.RequestError, factory_submit.SubmitError, json.JSONDecodeError) as e:
            print(f"refused: {e}", file=sys.stderr)
            return 1
        print(factory_submit.describe(prep))
        print("dry run: nothing uploaded, no run created")
        return 0
    if cmd == "reset-pause" and len(argv) == 3:
        Store(os.environ["FACTORY_INTAKE_DB"]).x("INSERT OR REPLACE INTO pause_resets VALUES (?,?)", argv[2], iso(now()))
        print(f"pause lifted for {argv[2]}")
        return 0
    if cmd == "serve":
        token = os.environ.get("FACTORY_INTAKE_TOKEN", "")
        if len(token) < 32:
            print("FACTORY_INTAKE_TOKEN missing or short — refusing to serve", file=sys.stderr)
            return 1
        fabro_submit, fabro_run, open_prs, notify, watch = real_clients()
        intake = Intake(Store(os.environ.get("FACTORY_INTAKE_DB", "/data/intake.db")), fabro_submit, fabro_run, open_prs, notify)
        threading.Thread(target=watch, args=(intake,), daemon=True).start()
        port = int(os.environ.get("FACTORY_INTAKE_PORT", "8080"))
        print(json.dumps({"listening": port}), flush=True)
        ThreadingHTTPServer(("0.0.0.0", port), make_handler(intake, token)).serve_forever()
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
