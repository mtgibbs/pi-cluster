#!/usr/bin/env python3
"""dependency-update — a single-concern validator.

ONE question: is a Renovate dependency bump (file change) safe to merge or does it
need a human eye (major / breaking / migration / security / critical-path)? Nothing else.
Reuses the model backend from triggerable_judge; its own prompt, parser, and eval set
(specs/validators/dependency-update/eval/).

  # measure it against the ruler
  dependency_update.py --eval --backend litellm --repeat 5 --out /tmp/du.json --score
  # one case / prompt only
  dependency_update.py --id renovate-pkg [--dry-run]
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

EVAL = REPO_ROOT / "specs/validators/dependency-update/eval/expected.yaml"
SCORER = REPO_ROOT / "specs/validators/dependency-update/eval/score.py"
BEGIN, END = tj.BEGIN, tj.END

PROMPT_TEMPLATE = (REPO_ROOT / "specs/validators/dependency-update/contract.md").read_text()


def build_prompt(changes, changelog):
    blocks = [f"--- FILE: {file} ---\n{diff}" for file, diff in changes]
    header = (f"--- dependency-bump file(s) under review ---\n{len(changes)} changed file(s) in this Renovate PR.\n")
    text = header + "\n\n".join(blocks)
    if changelog:
        text += f"\n\n--- CHANGELOG (from the Renovate PR body) ---\n{changelog}"
    return PROMPT_TEMPLATE.replace("{{INPUT}}", text)


def parse(text):
    if BEGIN not in text or END not in text:
        return {"verdict": "error", "findings": ["no verdict markers"]}
    body = text.rsplit(BEGIN, 1)[1].rsplit(END, 1)[0].strip()
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        return {"verdict": "error", "findings": [f"bad json: {e}"]}
    verdict = data.get("verdict")
    if verdict not in ("pass", "flag"):
        return {"verdict": "error", "findings": [f"bad verdict: {verdict!r}"]}
    return {"verdict": verdict, "findings": data.get("findings") or []}


def aggregate(runs):
    verdicts = [r["verdict"] for r in runs]
    escalating = [v for v in verdicts if v in ("flag", "error")]
    min_to_block = len(runs) // 2 + 1
    if len(escalating) >= min_to_block:
        verdict = "flag"
    else:
        verdict = "pass"
    findings = ([f for r in runs if r["verdict"] in ("flag", "error")
                 for f in r.get("findings", [])][:5] if verdict != "pass" else [])
    return {"verdict": verdict, "runs": verdicts,
            "escalating": len(escalating), "stable": len(set(verdicts)) == 1,
            "findings": findings}


def judge_changes(changes, changelog, backend, model, timeout, raw_path):
    text, rc = tj.run_model(build_prompt(changes, changelog), timeout, raw_path, backend, model)
    res = parse(text)
    res["returncode"] = rc
    return res


def _render_pr(res):
    # Advisory: res["block"] is always False, so key the headline on the VERDICT, not block.
    needs_review = res.get("verdict") == "flag"
    head = tj.comment_marker("dependency-update") + "\n## ⚖️ dependency-update\n\n" + (
        "⚠️ This dependency bump needs human review — major / breaking / migration / security / critical-path.\n\n"
        if needs_review else "✅ routine bump — safe to merge\n\n")
    files = ", ".join(f"`{f}`" for f in res.get("files", []))
    lines = [f"**Verdict: {res['verdict'].upper()}**", f"<sub>reviewed: {files}</sub>"]
    lines += [f"- {f}" for f in (res.get("findings") or [])[:6]]
    if res.get("runs"):
        lines.append(f"\n<sub>votes: {' '.join(res['runs'])}</sub>")
    return head + "\n".join(lines)


class DependencyUpdateValidator:
    name = "dependency-update"
    concern = "Is this Renovate dependency bump safe to merge, or does it need human review (major / breaking / migration / security / critical-path)?"
    repos = {"mtgibbs/pi-cluster"}
    globs = ["clusters/pi-k3s/*.yaml", "clusters/pi-k3s/*.yml", "*Dockerfile*", "*package.json", "*.lock", "renovate.json"]

    def applies_files(self, files):
        import fnmatch
        return any(any(fnmatch.fnmatch(f, g) for g in self.globs) for f in files)

    def review(self, forge, reps, timeout, model, raw_dir):
        import fnmatch
        meta = forge.pr_meta()
        if not (meta.get("head_ref") or "").startswith("renovate/"):
            return [], False, None
        changes = [(p, patch) for p, patch in forge.changed_patches()
                   if patch and any(fnmatch.fnmatch(p, g) for g in self.globs)]
        if not changes:
            return [], False, None
        changelog = meta.get("body") or ""
        runs = []
        for r in range(reps):
            rdir = Path(raw_dir) / f"rep{r}" if reps > 1 else Path(raw_dir)
            os.makedirs(rdir, exist_ok=True)
            runs.append(judge_changes(changes, changelog, "litellm", model, timeout, rdir / "pr.raw.txt"))
        res = runs[0] if reps == 1 else aggregate(runs)
        res["files"] = [p for p, _ in changes]
        res["block"] = False
        return [res], False, _render_pr(res)


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

    raw_dir = args.raw_dir or tempfile.mkdtemp(prefix="dependency-update-")
    os.makedirs(raw_dir, exist_ok=True)
    reps = max(1, args.repeat)
    print(f"dependency-update: {len(cases)} case(s) x{reps}; backend={args.backend} "
          f"model={args.model}", file=sys.stderr)

    results = []
    for c in cases:
        if args.dry_run:
            print(build_prompt([(c["file"], c["diff"])], c["changelog"]))
            continue
        runs = []
        for r in range(reps):
            rdir = Path(raw_dir) / f"rep{r}" if reps > 1 else Path(raw_dir)
            os.makedirs(rdir, exist_ok=True)
            runs.append(judge_changes([(c["file"], c["diff"])], c["changelog"],
                                      args.backend, args.model, args.timeout,
                                      rdir / f"{c['id']}.raw.txt"))
        res = runs[0] if reps == 1 else aggregate(runs)
        res["id"] = c["id"]
        results.append(res)
        seq = f"  [{' '.join(res.get('runs', []))}]" if reps > 1 else ""
        print(f"  {c['id']:<32} -> {res['verdict']:<5}{seq}", file=sys.stderr)

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
