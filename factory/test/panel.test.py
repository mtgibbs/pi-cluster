#!/usr/bin/env python3
"""Unit tests for the judge panels (factory/steps.py) and a structural check of the graph.
Plain python, no network, no git, no Fabro:

  python3 factory/test/panel.test.py

Stages are run as real subprocesses (`steps.py vote|raised|forward|verdict`, stdin = fx) with
FACTORY_TEST_DIR pointing /tmp/factory at a scratch directory.
"""
import importlib.util, json, os, pathlib, re, subprocess, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent.parent
STEPS = HERE / "steps.py"
TMP = tempfile.mkdtemp(prefix="factory-panel-test-")
os.environ["FACTORY_TEST_DIR"] = TMP
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("steps", STEPS)
steps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(steps)

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL {name}" + (f": {detail}" if detail else ""))


def run(stage, fx, *args, stdin=None):
    p = subprocess.run([sys.executable, str(STEPS), stage, *args], capture_output=True, text=True,
                       input=json.dumps(fx) if stdin is None else stdin, env=dict(os.environ, FACTORY_TEST_DIR=TMP))
    lines = p.stdout.strip().splitlines()
    upd = json.loads(lines[-1])["context_updates"] if lines and lines[-1].startswith("{") else {}
    return p, upd


def cast(fx, kind, verdict, reasons=(), pid="abc123abc123"):
    """What capture leaves behind for one vote, then the vote stage."""
    with open(f"{TMP}/{kind}-verdict.json", "w") as fh:
        json.dump({"verdict": verdict, "id": pid if verdict != "none" else "", "reasons": list(reasons),
                   "why": "" if verdict != "none" else "empty response"}, fh)
    p, upd = run("vote", fx, kind)
    check(f"vote stage exits 0 ({verdict})", p.returncode == 0, p.stdout + p.stderr)
    check("vote file deleted after the vote stage", not os.path.exists(f"{TMP}/{kind}-verdict.json"))
    return upd["fx"], upd[f"fx_{kind}_panel"], upd[f"fx_{kind}_vote"]


def fresh(panel=""):
    return {"spec": "x", "panel": steps.parse_panel(panel)}


# ------------------------------------------------------------------ tally()
T = steps.tally
# N=1 parity with the single judge: the vote IS the verdict.
check("N=1 raise", T(["raise"], 1, 1) == "raise")
check("N=1 pass", T(["pass"], 1, 1) == "pass")
check("N=1 none", T(["none"], 1, 1) == "none")
check("N=1 nothing cast yet -> more", T([], 1, 1) == "more")
# 5 votes, threshold 3 (pass needs 3 actual passes).
check("5/3: 3 raise -> raise", T(["raise"] * 3, 5, 3) == "raise")
check("5/3: 3 pass -> pass", T(["pass"] * 3, 5, 3) == "pass")
check("5/3: 2R 1P 2N -> none", T(["raise", "raise", "pass", "none", "none"], 5, 3) == "none")
for i in range(1, 5):
    check(f"5/3: 2R 1P 2N not decided after {i}", T(["raise", "raise", "pass", "none", "none"][:i], 5, 3) == "more")
check("5/3: early stop on 3 raises (2 votes never cast)", T(["raise", "raise", "raise"], 5, 3) == "raise")
check("5/3: 2 raises is not yet decided", T(["raise", "raise"], 5, 3) == "more")
check("5/3: early stop on 3 passes", T(["pass", "pass", "pass"], 5, 3) == "pass")
check("5/3: 3 none -> none early (neither bar reachable)", T(["none"] * 3, 5, 3) == "none")
check("5/3: 2R 2P -> more, then P -> pass", T(["raise", "raise", "pass", "pass"], 5, 3) == "more"
      and T(["raise", "raise", "pass", "pass", "pass"], 5, 3) == "pass")
# Fail closed: a none vote never counts as a pass.
check("3/2: 1P 2N -> none (none is not pass)", T(["pass", "none", "none"], 3, 2) == "none")
check("3/1 (any raise blocks): 2P then R -> raise", T(["pass", "pass", "raise"], 3, 1) == "raise")
check("3/1: pass needs all 3", T(["pass", "pass"], 3, 1) == "more" and T(["pass", "pass", "none"], 3, 1) == "none")
check("3/3: one pass is enough to pass", T(["pass"], 3, 3) == "pass")
# Exhaustive: never pass and raise at once; pass never without enough real passes.
import itertools
for n in range(1, 6):
    for thr in range(1, n + 1):
        for k in range(0, n + 1):
            for vs in itertools.product(["pass", "raise", "none"], repeat=k):
                d = T(list(vs), n, thr)
                if d == "pass" and vs.count("pass") < n - thr + 1:
                    check(f"exhaustive pass bar n={n} t={thr} {vs}", False)
                if d == "raise" and vs.count("raise") < thr:
                    check(f"exhaustive raise bar n={n} t={thr} {vs}", False)
                if k == n and d == "more":
                    check(f"exhaustive all cast decides n={n} t={thr} {vs}", False)
check("exhaustive tally sweep ran", True)

# ------------------------------------------------------------------ validation
for bad in ["spec_threshold=0", "spec_votes=3 spec_threshold=4", "spec_votes=0", "bogus=1", "spec_votes=x",
            "spec_votes=-1", "spec_votes", f"conf_votes={steps.MAX_VOTES + 1}", "conf_rounds=99"]:
    try:
        steps.parse_panel(bad)
        check(f"parse_panel rejects {bad!r}", False)
    except ValueError:
        check(f"parse_panel rejects {bad!r}", True)
check("parse_panel defaults", steps.parse_panel("") == steps.DEFAULT_PANEL)
check("parse_panel ok", steps.parse_panel("spec_votes=5 spec_threshold=3 conf_votes=3 conf_threshold=2")["spec_threshold"] == 3)
check("even N allowed", steps.parse_panel("spec_votes=4 spec_threshold=2")["spec_votes"] == 4)

# ------------------------------------------------------------------ the vote stage, N=1 parity
fx = fresh("spec_rounds=2")
fx, d, vid = cast(fx, "spec", "raise", ["r1 objection"])
check("N=1 one raise vote decides raise", d == "raise" and vid == "r1v1", (d, vid))
check("judge_log has round + vote index", fx["judge_log"][-1] == {
    "judge": "spec", "round": 1, "vote": 1, "of": 1, "verdict": "raise", "packet": "abc123abc123",
    "reasons": ["r1 objection"], "why": ""}, fx["judge_log"][-1])
p, upd = run("raised", fx, "spec")
check("N=1 raise 1 -> revise", upd.get("fx_spec_next") == "revise", p.stdout)
fx = upd["fx"]
fb = open(f"{TMP}/spec-feedback.md").read()
check("feedback header k of N", "1 of 1 voters raised" in fb and "### Voter 1" in fb and "- r1 objection" in fb, fb)
fx, d, _ = cast(fx, "spec", "raise", ["r2 objection"])
fx = run("raised", fx, "spec")[1]["fx"]
fx, d, vid = cast(fx, "spec", "raise", ["r3 objection"])
check("round numbering continues", vid == "r3v1", vid)
p, upd = run("raised", fx, "spec")
check("N=1: raise 3 with spec_rounds=2 -> hold", upd.get("fx_spec_next") == "hold", p.stdout)
fx = upd["fx"]
fb = open(f"{TMP}/spec-feedback.md").read()
check("feedback lists latest round first", fb.index("round 3 (LATEST") < fb.index("round 2 (earlier") < fb.index("round 1 (earlier"), fb)
fx1 = fresh()
fx1, d, _ = cast(fx1, "spec", "none")
check("N=1 none vote -> none", d == "none")
check("none vote logs its reason", fx1["judge_log"][-1]["why"] == "empty response")
fx1 = fresh()
fx1, d, _ = cast(fx1, "spec", "pass", ["ok"])
check("N=1 pass vote -> pass", d == "pass")
# a missing vote file (capture crashed) is a none vote
fx1 = fresh()
p, upd = run("vote", fx1, "spec")
check("missing vote file -> none", upd.get("fx_spec_panel") == "none", p.stdout)

# ------------------------------------------------------------------ 5/3 spec panel through the stages
fx = fresh("spec_votes=5 spec_threshold=3 spec_rounds=4")
seq = []
for i, v in enumerate(["raise", "pass", "raise", "raise"], 1):
    fx, d, vid = cast(fx, "spec", v, [f"voter{i} says {v}"])
    seq.append(d)
check("5/3: R P R -> more, 4th R decides raise, 5th never cast", seq == ["more", "more", "more", "raise"], seq)
check("5/3 tally recorded", fx["spec_tallies"][-1] == {"round": 1, "n": 5, "threshold": 3, "cast": 4, "raise": 3,
                                                        "pass": 1, "none": 0, "outcome": "raise"}, fx["spec_tallies"])
check("open round cleared once decided", "spec_open" not in fx)
p, upd = run("raised", fx, "spec")
fx = upd["fx"]
fb = open(f"{TMP}/spec-feedback.md").read()
check("5/3 feedback: 3 of 5 voters raised, early-stop note",
      "3 of 5 voters raised (4 votes cast; voting stops once the outcome is decided)" in fb, fb)
check("5/3 feedback: grouped per raising voter only",
      "### Voter 1" in fb and "### Voter 3" in fb and "### Voter 4" in fb and "### Voter 2" not in fb
      and "voter2 says pass" not in fb, fb)
check("raised -> revise within cap", upd.get("fx_spec_next") == "revise")
# Independence inside a round: the feedback file is not touched by votes.
before = open(f"{TMP}/spec-feedback.md").read()
fx, d, _ = cast(fx, "spec", "raise", ["round2 voter1"])
check("a vote does not rewrite the feedback file", open(f"{TMP}/spec-feedback.md").read() == before and d == "more")
check("vote files of this round are gone", not any(n.endswith("-verdict.json") for n in os.listdir(TMP)))
# round 2: pass with minority raise -> pass, minority notes kept
for v in ["pass", "pass", "pass"]:
    fx, d, vid = cast(fx, "spec", v, ["fine"])
check("round 2: R P P P -> pass at vote 4", d == "pass" and vid == "r2v4", (d, vid))
notes = steps.minority_notes(fx, "spec")
check("minority notes carried on a pass", "NON-BLOCKING" in notes and "1 of 5 voters raised" in notes
      and "round2 voter1" in notes and "### Voter 1" in notes, notes)
check("no minority notes on a clean pass", steps.minority_notes(
    {"spec_tallies": [{"round": 1, "n": 3, "threshold": 2, "cast": 2, "raise": 0, "pass": 2, "none": 0, "outcome": "pass"}]},
    "spec") == "")

# ------------------------------------------------------------------ forward ([F] at the gate)
if os.path.exists(f"{TMP}/human-note.md"):
    os.remove(f"{TMP}/human-note.md")
p, upd = run("forward", fx, "spec")
check("forward: latest round had a raising voter -> yes", upd.get("fx_spec_forwarded") == "yes", p.stdout)
hn = open(f"{TMP}/human-note.md").read()
check("forward writes the objections as the human note", "round2 voter1" in hn and "1 of 5 voters raised" in hn, hn)
check("forward recorded in fx", upd["fx"]["forwards"] == [{"kind": "spec", "round": 2}])
clean = fresh()
clean, _, _ = cast(clean, "spec", "pass", ["ok"])
p, upd = run("forward", clean, "spec")
check("forward with nothing open -> no", upd.get("fx_spec_forwarded") == "no", p.stdout)

# ------------------------------------------------------------------ conformance 3/2 + verdict record
fx["conf_judge"] = None
fx = {**fx, "panel": steps.parse_panel("spec_votes=5 spec_threshold=3 conf_votes=3 conf_threshold=2")}
fx, d, _ = cast(fx, "conf", "raise", ["missing AC3"], pid="d1ff1d")
fx, d, _ = cast(fx, "conf", "pass", ["ok"], pid="d1ff1d")
fx, d, _ = cast(fx, "conf", "pass", ["ok"], pid="d1ff1d")
check("conf 3/2: R P P -> pass", d == "pass")
fx["conf_judge"] = "pass"
p, upd = run("verdict", fx)
check("verdict stage runs without a PR", p.returncode == 0 and upd.get("fx_verdict") == "hold", p.stdout + p.stderr)
rec = json.loads(re.search(r"<!-- factory:record (.*) -->", p.stdout).group(1))
check("verdict record has per-round tallies", rec["panels"]["conf"][0]["outcome"] == "pass"
      and len(rec["panels"]["spec"]) == 2 and rec["panel"]["conf_votes"] == 3, rec.get("panels"))
check("verdict body shows conf minority notes", "missing AC3" in p.stdout and "NON-BLOCKING" in p.stdout, p.stdout)
check("verdict body shows tallies", "conformance judge panel: r1 pass (1 raise / 2 pass / 0 none of 3 cast" in p.stdout, p.stdout)

# ------------------------------------------------------------------ graph structure (no graphviz needed)
g = (HERE / "mcp" / "workflow.fabro").read_text()
body = re.sub(r"//[^\n]*", "", g)
nodes = set(re.findall(r"^\s*([a-z_]+)\s*\[", body, re.M)) - {"graph"}
edges = re.findall(r"^[ \t]*([a-z_]+)[ \t]*->[ \t]*([a-z_]+)[ \t]*(\[[^\n]*\])?", body, re.M)
check("graph brackets balance", body.count("[") == body.count("]") and body.count("{") == body.count("}"))
check("graph quotes balance", len(re.findall(r'(?<!\\)"', body)) % 2 == 0)
for a, b, _ in edges:
    check(f"edge {a}->{b} endpoints declared", a in nodes and b in nodes)
outs = {}
for a, b, attrs in edges:
    outs.setdefault(a, []).append((b, attrs or ""))
for k in ("spec", "conf"):
    o = outs.get(f"{k}_vote", [])
    check(f"{k}_vote loops on more", (f"{k}_judge", f'[condition="outcome=succeeded && fx_{k}_panel=more"]') in o, o)
    check(f"{k}_vote unconditional edge is the hold marker", (f"{k}_none", "") in o, o)
    check(f"{k}_capture always hands to {k}_vote", outs.get(f"{k}_capture") == [(f"{k}_vote", "")])
    check(f"{k}_judge only goes to capture (judges never route)", outs.get(f"{k}_judge") == [(f"{k}_capture", "")])
check("spec_forward forward edge is conditioned", ("ideate", '[condition="outcome=succeeded && fx_spec_forwarded=yes"]') in outs["spec_forward"])
check("spec_forward fallback re-presents the gate", ("lock", "") in outs["spec_forward"])
for n in ("spec_vote", "conf_vote", "spec_forward", "spec_capture", "conf_capture", "spec_raised", "conf_raised"):
    decl = re.search(rf"^\s*{n}\s*\[.*?\]\s*$", body, re.M | re.S)
    check(f"{n} re-checks code_sha", decl and "inputs.code_sha" in decl.group(0))
for k in ("spec", "conf"):
    decl = re.search(rf"^\s*{k}_judge\s*\[[^\n]*\]", body, re.M).group(0)
    check(f"{k}_judge keeps fidelity=truncate and no thread_id", 'fidelity="truncate"' in decl and "thread_id" not in decl)
for k in steps.PANEL_KEYS:
    check(f"setup passes inputs.{k}", f"{k}={{{{ inputs.{k} }}}}" in g)

print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
