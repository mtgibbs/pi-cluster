# Specs — Spec-Driven Development for the homelab

This directory is where we practice **spec-driven development (SDD)**: the spec is
the primary artifact, and the implementation (YAML, scripts, Helm) is a *regenerable
output* of it. We write the spec first, agree on it, then execute against it — by hand,
with Claude, or by handing it to a local agent (qwen3-coder in a Ralph loop).

> Why: agents (and humans) drift when the target is fuzzy. A rigorous spec is the
> shared source of truth — it aligns us *before* code exists, and it's the thing a
> reviewer checks the diff against. (Sean Grove, OpenAI: code is a lossy projection
> of the spec; Geoffrey Huntley: "specs are the real asset.")

## The layers we adopted

| Layer | What | Where it lives |
|---|---|---|
| **Constitution** | Non-negotiable principles every spec inherits | `/CLAUDE.md` Core Mandates + memory feedback |
| **Spec** | Per-feature: outcomes, scope, constraints, EARS acceptance criteria, tasks | `specs/<feature>/spec.md` |
| **Plan** | Resolved unknowns + technical approach (fills the spec's open questions) | a `## Plan` section appended to the spec, or `plan.md` |
| **Execute** | Do the work, one task at a time | by hand / Claude / Ralph loop on qwen3 |
| **Verify** | Self-check harness + PR gate | `verify.sh` (per feature) + human PR review |

## The constitution (operative principles, summarized)

These are the non-negotiables every spec inherits — full text in `/CLAUDE.md`:

- **GitOps only** — changes go through Flux-managed YAML, never web-UI/manual edits.
- **Secrets via 1Password + ExternalSecrets** — never inline a secret value.
- **MCP-first** — use `mcp__homelab__*` tools over raw kubectl where one exists.
- **Public-by-default** — topology/config is not secret; only secrets are secret.
- **Agent work is PR-gated** — autonomous loops are permissive in a sandbox but
  reviewed at the repo boundary before they reach the cluster.

## Acceptance criteria use EARS

[EARS](https://alistairmavin.com/ears/) (Easy Approach to Requirements Syntax) — five
templates that make a requirement testable instead of vibey:

- **Ubiquitous:** The `<system>` shall `<response>`.
- **Event-driven:** When `<trigger>`, the `<system>` shall `<response>`.
- **State-driven:** While `<state>`, the `<system>` shall `<response>`.
- **Unwanted behavior:** If `<condition>`, then the `<system>` shall `<response>`.
- **Optional:** Where `<feature>`, the `<system>` shall `<response>`.

## Lifecycle

1. Write `spec.md` (Draft). Capture what's known; list unknowns as **Open Questions**.
2. **Plan**: resolve the open questions (look up real URLs, verify keys exist), record
   decisions back into the spec — it's a *living document*.
3. **Execute** against the task breakdown.
4. **Verify** with the harness, open a PR, review against the acceptance criteria, merge.

## Index

### In progress
- [`homepage-refresh/`](homepage-refresh/spec.md) — refresh the Homepage dashboard
  (arr status widgets, AI/chat section, Beelink telemetry). *First dogfood artifact; tuned
  through a Round-1 qwen3-coder eval (see its §11).*

### Backlog (ready for qwen3-coder)
- [`decommission-carl-pi-ollama/`](decommission-carl-pi-ollama/spec.md) — retire CARL and the
  Pi-side Ollama (overhead; CARL was Ollama's only consumer, inference moved to the Beelink).
  Destructive teardown — PR-gated.
