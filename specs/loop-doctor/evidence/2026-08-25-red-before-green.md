# Red before green — `scripts/loop-doctor.sh`

`specs/amendments.md`, **"Gates must prove they can fail"**. This is the easy case: the gate
existed and had never passed, because the tool it verifies had never been written.

| | RED (spec + gate, no tool) | GREEN (T1–T6 built) |
|---|---|---|
| | 12 FAIL · 35 pend | **51 PASS · 0 pend** |

Excluding `scope:out-of-scope-files-untouched`, which trips by construction on any branch
touching the shared harness and clears on merge.

## The 12 red FAILs were correct, not a gate defect

Worth stating plainly, because I mischaracterised this when I first raised it — I called it
*"a spec gating an unbuilt tool"*, implying the gate was at fault. It wasn't. Its own header
says why:

> **THREE-VERDICT:** T1's deliverable — the script itself — is a hard FAIL when absent, because
> pend-on-your-own-first-deliverable is what scores "built nothing" as green.

So `t1:script-exists` and its eleven companions were *supposed* to be red. They were the gate
correctly reporting **"nothing was built"** for however long nobody looked. The 35 `pend`s
behaved as designed too: each keyed on its own observable, so T2–T6 waited rather than drowning
T1 in noise.

The defect was never the gate. It was that a spec sat fully specified, with a working
acceptance gate, and no one ran the loop against it.

## GREEN

```
51 PASS / 1 FAIL / 0 pend       (the 1 is the by-construction scope guard)
STRICT=1: 0 pend
```

## Proof on the live corpus, not just fixtures

Fixtures prove the rules; the corpus proves the tool. Run against this container's real
`~/.harness`:

```
qwen-104327  loop-run3          specs/model-watch  phase=stopped  fault=verify-fail   T2-attempt3.diff present
qwen-87045   loop-run2          specs/model-watch  phase=done     fault=done          phase=done
qwen-19312   loop-model-watch   specs/model-watch  phase=running  fault=dead          heartbeat stale 1193879s (phase=running)
qwen-17812   loop-model-watch   specs/model-watch  phase=running  fault=dead          heartbeat stale 1195372s (phase=running)
```

The last two are the point of the whole spec. Their heartbeats have read `running` for
**fourteen days**. `ralph-status.sh` states the liveness rule in its own header — *"phase
running|verifying with `updated` more than a few minutes old is a DEAD loop"* — and until now
nothing applied it. Two dead loops sat looking busy, and the only reason anyone would have
noticed is by opening the files by hand.

## Both storage layouts

The stores gained a per-spec level in #197; the spec text predates it and names the flat shape.
Rather than encode either, the discovery searches. Verified against a nested fixture with a
codex-prefixed run:

```
codex-9001  fixture-repo  specs/v1  phase=stopped  fault=watchdog-kill  … 22540 Killed: 9 …
```

A reader that only understands today's layout goes blind on the corpus it was built to explain.

## One defect the gate caught in this implementation

`t1:no-declare-A-bash32` failed on the first run — because the script's own header comment said
*"no `declare -A`"*, and that check greps the file's **raw text**, not comment-stripped code.

That is the gate being right and the comment being careless. Unlike `ac15`, which deliberately
strips comments first (a false negative caught 2026-08-18 when it fired on a header merely
naming `verify.sh`), this check wants the raw text: a bash-3.2 incompatibility is a
bash-3.2 incompatibility whether or not it is commented out today, and a commented-out builtin
is one uncomment away from breaking macOS. The comment was reworded; the check was left alone.
