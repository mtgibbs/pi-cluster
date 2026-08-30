# Spec: the namespace a dispatched worker lands in

**Status:** draft, 2026-08-30. Owner: Matt.

## 1. Why · [R — Requirements]

`mtgibbs/harness` can now render a Kubernetes Job for a run: `worker_image()` picks the image that
can execute a strategy, `worker_secret()` picks the credentials that strategy is entitled to, and
both resolve from the same strategy value read once (harness #65, #66). What it renders is
deliberately minimal:

```
metadata: namespace, name=run-<run_id>
spec:     activeDeadlineSeconds=1800, ttlSecondsAfterFinished=3600, backoffLimit=0
pod:      nodeSelector {harness-fleet: "true"}, restartPolicy Never
container: name=run, image, env REPO/SPEC/STRATEGY, envFrom (only when configured)
```

There is **no `serviceAccountName`, no `imagePullSecrets`, and no `resources`** in that body, and
that is a decision rather than an omission — the dispatcher staying describable in a paragraph is a
named cliff in the harness's `docs/design/fleet-dispatch.md`. Everything the body does not carry
has to come from **the namespace around it**, and that namespace does not exist.

Applied to the cluster today, a rendered Job would fail to schedule (no node carries the label), and
if it scheduled it would fail to pull (the image is private and nothing supplies a pull secret), and
if it pulled it would have no credentials. This spec builds the surroundings.

## 2. Outcomes (Definition of Done) · [R — Requirements]

1. A Job carrying no `imagePullSecrets` can still pull `ghcr.io/mtgibbs/loop-executor-*`.
2. A dispatcher can create Jobs in exactly one namespace and nothing else, anywhere.
3. A worker receives the credentials for its strategy, and no other strategy's.
4. A runaway dispatcher cannot fill the cluster.
5. A reader can tell what is deliberately inert here and why.

## 3. Entities · [E — Entities]

| resource | why it exists |
|---|---|
| `harness-fleet` namespace | the blast radius. Not `harness`, which holds the coordinator |
| `default` ServiceAccount, patched | **carries the pull secret the Job body will never name** |
| `ghcr-pull-secret` | the cluster's existing shared GHCR read token, materialised here |
| dispatcher SA + Role + RoleBinding | create Jobs *here*, nowhere else |
| `ResourceQuota` | the concurrency cap `fleet-dispatch.md` calls for |
| `harness-worker-<strategy>` secrets | one per strategy, never one shared blob |

**The `default` ServiceAccount is the load-bearing piece.** A pod with no `serviceAccountName` runs
as `default`, and a pull secret attached to that account applies to every pod in the namespace
without any pod naming it. That single fact is what lets the harness's Job body stay as small as it
is; get it wrong and every dispatched run dies at `ImagePullBackOff` with nothing in the Job to
explain why.

## 4. Approach · [A — Approach]

Mirror `clusters/pi-k3s/harness/` exactly — it is the same shape one namespace over, and the GHCR
ExternalSecret is a verbatim copy with the namespace changed. No new pull credential: `ghcr-read-token`
is already the cluster's "pull private packages" identity.

Per-strategy worker secrets follow the harness's resolution, which this spec does not get to change:

```
HARNESS_WORKER_SECRET_<STRATEGY_UPPER_SNAKE>  →  HARNESS_WORKER_SECRET  →  nothing
```

`build-codex` becomes `BUILD_CODEX`. So a secret named `harness-worker-build-codex` is selected by
setting `HARNESS_WORKER_SECRET_BUILD_CODEX=harness-worker-build-codex` on the dispatcher.

## 5. Scope · [S — Structure: boundary]

### In scope
- `clusters/pi-k3s/harness-fleet/` — namespace, patched `default` SA, GHCR pull secret, dispatcher
  RBAC, ResourceQuota, per-strategy worker ExternalSecrets, kustomization.
- A runbook section recording what is inert and why.

### Out of scope — and this is the important half

- **The dispatcher itself.** `scripts/dispatch/dispatcher.py` and `api.py` are **not packaged into
  any image**: `docker/coordinator.Dockerfile` copies `coordinator.py` and `board.html` and nothing
  else, and harness CI builds `harness-base`, `loop-executor-opencode` and `harness-coordinator`.
  `launch()` also shells out to `kubectl`, which no image carries. **There is nothing to deploy
  yet**, and building it is a harness spec, not this one.

  This spec therefore lands the surroundings **ahead of** the thing that will use them. That is
  deliberate and is stated here so a reader who finds an empty namespace knows it is waiting rather
  than broken. The alternative — blocking until the image exists — leaves the harness side with no
  target to build against.
- **The node label.** `nodeSelector` is `harness-fleet: "true"` and that label exists nowhere in
  this repo. Which node carries it is OQ2, and `node-config/` is where it would go.
- **Changing the rendered Job.** It is fixed by harness #66 and gated there.
- **Wiring `HARNESS_OUTCOME_PAT`.** It is provisioned into the worker secrets and consumed by
  nothing; harness reserves the name for a code-egress spec that has not been written.

## 6. Prior decisions / facts the implementer must know · [S]

- `clusters/pi-k3s/harness/external-secret-ghcr.yaml` is the copy source, and its header explains
  why reusing `ghcr-read-token` is right: one 1Password item is the whole cluster's pull identity.
- `clusters/pi-k3s/harness/external-secret.yaml` already holds `harness-coordinator/token` — the
  bearer token workers present when reporting. **Reuse it; do not mint a second.** Its header
  argues the general case: a token that leaks from a reporting worker must not also be able to
  launch Jobs.
- Walk `docs/secrets-map.md` before minting anything new. The repo's rule.
- The kustomization must **not** carry a top-level `namespace:` if it ever ships an
  `image-automation.yaml` — `clusters/pi-k3s/harness/kustomization.yaml` explains why in a comment.
  This spec ships no image automation, so declare `namespace: harness-fleet` on each resource, as
  every file in the sibling directory already does.
- Three identities, from harness `docs/executors.md`: the dispatch API token creates compute, the
  clone credential reads, and the outcome PAT pushes a branch and opens a PR and **may never launch
  compute**.

## 7. Norms · [N — Norms]

- GitOps only. Committed YAML; never `kubectl apply` as a fix.
- Secrets come from 1Password through ExternalSecrets. No inlined value, ever.
- Reuse and cite the file copied from.

## 8. Safeguards · [S — Safeguards]

- The dispatcher's Role is **namespaced**, never a ClusterRole. A dispatcher that can create Jobs
  cluster-wide is a dispatcher that can create Jobs in `kube-system`.
- The Role grants no `secrets` verbs. A component that launches workers does not need to read the
  credentials they receive.
- No worker secret contains a token that can launch compute.

## 9. Task breakdown · [O — Operations]

Sequential.

1. **T1** — namespace, GHCR pull secret, and the patched `default` ServiceAccount.
2. **T2** — dispatcher ServiceAccount, namespaced Role, RoleBinding, and the ResourceQuota.
3. **T3** — the per-strategy worker ExternalSecrets.
4. **T4** — the runbook: what is inert, why, and what unblocks it.

## 10. Acceptance criteria (EARS) · [O — Operations made testable]

- **AC-1** `clusters/pi-k3s/harness-fleet/namespace.yaml` shall declare a Namespace named
  `harness-fleet`.
- **AC-2** A ServiceAccount named `default` in `harness-fleet` shall carry `imagePullSecrets`
  referencing `ghcr-pull-secret`.
- **AC-3** An ExternalSecret shall materialise `ghcr-pull-secret` in `harness-fleet` from the
  existing `ghcr-read-token` 1Password item, as `kubernetes.io/dockerconfigjson`.
- **AC-4** A ServiceAccount for the dispatcher shall exist in `harness-fleet`.
- **AC-5** A **Role** — never a ClusterRole — shall grant `batch`/`jobs` create, get, list, watch
  and delete, and shall grant no verb on `secrets`.
- **AC-6** A RoleBinding shall bind that Role to that ServiceAccount.
- **AC-7** A ResourceQuota shall cap `count/jobs.batch` at no more than 2.
- **AC-8** For every strategy named in the spec, an ExternalSecret named
  `harness-worker-<strategy>` shall exist in `harness-fleet`.
- **AC-9** No worker ExternalSecret shall reference the dispatch API token.
- **AC-10** No manifest in this directory shall contain an inlined secret value.
- **AC-11** `kustomization.yaml` shall list every resource file in the directory.
- **AC-12** A runbook shall record that the dispatcher is not yet packaged and that these resources
  are inert until it is.

## 11. Verification (the harness)

`verify.sh`, STATIC tier only: it reads committed YAML and never touches a cluster. Presence-gated
with the three-verdict contract — a check whose file does not exist yet is `pend`, and `STRICT=1`
on the final task promotes every remaining `pend` to a failure.

It cannot prove the pull secret works, that Flux reconciles, or that a Job schedules. Those are the
LIVE tier and a human's call after deploy — the same split `harness-egress-allowlist` documents.

bash 3.2: no `mapfile`, no associative arrays. This gate is most likely to be run from the laptop.

## 12. Open questions

- **OQ1 — does the outcome PAT need `workflow` scope?** Without it a worker cannot land a change
  under `.github/workflows/`; with it, the widest-reaching identity in the table gets wider. The
  `gh api --method PUT` path works and needs no scope, but leaves no commit in the branch's history.
  **RESOLVED 2026-08-30 (Matt): yes — fine-grained Workflows: write.** The reasoning and the
  resulting threat model live in `clusters/pi-k3s/harness-fleet/README.md`, which is the doc a
  person reads when provisioning it.
- **OQ2 — which node carries `harness-fleet=true`?** `fleet-dispatch.md` says the heavy lifting is
  in the model on the Beelink anyway, so the Pi running the Job may be doing very little.

  **RESOLVED 2026-08-30 (Matt): pi5-worker-2**, as `node-config/pi5-worker-2.yaml`. Chosen by
  elimination rather than by load measurement — pi5-worker-1 carries the Pi-hole secondary, the
  Tailscale exit node, Immich and the MCP servers, and a runaway build contending with the DNS
  secondary presents as "the internet is broken" rather than "a build is slow"; pi3-worker-2 has
  1GB against a quota that permits 4Gi. The label is additive, with no taint, so the node keeps
  taking ordinary scheduler-driven work and the namespace ResourceQuota is what bounds the
  fleet's share.
- **OQ3 — one quota for the namespace, or per strategy?** Two strategies competing for one slot is
  a scheduling decision nobody has had to make yet.
