# Fabro examples — reference material

Nothing in this directory is applied to the cluster. Flux reads `../secrets` and `../server` only;
these files are here to be read, copied and submitted by hand (see ../README.md, "Starting a run").

## `gated-build-v2/workflow.fabro`

The workflow that was run end to end against the prototype pod, committed unchanged. It is a DOT
graph: plan → human approval → implement → `pytest` → collect diff → LLM judge, with a bounded fix
loop and a human escalation gate when the automatic checks do not settle.

Read these before reusing it:

- **Its goal is specific** to `mtgibbs/factory-trial` (add `top_words` to the `textkit` package).
  Change the `goal` graph attribute, or pass `--goal`, for anything else.
- **It was proven with a different sandbox image.** The prototype ran it in a locally built image:
  `python:3.12-bookworm` plus `pip install pytest`. The cluster's `gated-docker` environment uses
  stock `python:3.12-bookworm`, which has no pytest, so the `verify` stage (`python3 -m pytest -q`)
  fails there until the target repository installs it — for example by changing `verify`'s script
  to `python3 -m pip install -q pytest && python3 -m pytest -q` (pip reaches PyPI over 443, which
  the sandbox may use). That variant has **not** been run.
- **It was proven with pushing switched off.** The prototype server set `[run.run_branch] push =
  false` and `[run.pull_request] enabled = false`. This cluster's server leaves both at Fabro's
  defaults, so the same workflow here **pushes** the run branch `fabro/run/<run-id>` to the target
  repository after each stage. It still opens no pull request: that needs
  `[run.pull_request] enabled = true` in a `workflow.toml` beside the graph.
- It has two human gates (`approve_plan`, `escalate`). A run waits at them until someone answers
  in the UI or through the questions API, unless the run was started with `--auto-approve`.
