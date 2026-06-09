#!/usr/bin/env python3
"""fail-closed — a single-concern validator.

ONE question: does a PR diff make a security-relevant error path FAIL OPEN in
pi-cluster-mcp? Uphold the sentinel pattern — NotTriggerableError /
AlreadyRunningError are THROWN and the handler RETURNS the error (the action does
NOT proceed); errors.ts createError marks the refusal. A violation is a swallowed
guard (catch-and-continue, warn-and-proceed), a sentinel turned into a no-op, or
default-ALLOW on error. Nothing else (the guard's CONDITION is gate-regression's
job). Reuses the model backend from triggerable_judge; its own prompt, parser, and
eval set (specs/validators/fail-closed/eval/).

  # measure it against the ruler
  fail_closed.py --eval --backend litellm --repeat 5 --out /tmp/fc.json --score
  # one case / prompt only
  fail_closed.py --id warn-and-proceed-triggerable [--dry-run]
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

EVAL = REPO_ROOT / "specs/validators/fail-closed/eval/expected.yaml"
SCORER = REPO_ROOT / "specs/validators/fail-closed/eval/score.py"
BEGIN, END = tj.BEGIN, tj.END

# The prompt template lives next to its eval set (specs/validators/fail-closed/
# contract.md) — versioned with the cases that measure it, edited without touching
# code. `{{INPUT}}` marks where the per-diff block is substituted at build time.
PROMPT_TEMPLATE = (REPO_ROOT / "specs/validators/fail-closed/contract.md").read_text()


def build_prompt(changes):
    """changes = [(file, unified_diff), …] — judged TOGETHER so the model has
    cross-file context (a sentinel THROWN in backups.ts is RETURNED by the handler's
    catch, and the builder it returns lives in errors.ts — one wired-up refusal)."""
    blocks = [f"--- FILE: {file} ---\n{diff}" for file, diff in changes]
    header = (f"THE CHANGES UNDER REVIEW — {len(changes)} changed fail-closed-relevant "
              "file(s) in this PR. Reason ACROSS them before judging.")
    return PROMPT_TEMPLATE.replace("{{INPUT}}", header + "\n\n" + "\n\n".join(blocks))


def parse(text):
    if BEGIN not in text or END not in text:
        return {"verdict": "error", "findings": ["no verdict markers"]}
    body = text.rsplit(BEGIN, 1)[1].rsplit(END, 1)[0].strip()
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        return {"verdict": "error", "findings": [f"bad json: {e}"]}
    verdict = data.get("verdict")
    if verdict not in ("pass", "fail", "flag"):
        return {"verdict": "error", "findings": [f"bad verdict: {verdict!r}"]}
    return {"verdict": verdict, "findings": data.get("findings") or []}


def aggregate(runs):
    """Majority-to-escalate: block only when MOST of the votes escalate. Measured
    on the eval, the gap is clean — a real weakening is unanimous (5/5), while a
    safe-but-subtle change the model occasionally misreads tops out at 2/5. Strict
    majority (>=3 of 5) sits in that gap: every weakening blocks, no safe change
    false-blocks. (error counts as escalating; a minority of strays is denoised.)"""
    verdicts = [r["verdict"] for r in runs]
    escalating = [v for v in verdicts if v in ("fail", "flag", "error")]
    min_to_block = len(runs) // 2 + 1  # strict majority (reps=1 -> 1, 3 -> 2, 5 -> 3)
    if len(escalating) >= min_to_block:
        worst = next(v for v in ("fail", "flag", "error") if v in verdicts)
        verdict = "flag" if worst == "error" else worst
    else:
        verdict = "pass"
    findings = ([f for r in runs if r["verdict"] in ("fail", "flag")
                 for f in r.get("findings", [])][:5] if verdict != "pass" else [])
    return {"verdict": verdict, "runs": verdicts,
            "escalating": len(escalating), "stable": len(set(verdicts)) == 1,
            "findings": findings}


def judge_changes(changes, backend, model, timeout, raw_path):
    text, rc = tj.run_model(build_prompt(changes), timeout, raw_path, backend, model)
    res = parse(text)
    res["returncode"] = rc
    return res


def _render_pr(res):
    head = tj.comment_marker("fail-closed") + "\n## 🔒 fail-closed\n\n" + (
        "🚫 A change may make a security check **fail open** — human review required.\n\n"
        if res["block"] else "✅ Every security check still fails closed (refuses on error).\n\n")
    files = ", ".join(f"`{f}`" for f in res.get("files", []))
    lines = [f"**Verdict: {res['verdict'].upper()}**", f"<sub>reviewed: {files}</sub>"]
    lines += [f"- {f}" for f in (res.get("findings") or [])[:6]]
    if res.get("runs"):
        lines.append(f"\n<sub>votes: {' '.join(res['runs'])}</sub>")
    return head + "\n".join(lines)


class FailClosedValidator:
    """Single-concern: does a PR diff make a security check fail OPEN in pi-cluster-mcp?"""

    # ---- routing config: which repo + which files this validator runs on ----
    name = "fail-closed"
    concern = "On a failed guard or caught error, does the code still refuse — or now proceed (fail open)?"
    repos = {"mtgibbs/pi-cluster-mcp"}
    globs = ["src/utils/errors.ts", "src/tools/backups.ts", "src/tools/*.ts"]
    # -------------------------------------------------------------------------

    def applies_files(self, files):
        import fnmatch
        return any(any(fnmatch.fnmatch(f, g) for g in self.globs) for f in files)

    def review(self, forge, reps, timeout, model, raw_dir):
        import fnmatch
        changes = [(p, patch) for p, patch in forge.changed_patches()
                   if patch and any(fnmatch.fnmatch(p, g) for g in self.globs)]
        if not changes:
            return [], False, None
        # Judge ALL changed fail-closed files TOGETHER — cross-file context lets the
        # model see a sentinel THROWN in backups.ts and RETURNED by the handler's catch
        # (and the builder it returns, in errors.ts) as one wired-up refusal.
        runs = []
        for r in range(reps):
            rdir = Path(raw_dir) / f"rep{r}" if reps > 1 else Path(raw_dir)
            os.makedirs(rdir, exist_ok=True)
            runs.append(judge_changes(changes, "litellm", model, timeout, rdir / "pr.raw.txt"))
        res = runs[0] if reps == 1 else aggregate(runs)
        res["files"] = [p for p, _ in changes]
        res["block"] = res["verdict"] != "pass"
        return [res], res["block"], _render_pr(res)


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

    raw_dir = args.raw_dir or tempfile.mkdtemp(prefix="fail-closed-")
    os.makedirs(raw_dir, exist_ok=True)
    reps = max(1, args.repeat)
    print(f"fail-closed: {len(cases)} case(s) x{reps}; backend={args.backend} "
          f"model={args.model}", file=sys.stderr)

    results = []
    for c in cases:
        if args.dry_run:
            print(build_prompt([(c["file"], c["diff"])]))
            continue
        runs = []
        for r in range(reps):
            rdir = Path(raw_dir) / f"rep{r}" if reps > 1 else Path(raw_dir)
            os.makedirs(rdir, exist_ok=True)
            runs.append(judge_changes([(c["file"], c["diff"])], args.backend, args.model,
                                      args.timeout, rdir / f"{c['id']}.raw.txt"))
        res = runs[0] if reps == 1 else aggregate(runs)
        res["id"] = c["id"]
        results.append(res)
        seq = f"  [{' '.join(res.get('runs', []))}]" if reps > 1 else ""
        print(f"  {c['id']:<34} -> {res['verdict']:<5}{seq}", file=sys.stderr)

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
