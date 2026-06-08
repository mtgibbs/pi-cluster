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

# The prompt template lives next to its eval set (specs/validators/gate-regression/
# contract.md) — versioned with the cases that measure it, edited without touching
# code. `{{INPUT}}` marks where the per-diff block is substituted at build time.
PROMPT_TEMPLATE = (REPO_ROOT / "specs/validators/gate-regression/contract.md").read_text()


def build_prompt(file, diff):
    input_block = (f"THE DIFF UNDER REVIEW\n  file: {file}\n"
                   f"--- BEGIN DIFF ---\n{diff}\n--- END DIFF ---")
    return PROMPT_TEMPLATE.replace("{{INPUT}}", input_block)


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


def _render(results, any_block):
    head = "## 🛡️ gate-regression\n\n" + (
        "🚫 A change may **weaken a security gate** — human review required.\n\n"
        if any_block else "✅ No security gate is weakened by these changes.\n\n")
    secs = []
    for r in results:
        body = "\n".join(f"- {f}" for f in (r.get("findings") or [])[:4])
        secs.append(f"### `{r['path']}` — **{r['verdict'].upper()}**  (gate: {r.get('gate', '-')})\n{body}")
    return head + "\n\n".join(secs)


class GateRegressionValidator:
    """Single-concern: does a PR diff weaken a security gate in pi-cluster-mcp?"""

    # ---- routing config: which repo + which files this validator runs on ----
    name = "gate-regression"
    repos = {"mtgibbs/pi-cluster-mcp"}
    globs = ["src/utils/whitelist.ts", "src/utils/errors.ts", "src/tools/*.ts"]
    # -------------------------------------------------------------------------

    def applies_files(self, files):
        import fnmatch
        return any(any(fnmatch.fnmatch(f, g) for g in self.globs) for f in files)

    def review(self, forge, reps, timeout, model, raw_dir):
        import fnmatch
        targets = [(p, patch) for p, patch in forge.changed_patches()
                   if patch and any(fnmatch.fnmatch(p, g) for g in self.globs)]
        if not targets:
            return [], False, None
        results, any_block = [], False
        for p, patch in targets:
            runs = []
            for r in range(reps):
                rdir = Path(raw_dir) / f"rep{r}" if reps > 1 else Path(raw_dir)
                os.makedirs(rdir, exist_ok=True)
                runs.append(judge_diff(p, patch, "litellm", model, timeout,
                                       rdir / f"{p.replace('/', '_')}.raw.txt"))
            res = runs[0] if reps == 1 else aggregate(runs)
            res["path"] = p
            res["block"] = res["verdict"] != "pass"
            any_block = any_block or res["block"]
            results.append(res)
        return results, any_block, _render(results, any_block)


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
