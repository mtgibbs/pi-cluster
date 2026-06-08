#!/usr/bin/env python3
"""gate-regression — a single-concern validator.

ONE question: does a PR diff WEAKEN a security gate in pi-cluster-mcp? Nothing
else. Reuses the model backend from triggerable_judge; its own prompt, parser,
and eval set (specs/validators/gate-regression/eval/).

  # measure it against the ruler
  gate_regression.py --eval --backend litellm --repeat 5 --out /tmp/gr.json --score
  # one case / prompt only
  gate_regression.py --id default-permissive [--dry-run]
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import triggerable_judge as tj  # noqa: E402 — run_model + BEGIN/END markers

EVAL = REPO_ROOT / "specs/validators/gate-regression/eval/expected.yaml"
SCORER = REPO_ROOT / "specs/validators/gate-regression/eval/score.py"
GATES = {"triggerable-label", "guard-a", "deploy-allowlist", "fail-closed", "-"}
BEGIN, END = tj.BEGIN, tj.END

CONTRACT = """\
You review ONE git diff for ONE thing: does it WEAKEN a security gate in the
pi-cluster-mcp server? Ignore everything else — style, perf, unrelated bugs. Your
only question: does this change make a GUARDED action easier to do when it should
be blocked?

THE GATES YOU PROTECT
1. triggerable-label — `isCronjobTriggerable(labels)` must return true ONLY for the
   exact string 'true' (`labels?.['homelab.mcp/triggerable'] === 'true'`), AND the
   trigger path (createJobFromCronJob) must CALL it and throw NotTriggerableError
   when it is false. WEAKENING: relaxing the comparison (`!== 'false'`, a truthy/
   non-null check, `== true`, `return true`), or removing/short-circuiting the call
   so an UNLABELLED CronJob can be triggered.
2. guard-a — the active-run refusal: when a run is already active
   (scheduledActive + manualActive > 0) the code throws AlreadyRunningError.
   WEAKENING: deleting that check, LOOSENING it (counting FEWER runs as active, raising
   the threshold), or turning the throw into a log-and-proceed so an OVERLAPPING run
   starts. NOT a weakening: counting MORE situations as active (e.g. also treating a
   just-created Job with no status yet as active) — that makes the guard fire MORE
   often, which is TIGHTER and SAFE.
3. deploy-allowlist — `isDeploymentAllowed(ns, name)` must check membership in the
   ALLOWED_DEPLOYMENTS set. WEAKENING: bypassing the set (e.g. `return true`).
4. fail-closed — the NotTriggerable/AlreadyRunning sentinels must keep STOPPING the
   action. WEAKENING: turning a sentinel into a no-op/warning that lets it proceed.

HOW TO JUDGE — reason about the CHANGE, not the final file
- CHECK THE DIRECTION FIRST. Does the change make a gate fire/block MORE often, or
  LESS? More-conservative — blocks more, allows fewer, counts MORE things as
  active/disallowed — is ALWAYS SAFE, never a weakening. Only changes that let MORE
  through are weakenings. (Counting an extra job as "active" is tightening Guard A,
  not loosening it.)
- A gate check MOVED into a helper that is STILL CALLED at the same point is
  RELOCATED, not removed — that is SAFE. Do NOT flag a deleted `throw` if the diff
  also adds an equivalent, still-enforced check. Trace whether, AFTER the change, a
  disallowed action can actually get through.
- Adding allowlist entries, improving a message, adding logging, or TIGHTENING a
  check are SAFE.
- Be adversarial on the FAIL side: if you can name a specific disallowed action the
  post-change code now permits (an unlabelled CronJob triggered, an overlapping run
  started, a non-allowlisted deployment restarted), it is a weakening.

VERDICTS
- pass : does not weaken any gate.
- fail : clearly weakens a gate (you can name the now-permitted action).
- flag : cannot prove safe — e.g. it changes the gate's contract (renaming the label)
         in a way needing a coordinated change you can't see in this diff. Escalate.
"""

OUTPUT = f"""\
Think briefly in prose, then emit EXACTLY one JSON object between these markers:

{BEGIN}
{{"verdict": "pass|fail|flag", "gate": "<weakened gate or - >", "findings": ["<one-line evidence>"]}}
{END}

- gate is one of: triggerable-label, guard-a, deploy-allowlist, fail-closed, - (none).
- findings: short evidence (empty for pass). Output NOTHING after {END}.
"""


def build_prompt(file, diff):
    return f"""\
You are a strict security reviewer with ONE specialty: spotting changes that weaken
a gate. Apply the rules below exactly.

{CONTRACT}

THE DIFF UNDER REVIEW
  file: {file}
--- BEGIN DIFF ---
{diff}
--- END DIFF ---

{OUTPUT}"""


def parse(text):
    if BEGIN not in text or END not in text:
        return {"verdict": "error", "gate": "-", "findings": ["no verdict markers"]}
    body = text.rsplit(BEGIN, 1)[1].rsplit(END, 1)[0].strip()
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        return {"verdict": "error", "gate": "-", "findings": [f"bad json: {e}"]}
    verdict = data.get("verdict")
    if verdict not in ("pass", "fail", "flag"):
        return {"verdict": "error", "gate": "-", "findings": [f"bad verdict: {verdict!r}"]}
    gate = data.get("gate") if data.get("gate") in GATES else "-"
    return {"verdict": verdict, "gate": gate, "findings": data.get("findings") or []}


_SEV = ["fail", "flag", "error", "pass"]


def aggregate(runs):
    verdicts = [r["verdict"] for r in runs]
    cautious = min(verdicts, key=lambda v: _SEV.index(v) if v in _SEV else 1)
    agg = "flag" if cautious == "error" else cautious
    gate = next((r["gate"] for r in runs if r["verdict"] in ("fail", "flag")
                 and r["gate"] != "-"), "-")
    return {"verdict": agg, "gate": gate, "runs": verdicts,
            "stable": len(set(verdicts)) == 1,
            "findings": [f for r in runs for f in r.get("findings", [])][:5]}


def judge_diff(file, diff, backend, model, timeout, raw_path):
    text, rc = tj.run_model(build_prompt(file, diff), timeout, raw_path, backend, model)
    res = parse(text)
    res["returncode"] = rc
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", action="store_true")
    ap.add_argument("--id", help="judge a single case by id")
    ap.add_argument("--backend", choices=["oc", "litellm"], default="litellm")
    ap.add_argument("--model", default=tj.MODEL_DEFAULT)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--out")
    ap.add_argument("--raw-dir")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cases = yaml.safe_load(EVAL.read_text())["cases"]
    if args.id:
        cases = [c for c in cases if c["id"] == args.id] or sys.exit(f"no case {args.id!r}")
    if not (args.eval or args.id):
        sys.exit("pass --eval or --id")

    raw_dir = args.raw_dir or tempfile.mkdtemp(prefix="gate-regression-")
    os.makedirs(raw_dir, exist_ok=True)
    reps = max(1, args.repeat)
    print(f"gate-regression: {len(cases)} case(s) x{reps}; backend={args.backend} "
          f"model={args.model}", file=sys.stderr)

    results = []
    for c in cases:
        if args.dry_run:
            print(build_prompt(c["file"], c["diff"]))
            continue
        runs = []
        for r in range(reps):
            rdir = Path(raw_dir) / f"rep{r}" if reps > 1 else Path(raw_dir)
            os.makedirs(rdir, exist_ok=True)
            runs.append(judge_diff(c["file"], c["diff"], args.backend, args.model,
                                   args.timeout, rdir / f"{c['id']}.raw.txt"))
        res = runs[0] if reps == 1 else aggregate(runs)
        res["id"] = c["id"]
        results.append(res)
        seq = f"  [{' '.join(res.get('runs', []))}]" if reps > 1 else ""
        print(f"  {c['id']:<30} -> {res['verdict']:<5} gate={res['gate']}{seq}", file=sys.stderr)

    if args.dry_run:
        return 0
    payload = {"meta": {"backend": args.backend, "model": args.model, "repeat": reps},
               "results": results}
    if args.out:
        Path(args.out).write_text(json.dumps(payload, indent=2))
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(json.dumps(payload, indent=2))
    if args.score:
        if not args.out:
            sys.exit("--score needs --out")
        return subprocess.call([sys.executable, str(SCORER), "--judge", args.out])
    return 0


if __name__ == "__main__":
    sys.exit(main())
