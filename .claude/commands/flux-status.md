---
description: Show Flux GitOps synchronization status for all resources
allowed-tools: Bash(KUBECONFIG=~/dev/pi-cluster/kubeconfig flux:*), Bash(KUBECONFIG=~/dev/pi-cluster/kubeconfig kubectl:*)
---

# Flux Status Check

Show the current state of Flux GitOps synchronization.

## Commands to Run

Run these commands and summarize the results:

1. Git source status: `KUBECONFIG=~/dev/pi-cluster/kubeconfig flux get source git flux-system`
2. All Kustomizations: `KUBECONFIG=~/dev/pi-cluster/kubeconfig flux get kustomizations`
3. All HelmReleases: `KUBECONFIG=~/dev/pi-cluster/kubeconfig flux get helmrelease -A`

## Output Format

Provide a concise summary:
1. **Git Sync**: Last sync time, revision
2. **Kustomizations**: Count ready/total, list any failed
3. **HelmReleases**: Count ready/total, list any failed
4. **Action needed**: Yes/No with details if yes
