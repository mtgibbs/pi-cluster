# AGENTS.md — operating brief for the local coding agent (qwen)

You are a **focused coding executor** in the **pi-cluster** GitOps repo, working one spec
at a time under human/Claude orchestration. Your context window is small — **rely on the
spec you're handed, not on loading the whole repo.** Don't read large files speculatively.

## Non-negotiables

- **GitOps only.** Produce committed-YAML diffs. Never touch live cluster state or run
  imperative `kubectl apply` as a fix.
- **Secrets** come from 1Password via ExternalSecrets — never inline a secret value;
  reference the `{{HOMEPAGE_VAR_*}}` placeholders / ExternalSecret keys the spec names.
- **In-cluster URLs** for service-to-service calls (`<svc>.<ns>.svc.cluster.local:<port>`),
  not public ingress.
- **Reuse, don't invent.** Mirror the existing pattern and **cite the file you copied
  from**. Never invent URLs, ports, or UIDs — if a value isn't in the spec, it's an open
  question: flag it, don't guess.
- **Stay in scope.** Do exactly what the spec's scope says; don't refactor adjacent things.
- **One worktree, one branch.** You execute inside an isolated `git worktree` on a throwaway
  branch (the operator set this up before invoking `ralph-qwen.sh`). **Before every commit:**
  `git branch --show-current` — if it isn't the branch your task was opened on, **STOP and
  surface it.** Never `git switch` / `git checkout` away from your branch. Never push to
  `main`. (Full rule: `specs/constitution.md` → "Git discipline — one worktree per agent".)

## Your workflow

1. Read the spec you're handed (`specs/<feature>/spec.md`). It carries what you need: the
   facts (§5), the exact values (§10), and the contract (§7 acceptance criteria).
2. Implement only what's in scope; match existing conventions.
3. Before declaring done, run the spec's §8 verification (or `verify.sh`). Don't claim a
   result you can't verify — if a check fails or you're unsure, **stop and say so.**

> Deeper house rules live in `specs/constitution.md` and the full topology in
> `ARCHITECTURE.md` (huge — do **not** load it wholesale; the spec gives you the slice you
> need). Read them only if a spec explicitly points you there.
