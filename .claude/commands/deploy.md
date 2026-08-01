---
description: Commit changes, open a PR, and reconcile Flux once merged
allowed-tools: Bash(git:*), Bash(gh:*), mcp__homelab__reconcile_flux, mcp__homelab__get_flux_status
argument-hint: [commit message]
---

# Deploy Changes via GitOps

Land pending changes through the **PR gate**, then reconcile Flux.

## Steps

1. **Check branch and changes**: `git branch --show-current` and `git status`. If you're on
   `main`, create a working branch first — never commit an agent's work straight onto `main`.
   Prefer a worktree (`git worktree add /tmp/<name> -b <branch> main`) so the user's checkout
   is never switched out from under them.
2. **Stage**: `git add` the intended paths (prefer explicit paths over `git add -A`).
3. **Commit**: use `$ARGUMENTS` if provided, else generate from the diff.
   - Format: `<type>(<scope>): <description>` — e.g. `feat(media): add Jellyseerr ingress`
   - End with the standard Claude Code footer
4. **Push + PR**: push the branch and `gh pr create`. This is the gate — cluster-affecting
   changes get reviewed before Flux applies them.
5. **After merge, reconcile**: `reconcile_flux(resource="...")`.
   **Reconcile the *source* first**, then the Kustomization — see the gotcha in
   `docs/flux-gitops.md`. Omit `resource` to reconcile everything.
6. **Verify**: `get_flux_status` — confirm the Kustomizations and HelmReleases went ready.

## Why a PR and not a push to main

`main` blocks force-pushes and deletions but has **no required-PR rule** — deliberately, so Flux
`ImageUpdateAutomation` can commit image-tag bumps directly as the bot (a required-PR rule would
silently halt image automation). That the guard *permits* a direct push doesn't make it the agent
path: agent work is PR-gated by convention. Direct-to-`main` is for the Flux bot and for the user's
own call, not for this command.

## Output

Report:
- Branch and files committed
- Commit hash and PR URL
- After merge: Flux sync status
- Any errors or warnings
