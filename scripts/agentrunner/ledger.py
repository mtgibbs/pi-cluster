"""Append-only JSONL run ledger — the source of truth for idempotency, daily counts and GET /runs.

Each line is one transition: {"ts", "op", "run_id", ...fields}. A run's record is the fold of its
lines. Ops: queue -> (requeue ->)* launch -> launch_failed | finished, where a run admitted with a free
slot starts at `launch`, and a queued run can also go straight to `finished` (queue_expired, or it
could not be started). Only identifiers are written — event id/type/subject, never event.data, never
a secret, never agent output bodies. A queued run's event lives in the Spool (below) until it starts.
"""
import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

STATUS_BY_OP = {"queue": "queued", "requeue": "queued", "launch": "launched",
                "launch_failed": "launch_failed", "finished": "finished"}
CLAIMS_KEY = ("queue", "launch")  # ops that claim the (agent, event_id) idempotency key


def utc_iso(dt=None):
    return (dt or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.runs = {}
        self.by_key = {}  # (agent, event_id) -> run_id, live (non-failed) runs only
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                    self._apply(rec)
                except (ValueError, KeyError, TypeError):
                    # A torn final line from a crash mid-write: skip it, keep going.
                    print(json.dumps({"ts": utc_iso(), "event": "ledger_bad_line", "line": n}),
                          file=sys.stdout, flush=True)

    def _apply(self, rec):
        op = rec["op"]
        rid = rec["run_id"]
        run = self.runs.setdefault(rid, {"run_id": rid})
        run.update({k: v for k, v in rec.items() if k not in ("op", "ts")})
        run["status"] = STATUS_BY_OP[op]
        run["updated"] = rec.get("ts")
        key = (run.get("agent"), run.get("event_id"))
        if op in CLAIMS_KEY:
            self.by_key[key] = rid
        elif op == "launch_failed" and self.by_key.get(key) == rid:
            del self.by_key[key]

    def append(self, op, run_id, **fields):
        if op not in STATUS_BY_OP:
            raise ValueError(op)
        rec = {"ts": utc_iso(), "op": op, "run_id": run_id, **fields}
        line = json.dumps(rec, separators=(",", ":"), sort_keys=True) + "\n"
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
            self._apply(rec)

    def get(self, run_id):
        with self.lock:
            r = self.runs.get(run_id)
            return dict(r) if r else None

    def find(self, agent, event_id):
        with self.lock:
            rid = self.by_key.get((agent, event_id))
            return dict(self.runs[rid]) if rid else None

    def count_on_day(self, agent, day):
        """Accepted runs (not failed launches) for `agent` admitted on UTC date `day` (YYYY-MM-DD).
        Counted at ACCEPT: a queued run counts from the moment it is queued. `accepted` is absent on
        records written before 0.2.0, whose `started` was the accept time."""
        with self.lock:
            return sum(1 for r in self.runs.values()
                       if r.get("agent") == agent and r.get("status") != "launch_failed"
                       and str(r.get("accepted") or r.get("started") or "").startswith(day))

    def unfinished(self):
        """Runs with a Job (launched, not yet finalized) — these hold a concurrency slot."""
        with self.lock:
            return [dict(r) for r in self.runs.values() if r.get("status") == "launched"]

    def count_launched(self):
        with self.lock:
            return sum(1 for r in self.runs.values() if r.get("status") == "launched")

    def queued(self):
        """Queued runs in accept order (dict order = first ledger line = the `queue` op)."""
        with self.lock:
            return [dict(r) for r in self.runs.values() if r.get("status") == "queued"]


class Spool:
    """One file per QUEUED run holding its event, next to the ledger on the PVC, so a queue survives a
    runner restart. The ledger stays identifiers-only; event.data lives here only between accept and
    Job creation (or the run's end), then the file is deleted. Writes are atomic (tmp + rename)."""

    def __init__(self, directory):
        self.dir = Path(directory)

    def _path(self, run_id):
        return self.dir / f"{run_id}.json"

    def save(self, run_id, doc):
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / f".{run_id}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._path(run_id))

    def load(self, run_id):
        try:
            return json.loads(self._path(run_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def delete(self, run_id):
        try:
            self._path(run_id).unlink()
        except FileNotFoundError:
            pass

    def prune(self, keep):
        """Delete spool files for runs that are no longer queued (crash between steps)."""
        if not self.dir.exists():
            return []
        gone = []
        for f in self.dir.iterdir():
            rid = f.name[1:].split(".", 1)[0] if f.name.startswith(".") else f.stem
            if rid not in keep:
                f.unlink(missing_ok=True)
                gone.append(rid)
        return gone
