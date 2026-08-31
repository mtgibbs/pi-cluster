# Constitution — pi-cluster's overlay

> This is the **consumer overlay** to Jig's generic constitution
> (`mtgibbs/jig:specs/constitution.md`). The judge assembles law in order — generic
> first, this file second — so nothing here restates the generic layer (worktree
> discipline, the gate contract, evidence rules, anti-novelty, spec authoring). This
> file carries only what is true of *this* repo: the homelab's own non-negotiables.
> Deep reference is `ARCHITECTURE.md` (~2,500 lines — read on demand, never ship
> wholesale); Claude-specific protocol lives in `/CLAUDE.md`.

## How we build (non-negotiable)

- **GitOps via Flux.** Every change is committed YAML reconciled by Flux. **Never** edit
  live cluster state, web UIs, or run imperative `kubectl apply` as the solution. The
  deliverable is a diff, not a running change.
- **Secrets via 1Password + ExternalSecrets.** Never inline a secret value. Reference an
  `ExternalSecret` that pulls from the `pi-cluster` 1Password vault. `op://` *paths* are
  fine to write; values never.
- **MCP-first.** Use `mcp__homelab__*` tools over raw kubectl where one exists.

## House conventions (match these — do not invent your own)

- **In-cluster service URLs** for service-to-service / widget calls
  (`<svc>.<namespace>.svc.cluster.local:<port>`), **not** public ingress.
- **Public ingress** is `https://<name>.lab.mtgibbs.dev` (Let's Encrypt via cert-manager/Caddy).
- **Public-by-default.** Topology and config are not secret (Kerckhoffs); only secrets are
  secret. Don't add obscurity; don't over-engineer caution.
- File layout mirrors the live tree: `clusters/pi-k3s/<service>/{deployment,service,ingress,
  kustomization,external-secret,...}.yaml`, wired into `flux-system/infrastructure.yaml`.

## The stack in one breath

Pi 5 K3s cluster (Flux GitOps, 1Password/ESO, Pi-hole+Unbound DNS, ingress-nginx +
cert-manager, kube-prometheus + Grafana + Uptime Kuma, Jellyfin/Immich + *arr media in
`media` ns). Separate **Beelink** box runs the AI stack (Ollama/LiteLLM/Open WebUI, Docker
Compose, NOT in K3s) — reached at `ai.lab.mtgibbs.dev`. Cluster scrapes the Beelink over the LAN.

## Where to read more (on demand)

- `ARCHITECTURE.md` — full topology + design decisions (large; read the relevant section).
- `.claude/skills/<area>/SKILL.md` — operational runbooks (dns-ops, monitoring-ops, media-services, …).
- The SDD method, the spec skeleton, and the generic law: `mtgibbs/jig` — `specs/README.md`,
  `specs/TEMPLATE.md`, `specs/constitution.md` + `specs/amendments.md` there.
