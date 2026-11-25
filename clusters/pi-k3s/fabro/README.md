# Fabro

[Fabro](https://github.com/fabro-sh/fabro) (MIT) is a workflow engine for coding agents: an API
server with a web UI that walks a workflow — a graph of agent, script and human-approval stages —
and runs the agent's tools inside a Docker sandbox. It sits beside the in-house fleet
(`clusters/pi-k3s/harness-fleet/`) and Kelos (`clusters/pi-k3s/kelos/`) as a third way to run a
coding worker; it replaces neither.

- UI + API: <https://fabro.lab.mtgibbs.dev> (LAN-only, one shared login token)
- Image: `ghcr.io/fabro-sh/fabro:0.421.0-nightly.0`, pinned by digest (multi-arch, incl. arm64)
- Model: `hot-coder` — qwen on the Beelink via LiteLLM, `https://ai.lab.mtgibbs.dev/v1`
- Sandboxes: rootless Docker (`docker:29.10.0-dind-rootless`) as an **unprivileged** sidecar in the
  same pod; environment `gated-docker` (`python:3.12-bookworm`); one run at a time
- Where: namespace `fabro`, one StatefulSet pod on pi5-worker-2 (`harness-fleet=true`)

## Review this first

**(a) The sidecar is privileged only inside the pod's user namespace.** `dind` runs as uid 1000
with `privileged: true`, but the pod has `hostUsers: false`, so those capabilities apply to the
pod's user namespace and not to the node. To run rootless Docker it also needs, and has:

- `allowPrivilegeEscalation: true` — `newuidmap`/`newgidmap` are setuid binaries.
- `procMount: Unmasked` — its `/proc` has no masked paths, so it can mount a fresh `/proc` for each
  sandbox.
- the host's `/dev/net/tun`, which rootless networking opens. This is the only reason for
  `privileged`: it makes the runtime expose the node's devices. A `hostPath` volume for the device
  was the first attempt and failed on pi5-worker-2 (`failed to set MOUNT_ATTR_IDMAP on
  /dev/net/tun`): a user-namespaced pod's volumes are id-mapped mounts and devtmpfs does not
  support them. The cost is that every node device node is visible in the container; root-owned
  ones (disks, memory) cannot be opened, because root in the pod is a high unprivileged uid on
  the node.
- `seccompProfile: Unconfined` and `appArmorProfile: Unconfined` (see the table below).
- a pod-level user namespace (`hostUsers: false`), which is what makes the rest tolerable: every
  process in the pod, sandboxes included, is one unprivileged high uid on the node.

The other two containers (`fabro`, `bootstrap`) are plain: uid 1000, read-only root, all
capabilities dropped, no privilege escalation, RuntimeDefault seccomp. Nothing in the pod has a
Kubernetes service-account token.

What was tried to tighten the sidecar, on the test cluster:

| Setting | Tried | Result | Kept |
| :--- | :--- | :--- | :--- |
| seccomp on `dind` | `RuntimeDefault` | **Fails.** `[rootlesskit:parent] error: failed to start the child: fork/exec /proc/self/exe: operation not permitted`; the container crash-loops. The default profile refuses the user-namespace clone. | `Unconfined` |
| AppArmor on `dind` | field removed (runtime default) | Pod ran — but the result is **void**: the test cluster's kernel has no AppArmor, so no profile was ever applied. | `Unconfined`, as the prototype had it |
| Pod Security label on the namespace | none (prototype had `enforce: privileged`) | Pod admitted and ran. This cluster enforces no Pod Security default, so the label granted nothing. | no label |

A custom seccomp profile (RuntimeDefault plus the handful of calls rootlesskit needs) would be
tighter than `Unconfined`. It needs a profile file on the node, which is host configuration this
repo has no automation for; not attempted.

**(b) This was proven on k3d, not on the Raspberry Pi nodes.** The test cluster was k3d on a Mac:
k3s v1.35.5, containerd 2.2.3, kernel 7.0.14-linuxkit, arm64. The pod has **never run on a Pi**.
It depends on four things the Pi kernel and runtime must provide:

1. user namespaces for pods (`hostUsers: false`) — kubelet, containerd and runc support, plus
   id-mapped mounts in the kernel for the pod's volumes;
2. unprivileged user namespaces (rootless Docker creates a nested one for the sandboxes);
3. overlayfs inside a user namespace (the sidecar's image store);
4. the runtime exposing `/dev/net/tun` to a container that is privileged inside a pod user
   namespace.

Seen on pi5-worker-2 (2026-11-20): items 1 held for the `fabro` and `bootstrap` containers
(both ran with `hostUsers: false`, volumes mounted); the `hostPath` form of item 4 failed.

What this repo records about the nodes: **k3s v1.34.3+k3s1** on all four, **Raspberry Pi OS Lite
64-bit / Debian 13**. It records **no kernel version, no containerd version, and nothing about
AppArmor**. Kubernetes 1.34 has pod user namespaces and `procMount` on by default (both since
1.33), so the Kubernetes side is expected to be fine; whether the node's containerd and kernel
deliver it is **unknown** from the repo. A cheap check before merging — the node reports it:

```bash
kubectl get node pi5-worker-2 -o jsonpath='{.status.runtimeHandlers}'
# want: "userNamespaces":true on the default handler (the test cluster's node reports exactly that)
ssh pi5-worker-2 'uname -r; ls -l /dev/net/tun; cat /sys/module/apparmor/parameters/enabled'
```

**If the pod does not come up on the Pi**, the fallback is the same rootless image run as a
`privileged` container without the pod user namespace. It is a ready patch,
`server/fallback-privileged-dind.patch`: add it under `patches:` in
`server/kustomization.yaml` and merge (the file's header has the three lines). It was tested on
the same test cluster — pod Ready, a sandbox ran. Understand what it gives up before using it:
the sidecar becomes a privileged container on the host, and everything in (a) about "one
unprivileged uid on the node" stops being true. If only one piece fails (say, `/dev/net/tun`),
prefer fixing that piece.

**(c) Sandbox CPU and memory limits are not enforced.** Rootless Docker here runs without cgroup
delegation (`Cgroup Driver: none`). An environment's `resources` (2 CPU / 2GB for `gated-docker`)
are accepted and ignored — measured: a container started with `--memory 64m --cpus 1` saw the
sidecar's 3Gi / 3 CPU. The only bound is the `dind` container's own limit — 3 CPU / 3Gi for
all sandboxes together — which is also why `max_concurrent_runs = 1`. Its image store is an
`emptyDir` capped at 8Gi on the node's disk; exceeding that evicts the pod. Finished sandbox
containers were seen left behind (stopped, not removed), so expect that space to grow between pod
restarts.

**(d) Sandboxes hold a GitHub token that covers all of the account's repos.** With the `token`
GitHub strategy Fabro injects the PAT itself (`harness-fleet/outcome-pat`: contents, pull requests
and workflows, read-write) into the sandbox as `GITHUB_TOKEN`. A prompt — or anything the model
reads while working — can make the agent push to, or open PRs against, any repository that token
reaches, not just the run's target. Fabro's fix is its GitHub App strategy (short-lived tokens
scoped to named repositories); that needs an App registered and is not set up.

Also new relative to the prototype: the server no longer disables pushing. Every run pushes its
branch `fabro/run/<run-id>` to the target repository after each stage (Fabro's default). Pull
requests stay off unless a workflow enables them.

**(e) Fabro calls itself a research preview.** No third-party security testing. One shared login
token, no users, no roles: whoever has the token can do everything, including run an arbitrary
workflow with the credentials above. Its vault is **plaintext** in the SQLite database on the PVC
— and therefore also in the weekly copy `worker2-backup` writes to the QNAP. Keep it LAN-only (no
Cloudflare tunnel route). The image is a nightly build.

**(f) A sandbox can reach the Fabro API.** The NetworkPolicy bounds what leaves the pod; a sandbox
talking to the pod's own IP on :32276 never leaves it (measured: reachable). The API still wants
the login token, which sandboxes are not given, so today this is an unauthenticated caller
reaching `/health` and the login page. It becomes a real hole the moment a workflow puts the
token in a sandbox's environment — don't.

## Layout and deploy order

Two Flux Kustomizations (`clusters/pi-k3s/flux-system/infrastructure.yaml`), chained by
`dependsOn` with `wait: true`:

| Flux Kustomization | Directory | Holds | Ready means |
| :--- | :--- | :--- | :--- |
| `fabro-secrets` | `secrets/` | `fabro` namespace, the two ExternalSecrets | both Secrets exist |
| `fabro` | `server/` | StatefulSet (server + rootless Docker + bootstrap), Service, Ingress, NetworkPolicy, ConfigMaps | the pod is Ready: server healthy, Docker up, bootstrap finished |

`examples/` is not applied by anything.

The split is weaker-motivated than Kelos' and it is worth being honest about that. Kelos needed
its stages: a Task whose Secret is missing fails permanently. Nothing here does — a pod created
before its Secrets exist just waits in `CreateContainerConfigError` and starts when they arrive.
What the split buys is attribution: a 1Password/ESO outage shows as `fabro-secrets` not Ready,
instead of as `fabro` burning its 10-minute timeout on a pod that cannot start. One stage would
also converge.

## What the bootstrap does

Fabro reads its settings from a file, but keeps provider keys, the GitHub token and sandbox
environments in its own database, settable only through its API against a running server. So the
pod carries a third container, `bootstrap` (`server/bootstrap.sh`), which on **every pod start**:

1. waits for `GET /health`;
2. writes every key of the `fabro-vault-seed` Secret into the vault (`LITELLM_API_KEY`,
   `GITHUB_TOKEN`);
3. creates, or replaces, one environment per `server/environment-<id>.json`;
4. turns Ready, and idles.

The pod is not Ready — and the Service has no endpoint — until that has finished, so "Ready" means
"configured". On an empty PVC that took about ten seconds on the test cluster. Git wins on every
start: an environment edited in the UI is put back. The ConfigMap with the settings, the script
and the environment files is name-hashed, so editing any of them rolls the pod.

It does **not** pre-pull the sandbox image. Fabro's Docker provider pulls a missing image itself
when a run first needs it (measured: empty image store, first run pulled `python:3.12-bookworm`
and succeeded, 13 s to sandbox-ready on a fast link). The sidecar's image store is empty after
every pod restart, so the first run after a restart pays for the pull — expect minutes, not
seconds, on a Pi.

To change things:

- **another vault secret** — add a key to `secrets/external-secret-vault-seed.yaml`;
- **another environment** — add `server/environment-<id>.json` (the definition without its `id`)
  and list it in `server/kustomization.yaml`;
- **a rotated credential** — update 1Password, wait for the ExternalSecret to refresh, then delete
  the pod (the bootstrap only runs at start; the dev token and session secret are env vars).

## Logging in

The login token is **`fabro/dev-token` in 1Password** (vault `pi-cluster`); it has the form
`fabro_dev_` followed by 64 hex characters.

- **Web**: open <https://fabro.lab.mtgibbs.dev> and paste the token on the login page.
- **CLI**: `fabro auth login --server https://fabro.lab.mtgibbs.dev --dev-token <token>` — it is
  stored in `~/.fabro/auth.json`; later commands take `--server` (or `FABRO_SERVER`).
- **REST**: `Authorization: Bearer <token>` on anything under `/api/v1`.

## Starting a run

A workflow is a DOT graph (`workflow.fabro`): nodes are stages — agent prompts, shell scripts,
human gates — and edges carry the conditions for moving between them. The example that was run
end to end against the prototype is `examples/gated-build-v2/workflow.fabro`; read
`examples/README.md` before reusing it.

There is no `default` environment here, so a run must name one: `gated-docker`.

- **UI** — "Start new run", pick the workflow source, the target repository and the environment.
- **CLI** (from Fabro's CLI reference; this exact command has not been run against this server) —
  ```bash
  fabro run examples/gated-build-v2/workflow.fabro \
    --server https://fabro.lab.mtgibbs.dev \
    --environment gated-docker --target mtgibbs/factory-trial
  ```
- **REST** — three calls, which is how the prototype's runs were started:
  ```bash
  S=https://fabro.lab.mtgibbs.dev/api/v1; A="Authorization: Bearer $FABRO_DEV_TOKEN"
  # 1. register the workflow's files -> workflow_version_id
  jq -n --rawfile g workflow.fabro \
    '{entrypoint:"workflow.fabro", files:{"workflow.fabro":$g}, workflow_dependencies:{}}' \
    | curl -fsS -H "$A" -H 'Content-Type: application/json' -d @- $S/workflow-versions
  # 2. create the run -> id
  curl -fsS -H "$A" -H 'Content-Type: application/json' $S/runs -d '{
    "workflow_version_id": "<id from 1>",
    "target": {"kind": "git", "repo": "mtgibbs/factory-trial", "branch": "main"},
    "args": {"model": "hot-coder", "provider": "litellm"},
    "environment_id": "gated-docker", "title": "gated-build-v2"}'
  # 3. start it
  curl -fsS -X POST -H "$A" $S/runs/<id from 2>/start
  ```
  A run waiting at a human gate lists its question at `GET /runs/<id>/questions`.

A run that changes files pushes `fabro/run/<run-id>` to the target repository. To have it open a
pull request as well, put a `workflow.toml` beside the graph with `[run.pull_request] enabled =
true`. Fabro's documentation says in one place that automatic PRs need the GitHub App strategy and
in another that the `token` strategy supports pull requests; **which is true here is not tested.**

The sandbox can reach the public internet on TCP 443 and the model endpoint, and nothing else:
not port 80 (so `apt` against http mirrors fails — use pip/npm, or a different image), not the
LAN, not the cluster.

## Credentials — reused, and why

| Secret (namespace `fabro`) | Key | 1Password | Status |
| :--- | :--- | :--- | :--- |
| `fabro-vault-seed` | `LITELLM_API_KEY` | `fabro/litellm-key` | Minted 2026-11-25 — Fabro's own LiteLLM key: `hot-coder`, `claude-haiku`, `claude-sonnet`; $100 per 30 days (only Claude spends it) |
| `fabro-vault-seed` | `GITHUB_TOKEN` | `harness-fleet/outcome-pat` | **Reused** from the harness fleet |
| `fabro-server-env` | `FABRO_DEV_TOKEN` | `fabro/dev-token` | Minted — Fabro's own login |
| `fabro-server-env` | `SESSION_SECRET` | `fabro/session-secret` | Minted — its cookie key |

Credentials here scale by role, not by tool. For GitHub a Fabro run does the job a fleet worker
and a Kelos agent pod already do — clone, push a branch, open a PR — so it carries the same PAT
rather than a third one to rotate and audit; the cost is that revoking it stops all three. Replace
it with a GitHub App if Fabro outlives its trial (risk (d)).

The LiteLLM key is Fabro's own since 2026-11-25. Fabro is the one runner allowed hosted models
(`claude-haiku`, `claude-sonnet`, chosen per stage by a workflow's model stylesheet), and a
hosted-model budget has to be attributable to the workload that spends it. `hot-coder` has no
price in LiteLLM, so local runs do not draw on the $100.

The key names are Fabro's, not ours: its `litellm` provider looks up `LITELLM_API_KEY` and its
`token` GitHub strategy looks up `GITHUB_TOKEN`, both in its vault. Neither is read from the
server's environment.

## Operating notes

- **Data**: `/storage` is the PVC `storage-fabro-0` (local-path, on pi5-worker-2) — the SQLite
  database and run artifacts. Never NFS. It is created by the StatefulSet, not by Flux, so
  removing Fabro from Git leaves it behind; delete it by hand if you mean to.
- **Backup**: `fabro_storage-fabro-0` rides `worker2-backup` (weekly, to the QNAP). It is a live
  copy of an open SQLite file and it contains the plaintext vault. A rebuild does not need it —
  the bootstrap re-provisions everything except run history.
- **Upgrading**: change the image tag and digest on the `fabro` container in
  `server/statefulset.yaml` (the `bootstrap` container is a separate curl image). Fabro migrates
  its database on start and leaves `fabro.sqlite3.pre-migration.bak` beside it.
- **Reaching it without the ingress**: with `server.web.url` set to the public origin, the UI
  redirects any other host name to `https://fabro.lab.mtgibbs.dev`. The API does not, so
  `kubectl port-forward` works for API calls and the CLI.
- **Monitoring**: Uptime Kuma and the Homepage tile probe `https://fabro.lab.mtgibbs.dev/health`,
  the unauthenticated health endpoint.
