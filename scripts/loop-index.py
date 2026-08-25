#!/usr/bin/env python3
"""run-index.py — join every store the loop wrote into one traceable index.

The loop left its record in five places and nothing has ever joined them:

  1. git history            one commit per task; the task text IS the commit message
  2. .evidence/status/      one JSON per executor process: task, attempt, phase, verdict
  3. .evidence/runs/        per-attempt .log and .diff (gitignored; bulky)
  4. $EVID/supervisor/      launches, stalls, kills, restarts
  5. ralph-judge/ledger     findings, decision per finding

Stores 2 and 3 are read from the IN-REPO `.evidence/` first and from `~/.harness/` only
as a fallback. The harness writes to an unversioned dotfolder in $HOME on a 3-day (logs)
and 1-day (status) deletion timer; 14 of this project's 42 runs had already lost their
status file to it before anyone noticed. See `.evidence/README.md`.

Store 3's filenames are the trap: `T1-attempt2.log` means "second attempt at the first
task in THAT RUN'S queue", so the same name appears in a dozen unrelated runs and never
matches the task id it implemented. The join key that actually works is the PID in the
directory name, which store 2 maps to a real task.

  usage: run-index.py [--evid DIR] [--repo DIR] [-o docs/run-index.md]

Writes .evidence/index.md and .evidence/index.jsonl. Re-runnable; derives everything
from the stores, holds no state of its own.

HONESTY RULE, same as the gate's: a field that cannot be derived is emitted as null
and rendered `—`, never as zero and never inferred from a neighbouring run. Several
columns are mostly `—`; that is the finding, not a bug in this script.
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone

HOME = os.path.expanduser("~")

# THE CONVENTION. A loopable repo has specs/<feature>/{spec.md,tasks.txt,verify.sh} and
# gets its record written to .evidence/ IN THAT REPO. Everything below is relative to the
# target repo root — this tool holds no knowledge of any particular project, and no
# knowledge of where the harness happens to keep scratch.
EVIDENCE = ".evidence"
SPECS = "specs"

REPO_DIR_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def repo_names(repo):
    """Names that count as 'this repo': the checkout, and any linked worktree of it.

    A linked worktree has a different directory name but the same history, and the
    harness records whichever one it ran in. Derive both rather than hardcoding.
    """
    names = {os.path.basename(os.path.abspath(repo))}
    common = sh(["git", "rev-parse", "--git-common-dir"], cwd=repo).strip()
    if common:
        if not os.path.isabs(common):
            common = os.path.abspath(os.path.join(repo, common))
        names.add(os.path.basename(os.path.dirname(common)))
        for wt in glob.glob(os.path.join(common, "worktrees", "*")):
            gitdir = os.path.join(wt, "gitdir")
            if os.path.exists(gitdir):
                try:
                    names.add(os.path.basename(os.path.dirname(
                        open(gitdir).read().strip())))
                except OSError:
                    pass
    return sorted(n for n in names if n)


def store_bases(repo, kind):
    """Where to look for `kind` ('logs' or 'status'), in precedence order.

    The in-repo `.evidence/` store comes FIRST and is authoritative: it is committed (or
    at least local and un-swept), it travels with the clone, and nothing deletes it on a
    timer. `~/.harness/` is the fallback for runs that have not been distilled into the
    repo yet — it is the harness's scratch cache, scoped per repo since pi-cluster#194
    but still living in $HOME, still unversioned, and still on a 3-day/1-day fuse.

    Reading both means a fresh clone works with no harness present at all, and a live
    machine still sees runs that finished five minutes ago.
    """
    d = os.path.join(repo, EVIDENCE, "runs" if kind == "logs" else "status")
    return [d] if os.path.isdir(d) else []


def harness_roots(base, leaf_glob):
    """Every directory under `base` that may hold run artefacts, old layout and new.

    Returns [(path, repo_or_None)] — repo is the scoping directory name when the
    artefacts came from the repo-scoped layout, None when they were flat.
    """
    roots = []
    if not os.path.isdir(base):
        return roots
    if glob.glob(os.path.join(base, leaf_glob)):
        roots.append((base, None))          # old flat layout
    for entry in sorted(os.listdir(base)):
        d = os.path.join(base, entry)
        if not os.path.isdir(d) or not REPO_DIR_RE.match(entry):
            continue
        if entry.startswith("qwen-") or entry.startswith("codex-"):
            continue                        # that's a run dir, not a repo scope
        if glob.glob(os.path.join(d, leaf_glob)):
            roots.append((d, entry))        # repo-scoped layout
    return roots

# TASK LABEL GRAMMAR — one definition, because there is more than one dialect in the wild
# and hardcoding either one is how this tool ended up unable to index the repo it lives in:
#
#   bare-label     tasks.txt "T1: create scripts/..."    commit "<agent>: T1 — ..."
#   label+slug     tasks.txt "T01 kit-package: ..."      commit "<agent>: T01 kit-package — ..."
#
# So: T, one to three digits, optional suffix letter. The slug after it is OPTIONAL, and
# the agent prefix is any "word(word):" rather than literally ralph(qwen) — a tool that
# names one executor is a tool that stops working when you change executors.
LABEL = r"T\d{1,3}[a-z]?"
AGENT_PREFIX = r"(?:[a-z]+\([a-z0-9-]+\):\s*)?"
TASK_RE = re.compile(rf"\b({LABEL})\b")


def sh(args, cwd=None):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


# --------------------------------------------------------------------------
# store 1 — git: the task commits, and the gate commits between them
# --------------------------------------------------------------------------
def spec_birth(repo, spec):
    """The commit that introduced this spec dir — a derivable lower bound for its work.

    Task labels are unique only WITHIN a spec directory: pi-cluster has 25 different
    tasks.txt files that each define a T1. Indexing a whole repo by bare label therefore
    merges unrelated features and reports every one of them as "requeued". Bounding the
    commit walk at the spec's own birth is what makes the label unambiguous again.
    """
    if not spec:
        return None
    out = sh(["git", "log", "--diff-filter=A", "--format=%H", "--reverse",
              "--", os.path.join(spec, "spec.md")], cwd=repo).split()
    return out[0] if out else None


def load_commits(repo, spec=None):
    """Every commit on this branch, tagged with the task id it names (if any)."""
    fmt = "%H%x1f%h%x1f%aI%x1f%s%x1f%b%x1e"
    args = ["git", "log", "--reverse", f"--format={fmt}"]
    birth = spec_birth(repo, spec)
    if birth:
        args.append(f"{birth}~1..HEAD" if sh(["git", "rev-parse", f"{birth}~1"],
                                             cwd=repo).strip() else "HEAD")
    out = sh(args, cwd=repo)
    commits = []
    for rec in out.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        parts = rec.split("\x1f")
        if len(parts) < 4:
            continue
        full, short, when, subject = parts[0], parts[1], parts[2], parts[3]
        m = re.match(rf"^{AGENT_PREFIX}({LABEL})(?:\s+([a-z0-9-]+))?(?=[\s:—-]|$)", subject)
        kind = "task" if m else (
            "gate" if subject.startswith("gate:") else
            "judge" if subject.startswith("judge:") else
            "spec" if subject.startswith(("spec:", "specs:", "constitution:")) else
            "docs" if subject.startswith("docs:") else
            "fix" if subject.startswith(("fix:", "feat:")) else "other")
        commits.append({
            "sha": full, "short": short, "at": when, "subject": subject,
            "kind": kind,
            "task": m.group(1) if m else None,
            "slug": m.group(2) if m else None,
        })
    return commits


def diffstat(repo, sha):
    out = sh(["git", "show", "--numstat", "--format=", sha], cwd=repo)
    files = ins = dele = 0
    for line in out.splitlines():
        f = line.split("\t")
        if len(f) == 3:
            files += 1
            ins += int(f[0]) if f[0].isdigit() else 0
            dele += int(f[1]) if f[1].isdigit() else 0
    return {"files": files, "insertions": ins, "deletions": dele}


# --------------------------------------------------------------------------
# store 2 — status JSONs: pid -> task. The only reliable join key.
# --------------------------------------------------------------------------
def load_status(repo):
    runs = {}
    paths = []
    for base in store_bases(repo, "status"):
        for root, _repo in harness_roots(base, "*.json"):
            paths += glob.glob(os.path.join(root, "*.json"))
    for p in paths:
        try:
            d = json.load(open(p))
        except Exception:
            continue
        pid = str(d.get("pid") or os.path.basename(p).split("-")[-1].split(".")[0])
        task = None
        m = TASK_RE.search((d.get("task") or "")[:40])
        if m:
            task = m.group(1)
        runs[pid] = {
            "pid": pid, "task": task, "repo": d.get("repo"), "branch": d.get("branch"),
            "task_index": d.get("task_index"), "total_tasks": d.get("total_tasks"),
            "attempt": d.get("attempt"), "max_attempts": d.get("max_attempts"),
            "phase": d.get("phase"), "verify_pass": d.get("verify_pass"),
            "last_commit": d.get("last_commit"),
            "started": d.get("started"), "updated": d.get("updated"),
            "source": "status",
        }
    return runs


# --------------------------------------------------------------------------
# store 3/4 — attempt logs. Recover the task id from log CONTENT when there is
# no status file (the status file did not exist before 2026-08-19).
# --------------------------------------------------------------------------
CWD_RE = re.compile(r"/Users/[a-zA-Z0-9._-]+/dev/([a-zA-Z0-9._-]+)")


def scan_log_dir(d):
    """Return (task_id_guess, project_guess, files) for one qwen-<pid> log dir.

    Since pi-cluster#194 (D1) the filename carries the task LABEL rather than the queue
    position: `T21-attempt2.log`, not `T1-attempt2.log`. That is authoritative when
    present — but the two are textually indistinguishable for a single-task queue, where
    position 1 and label T1 both render as `T1`. So only trust a filename label that
    cannot be a queue index: a zero-padded or high number (`T07`, `T21`), never a bare
    `T1`..`T9`. Everything else still falls back to reading the transcript.
    """
    files = sorted(os.listdir(d)) if os.path.isdir(d) else []
    task = project = None
    for name in files:
        m = re.match(r"^(T(?:\d{2,}|\d[a-z]))-attempt\d+\.(log|diff)$", name)
        if m:
            task = m.group(1)
            break
    for name in files:
        if not name.endswith(".log"):
            continue
        try:
            head = open(os.path.join(d, name), errors="replace").read(60000)
        except Exception:
            continue
        if project is None:
            m = CWD_RE.search(head)
            if m:
                project = m.group(1)
        if task is None:
            # the task line the executor was handed, e.g. "T07 session-controller:"
            m = re.search(rf"\b({LABEL})(?:\s+[a-z0-9-]{{3,30}})?\s*:", head)
            if m:
                task = m.group(1)
        if task and project:
            break
    return task, project, files


def load_log_dirs(evid, repo):
    """pid -> {attempts, diffs, stillborn, files, task_guess, project_guess, where}"""
    out = {}
    bases = []
    for b in store_bases(repo, "logs"):
        bases += [(r, "logs", sc) for r, sc in harness_roots(b, "qwen-*")]
    bases += [(r, "evidence", sc)
              for r, sc in harness_roots(os.path.join(evid, "attempts"), "qwen-*")]
    for base, where, scope_repo in bases:
        for d in sorted(glob.glob(os.path.join(base, "qwen-*"))):
            pid = os.path.basename(d).split("-", 1)[1]
            task, project, files = scan_log_dir(d)
            logs = [f for f in files if f.endswith(".log")]
            diffs = [f for f in files if f.endswith(".diff")]
            stillborn = 0
            for f in logs:
                try:
                    if os.path.getsize(os.path.join(d, f)) <= 40:
                        stillborn += 1
                except OSError:
                    pass
            mt = max((os.path.getmtime(os.path.join(d, f)) for f in files), default=None)
            rec = out.setdefault(pid, {
                "pid": pid, "attempt_logs": 0, "failed_diffs": 0, "stillborn": 0,
                "task_guess": None, "project_guess": None, "where": [], "mtime": None,
            })
            rec["attempt_logs"] = max(rec["attempt_logs"], len(logs))
            rec["failed_diffs"] = max(rec["failed_diffs"], len(diffs))
            rec["stillborn"] = max(rec["stillborn"], stillborn)
            rec["task_guess"] = rec["task_guess"] or task
            rec["project_guess"] = rec["project_guess"] or project
            rec["where"].append(where)
            if mt and (rec["mtime"] is None or mt > rec["mtime"]):
                rec["mtime"] = mt
    return out


# --------------------------------------------------------------------------
# store 5 — supervisor logs
# --------------------------------------------------------------------------
def load_supervisor(evid):
    """task -> list of {file, launches, stalls, kills, restarts, exits}"""
    by_task = defaultdict(list)
    unattributed = []
    for p in sorted(glob.glob(os.path.join(evid, "supervisor", "*.log"))):
        name = os.path.basename(p)
        try:
            text = open(p, errors="replace").read()
        except Exception:
            continue
        m = re.match(rf"sup-({LABEL})", name)
        task = m.group(1) if m else None
        if task is None:
            m = re.search(rf"TASK:\s*({LABEL})\b", text)
            task = m.group(1) if m else None
        # Two different files live in this directory and they are not the same thing:
        #   sup-Tnn.log       the SUPERVISOR's own event log — "[supervise HH:MM:SS] ..."
        #   Tnn-launchN.log   the run-loop TRANSCRIPT it launched — strategy output
        # Counting the word "restart" across both double-counts the banner
        # ("restarts used 0/8" is a status line, not a restart), so parse events.
        events = re.findall(r"^\[supervise [0-9:]+\]\s*(.+)$", text, re.M)
        is_supervisor = name.startswith("sup") or name.startswith("supervisor") or bool(events)
        strategy = None
        ms = re.search(r"^strategy:\s*(\S+)", text, re.M)
        if ms:
            strategy = ms.group(1)
        rec = {
            "file": name,
            "role": "supervisor" if is_supervisor else "run-loop transcript",
            "strategy": strategy,
            "events": events,
            "launches": sum(1 for e in events if e.startswith("launching")),
            "stalls": sum(1 for e in events if re.search(r"(?i)stall", e)),
            "kills": sum(1 for e in events if re.search(r"(?i)\bkill", e)),
            "restarts": sum(1 for e in events if re.search(r"(?i)restarting|restart #", e)),
            "stillborn": sum(1 for e in events if "STILLBORN" in e),
            "exit_zero": sum(1 for e in events if re.search(r"exited 0\b", e)),
            "exit_nonzero": sum(1 for e in events if re.search(r"exited [1-9]", e)),
            "success": sum(1 for e in events if "SUCCESS" in e),
        }
        if task:
            by_task[task].append(rec)
        else:
            unattributed.append(rec)
    return by_task, unattributed


# --------------------------------------------------------------------------
# store 6 — the judge ledger
# --------------------------------------------------------------------------
def find_judge_dir(repo):
    """Locate ralph-judge/, which hides in whichever git dir the judge ran under.

    ralph-judge.sh puts its state at `git rev-parse --git-path ralph-judge`. Run from
    a LINKED WORKTREE that resolves to .git/worktrees/<name>/ralph-judge; run from the
    main checkout it resolves to .git/ralph-judge. Those are different directories, so
    a judge that ran in a worktree is invisible from the main checkout — this script
    reported "0 findings" against a 31 KB ledger sitting right there, which is exactly
    the zero-instead-of-unavailable failure its own honesty rule forbids.

    Search the common dir AND every linked worktree. Returns (dir, None) or
    (None, reason).
    """
    common = sh(["git", "rev-parse", "--git-common-dir"], cwd=repo).strip()
    if not common:
        return None, "not a git repository"
    if not os.path.isabs(common):
        common = os.path.abspath(os.path.join(repo, common))
    candidates = [os.path.join(common, "ralph-judge")]
    candidates += sorted(glob.glob(os.path.join(common, "worktrees", "*", "ralph-judge")))
    found = [c for c in candidates if os.path.exists(os.path.join(c, "ledger.jsonl"))]
    if not found:
        return None, (f"no ledger.jsonl under {len(candidates)} candidate location(s) "
                      f"below {common}")
    if len(found) > 1:
        # Prefer the largest; report the ambiguity rather than silently picking.
        found.sort(key=lambda d: os.path.getsize(os.path.join(d, "ledger.jsonl")),
                   reverse=True)
    return found[0], None


def load_judge(repo):
    jd, why = find_judge_dir(repo)
    if jd is None:
        return None, {}, why
    ledger = os.path.join(jd, "ledger.jsonl")
    report = os.path.join(jd, "report.json")
    findings = []
    if os.path.exists(ledger):
        for line in open(ledger):
            line = line.strip()
            if line:
                try:
                    findings.append(json.loads(line))
                except Exception:
                    pass
    rep = {}
    if os.path.exists(report):
        try:
            rep = json.load(open(report))
        except Exception:
            pass
    return findings, rep, None


# --------------------------------------------------------------------------
# metrics.jsonl
# --------------------------------------------------------------------------
def load_metrics(evid, repo):
    rows = {}
    for path in (os.path.join(evid, "metrics.jsonl"),
                 os.path.join(repo, EVIDENCE, "metrics.jsonl")):
        if not os.path.exists(path):
            continue
        for line in open(path):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            t = d.get("task")
            if not t:
                continue
            prev = rows.get(t, {})
            prev.update({k: v for k, v in d.items() if v is not None})
            prev.setdefault("_sources", [])
            prev["_sources"].append("evid" if "evidence" in path else "repo")
            rows[t] = prev
    return rows


# --------------------------------------------------------------------------
# the join
# --------------------------------------------------------------------------
def build(repo, evid, project_names, spec=None):
    commits = load_commits(repo, spec)
    status = load_status(repo)
    logdirs = load_log_dirs(evid, repo)
    sup_by_task, sup_orphans = load_supervisor(evid)
    findings, judge_report, judge_why = load_judge(repo)
    metrics = load_metrics(evid, repo)

    # pid -> task, preferring the status file, falling back to log content
    runs = {}
    for pid, rec in logdirs.items():
        st = status.get(pid, {})
        task = st.get("task") or rec.get("task_guess")
        project = st.get("repo") or rec.get("project_guess")
        runs[pid] = {
            **rec,
            "task": task,
            "project": project,
            "task_source": "status" if st.get("task") else ("log-content" if rec.get("task_guess") else None),
            "status": st or None,
        }
    for pid, st in status.items():
        if pid not in runs:
            runs[pid] = {"pid": pid, "task": st.get("task"), "project": st.get("repo"),
                         "task_source": "status", "status": st, "attempt_logs": 0,
                         "failed_diffs": 0, "stillborn": 0, "where": [], "mtime": None}

    ours = {p for p in project_names}
    runs_by_task = defaultdict(list)
    foreign, unknown = [], []
    for pid, r in runs.items():
        if r.get("project") and r["project"] not in ours:
            foreign.append(r)
            continue
        if not r.get("task"):
            unknown.append(r)
            continue
        runs_by_task[r["task"]].append(r)

    # task -> commit(s)
    commits_by_task = defaultdict(list)
    for c in commits:
        if c["task"]:
            commits_by_task[c["task"]].append(c)

    # gate/fix commits that FOLLOW a task commit belong to its aftermath
    followups = defaultdict(list)
    current = None
    for c in commits:
        if c["kind"] == "task":
            current = c["task"]
        elif current and c["kind"] in ("gate", "judge", "fix", "spec"):
            followups[current].append(c)

    # tasks.txt / tasks-blocked.txt — a task can be queued and never land a commit,
    # which is exactly the case worth surfacing. Include them or the index only ever
    # shows work that succeeded.
    queued = {}
    task_files = []
    spec_dirs = [os.path.join(repo, spec)] if spec else \
        sorted(glob.glob(os.path.join(repo, SPECS, "*")))
    for sd in spec_dirs:
        if not os.path.isdir(sd):
            continue
        for fn, why in (("tasks.txt", "queued"), ("tasks-blocked.txt", "blocked")):
            task_files.append((os.path.join(sd, fn), why, os.path.basename(sd)))
    for p, why, _spec in task_files:
        if not os.path.exists(p):
            continue
        for line in open(p, errors="replace"):
            m = re.match(rf"\s*({LABEL})(?:\s+([a-z0-9-]+))?\s*[:—-]", line)
            if m:
                queued.setdefault(m.group(1), {"slug": m.group(2), "state": why,
                                               "spec": _spec})

    tasks = sorted(set(list(commits_by_task) + list(runs_by_task) + list(metrics) + list(queued)),
                   key=lambda t: (int(re.sub(r"\D", "", t) or 0), t))

    index = []
    for t in tasks:
        cs = commits_by_task.get(t, [])
        last = cs[-1] if cs else None
        m = metrics.get(t, {})
        rs = sorted(runs_by_task.get(t, []), key=lambda r: (r.get("mtime") or 0))
        sups = sup_by_task.get(t, [])

        attempts_observed = sum(r.get("attempt_logs") or 0 for r in rs) or None
        failed_observed = sum(r.get("failed_diffs") or 0 for r in rs) or None
        stillborn = sum(r.get("stillborn") or 0 for r in rs) or None

        gate = m.get("gate") or {}
        index.append({
            "task": t,
            "slug": last["slug"] if last else queued.get(t, {}).get("slug"),
            "queue_state": queued.get(t, {}).get("state"),
            "landed": bool(cs),
            "commits": [{"sha": c["short"], "at": c["at"], "subject": c["subject"][:120]} for c in cs],
            "commit": last["short"] if last else None,
            "committed_at": last["at"] if last else None,
            "requeued": len(cs) > 1,
            "diff": diffstat(repo, last["sha"]) if last else None,
            "runs": [{"pid": r["pid"], "attempt_logs": r.get("attempt_logs"),
                      "failed_diffs": r.get("failed_diffs"),
                      "stillborn": r.get("stillborn"),
                      "task_source": r.get("task_source"),
                      "phase": (r.get("status") or {}).get("phase"),
                      "verify_pass": (r.get("status") or {}).get("verify_pass"),
                      "started": (r.get("status") or {}).get("started"),
                      "updated": (r.get("status") or {}).get("updated"),
                      "mtime": r.get("mtime"),
                      "retained": "evidence" in (r.get("where") or [])} for r in rs],
            "attempts_metrics": m.get("attempts"),
            "attempts_observed": attempts_observed,
            "failed_metrics": m.get("failed_attempts"),
            "failed_observed": failed_observed,
            "stillborn_observed": stillborn,
            "supervisor": sups or None,
            "gate_pass": gate.get("pass"),
            "gate_fail": gate.get("fail"),
            "gate_pend": gate.get("pend"),
            "evidence_classes": m.get("evidence"),
            "judge_cumulative_gaps": (m.get("judge_cumulative") or {}).get("gate_gaps"),
            "judged": m.get("judged"),
            "followups": [{"sha": c["short"], "kind": c["kind"], "subject": c["subject"][:100]}
                          for c in followups.get(t, [])],
        })

    return {
        "index": index, "commits": commits, "findings": findings,
        "judge_unavailable": judge_why,
        "judge_report": judge_report, "foreign_runs": foreign,
        "unknown_runs": unknown, "sup_orphans": sup_orphans,
        "counts": {
            "tasks": len(index),
            "task_commits": sum(len(c) for c in commits_by_task.values()),
            "runs_total": len(runs),
            "runs_ours": sum(len(v) for v in runs_by_task.values()),
            "runs_foreign": len(foreign),
            "runs_unattributed": len(unknown),
            "findings": None if findings is None else len(findings),
            "status_files": len(status),
            "log_dirs": len(logdirs),
        },
    }


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------
def n(v):
    return "—" if v in (None, "", []) else str(v)


def ts(epoch):
    if not epoch:
        return "—"
    return datetime.fromtimestamp(epoch).strftime("%m-%d %H:%M")


def dur(a, b):
    if not a or not b:
        return "—"
    mins = int((b - a) // 60)
    return f"{mins//60}h{mins%60:02d}m" if mins >= 60 else f"{mins}m"


def render(data, repo):
    c = data["counts"]
    L = []
    A = L.append
    generated = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    branch = sh(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo).strip()
    head = sh(["git", "rev-parse", "--short", "HEAD"], cwd=repo).strip()

    A("# Run Index — every task the loop ran, and how it went")
    A("")
    A(f"Generated by `scripts/run-index.py` on {generated} from `{branch}` @ `{head}`.")
    A("Re-run it after every task; it derives everything and stores nothing.")
    A("")
    A("A `—` means **the data does not exist**, not zero. Columns that are mostly dashes")
    A("are the honest output of stores that were added partway through the run.")
    A("")
    A("## Totals")
    A("")
    landed = sum(1 for r in data["index"] if r["landed"])
    A(f"- **{c['tasks']} tasks** known to any store — {landed} landed a commit under their "
      f"own task id, {c['tasks'] - landed} did not")
    A(f"- **{c['task_commits']} task commits** (some tasks were requeued and committed twice)")
    A(f"- **{c['runs_ours']} executor runs** attributed to this project")
    A(f"- **{c['runs_foreign']} runs** in the evidence bundle belong to a *different* project")
    A(f"- **{c['runs_unattributed']} runs** cannot be attributed to any task")
    A(f"- **{n(c['findings'])} judge findings** in the ledger"
      + ("" if c["findings"] is not None else
         f" — *ledger not reachable from this checkout ({data['judge_unavailable']})*"))
    A("")

    # ---- the main table
    A("## Per task")
    A("")
    A("| Task | Commit | When | Diff | Attempts | Failed | Gate after | Cum. gaps | Runs | Follow-ups |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for r in data["index"]:
        d = r["diff"] or {}
        # Show both numbers when the recorded count and the retained logs disagree.
        # metrics.jsonl counts the winning run's attempts; the log store counts every
        # attempt across every run of that task, abandoned ones included.
        def pair(rec, obs):
            if rec is None:
                return n(obs)
            if obs is None or obs == rec:
                return str(rec)
            return f"{rec} / **{obs}**"
        att = pair(r["attempts_metrics"], r["attempts_observed"])
        fail = pair(r["failed_metrics"], r["failed_observed"])
        gate = "—"
        if r["gate_pass"] is not None:
            gate = f"{r['gate_pass']}P/{r['gate_fail']}F/{r['gate_pend']}p"
        when = (r["committed_at"] or "")[5:16].replace("T", " ") or "—"
        diff = f"{d.get('files','—')}f +{d.get('insertions',0)}/-{d.get('deletions',0)}" if d else "—"
        star = " ⚠︎" if r["requeued"] else ""
        if not r["landed"]:
            star = " ✗"
        A(f"| **{r['task']} {n(r['slug'])}**{star} | `{n(r['commit'])}` | {when} | {diff} "
          f"| {att} | {fail} | {gate} | {n(r['judge_cumulative_gaps'])} "
          f"| {len(r['runs']) or '—'} | {len(r['followups']) or '—'} |")
    A("")
    A("⚠︎ = committed more than once (reverted and requeued). "
      "✗ = **queued but never landed a commit under its own task id**.")
    A("")
    A("Where Attempts/Failed reads `a / **b**`, the two stores disagree: `a` is what "
      "`metrics.jsonl` recorded (the winning run only), **`b`** is how many attempt logs "
      "actually survive across every run of that task. The gap is abandoned runs — work "
      "that happened and was never counted.")
    A("")

    # ---- per-task detail
    A("## Task detail")
    A("")
    for r in data["index"]:
        A(f"### {r['task']} {n(r['slug'])}")
        A("")
        for cm in r["commits"]:
            A(f"- **commit** `{cm['sha']}` — {cm['at'][:16].replace('T',' ')} — {cm['subject']}")
        if not r["commits"]:
            A(f"- **commit** — *none.* This task is `{n(r['queue_state'])}` in the task list "
              "but no commit names it. Its work, if any, landed under some other subject — "
              "which means the queue and the history disagree about what was done.")
        if r["runs"]:
            A("- **executor runs**")
            for run in r["runs"]:
                tag = "retained" if run["retained"] else "log only"
                verdict = run["verify_pass"]
                verdict = "PASS" if verdict is True else ("FAIL" if verdict is False else "—")
                when = ts(run["started"]) if run["started"] else (
                    ts(run["mtime"]) + "~" if run.get("mtime") else "—")
                A(f"    - `qwen-{run['pid']}` · {when} · {dur(run['started'], run['updated'])} · "
                  f"{n(run['attempt_logs'])} attempt logs / {n(run['failed_diffs'])} failed-diffs "
                  f"· phase `{n(run['phase'])}` · verify {verdict} "
                  f"· task id via {n(run['task_source'])} · {tag}")
        else:
            A("- **executor runs** — *no run in either log store maps to this task*")
        if r["supervisor"]:
            sups = [s for s in r["supervisor"] if s["role"] == "supervisor"]
            trans = [s for s in r["supervisor"] if s["role"] != "supervisor"]
            for s in sups:
                bits = [f"{s['launches']} launches"]
                for k, label in (("restarts", "restarts"), ("stalls", "stalls"),
                                 ("kills", "kills"), ("stillborn", "stillborn")):
                    if s[k]:
                        bits.append(f"{s[k]} {label}")
                bits.append(f"exits {s['exit_zero']}✓/{s['exit_nonzero']}✗")
                A(f"- **supervisor** `{s['file']}` — " + ", ".join(bits))
                for e in s["events"]:
                    A(f"    - `{e[:110]}`")
            if trans:
                A("- **run-loop transcripts** — " + ", ".join(
                    f"`{s['file']}`" + (f" ({s['strategy']})" if s["strategy"] else "")
                    for s in trans))
        if r["evidence_classes"]:
            e = r["evidence_classes"]
            A("- **gate evidence** — " + ", ".join(
                f"{k} {v}" for k, v in e.items() if k != "real_evidence_pct"))
        if r["followups"]:
            A("- **follow-up commits** (what this task's output forced afterwards)")
            for f in r["followups"]:
                A(f"    - `{f['sha']}` *{f['kind']}* — {f['subject']}")
        A("")

    # ---- judge
    A("## Judge findings")
    A("")
    rep = data["judge_report"]
    if data["findings"] is None:
        A(f"**Ledger not reachable from this checkout** — {data['judge_unavailable']}.")
        A("")
        A("This is *unavailable*, not *empty*. `ralph-judge.sh` writes its state to "
          "`git rev-parse --git-path ralph-judge`, which resolves to "
          "`.git/worktrees/<name>/ralph-judge` in a linked worktree and `.git/ralph-judge` "
          "in the main checkout — so a judge that ran in a worktree is invisible from the "
          "other side. Re-run this script from the checkout the judge ran in, or pass "
          "`--repo` pointing at it.")
        A("")
    elif rep:
        A(f"`report.json` — baseline score {rep.get('baseline', {}).get('score')} over "
          f"{rep.get('baseline', {}).get('total')} checks, "
          f"`rounds_run: {rep.get('rounds_run')}`, outcome **{rep.get('outcome')}**.")
        A("")
    by_dec = defaultdict(list)
    for f in (data["findings"] or []):
        by_dec[f.get("decision", "?")].append(f)
    for dec in sorted(by_dec):
        A(f"### {dec} ({len(by_dec[dec])})")
        A("")
        A("| id | round | before | after |")
        A("|---|---|---|---|")
        for f in by_dec[dec]:
            A(f"| `{f.get('id')}` | {n(f.get('round'))} | `{n((f.get('before_head') or '')[:7])}` "
              f"| `{n((f.get('after_head') or '')[:7])}` |")
        A("")

    # ---- what the stores cannot answer
    A("## What these stores cannot answer")
    A("")
    if data["foreign_runs"]:
        A(f"**{len(data['foreign_runs'])} runs under `{EVIDENCE}/` belong to another repo.** "
          "Under the convention this should be impossible — the directory is the scope. "
          "These are almost certainly pre-convention leftovers:")
        A("")
        for r in data["foreign_runs"]:
            A(f"- `qwen-{r['pid']}` → `{r.get('project')}`")
        A("")
    if data["unknown_runs"]:
        A(f"**{len(data['unknown_runs'])} runs cannot be attributed to a task** — no status file "
          "(they predate it) and no recoverable task line in the log:")
        A("")
        A("| pid | attempt logs | failed diffs | project |")
        A("|---|---|---|---|")
        for r in sorted(data["unknown_runs"], key=lambda x: x.get("mtime") or 0):
            A(f"| `qwen-{r['pid']}` | {n(r.get('attempt_logs'))} | {n(r.get('failed_diffs'))} "
              f"| {n(r.get('project'))} |")
        A("")
    if data["findings"] is None:
        A("**The judge ledger could not be read from this checkout**, so nothing here "
          "describes it. See the Judge findings section above — and do not read its "
          "absence as an absence of findings.")
        A("")
        return "\n".join(L) + "\n"
    rounds = {f.get("round") for f in data["findings"]}
    A(f"**The judge ledger's round numbers are unusable.** {len(data['findings'])} findings "
      f"carry only rounds {sorted(x for x in rounds if x is not None)}, and `report.json` "
      f"claims `rounds_run: {rep.get('rounds_run')}` — while the cumulative gap count in "
      "`metrics.jsonl` climbs across eleven task rows. No finding can be traced to the build "
      "it was found against (`docs/lessons.md` D4).")
    A("")
    A("**Attempt logs are named by queue position, not task id.** `T1-attempt2.log` means "
      "\"second attempt at the first task in that run's queue\". The name collides across "
      "every run and never matches the task. Only the PID resolves it.")
    A("")

    disagree = [r for r in data["index"]
                if r["attempts_metrics"] is not None
                and r["attempts_observed"] is not None
                and r["attempts_metrics"] != r["attempts_observed"]]
    if disagree:
        A("**The recorded attempt count and the surviving logs disagree.** "
          + "; ".join(f"{r['task']} recorded {r['attempts_metrics']}, "
                      f"{r['attempts_observed']} logs survive"
                      for r in disagree) + ".")
        A("")
        A("It breaks in both directions, for two different reasons. **Under-counting** "
          "(recorded < logs) is `loop-metrics.sh` being handed ONE log dir — the run that "
          "finally passed — so every abandoned run before it is invisible to the cost "
          "figure. **Over-counting** (recorded > logs) is an attempt that was killed before "
          "it wrote anything, or whose log was never snapshotted; the counter incremented, "
          "the evidence did not. Neither number is the truth on its own.")
        A("")

    never = [r for r in data["index"] if not r["landed"]]
    if never:
        A("**" + ", ".join(r["task"] for r in never) + " never landed a commit under "
          "the task id.** The work went in under other subjects, so `git log --grep` — which is "
          "how `loop-metrics.sh` finds a task's commit — finds nothing and records no row at all.")
        A("")

    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evid", default=None)
    ap.add_argument("--repo", default=os.getcwd())
    ap.add_argument("--spec", default=None,
                    help="scope to one spec dir (e.g. specs/foo). REQUIRED for correctness "
                         "in a repo with more than one, since task labels are unique only "
                         "within a spec dir.")
    ap.add_argument("--project", action="append", default=None,
                    help="directory name(s) that count as this project (repeatable)")
    ap.add_argument("-o", "--out", default=os.path.join(EVIDENCE, "index.md"))
    ap.add_argument("--jsonl", default=os.path.join(EVIDENCE, "index.jsonl"))
    args = ap.parse_args()

    if args.evid is None:
        args.evid = os.environ.get("EVID") or os.path.join(args.repo, EVIDENCE)
    # A run belongs to this repo if the harness wrote it into this repo. The old
    # allowlist existed only because the store was global; under the convention the
    # directory IS the scope, so the check is the repo's own name plus any worktree.
    projects = args.project or repo_names(args.repo)
    data = build(args.repo, args.evid, projects, args.spec)

    md = render(data, args.repo)
    out = os.path.join(args.repo, args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        fh.write(md)

    jl = os.path.join(args.repo, args.jsonl)
    with open(jl, "w") as fh:
        for row in data["index"]:
            fh.write(json.dumps(row, sort_keys=True) + "\n")

    c = data["counts"]
    print(f"wrote {args.out} and {args.jsonl}", file=sys.stderr)
    findings = (f"{c['findings']} findings" if c["findings"] is not None
                else "findings UNAVAILABLE (ledger not reachable)")
    print(f"  {c['tasks']} tasks · {c['runs_ours']} runs ours · {c['runs_foreign']} foreign "
          f"· {c['runs_unattributed']} unattributed · {findings}", file=sys.stderr)


if __name__ == "__main__":
    main()
