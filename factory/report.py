#!/usr/bin/env python3
"""report.py — time and cost of factory runs, by role, so model profiles can be compared.

  FABRO_URL=... FABRO_DEV_TOKEN=... factory/report.py [--json] [<run-id> ...]

With no run ids it reports every run whose title starts with "factory:". For each run it
reads Fabro's recorded stages (which model ran, wall time, tokens) and prints, per role:
the model, minutes, visits, tokens, and an estimated cost from factory/models.toml.

Two cost figures are printed for hosted models: `est` assumes the gateway honours prompt
caching (cache-read tokens billed at the cache rate), `no-cache` bills them as fresh input.
Both are estimates; LiteLLM's spend log for Fabro's key is the bill of record.

Outcome columns come from the run's own state: where it ended, the factory verdict, how
many times the local gates and CI went red, and how many times each judge raised.
Judge panels: each judge role's `visits` is the number of votes cast (one agent visit per
vote), and a `panel` line per judge shows every round's tally (raise / pass / none of the
votes cast, panel size, threshold, outcome). Runs from before panels show one vote per round.
"""
import json, os, pathlib, sys, tomllib, urllib.request

U = os.environ["FABRO_URL"].rstrip("/") + "/api/v1"
T = os.environ["FABRO_DEV_TOKEN"]
CFG = tomllib.loads((pathlib.Path(__file__).resolve().parent / "models.toml").read_text())
ROLES = {"ideate": "writer", "spec_judge": "spec_judge", "implement": "builder", "conf_judge": "conf_judge"}
ORDER = ["writer", "spec_judge", "builder", "conf_judge"]


def get(path):
    req = urllib.request.Request(U + path, headers={"Authorization": "Bearer " + T})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def cost(model, tok):
    """(estimate, no-cache worst case) in USD, or (None, None) for a model with no price."""
    p = (CFG["models"].get(model) or {}).get("usd_per_mtok")
    if p is None:
        return None, None
    i, o, c = tok.get("input", 0), tok.get("output", 0) + tok.get("reasoning", 0), tok.get("cache_read", 0)
    est = (i * p["input"] + o * p["output"] + c * p["cache_read"]) / 1e6
    worst = ((i + c) * p["input"] + o * p["output"]) / 1e6
    return est, worst


def profile_of(models):
    for name, prof in CFG["profiles"].items():
        if all(models.get(r) in (None, prof[r]) for r in ORDER) and any(models.values()):
            if all(models.get(r) == prof[r] for r in ORDER if models.get(r)):
                return name
    return "custom"


def last_fx(rid, stages):
    """The factory's own state as of the last script stage that emitted it."""
    import base64
    for s in reversed(stages):
        if s.get("handler") == "agent" or s["status"] != "succeeded":
            continue
        try:
            o = get(f"/runs/{rid}/stages/{urllib.request.quote(s['id'], safe='')}/logs/output")
            line = base64.b64decode(o["bytes_base64"]).decode(errors="replace").strip().splitlines()[-1]
            fx = json.loads(line)["context_updates"].get("fx")
            if fx:
                return fx
        except Exception:
            continue
    return {}


def one(rid):
    run = get(f"/runs/{rid}")
    stages = get(f"/runs/{rid}/stages")["data"]
    roles = {r: {"model": None, "seconds": 0, "visits": 0, "failed": 0,
                 "tokens": {"input": 0, "output": 0, "reasoning": 0, "cache_read": 0}} for r in ORDER}
    for s in stages:
        r = ROLES.get(s["node_id"])
        if not r:
            continue
        d = roles[r]
        d["model"] = (s.get("provider_used") or {}).get("model") or d["model"]
        d["seconds"] += (s.get("wall_time_ms") or 0) // 1000
        d["visits"] += 1
        d["failed"] += s["status"] == "failed"
        for k, v in ((s.get("usage") or {}).get("tokens") or {}).items():
            if k in d["tokens"]:
                d["tokens"][k] += v or 0
    for d in roles.values():
        d["usd_est"], d["usd_no_cache"] = cost(d["model"], d["tokens"]) if d["model"] else (None, None)
    fx = last_fx(rid, stages)
    log = fx.get("judge_log") or []
    tallies = {k: fx.get(f"{k}_tallies") for k in ("spec", "conf")}

    def raises(k):          # panel runs count raised ROUNDS; older runs logged one entry per round
        if tallies[k] is not None:
            return sum(1 for t in tallies[k] if t.get("outcome") == "raise")
        return sum(1 for j in log if j.get("judge") == k and j.get("verdict") == "raise")
    status = ((run.get("lifecycle") or {}).get("status") or {}).get("kind") or (run.get("status") or {}).get("kind")
    gate = sum(s["wall_time_ms"] or 0 for s in stages if s.get("handler") == "human" or s["node_id"].startswith("approve")) // 1000
    total = sum((s.get("wall_time_ms") or 0) for s in stages) // 1000
    return {
        "run": rid, "title": run.get("title"), "status": status,
        "last_stage": stages[-1]["node_id"] if stages else None,
        "profile": profile_of({r: roles[r]["model"] for r in ORDER}),
        "roles": roles,
        "machine_seconds": total - gate, "human_wait_seconds": gate,
        "usd_est": sum(d["usd_est"] or 0 for d in roles.values()),
        "usd_no_cache": sum(d["usd_no_cache"] or 0 for d in roles.values()),
        "verdict": (fx.get("verdict") or {}).get("verdict"),
        "class": fx.get("class"),
        "gate_fails": fx.get("gate_fails"), "ci_red_rounds": fx.get("ci_red_rounds"),
        "spec_raises": raises("spec"), "conf_raises": raises("conf"),
        "panel": fx.get("panel"),
        "votes_cast": {k: sum(1 for j in log if j.get("judge") == k) for k in ("spec", "conf")},
        "tallies": {k: tallies[k] or [] for k in ("spec", "conf")},
        "pr": (fx.get("pr") or {}).get("url"),
    }


def mins(s):
    return f"{s / 60:.0f}m"


def show(r):
    print(f"\n{r['run']}  {r['title']}")
    print(f"  profile {r['profile']} · ended {r['status']} at `{r['last_stage']}` · verdict {r['verdict'] or '-'}"
          f" · class {r['class'] or '-'}")
    print(f"  machine time {mins(r['machine_seconds'])} · waiting on a human {mins(r['human_wait_seconds'])}"
          f" · est ${r['usd_est']:.2f} (no-cache ${r['usd_no_cache']:.2f})")
    print(f"  gate fails {r['gate_fails']} · CI red rounds {r['ci_red_rounds']} · spec raises {r['spec_raises']}"
          f" · conformance raises {r['conf_raises']}" + (f"\n  {r['pr']}" if r["pr"] else ""))
    print(f"  {'role':<11}{'model':<15}{'time':>6}{'visits':>7}{'in':>9}{'cached':>10}{'out':>8}{'est $':>8}{'no-cache $':>12}")
    for name in ORDER:
        d = r["roles"][name]
        if not d["visits"]:
            continue
        t = d["tokens"]
        e = "-" if d["usd_est"] is None else f"{d['usd_est']:.2f}"
        w = "-" if d["usd_no_cache"] is None else f"{d['usd_no_cache']:.2f}"
        v = f"{d['visits']}" + (f" ({d['failed']}✗)" if d["failed"] else "")
        print(f"  {name:<11}{d['model'] or '?':<15}{mins(d['seconds']):>6}{v:>7}{t['input']:>9}{t['cache_read']:>10}"
              f"{t['output'] + t['reasoning']:>8}{e:>8}{w:>12}")
    for k, name in (("spec", "spec_judge"), ("conf", "conf_judge")):
        ts = r["tallies"][k]
        if not ts and not r["votes_cast"][k]:
            continue
        rounds = "; ".join(f"r{t['round']} {t['outcome']} {t['raise']}R/{t['pass']}P/{t['none']}N of {t['cast']}"
                           f" (panel {t['n']}, threshold {t['threshold']})" for t in ts) or "no decided rounds"
        print(f"  {name} panel: {r['votes_cast'][k]} vote(s) cast · {rounds}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "-h" in sys.argv or "--help" in sys.argv:
        sys.exit(__doc__)
    if not args:
        args = [r["id"] for r in get("/runs?limit=200")["data"] if str(r.get("title", "")).startswith("factory:")]
        args.reverse()
    out = [one(r) for r in args]
    if "--json" in sys.argv:
        print(json.dumps(out, indent=2))
    else:
        for r in out:
            show(r)
