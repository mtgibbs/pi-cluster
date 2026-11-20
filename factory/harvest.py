#!/usr/bin/env python3
"""harvest.py — turn a factory run's judge verdicts into candidate eval cases.

  FABRO_URL=... FABRO_DEV_TOKEN=... factory/harvest.py <run-id> [<run-id> ...]

For every spec-judge round in the run it writes
  factory/evals/spec-judge/cases/<run-id>-r<N>.json
holding exactly what the judge was shown (the review packet), what it said, and what the
human then did at the gate. Existing case files are never overwritten.

Why a script on the laptop and not a stage in the run: a judge must not be able to write
the cases that grade it. This reads the run's recorded log after the fact; the cases reach
the eval set only through a pull request a human reviews.

`label` is always written as null. A case counts in the eval set only once a human sets it:
  "confirmed" — the judge's verdict was right (a real hole, or a sound spec)
  "wrong"     — the judge was wrong (false alarm, or a miss found later)
`human_action` is recorded as evidence for that call, not as the label: approving over a
raise suggests "wrong", rejecting or revising suggests "confirmed", but only a person decides.
"""
import base64, json, os, pathlib, re, sys, urllib.parse, urllib.request

U = os.environ["FABRO_URL"].rstrip("/") + "/api/v1"
T = os.environ["FABRO_DEV_TOKEN"]
OUT = pathlib.Path(__file__).resolve().parent / "evals" / "spec-judge" / "cases"


def get(path):
    req = urllib.request.Request(U + path, headers={"Authorization": "Bearer " + T})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def stage_output(rid, sid):
    o = get(f"/runs/{rid}/stages/{urllib.parse.quote(sid, safe='')}/logs/output")
    return base64.b64decode(o["bytes_base64"]).decode(errors="replace")


def gate_answers(rid):
    """{stage visit number of approve_spec: answer} from the run's recorded events."""
    answers, after = [], None
    while True:
        d = get(f"/runs/{rid}/events?limit=1000" + (f"&after={after}" if after else ""))
        for it in d["data"]:
            rec = (it.get("item") or {}).get("record") or {}
            if rec.get("kind") == "interview.answered" and str(rec.get("question", "")).startswith("approve_spec#"):
                answers.append({"answer": rec.get("answer"), "by": (rec.get("principal") or {}).get("login")})
        if not d["meta"].get("has_more"):
            return answers
        after = d["data"][-1]["stream_seq"]


def action(ans):
    a = ans.get("answer")
    key = a if isinstance(a, str) else json.dumps(a)
    return {"A": "approved", "X": "rejected", "a": "aborted"}.get(key, "revised-with-note")


def harvest(rid):
    run = get(f"/runs/{rid}")
    stages = get(f"/runs/{rid}/stages")["data"]
    by_node = lambda n: [s for s in stages if s["node_id"] == n and s["status"] == "succeeded"]
    packets = {}
    for s in by_node("spec_check") + by_node("lock"):
        out = stage_output(rid, s["id"])
        for sid, body in re.findall(r"-----BEGIN SPEC PACKET (\w+)-----\n(.*?)\n-----END SPEC PACKET \1-----", out, re.S):
            packets[sid] = body
        m = re.search(r"spec id (\w{12})", out)          # runs before the packet echo existed
        if m and m.group(1) not in packets and "===== specs/" in out:
            packets[m.group(1)] = out[out.index("===== specs/"):]
    answers = gate_answers(rid)
    caps = by_node("spec_capture")
    written = []
    for n, s in enumerate(caps, 1):
        out = stage_output(rid, s["id"])
        upd = json.loads(out.strip().splitlines()[-1])["context_updates"]
        verdict, reasons = upd["fx_spec_verdict"], json.loads(upd["fx_spec_reasons"])
        judge = by_node("spec_judge")[n - 1]
        reply = stage_output(rid, judge["id"])
        m = re.search(r'"id":\s*"(\w+)"', reply.strip().splitlines()[-1]) if reply.strip() else None
        pid = m.group(1) if m else ""
        last = n == len(caps)
        case = {
            "judge": "spec-judge",
            "source": {"run": rid, "round": n, "of": len(caps), "title": run.get("title"),
                       "model": (judge.get("provider_used") or {}).get("model")},
            "idea": run.get("goal"),
            "packet_id": pid,
            "packet": packets.get(pid),
            "verdict": verdict,
            "reasons": reasons,
            "judge_seconds": judge.get("wall_time_ms", 0) // 1000,
            # Only the last round reaches a human; earlier raises were answered by the spec writer.
            "followed_by": ("human gate" if last else "automatic revise round"),
            "human_action": (action(answers[-1]) if last and answers else None),
            "human_answered_as": (answers[-1]["by"] if last and answers else None),
            "label": None,
            "label_note": "",
        }
        f = OUT / f"{rid}-r{n}.json"
        if f.exists():
            print(f"skip   {f.name} (exists)")
            continue
        OUT.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(case, indent=2, ensure_ascii=False) + "\n")
        written.append(f.name)
        print(f"wrote  {f.name}: {verdict}, {len(reasons)} reasons, packet {'ok' if case['packet'] else 'MISSING'}, human: {case['human_action']}")
    if not caps:
        print(f"{rid}: no spec-judge verdicts recorded")
    return written


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for r in sys.argv[1:]:
        harvest(r)
