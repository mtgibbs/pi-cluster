# Red-before-green — `specs/run-regression-guard/verify.sh`

Compiled 2026-08-18, run **before any implementation exists**, per the ratified amendment
"Gates must prove they can fail".

## Structure

- **Unit tier** (AC1-AC6) — drives the helper directly, on **`/bin/bash` specifically**
  (`GNU bash 3.2.57`). The defect under test does not reproduce on Homebrew's bash 5, so a gate
  that ran on `bash` from `PATH` would be green against broken code on most developer machines.
- **Integration tier** (AC7-AC11) — a real `ralph-qwen.sh` run in a throwaway git repo, mock `oc`
  first on `PATH`, two-task inner spec whose `alpha` check is **presence-gated on `a.txt`** so
  deleting the file makes it PEND rather than FAIL. That is the `qwen-10668` signature exactly,
  and the case a failed-only rule would miss.

## Pre-implementation

```
7 PASS, 19 pend, exit 0  ;  STRICT=1 -> exit 1
```

The seven passes are the scope checks and **AC10, the happy-path guard** — two tasks, three
commits, both artifacts present. AC10 passing *before* any fix is the load-bearing signal: the
mock harness really drives a ralph run, so a later green cannot be an artefact of a broken
harness.

## The defects, reproduced by machine

Forcing the T1 and T2/T3 presence-gates open against the **current, unmodified** code:

```
FAIL  ac1:three-run-scoped-functions
FAIL  ac2:no-regressions-silent-on-stderr
      — got 'ralph-retry.sh: line 41: regressions[@]: unbound variable'
FAIL  ac2:no-regressions-returns-0
FAIL  ac3:pend-counts-as-regression
FAIL  ac7:destroying-task-not-committed — 3 commits, want 2 (base + T1)
FAIL  ac8:regression-heading-in-next-prompt / names-regressed-check / names-owning-task
FAIL  ac9:stop-message-names-the-cause / stop-line-names-destroying-task / evidence-preserved
FAIL  ac11:twins-do-not-drift
```

Two of those are the whole point:

- **`ac2` catches the live bash 3.2 bug** — verbatim, including the misleading `line 41`
  attribution (the offending expansion is line 58; bash 3.2 blames a function's opening line).
- **`ac7 — 3 commits, want 2`** is `qwen-10668` reproduced in seconds. Under the current loop the
  task that deleted an earlier task's work **commits successfully**.

## A false positive, caught the same way — the third of the session

`ac9` began as *"does the loop log contain `T2`?"* and **passed against the unfixed loop**: every
task banner already echoes `T2`. It was asserting nothing.

Fixed by scoping the grep to the STOP line itself.

This is now the **third** time in three specs that running a gate against known-bad code exposed
a check passing for the wrong reason:

| Spec | The check that lied | Why it passed |
|---|---|---|
| loop-doctor | `ac15:no-forbidden-invocations` | matched the word in a **comment** |
| ralph-retry-contract | `ac9:regressed-check-named` | the FAIL feedback already contained the name |
| run-regression-guard | `ac9:stop-names-destroying-task` | the task banner already contained the label |

All three share one shape: **a whole-artifact grep for a token the artifact already contains for
unrelated reasons.** The fix is always the same — scope the search to the region the feature is
supposed to produce. Worth promoting to a gate-authoring norm in `specs/TEMPLATE.md`.
