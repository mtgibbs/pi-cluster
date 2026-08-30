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
2. ~~A pinned name for the clone credential.~~ **Named 2026-08-30** — `HARNESS_CLONE_PAT`,
   pinned in that repo's `docs/executors.md` contract table by mtgibbs/harness#67 and adopted
   here. It is *not* `HARNESS_GITHUB_PAT`, the name that appears once in `20260829a`'s prose:
   that was written before `20260830a` split one PAT into a clone identity and an outcome
   identity, and beside `HARNESS_OUTCOME_PAT` it reads as *the* GitHub credential. What is still
   missing is the `entrypoint.sh` that reads it and writes `~/.git-credentials` — it has a name
   now, not an implementation, and it lands with the image in (1).
3. A `loop-executor-codex` image. `harness-worker-build-codex` exists here, but CI builds no image
   that carries the `codex` CLI, so the strategy has credentials and nowhere to run.

**In this repo:**

4. ~~**The 1Password fields.**~~ **DONE 2026-08-30.** All four fields exist on a `harness-fleet`
   item in the `pi-cluster` vault. `harness-coordinator/token` and `ghcr-read-token/token` were
   reused, not re-minted. Kept below as the record of what each credential is and why it is scoped
   the way it is — the next person to rotate one needs this table more than the person who made it.

   | field | what to create |
   |---|---|
   | `clone-token` | fine-grained PAT — **Contents: read**. Nothing else. It only ever clones |
   | `outcome-pat` | fine-grained PAT — **Contents: RW, Pull requests: RW, Workflows: RW** (that last one is OQ1, decided below). Note this is the fine-grained *Workflows* permission, not classic `repo`+`workflow` — the classic pair also grants everything else in `repo`, which is the opposite of what a worker's credentials should be |
   | `litellm-key` | a LiteLLM virtual key, scoped to the models `build-converge` may call. Per-consumer on purpose: cost attribution and independent revocation |
   | `codex-api-key` | the OpenAI key `codex exec` reads |

   Scope both PATs to the repos the fleet may actually land work in, not the whole account. The two
   are separate identities for a reason — one PAT doing both means a worker that only ever needed
   to read is holding the credential that can write.
5. ~~**The Flux Kustomization.**~~ **DONE 2026-08-30.** Registered as entry 36 in
   `clusters/pi-k3s/flux-system/infrastructure.yaml`, `dependsOn: external-secrets-config`, the
   same shape as `harness`. It was held back until step 4 on purpose: registering it before the
   fields existed would have produced a Kustomization that failed on every reconcile and alerted
   about a namespace nobody was using. From here that failure mode inverts into a useful one —
   `wait: true` means the Kustomization goes red if an ExternalSecret ever stops resolving.
6. **The node label.** The rendered Job's `nodeSelector` is `harness-fleet: "true"` and that label
   exists nowhere in this repo. `node-config/` is where it would go. Which node carries it is open
   (OQ2 in the spec) — `fleet-dispatch.md` notes the heavy lifting happens in the model on the
   Beelink, so the Pi running the Job may be doing very little.
7. **A Deployment for the dispatcher**, using the `harness-dispatcher` ServiceAccount from
   `rbac.yaml`, once (1) exists. Its environment is what binds strategy to image and secret:
   `HARNESS_WORKER_IMAGE_<STRATEGY>` and `HARNESS_WORKER_SECRET_<STRATEGY>`, upper-snake — so
   `build-codex` reads `HARNESS_WORKER_IMAGE_BUILD_CODEX` / `HARNESS_WORKER_SECRET_BUILD_CODEX`.

The reason this namespace looks abandoned is that its two halves land in different repositories.
Steps 1–3 are harness's; 4–7 are this repo's. 4 and 5 are done — what remains on this side is
6 (a node label, still OQ2) and 7 (a dispatcher Deployment), and 7 cannot start until harness
ships 1. So the critical path now runs entirely through the other repo.

## Decided

- **OQ1 — the outcome PAT carries workflow write.** Matt, 2026-08-30. A worker that cannot touch
  `.github/workflows/` cannot land a whole class of the work it exists to do, and the alternative —
  `gh api --method PUT` — leaves no commit in the branch's history, which breaks the property the
  whole evidence corpus rests on: that what the loop did is readable as a diff.

  **What this buys the attacker, stated plainly:** a compromised worker can open a PR that edits the
  workflows which gate its own PRs. It cannot merge that PR. The containment is therefore branch
  protection on the consumer repo plus a human (or `review-hub`) on the required review — not the
  token's scope, which was never going to be the thing that stopped it. What the PAT still may not
  do is create compute: that identity lives with the coordinator and is absent from every worker
  secret here.

## Still open

- **OQ3** — one quota for the namespace, or one per strategy? Two strategies competing for one slot
  is a scheduling decision nobody has had to make yet.

## What the gate does and does not prove

`specs/harness-fleet-workers/verify.sh` is STATIC tier: it reads the YAML in this directory and
never touches a cluster. It cannot prove the pull secret works, that Flux reconciles, or that a Job
schedules. Those are LIVE-tier checks and a human's call after deploy — in order: the ExternalSecrets
sync, then a throwaway pod with no `imagePullSecrets` pulls a private `ghcr.io/mtgibbs/*` image, then
a Job actually schedules onto the labelled node.

With step 5 merged, the first of those is answerable now: the `harness-fleet` Kustomization reaching
Ready is exactly the assertion that all three ExternalSecrets resolved. The second still needs a
throwaway pod — nothing here pulls an image, so a pull secret that is attached but wrong looks
identical to one that works until something tries. The third waits on the node label and a Job.
