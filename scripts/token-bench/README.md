# token-bench — repo-map token-efficiency analytics for the local coding agent

Measures whether the **passive repo-map pattern** actually saves tokens / improves
answer quality for qwen3-coder at 32k context, per the recommendation in
`docs/research/codemap-serena-token-efficiency.md` (no tool in that space publishes
measured savings — this collects our own).

## Design

Repo-navigation Q&A: 8 questions (`questions.jsonl`) whose answers are literal,
grep-verified values in this repo (cron expressions, filenames, namespaces, images).
Each trial is one headless `oc run`; the grader regex-checks the model's answer;
token counts come from opencode's session DB (`~/.local/share/opencode/opencode.db`
`session` table — input/output/reasoning/cache per session), which is why this needs
no LiteLLM admin access.

**Arms:**
- **A — baseline**: question only; model navigates with its normal tools.
- **B — repo-map**: `gen-repomap.mjs` output (token-budgeted structural map:
  yaml kind/name, md headings, script comments; auto-degrades detail to fit
  `--budget`, default 2000 tokens (soft target — collapsed-dir summaries can overshoot slightly)) prepended as a navigation index.
- **G — repo-map + edge index**: adds `gen-edges.mjs` (file-level reference
  graph: secrets, PVCs, Flux dependsOn, TS imports, /api/ fetches — the
  "knowledge cloud").
- **S — repo-map + symbol graph**: adds `gen-symbols.mjs` instead — a
  symbol-level component graph for TS/TSX (which component renders which,
  provider vs consumer, custom-hook origins through barrels, props-type
  extends, per-symbol imports). Subsumes G's import edges on code repos;
  targets "how do classes/components compose" questions
  (`questions-site-components.jsonl`).
- **C — serena**: MCP symbol tools, registered per-trial via `OPENCODE_CONFIG`
  (merges with global config), `.serena/project.yml` seeded, symbol-tool hint.
  Setup details: `serena-prep.md`. **Benchmarked 2026-07-11: 57/57 but
  2.8–4.5× arm S's context — see the research doc; kept for editing-task
  benches, not recommended for navigation.**

## Usage (inside a coding-harness container or anywhere `oc` works)

```sh
node scripts/token-bench/run-bench.mjs --arm A --reps 3   # baseline
node scripts/token-bench/run-bench.mjs --arm B --reps 3   # repo-map
node scripts/token-bench/report.mjs                        # aggregate tables
node scripts/token-bench/gen-repomap.mjs . --budget 2000   # inspect the map
```

Results append to `results/results.jsonl` (one JSON line per trial; committed —
it IS the analytics). Key metric: `ctx = tokens_input + tokens_cache_read`
(total context occupancy) alongside pass rate and wall time. Cache-read is
nearly free in *latency* on the Beelink (prefix caching) but still occupies
context — report both before declaring victory.

## Caveats

- Q&A navigation is a proxy for the real SDD workload (edit tasks); it isolates
  the navigation cost repo-maps target. An edit-task bench needs worktree
  reset between trials — future work.
- Session attribution assumes no concurrent opencode sessions in this container
  during a run.
- Grade regexes are answer-literals that do not appear in the question text.
