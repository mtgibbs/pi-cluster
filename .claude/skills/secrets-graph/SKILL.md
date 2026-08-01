---
name: secrets-graph
description: >
  START HERE before adding, reusing, or reasoning about ANY credential in the
  cluster. Walk the secrets connectivity graph (1Password item → ExternalSecret
  → k8s Secret → consuming workload) to answer "do we already have a cred for
  this?" and "what breaks if I rotate/delete this?" — instead of guessing and
  minting a duplicate.
---

# Secrets graph — the credential connective tissue

## When to load this

- **Before adding a secret to any service** — the #1 use. Someone (an agent, 2026-08)
  minted a `ghcr-pull` token when `ghcr-read-token` already did the job. This graph makes
  "we already have that" a one-glance answer.
- Answering **"what uses `<item>`?"** or **"what's the blast radius if I rotate/delete `<secret>`?"**
- Auditing for **orphaned** secrets (defined, consumed by nothing).

## The one rule

**Reuse before mint.** Shared *infrastructure* identities (pull images, send alerts, reach the
NAS, edit DNS) are **one-per-role**, not one-per-service. A new service *references* the existing
1Password item; it does not create a parallel token. Mint a new secret only for a genuinely
**per-workload** cred (this app's own DB password, its own scoped LiteLLM key — see the LiteLLM
note in `docs/secrets-map.md`, that separation is deliberate).

## How to walk it (30 seconds)

1. Open **`docs/secrets-map.md`**. The curated top half is roles/tiers/why; the
   `## Connectivity graph (auto-derived)` block is the exhaustive, always-fresh truth.
2. **"Do we already have a cred for X?"** → scan the **1Password items** list. If the item exists,
   **reuse it** (copy the pattern of an existing `ExternalSecret` that references it). Any item
   tagged `⟵ SHARED` is explicitly a reuse target — do NOT mint a parallel one.
3. **Blast radius** → find the ExternalSecret; every `→ <ns>/<workload>` line is something that
   breaks if the secret changes. (e.g. `synology_backup` fans out to 9 backup CronJobs.)
4. **Handling tier** badges (`safe` / `cluster-acting` / `crown-jewel`) say who may touch it.
   Crown-jewel stays biometric/laptop-only — never relocate it into a container.

## Keeping it true (no drift)

The graph is **generated**, so it can't rot:

```bash
node scripts/gen-secrets-graph.mjs clusters --inject docs/secrets-map.md
```

- Deterministic bytes per tree — re-running with no manifest change is a no-op. A CI/pre-merge
  check is just: run the command, then `git diff --exit-code docs/secrets-map.md`.
- Other modes: `--shared` (reuse-lens mermaid to stdout), `--json` (machine graph), default = node index.
- The generator is a **regex-per-document manifest walk** (no YAML-parser dependency, house idiom
  from `token-bench/gen-edges.mjs`). It sees ~90% of edges directly.

## The ~10% it can't see — `docs/secrets-overlay.yaml`

A pod-spec walk cannot see secrets consumed by a **HelmRelease `values:`**, a **Flux
`postBuild.substituteFrom`**, a **cert-manager ClusterIssuer** ref, or **app-internal config**.
Those consumers are curated in `docs/secrets-overlay.yaml` (also holds tier tags). If the graph
shows `⚠️ no consumer found in-repo` for a secret you know is used, add its real consumer there —
don't assume it's orphaned. (Two genuine "verify or prune" candidates today: `newshosting` and
`opensubtitles` creds — wired inside SABnzbd/Bazarr config, not any manifest.)

## Files

| File | Role |
|---|---|
| `docs/secrets-map.md` | The map: curated roles/tiers + the auto-derived graph. Read this first. |
| `docs/secrets-overlay.yaml` | Curated un-derivable consumers + handling tiers. |
| `scripts/gen-secrets-graph.mjs` | The generator. Regenerate to refresh; extends to a fuller domain map. |

Related: `[[reference_harness_claude_capabilities]]` (why the harness gets MCP diagnostics, not a
raw keystore), the External Secrets / 1Password mechanics in `docs/secrets-map.md`.
