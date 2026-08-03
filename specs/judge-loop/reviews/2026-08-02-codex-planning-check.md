# Planning check — Codex adversarial review of judge-loop spec v0.1

- **Date:** 2026-08-02
- **Reviewer:** OpenAI Codex CLI (`codex exec --sandbox read-only`, laptop), a deliberately
  different model family from the builder (qwen) and orchestrator (Claude).
- **Process note:** first dispatch hung silently for 30+ min (0% CPU, no open connections —
  dead client). Relaunched under a stall watchdog (6-min silence / 25-min total kill). That
  incident independently validates finding #1: every external command in this loop needs a
  timeout. Verdict below produced by the watchdogged run in ~9 minutes.
- **Verification:** the four BLOCKERs were independently confirmed by Claude against
  `scripts/gate-score.sh` and `scripts/ralph-qwen.sh` before being folded into spec v0.2.

---

### 1. Open-question rulings

**1. Use a fresh spec-intent judge; do not adapt review-hub validators for v1.**

Review-hub is coupled to GitHub webhooks, changed-file APIs, Check Runs, and per-repository validator routing (`scripts/reviewhub/receiver.py:113-179`). Its validators return pass/block summaries rather than the finding schema required here (`scripts/reviewhub/reporting.py:38-56`); reuse its model-call and fail-closed patterns, not its validators.

**2. The default judge must be a different, stronger, eval-qualified model.**

Using qwen for both roles contradicts the independence requirement in spec §7 (`spec.md:113-115`). Review-hub’s repeated voting and explicit timeout demonstrate that model selection alone is insufficient; the default also needs measured stability, while qwen may remain an explicit override (`gate_regression.py:62-89`).

**3. Limit v1 to localized comments, naming, clarity, and literal spec-fidelity corrections.**

Exclude “dead-code” deletion and behavior-preserving refactors: both can change behavior that the gate does not observe, precisely the condition motivating this loop (`spec.md:14-19`). Findings outside the conservative set should be reported as gate-gaps for human action.

**4. Keep it standalone after `ralph-qwen.sh`.**

Ralph has task/retry semantics followed by a distinct final `STRICT=1` convergence gate (`ralph-qwen.sh:75-154`). Folding stochastic review into that loop would corrupt its one-task/fresh-context contract and make deterministic failures indistinguishable from judge churn.

**5. Require a corrected gate-score dependency, but do not require score integration into ralph-qwen first.**

The standalone judge consumes gate-score directly, so wiring score into ralph-qwen is unrelated to its correctness (`spec.md:87-95`). More importantly, current gate-score discards the underlying verifier exit status (`gate-score.sh:26-28,55-68`); that interface must be fixed before this loop can claim fail-closed gating.

### 2. Attack findings

1. **BLOCKER — spec §§2, 4, 8 — The round cap does not bound findings per round or the duration of judge and gate calls.**  
   `MAX_ROUNDS` advances only after `JUDGE_CMD` returns, while one response can contain unlimited mutations (`spec.md:32-33,63-74,121-123`). A hung judge, hung `verify.sh`, or a million-finding response never reaches the cap; ralph only demonstrates a timeout for `oc run`, not for verification (`ralph-qwen.sh:89-94,111-120`).

2. **BLOCKER — spec §§2, 4, 6 — gate-score can report convergence after `verify.sh` itself failed.**  
   The script captures verifier output but never captures or incorporates its exit status (`gate-score.sh:26-28`); it derives its own exit solely from parsed lines (`gate-score.sh:55-68,89-93`). A verifier prints its PASS lines, crashes during cleanup, and exits 2; gate-score still returns `converged=1`, allowing the mutation to commit.

3. **BLOCKER — spec §§2, 4, 8 — score equality permits deletion or weakening of the gate.**  
   For any all-pass output, score is `1.000` regardless of how many checks remain (`gate-score.sh:55-64`). A mutation deletes nine of ten checks from `verify.sh`; the remaining check passes, `no_fail=1`, and the unchanged 1.000 score satisfies `spec.md:70-72`.

4. **BLOCKER — spec §§4, 6, 8 — the proposed restore mechanism is neither a defined snapshot nor safe for staged state.**  
   “git stash-point” is not a literal Git operation (`spec.md:68`), while the cited ralph restore only resets the worktree and deletes untracked files (`ralph-qwen.sh:129-133`). If the executor stages a rejected edit, `git checkout -- .` restores that staged version into the worktree; the rejected mutation can enter the next accepted commit. Conversely, `git clean -fd` can destroy pre-existing untracked work unless the constitution’s clean isolated-worktree precondition is enforced.

5. **MAJOR — spec §§4, 6 — executor timeout and nonzero-exit behavior is unspecified.**  
   The pseudocode gates whatever tree remains after `EXECUTOR_CMD`, regardless of its status (`spec.md:67-72`). A watchdog kills qwen halfway through a multi-file edit, but the partial edit happens to pass; ralph’s cited implementation only aborts a nonzero executor when its log is under 512 bytes (`ralph-qwen.sh:93-108`), so mirroring it would accept some timed-out partial applies.

6. **MAJOR — spec §§3, 9 — malformed or adversarial JSONL has no fail-closed contract.**  
   The spec names JSON lines but defines no parser errors, duplicate-ID behavior, field types, path validation, or command exit semantics (`spec.md:43-57,131-140`). A truncated final line could be silently ignored and produce a false “dry” round; two records with the same ID but conflicting kinds could make processing order decide whether code is mutated.

7. **MAJOR — spec §§4, 8 — all findings are evaluated against a stale pre-round solution.**  
   Findings are generated once and then applied sequentially (`spec.md:64-73`). Two individually plausible findings—rename A to B and standardize B back to A—can both tie at 1.000 and commit, producing a two-mutation oscillation or undoing the first improvement without re-review.

8. **MAJOR — spec §§1, 2, 4 — the loop never verifies that an accepted mutation actually resolves the judge’s finding.**  
   Acceptance asks only whether the deterministic gate stayed level (`spec.md:27-36,70-79`), yet the premise is that this gate cannot observe the quality defect (`spec.md:14-19`). The executor can misunderstand a comment-fidelity finding, make a different gate-neutral edit, and receive an “accepted improvement” commit without any quality-side confirmation.

9. **MAJOR — spec §§2, 4, 8 — a single post-mutation gate sample silently accepts flaky verification.**  
   Each mutation gets one gate invocation (`spec.md:70-72`), although “inviolable” is stated categorically (`spec.md:30-31,121`). A mutation triggers a race-sensitive check; its lucky passing run commits it, while a subsequent human run fails.

10. **MAJOR — spec §§3, 4, 8 — the dedupe ledger has no cross-run persistence.**  
    `already_seen` exists only in the pseudocode (`spec.md:64-66`), and “stable” IDs are promised only as round dedupe keys (`spec.md:45,121-123`). Restarting the script replays every previously rejected mutation; two inverse findings can alternate across invocations indefinitely even though each individual run terminates.

11. **MAJOR — spec §§2, 8, 9 — the audit trail has no literal location, schema, durability, or crash behavior.**  
    “Full record” and “write the audit” are aspirations, not an interface (`spec.md:34-36,125,136`). A reject cleanup can delete an in-worktree untracked report, and a crash after mutation but before logging can leave neither a decision record nor a reliable recovery point.

12. **MAJOR — spec §§4, 6 — the gate invocation omits the final STRICT contract used by ralph-qwen.**  
    Ralph declares completion only after `STRICT=1 bash "$VERIFY"` (`ralph-qwen.sh:145-154`), but the judge pseudocode merely calls gate-score on verify (`spec.md:70,99-103`). The judge therefore does not literally re-run the same convergence gate unless `STRICT=1` inheritance is specified.

13. **MAJOR — spec §6 — parsing “the score line” is ambiguous because gate-score emits raw verifier output before its sentinel.**  
    Actual output starts with untrusted raw gate output, then the sentinel and authoritative line (`gate-score.sh:26-31,66-68`). A verifier that itself prints `score=` or `---GATE-SCORE---` can fool a grep-based implementation unless the spec requires parsing the final sentinel and exactly its following line.

14. **MINOR — spec §§2, 8 — the optional branch argument has no defined semantics or constitutional branch check.**  
    The CLI advertises `[branch]` (`spec.md:27`) but never says whether it validates, creates, or switches branches. The constitution’s “Git discipline — one worktree per agent” requires checking the current branch before every commit; silently ignoring this argument risks committing on the wrong branch.

### 3. Self-fidelity check

- The spec preaches externally observable tasks but defers every acceptance criterion and the verifier (`spec.md:129-142`), contrary to the constitution’s “Verification is external and mandatory.”
- The finding fields are a useful start, but command invocation, JSONL validation, gate parsing, ledger storage, and audit output lack literal shapes.
- `JUDGE_CMD` and `EXECUTOR_CMD` are mockable in name only: their argv/stdin/stdout/stderr/exit-code contracts are unspecified (`spec.md:53-57`).
- The proposed fixture covers one happy mutation, one gate failure, and one gate-gap, but omits malformed output, timeout, staged state, flaky gates, conflicting findings, and restart persistence (`spec.md:138-140`).
- The approach claims a ratchet, but its measurable signal is saturated at 1.000 before the loop begins; no mockable quality-side acceptance seam is defined.

### 4. Concrete edits

**Findings 1, 5 — spec §4 replacement**

> `MAX_ROUNDS` bounds judge invocations and `MAX_FINDINGS_PER_ROUND` bounds records processed per invocation. `JUDGE_TIMEOUT`, `EXECUTOR_TIMEOUT`, and `GATE_TIMEOUT` bound every external command. Judge or gate timeout/nonzero exit aborts the run fail-closed; executor timeout/nonzero exit rejects and restores the mutation before aborting.

**Findings 2–3 — spec §§5–6 replacement**

> Dependency: `gate-score.sh` MUST expose `verify_rc=<n>` and return nonzero whenever the underlying verifier returns nonzero. Judge-loop implementation is blocked until that contract exists. A valid gate result requires `verify_rc=0`, `converged=1`, `no_fail=1`, `total>0`, and the same `total` as the pre-mutation baseline; score alone never proves the gate was preserved.

**Findings 4–5, 14 — spec §8 replacement**

> Preflight MUST verify an isolated worktree, exact expected branch, and empty `git status --porcelain`, including untracked files. Before each mutation record `before_head`; the executor MUST NOT commit. On rejection, timeout, or nonzero exit, restore exactly `before_head`, remove only files created after the clean preflight, and assert the tree is clean. Before acceptance, re-check the branch and stage only paths changed by that mutation.

**Finding 6 — spec §3 addition**

> Each nonblank judge-output line MUST be one JSON object matching the Finding schema. Reject the entire judge invocation before mutation on malformed JSON, missing/extra fields, invalid enums, non-relative paths, invalid line numbers, invalid IDs, or duplicate IDs with unequal payloads. Empty output is the only valid zero-finding response.

**Findings 7–8 — spec §4 replacement**

> Process at most one `mutate` finding per judge invocation, then re-run the judge against the new HEAD. Before commit, call `JUDGE_CMD --check-resolution <finding-json>`; it MUST emit exactly `{"id":"…","resolved":true}`. Unresolved, malformed, timed-out, or conflicting confirmation rejects the mutation even when the deterministic gate passes.

**Finding 9 — spec §8 addition**

> Establish the baseline with two consecutive identical, converged gate results. After every mutation require two consecutive identical results matching the baseline check count and score floor. Any disagreement is a flaky/unstable gate: restore the mutation, record `gate-unstable`, and stop for human review.

**Findings 10–11 — spec §§3, 8 addition**

> `JUDGE_STATE_DIR` defaults to a worktree-specific path beneath `git rev-parse --git-path ralph-judge`. Persist an append-only JSONL ledger keyed by repository, branch, spec path, and finding ID; write each seen/accepted/rejected/gate-gap decision atomically before continuing. Reload it on startup. The final report path and JSON schema are stable outputs, and recovery after interruption begins by reconciling recorded `before_head`/`after_head` with current HEAD.

**Finding 12 — spec §6 replacement**

> Every baseline and post-mutation score invocation MUST run from repository root with `STRICT=1` inherited by `gate-score.sh`, matching ralph-qwen’s final convergence gate.

**Finding 13 — spec §6 addition**

> Parse only the final exact `---GATE-SCORE---` sentinel and the immediately following single key-value line. Reject missing, duplicate-after-final, malformed, unknown, or nonnumeric fields; never grep raw verifier output for `score=` or `no_fail=`.

**Finding 5 — spec §12 question 5 replacement**

> Sequencing: first amend and merge gate-score’s fail-closed `verify_rc` interface; then build standalone judge-loop. Wiring score into ralph-qwen is independent and is not a prerequisite.

### 5. Verdict

**NEEDS-REVISION**

Blockers:

- The advertised termination bound does not bound calls, findings, or elapsed time.
- gate-score can conceal verifier failure.
- equal 1.000 scores permit gate-check deletion.
- the snapshot/revert protocol can retain rejected staged changes or destroy pre-existing files.