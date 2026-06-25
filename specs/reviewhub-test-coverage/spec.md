# Spec: review-hub validator unit-test coverage

- **Status:** Planned
- **Owner:** Matt / Claude (orchestration); qwen (executor)
- **Constitution:** `specs/constitution.md` (+ `/CLAUDE.md` Core Mandates)
- **Touches:** `scripts/reviewhub/validators/test_<validator>.py` (NEW, one per validator) — nothing else

---

## 1. Why · [R — Requirements]
review-hub now gates every PR but is almost entirely untested (one test file). Each validator is a
single-concern specialist whose **pure logic** — file routing, verdict parsing, vote aggregation, PR
rendering — decides whether a PR is flagged. A bug there silently mis-gates. This adds unit tests for
that pure logic, one file per validator.

## 2. Outcomes (Definition of Done) · [R]
1. Each of the 9 remaining validators has `scripts/reviewhub/validators/test_<name>.py`.
2. Each tests the five pure functions: `build_prompt`, `parse`, `aggregate`, `_render_pr`, `applies_files`.
3. `verify.sh` is green: pytest passes; each file imports its module, has ≥10 tests, exercises ≥4/5 functions.
4. No validator source file is modified.

## 3. Entities · [E — Entities]
Each validator module `scripts/reviewhub/validators/<name>.py` exposes (ALL network-free):
- `build_prompt(changes, changelog) -> str` — substitutes `{{INPUT}}` in its `contract.md` template.
- `parse(text) -> {"verdict": ..., "findings": [...]}` — extracts JSON between `BEGIN`/`END` markers
  (re-exported: `from <name> import BEGIN, END`); **last marker pair wins**; bad markers/json/verdict → `error`.
- `aggregate(runs) -> {"verdict","runs","escalating","stable","findings"}` — majority escalation
  (`min_to_block = len(runs)//2 + 1`; flag/error count as escalating). **CHECK each validator's actual rule.**
- `_render_pr(res) -> str` — markdown; headline keys on `res["verdict"]`; includes `comment_marker("<name>")`.
- `<Name>Validator.applies_files(files) -> bool` — `fnmatch` over `self.globs`.
NOT tested: `review()` (LLM), `main()` (CLI).

## 4. Approach · [A — Approach]
**Mirror the WORKED EXAMPLE exactly:** `scripts/reviewhub/validators/test_dependency_update.py` (already
written, 24 passing tests). Same import style (`from <name> import ...`, resolved by the dir's
`conftest.py`), same class layout (one `Test*` class per function), same kinds of cases. **Read each
validator's real source** for its verdict set, globs, and aggregation rule — they DIFFER per validator;
do NOT assume dependency-update's values.

## 5. Scope · [S — Structure]
### In scope
NEW `test_<name>.py` for: `concurrency_safety`, `fail_closed`, `gate_regression`, `input_validation`,
`mutation_gating`, `no_false_green`, `output_bounds`, `read_only_integrity`, `secret_hygiene`.
(`dependency_update` is the done worked example.)
### Out of scope
Any validator source `.py`, `__init__.py`, `conftest.py`, `triggerable_judge.py`, `review()`/`main()`,
the engine functions (separate spec), and anything that touches the network or an LLM.

## 6. Prior facts the implementer must know · [S]
- Imports resolve via the dir's `conftest.py` — just `from <name> import build_prompt, parse, aggregate,
  _render_pr, <Name>Validator, BEGIN, END`.
- `parse`'s valid verdicts DIFFER — read the `if verdict not in (...)` line (most are `(pass, flag)`; CHECK).
- `applies_files` globs DIFFER — read `self.globs`; assert one real MATCHING path and one real NON-matching path.
- `aggregate`'s threshold may differ — read it; test the real numbers.
- `fnmatch` `*` spans `/` here (so `clusters/pi-k3s/*` matches nested paths).
- `comment_marker("<name>")` → `<!-- review-hub:<name> -->`.
- Pattern to copy: `test_dependency_update.py`; reuse its `_verdict_text(verdict, findings)` helper shape.

## 7. Norms · [N — Norms]
- One `Test*` class per function. Descriptive `test_<behavior>` names. ≥2 cases/function incl. an edge
  case (missing markers; minority vote; non-matching path; empty input).
- Assert real return shapes/values read from the code. **Never `assert True`.** No network, no mocking.

## 8. Safeguards · [S — Safeguards]
- NEVER modify a non-test file (only create `test_*.py`). [verify: only NEW test files in the diff]
- NEVER import/call `review()`, `judge_changes`, `run_model`, or anything network. [verify: pytest is offline]
- Tests must PASS, ≥10 per file across ≥4 of the five functions. [verify.sh]

## 9. Task breakdown · [O — Operations]
One validator per task — see `tasks.txt`. Each is independent; mirror the worked example.

## 10. Acceptance criteria (EARS) · [O]
- The system shall provide `test_<name>.py` for each in-scope validator.
- When the suite runs, pytest shall exit 0.
- Each `test_<name>.py` shall `from <name> import` its module, define ≥10 `def test_` functions, and
  reference ≥4 of {`build_prompt`,`parse`,`aggregate`,`_render_pr`,`applies_files`}.
- If a validator's verdicts / globs / aggregation differ from dependency-update's, then the tests shall
  assert THAT validator's real values (read from its source).
- The system shall NOT modify any non-test file.

## 11. Verification — `verify.sh`
`specs/reviewhub-test-coverage/verify.sh` — pytest-green + per-file structural gate, cumulative-safe
(checks only the test files that exist, so it passes incrementally as the loop adds one per task).

## 11b. Loop execution
`scripts/ralph-qwen.sh specs/reviewhub-test-coverage`, run from inside a worktree on a throwaway branch.
One task per iteration, fresh context, timeboxed, verify-gated, retry-with-feedback, stop-for-human.

## 12. Open questions
- None blocking — the worked example resolves the pattern; per-validator values are read from source.
