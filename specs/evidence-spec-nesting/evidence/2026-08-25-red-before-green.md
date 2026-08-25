# Red before green — `specs/evidence-spec-nesting/verify.sh`

`specs/amendments.md`, **"Gates must prove they can fail"** (Accepted 2026-08-10): a `verify.sh`
check must be shown to go RED without the change it verifies. A check that has never failed
proves presence, not correctness.

This gate was written **after** its implementation (#197), so the red run is against a pinned
commit rather than an unbuilt tree. Pin it explicitly: once #197 merges, `origin/main` is green
and this transcript is only reproducible at the ref below.

| | |
|---|---|
| **RED at** | `e669455` — *fix(harness): the loop wrote its record where nothing could read it (#196)*, the commit immediately before #197 |
| **GREEN at** | `77c185b` — *feat(harness): file run evidence under the spec* |
| **Reproduce** | `git worktree add /tmp/pre197 --detach e669455 && cp -r specs/evidence-spec-nesting /tmp/pre197/specs/ && cd /tmp/pre197 && bash specs/evidence-spec-nesting/verify.sh` |

## RED — `e669455`

```
  PASS  scope:no-litter-in-spec-dir
  FAIL  AC-1:runs-nested-under-slug — run dir is still flat in the root — no spec level
  FAIL  AC-2:status-nested-under-slug — status file is still flat in the root — no spec level
  PASS  AC-3:leaf-carries-no-slug
  PASS  AC-4:index-recovers-pid
  FAIL  AC-8:index-sees-codex — the codex run (pid=2701664) has no attempt logs in the index — store 3 enumeration is executor-specific
  FAIL  AC-9:index-names-real-dir — rendered the codex run as qwen-2701664 — a path that does not exist
  FAIL  AC-5:aged-spec-keeps-fresh-runs — 2 of 2 fresh runs were deleted because their SPEC directory aged out — the sweep is reaping at the feature level
  PASS  AC-6:prunes-empty-keeps-live
  FAIL  AC-7:override-root-verbatim — the override root was used but the slug level is missing beneath it
  PASS  AC-10:twins-share-the-helpers

evidence: 4 negative-invariant · 7 executing · 4 presence
score: 9 PASS / 6 FAIL / 0 pend
```

## GREEN — `77c185b`

```
evidence: 4 negative-invariant · 7 executing · 4 presence
score: 15 PASS / 0 FAIL / 0 pend
```

`STRICT=1` likewise: 0 pend, 0 FAIL.

## What the six red marks each prove

| AC | Proves |
|---|---|
| AC-1 / AC-2 | the layout genuinely changed — runs and heartbeats were flat in the root |
| AC-5 | **the cliff.** An aged spec directory took *both* of its fresh runs with it. This is the one that would silently destroy history |
| AC-7 | the slug level is absent beneath an explicit `RALPH_*_DIR`, so the seam alone was not enough |
| AC-8 | a codex run's transcripts existed on disk and the index counted **zero** attempt logs for it |
| AC-9 | worse than invisible — the index *named* the codex run `qwen-<pid>`, a path that does not exist, sending a reader somewhere real-looking and wrong |

## The four that stay green on both sides, and why that is stated rather than hidden

AC-3, AC-4, AC-6 and AC-10 are **invariant guards**. They pass before and after; they exist to
catch a *future* regression, and counting them as evidence for this change would be exactly the
false-green the amendment was written against.

**AC-4 is the counter-intuitive one.** It would be easy to assume "the index can read a nested
tree" must be red beforehand. It is not: `harness_roots()` already descended exactly one level —
it was built for #194's `~/.harness/<repo>/` scoping — so the old indexer read a nested *qwen*
tree correctly. AC-4's real job is as the SG-1 tripwire: it asserts the recovered pid is the
bare number, so folding the slug into the leaf name (`qwen-asset-ladder-37173`, the tempting
"smaller" change) makes the pid `asset-ladder-37173` and trips it.

## Two checks rewritten to earn that classification

The first draft of this gate produced **8** red marks, not 6. AC-3 and AC-6 reused the nested
fixture's depth-2 lookup, so against a flat tree they failed reporting `leaf 'none'` and a
self-deletion bug that does not exist at `e669455`. Both were red for "the layout is flat" —
which is AC-1's sentence to speak — rather than for anything they assert.

Both now search at any depth. Two fewer red marks, and the remaining six each mean what they
say. **A gate that fails for the wrong reason is worse than one that does not fail at all: it
teaches the reader to discount it**, and a discounted gate is how a real regression gets waved
through.
