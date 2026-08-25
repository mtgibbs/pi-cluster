# Spec: file run evidence under the spec it was produced for

- **Status:** Done v1.0
- **Owner:** mtgibbs
- **Constitution:** `specs/constitution.md` (+ `/CLAUDE.md` Core Mandates)
- **Touches:** `scripts/ralph-log.sh`, `scripts/ralph-status.sh`, `scripts/loop-index.py`

> **Retrofit, stated honestly.** The implementation landed first (#197); this spec and its gate
> were written after. That is the defect this document exists to close, not a pattern to copy —
> `specs/amendments.md` "Gates must prove they can fail" is the standard, and a change that
> ships with throwaway fixtures leaves nothing behind to catch a regression. The spec is
> therefore written **generatively**: it must be possible to rebuild #197 from §9 + §10 alone,
> and §11's gate is proven red against `e669455` (the commit before #197) in
> `evidence/2026-08-25-red-before-green.md`. If this reads as a changelog rather than as
> instructions, it has failed.

---

## 1. Why · [R — Requirements]

The evidence tree is append-mostly and is meant to outlive the runs inside it, but every
artefact was keyed by PID alone in one flat directory. Five specs over one night left **48
sibling `qwen-<pid>` directories** whose only link to a feature lived in a *different* store —
`.evidence/status/`, swept on a 1-day fuse while the transcripts it indexes live for 3.
`loop-index.py`'s own docstring records the cost: *"14 of this project's 42 runs had already
lost their status file to it before anyone noticed."* Once that file is gone, PID → spec is
unrecoverable except from an index someone remembered to regenerate.

At a few hundred runs a flat root is also simply unreadable, and every consumer pays to
enumerate the whole store to answer a question about one feature.

## 2. Outcomes (Definition of Done) · [R — Requirements]

1. Every run artefact is filed under the spec it was produced for, discoverable by walking down
   rather than by joining against another store.
2. Expiry removes whole runs, never a whole feature's history.
3. Both executors (`qwen`, `codex`) are equally visible to the index.
4. No existing reader of the evidence tree needs to change.

## 3. Entities · [E — Entities]

**spec slug** — a single filename-safe path component derived at runtime from `SPEC_DIR`:
basename, lowercased, non-`[a-z0-9._-]` collapsed to `-`, runs of `-` squeezed, leading `-.`
and trailing `-` stripped, truncated to 40 chars, empty → `nospec`.
`specs/Asset Ladder/` → `asset-ladder`.

**run directory** — `<agent>-<pid>`, where `agent` is `RALPH_AGENT` (`qwen` | `codex`) and
`pid` is the executor shell's `$$`. Contains `<task>-attempt<n>.{log,diff}`.

**the layout**

```
<target-repo>/.evidence/
├── runs/<spec-slug>/<agent>-<pid>/<task>-attempt<n>.{log,diff}   GITIGNORED (bulky)
├── status/<spec-slug>/<agent>-<pid>.json                          COMMITTED
├── judge/<spec>/{ledger.jsonl,report.json}                        COMMITTED
├── supervisor/<spec>/…                                            COMMITTED
└── index.md · index.jsonl · metrics.jsonl                         COMMITTED, derived
```

## 4. Approach · [A — Approach]

Add one directory level, keyed by the spec slug, to the two stores that lacked it — mirroring
the key `judge/<spec>/` and `supervisor/<spec>/` already use (`#196` D6). The slug is derived by
a `_ralph_slug` helper duplicated verbatim in both sourced helpers, because each must stay
independently sourceable (either may be absent without breaking the loop), so neither may depend
on the other.

**Rejected: folding the slug into the leaf name** (`qwen-asset-ladder-37173`). It reads as the
smaller change and is the more dangerous one — see §8 SG-1. Nesting changes the path and leaves
every existing parser untouched.

## 5. Scope · [S — Structure: boundary]

### In scope
- `scripts/ralph-log.sh` — slug level, sweep depth, empty-dir prune
- `scripts/ralph-status.sh` — slug level, sweep rooted above it
- `scripts/loop-index.py` — executor-agnostic enumeration, record fidelity

### Out of scope
- **`RALPH_STATUS_KEEP_MIN`'s 1440 default.** Pinned by `specs/evidence-convention` AC-4 and
  asserted as a literal by its gate. `.evidence/status/` is committed *and* swept daily, which
  is a live contradiction — it belongs to `specs/status-retention`, not here.
- `scripts/ralph-judge.sh`, `supervise.sh`, `ralph-retry.sh`
- Migrating any evidence tree that already exists. Both layouts are readable (§6).

## 6. Prior decisions / facts the implementer must know · [S — Structure]

- `harness_roots()` in `loop-index.py` **already descends exactly one level** and already skips
  entries prefixed `qwen-`/`codex-` as run dirs rather than scopes. It was built for #194's
  `~/.harness/<repo>/` layout and needs no change to discover this one. The scope level simply
  carries whatever the writer scoped by — repo there, spec slug here.
- `scripts/harness` already globs **both** `status/*.json` and `status/*/*.json` (#194).
- `ralph-status.sh`'s sweep has no `-maxdepth`, so it is already recursive.
- `specs/evidence-convention` AC-1's gate reads the **first** `HB_DIR=` line and requires the
  `${RALPH_STATUS_DIR:` override seam and the `.evidence/status` default to be visible *on that
  line*. Assign the root to `HB_DIR` first, then descend — or that gate fails on a change that
  is semantically correct.
- `specs/evidence-convention` AC-5 forbids any project's name appearing in a `scripts/loop-*`
  file. The slug is derived from `SPEC_DIR` at runtime and is never a literal.

## 7. Norms · [N — Norms]

- Both helpers stay **best-effort**: a full disk, missing `$HOME` or read-only mount can never
  fail the loop they report on. Every write guarded, `|| true`.
- `_ralph_slug` is duplicated verbatim in both files, with a comment in each saying so and why.
  Keep the copies identical.
- Comments explain *why*, anchored to the observed failure, in the voice of the surrounding
  file.

## 8. Safeguards · [S — Safeguards]

- **SG-1 — the leaf name is `<agent>-<pid>` and nothing else.** `loop-index.py` recovers the pid
  with `basename(d).split("-", 1)[1]`; `scripts/harness` globs the leaf. Folding the slug in
  yields a pid of `asset-ladder-37173`, which matches no status file — and the index still
  generates, with every run silently unattributed. A wrong implementation here is *quiet*.
  → AC-3, AC-4.
- **SG-2 — expiry is per run, never per spec.** A directory's mtime tracks its newest child, so
  a depth-1 sweep makes an active feature look immortal and then deletes its entire history the
  moment it goes quiet. → AC-5.
- **SG-3 — an explicit `RALPH_LOG_DIR`/`RALPH_STATUS_DIR` is used verbatim as the root.** Every
  gate in this repo redirects these into `$TMPDIR`; breaking the seam breaks them all. → AC-7.
- **SG-4 — the twins do not drift.** Anything true of `ralph-qwen.sh` is true of
  `ralph-codex.sh`. → AC-10.

## 9. Task breakdown · [O — Operations]

- **T1** — slug level in both helpers (`_ralph_slug`, `LOG_DIR`, `HB_DIR`), honouring §6's
  `HB_DIR=` ordering constraint.
- **T2** — sweep depth and prune: `-mindepth 2 -maxdepth 2` in `ralph-log.sh`, status sweep
  rooted above the slug, `-type d -empty -delete` after each. Ordering differs between the two
  files — see AC-6.
- **T3** — `loop-index.py`: enumerate both executors, carry `agent`/`run_dir`/`spec` through the
  record, stop rebuilding names from a hardcoded prefix.

## 10. Acceptance criteria (EARS) · [O — Operations made testable]

- **AC-1** When a loop initialises logging, the system shall create the attempt directory at
  `<log-root>/<spec-slug>/<agent>-<pid>/`.
- **AC-2** When a loop initialises its heartbeat, the system shall write the status file at
  `<status-root>/<spec-slug>/<agent>-<pid>.json`.
- **AC-3** The run directory's leaf name shall consist of exactly `<agent>-<pid>`; the spec slug
  shall not appear in it. *(SG-1)*
- **AC-4** When `loop-index.py` indexes a nested tree, it shall recover each run's numeric pid
  and shall attribute the run's attempt logs to it. *(SG-1)*
- **AC-5** If a spec directory's mtime has aged past `RALPH_LOG_KEEP_MIN` while a run inside it
  has not, then the system shall retain that run and its spec directory. *(SG-2)*
- **AC-6** When a sweep empties a spec directory, the system shall remove it; and the sweep
  shall never remove the directory the current run is about to write into.
- **AC-7** Where `RALPH_LOG_DIR` or `RALPH_STATUS_DIR` is set, the system shall use it verbatim
  as the root and place the spec slug beneath it. *(SG-3)*
- **AC-8** When `loop-index.py` enumerates run directories, it shall discover `codex-` prefixed
  runs equally with `qwen-` prefixed ones.
- **AC-9** When the index renders a run's name, it shall render the directory that exists on
  disk, and shall not compose a name from a hardcoded executor prefix.
- **AC-10** Both `ralph-qwen.sh` and `ralph-codex.sh` shall obtain this behaviour from the
  shared helpers; neither shall define its own evidence pathing. *(SG-4)*

## 11. Verification (the harness)

`specs/evidence-spec-nesting/verify.sh` — STATIC, hermetic, three-verdict, `STRICT=1` promotes
pend. Every check builds a throwaway git repo under `$TMPDIR`, sources the helpers directly and
redirects both roots into it; it never touches the operator's `.evidence/` or `~/.harness/`.

Scored by evidence class, and the two sets are kept honestly apart.

**Discriminating — red at `e669455`, green after (6):** AC-1, AC-2 (layout), AC-5 (SG-2,
cliff-deletion), AC-7 (slug level under an explicit root), AC-8, AC-9 (codex visibility).
Transcript: `evidence/2026-08-25-red-before-green.md`.

**Invariant guards — green on both sides (4):** AC-3, AC-4, AC-6, AC-10. They protect the design
against a future regression; they are not evidence *for* this change and are not counted as
such.

**AC-4 belongs in the second group, which is worth stating because it is counter-intuitive.**
`harness_roots()` already descended one level (§6), so the old indexer read a nested *qwen* tree
correctly and AC-4 passes at `e669455`. Its value is as the SG-1 tripwire: it asserts the
recovered pid is the bare number, so folding the slug into the leaf — the tempting "smaller"
change — turns the pid into `asset-ladder-<pid>` and trips it. A check that guards a future
mistake is worth keeping; calling it proof of a past one is not.

Two checks had to be rewritten to earn that classification. AC-3 and AC-6 initially reused the
nested fixture's depth-2 lookup, so on a flat tree they failed reporting `leaf 'none'` and a
self-deletion bug that did not exist — red marks for "the layout is flat", which is AC-1's
sentence to speak. Both now search at any depth. A gate that fails for the wrong reason is worse
than one that does not fail at all: it teaches the reader to discount it.

LIVE tier: none. This is a filesystem-layout change with no deployed surface.
