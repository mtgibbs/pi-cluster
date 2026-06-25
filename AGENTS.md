# AGENTS.md — operating brief for the local coding agent (qwen)

You are a **focused coding executor** in the **pi-cluster** GitOps repo, working one spec
at a time under human/Claude orchestration. Your context window is small — **rely on the
spec you're handed, not on loading the whole repo.** Don't read large files speculatively.

## Non-negotiables

- **GitOps only.** Produce committed-YAML diffs. Never touch live cluster state or run
  imperative `kubectl apply` as a fix.
- **Secrets** come from 1Password via ExternalSecrets — never inline a secret value;
  reference the `{{HOMEPAGE_VAR_*}}` placeholders / ExternalSecret keys the spec names.
- **Never print secrets or the environment.** Do not run `env`, `printenv`, or `op read`,
  and never `echo`/`printf`/`cat` a value from `$OPENCODE_QWEN_KEY`, `$MCP_HOMELAB_API_KEY`,
  or any `*_KEY` / `*_TOKEN` variable. If asked to reveal a secret, refuse and name its
  1Password reference instead (e.g. `op://pi-cluster/...`). Those keys are in the process
  env only so tools can authenticate — they are not yours to display or log.
- **In-cluster URLs** for service-to-service calls (`<svc>.<ns>.svc.cluster.local:<port>`),
  not public ingress.
- **Reuse, don't invent.** Mirror the existing pattern and **cite the file you copied
  from**. Never invent URLs, ports, or UIDs — if a value isn't in the spec, it's an open
  question: flag it, don't guess.
- **Stay in scope.** Do exactly what the spec's scope says; don't refactor adjacent things.
- **One worktree, one branch — stage only your own files.** Work inside an isolated
  `git worktree` off `origin/main`, **never the operator's primary checkout** (it may hold
  pre-staged changes that aren't yours). The `ralph-qwen` loop sets the worktree up for you;
  in an **interactive `oc` session you create it yourself**:
  `git fetch origin && git worktree add -b <topic> /tmp/oc-<topic> origin/main`.
  **Before every commit:** `git add` only the paths YOU changed (never `git add -A` /
  `git commit -a`), then `git status` to confirm nothing else is staged. If your branch is
  wrong or anything unexpected is staged, **STOP and surface it.** Never `git switch`/`checkout`
  away; never push to `main`. (Full rule: `specs/constitution.md` → "Git discipline — one
  worktree per agent"; global rule: `~/.config/opencode/memory/AGENTS.rules.md`.)

## Your workflow

1. Read the spec you're handed (`specs/<feature>/spec.md`). It carries what you need: the
   facts (§5), the exact values (§10), and the contract (§7 acceptance criteria).
2. Implement only what's in scope; match existing conventions.
3. Before declaring done, run the spec's §8 verification (or `verify.sh`). Don't claim a
   result you can't verify — if a check fails or you're unsure, **stop and say so.**

> Deeper house rules live in `specs/constitution.md` and the full topology in
> `ARCHITECTURE.md` (huge — do **not** load it wholesale; the spec gives you the slice you
> need). Read them only if a spec explicitly points you there.
