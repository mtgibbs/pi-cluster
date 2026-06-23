# Spec: `dependency-update` validator — advisory Renovate-PR risk review

- **Status:** Planned v0.1 (advisory phase; OQ1 resolved)
- **Owner:** Matt (orchestrated by Claude; judged by the Beelink Q8 = review-hub `hot-coder`)
- **Constitution:** `specs/constitution.md` (+ `/CLAUDE.md` Core Mandates); framework seam: `docs/adr/008-review-hub-framework-seam.md`
- **Touches:**
  - `scripts/reviewhub/validators/dependency_update.py` *(new — the validator)*
  - `scripts/reviewhub/validators/__init__.py` *(edit — add to `REGISTRY`)*
  - `specs/validators/dependency-update/contract.md` *(new — the prompt template)*
  - `specs/validators/dependency-update/eval/{expected.yaml,score.py}` *(new — the eval gate)*
  - `scripts/triggerable_judge.py` *(edit — add `GitHubForge.pr_meta()` + `LocalForge.pr_meta()`)*
  - `.review-hub.yml` *(edit — opt `mtgibbs/pi-cluster` into `dependency-update`)*

---

## 1. Why · [R — Requirements]

Renovate (self-hosted CronJob, `automerge: false`) opens dependency-bump PRs against this repo —
there's a standing backlog (#3, #4, #8, #9, #20, #21). Today each is triaged by hand off the
dependency dashboard. We want the review-hub Q8 to read each Renovate PR's **version delta + the
changelog Renovate embeds in the PR body** and post an **advisory** risk read — *safe-to-merge* vs
*needs-a-human* — so routine bumps are obvious and risky ones (major / breaking / critical-path) are
called out. **Advisory only this phase: it never blocks the merge.** Gating comes later, once the
eval and a few weeks of real calls earn it.

## 2. Outcomes (Definition of Done) · [R — Requirements]

1. On a Renovate PR, a `dependency-update` Check Run + the consolidated report show a verdict
   (✅ `pass` = safe / ⚠️ `flag` = review) with reasons drawn from the changelog.
2. It **never blocks** — `any_block` is False on every path; `automerge` stays `false`; you still merge.
3. Non-Renovate PRs are untouched by this validator.
4. It is **eval-gated** (§11) before `.review-hub.yml` opts in — like the other 10 validators.
5. Built so flipping to **gating** later is just: set `any_block` on `flag`, require the check, flip
   Renovate `automerge` for patch/minor. No redesign.

## 3. Entities · [E — Entities]

- **PR metadata** — new `forge.pr_meta()` returns: `{title, body, user, head_ref, labels}` (one cached
  API call: `GET /repos/{repo}/pulls/{number}`). `head_ref` is the branch (Renovate signal); `body`
  carries the changelog.
- **Model verdict** (JSON between `tj.BEGIN`/`tj.END`):
  `{"verdict": "pass"|"flag", "findings": [str], "risk": {"bump": "patch"|"minor"|"major"|"calver"|"digest"|"unknown", "breaking": bool, "critical_component": bool}}`
- **Eval case** (`eval/expected.yaml`): `{id, file, diff, changelog, branch, expected: "pass"|"flag"}` —
  note the **`changelog`** field (the simulated PR body) is new vs other validators' diff-only cases.

## 4. Approach · [A — Approach]

Mirror `scripts/reviewhub/validators/output_bounds.py` (a starter-library validator) — same class shape
(`name`/`concern`/`repos`/`globs`/`applies_files`/`review`), same `tj.judge_changes` + `aggregate`
reuse, same `contract.md`-with-`{{INPUT}}` prompt. **Three deltas:**

1. **Feed the changelog.** `review()` calls the new `forge.pr_meta()`, and `build_prompt(changes, changelog)`
   includes the PR-body changelog alongside the version-bump diff (the diff alone is just `-tag:5.2.1`/
   `+tag:5.2.2` — the changelog is where the risk lives).
2. **Renovate-gate on branch.** Only assess when `head_ref` starts with `renovate/`. (All Renovate PRs
   here are authored by `mtgibbs` via the PAT, so author detection is useless — branch prefix is the
   reliable signal.) Non-Renovate → `([], False, None)`.
3. **Advisory.** `any_block` is **always False**; verdict ∈ {`pass`,`flag`} (never `fail`). A `flag`
   surfaces as ⚠️ attention in the report, not a failing/blocking check.

Rejected: a standalone Q8/`oc` script that lists+comments on Renovate PRs — it would duplicate
review-hub's webhook, GitHub-App identity, Check-Run reporting, and eval machinery. This is a
starter-library concern (per ADR-008): generic to any Renovate repo; only `repos`/`globs` are instance config.

## 5. Scope · [S — Structure: boundary]

### In scope
- The new validator module + its `contract.md` + eval set.
- The `forge.pr_meta()` framework addition (portable side).
- `REGISTRY` entry + `.review-hub.yml` opt-in.

### Out of scope
- **Do NOT flip Renovate `automerge`** or touch `renovate.json` — that's the gating phase.
- **Do NOT add/require branch protection** or the rollup-check change — gating phase.
- **Do NOT modify the receiver's dispatch**, other validators, or other repos' opt-in.
- **Do NOT make this a blocking gate** — `any_block` stays False this phase (the §8 invariant).
- **Do NOT review mechanical validity** (does the tag exist / does YAML parse) — that's Renovate + Flux.
  This validator answers ONE question: *is the bump risky enough to need a human?*

## 6. Prior decisions / facts the implementer must know · [S — Structure: system fit & deps]

- **Validator class contract** (copy `output_bounds.py`): class attrs `name` (str), `concern` (str),
  `repos` (set), `globs` (list); `applies_files(self, files)` → bool (fnmatch any); `review(self, forge,
  reps, timeout, model, raw_dir)` → `(results_list, any_block_bool, body_or_None)`. No changes →
  `([], False, None)`. Judge with `tj.judge_changes(changes, "litellm", model, timeout, raw_path)`;
  `aggregate(runs)` for reps>1; markers `tj.BEGIN`/`tj.END`.
- **`res["block"]`** in the others is `verdict != "pass"`. **HERE it must be hard-coded False** (advisory).
- **Receiver flow** (`scripts/reviewhub/receiver.py`): GitHub App → webhook (`opened`/`synchronize`/
  `reopened`) → `validators_for(repo, changed_files, opted_in)` → each validator's `review()` →
  per-validator Check Run + one consolidated report comment + a rollup check. The validator never
  touches the webhook/token path.
- **`forge` is `tj.GitHubForge`** with: `changed_files()`, `changed_patches()`, `get_file()`,
  `post_review()`, `upsert_comment()`, `create_check_run()`, `complete_check_run()`. **It has NO PR-body
  accessor today** — add `pr_meta()` (and a `LocalForge.pr_meta()` reading a case fixture for eval/dev).
- **Renovate setup:** self-hosted CronJob (`clusters/pi-k3s/renovate/`, image `renovate/renovate:43`),
  `automerge: false`, `dependencyDashboard: true`, `extends: config:recommended`. Manages Docker image
  tags + Flux/k8s manifests under `clusters/pi-k3s/**`. Branches are always `renovate/*`.
- **OQ1 RESOLVED — the changelog IS in the PR body.** Confirmed on live PR #21: the body has a package
  table (`4.94.0 → 4.103.0`) and a **`### Release Notes`** `<details>` block with the real changelog
  (e.g. "export has been removed … update your import"). **CAVEAT: Renovate truncates large bodies**
  ("This PR body was truncated due to platform limits") — the validator must handle truncation: judge on
  what's present, and **lean `flag` if the body is truncated** (incomplete info on a non-trivial change).
- **`hot-coder` = the Q8** while `aimode work` is set (this validator's judge). Backend `litellm`,
  `JUDGE_REPEAT=5`, `LITELLM_TEMPERATURE=0.4`, endpoint `https://ai.lab.mtgibbs.dev/v1`.
- **Critical-path components (always `flag`, even patch/minor)** — a wrong bump here breaks the cluster:
  `cert-manager`, ingress/`traefik`, `flux`/`fluxcd`, `pihole`/`unbound` (DNS), `postgres`/`postgresql`,
  any CSI/storage driver, CNI. (Finalize the literal list in `contract.md` from the repo's managed images — OQ2.)
- **App identity:** review-bot, app id 3998878; per-repo install token minted from the webhook payload.
  No new credential for this validator.

## 7. Norms · [N — Norms]

- **Mirror `output_bounds.py`** style/structure; reuse `tj.judge_changes`/`aggregate`/`MODEL_DEFAULT`.
- **Prompt in `contract.md`** with `{{INPUT}}`; output `tj.BEGIN`/`tj.END` + the §3 JSON.
- **Findings: ≤6, specific + actionable** — name the version delta and the changelog reason and what to
  check: e.g. `"minor bump but changelog removes the public export X — verify nothing here imports it"`,
  not `"might be risky"`.
- **One concern only:** risk triage. Not style, not "does the tag exist", not mechanical validity.
- **Conservative under uncertainty:** truncated/absent changelog on a non-patch bump → `flag`.

## 8. Safeguards · [S — Safeguards]

- **ADVISORY INVARIANT:** `review()` returns `any_block=False` on EVERY path; verdict ∈ {`pass`,`flag`}
  (never `fail`). It can never block a merge this phase. (verify: §11 static + the eval expectations)
- **Renovate-only:** assess only when `head_ref` starts `renovate/`; otherwise `([], False, None)`.
- **Read-only to the repo:** posts Check Runs / the report comment via `forge` only — never edits content,
  never approves, never merges. (Advisory; no write/merge call exists in the module.)
- **No secrets:** uses the App installation token via `forge`; no inline tokens; never echo secrets.
- **Eval-gated:** `.review-hub.yml` opt-in (T5) is committed ONLY after the eval (§11) passes its thresholds.
- **Cost bound:** judged at `JUDGE_REPEAT=5` like the others; `LITELLM_MAX_TOKENS=2000`.

## 9. Task breakdown · [O — Operations]

1. **T1 (framework):** add `GitHubForge.pr_meta()` (`GET /repos/{repo}/pulls/{number}` → cached
   `{title, body, user, head_ref, labels}`) + `LocalForge.pr_meta()` (reads the case's `branch`/`changelog`
   fixture) to `scripts/triggerable_judge.py`.
2. **T2 (validator):** `dependency_update.py` — class + `build_prompt(changes, changelog)` + `parse` +
   `aggregate` + `review()` (Renovate gate, changelog fetch, advisory `any_block=False`) + CLI `main()`
   for `--eval`/`--id` (mirror output_bounds).
3. **T3 (contract):** `contract.md` prompt template (§13 draft) with `{{INPUT}}`.
4. **T4 (eval):** `eval/expected.yaml` (seed from the 6 open PRs + synthetic clear-cut cases) + `eval/score.py`
   (reuse an existing validator's scorer).
5. **GATE:** run T4 to threshold (§11) BEFORE T5.
6. **T5 (wire):** add to `validators/__init__.py` `REGISTRY`; add `dependency-update` to `.review-hub.yml`.
7. **T6 (deploy):** GHCR image bump via the existing Flux image-automation (no manual deploy).

Order: T1 → T2/T3 → T4 → **gate** → T5 → T6.

## 10. Acceptance criteria (EARS) · [O — Operations made testable]

- **A1 (Event):** When a PR's `head_ref` starts `renovate/` and a changed file matches `globs`, the
  validator shall judge the version-bump diff + the PR-body changelog and emit a verdict.
- **A2 (Unwanted):** If `head_ref` does not start `renovate/`, the validator shall return `([], False, None)`.
- **A3 (Ubiquitous):** The validator shall return `any_block=False` on every path (advisory).
- **A4 (Event):** When the bump is patch/minor (or CalVer/digest) on a non-critical component with no
  breaking/migration/security/removal note in the changelog, the verdict shall be `pass`.
- **A5 (Event):** When the bump is major, OR the changelog signals a breaking change / required migration /
  removed-or-renamed API / security advisory, OR the package is a critical-path component (§6), OR the body
  is truncated on a non-patch bump, the verdict shall be `flag`, with findings naming the reason.
- **A6 (Ubiquitous):** The verdict shall be one of `pass`|`flag` (never `fail`).
- **A7 (State):** While run at `--repeat 5` majority, the validator shall meet the §11 thresholds.

## 11. Verification (the harness)

**LIVE / eval — the real gate** (`dependency_update.py --eval --backend litellm --repeat 5 --out … --score`):
- **Recall on `flag` cases = 1.00** — the cost is asymmetric; **never miss a risky bump** (a missed major/
  breaking is a bad merge; a false flag is one human glance). This is the primary bar.
- **Precision on `flag` ≥ 0.85** — limit alert fatigue (don't flag routine patches).
- Aim for the roster norm (1.00/1.00) but recall-on-flag is non-negotiable.

**Seed eval cases** (T4 fills `expected.yaml`; live PRs give real bodies):
| id | bump | expected | why |
|---|---|---|---|
| qbittorrent-5.2.1-5.2.2 (#20) | patch | `pass` | bugfix patch, non-critical |
| cloudflared-calver (#9) | calver patch | `pass` | routine monthly CalVer |
| sabnzbd-5.0.x (#8) | patch | `pass` | non-critical patch |
| wrangler-4.94-4.103 (#21) | minor | `flag` | changelog removes public exports ("update your import") |
| alpine-3.23-3.24 (#3) | base-image minor | `flag` | base-image bump can shift many pkgs; truncation-prone |
| postgres-15-16 (synthetic) | major | `flag` | breaking on-disk format / dump+restore migration |
| cert-manager-minor (synthetic) | minor | `flag` | critical-path component |
| ntfy-2.23-2.24 (#4) | minor | `pass` | non-critical, additive changelog |
| servarr-bundle-major (synthetic) | major group | `flag` | grouped major bundle |

**STATIC `verify.sh`** (offline): the module imports + is in `REGISTRY`; has `name/concern/repos/globs/
applies_files/review`; `contract.md` contains `{{INPUT}}`; `eval/expected.yaml` parses and every case's
`expected` ∈ {`pass`,`flag`}; `.review-hub.yml` lists `dependency-update`; `triggerable_judge.py` defines
`def pr_meta`; **advisory invariant** — the module never returns a truthy `any_block` (grep: no
`return .*True` in `review`; `res["block"]`/any_block hard-set False) and the parser/contract restrict
verdicts to `pass|flag`.

## 12. Open questions

- **OQ1 (RESOLVED):** Changelog in the PR body? **Yes** — `### Release Notes` block (see §6). Truncation
  caveat handled by leaning `flag`.
- **OQ2:** Finalize the literal critical-component list in `contract.md` against the repo's actually-managed
  images. Draft in §6; confirm during T3.
- **OQ3:** Digest-only / lockfile-only bumps (e.g. #21 is `*-lockfile`) — default `pass` unless major or the
  changelog flags breakage. Confirm the rule reads cleanly in `contract.md`.
- **OQ4:** Does `config:recommended` populate release notes for ALL datasources here (docker tags vs npm)?
  Docker-tag PRs may have a thinner body than npm. If a datasource yields no changelog, fall back to
  semver-only (major→flag, else pass). Verify against PRs #20/#8 (docker) during T4.

## 13. Plan — `contract.md` prompt (draft)

```
You are a release-risk reviewer for a GitOps homelab. You judge ONE Renovate dependency-bump PR and
decide whether it is SAFE to merge unattended or NEEDS A HUMAN. You are ADVISORY — you never block.

Decide from: (a) the version delta, (b) the changelog / release notes below. Rules:
- patch / minor / CalVer / digest, non-critical component, no breaking-or-removal-or-migration-or-security
  note  -> verdict "pass".
- major bump  -> "flag".
- changelog mentions a breaking change, removed/renamed public API, required migration, or a security
  advisory  -> "flag" (even on a minor).
- the package is a critical-path component (cert-manager, traefik/ingress, flux, pihole/unbound, postgres,
  storage/CSI, CNI)  -> "flag" even on patch/minor.
- the changelog is TRUNCATED or ABSENT on a non-patch bump  -> "flag" (incomplete information).
Findings: name the version delta + the specific changelog reason + what to check here. <=6, specific.

Output between {{BEGIN}} and {{END}}:
{"verdict":"pass|flag","findings":["…"],"risk":{"bump":"…","breaking":<bool>,"critical_component":<bool>}}

{{INPUT}}
```

## 11b. Loop execution (handing to a local model)

Decompose §9 into `tasks.txt`; run on a worktree branch. T1 (forge) and T3 (contract) are bounded single
edits; T2 is one file mirroring `output_bounds.py`; T4 is data + a reused scorer. The **eval (T4) is the
gate** — the model never self-certifies, and `.review-hub.yml` (T5) is committed only after §11 passes.
Candidate for a Q8 dogfood, with the eval set as the verifier this time.
