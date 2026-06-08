#!/usr/bin/env python3
"""Score the triggerable-judge against the evaluation set.

The eval set (expected.yaml) is the ruler. This scorer grades two predictors
against it:

  1. The deterministic lint baseline — computed live by importing the real
     lint and running it per case. Always available, no judge required.
  2. The LLM judge — if a judge-output JSON is passed with --judge.

It reports a per-case table, precision/recall/F1 on the "not safe to silently
trigger" class ({fail, flag} = positive, pass = negative), per-criterion
accuracy for the judge, and the three headline DoD checks:

  - PASS set has ZERO false-blocks (precision trap)
  - judge-only gap is fully closed (recall beyond the lint)
  - agreement cases don't regress

Usage:
  score.py                          # lint baseline only + self-check of expected.yaml
  score.py --judge out.json         # also grade a judge output
  score.py --check                  # exit non-zero if the lint baseline disagrees
                                     #   with the `lint:` labels in expected.yaml

Judge-output JSON format (what the Phase 1 harness must emit):
  {"results": [
     {"id": "11-duplicate-insert-rollup", "verdict": "fail",
      "criteria": ["idempotent"], "findings": ["...optional free text..."]},
     ...
  ]}
A bare top-level list of those objects is also accepted.
"""
import argparse
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]  # …/specs/validators/triggerable-judge/eval/score.py
EVAL_DIR = Path(__file__).resolve().parent
EXPECTED = EVAL_DIR / "expected.yaml"
LINT_DIR = REPO_ROOT / ".github" / "scripts"

POSITIVE = {"fail", "flag"}  # "not safe to silently trigger"
CRITERIA = {
    "idempotent", "concurrency-tolerant", "time-insensitive",
    "bounded", "quota-safe", "fails-safe",
}

sys.path.insert(0, str(LINT_DIR))
import triggerable_lint as lint  # noqa: E402


def is_pos(verdict):
    return verdict in POSITIVE


def load_cronjob(source):
    path = (REPO_ROOT / source)
    with open(path) as f:
        for doc in yaml.safe_load_all(f):
            if isinstance(doc, dict) and doc.get("kind") == "CronJob":
                return doc
    raise ValueError(f"no CronJob doc in {source}")


def lint_predict(doc, source):
    """Run the real deterministic lint on one case. Returns 'fail' or 'pass'."""
    findings = []
    lint.lint_cronjob(doc, source, findings)
    has_block = any(sev == "error" for sev, *_ in findings)
    return "fail" if has_block else "pass"


def load_judge(path):
    with open(path) as f:
        data = json.load(f)
    results = data["results"] if isinstance(data, dict) else data
    return {r["id"]: r for r in results}


def confusion(cases, predict):
    """predict: id -> verdict. Returns (tp, fp, fn, tn, per_case[])."""
    tp = fp = fn = tn = 0
    per_case = []
    for c in cases:
        exp = c["verdict"]
        pred = predict(c)
        ep, pp = is_pos(exp), is_pos(pred)
        if ep and pp:
            tp += 1; kind = "TP"
        elif not ep and pp:
            fp += 1; kind = "FP"
        elif ep and not pp:
            fn += 1; kind = "FN"
        else:
            tn += 1; kind = "TN"
        per_case.append((c, pred, kind))
    return tp, fp, fn, tn, per_case


def prf(tp, fp, fn):
    p = tp / (tp + fp) if (tp + fp) else 1.0
    r = tp / (tp + fn) if (tp + fn) else 1.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f


def criterion_accuracy(cases, judge):
    """Micro precision/recall over violated-criteria mentions (judge only)."""
    tp = fp = fn = 0
    for c in cases:
        if not is_pos(c["verdict"]):
            continue
        exp = set(c.get("criteria") or [])
        jr = judge.get(c["id"], {})
        got = set(jr.get("criteria") or []) & CRITERIA
        tp += len(exp & got)
        fp += len(got - exp)
        fn += len(exp - got)
    return prf(tp, fp, fn)


def fmt_row(case, pred, kind):
    mark = "ok " if kind in ("TP", "TN") else "XX "
    crit = ",".join(case.get("criteria") or []) or "-"
    return (f"  {mark}{case['id']:<28} exp={case['verdict']:<5} "
            f"pred={pred:<5} [{kind}]  {case['judge_value']:<10} crit={crit}")


def report(title, cases, predict, with_criteria=None):
    tp, fp, fn, tn, per_case = confusion(cases, predict)
    p, r, f = prf(tp, fp, fn)
    print(f"\n=== {title} ===")
    for case, pred, kind in per_case:
        print(fmt_row(case, pred, kind))
    print(f"\n  TP={tp} FP={fp} FN={fn} TN={tn}")
    print(f"  precision={p:.2f}  recall={r:.2f}  F1={f:.2f}")
    if with_criteria is not None:
        cp, cr, cf = criterion_accuracy(cases, with_criteria)
        print(f"  per-criterion: precision={cp:.2f}  recall={cr:.2f}  F1={cf:.2f}")
    return tp, fp, fn, tn, per_case


def dod_checks(cases, predict, label):
    """The three headline checks. Returns list of (name, ok, detail)."""
    checks = []

    pass_set = [c for c in cases if c["judge_value"] == "baseline"]
    false_blocks = [c["id"] for c in pass_set if is_pos(predict(c))]
    checks.append(("no false-blocks on PASS set", not false_blocks,
                   f"{len(false_blocks)} false-block(s): {false_blocks}"))

    judge_only = [c for c in cases if c["judge_value"] == "judge-only"]
    missed = [c["id"] for c in judge_only if not is_pos(predict(c))]
    checks.append(("judge-only gap closed", not missed,
                   f"{len(judge_only) - len(missed)}/{len(judge_only)} caught; missed: {missed}"))

    agreement = [c for c in cases if c["judge_value"] == "agreement"]
    regressed = [c["id"] for c in agreement if not is_pos(predict(c))]
    checks.append(("no regression on agreement cases", not regressed,
                   f"{len(agreement) - len(regressed)}/{len(agreement)} held; regressed: {regressed}"))

    print(f"\n--- DoD checks ({label}) ---")
    for name, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} — {detail}")
    return checks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", help="judge-output JSON to grade")
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if the live lint disagrees with the expected.yaml `lint:` labels")
    args = ap.parse_args()

    spec = yaml.safe_load(EXPECTED.read_text())
    cases = spec["cases"]

    # Pre-load docs + live lint predictions.
    docs = {c["id"]: load_cronjob(c["source"]) for c in cases}
    lint_pred = {c["id"]: lint_predict(docs[c["id"]], c["source"]) for c in cases}

    print(f"Loaded {len(cases)} eval cases from {EXPECTED.relative_to(REPO_ROOT)}")
    print(f"  PASS={sum(1 for c in cases if c['verdict']=='pass')}  "
          f"FAIL={sum(1 for c in cases if c['verdict']=='fail')}  "
          f"FLAG={sum(1 for c in cases if c['verdict']=='flag')}")

    # Self-check: does the live lint match the hand-labelled `lint:` column?
    mismatches = []
    for c in cases:
        expected_lint = "fail" if c["lint"] == "block" else "pass"
        if lint_pred[c["id"]] != expected_lint:
            mismatches.append((c["id"], c["lint"], lint_pred[c["id"]]))
    if mismatches:
        print("\n!! expected.yaml `lint:` labels disagree with the live lint:")
        for cid, labelled, got in mismatches:
            print(f"     {cid}: labelled '{labelled}' but lint says '{got}'")
    else:
        print("  self-check ok: every `lint:` label matches the live lint")

    report("LINT BASELINE (live)", cases, lambda c: lint_pred[c["id"]])
    dod_checks(cases, lambda c: lint_pred[c["id"]], "lint baseline")

    judge_only = [c["id"] for c in cases if c["judge_value"] == "judge-only"]
    print(f"\nJudge-only target (lint misses, judge must catch): {judge_only}")

    rc = 0
    if args.judge:
        judge = load_judge(args.judge)
        missing = [c["id"] for c in cases if c["id"] not in judge]
        if missing:
            print(f"\n!! judge output missing {len(missing)} case(s): {missing}")
        judge_pred = lambda c: judge.get(c["id"], {}).get("verdict", "pass")
        report("LLM JUDGE (alone)", cases, judge_pred, with_criteria=judge)
        dod_checks(cases, judge_pred, "judge alone")

        # What actually ships: the lint and the judge both run on a PR; EITHER
        # one flagging escalates. So the production predictor is lint OR judge.
        # This is what matters — a judge wobble on a case the lint already blocks
        # is harmless, and the judge's real job is the slice the lint can't see.
        def combined_pred(c):
            lp = lint_pred[c["id"]]
            jv = judge.get(c["id"], {}).get("verdict", "pass")
            return "fail" if (is_pos(lp) or is_pos(jv)) else "pass"

        report("COMBINED — lint OR judge (what ships)", cases, combined_pred)
        checks = dod_checks(cases, combined_pred, "combined")
        if not all(ok for _, ok, _ in checks):
            rc = 1

    if args.check and mismatches:
        rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
