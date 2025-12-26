---
description: Commit changes, push to GitHub, and reconcile Flux
allowed-tools: Bash(git:*), Bash(KUBECONFIG=~/dev/pi-cluster/kubeconfig flux:*), Bash(KUBECONFIG=~/dev/pi-cluster/kubeconfig kubectl:*)
argument-hint: [commit message]
---

# Deploy Changes via GitOps

Commit pending changes and trigger Flux reconciliation.

## Steps

1. **Check for changes**: Run `git status` to see what's pending
2. **Stage changes**: Run `git add -A` for all changes
3. **Commit**: Use the provided message or generate one based on changes
   - Format: `<type>: <description>` (e.g., `feat: Add new service`, `fix: Correct DNS config`)
   - End with the standard Claude Code footer
4. **Push**: Push to origin/main
5. **Reconcile**: Run `KUBECONFIG=~/dev/pi-cluster/kubeconfig flux reconcile source git flux-system`
6. **Wait**: Run `KUBECONFIG=~/dev/pi-cluster/kubeconfig flux reconcile kustomization flux-system`
7. **Verify**: Show `flux get kustomizations` to confirm all are ready

## Commit Message

If message provided: $ARGUMENTS

If no message provided, analyze the staged files and generate an appropriate commit message.

## Output

Report:
- Files committed
- Commit hash
- Flux sync status
- Any errors or warnings
