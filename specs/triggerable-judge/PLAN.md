# Triggerable-Judge — Prototype Plan

> Status: planning (2026-06-08). Self-contained so it survives a context compaction.
> Sibling of the deterministic lint (`.github/scripts/triggerable_lint.py`).

## Goal

An **LLM judge (local qwen)** that reviews PRs touching CronJobs labelled
`homelab.mcp/triggerable: "true"` against the *triggerable contract*, catching the
**contextual** violations the deterministic lint cannot — subtle non-idempotency,
time-sensitivity, conditional/contextual destruction (e.g. a bare `rm "$f"` that's
dangerous here but benign there). It posts a structured verdict to the PR and, on
any flag, blocks + escalates to a human.

**Secondary goal (the real point):** a rigorous **EVAL** so we measure what qwen
actually brings — precision/recall on a labelled case set, not vibes. This is also
the "my box reviews my GitHub PRs" exercise.

## The contract being judged (6 criteria)

1. **Idempotent** 2. **Concurrency-tolerant** 3. **Time-insensitive**
4. **Bounded** 5. **Quota-safe** 6. **Fails-safe**

The deterministic lint already covers the *certain* slice of 1/2/3/4 (rm -r,
rsync/find `--delete`, SQL DROP/TRUNCATE, mkfs, dd; writable shared NFS/PVC mount
without a lock; missing `activeDeadlineSeconds`). The judge covers the *reasoning*
slice the regex can't prove.

## Architecture

```
parse (reuse lint's extractor)
  → build prompt (contract + job script + jobTemplate spec)
  → qwen via `oc run` in TEXT-GEN mode (structured JSON between markers, NO tool calls)
  → parse {verdict, findings[]}
  → post PR review via gh
  → on fail: request-changes + `triggerable-review` label (human = final authority)
```

**Hard constraint (banked lesson):** drive qwen headless as a *pure text generator*
— spec/job inline, output between explicit markers on stdout, orchestrator does the
I/O. qwen3 emits malformed text-format tool calls headless and stalls. (See
`.claude/skills/coding-agent-ops/SKILL.md` "Headless `oc run` writes no files".)

## Key decisions (confirm before/at Phase 1)

- **Execution model:** MVP = **local script driven by `oc`** (`scripts/triggerable-judge.py`),
  run on-demand against a PR number. Graduate to a **self-hosted GitHub Actions runner
  on the Beelink** once quality holds. → *recommend local-first.*
- **Model:** prototype on **30B (family-mode, no disruption)** first; A/B against
  **Q8 (work-mode, sole-tenant)** — concurrency reasoning is the hard part, likely where
  Q8 wins. → *run both, measure on the eval set.*
- **Severity:** any criterion fail → PR comment + `triggerable-review` label +
  request-changes. Human stays the merge authority; the judge is advisory + tripwire.

## Phased plan

### Phase 0 — Eval set (build the ruler first) ✅ DONE (2026-06-08)
Built under `eval/` — 15 labelled cases (`expected.yaml`), 7 synthetics
(`synthetic/`), and `score.py` (grades the live lint baseline + a judge output,
self-checks the `lint:` labels). See `eval/README.md`.

**Lint-baseline result (the bar to beat): precision=1.00, recall=0.50.** Zero
false-blocks on the PASS set; the 5 judge-only cases (11 idempotency, 12 quota,
13 concurrency, 14 time, 15 import-resolver borderline) are isolated as exactly
what the judge must catch. The judge's target: recall→1.00 without dropping
precision below 1.00, naming the right violated criteria.

<details><summary>Original Phase 0 spec</summary>

Curate labelled cases — real cluster jobs + synthetics — each = `cronjob YAML +
expected verdict + which criteria should flag`:
- **PASS:** `clusters/pi-k3s/renovate/cronjob.yaml`; `media/orphan-sweep-cronjob.yaml`
  (report-only, `readOnly: true`); a synthetic job that takes a proper `flock`.
- **FAIL:** the 5 rsync `--delete` backups (`backup-jobs/{backup,git-mirror,media-backup,
  worker2-backup}-cronjob.yaml` — concurrency/idempotency); a **synthetic orphan-sweep
  delete-mode** (writable mount + `find -delete` → time-sensitive + destructive); a job
  that **appends to a cumulative file** (idempotency); a job hitting a **rate-limited API
  in a loop** (quota).
- **BORDERLINE:** `media/import-resolver-cronjob.yaml`.
- Build a **scorer**: run the judge over the set, compare to expected, report
  precision/recall + per-criterion hits/misses. The deterministic lint is the baseline
  to beat (it already catches the 5 rsync jobs; the judge must add the ones it *misses* —
  orphan-sweep-delete-mode, the append-cumulative idempotency case — without
  false-blocking the PASS set).

</details>

> **Phase 0 deviations from the original spec, and why:** (1) the "append-to-a-
> cumulative-file" idempotency case is realised as **case 11 duplicate-INSERT
> rollup** — an *external-DB* append rather than a file, because a writable file
> mount would trip the lint and stop being a judge-only case. Same lesson, kept
> lint-blind. (2) Added two more judge-only cases beyond the plan — **13 external
> read-modify-write** (pure concurrency) and **14 stale-window reprocess** (time +
> idempotency) — so all of the contract's reasoning criteria (idempotency,
> concurrency, time, quota) each get a dedicated lint-blind case. (3) Added **05
> idempotent-upsert** and **03 postgres-backup** as precision traps (near-identical
> to a FAIL case but actually safe) so the judge is tested on *discrimination*,
> not just detection.

### Phase 1 — Judge harness (local) ✅ DONE (2026-06-08)
- `scripts/triggerable-judge.py` — builds the contract prompt from a manifest,
  drives qwen via `oc run` in pure text-gen mode (CoT prose + a JSON verdict
  between `===VERDICT-BEGIN/END===` markers, no tool calls), parses the verdict,
  emits the score.py JSON, and can `--score` in one shot. Flags: `--eval`,
  `--id <case>`, `--dry-run`, `--model`, `--timeout`, `--out`, `--raw-dir`.
- **Shared parser extracted** to `.github/scripts/cronjob_parse.py`
  (`script_text`, `writable_shared_volumes`, `job_spec_of`, `iter_cronjobs`,
  `TRIGGERABLE_LABEL`); lint refactored to import it — verified behaviour-preserving.
- **Smoke test:** case 11 (idempotency, judge-only) → `fail`/`idempotent` in ~15s
  on 30B, citing the duplicate `INSERT`. Genuine 6-criterion CoT, clean markers,
  `oc_returncode 0` — the pure-text-generator framing held (no malformed tool calls).
- **Fairness fix:** de-telegraphed synthetic inline comments (removed `# BUG:` /
  "double-counts" tells) so the judge must reason from code, not read the verdict
  off a comment. The pedagogical "why" lives in the YAML header + expected.yaml
  (both stripped by the parser, invisible to the judge).

### Phase 2 — Prompt + model iteration 🔄 IN PROGRESS (30B; Q8 A/B pending)
- **Adversarial concurrency framing:** ask qwen to *construct a sequence where two
  overlapping runs corrupt state* (try to break it), not "is it safe?". Per-criterion
  verdicts with evidence. ✅ in the v1 prompt.
- Run against the eval set; tune the prompt; A/B 30B vs Q8 (`aimode work`/`family`); pick.

**v1 → v2 (30B), measured on the eval set:**

| predictor | precision | recall | judge-only |
|---|---|---|---|
| lint baseline | 1.00 | 0.50 | 0/5 |
| judge v1 | 0.90 | 0.90 | 4/5 |
| judge v2 | 1.00 | 0.90 | **5/5** |
| **lint OR judge v2 (ships)** | **1.00** | **1.00** | **5/5** — all DoD PASS |

v2 prompt changes (all in `scripts/triggerable-judge.py`):
1. **Dropped `bounded`** from the judge's criteria — the lint owns that deterministic
   check as a WARN; grading it in the LLM only produced a false-block (v1 failed
   postgres-backup on it alone) + criterion noise.
2. **Hard no-execution banner** — v1's orphan-sweep-report case made the model *run*
   the script (tools fired → permission reject → no verdict). v2 frames the script as
   inert quoted data, no tools.
3. **Sharpened quota criterion** — external/public API vs internal `*.svc.cluster.local`,
   "about call volume not read-vs-write". Caught the previously-missed quota-burn case.
4. **Conservative criteria attribution** — list only primary, provable violations.

**Findings carried forward:**
- The judge is **stochastic**: `06-pvc-backup` flip-flopped fail→pass across runs (it
  found the same-date-dir hazard then rationalised it). Harmless here — the lint blocks
  all `--delete` backups deterministically — but it dictates a **fail-safe operational
  policy: judge N times, any fail/flag wins.** Don't overfit the prompt to a stochastic
  miss the lint already covers.
- The judge's recall-critical slice is the **judge-only cases (11–15)** — the only ones
  with no deterministic backstop. Their across-run **stability** is what the combined
  system's recall actually rests on; measure it (×N) before trusting the 1.00.
- **Per-criterion** labels still noisy (0.69/0.61) — verdict gates escalation; criteria
  are advisory until tightened.
- **Q8 A/B still pending** — the borderline concurrency reasoning (06-style) is the most
  likely place a bigger model reduces variance; the combined system already hits 1.00, so
  Q8 is about judge robustness, not closing a gap.

**Stability run (30B, judge-only cases ×5, `--repeat 5`):**

| case | 5 runs | reliable? |
|---|---|---|
| 11 duplicate-insert | `fail fail fail fail fail` | solid |
| 13 counter-rmw | `fail fail fail fail fail` | solid |
| 14 stale-window | `fail fail fail fail fail` | solid |
| 12 quota-burn | `fail fail fail flag fail` | unstable but 5/5 escalate |
| 15 import-resolver | `flag pass fail fail pass` | **2/5 pass — shaky** |

- Clear-cut contextual violations (11–14): 19/20 fail + 1 flag, **zero passes** — the judge
  is reliable on unambiguous hazards.
- The **borderline** case (15, import-resolver): ~40% single-run `pass` rate. The model can
  see the double-POST (3/5 runs) but doesn't reliably engage it. Its own uncertainty IS the
  signal — that's what `flag` means.
- **Operational conclusion (now load-bearing):** single-run judging is UNSAFE for borderline
  cases. The standard invocation must be **`--repeat N`, any-fail-wins** — over 5 runs even the
  40%-pass case escalates ~99% of the time (P(all pass)=0.4⁵≈1%). `--repeat` aggregate already
  escalated both 12 and 15 despite the wobble. Criteria labels remain noisy (union across runs);
  the verdict is the reliable signal.

### Phase 3 — PR integration ✅ DONE (2026-06-08) — code built, awaiting deploy
- `--pr <n>` / `--local-diff <base>`: select the changed triggerable CronJobs,
  judge each (multi-vote), post a verdict comment, exit non-zero on any fail/flag
  (the merge gate). `--local-diff` flow verified end-to-end structurally.
- **Forge-agnostic** via a thin adapter (the user's "agnostic to GitHub vs local
  GitLab" ask): `GitHubForge` (REST API + urllib — no `gh`/node, so a stock runner
  needs only python3), `LocalGitForge` (git diff → stdout). `GitLabForge` is a future drop-in.
- **LiteLLM HTTP backend** (`--backend litellm`): the judge calls the Beelink
  directly (no `oc`/opencode — pure text-gen by construction). Verified reachable
  (clean 401 with a bogus key). `--backend oc` stays the macOS local-dev path.
- **Fail-safe block:** only a clean `pass` clears; fail/flag/error all escalate, so a
  model timeout or unparseable run can never silently wave a hazard through.

### Phase 4 — reactive review-hub receiver 🔧 BUILT (2026-06-08), deploy-gated
Two course-corrections from the user reshaped this (see RECEIVER.md, the durable doc):
- **Not the Beelink → in-cluster** (calls the Beelink LiteLLM like local-llm-mcp).
- **Not per-repo runners/PATs → one GitHub App** (installed all-repos, mints per-repo
  tokens). Credentials scale with bot-roles, not repos. The runner scaffold was retired
  (uncommitted) — the ARC/simple-runner path with it.
- **Not GH Actions → a webhook receiver** (the forge-agnostic, multi-evaluator end-state;
  reactive via GitHub webhook → Cloudflare Tunnel; no inbound creds beyond the App).

Built + verified: `scripts/reviewhub/` (`github_app.py` JWT→token [App auth verified live —
app id 3998878, sees all 45 repos], `evaluators.py` registry, `receiver.py` HMAC+dispatch
[HMAC tested]) + `Dockerfile`/`VERSION` + `.github/workflows/build-review-hub.yml` (GHCR
multi-arch) + `clusters/pi-k3s/review-hub/` (ns, ExternalSecret, Deployment, Service,
image-automation, kustomization) + Flux Kustomization #29 + the `review-hub.mtgibbs.dev`
path-locked Tunnel route. 1Password `review-hub` item ready (App creds + webhook secret +
scoped LiteLLM key, all live). Deploy: commit/push → flip GHCR public → DNS → set App webhook
URL → required check. Q8 A/B still deferred.

### Framework (the user's "many evaluators / many bots" ask) — REALISED
Identity: ONE GitHub App per bot-role, all-repos, per-repo tokens on demand — never a
token-per-repo. Execution: one in-cluster receiver dispatches to an evaluator REGISTRY
(`scripts/reviewhub/evaluators.py`: pi-cluster→triggerable; pi-cluster-mcp→evaluator #2 TBD).
Forge adapter (`GitHubForge` API/no-checkout, `LocalGitForge`; GitLab/Gitea = add a forge +
webhook parser). A new repo = zero new creds; a new evaluator = a registry entry. Reusable
engine (backends/parse/aggregate/forge) still in `triggerable_judge.py` — extract to a shared
lib when evaluator #2 lands.

## Definition of done (prototype)
- Eval set ≥ ~10 cases; the scorer reports precision/recall + per-criterion accuracy.
- On the eval set the judge catches the FAIL cases the deterministic lint **misses**
  (esp. orphan-sweep-delete-mode and the append-cumulative idempotency case) with **no
  false-blocks** on the PASS set — *or* we learn exactly where qwen falls short (itself a
  useful, publishable result for the homelab notes).
- `triggerable-judge.py --pr <n>` runs end-to-end and posts a verdict.

## Dependencies / pointers
- Lint parser to reuse: `.github/scripts/triggerable_lint.py` (in pi-cluster).
- Local agent: `.claude/skills/coding-agent-ops/SKILL.md` — `oc run` text-gen mode,
  `OC_RUN_TIMEOUT`, redirect-to-file; `aimode work`/`family` for Q8/30B.
- Contract + tool-side gate (context): pi-cluster-mcp PR #32 (label gate + guard A);
  `clusters/pi-k3s/*/...` CronJobs; this lint's severities.
- SDD method: `specs/README.md`, `specs/TEMPLATE.md`.
