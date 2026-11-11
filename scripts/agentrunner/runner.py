#!/usr/bin/env python3
"""agent-runner — launches one ephemeral, least-privilege Kubernetes Job per (event, agent).

n8n decides *when* (POST /runs); the runner decides *how*: validate the agent manifest + event,
enforce the kill switch / daily cap / idempotency, render the Job (CONTRACT.md §4), watch it, read
the agent's Result from the pod log (§5), and POST it to the caller's callback.

The runner never reads Secrets (it only names the agent's Secret in envFrom) and treats the
agent's Result purely as data.

Env (CONTRACT.md §3):
  RUNNER_API_TOKEN (required)  RUNNER_NAMESPACE=agents  RUNNER_MANIFEST_DIR=/etc/agents
  RUNNER_LEDGER_PATH=/data/ledger.jsonl  RUNNER_CALLBACK_PREFIXES  RUNNER_LOCAL_MODELS
  RUNNER_PAUSED  RUNNER_LITELLM_BASE_URL  RUNNER_NODE_HOSTNAMES
  PORT=8080  RUNNER_POLL_SECONDS=5  (tunables)
"""
import hmac
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agentspec  # noqa: E402
import jobspec  # noqa: E402
import results  # noqa: E402
from kubeapi import KubeClient, KubeError  # noqa: E402
from ledger import Ledger, utc_iso  # noqa: E402

_VFILE = Path(__file__).resolve().parent / "VERSION"
VERSION = _VFILE.read_text().strip() if _VFILE.exists() else "?"

MAX_REQUEST_BYTES = 128 * 1024
RUN_ID_RE = re.compile(r"^[a-z0-9]{1,40}$")
CALLBACK_RETRIES = 3                 # CONTRACT: "Retries 3x" -> 1 attempt + 3 retries
CALLBACK_BACKOFF = (2, 5, 10)
CALLBACK_TIMEOUT = 10
DEADLINE_GRACE_S = 300               # runner-side safety net beyond activeDeadlineSeconds
LOG_TAIL_LINES = 5
LOG_LIMIT_BYTES = results.MAX_MARKER_LINE + 64 * 1024


def jlog(event, **fields):
    """One JSON line per event on stdout. Callers pass identifiers only — never event.data,
    tokens, or agent output."""
    print(json.dumps({"ts": utc_iso(), "event": event, **fields}, separators=(",", ":"),
                     default=str), file=sys.stdout, flush=True)


def _csv(v):
    return [x.strip() for x in (v or "").split(",") if x.strip()]


@dataclass
class Config:
    token: str
    namespace: str = "agents"
    manifest_dir: str = "/etc/agents"
    ledger_path: str = "/data/ledger.jsonl"
    callback_prefixes: list = field(default_factory=list)
    local_models: list = field(default_factory=list)
    paused: bool = False
    litellm_base_url: str = ""
    node_hostnames: list = field(default_factory=list)
    port: int = 8080
    poll_seconds: float = 5.0

    @classmethod
    def from_env(cls, env):
        return cls(
            token=env.get("RUNNER_API_TOKEN", ""),
            namespace=env.get("RUNNER_NAMESPACE", "agents"),
            manifest_dir=env.get("RUNNER_MANIFEST_DIR", "/etc/agents"),
            ledger_path=env.get("RUNNER_LEDGER_PATH", "/data/ledger.jsonl"),
            # A prefix without a trailing "/" would also match a longer hostname
            # (http://n8n.n8n.svc -> http://n8n.n8n.svc.evil), so those are dropped.
            callback_prefixes=[p for p in _csv(env.get("RUNNER_CALLBACK_PREFIXES")) if p.endswith("/")],
            local_models=_csv(env.get("RUNNER_LOCAL_MODELS")),
            paused=env.get("RUNNER_PAUSED", "").strip().lower() in ("true", "1", "yes"),
            litellm_base_url=env.get("RUNNER_LITELLM_BASE_URL", ""),
            node_hostnames=_csv(env.get("RUNNER_NODE_HOSTNAMES")),
            port=int(env.get("PORT", "8080")),
            poll_seconds=float(env.get("RUNNER_POLL_SECONDS", "5")),
        )

    def callback_allowed(self, url):
        return (isinstance(url, str) and url.startswith(("http://", "https://"))
                and any(url.startswith(p) for p in self.callback_prefixes))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # A redirect could leave the callback-prefix allowlist; treat any 3xx as a failed delivery.
    def redirect_request(self, *a, **k):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def http_post_json(url, payload):
    """POST JSON; return the HTTP status (raises on transport errors)."""
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": f"agent-runner/{VERSION}"})
    try:
        with _OPENER.open(req, timeout=CALLBACK_TIMEOUT) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def _now():
    return datetime.now(timezone.utc)


def _parse_ts(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def job_state(job):
    """(exit_reason, finished_iso) for a finished Job, or (None, None) while it runs."""
    status = (job or {}).get("status") or {}
    for c in status.get("conditions") or []:
        if c.get("status") != "True":
            continue
        if c.get("type") == "Complete":
            return "completed", c.get("lastTransitionTime") or status.get("completionTime")
        if c.get("type") == "Failed":
            reason = "deadline" if c.get("reason") == "DeadlineExceeded" else "job_failed"
            return reason, c.get("lastTransitionTime")
    return None, None


class Runner:
    def __init__(self, cfg, kube, ledger, post=http_post_json, now=_now, sleep=time.sleep,
                 spawn_watchers=True):
        self.cfg = cfg
        self.kube = kube
        self.ledger = ledger
        self.post = post
        self.now = now
        self.sleep = sleep
        self.spawn_watchers = spawn_watchers
        self.admit_lock = threading.Lock()
        self._watching = set()
        self._watch_lock = threading.Lock()

    # ---------------------------------------------------------------- HTTP surface
    def authorized(self, header):
        given = header[7:] if isinstance(header, str) and header.startswith("Bearer ") else ""
        return hmac.compare_digest(given.encode(), self.cfg.token.encode())

    def handle(self, method, path, headers, body):
        """(status, json-able payload). Pure enough to test without sockets."""
        path = path.split("?", 1)[0]
        if method == "GET" and path == "/healthz":
            return 200, {"status": "ok", "version": VERSION}
        if not (path == "/runs" or path.startswith("/runs/")):
            return 404, {"error": "not found"}
        if not self.authorized(headers.get("Authorization")):
            return 401, {"error": "unauthorized"}
        if method == "POST" and path == "/runs":
            if body is None:
                return 422, {"error": "request body too large"}
            try:
                req = json.loads(body or b"")
            except (ValueError, UnicodeDecodeError):
                return 422, {"error": "body is not JSON"}
            return self.submit(req)
        if method == "GET" and path.startswith("/runs/"):
            rid = path[len("/runs/"):]
            rec = self.ledger.get(rid) if RUN_ID_RE.match(rid) else None
            return (200, rec) if rec else (404, {"error": "unknown run"})
        return 404, {"error": "not found"}

    # ---------------------------------------------------------------- admission
    def submit(self, req):
        if not isinstance(req, dict):
            return 422, {"error": "body must be an object"}
        agent, event, callback = req.get("agent"), req.get("event"), req.get("callback")
        if not isinstance(agent, str) or not agent:
            return 422, {"error": "agent is required"}
        try:
            agentspec.validate_event(event)
        except agentspec.EventError as e:
            jlog("rejected", agent=agent, reason="invalid_event")
            return 422, {"error": str(e)}
        if not self.cfg.callback_allowed(callback):
            jlog("rejected", agent=agent, event_id=event["id"], reason="callback_not_allowed")
            return 422, {"error": "callback is not under an allowed prefix"}

        with self.admit_lock:
            existing = self.ledger.find(agent, event["id"])
            if existing:
                jlog("replay", run_id=existing["run_id"], agent=agent, event_id=event["id"])
                return 200, existing
            if self.cfg.paused:
                jlog("rejected", agent=agent, event_id=event["id"], reason="paused")
                return 503, {"error": "runner is paused"}
            try:
                manifest, timeout_s = agentspec.load_manifest(
                    self.cfg.manifest_dir, agent, self.cfg.local_models)
            except agentspec.AgentNotFound:
                jlog("rejected", agent=agent, event_id=event["id"], reason="unknown_agent")
                return 404, {"error": "unknown agent"}
            except agentspec.ManifestError as e:
                jlog("rejected", agent=agent, event_id=event["id"], reason="invalid_manifest",
                     detail=str(e)[:500])
                return 422, {"error": f"invalid manifest: {e}"}

            now = self.now()
            cap = manifest["limits"]["runs_per_day"]
            if self.ledger.count_on_day(agent, now.strftime("%Y-%m-%d")) >= cap:
                jlog("rejected", agent=agent, event_id=event["id"], reason="daily_cap", cap=cap)
                return 429, {"error": f"daily cap of {cap} runs reached"}

            run_id = uuid.uuid4().hex[:16]
            job = jobspec.render_job(run_id, manifest, event, timeout_s, self.cfg.namespace,
                                     self.cfg.litellm_base_url, self.cfg.node_hostnames)
            # Ledger first: a crash between this line and the create is re-adopted on restart
            # (Job 404 -> job_failed), never silently lost or launched twice.
            self.ledger.append(
                "launch", run_id, agent=agent, event_id=event["id"], event_type=event["type"],
                event_subject=event["subject"], callback=callback, started=utc_iso(now),
                timeout_s=timeout_s, job=jobspec.job_name(run_id),
                allowed_outputs=list(manifest["outputs"]))
            try:
                self.kube.create_job(job)
            except KubeError as e:
                self.ledger.append("launch_failed", run_id, error=f"kubernetes {e.status}")
                if e.quota_exceeded:
                    jlog("rejected", run_id=run_id, agent=agent, reason="quota")
                    return 429, {"error": "cluster quota exceeded"}
                jlog("launch_failed", run_id=run_id, agent=agent, status=e.status)
                return 502, {"error": f"kubernetes API error {e.status}"}
            except Exception as e:  # noqa: BLE001 — transport failure talking to the API
                self.ledger.append("launch_failed", run_id, error=type(e).__name__)
                jlog("launch_failed", run_id=run_id, agent=agent, error=type(e).__name__)
                return 502, {"error": "kubernetes API unreachable"}

        jlog("launched", run_id=run_id, agent=agent, event_id=event["id"],
             event_type=event["type"], subject=event["subject"], timeout_s=timeout_s)
        self.watch(run_id)
        return 202, {"run_id": run_id, "status": "launched"}

    # ---------------------------------------------------------------- watching
    def watch(self, run_id):
        if not self.spawn_watchers:
            return
        with self._watch_lock:
            if run_id in self._watching:
                return
            self._watching.add(run_id)
        threading.Thread(target=self._watch_loop, args=(run_id,), daemon=True,
                         name=f"watch-{run_id}").start()

    def _watch_loop(self, run_id):
        try:
            while True:
                try:
                    if self.poll_once(run_id):
                        return
                except Exception as e:  # noqa: BLE001 — keep watching through API blips
                    jlog("watch_error", run_id=run_id, error=type(e).__name__)
                self.sleep(self.cfg.poll_seconds)
        finally:
            with self._watch_lock:
                self._watching.discard(run_id)

    def readopt(self):
        """On start: resume watching every run the ledger shows as launched but not finished."""
        runs = self.ledger.unfinished()
        for r in runs:
            jlog("readopt", run_id=r["run_id"], agent=r.get("agent"))
            self.watch(r["run_id"])
        return [r["run_id"] for r in runs]

    def poll_once(self, run_id):
        """One poll step. True when the run is finished (finalized now or earlier)."""
        run = self.ledger.get(run_id)
        if not run or run.get("status") != "launched":
            return True
        job = self.kube.get_job(run["job"])
        now = self.now()
        if job is None:
            jlog("job_missing", run_id=run_id, agent=run.get("agent"))
            self.finalize(run, "job_failed", utc_iso(now))
            return True
        reason, finished = job_state(job)
        if reason is None:
            started = _parse_ts(run.get("started"))
            limit = timedelta(seconds=int(run.get("timeout_s") or 0) + DEADLINE_GRACE_S)
            if started and now - started > limit:
                jlog("deadline_enforced", run_id=run_id, agent=run.get("agent"))
                self.kube.delete_job(run["job"])
                self.finalize(run, "deadline", utc_iso(now))
                return True
            return False
        self.finalize(run, reason, finished or utc_iso(now))
        return True

    def read_log(self, run_id):
        """The tail of the run's pod log, or None if no pod/log is available."""
        try:
            pods = self.kube.list_pods(f"run-id={run_id}")
        except Exception as e:  # noqa: BLE001
            jlog("log_unavailable", run_id=run_id, error=type(e).__name__)
            return None
        if not pods:
            return None
        pods.sort(key=lambda p: (p.get("metadata") or {}).get("creationTimestamp") or "")
        name = (pods[-1].get("metadata") or {}).get("name")
        try:
            return self.kube.pod_log(name, container=jobspec.CONTAINER,
                                     tail_lines=LOG_TAIL_LINES, limit_bytes=LOG_LIMIT_BYTES)
        except Exception as e:  # noqa: BLE001
            jlog("log_unavailable", run_id=run_id, error=type(e).__name__)
            return None

    def finalize(self, run, exit_reason, finished):
        run_id = run["run_id"]
        log_text = self.read_log(run_id)
        status, res, why = results.parse_result(log_text or "", run.get("allowed_outputs") or [])
        if status == results.OK:
            result = res
        else:
            if exit_reason == "completed":
                exit_reason = status  # no_result | invalid_result
            result = results.failed_result(f"{exit_reason}: {why}")
        payload = {"run_id": run_id, "agent": run.get("agent"), "event_id": run.get("event_id"),
                   "started": run.get("started"), "finished": finished,
                   "exit_reason": exit_reason, "result": result}
        delivered, attempts = self.deliver(run.get("callback"), payload, run_id)
        # Written AFTER delivery: a crash mid-callback leaves the run "launched", so it is
        # re-adopted and the callback re-sent (at-least-once).
        self.ledger.append("finished", run_id, finished=finished, exit_reason=exit_reason,
                           outcome=result["outcome"],
                           output_kinds=[o["kind"] for o in result.get("outputs", [])],
                           callback_delivered=delivered, callback_attempts=attempts)
        jlog("finished", run_id=run_id, agent=run.get("agent"), exit_reason=exit_reason,
             outcome=result["outcome"], callback_delivered=delivered, attempts=attempts)
        return payload

    def deliver(self, url, payload, run_id):
        # Re-check: the allowlist may have tightened since launch (restart with new config).
        if not self.cfg.callback_allowed(url):
            jlog("callback_refused", run_id=run_id, reason="prefix_no_longer_allowed")
            return False, 0
        attempts = 0
        for i in range(1 + CALLBACK_RETRIES):
            attempts += 1
            try:
                code = self.post(url, payload)
                if 200 <= code < 300:
                    return True, attempts
                jlog("callback_failed", run_id=run_id, attempt=attempts, status=code)
            except Exception as e:  # noqa: BLE001
                jlog("callback_failed", run_id=run_id, attempt=attempts, error=type(e).__name__)
            if i < CALLBACK_RETRIES:
                self.sleep(CALLBACK_BACKOFF[i])
        return False, attempts


class Handler(BaseHTTPRequestHandler):
    runner = None  # set by make_server

    def _reply(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n < 0 or n > MAX_REQUEST_BYTES:
            self.close_connection = True
            return None
        return self.rfile.read(n)

    def do_GET(self):
        self._reply(*self.runner.handle("GET", self.path, self.headers, b""))

    def do_POST(self):
        body = self._body() if self.path.split("?", 1)[0] == "/runs" else b""
        self._reply(*self.runner.handle("POST", self.path, self.headers, body))

    def log_message(self, *args):
        pass  # structured lines come from jlog


def make_server(runner, host="0.0.0.0", port=8080):
    handler = type("BoundHandler", (Handler,), {"runner": runner})
    return ThreadingHTTPServer((host, port), handler)


def main():
    cfg = Config.from_env(os.environ)
    if not cfg.token.strip():
        sys.exit("RUNNER_API_TOKEN is empty — refusing to start")
    if not cfg.callback_prefixes:
        jlog("warning", detail="RUNNER_CALLBACK_PREFIXES is empty; every POST /runs will be 422")
    runner = Runner(cfg, KubeClient(cfg.namespace), Ledger(cfg.ledger_path))
    adopted = runner.readopt()
    jlog("started", version=VERSION, port=cfg.port, namespace=cfg.namespace,
         paused=cfg.paused, readopted=len(adopted))
    make_server(runner, port=cfg.port).serve_forever()


if __name__ == "__main__":
    main()
