# agents — the sandbox where short-lived AI agent Jobs run

This namespace is where the agent sandbox's **runner** lives and where it launches **agents**:
one Kubernetes Job per run, each a small model-driven loop with a narrow allowlist of tools, a
deadline, and no Kubernetes credentials. The contracts between the parts are in
`scripts/agentrunner/CONTRACT.md`. In short, n8n decides *when* to run something, the runner decides
*how*, the `agent-runtime` image decides *what*, and the existing gates decide *whether* anything
ships.

```
n8n ──POST /runs──▶ agent-runner (Deployment) ──creates──▶ Job run-<id> (agent-runtime image)
 ▲                        │ reads ::agent-result:: from the pod log      │
 └──── callback ──────────┘                                              ├─▶ LiteLLM (192.168.1.70:443)
                                                                         └─▶ allowlisted MCP tools
```

> **Status, 2026-11-11:** activated. Checklist steps 1, 2 and 4–6 are done: the 1Password fields exist, both
> images are built and public, and the Kustomization is registered as entry 37. Step 3 (a `claude-haiku`
> alias) is not done, so the agent runs on `hot-coder` only. Step 7's n8n import and step 8's live checks
> remain. The section below is kept as the record of why it landed inert first.

## This directory is inert, on purpose

**It is NOT registered in `clusters/pi-k3s/flux-system/infrastructure.yaml`.** Like `harness-fleet`
before it, it lands ahead of the things it needs. The 1Password fields don't exist yet, and neither
do the `agent-runner` / `agent-runtime` images. Registering it now would give you a Kustomization
that fails on every reconcile (`SecretSyncErr`, `ImagePullBackOff`) and alerts about a namespace
nobody uses. Work through the checklist below first. After that, `wait: true` turns failures into
useful ones: the Kustomization goes red if a secret stops resolving.

## What each file guarantees

| File | Safety property |
|---|---|
| `namespace.yaml` | Pod Security **`restricted` enforced** (plus audit and warn). A root, privileged or hostPath pod is refused at admission. |
| `serviceaccounts.yaml` | Agents run as `agent-run`, which has **no RBAC and no mounted token**, so a compromised agent can't talk to the API server. The namespace `default` SA also has its token turned off. |
| `rbac.yaml` | `agent-runner` can only create, get, list, watch and delete **Jobs**, get and list **pods**, and get **pods/log**, all **in this namespace**. It has **no Secret verbs** and nothing cluster-scoped. It launches agents but can't read their credentials. |
| `resourcequota.yaml` | **At most 2 agents run at once** (`pods: 3` = runner + 2). Compute is capped at runner + 2 × the LimitRange max. No NodePorts or LoadBalancers. The header explains why the cap is `pods` and not `count/jobs.batch`: finished Jobs stay around for an hour. |
| `limitrange.yaml` | Default 1 CPU / 512Mi limit, max 1 CPU / 1Gi per container. Manifests that leave out `resources` still pass the quota. |
| `networkpolicies.yaml` | **Default-deny in both directions.** Agents may reach only DNS and the LiteLLM gateway. `media-investigator` may also reach the homelab MCP on :3000. The runner accepts traffic only from `n8n` on :8080, and may reach only DNS, the Kubernetes API (192.168.1.55:6443) and n8n on :5678. |
| `external-secret-runner.yaml` | The runner's bearer token, Tier 2, kept in the `pi-cluster` vault (Touch ID). |
| `external-secret-media-investigator.yaml` | The agent's own scoped LiteLLM key plus the **reused read-only** homelab-MCP key, both Tier 1, in the `homelab-agent` vault. Each agent gets its own Secret. |
| `manifests/media-investigator.yaml` | A read-only investigator with an allowlist of 7 read-only MCP tools. Tools that could make the MCP server contact an arbitrary host are left out. |
| `kustomization.yaml` | The `configMapGenerator` builds `agent-manifests` with a hash suffix, so any manifest edit rolls the runner. |
| `deployment.yaml` / `service.yaml` / `pvc.yaml` | Restricted-compliant runner on the Pi 5 workers, **ClusterIP only, no Ingress**. The dedupe and daily-cap ledger is on a PVC so it survives a restart. `RUNNER_PAUSED` is the kill switch. |
| `image-automation.yaml` | Flux bumps the runner's image tag automatically. The agent-runtime tag in each manifest is deliberately **not** automated. |

What this does **not** cover: the read-only MCP key limits *which tools* an agent can call, not
*what data* they return. `get_pod_logs` can read any namespace's logs. Agents also hold their own
LiteLLM key, so the **LiteLLM key's model allowlist and budget** are the real spend boundary.

## Activation checklist (human-only, in order)

1. **Create the runner token.** In the `pi-cluster` vault, create item `agent-runner` with field
   `api-token` set to a long random value. Put the same value in n8n's credential store when the
   workflow that calls the runner is built.
2. **Mint the media-investigator LiteLLM key.** Create a virtual key on the Beelink LiteLLM with
   `models: [hot-coder, claude-haiku]`, a daily `max_budget` with `budget_duration: 1d`, and a
   recognisable alias such as `agent-media-investigator`. Store it in the **`homelab-agent`** vault
   as item `agent-media-investigator`, field `litellm-key`. Don't create the MCP key: it reuses the
   existing `mcp-homelab-readonly/password`, which is already in `homelab-agent`.
3. **Add the `claude-haiku` alias in LiteLLM if you want it.** The manifest tries `hot-coder` first
   and moves to the next model only on an API error. If the alias doesn't exist, that fallback just
   fails, so either add the alias or drop it from `model.allow`.
4. **Merge so CI builds the images.** That means `ghcr.io/mtgibbs/agent-runner:0.1.0` and
   `ghcr.io/mtgibbs/agent-runtime:0.1.0`, both multi-arch including arm64, because the Pis are ARM.
5. **Make the GHCR packages pullable.** Either make both packages **public**, or keep them private and
   add a pull secret. Public is fine because neither image contains PII; the agent's prompt is in this
   repo, not in the image. For private, copy `harness-fleet/external-secret-ghcr.yaml` into this
   directory with `namespace: agents` (this reuses `ghcr-read-token`, so no new credential), then add
   `imagePullSecrets: [ghcr-pull-secret]` to **both** `agent-runner` and `agent-run` in
   `serviceaccounts.yaml`. The rendered Job doesn't name a pull secret, so the SA has to carry it.
6. **Register the Flux Kustomization.** Append this to `clusters/pi-k3s/flux-system/infrastructure.yaml`:

   ```yaml
   ---
   # NN. agents - the agent sandbox: agent-runner Deployment + short-lived agent Jobs
   # (clusters/pi-k3s/agents/README.md). Needs 1Password: pi-cluster/agent-runner/api-token,
   # homelab-agent/agent-media-investigator/litellm-key (+ reused mcp-homelab-readonly/password).
   apiVersion: kustomize.toolkit.fluxcd.io/v1
   kind: Kustomization
   metadata:
     name: agents
     namespace: flux-system
   spec:
     dependsOn:
       - name: external-secrets-config
     interval: 10m
     path: ./clusters/pi-k3s/agents
     prune: true
     sourceRef:
       kind: GitRepository
       name: flux-system
     wait: true
     timeout: 5m
   ```

   After merging, reconcile the source first and then the Kustomization (`docs/flux-gitops.md`).

7. **Let n8n notify you.** Add `ntfy access family "agent-runs" rw || true` to the ACL seed in
   `clusters/pi-k3s/ntfy/deployment.yaml` (its own PR: it restarts ntfy). Then import
   `clusters/pi-k3s/n8n/workflows/agent-run-manual.json` and create the `agent-runner` credential,
   following `docs/agent-sandbox-n8n.md`.
8. **Verify live.** These can only be checked on the cluster, after deploy:
   - Both ExternalSecrets are `SecretSynced`. With `wait: true`, the Kustomization being Ready already
     means this.
   - `kubectl get endpoints kubernetes -n default` shows `192.168.1.55:6443`. The runner's API egress
     rule assumes exactly this. If the runner's Job creation times out, check this first.
   - The runner turns Ready. If it flaps on `/healthz` with no app error, kube-router isn't letting
     kubelet probes through default-deny; add a rule allowing ingress from the node IPs on 8080.
   - **Positive control for the NetworkPolicies:** a throwaway pod in `agents` with the agent labels
     should reach `ai.lab.mtgibbs.dev:443` and should **fail** to reach, for example,
     `1.1.1.1:443` and `storage.lab.mtgibbs.dev`. A deny you've never seen deny proves nothing.
   - Run one `media-investigator` from n8n end to end and read the callback.

Also update the node-workload list in `ARCHITECTURE.md` (Decision #13) when the runner lands on
`pi5-worker-1` / `pi5-worker-2`.

## Adding an agent

1. Write `manifests/<name>.yaml` (CONTRACT §2). The file name must equal `name`.
2. List it under `configMapGenerator.files` in `kustomization.yaml`. There's no glob support.
3. Add `external-secret-<name>.yaml`: one Secret per agent, with a LiteLLM key minted for that agent,
   reusing existing items for connector keys.
4. Give it egress only if it needs more than DNS and LiteLLM: add an `agent: <name>` policy to
   `networkpolicies.yaml`.
5. Regenerate the docs: `bash scripts/check-generated-docs.sh`.
