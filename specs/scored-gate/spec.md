# Spec: a scored gate — turn the pass/fail verify into a convergence signal

- **Status:** Draft v0.1
- **Owner:** Matt (orchestrated by Claude; executor TBD)
- **Constitution:** `specs/constitution.md` (+ `/CLAUDE.md` Core Mandates)
- **Touches:** `scripts/gate-score.sh` (new, this spec's only in-scope file)

---

## 1. Why · [R]

`verify.sh` already knows more than it says. Internally it decides every check `PASS` / `FAIL` /
`pend`, but it collapses all of that to one exit code: `0` or `1`. The loop
(`scripts/ralph-qwen.sh`) therefore sees a light switch, not a dimmer.

That costs us the thing we most want from an eval loop: **"getting closer."** Attempt 2 cannot
tell whether it improved on attempt 1 (went 3-fails → 1-fail) or regressed — both read as "not
0, retry." And the feedback it hands back is a blind `grep -E 'FAIL'` (`ralph-qwen.sh:127`),
which drops every `pend` — i.e. every *not-built-yet* check, which for a presence-gated per-task
run is usually exactly the work the current task should do.

We are one small tool away from a score. This spec builds that tool. It does **not** touch the
loop — wiring the score into `ralph-qwen.sh` is a deliberate second step (see §5).

## 2. Outcomes (Definition of Done) · [R]

1. A new `scripts/gate-score.sh <verify-path>` runs any existing `verify.sh` unmodified and emits
   a machine-readable score block: `passed failed pending total score` plus `no_fail` /
   `converged` booleans.
2. It emits the **itemized remaining work** — the `FAIL:` messages (regressions, fix these) and
   the `TODO:` messages (pending, build these) — so the loop can feed *targeted* text back
   instead of a raw grep.
3. It parses **every format variant the current fleet actually emits** (see §6), case-insensitively.
4. A gate that emits **no parseable checks** is a loud error (`exit 2`), never a silent
   `score=1.000`. A wrong score must never look like a good one.
5. `verify.sh` files are **untouched** — they remain the single source of truth for *what* is
   checked; this tool only re-expresses *how much* passed.

## 3. Entities · [E]

The parsed shape of one `verify.sh` run:

| Field | Type | Meaning |
|---|---|---|
| `passed` | int | count of checks in the PASS vocabulary |
| `failed` | int | count in the FAIL vocabulary (a check that ran and was wrong) |
| `pending` | int | count in the PEND vocabulary (presence-gated, not built yet) |
| `total` | int | `passed + failed + pending` |
| `score` | float, 3dp | `passed / total` — completeness of the whole rubric |
| `no_fail` | 0\|1 | `failed == 0` — the per-task commit bar (pends allowed), == today's `bash verify.sh` exit 0 |
| `converged` | 0\|1 | `failed == 0 && pending == 0 && total > 0` — the done bar, == today's `STRICT=1` exit 0 |

## 4. Approach · [A]

**Wrap, don't rewrite.** `gate-score.sh` shells out to the target `verify.sh`, captures its
combined stdout+stderr (FAIL lines go to stderr — see §6), and classifies each status line by a
**tolerant, case-insensitive leading-token match**. It re-prints the raw output verbatim, then a
sentinel-delimited machine block. Same rubric, new readout.

Rejected: sourcing a shared `verify-lib.sh` into all ~23 gates so helpers emit structured records
natively. Cleaner in theory, but it edits 23 working gates for a scoring feature — the wrong
risk/reward for step one. The wrapper reads their existing output and touches nothing. Fleet
normalization can come later if ever; it is explicitly out of scope here.

## 5. Scope · [S]

### In scope
- `scripts/gate-score.sh` — new file, the whole deliverable.

### Out of scope here, but the REASON this exists — separate step, done by hand
- Wiring `gate-score.sh` into `scripts/ralph-qwen.sh` (score-driven retry + itemized feedback +
  score in the heartbeat). Deliberately excluded: a loop must not be rewritten by a run of
  itself, and the integration is delicate. Claude does that step directly after this lands.

### Out of scope entirely
- Editing any `specs/*/verify.sh`. They are the rubric; this tool only reads them.
- Changing what any check tests, or the PASS/FAIL/pend semantics.

## 6. Prior decisions / facts the implementer must know · [S]

**Surveyed 2026-07-27 across all 23 `verify.sh` in `specs/` — these are real, do not assume uniformity.**

The fleet does **not** emit one canonical format. A parser that assumes `"  PASS  "` (two spaces,
uppercase) will silently miscount two real files, and a miscount in a *scoring* gate is the worst
possible bug — it misdirects the loop with false confidence. Observed spellings:

| bucket | spellings seen in the wild | emitted to |
|---|---|---|
| pass | `  PASS  ` (14 files), `  ok   ` — 3 spaces, lowercase (`aimode-toggle`) | stdout |
| fail | `  FAIL  ` (all) | **stderr** (`no(){ … >&2; }`) — so you MUST capture `2>&1` |
| pend | `  pend  ` (most), `  PEND  ` (several) | stdout |

Facts that pin the parser:

- **Capture stderr.** `FAIL` goes to stderr. Run the gate as `bash "$V" 2>&1`.
- **Status lines are indented; headers are not.** Checks print with 1–4 leading spaces
  (`  PASS  …`, `  ok   …`). The summary lines `VERIFY …` and `VERIFY: PASS` start at column 0.
  Anchor on a small leading indent so headers, `sed 's/^/    | /'` context dumps, and message
  bodies never false-match.
- **Match the leading TOKEN, case-insensitively, against a fixed vocabulary — never substring.**
  A message body legitimately contains the word "fail" (e.g. `  PASS  invalid repo exits …`);
  matching a bare `FAIL` anywhere would count that PASS as a failure. Classify by the first word
  after the indent only.
- **Vocabulary (closed set):**
  - pass ← `PASS`, `OK`
  - fail ← `FAIL`
  - pend ← `PEND`, `PENDING`
  - Any other leading token is **not a check** — ignore it. In particular do **NOT** add `NO` as a
    fail synonym: the helper is named `no()` but it prints `FAIL`, and a genuine informational line
    like `  No changes detected` would then be miscounted as a failure. `TODO` is an **output**
    label (the `TODO:` lines in §2/§10), never an input token.
- `score = passed / total`. When `total == 0`, `score = 0.000` **and** an `error=no-checks-parsed`
  token is emitted and the exit code is `2`. Zero checks is a broken invocation, not a perfect score.

### WORKED EXAMPLE — the classifier shape (copy this idea)

Prose was not enough on past specs, so the shape is given. An `awk` pass over the captured output
is the natural fit — one line in, one bucket out, by first token, case-folded:

```sh
run="$(cd_target && bash "$V" 2>&1)"        # combined; FAIL is on stderr
counts="$(printf '%s\n' "$run" | awk '
  # $1 is the first whitespace-delimited field; leading indent is already stripped by awk.
  # Guard on a small original indent so column-0 headers are excluded.
  /^[[:space:]][[:space:]]?[[:space:]]?[[:space:]]?[A-Za-z]/ {
    t = toupper($1)
    if (t=="PASS"||t=="OK")            p++
    else if (t=="FAIL")               f++
    else if (t=="PEND"||t=="PENDING") d++
  }
  END { printf "%d %d %d", p, f, d }
')"
```

Read `passed failed pending` back from `$counts`. The itemized lists come from the same output:
the `FAIL:` payload is every fail-token line's message, the `TODO:` payload every pend-token
line's message.

### WORKED EXAMPLE — the score line (copy this; do NOT compute the score in bash)

**bash arithmetic is integer-only: `$((3/6))` is `0`, so a bash-computed score is *always* `0.000`.**
This bit three dogfood attempts. Compute the float in `awk`, and handle the empty gate explicitly:

```sh
total=$(( passed + failed + pending ))
no_fail=0;   [ "$failed"  -eq 0 ] && no_fail=1
converged=0; [ "$failed"  -eq 0 ] && [ "$pending" -eq 0 ] && [ "$total" -gt 0 ] && converged=1

if [ "$total" -eq 0 ]; then
  score="0.000"; extra=" error=no-checks-parsed"           # empty gate: literal 0.000 + marker, exit 2
else
  score="$(awk -v p="$passed" -v t="$total" 'BEGIN{ printf "%.3f", p/t }')"; extra=""
fi

echo "---GATE-SCORE---"
echo "passed=$passed failed=$failed pending=$pending total=$total score=$score no_fail=$no_fail converged=$converged$extra"
# then the FAIL:/TODO: lines; then: [ "$total" -eq 0 ] && exit 2; [ "$converged" -eq 1 ] && exit 0 || exit 1
```

## 7. Norms · [N]

- POSIX-ish bash + `awk`. No new runtime dependencies (no `jq`, no python) — this runs inside the
  minimal executor containers.
- The tool is **read-only**: it runs a gate and reports. It must never write, commit, or mutate
  the tree. `git status` is not its business.
- Preserve the raw `verify.sh` output verbatim above the machine block — the loop still logs it,
  and a human still wants to read it. Add signal; subtract nothing.
- Match the existing file voice: comments name the *why* and the failure they prevent.

## 8. Safeguards · [S]

1. **No silent perfect score.** `total == 0` ⇒ `error=no-checks-parsed`, `score=0.000`, `exit 2`.
   A gate that parsed nothing must fail loudly, because the loop would read a bogus `1.000` as
   "done."
2. **Classify by leading token only, case-insensitive.** Never substring-match a status word,
   or a PASS whose message mentions "fail" is miscounted. This is the correctness core.
3. **Capture stderr.** FAIL lines are on stderr; a stdout-only capture scores every failing gate
   as passing — the exact false-green this whole effort exists to kill.
4. **Read-only.** No writes to the repo, ever.

## 9. Task breakdown · [O]

See `tasks.txt` — **one task**: build the whole `scripts/gate-score.sh`. The full gate (§11)
grades it; presence-gating lets a partial attempt pend the rest and iterate.

> **Two dogfood lessons, 2026-07-27, both about matching the task to the executor.**
>
> 1. *A task an external gate cannot see is not a task.* The first split made "T1" the classifier
>    with no printed output — ungradeable. Fixed by making every increment emit a testable surface.
> 2. *qwen is a holistic stamper; it ignores "don't build the other parts."* Re-split into
>    observable increments, it still built T1 **and** T3 in one attempt and scored 16/17 — the miss
>    was a blank `score=` on the empty gate, compounded by a gate message that misstated the fix.
>    The prohibition-based split (which the `harness-multi-repo` spec needed for a file with
>    distinct owned line-ranges) fights a 40-line single-file deliverable. So: **one task, whole
>    file, full gate.** Granularity should match the deliverable — over-decomposition is its own bug.

**Scope, as a hard rule** (enforced by the gate, not just prose): the only file that may change is
`scripts/gate-score.sh`. Test fixtures go in `$TMPDIR` — an out-of-scope file in the tree fails
the gate.

## 10. Acceptance criteria (EARS) · [O]

1. **When** given a `verify.sh` that emits a known mix of checks, `gate-score.sh` **shall** print
   a line `passed=<p> failed=<f> pending=<d> total=<t> score=<s>` where `t = p+f+d` and
   `s = p/t` to three decimals.
2. **Where** a check line uses any observed spelling — `PASS`, `ok` (3-space lowercase), `FAIL`,
   `pend`, `PEND` — it **shall** be classified into pass/fail/pend respectively, case-insensitively.
3. **Where** a gate emits its `FAIL` lines to stderr, `gate-score.sh` **shall** still count them
   (i.e. it captures stderr).
4. **When** at least one check is `FAIL`, the output **shall** include `no_fail=0`; **when** none
   are, `no_fail=1`. **When** `failed==0 && pending==0 && total>0`, it **shall** include
   `converged=1` and **exit 0**; otherwise `converged=0` and **exit 1**.
5. **When** a check fails, its message **shall** appear on a `FAIL: <message>` line; **when** a
   check is pending, its message **shall** appear on a `TODO: <message>` line.
6. **Where** the target gate emits zero parseable checks, `gate-score.sh` **shall** emit
   `error=no-checks-parsed`, `score=0.000`, and **exit 2** — never `score=1.000`.
7. **Where** a check message contains the word "fail" or "pass" in its body (e.g.
   `  PASS  invalid repo exits non-zero`), the leading token **shall** decide its bucket — the
   body **shall not** change the count.
8. **The** tool **shall not** modify the working tree (read-only).

## 11. Verification (the harness)

`./specs/scored-gate/verify.sh` — STATIC, offline, presence-gated. It synthesizes fixture gate
scripts (a mixed one covering every spelling incl. the `ok`/`PEND` outliers and a body-with-"fail"
trap; an all-pass one; an empty one) and asserts `gate-score.sh`'s counts, score, booleans, exit
codes, and itemized lines against them. No network, no cluster.

## 12. Open questions

- **v2, not now:** should the loop grant *extra* retry attempts while the score is strictly
  improving (true "closer and closer"), capped hard to prevent a 0.01-per-turn crawl? Deferred to
  the `ralph-qwen.sh` integration step — this spec only builds the readout the loop would steer on.
- Should `gate-score.sh` optionally emit the block as JSON (`--json`) for the heartbeat/console?
  The `key=value` line parses trivially in bash; JSON adds a dep or hand-rolling. Decide at wiring.
