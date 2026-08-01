---
description: Show Flux GitOps synchronization status for all resources
allowed-tools: mcp__homelab__get_flux_status
---

# Flux Status Check

Show the current state of Flux GitOps synchronization.

## Command to Run

`get_flux_status` — returns Kustomization and HelmRelease sync state in one call (no args).

## Output Format

1. **Git Sync**: Last sync time, revision
2. **Kustomizations**: Count ready/total, list any failed
3. **HelmReleases**: Count ready/total, list any failed
4. **Action needed**: Yes/No with details if yes

## Notes

- To force a sync, use `reconcile_flux` (omit `resource` for everything, or pass
  `"kustomization/flux-system/<name>"` for one). **Reconcile the *source* first** — see the
  gotcha in `docs/flux-gitops.md`.
- A Kustomization stuck "not ready" is an **Investigate**, not a re-reconcile loop: check
  `dependsOn`, the namespace, and ExternalSecret sync before forcing again.
