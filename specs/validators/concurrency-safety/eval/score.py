#!/usr/bin/env python3
"""Score the concurrency-safety validator against its eval set.

Single concern: did the validator correctly call each diff a concurrency-safety
violation or not? Positive class = "not safe to merge as-is" = {fail, flag};
pass = negative.

Usage:
  score.py                      # set summary (counts; no judge needed)
  score.py --judge out.json     # grade a validator output

Validator-output JSON (what the harness emits):
  {"results": [
     {"id": "remove-guard-a", "verdict": "fail", "findings": ["..."]},
     ...]}
A bare top-level list is also accepted.
"""
import argparse
import json
import sys
from pathlib import Path

import yaml

EXPECTED = Path(__file__).resolve().parent / "expected.yaml"
POSITIVE = {"fail", "flag"}
VERDICTS = {"pass", "fail", "flag"}


def is_pos(v):
    return v in POSITIVE


def load_judge(path):
    data = json.load(open(path))
    results = data["results"] if isinstance(data, dict) else data
    return {r["id"]: r for r in results}


def prf(tp, fp, fn):
    p = tp / (tp + fp) if (tp + fp) else 1.0
    r = tp / (tp + fn) if (tp + fn) else 1.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", help="validator-output JSON to grade")
    args = ap.parse_args()

    cases = yaml.safe_load(EXPECTED.read_text())["cases"]
    n_pass = sum(1 for c in cases if c["verdict"] == "pass")
    n_fail = sum(1 for c in cases if c["verdict"] == "fail")
    n_flag = sum(1 for c in cases if c["verdict"] == "flag")
    print(f"concurrency-safety eval: {len(cases)} cases — "
          f"PASS={n_pass} FAIL={n_fail} FLAG={n_flag}")
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    for c in cases:
        assert c.get("verdict") in VERDICTS, f"{c['id']}: bad verdict {c.get('verdict')!r}"
        assert c.get("diff"), f"{c['id']}: missing diff"
        assert c.get("file"), f"{c['id']}: missing file"
    print("  self-check ok: every case has a unique id, known verdict, file + diff")

    if not args.judge:
        print("\n(no --judge given; pass a validator output to grade it)")
        return 0

    judge = load_judge(args.judge)
    missing = [c["id"] for c in cases if c["id"] not in judge]
    if missing:
        print(f"\n!! judge output missing {len(missing)} case(s): {missing}")

    tp = fp = fn = tn = 0
    print("\n=== CONCURRENCY-SAFETY VALIDATOR ===")
    for c in cases:
        exp = c["verdict"]
        pred = judge.get(c["id"], {}).get("verdict", "pass")
        ep, pp = is_pos(exp), is_pos(pred)
        if ep and pp:
            tp += 1; kind = "TP"
        elif not ep and pp:
            fp += 1; kind = "FP"
        elif ep and not pp:
            fn += 1; kind = "FN"
        else:
            tn += 1; kind = "TN"
        mark = "ok " if kind in ("TP", "TN") else "XX "
        print(f"  {mark}{c['id']:<34} exp={exp:<5} pred={pred:<5} [{kind}]")

    p, r, f = prf(tp, fp, fn)
    print(f"\n  TP={tp} FP={fp} FN={fn} TN={tn}")
    print(f"  precision={p:.2f}  recall={r:.2f}  F1={f:.2f}")

    pass_cases = [c for c in cases if c["verdict"] == "pass"]
    fp_ids = [c["id"] for c in pass_cases if is_pos(judge.get(c["id"], {}).get("verdict", "pass"))]
    fail_cases = [c for c in cases if c["verdict"] == "fail"]
    missed = [c["id"] for c in fail_cases if not is_pos(judge.get(c["id"], {}).get("verdict", "pass"))]
    print("\n--- DoD checks ---")
    print(f"  [{'PASS' if not fp_ids else 'FAIL'}] no false-blocks on safe diffs — {fp_ids or 'none'}")
    print(f"  [{'PASS' if not missed else 'FAIL'}] every violation caught — missed: {missed or 'none'}")
    return 0 if (not fp_ids and not missed) else 1


if __name__ == "__main__":
    sys.exit(main())
