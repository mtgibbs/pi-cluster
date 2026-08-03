# Recap — the judge loop lands, and a secret leak handled mid-arc (2026-08-02 → 2026-08-03)

One continuous overnight arc, eight PRs (#132–#139). The goal set at the top: put the Codex
subscription to work as an **adversarial reviewer and planning checker** — a second mind from a
different model family — complementing qwen-as-workhorse and Claude-as-orchestrator. By the end,
the eval-loop tower was complete (binary `verify.sh` → scored `gate-score.sh` → **judge**), the
judge had run once in production and found five real defects, and a live credential leak on the
agent bus had been detected, rotated, revoke-verified, and root-caused — all inside the same arc.

## 1. The spec, adversarially checked (#132: v0.1 → v0.3)

The judge-loop spec — a post-convergence intent reviewer that reads the delta between spec prose
and gate assertions — went through its first **Codex adversarial planning check** before a line
of implementation existed. Artifact: `specs/judge-loop/reviews/2026-08-02-codex-planning-check.md`.

- **4 BLOCKERs, all independently verified by Claude before folding into v0.2** — including
  **two real bugs in already-merged `gate-score.sh` (#104)**: it discarded the verifier's exit
  status (PASS lines + a crash still scored `converged=1`), and score ties permitted check
  deletion (drop 9 of 10 checks → still 1.000). Plus 10 MAJOR/MINOR: JSONL fail-closed contract,
  flake detection, cross-run ledger persistence, sentinel-parse hardening, STRICT parity,
  one-finding-per-invocation + `--check-resolution`.
- **The stall-watchdog discipline was born here:** the first Codex dispatch hung silently for
  30+ minutes (0% CPU, dead client). Relaunched under a 6-min-silence / 25-min-total watchdog,
  it returned the verdict in ~9 minutes — empirically validating its own finding #1 (every
  external command needs a timeout), now spec'd for `JUDGE_CMD` itself.
- **v0.3** folded in the harness agent's production evidence from building `specs/export` in
  new-horizons, relayed over the Matrix bus:
  `specs/judge-loop/evidence/2026-08-03-harness-gate-gap-evidence.md` — **four defect classes
  a two-way-validated gate still missed** (fail-open ordering, assertion theatre, symmetric
  round-trip blindness, fixture coincidence), each with a reproduction, plus the core claim:
  *a gate cannot validate its own blind spots; the loop fixes what is gated and regresses what
  is merely described.*

## 2. Security incident, mid-arc: agent-bus interpolation leaked six live creds (#133, #135)

While the spec work was in flight, `coding-harness-claude` posted a status message to `#tasks`
whose body contained a `$(export)`-shaped fragment — and `agent-bus post` passed message bodies
through **shell interpolation**. The shell expanded it and pasted the container's entire
environment into the room: six live credentials (GitHub PAT, homelab/local-llm/kiwix MCP keys,
LiteLLM key, Matrix token).

- **Same-night remediation, revoke-verified:** all six rotated in blast-radius order (the
  off-LAN GitHub PAT first, the bus token last); every rotation closed only when the **old**
  value observably returned 401. Consumers re-keyed via `deploy-ai-stack.sh`; harness confirmed
  bus/MCP/git green on the new set by ~00:30.
- **Root cause fixed the same night (#133):** `agent-bus post --file` / stdin — the body is
  data, never a shell argument — plus an outbound secrets guard.
- **Write-up (#135):** `docs/incidents/2026-08-02-agent-bus-secret-leak.md` — including the
  lessons (revoke-and-verify is the deliverable; per-role creds kept it to six rotations with
  zero cascade; a guard that cries wolf gets overridden).
- **One missed consumer surfaced the next morning:** the laptop `oc` credential in the macOS
  Keychain wasn't on the `deploy-ai-stack` re-key path — found and fixed after the fact.

## 3. gate-score goes fail-closed (#134)

The judge loop's one hard prerequisite, closing both Codex-found bugs, red-before-green:
`verify_rc=<n>` now rides the score line and exit 0 requires `converged==1 && verify_rc==0`
(AC9); the check-deletion hole is covered by the consumer-side `total == baseline` rule the
judge enforces. Also folded in the pend-contract ruling from the specs/export incident (pend
keys on the *dependency*, never the deliverable; scope checks first and fatal). 22/22 + STRICT,
new assertions observed failing before the fix.

## 4. The loop gets built — and the gate catches its own author (#136)

`scripts/ralph-judge.sh`, implementing spec v0.3 exactly: judge proposes against intent, qwen
executes, the deterministic gate arbitrates every mutation. Shipped at **17/17 + STRICT clean**,
every assertion previously observed red; the 11 behavioral fixtures cover the taxonomy the spec
was hardened with (staged-state restore, check-deletion, malformed JSONL, cross-run ledger,
executor timeout, `resolved:false`, MAX_ROUNDS, dirty preflight, flake rule).

- **qwen via ralph went 8/9 × 3 attempts** — every safety/reject path correct, never the accept
  path — then stopped **"needs a human"**: the escalation working as designed. Claude
  hand-finished; the accept path passed immediately, proving the failure was executor-depth,
  not spec ambiguity.
- **The gate caught its own author twice:** a whitespace-blind compare in verify.sh, and a jq
  `--slurpfile` misuse that ate `report.json` on non-empty ledgers — masked by the empty-ledger
  fixture. Fixture-coincidence in the wild, again.
- **Environment lesson (third sighting of the fail-open-pend class):** fresh worktrees lack the
  gitignored `opencode.json`, so headless `oc` auto-rejects every tool call and pends score
  green until STRICT.

## 5. First production judge run (#137)

Codex judged the loop's **own freshly-merged implementation**. Baseline 1.000/17 (double-run,
stable) → **5 findings, all real, all `gate-gap`, 0 mutations, outcome dry, exit 0**. Every
contract held on the first try: valid JSONL, nothing auto-applied (the conservative v1 surface
routed behavior-adjacent findings to the report channel), report matched ledger, run bounded
itself — and the recursion held, with the outer gate spawning eleven inner fixture runs.

The headline: **all five findings entered at the same seam — the human compilation of spec §§
into `tasks.txt`**. The executor built exactly what the tasks gated; what the spec merely
described drifted. That is the evidence doc's §6 pattern observed one level up, caught by the
judge whose designed input is precisely that delta. Plus finding #6, found by the run itself:
gate-gap payloads weren't persisted — recovered only because Codex's session log happened to
retain them. Artifact: `specs/judge-loop/reviews/2026-08-03-first-judge-run.md` (findings +
triage table, decided with Matt).

## 6. Triage fix-now set (#138) and operator bindings (#139)

- **#138:** schema `line` + nonempty-string enforcement, full finding payloads in
  `rejected`/`gate-gap` ledger records, `scope-violation` rejection for post-executor changes
  outside the finding's file, optional `RJ_EXPECTED_BRANCH` preflight — with the spec two-way
  synced (command bindings belong at the operator layer; ledger keying note). The red run
  caught **two new checks passing for the WRONG reason** (old-schema rejection mimicked the
  target behavior at the rc level) — masked red, caught before green. Final 21/21 + STRICT.
- **#139:** the wrappers promoted from scratchpad to `scripts/` — `ralph-judge-codex.sh`
  (JUDGE_CMD: read-only Codex, JSONL, `--check-resolution`, fence-strip only) and
  `ralph-judge-exec-qwen.sh` (one finding, one file, no commits) — plus the README section with
  pairing, exit codes, and the `opencode.json` worktree gotcha. Prompts now derive targets from
  the spec's Touches/Scope, usable against any converged spec.

## 7. Themes

- **The eval-loop tower is complete:** `verify.sh` (binary) → `gate-score.sh` (scored,
  fail-closed) → `ralph-judge.sh` (intent judge). Each layer arbitrates the one below.
- **Every layer's lessons were caught by the layer built from them:** the gate caught its own
  author twice (#136); the red run caught masked reds in the triage checks (#138); the judge
  caught the spec compiler (#137). The system is eating its own findings.
- **Escalate-to-human proved itself twice** — qwen stopping at "needs a human" on specs/export
  (4 attempts) and on the ralph-judge accept path (3 attempts) — both times correctly: the
  remaining work needed judgment, not retries.
- **Multi-agent collaboration over the Matrix bus worked under load:** Codex (adversarial
  reviewer), harness-claude (production evidence relayed over the bus), qwen (executor), Claude
  (orchestrator) — including a security incident detected, coordinated, and closed *inside* the
  same bus the incident happened on.

## 8. Open items

- [ ] Second judge run on a spec the loop **didn't** build (independence check on the target).
- [ ] Wire `gate-score.sh` into `ralph-qwen.sh` (independent of the judge; OQ-5 sequencing).
- [ ] Red-before-green as a **required per-AC template field** ("has this assertion been seen
      red?") in `specs/TEMPLATE.md`.
- [ ] `coding-agent-ops` SKILL.md updates — the `opencode.json` fresh-worktree gotcha is in
      `scripts/README.md` but the skill doc is still pending.
- [ ] v1.1 deferrals from the #137 triage: isolated-worktree detection, interrupted-run
      reconciliation.
- [ ] Harness outbound secret-guard tightening (match actual assignments like `declare -x NAME=`,
      not mentions — a guard that cries wolf gets overridden).

## Artifacts

| What | Where |
| :--- | :--- |
| Judge-loop spec (v0.3) + gate | `specs/judge-loop/spec.md`, `tasks.txt`, `verify.sh` |
| Codex planning check | `specs/judge-loop/reviews/2026-08-02-codex-planning-check.md` |
| Harness gate-gap evidence | `specs/judge-loop/evidence/2026-08-03-harness-gate-gap-evidence.md` |
| First judge run + triage | `specs/judge-loop/reviews/2026-08-03-first-judge-run.md` |
| Incident write-up | `docs/incidents/2026-08-02-agent-bus-secret-leak.md` |
| The loop + bindings | `scripts/ralph-judge.sh`, `ralph-judge-codex.sh`, `ralph-judge-exec-qwen.sh` |

Relevant PRs: #132 (spec + planning check) · #133 (agent-bus `--file` fix) · #134 (gate-score
`verify_rc`) · #135 (incident doc) · #136 (ralph-judge.sh) · #137 (first judge run) · #138
(triage fixes) · #139 (operator bindings).
