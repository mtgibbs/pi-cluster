# Loop strategies — named bindings, not new machinery

A strategy is one `.env` file: which phases run, and the operator-layer bindings
they need. The loops themselves (`ralph-qwen.sh`, `ralph-judge.sh`) do not change —
per the judge-loop spec §3, command bindings live at the operator layer, and a
strategy file IS that layer, written down and named.

    scripts/run-loop.sh <strategy> specs/<feature>

Run from a git worktree on a throwaway branch (constitution: worktree rule), same
as invoking the loops by hand.

## The contract

A strategy file may ONLY:
- declare `STRATEGY_DESC` and `STRATEGY_PHASES` (space-separated, run in order)
- export env knobs the loop scripts already accept

It may not define functions, add stopping logic, or invoke anything itself.
New behavior belongs in a loop script, behind its own spec and gate. This keeps
"add a strategy" reviewable at a glance: if a strategy PR touches anything
outside `scripts/loops/`, it is not a strategy PR.

## Current strategies → Loop Library taxonomy

| File | Phases | Library pattern |
|---|---|---|
| `build-converge.env` | build | Generate-Verify-Refine (deterministic gate, bounded change, fresh context per task) |
| `judge-refine.env` | judge | Evaluator/Judge (cross-family: Codex judges, qwen executes, gate arbitrates) |
| `build-then-judge.env` | build judge | the full "basic → evaluator/judge → convergence" modern path |

Comparing strategies on one spec = one worktree per strategy, same spec dir,
diff the branches. The judge phase's `ledger.jsonl` + `report.json` and the
build phase's commit trail are the comparable outputs.

Amendment "Gates must prove they can fail" applies to every strategy: no phase
combination is a substitute for a verify.sh that goes red without the work.
