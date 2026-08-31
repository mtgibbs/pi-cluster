# harness-fleet — the namespace a dispatched worker lands in

**The dispatcher runs here now.** `deployment.yaml` runs
`ghcr.io/mtgibbs/harness-dispatcher` under the `harness-dispatcher` ServiceAccount — the one
identity in the cluster that can create Jobs, bounded by `rbac.yaml` to this namespace. Its
Service is ClusterIP only, on purpose: the endpoint whose POST creates compute stays unreachable
from outside the cluster until the event transport is decided (see `service.yaml`'s header for
the port-forward a human uses meanwhile).

Two things remain deliberately inert, and finding them idle is expected, not broken:

- **`build-codex`** — its worker secret syncs, but harness CI builds no image carrying the
  `codex` CLI, so the strategy is absent from the dispatcher's `HARNESS_STRATEGIES` allowlist:
  credentials with nowhere to run are refused at dispatch time, not failed inside a pod.
- **`HARNESS_OUTCOME_PAT`** — provisioned into the worker secrets, consumed by nothing yet; the
  harness reserves the name for a code-egress spec that has not been written.

## Why this directory landed empty first

This directory shipped 2026-08-30 **ahead of** its consumer, deliberately, so the harness side had
a target to build against instead of both halves waiting on each other. At the time
`scripts/dispatch/dispatcher.py` and `api.py` were packaged in **no image** and `launch()` shelled
out to `kubectl`, which no image carried — nothing to point the ServiceAccount at. That unblocked
2026-08-31 when harness CI began publishing `harness-dispatcher` (multi-arch, `kubectl` pinned and
checksum-verified in its Dockerfile).

What was here from the start is everything the rendered Job will not carry. The harness renders a
deliberately minimal Job — no `serviceAccountName`, no `imagePullSecrets`, no `resources` — because
the dispatcher staying describable in a paragraph is a named cliff in its
`docs/design/fleet-dispatch.md`. Every one of those omissions is answered by a file in this
directory.

## What unblocked it — the record

**In `mtgibbs/harness`:**

1. ~~An image carrying `dispatcher.py`, `api.py` and `kubectl`.~~ **DONE 2026-08-31** —
   `docker/dispatcher.Dockerfile`, published as `ghcr.io/mtgibbs/harness-dispatcher`
   (linux/amd64 + arm64). It is FROM `python:3.12-slim`, not `harness-base`, so the component
   permitted to create Jobs carries no loop, no node runtime and no harness scripts.
2. ~~A pinned name for the clone credential.~~ **Named 2026-08-30** — `HARNESS_CLONE_PAT`,
   pinned in that repo's `docs/executors.md` contract table by mtgibbs/harness#67 and adopted
   here. It is *not* `HARNESS_GITHUB_PAT`, the name that appears once in `20260829a`'s prose:
   that was written before `20260830a` split one PAT into a clone identity and an outcome
   identity, and beside `HARNESS_OUTCOME_PAT` it reads as *the* GitHub credential. The
   `entrypoint.sh` that reads it and writes `~/.git-credentials` **now exists** in that repo
   (it unsets the variable after writing, so the token never sits in the loop's environment).
3. A `loop-executor-codex` image. `harness-worker-build-codex` exists here, but CI builds no image
   that carries the `codex` CLI, so the strategy has credentials and nowhere to run.

**In this repo:**

4. ~~**The 1Password fields.**~~ **DONE 2026-08-30.** All four fields exist on a `harness-fleet`
   item in the `pi-cluster` vault. `harness-coordinator/token` and `ghcr-read-token/token` were
   reused, not re-minted. Kept below as the record of what each credential is and why it is scoped
   the way it is — the next person to rotate one needs this table more than the person who made it.

   | field | what to create |
   |---|---|
   A **fifth field** joins them with the dispatcher Deployment:

   | field | what to create |
   |---|---|
   | `dispatch-api-token` | any long-random value — `api.py` compares it verbatim as `Bearer <token>`. This is the one identity that can create compute, so it is NOT a reuse of `harness-coordinator/token`: every worker holds that one to report, and a token that leaks from a worker must not also launch Jobs (`external-secret-dispatcher.yaml` argues it in full). Until this field exists, ESO reports `SecretSyncErr` and the Kustomization holds not-ready |

   The original four, kept as the rotation record:

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
6. ~~**The node label.**~~ **Decided 2026-08-30 — `pi5-worker-2`**, committed as
   `node-config/pi5-worker-2.yaml`. The rendered Job's `nodeSelector` is `harness-fleet: "true"`,
   so without the label a dispatched run sits Pending with no events worth reading.

   **It is not live until someone applies it.** `node-config/` is rebuild persistence — nothing
   consumes those files automatically, and the label lands on the next k3s restart. The live half
   is `kubectl label node pi5-worker-2 harness-fleet=true --overwrite`, which this container
   cannot run. Both halves are needed: the `kubectl` one works now and is lost on rebuild, the
   file survives the rebuild and does nothing until a restart.
7. ~~**A Deployment for the dispatcher.**~~ **DONE 2026-08-31** — `deployment.yaml`, using the
   `harness-dispatcher` ServiceAccount from `rbac.yaml`. Its environment is what binds strategy
   to image and secret: `HARNESS_WORKER_IMAGE_<STRATEGY>` and `HARNESS_WORKER_SECRET_<STRATEGY>`,
   upper-snake. Only `build-converge` is mapped and allowlisted; there is deliberately no bare
   `HARNESS_WORKER_IMAGE` fallback, so an unmapped strategy resolves nothing instead of silently
   riding a default image.

Of the seven, what still needs a human's hands: the `dispatch-api-token` field (step 4's fifth
row — `op` on the laptop), the **live** half of the node label (step 6 — the committed file does
nothing until a k3s restart or a `kubectl label`), and a `loop-executor-codex` image (step 3)
whenever `build-codex` is wanted. The first two gate the first dispatched run.

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
