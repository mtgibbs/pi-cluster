# Gate-gap evidence for judge-loop — four defect classes, with reproductions

From building `specs/export` (lossless `nh export`/`import`) in `mtgibbs/new-horizons`,
2026-08-03. Shipped green at 18/18 STRICT as new-horizons#25.

Every defect below was found by **reading the diff above a green gate**. None were caught by
the gate as first written — and that gate had been validated two ways before handoff. That is
the single most important fact here, so it's stated first.

---

## 0. Why pre-handoff gate validation was not enough

Before giving the spec to qwen I did what the constitution asks, and then some:

1. **Passability check** — wrote a throwaway reference implementation, ran `verify.sh` against
   it, got 15/15. This rules out the failure mode where a subtly impossible gate makes the loop
   thrash forever. Worth keeping.
2. **Mutation testing** — mutated the reference 5 ways (NULLs→`""`, non-deterministic output,
   `created_at` clobbered, import deleting rows, `--dry-run` guard neutralised) and confirmed
   each was caught by the AC meant to catch it. 5/5.

I was pleased with that gate. **It then missed four distinct defect classes.**

The reason is structural and worth putting in the spec: *both* validation techniques only ever
ran the gate against **implementations that attempted the task**. Neither could detect a gate
that returns PASS when nothing was built, an assertion that checks the wrong property, or a
fixture whose data can't express the failure. **A gate cannot validate its own blind spots.**
That is precisely the gap a judge fills — and it means the judge must read the **diff against
spec intent**, never the gate's verdict.

---

## 1. FAIL-OPEN ORDERING

**What happened.** qwen attempted head/tail surgery on `scripts/nh`, abandoned `temp_head` and
`temp_tail`, and never modified the target file. `verify.sh` reported **PASS**. The loop
committed the junk and moved on; only the final STRICT pass caught it.

**Why.** The presence gate ran *before* the scope check and exited 0 on `pend`:

```bash
if ! grep -q "'export'" "$NHFILE"; then
  pend "T1: nh export/import"; exit "$fail"     # <-- exits 0. Nothing after this ever runs.
fi
...
outside="$(git status --porcelain ... )"        # scope/litter check — never reached
```

**Fix.** Scope/litter checks run **first and fatal**, unconditionally. This is the same class as
the merged `gate-score.sh` bug Codex found (discarding the verifier's exit status): *an early
exit path that returns success.*

**Judge implication.** Any gate with an early-exit `pend` needs its ordering audited. A judge
that only consumes `VERIFY: PASS` inherits this exactly.

---

## 2. ASSERTION THEATRE

**What happened.** `--dry-run` reported `(0 new, 0 updated)` for every input, because the whole
counting loop sat inside `if not args.dry_run:`. The counts *are* the deliverable of a dry run.

**Why the gate missed it.** The assertion was:

```bash
echo "$out" | grep -qi "dry-run" && ok "AC8: --dry-run reported counts"
```

That checks the feature **said something**, not that it said the **right thing**. An
implementation that always prints zeros satisfies it perfectly.

**Fix — compare against an oracle, not a constant:**

```bash
dry="$(nh import "$f" --dry-run)"; real="$(nh import "$f")"
dnum="$(echo "$dry"  | grep -oE '[0-9]+ new, [0-9]+ updated')"
rnum="$(echo "$real" | grep -oE '[0-9]+ new, [0-9]+ updated')"
[ "$dnum" = "$rnum" ] || no "dry-run said '$dnum' but the real import did '$rnum'"
```

**Judge implication.** Grep-for-a-substring assertions are the most common shape in our gates and
the least load-bearing. A judge should flag any assertion whose expected value is a **literal
string** rather than a **computed comparison**.

---

## 3. SYMMETRIC ROUND-TRIP BLINDNESS

**What happened.** Export emitted **two** trailing newlines (`print(json.dumps(...))` already
emits one, then a bare `print()` added another).

**Why the gate missed it.** The central AC was round-trip equality: export → import → export must
be byte-identical. **Both sides were equally wrong**, so they compared equal. `$( … )` capture
also strips trailing newlines, hiding it from any shell-based check.

**Fix.** Assert the absolute property, not just the relative one:

```bash
python3 -c "d=open('$f','rb').read(); n=len(d)-len(d.rstrip(b'\n')); assert n==1, f'{n} trailing newlines'"
```

**Judge implication.** Any *invariant-style* AC (round-trip, idempotency, symmetry) is blind to
errors that affect both sides identically. Those ACs need at least one absolute anchor. This
generalises well beyond newlines — it's the same reason `A == B` can't detect that both are
corrupt.

---

## 4. FIXTURE COINCIDENCE — the worst one

**What happened.** The reconverge fixed #2 and #3 and **silently regressed id preservation**:
the INSERT dropped the `id` column ("let SQLite auto-increment the ID"). AC7 — the *dedicated*
id-preservation assertion — still **passed**.

**Why.** The fixture seeded ids `1,2`. Plain autoincrement reproduces `1,2` **by coincidence**.
The test passed for the wrong reason, which is worse than not having it.

**Proof it was real.** Any store develops gaps the moment a lead is deleted:

```
source ids:       [1, 3]
after round-trip: [1, 2]      # renumbered
```

That silently breaks `nh alert`, which keys its already-alerted state file on lead **id** — a
renumbering re-alerts everything or suppresses the wrong leads. The exact failure the spec
argued for preserving ids to avoid.

**Fix.** Fixture now seeds 1,2,3, deletes 2, and asserts `[1,3]` survives — so the property is
*exercised* rather than accidentally satisfied.

**Judge implication.** This is the one a judge is uniquely placed to catch, because it requires
reading the AC's **intent** against the fixture's **data**. Ask of every assertion: *could this
fixture ever produce a failing value?* If not, the assertion is decorative.

> **A fixture that cannot fail is worse than no fixture** — it purchases false confidence, and
> it survives review because the line item is present and green.

---

## 5. RED-BEFORE-GREEN — concrete, and cheap

Your "self-proving gates" note is the right deeper fix for #4, and it costs almost nothing. For
every new AC I added after this point I ran it **against a known-bad build first** and required
it to FAIL, naming the observed wrong value, before trusting a PASS:

```
AC7(gaps) vs regressed build: FAIL — ids not preserved — source [1, 3] became [1, 2]
AC7(gaps) vs correct build:   PASS
```

An assertion that has never been observed failing is an assertion of unknown value. Suggest
making this a **required field per AC** in the judge's checklist: *has this assertion been seen
red?* It converts #4 from "reviewer must be clever" into a mechanical question.

---

## 6. The behavioural pattern that ties it together

**The loop fixes precisely what is GATED and regresses what is merely DESCRIBED.**

Round 2 fixed the two newly-gated defects and broke a described-but-under-gated one, in the same
diff. This is not qwen being careless — it's a faithful stamper optimising against the only
objective function it can observe. Design consequence for judge-loop: the judge's value is
highest exactly where the spec says something the gate cannot measure, and it should probably be
pointed at **the delta between spec prose and gate assertions** as a first-class input.

## 7. Loop economics, for your sequencing

4 gate-fix rounds; qwen exhausted its 4 attempts on the final AC and stopped with "needs a
human" — the escalation working as designed. The last fix (free-id check plus autoincrement
fallback on collision) needed judgment it did not have. So: the judge should be able to
*terminate* a loop, not just annotate it, and "escalate to human" is a legitimate verdict.

## 8. Reference implementation of your contract ruling

`specs/export/verify.sh` in new-horizons#25 already implements the ruling you issued:
- PEND keys on the **dependency's** observable (`add_parser('add'` from lead-store), never on the
  task-under-test's own deliverable;
- a missing deliverable on a single-task spec is a hard **FAIL**;
- scope/litter checks run **first and fatal**.

Usable as the reference shape when you fold the ruling into `gate-score.sh`.

## 9. Still blocking you

The `verify_rc` fail-closed amendment was **never written** — no branch, no commits. So both
fail-open bugs remain live in merged `gate-score.sh` (discards verifier exit status; score ties
permit check-deletion). Only `specs/scored-gate` consumes it and `ralph-qwen.sh` does not, so it
is latent rather than actively corrupting — but by your own sequencing note, judge-loop is
blocked on it. Say the word and I'll write it; otherwise it's yours.
