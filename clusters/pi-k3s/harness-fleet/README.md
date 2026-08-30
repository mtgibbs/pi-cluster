# harness-fleet — the namespace a dispatched worker lands in

**These resources are INERT. Nothing runs here yet, and that is the expected state.**

If you came looking for a workload and found an empty namespace: it is waiting, not broken.

## Why it is inert

The dispatcher does not exist as a deployable thing. In `mtgibbs/harness`:

- `scripts/dispatch/dispatcher.py` and `api.py` are **in no image** — `docker/coordinator.Dockerfile`
  copies `coordinator.py` and `board.html` and nothing else, and that repo's CI builds exactly three
  images: `harness-base`, `loop-executor-opencode`, `harness-coordinator`.
- `launch()` shells out to `kubectl`, which none of those images carries.

So there is nothing to point this namespace's ServiceAccount at. Building that image is a harness
spec, not this one — and this directory lands **ahead of** its consumer deliberately, so the harness
side has a target to build against instead of both halves waiting on each other.

What *is* here is everything the rendered Job will not carry. The harness renders a deliberately
minimal Job — no `serviceAccountName`, no `imagePullSecrets`, no `resources` — because the
dispatcher staying describable in a paragraph is a named cliff in its `docs/design/fleet-dispatch.md`.
Every one of those omissions is answered by a file in this directory.

## What unblocks it

**In `mtgibbs/harness`:**

1. An image carrying `dispatcher.py`, `api.py` and `kubectl`.
2. A pinned name for the clone credential. `run-task.sh` clones a plain https URL with no token in
   it and relies on a credential helper written at container start, but no entrypoint writing
   `~/.git-credentials` exists yet. `HARNESS_CLONE_TOKEN` in the worker secrets is this repo's
   provisional guess and should be reconciled with whatever that entrypoint reads.
3. A `loop-executor-codex` image. `harness-worker-build-codex` exists here, but CI builds no image
   that carries the `codex` CLI, so the strategy has credentials and nowhere to run.

**In this repo:**

4. **The 1Password fields.** ESO will report `SecretSyncErr` until the `pi-cluster` vault has
   `harness-fleet/litellm-key`, `harness-fleet/codex-api-key`, `harness-fleet/clone-token` and
   `harness-fleet/outcome-pat`. `harness-coordinator/token` and `ghcr-read-token/token` already
   exist and are reused. Minting these needs `op` on the laptop — the container cannot.
5. **The Flux Kustomization.** This directory is deliberately *not* yet registered in
   `clusters/pi-k3s/flux-system/infrastructure.yaml`: registering it before step 4 produces a
   Kustomization that fails on every reconcile and alerts about a namespace nobody is using. Add it
   the same way `harness` is registered, after the fields exist.
6. **The node label.** The rendered Job's `nodeSelector` is `harness-fleet: "true"` and that label
   exists nowhere in this repo. `node-config/` is where it would go. Which node carries it is open
   (OQ2 in the spec) — `fleet-dispatch.md` notes the heavy lifting happens in the model on the
   Beelink, so the Pi running the Job may be doing very little.
7. **A Deployment for the dispatcher**, using the `harness-dispatcher` ServiceAccount from
   `rbac.yaml`, once (1) exists. Its environment is what binds strategy to image and secret:
   `HARNESS_WORKER_IMAGE_<STRATEGY>` and `HARNESS_WORKER_SECRET_<STRATEGY>`, upper-snake — so
   `build-codex` reads `HARNESS_WORKER_IMAGE_BUILD_CODEX` / `HARNESS_WORKER_SECRET_BUILD_CODEX`.

The reason this namespace looks abandoned is that its two halves land in different repositories.
Steps 1–3 are harness's; 4–7 are this repo's, and 4 gates 5.

## Still open

- **OQ1** — does the outcome PAT need `workflow` scope? Without it a worker cannot land a change
  under `.github/workflows/`; with it, the widest-reaching identity gets wider.
- **OQ3** — one quota for the namespace, or one per strategy? Two strategies competing for one slot
  is a scheduling decision nobody has had to make yet.

## What the gate does and does not prove

`specs/harness-fleet-workers/verify.sh` is STATIC tier: it reads the YAML in this directory and
never touches a cluster. It cannot prove the pull secret works, that Flux reconciles, or that a Job
schedules. Those are LIVE-tier checks and a human's call after deploy — in order: the ExternalSecrets
sync, then a throwaway pod with no `imagePullSecrets` pulls a private `ghcr.io/mtgibbs/*` image, then
a Job actually schedules onto the labelled node.
