# Kelos

[Kelos](https://github.com/kelos-dev/kelos) (Apache-2.0) is a Kubernetes-native controller that
runs coding-agent tasks as custom resources: you apply a `Task`, the controller turns it into a
Job, the Job's pod clones a repository, runs an agent in it, and writes the outcome back onto the
Task's status. It sits beside the in-house fleet (`clusters/pi-k3s/harness-fleet/`) as a second
way to run an unattended coding worker; it does not replace it.

- Chart: `oci://ghcr.io/kelos-dev/charts/kelos`, pinned to `0.64.0`
- Console: <https://kelos.lab.mtgibbs.dev> (LAN-only, one shared login token)
- Agent: OpenCode, model `litellm/hot-coder` — qwen on the Beelink via `https://ai.lab.mtgibbs.dev/v1`
- Agent pods: namespace `kelos-tasks`, node pi5-worker-2 (`harness-fleet=true`), one at a time

## Risk — read this before adding Tasks or widening access

- **The controller's reach is cluster-wide.** The chart's controller ClusterRole
  (`kelos-controller-role`) can get, list, create and update **Secrets and ConfigMaps in every
  namespace**, and create and delete **Jobs and Deployments in every namespace** (plus delete pods,
  and create/delete Roles and RoleBindings). It cannot create bare pods directly, which changes
  nothing: a Job or Deployment is a pod. Chart 0.64.0 exposes **no value to scope it to a
  namespace**. The `kelos-tasks` namespace bounds where *we* put Tasks and how much they can
  consume; it does not bound the controller. A Task created in any other namespace would run there.
- **Agent pods run a model with an unrestricted shell, holding a GitHub token that covers all of
  the account's repos.** The Workspace sets OpenCode's `edit` and `bash` permissions to `allow`;
  the pod carries `harness-fleet/outcome-pat` (contents, pull requests and workflows, read-write).
  A prompt — or anything the model reads while working — can make it push to, or open PRs against,
  any repository that token reaches, not just the Workspace's. It also holds the fleet's LiteLLM
  key.
- **The console is a second way in.** Its ServiceAccount can create Tasks and `exec` into pods in
  every namespace, and it is guarded by a single static token shared by everyone who logs in.
  Anyone who can reach `kelos.lab.mtgibbs.dev` and has that token can run an arbitrary prompt with
  the credentials above. It is LAN-only; keep it that way (no Cloudflare tunnel route).

## Layout and deploy order

Three Flux Kustomizations (`clusters/pi-k3s/flux-system/infrastructure.yaml`), chained by
`dependsOn` with `wait: true`:

| Flux Kustomization | Directory | Holds | Ready means |
| :--- | :--- | :--- | :--- |
| `kelos` | `controller/` | `kelos-system` namespace, console-token ExternalSecret, HelmRelease (controller + console + CRDs), console Ingress | the HelmRelease is Ready: CRDs exist and the controller is serving their conversion webhook |
| `kelos-workspace` | `workspace/` | `kelos-tasks` namespace, ResourceQuota, LimitRange, the two reused ExternalSecrets, the `factory-trial` Workspace | both Secrets exist |
| `kelos-tasks` | `tasks/` | the Tasks | — |

Both splits are required, not tidiness:

- **CRDs before CRs.** `Workspace` and `Task` are `kelos.dev` kinds; they cannot apply until the
  HelmRelease has installed the CRDs. The chart also needs cert-manager first — the CRDs carry a
  conversion webhook whose certificate cert-manager issues.
- **Secrets before Tasks.** A Task is a one-shot. If its Workspace's Secret (`github-token`) does
  not exist at the moment the controller first sees the Task, the controller marks it `Failed`
  ("Failed to resolve GitHub token") and never retries. Creating the Secret afterwards does not
  revive it. So Tasks apply only after `kelos-workspace` reports both ExternalSecrets synced.

The `kelos-system` namespace is owned by Git. The chart would also render it; a `postRenderers`
patch in `controller/helmrelease.yaml` drops the chart's copy so Helm never owns (and never
deletes) a namespace that holds our ExternalSecret and Ingress.

## Submitting a Task

A Task is a manifest, submitted by PR:

1. Copy `tasks/task-smoke-word-stats.yaml` to a new file with a **new `metadata.name`**.
2. Change the `prompt`. Keep `podOverrides` (node pin, `LITELLM_KEY` env, resources) as they are
   unless you are also changing `workspace/resourcequota.yaml`.
3. Add the file to `tasks/kustomization.yaml`, open a PR, merge. Flux applies it and it runs once.

Things that will otherwise surprise you:

- **A Task's spec is immutable.** Editing a Task file after it has been applied does nothing (the
  files carry `kustomize.toolkit.fluxcd.io/ssa: IfNotExists`, so Flux never patches an existing
  Task). To run again, or run something different, add a new Task with a new name.
- **Deleting the file deletes the record.** `prune: true` removes the Task, its Job and its pod
  logs. Leave a Task in Git for as long as you want its result readable in the cluster.
- **One at a time.** The `kelos-tasks` quota fits exactly one agent pod. A second Task merged while
  one is running waits (its Job cannot create a pod until the first finishes); it is not rejected.
- **A failed attempt is retried once.** Kelos sets the Job's `backoffLimit` to 1, so a pod that
  fails gets one more pod — the agent can run twice. `activeDeadlineSeconds: 1800` caps the whole
  Job at 30 minutes.
- **To target another repository**, add a second `Workspace` under `workspace/` (same
  `secretRef`, same `setupCommand`) and reference it from the Task's `workspaceRef`.
- **Remove Tasks before removing Kelos.** Tasks carry a finalizer only the controller can clear.

Tasks can also be created from the console; those live only in the cluster, not in Git.

## Credentials — reused, and why

| Secret (namespace) | Key | 1Password | Status |
| :--- | :--- | :--- | :--- |
| `github-token` (`kelos-tasks`) | `GITHUB_TOKEN` | `harness-fleet/outcome-pat` | **Reused** from the harness fleet |
| `litellm-key` (`kelos-tasks`) | `LITELLM_KEY` | `harness-fleet/litellm-key` | **Reused** from the harness fleet |
| `kelos-console-token` (`kelos-system`) | `token` | `kelos/console-token` | Minted — the console's own login |

Credentials here scale by role, not by tool. A Kelos agent pod does the same job as a fleet worker
— clone, push a branch, open a PR, spend `hot-coder` tokens — on the same node, so it carries the
same two identities rather than a parallel pair to rotate and audit. The costs are real and
accepted for now: LiteLLM cannot tell fleet spend from Kelos spend, and revoking either credential
stops both runners. If Kelos outlives its trial, mint it its own LiteLLM key first.

Kelos requires the key name `GITHUB_TOKEN` in the Workspace's Secret. The LiteLLM key is not
something Kelos knows about (`credentials.type: none`): each Task injects it as the `LITELLM_KEY`
env var, and the Workspace's `setupCommand` writes an OpenCode config that reads it from there.

## Reading a result

`Task.status` is the record:

```bash
kubectl -n kelos-tasks get tasks
kubectl -n kelos-tasks get task smoke-word-stats -o jsonpath='{.status.phase}{"\n"}{.status.results}{"\n"}'
```

- `status.phase` — `Pending`, `Running`, `Succeeded` or `Failed`; `status.message` says why on failure.
- `status.results` — a string map the agent run fills in: `branch`, `base-branch`, `commit`, `pr`
  (the pull request URL), `input-tokens`, `output-tokens`.
- `status.usage` — the token counts again, as numbers.
- `status.jobName` / `status.podName` — where the logs are (`kubectl -n kelos-tasks logs <pod> -c kelos-agent`).

From this repo's container there is no `kubectl`: read the same fields with the homelab MCP
(`describe_resource` on the Task) or in the console at <https://kelos.lab.mtgibbs.dev> (namespace
`kelos-tasks`), which also shows the agent's log.

`Succeeded` means the agent process exited 0, not that the work is right. The pull request in the
target repository is the thing to review.

## Operating notes

- **Upgrading the chart** is a `version:` bump in `controller/helmrelease.yaml`. Helm owns the
  CRDs here (`crds.install: true`), so they move with the chart; read the chart README's upgrade
  section first, because the CRDs carry a conversion webhook the new controller must be serving.
- **The Helm release Secret is large.** With the CRDs in the release it is about 874 KB against
  Kubernetes' 1 MiB Secret limit. A future chart version with bigger CRDs can fail the upgrade with
  "Secret … is invalid: data: Too long"; the fix then is `crds.install: false` and managing the
  CRDs separately.
- **Telemetry is off** (`telemetry.enabled: false`); the chart default is a daily phone-home CronJob.
- **Not enabled:** webhook servers, Slack server, TaskSpawners, workspace `ghproxy`. TaskSpawners
  and `ghproxy` run as extra pods in the task namespace — the `kelos-tasks` quota has no room for
  them and must grow before either is used.
