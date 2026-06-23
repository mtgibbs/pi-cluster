#!/usr/bin/env python3
"""Score the dependency-update validator against its eval set.

Single concern: did the validator correctly call each Renovate bump SAFE (pass) or
NEEDS-A-HUMAN (flag)? Advisory — only two verdicts, no fail/block. Positive class =
{flag}. The cost is asymmetric: a missed risky bump (FN) is a bad merge; a false flag
(FP) is one human glance. So recall-on-flag is the hard bar; precision is the comfort bar.

Usage:
  score.py                      # set summary + self-check (no judge needed)
  score.py --judge out.json     # grade a validator output

Validator-output JSON (what the harness emits):
  {"results": [{"id": "postgres-major-migration", "verdict": "flag", "findings": ["..."]}, ...]}
A bare top-level list is also accepted.
"""
import argparse
import json
import sys
from pathlib import Path

import yaml

EXPECTED = Path(__file__).resolve().parent / "expected.yaml"
POSITIVE = {"flag"}            # "needs a human"
VERDICTS = {"pass", "flag"}    # advisory — never fail


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
    n_flag = sum(1 for c in cases if c["verdict"] == "flag")
    print(f"dependency-update eval: {len(cases)} cases — PASS={n_pass} FLAG={n_flag}")

    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), f"duplicate case id(s): {ids}"
    for c in cases:
        assert c.get("verdict") in VERDICTS, f"{c['id']}: bad verdict {c.get('verdict')!r} (advisory = pass|flag)"
        assert c.get("diff"), f"{c['id']}: missing diff"
        assert c.get("file"), f"{c['id']}: missing file"
        assert c.get("changelog"), f"{c['id']}: missing changelog"
    print("  self-check ok: unique ids, every case has a pass|flag verdict + file + diff + changelog")

    if not args.judge:
        print("\n(no --judge given; pass a validator output to grade it)")
        return 0

    judge = load_judge(args.judge)
    missing = [c["id"] for c in cases if c["id"] not in judge]
    if missing:
        print(f"\n!! judge output missing {len(missing)} case(s): {missing}")

    tp = fp = fn = tn = 0
    print("\n=== DEPENDENCY-UPDATE VALIDATOR ===")
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
        print(f"  {mark}{c['id']:<30} exp={exp:<4} pred={pred:<4} [{kind}]")

    p, r, f = prf(tp, fp, fn)
    print(f"\n  TP={tp} FP={fp} FN={fn} TN={tn}")
    print(f"  precision={p:.2f}  recall={r:.2f}  F1={f:.2f}")

    flag_cases = [c for c in cases if c["verdict"] == "flag"]
    missed = [c["id"] for c in flag_cases if not is_pos(judge.get(c["id"], {}).get("verdict", "pass"))]
    pass_cases = [c for c in cases if c["verdict"] == "pass"]
    false_flags = [c["id"] for c in pass_cases if is_pos(judge.get(c["id"], {}).get("verdict", "pass"))]

    # DoD: recall-on-flag MUST be 1.00 (never miss a risky bump); precision >= 0.85.
    recall_ok = not missed
    precision_ok = p >= 0.85
    print("\n--- DoD checks ---")
    print(f"  [{'PASS' if recall_ok else 'FAIL'}] recall-on-flag = 1.00 (every risky bump caught) — missed: {missed or 'none'}")
    print(f"  [{'PASS' if precision_ok else 'FAIL'}] precision >= 0.85 (limit alert fatigue) — false flags: {false_flags or 'none'}")
    return 0 if (recall_ok and precision_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
