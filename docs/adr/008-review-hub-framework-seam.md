# ADR-008: review-hub as a Reusable Framework — Seam Definition and Spin-off Plan

## Status
Accepted

## Date
2026-06-10

## Context

review-hub started as a single-purpose CronJob safety gate for this repo. It has since grown
into a 10-validator roster, a multi-repo opt-in surface, an eval methodology, and a
deployment harness:

- **Webhook receiver** (`scripts/reviewhub/receiver.py`) — GitHub App POSTs `pull_request`
  events via Cloudflare Tunnel; HMAC-verified, ack-fast, background dispatch.
- **Validator convention** (`scripts/reviewhub/validators/`) — each validator answers ONE
  question (`name`, `concern`, `repos`, `globs`, `applies_files()`, `review()`).
- **Two-sided opt-in handshake** (`validators_for(repo, files, opted_in)`) — a repo commits
  `.review-hub.yml` on its default branch listing validator names; a validator declares which
  repos it is valid for. Both conditions must hold, plus file-glob matching.
- **Eval-first methodology** (`specs/validators/<name>/{contract.md, eval/expected.yaml,
  eval/score.py}`) — every validator is measured against a labelled case set before it ships.
  All 10 validators are at precision 1.00 / recall 1.00 on reps=5/majority.
- **Identity** — one GitHub App ("review-bot", app id 3998878) installed across all repos;
  per-repo installation tokens minted from the webhook payload's `installation.id`. No
  per-repo credential storage.
- **LLM backend** — Beelink LiteLLM at `https://ai.lab.mtgibbs.dev/v1`, model `hot-coder`,
  `JUDGE_REPEAT=5`, `LITELLM_MAX_TOKENS=2000`, `LITELLM_TEMPERATURE=0.4`.
- **Deployment** — `clusters/pi-k3s/review-hub/` Flux manifests; Flux image-automation
  auto-bumps the GHCR image; current version: `0.5.0`.

At v0.5.0, review-hub has a clear **config surface**: repos opt in, validators declare scope,
the harness engine and the per-instance bindings are separable. A second consumer (a different
cluster or a different repo set) could reuse the engine without touching any instance-specific
config. The seam exists in the code already; this ADR names it.

### The family-board precedent

The family-board UI lives as a self-contained subtree at `clusters/pi-k3s/family-board/`
with its own `CLAUDE.md`, `.claude/skills/`, and `.claude/agents/board-designer`. It is
"slated to spin off" once a second consumer exists, but has not been extracted — premature
extraction is maintenance cost with no payoff. review-hub will follow the same pattern.

## Decision

**Draw the framework/instance seam now. Defer the repo-split until a second consumer earns it.**

### The seam

| Side | What lives there | Rule of thumb |
|---|---|---|
| **Portable (framework)** | Judge harness: `scripts/triggerable_judge.py`, `scripts/reviewhub/receiver.py`, `github_app.py`, `reporting.py` | Would a different cluster use this unchanged? |
| **Portable (framework)** | Validator convention: the `applies_files()` / `review()` protocol, the two-sided handshake (`validators_for`), the `REGISTRY` dispatch loop | Yes — the handshake design is cluster-agnostic. |
| **Portable (framework)** | Eval-first methodology: `specs/validators/<name>/{contract.md, eval/expected.yaml, eval/score.py}` + the gauntlet runner | This is a *way of making* gates, not a gate. The most transferable asset. |
| **Portable (framework)** | Starter validator library: `secret-hygiene`, `no-false-green`, `output-bounds`, `input-validation`, `fail-closed` — generic concerns any LLM-tool repo would want | The concern is general; only the `repos`/`globs` binding is instance config. |
| **Instance config** | LLM endpoint + model: `LITELLM_BASE_URL`, `JUDGE_MODEL`, `JUDGE_REPEAT`, `LITELLM_MAX_TOKENS`, `LITELLM_TEMPERATURE` | Names *this* Beelink. |
| **Instance config** | GitHub App identity: app id 3998878, private key in 1Password `review-hub` item | Names *this* App. |
| **Instance config** | Deployment manifests: `clusters/pi-k3s/review-hub/` (namespace, ExternalSecret, Deployment, Service, image-automation, Kustomization), Cloudflare Tunnel route | Wired to *this* cluster. |
| **Instance config** | Roster bindings: each validator's `repos` set and `globs` list; each repo's `.review-hub.yml` opt-in | Names *these* repos. |
| **Instance config** | Validators specific to this cluster's concerns: `triggerable-judge`, `gate-regression`, `mutation-gating`, `concurrency-safety`, `read-only-integrity` | Concern is pi-cluster-mcp-shaped. |

### The seam test (litmus)

> "Would a different cluster reviewing different repos reuse this unchanged?"
>
> - Yes → framework (portable side of the seam).
> - Names *this* Beelink / *this* App / *this* repo → instance config (stays per-cluster).

### Evidence the seam was already real before this ADR

1. **Credentials scale by role, not repo.** One GitHub App identity mints per-repo tokens on
   demand from the webhook payload. A new consumer repo costs zero new credentials. This was a
   deliberate design choice (`feedback_credentials_scale_by_role`), not a side-effect.

2. **Validator concern vs. binding is already split in code.** A validator's `concern` string
   and `review()` logic are generic. Its `repos` set and `globs` list are the only
   instance-specific fields. The `validators_for()` handshake enforces the split — the engine
   never consults per-instance config outside those two fields.

### Make it portable in-place (the family-board treatment)

Before any repo-split, the in-place work that makes extraction low-friction:

1. Ensure validator modules in `scripts/reviewhub/validators/` that belong to the **starter
   library** (generic concerns) are clearly separated from those that are **pi-cluster-specific**
   (by comment in `validators/__init__.py`, or by a subdirectory split if the roster grows).
2. Keep `specs/validators/` as the canonical home for eval artifacts — they travel with the
   framework, not with the deployment manifests.
3. Keep instance config (LLM env, App id, `repos`/`globs` bindings) in `receiver.py` env vars
   and the Flux manifests only — nothing instance-specific should be hardcoded inside a
   "portable" module.

### Deferred extraction trigger

> Extract review-hub to its own repo when a **second repo or cluster** wants the harness.

Until then, the code stays here. The value of the seam is that extraction will be mechanical
(move the portable side, leave the instance config, update import paths) rather than a
design exercise.

### Pending framework-grade feature: rollup Check Run

An always-on "review-hub" summary Check Run posted by the receiver itself (not per-validator)
would enable **hard-required branch protection** on consumer repos: require the rollup by name,
and all opted-in validators are implicitly required without needing to enumerate them in branch
protection settings. This belongs on the **portable side** — it is receiver-level reporting
infrastructure, not instance config. It is the blocking item for flipping pi-cluster-mcp's
branch protection from soft (PR + CI required) to hard (gates required).

## Consequences

### Positive

- The seam is named and documented before a second consumer arrives, so extraction stays
  mechanical when it happens.
- Eval-first methodology is explicitly recognized as the most transferable asset — it is a
  discipline for building LLM gates, not a gate itself.
- The starter validator library (generic concerns) is identified so future contributors know
  which validators belong in a shared layer.
- The rollup Check Run is scoped as a framework feature, clarifying why it belongs in the
  receiver rather than being solved per-instance.

### Negative

- No immediate payoff. The seam is conceptual until a second consumer exists.
- Maintaining the in-place distinction (portable vs. instance) requires discipline — it is
  easy to let instance-specific concerns creep into what should be generic modules.

### Risks

- If the roster grows significantly before extraction, the in-place distinction may blur.
  Mitigated by keeping the `repos`/`globs` binding as the only allowed instance-specific
  fields inside a validator module.

## Alternatives Considered

### Extract immediately into a shared repo

- Pro: Forces the seam clean right now.
- Con: No second consumer exists. Maintaining two repos without a second consumer is overhead
  with no payoff. The family-board precedent counsels against premature extraction.

### Leave the seam implicit (don't document it)

- Pro: No documentation work.
- Con: The next person to extend the roster or onboard a second consumer has to rediscover the
  seam. The family-board pattern showed the value of naming the boundary before it is needed.

### Define a formal plugin registry (interface + discovery)

- Pro: Maximally extensible.
- Con: Overengineered for a two-consumer horizon. The current `REGISTRY` list in
  `validators/__init__.py` plus the validator protocol (`name`, `concern`, `repos`, `globs`,
  `applies_files()`, `review()`) is sufficient. Design-for-two, not design-for-N.
