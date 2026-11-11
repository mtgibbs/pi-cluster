"""Append-only JSONL run ledger — the source of truth for idempotency, daily counts and GET /runs.

Each line is one transition: {"ts", "op", "run_id", ...fields}. A run's record is the fold of its
lines. Ops: launch -> launch_failed | finished. Only identifiers are written — event id/type/subject,
never event.data, never a secret, never agent output bodies.
"""
import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

STATUS_BY_OP = {"launch": "launched", "launch_failed": "launch_failed", "finished": "finished"}


def utc_iso(dt=None):
    return (dt or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.runs = {}
        self.by_key = {}  # (agent, event_id) -> run_id, live (non-failed) launches only
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
        if op == "launch":
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
        """Launches (not failed launches) for `agent` whose `started` falls on UTC date `day`
        (YYYY-MM-DD)."""
        with self.lock:
            return sum(1 for r in self.runs.values()
                       if r.get("agent") == agent and r.get("status") != "launch_failed"
                       and str(r.get("started", "")).startswith(day))

    def unfinished(self):
        with self.lock:
            return [dict(r) for r in self.runs.values() if r.get("status") == "launched"]
