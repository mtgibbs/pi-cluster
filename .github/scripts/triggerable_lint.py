#!/usr/bin/env python3
"""Deterministic lint for CronJobs opted in to manual triggering.

A CronJob may carry `homelab.mcp/triggerable: "true"` only if it meets the
triggerable contract (idempotent, concurrency-safe, time-insensitive, bounded,
quota-safe, fails-safe). This lint enforces the *deterministic* slice of that
contract — the parts a static check can prove with high precision. The subtle
idempotency/concurrency reasoning is left to human review (and, later, an
LLM judge).

Findings are emitted as GitHub Actions annotations. Any BLOCK-severity finding
exits non-zero so the PR check fails and a human is brought in.

Usage:
  triggerable_lint.py            # lint only labelled CronJobs (the gate)
  triggerable_lint.py --all      # lint every CronJob (audit mode)
"""
import argparse
import glob
import os
import re
import sys

import yaml

# Shared extraction helpers (this script's dir is on sys.path when run directly).
from cronjob_parse import (
    TRIGGERABLE_LABEL,
    job_spec_of,
    script_text,
    writable_shared_volumes,
)

# BLOCK: destructive operations — re-running, or two overlapping runs, risk
# losing data. (`rm -f <file>` of a temp file is fine and is NOT matched; only
# recursive deletes and mirror-deletes are.)
DESTRUCTIVE = [
    (r"\brm\s+-\w*r\w*", "rm -r* (recursive delete)"),
    (r"-{1,2}delete\b", "`-delete`/`--delete` (rsync mirror / find delete)"),
    (r"\bDROP\s+(TABLE|DATABASE)\b", "SQL DROP"),
    (r"\bTRUNCATE\s+TABLE\b", "SQL TRUNCATE"),
    (r"\bmkfs\b", "mkfs (format)"),
    (r"\bdd\s+if=", "dd (raw write)"),
]
LOCK_HINT = re.compile(r"\bflock\b|coordination\.k8s\.io|\bLease\b", re.IGNORECASE)


def lint_cronjob(doc, path, findings):
    meta = doc.get("metadata", {}) or {}
    ref = f"{meta.get('namespace', '?')}/{meta.get('name', '?')}"
    job_spec = job_spec_of(doc)
    text = script_text(job_spec)

    # #4 bounded -> WARN (hygiene, not blocking)
    if "activeDeadlineSeconds" not in job_spec:
        findings.append(("warning", path, ref,
                         "no activeDeadlineSeconds — job is unbounded; add a deadline so manual triggers can't stack up"))

    # #1/#3 destructive -> BLOCK
    for pattern, label in DESTRUCTIVE:
        if re.search(pattern, text):
            findings.append(("error", path, ref,
                             f"destructive op {label} — overlapping/repeated runs risk data loss; "
                             "prove idempotency and that it's safe to run at any time"))

    # #2 concurrency -> BLOCK: writable shared (NFS/PVC) mount with no visible lock
    shared = writable_shared_volumes(job_spec)
    if shared and not LOCK_HINT.search(text):
        findings.append(("error", path, ref,
                         f"writable shared storage ({', '.join(shared)}) with no visible lock (flock/Lease) — "
                         "two runs can corrupt each other; add a lock or prove concurrency-safety"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="lint every CronJob, not just labelled ones")
    ap.add_argument("--root", default="clusters")
    args = ap.parse_args()

    findings = []
    checked = 0
    for path in sorted(glob.glob(os.path.join(args.root, "**", "*.yaml"), recursive=True)):
        try:
            with open(path) as f:
                docs = list(yaml.safe_load_all(f))
        except Exception:
            continue
        for doc in docs:
            if not isinstance(doc, dict) or doc.get("kind") != "CronJob":
                continue
            labels = (doc.get("metadata", {}) or {}).get("labels") or {}
            if args.all or labels.get(TRIGGERABLE_LABEL) == "true":
                checked += 1
                lint_cronjob(doc, path, findings)

    errors = [f for f in findings if f[0] == "error"]
    warns = [f for f in findings if f[0] == "warning"]

    for sev, path, ref, msg in findings:
        print(f"::{sev} file={path}::[{ref}] {msg}")

    print(f"\nChecked {checked} triggerable CronJob(s): {len(errors)} blocking, {len(warns)} warning(s).")
    if errors:
        print("\nBLOCK: a triggerable CronJob violates the contract — a human must review before merge.")
        return 1
    print("OK: no blocking violations.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
