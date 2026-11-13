#!/usr/bin/env python3
"""agent-runner — launches one ephemeral, least-privilege Kubernetes Job per (event, agent).

n8n decides *when* (POST /runs); the runner decides *how*: validate the agent manifest + event,
enforce the kill switch / daily cap / idempotency, gate concurrency (at most RUNNER_MAX_CONCURRENT
Jobs; the rest wait in a bounded FIFO queue), render the Job (CONTRACT.md §4), watch it, read the
agent's Result from the pod log (§5), and POST it to the caller's callback.

The runner never reads Secrets (it only names the agent's Secret in envFrom) and treats the
agent's Result purely as data.

Env (CONTRACT.md §3):
  RUNNER_API_TOKEN (required)  RUNNER_NAMESPACE=agents  RUNNER_MANIFEST_DIR=/etc/agents
  RUNNER_LEDGER_PATH=/data/ledger.jsonl  RUNNER_CALLBACK_PREFIXES  RUNNER_LOCAL_MODELS
  RUNNER_PAUSED  RUNNER_LITELLM_BASE_URL  RUNNER_NODE_HOSTNAMES
  RUNNER_MAX_CONCURRENT=2  RUNNER_MAX_QUEUE=8  RUNNER_MAX_QUEUE_WAIT=45m
  RUNNER_CHECKOUT_BASE_URL=http://source-controller.flux-system.svc.cluster.local.
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
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agentspec  # noqa: E402
import jobspec  # noqa: E402
import results  # noqa: E402
from kubeapi import KubeClient, KubeError  # noqa: E402
from ledger import Ledger, Spool, utc_iso  # noqa: E402

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
    max_concurrent: int = 2          # agent Jobs alive at once; resourcequota.yaml pods = this + 1
    max_queue: int = 8               # runs waiting for a slot; beyond this POST /runs is 429 queue_full
    max_queue_wait_s: int = 45 * 60  # a run still queued after this ends as exit_reason queue_expired
    checkout_base_url: str = jobspec.DEFAULT_CHECKOUT_BASE_URL  # Flux source-controller (manifest `checkout:`)

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
            max_concurrent=max(1, int(env.get("RUNNER_MAX_CONCURRENT", "2"))),
            max_queue=max(0, int(env.get("RUNNER_MAX_QUEUE", "8"))),
            max_queue_wait_s=agentspec.parse_duration(
                (env.get("RUNNER_MAX_QUEUE_WAIT") or "45m").strip()),
            checkout_base_url=(env.get("RUNNER_CHECKOUT_BASE_URL") or "").strip()
            or jobspec.DEFAULT_CHECKOUT_BASE_URL,
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
        # admit_lock serialises every admission decision AND every queue/slot change: the
        # dedupe/cap/slot checks and the Job create happen under it, so two concurrent POSTs (or a
        # POST racing a watcher that just freed a slot) can never both take the last slot.
        self.admit_lock = threading.Lock()
        self.queue = deque()  # run_ids waiting for a slot, FIFO; guarded by admit_lock
        self.spool = Spool(Path(cfg.ledger_path).parent / "queue")
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
            if not rec:
                return 404, {"error": "unknown run"}
            if rec.get("status") == "queued":
                with self.admit_lock:
                    rec["position"] = (self.queue.index(rid) + 1) if rid in self.queue else None
            return 200, rec
        return 404, {"error": "not found"}

    # ---------------------------------------------------------------- admission
    def resolve_checkout(self, manifest, event):
        """The commit sha of the artifact source-controller serves right now for the manifest's
        checkout.source — read from that GitRepository's .status.artifact (RBAC: `get` on that one
        object, agents/rbac.yaml). Returns (sha | None, problem | None, transient):
        - a manifest without `checkout:` → (None, None, False);
        - sha read → (sha, None, False);
        - not read, but the event names its own revision → (None, None, False): the Job fetches that
          artifact with no fallback (degraded, logged);
        - not read and the event names none (manual / scheduled run) → (None, problem, transient):
          nothing could be fetched, so the run is refused instead of launching a checkout that 404s.
          `transient` is True for a transport failure (no HTTP answer), False when the API answered.
        Only the 40-hex sha is ever used; the object itself is not logged or stored."""
        if not manifest.get("checkout"):
            return None, None, False
        src = manifest["checkout"]["source"]
        ns, name = src.split("/", 1)
        transient = False
        try:
            sha = jobspec.artifact_sha(self.kube.get_gitrepository(ns, name))
            why = None if sha else "GitRepository has no stored artifact"
        except KubeError as e:
            sha, why = None, f"kubernetes API error {e.status}"
        except Exception as e:  # noqa: BLE001 — transport failure talking to the API
            sha, why, transient = None, f"kubernetes API unreachable ({type(e).__name__})", True
        has_rev = jobspec.event_revision(event) is not None
        if sha:
            jlog("checkout_resolved", source=src, revision=sha)
            return sha, None, False
        jlog("checkout_unresolved", source=src, reason=why, event_revision=has_rev)
        if has_rev:
            return None, None, False
        return None, (f"no repository revision to check out: could not read the current Flux artifact "
                      f"of {src} ({why}) and the event names no revision"), transient

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
            # FIFO: a free slot is only taken directly when nobody is already waiting for one.
            if self.queue or self.ledger.count_launched() >= self.cfg.max_concurrent:
                if len(self.queue) >= self.cfg.max_queue:
                    jlog("rejected", agent=agent, event_id=event["id"], reason="queue_full",
                         queued=len(self.queue))
                    return 429, {"error": "queue_full",
                                 "detail": f"{len(self.queue)} runs already waiting for a slot"}
                # Spool first: a crash before the ledger line leaves an orphan file (pruned on
                # start), never a queued ledger record with no event.
                self.spool.save(run_id, {"event": event})
                self.ledger.append(
                    "queue", run_id, agent=agent, event_id=event["id"], event_type=event["type"],
                    event_subject=event["subject"], callback=callback, accepted=utc_iso(now))
                self.queue.append(run_id)
                position = len(self.queue)
                jlog("queued", run_id=run_id, agent=agent, event_id=event["id"],
                     event_type=event["type"], subject=event["subject"], position=position)
                return 202, {"run_id": run_id, "status": "queued", "position": position}

            checkout_sha, problem, _ = self.resolve_checkout(manifest, event)
            if problem:
                jlog("rejected", agent=agent, event_id=event["id"], reason="checkout_unresolved")
                return 502, {"error": problem}
            job = jobspec.render_job(run_id, manifest, event, timeout_s, self.cfg.namespace,
                                     self.cfg.litellm_base_url, self.cfg.node_hostnames,
                                     checkout_base_url=self.cfg.checkout_base_url,
                                     checkout_sha=checkout_sha)
            # Ledger first: a crash between this line and the create is re-adopted on restart
            # (Job 404 -> job_failed), never silently lost or launched twice.
            self.ledger.append(
                "launch", run_id, agent=agent, event_id=event["id"], event_type=event["type"],
                event_subject=event["subject"], callback=callback, accepted=utc_iso(now),
                started=utc_iso(now), timeout_s=timeout_s, job=jobspec.job_name(run_id),
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

    # ---------------------------------------------------------------- queue
    def pump(self):
        """Start queued runs, head first, while a slot is free. Safe from any thread."""
        started, failed = [], []
        with self.admit_lock:
            while (self.queue and not self.cfg.paused
                   and self.ledger.count_launched() < self.cfg.max_concurrent):
                rid = self.queue[0]
                outcome, why = self._start_queued(rid)
                if outcome == "retry":
                    break  # head stays at the head; the next tick tries again
                self.queue.popleft()
                if outcome == "launched":
                    started.append(rid)
                elif outcome == "failed":
                    failed.append((rid, why))
        for rid in started:
            self.watch(rid)
        # Delivery retries sleep, so they run outside the lock.
        for rid, why in failed:
            run = self.ledger.get(rid)
            if run:
                self.finish_unstarted(run, "job_failed", why)
        return started

    def _start_queued(self, rid):
        """Create the Job for queued run `rid`. Caller holds admit_lock.
        ("launched"|"failed"|"retry"|"gone", reason)."""
        run = self.ledger.get(rid)
        if not run or run.get("status") != "queued":
            return "gone", None
        agent = run.get("agent")
        doc = self.spool.load(rid)
        event = (doc or {}).get("event")
        if not isinstance(event, dict):
            jlog("start_failed", run_id=rid, agent=agent, reason="spool_missing")
            return "failed", "the queued event was lost before the run could start"
        # The manifest is re-read now, not at accept: what runs is what is deployed when it starts
        # (a removed or broken manifest stops queued runs too).
        try:
            manifest, timeout_s = agentspec.load_manifest(
                self.cfg.manifest_dir, agent, self.cfg.local_models)
        except (agentspec.AgentNotFound, agentspec.ManifestError) as e:
            jlog("start_failed", run_id=rid, agent=agent, reason="manifest")
            return "failed", f"agent manifest no longer loads: {str(e)[:300] or 'not found'}"
        # Resolved at Job creation, not at accept: a queued run reads whatever Flux serves when it starts.
        checkout_sha, problem, transient = self.resolve_checkout(manifest, event)
        if problem:
            if transient:
                jlog("start_deferred", run_id=rid, agent=agent, reason="checkout_unresolved")
                return "retry", None
            jlog("start_failed", run_id=rid, agent=agent, reason="checkout_unresolved")
            return "failed", problem
        now = self.now()
        job = jobspec.render_job(rid, manifest, event, timeout_s, self.cfg.namespace,
                                 self.cfg.litellm_base_url, self.cfg.node_hostnames,
                                 checkout_base_url=self.cfg.checkout_base_url,
                                 checkout_sha=checkout_sha)
        # `started` is set HERE, at Job creation: the run's deadline counts from now, not accept.
        self.ledger.append("launch", rid, started=utc_iso(now), timeout_s=timeout_s,
                           job=jobspec.job_name(rid), allowed_outputs=list(manifest["outputs"]))
        try:
            self.kube.create_job(job)
        except KubeError as e:
            if not e.quota_exceeded:
                jlog("start_failed", run_id=rid, agent=agent, status=e.status)
                return "failed", f"could not create the Job: kubernetes API error {e.status}"
            self.ledger.append("requeue", rid, started=None, error=f"kubernetes {e.status}")
            jlog("start_deferred", run_id=rid, agent=agent, reason="quota")
            return "retry", None
        except Exception as e:  # noqa: BLE001 — transport blip: keep it queued, retry next tick
            self.ledger.append("requeue", rid, started=None, error=type(e).__name__)
            jlog("start_deferred", run_id=rid, agent=agent, error=type(e).__name__)
            return "retry", None
        self.spool.delete(rid)
        jlog("launched", run_id=rid, agent=agent, event_id=run.get("event_id"),
             event_type=run.get("event_type"), subject=run.get("event_subject"),
             timeout_s=timeout_s, queued_since=run.get("accepted"))
        return "launched", None

    def expire_queued(self):
        """Finish every run queued longer than max_queue_wait_s with exit_reason queue_expired."""
        now = self.now()
        limit = timedelta(seconds=self.cfg.max_queue_wait_s)
        expired = []
        with self.admit_lock:
            for rid in list(self.queue):
                run = self.ledger.get(rid)
                accepted = _parse_ts((run or {}).get("accepted"))
                if run is None or (accepted and now - accepted > limit):
                    self.queue.remove(rid)
                    if run:
                        expired.append(run)
        for run in expired:
            mins = self.cfg.max_queue_wait_s // 60
            self.finish_unstarted(
                run, "queue_expired",
                f"not started: still waiting for a free agent slot after {mins} minutes "
                f"(at most {self.cfg.max_concurrent} agents run at once)")
        return [r["run_id"] for r in expired]

    def tick(self):
        """One dispatcher step: expire stale queued runs, then fill free slots."""
        self.expire_queued()
        self.pump()

    def restore_queue(self):
        """On start: rebuild the in-memory FIFO from the ledger's queued runs (accept order)."""
        runs = self.ledger.queued()
        with self.admit_lock:
            self.queue = deque(r["run_id"] for r in runs)
            pruned = self.spool.prune(set(self.queue))
        for rid in pruned:
            jlog("spool_pruned", run_id=rid)
        return [r["run_id"] for r in runs]

    def start_dispatcher(self, stop=None):
        """Background tick every poll_seconds (queue expiry; retries after a deferred start).
        Slots freed by a finishing run are refilled at once by finalize(), not by this loop."""
        stop = stop or threading.Event()

        def loop():
            while not stop.is_set():
                try:
                    self.tick()
                except Exception as e:  # noqa: BLE001 — never let the dispatcher die
                    jlog("dispatch_error", error=type(e).__name__)
                self.sleep(self.cfg.poll_seconds)
        threading.Thread(target=loop, daemon=True, name="dispatcher").start()
        return stop

    def finish_unstarted(self, run, exit_reason, why):
        """End a run that never got a Job: send the normal callback (failed Result), then record."""
        run_id = run["run_id"]
        finished = utc_iso(self.now())
        result = results.failed_result(f"{exit_reason}: {why}")
        payload = {"run_id": run_id, "agent": run.get("agent"), "event_id": run.get("event_id"),
                   "started": None, "finished": finished,
                   "exit_reason": exit_reason, "result": result}
        delivered, attempts = self.deliver(run.get("callback"), payload, run_id)
        self.ledger.append("finished", run_id, finished=finished, exit_reason=exit_reason,
                           outcome=result["outcome"], output_kinds=[],
                           callback_delivered=delivered, callback_attempts=attempts)
        self.spool.delete(run_id)
        jlog("finished", run_id=run_id, agent=run.get("agent"), exit_reason=exit_reason,
             outcome=result["outcome"], callback_delivered=delivered, attempts=attempts)
        return payload

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
        """On start: resume watching every run the ledger shows as launched but not finished, and
        rebuild the queue (its events are in the spool). Returns the re-adopted launched runs."""
        runs = self.ledger.unfinished()
        for r in runs:
            jlog("readopt", run_id=r["run_id"], agent=r.get("agent"))
            self.watch(r["run_id"])
        self.restore_queue()
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
        self.pump()  # a slot just freed
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
         paused=cfg.paused, readopted=len(adopted), queued=len(runner.queue),
         max_concurrent=cfg.max_concurrent, max_queue=cfg.max_queue,
         max_queue_wait_s=cfg.max_queue_wait_s)
    runner.start_dispatcher()
    make_server(runner, port=cfg.port).serve_forever()


if __name__ == "__main__":
    main()
