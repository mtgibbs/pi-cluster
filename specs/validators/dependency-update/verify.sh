#!/usr/bin/env bash
# Static gate for the dependency-update validator (§11). Offline, deterministic, no imports.
# The EVAL (score.py against the live judge) is the behavioural gate; this checks structure +
# the advisory invariant that a static read can confirm.
set -u
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"

exec python3 - "$ROOT" <<'PY'
import re, sys
from pathlib import Path
root = Path(sys.argv[1])
fails = []
def chk(name, cond):
    print(("  ok   - " if cond else "  FAIL - ") + name)
    if not cond:
        fails.append(name)

val = (root / "scripts/reviewhub/validators/dependency_update.py").read_text()
contract = (root / "specs/validators/dependency-update/contract.md").read_text()
expected = (root / "specs/validators/dependency-update/eval/expected.yaml").read_text()
init = (root / "scripts/reviewhub/validators/__init__.py").read_text()
optin = (root / ".review-hub.yml").read_text()
tj = (root / "scripts/triggerable_judge.py").read_text()

# --- validator structure ---
chk("class DependencyUpdateValidator", "class DependencyUpdateValidator" in val)
chk("name = 'dependency-update'", 'name = "dependency-update"' in val)
for attr in ("concern =", "repos =", "globs =", "def applies_files", "def review"):
    chk(f"has {attr.strip()}", attr in val)

# --- ADVISORY INVARIANT (the safeguard) ---
# review() must never return a truthy any_block: both its returns end in ", False, ...".
# review() is the class's LAST method, so bound its body at the next MODULE-level def/class
# (a 4-space `def` boundary would never match and would bleed into main()'s `return 0`s).
_after = val.split("def review", 1)[1] if "def review" in val else ""
review_body = re.split(r"\n(?:def |class )", _after)[0]
returns = re.findall(r"return\s+(.+)", review_body)
chk("review() returns are advisory (2nd value False on every path)",
    bool(returns) and all(re.search(r",\s*False\s*,", r) for r in returns))
chk("res['block'] hard-set False (advisory)", re.search(r'res\["block"\]\s*=\s*False', val) is not None)
chk("verdicts restricted to pass|flag (no 'fail')",
    '("pass", "flag")' in val and '"fail"' not in val)

# --- contract.md ---
chk("contract.md has {{INPUT}}", "{{INPUT}}" in contract)
chk("contract.md uses the verdict markers", "===VERDICT-BEGIN===" in contract and "===VERDICT-END===" in contract)
chk("contract.md verdicts are pass|flag only", "fail" not in contract.lower().replace("fail/block", ""))

# --- eval set (no yaml import: text checks) ---
verdicts = re.findall(r"^\s*verdict:\s*(\w+)", expected, re.M)
chk("eval has cases", len(verdicts) >= 8)
chk("eval verdicts all pass|flag (advisory)", all(v in ("pass", "flag") for v in verdicts))
chk("eval has both classes", "pass" in verdicts and "flag" in verdicts)
chk("every eval case has a changelog", expected.count("changelog:") == len(verdicts))

# --- wiring ---
chk("registered: import in __init__", "from dependency_update import DependencyUpdateValidator" in init)
chk("registered: in REGISTRY", "DependencyUpdateValidator()" in init)
chk("opted in: .review-hub.yml lists dependency-update", re.search(r"-\s*dependency-update", optin) is not None)

# --- framework addition ---
chk("triggerable_judge defines pr_meta", "def pr_meta" in tj)

print()
if fails:
    print("VERIFY FAIL (%d)" % len(fails)); sys.exit(1)
print("VERIFY PASS"); sys.exit(0)
PY
