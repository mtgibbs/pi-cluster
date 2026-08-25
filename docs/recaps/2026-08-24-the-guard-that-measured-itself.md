# Recap — the guard that started measuring itself (2026-08-24)

A check that had worked correctly for months started giving wrong answers. Nothing about
the check changed. We changed something else, somewhere else, and the check quietly
started answering a different question than the one it was written to answer.

This is what happened and why it was hard to see.

## The guard

`ralph-qwen.sh` runs one task per iteration. After the model finishes, before the gate
runs, there is this:

```sh
if [ -z "$(git -C "$ROOT" status --porcelain 2>/dev/null)" ]; then
    echo "  ✗ attempt $attempt changed nothing — a no-op is a failure, not a pass"
```

Plain English: *if nothing in the repo changed, the model did nothing, so this attempt
failed.*

It exists for a real reason, recorded in the comment above it. On 2026-08-12 the model was
asked to read `/specs/model-watch/spec.md` — an absolute path from filesystem root.
opencode rejected it as an external directory. The model produced no file. The gate at that
point was pend-staged, meaning every check reported "not built yet", which is not a
failure. So the gate passed. The task was marked done. Nothing had been written.

The guard closed that hole. An attempt that changes nothing is a failure.

## The assumption nobody wrote down

`git status` tells you if anything in the repo changed. The guard treats that as "did the
model do work."

Those are only the same thing if **the model is the only thing writing to the repo.**

That was true. It was true for months. It was true by accident — the harness kept its own
files in `~/.harness`, outside every repo it worked on. Attempt logs, status heartbeats,
metrics. None of it in the tree.

Nobody ever wrote that down, because nobody had to. It was just how things were.

## What we changed

We moved the harness's record into the repo it describes.

Good reasons. The old location was unversioned, in `$HOME`, shared by every project on the
machine, and on a deletion timer — three days for logs, one day for status heartbeats.
Fourteen of one project's forty-two runs had already lost their status files to that timer
before anyone noticed. A record that does not travel with the clone is not a record.

So now the harness writes `.evidence/` into the target repo. Status heartbeats, the run
index, the raw transcripts.

Into the tree. The same tree `git status` looks at.

## What broke, first time

A task that was already complete. The model correctly changed nothing — there was nothing
to change. The guard should have caught that and said "no-op."

Instead the guard saw a change and let it through. The change was
`.evidence/status/qwen-21994.json` — the harness's own heartbeat, updated one second
earlier by the harness itself.

The commit that resulted:

```
ralph(qwen): T1 — in scripts/ralph-status.sh make the status sweep configurable ...
 .evidence/status/qwen-21994.json | 1 +
 1 file changed, 1 insertion(+)
```

A task commit whose entire content is the loop's own pulse. The guard asked "did anything
change" and the honest answer was yes. It just had nothing to do with the model.

## What broke, second time

The judge has a preflight:

```sh
[ -z "$(git status --porcelain)" ] || die 1 "worktree not clean (untracked included) — refusing to run"
```

Same shape. Same assumption.

One of the new tasks makes the loop run the indexer after every task, so the record is
written while the raw logs still exist. Sensible on its own. It also means the index file
is modified immediately after the last commit — so the tree is dirty at precisely the
moment the judge starts.

The judge refused to run. Every time. It was correct to refuse; it is fail-closed by
design and a dirty tree genuinely is a reason not to judge. The rule was never wrong. The
tree was dirty for a reason the rule was never told about.

## Why this was hard to see

The gate said **19 PASS / 0 FAIL / 0 pend**.

Every check passed. Nothing was red. The build phase printed "all tasks passed verify —
branch ready for PR review."

We found the first problem by reading a commit and asking what it actually contained. Not
from a check. From `git show`. The answer was one status file.

We found the second because the run exited non-zero and we read the log instead of assuming
the exit code meant what it usually means.

Neither was caught by the thing built to catch problems, because both were problems *in*
the thing built to catch problems. A guard cannot flag its own premise.

## The actual mistake

Not the guard. The guard is fine.

The mistake is that **one measurement was answering two questions**, and only one of them
was the question anyone meant to ask:

- Did the work change?
- Did anything at all change?

Those were the same question right up until they weren't, and the moment they diverged, the
guard kept running and kept returning confident answers.

That is the failure mode worth remembering. Not "the check was wrong." The check was
right, ran fine, and returned an answer. The world underneath it had moved.

## The fix, and the half that is easy to miss

Scope the work question to the work:

```sh
git status --porcelain -- . ':!.evidence'
```

That is the obvious half. Here is the half that is easy to skip:

If you exclude `.evidence/` from the work question and stop there, you have not removed the
blind spot. You have moved it. The indexer is invoked best-effort — `|| WARN` — so if it
silently stops working, nothing notices. The evidence just quietly stops being collected
and every run still looks healthy.

So the second question needs its own answer:

> After a task commits, `.evidence/index.jsonl` must contain a row for that task.

Two questions, two checks. **Collect the metadata, verify you collected it, and never read
it as proof that work happened.**

## What to take from this

**A check inherits assumptions from its environment, and those assumptions are usually
invisible.** The guard's correctness depended on "nothing but the model writes to this
repo." That was never written anywhere. It could not be violated by editing the guard —
only by changing something far away from it.

**Ask what a check would do if it were wrong.** A green check and a check that cannot fail
look identical from the outside. This one could still fail — it just could no longer fail
for the right reason.

**When you move where something writes, audit what reads.** We moved the record into the
repo and thought about durability, gitignore, and size. We did not think about who was
already reading that directory to make decisions. Two things were.

**Instrumentation belongs off the surface it measures**, or every reader of that surface
needs to know to exclude it. We chose to put it on the surface, for good reasons. That
choice comes with an obligation: every check that asks "did the work change" must exclude
`.evidence/`. That is now an invariant with a gate check behind it, because an invariant
without an owner is a lesson you get to learn twice.
