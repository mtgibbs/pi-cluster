# Constitution — house rules for any agent working this repo

> Tier-1 context: prepend this to **every** agent handoff. It's the non-negotiable
> architectural DNA, kept deliberately short so it always fits the budget. The full
> reference is `ARCHITECTURE.md` (~2,500 lines — read on demand, never ship wholesale).

## How we build (non-negotiable)

- **GitOps via Flux.** Every change is committed YAML reconciled by Flux. **Never** edit
  live cluster state, web UIs, or run imperative `kubectl apply` as the solution. The
  deliverable is a diff, not a running change.
- **Secrets via 1Password + ExternalSecrets.** Never inline a secret value. Reference an
  `ExternalSecret` that pulls from the `pi-cluster` 1Password vault. `op://` *paths* are
  fine to write; values never.
- **PR-gated.** Your output is reviewed before it reaches the cluster. Optimize for a
  diff a human can verify against the spec's acceptance criteria.

## Git discipline — one worktree per agent (non-negotiable)

This is forward-looking: today there is one ralph loop, but qwen will fan out to a **set
of parallel agents** (and Claude runs alongside). Shared-checkout work races on
`git switch`/`git checkout`. The rule that lets us fan out safely:

- **Each agent loop runs from its OWN `git worktree` on its own throwaway branch.** The
  operator launches `scripts/ralph-qwen.sh` from inside that worktree — the script's
  usage already states this. Don't run a loop from the primary checkout.
- **Before any commit, verify the branch:** `git branch --show-current`. If it's not
  the branch your task was opened on, STOP and ask. Committing default-branch work onto
  a feature branch (or feature-branch work onto `main`) is just as wrong as committing
  straight to `main`.
- **Operator setup, the pattern:**
  ```bash
  git worktree add ../pi-cluster-<task> -b ralph/<task>   # isolated dir + branch
  cd ../pi-cluster-<task>
  scripts/ralph-qwen.sh <spec-dir>
  ```
- **Cherry-pick or PR back to `main` deliberately** (`PR-gated` rule above). Never push
  the throwaway branch straight to `main`.
- **Teardown when the task lands:** `git worktree remove --force ../pi-cluster-<task>`.
- **Landing other work onto `main` while a worktree is in flight** (e.g. an unrelated
  doc fix): use a *second* temporary worktree (`git worktree add /tmp/<name> main`); do
  not `git switch main` in the primary checkout (that disturbs whoever is working there).

## House conventions (match these — do not invent your own)

- **In-cluster service URLs** for service-to-service / widget calls
  (`<svc>.<namespace>.svc.cluster.local:<port>`), **not** public ingress.
- **Public ingress** is `https://<name>.lab.mtgibbs.dev` (Let's Encrypt via cert-manager/Caddy).
- **Public-by-default.** Topology and config are not secret (Kerckhoffs); only secrets are
  secret. Don't add obscurity; don't over-engineer caution.
- File layout mirrors the live tree: `clusters/pi-k3s/<service>/{deployment,service,ingress,
  kustomization,external-secret,...}.yaml`, wired into `flux-system/infrastructure.yaml`.

## Anti-novelty directives (READ THIS)

This is a **conventional, mature homelab — not a greenfield**. Your job is to fit in, not
to innovate.

- **Reuse the existing pattern. Cite the file you copied from.** If a similar service or
  widget already exists, mirror it.
- **Do not invent URLs, UIDs, ports, or API shapes.** If a value isn't given in the spec,
  it's an open question — flag it, don't guess. (Guessed links are usually broken.)
- **Beware the *similar-but-different* trap.** When two existing patterns look alike, the
  spec will tell you which to follow and how they differ — honor that over your instinct
  to copy the nearest one.
- **Stay in scope.** Do exactly what the spec's §3 says; don't "helpfully" refactor or
  touch adjacent things.

## Specs & verification (for whoever authors a spec for an agent)

- **Worked examples must be tested before handoff.** A local model executes your example
  *faithfully* — bugs and all. An untested example is a bug you've outsourced. (We once
  shipped a `round(100 * …)` + `format: percent` example that renders "6100%"; the model
  copied it verbatim. Verify examples against reality first.)
- **Verification is external and mandatory.** Every spec handed to an agent ships a
  `verify.sh` — the §7 acceptance criteria compiled into a deterministic gate (exit 0 =
  acceptable). The loop runs it; **the model never self-certifies "done".**
- **One task per loop iteration, fresh context.** Decompose; never hand the model the whole
  repo or whole spec at once. Small scope = small context = reliable, fast, cheap. The
  fixture (loop) carries the rigor, not the model. See `scripts/ralph-qwen.sh`.
- **Verify the exact thing a criterion depends on — not a proxy.** An ExternalSecret needs a
  *field*; checking the *item* exists isn't enough (the prowlarr/lidarr lesson: the items
  existed, the `api-key` field didn't). Resolve at the right granularity in the Plan phase —
  and don't let tooling friction (e.g. a flaky `op` biometric) silently downgrade your check
  from field-level to item-level. If you can't verify it now, it's an open question, not a fact.
- **Research the idiomatic, *tasteful* pattern before specifying** — not just the first correct
  one. The Plan phase resolves design unknowns too, per `design-principles.md`. Taste needs an
  eye on the rendered artifact; static gates can't see "this looks dumb".

## The stack in one breath

Pi 5 K3s cluster (Flux GitOps, 1Password/ESO, Pi-hole+Unbound DNS, ingress-nginx +
cert-manager, kube-prometheus + Grafana + Uptime Kuma, Jellyfin/Immich + *arr media in
`media` ns). Separate **Beelink** box runs the AI stack (Ollama/LiteLLM/Open WebUI, Docker
Compose, NOT in K3s) — reached at `ai.lab.mtgibbs.dev`. Cluster scrapes the Beelink over the LAN.

## Where to read more (on demand)

- `ARCHITECTURE.md` — full topology + design decisions (large; read the relevant section).
- `.claude/skills/<area>/SKILL.md` — operational runbooks (dns-ops, monitoring-ops, media-services, …).
- `specs/README.md` — the SDD method; `specs/TEMPLATE.md` — the spec skeleton.
