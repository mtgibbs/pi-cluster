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

## Agent roster

| Agent | Started by | Tools | Output | Status |
|---|---|---|---|---|
| `media-investigator` | n8n form (`agent-run-manual`), by hand | 7 read-only homelab MCP tools (media-focused) | `report` | slice 1 — active |
| `ops-investigator` | Alertmanager → n8n `agent-alert` webhook, automatically (warning/critical) | 15 read-only homelab MCP tools (cluster-wide triage) | `report` | slice 2 — manifests landed; see its activation checklist |
| `sec-researcher` | n8n `agent-sec-researcher`: a Flux revision that touched access-control paths; the weekly sweep (Sun 06:00); Matt's form | Read-only repo checkout (Flux artifact, `repo__*` tools) + 4 read-only homelab MCP tools | `plan` — **filed as issues by n8n**, not by the agent | slice 3 — landed inert-safe; see its activation checklist |

## Activation checklist for `sec-researcher` (slice 3, human-only, in order)

The agent holds **no** GitHub credential and the runner holds no GitHub App key: the agent returns `plan` items and
the n8n workflow files them (`docs/agent-sandbox-n8n.md`, "sec-researcher"). As with slice 2, `wait: true` means a
missing 1Password item turns the whole `agents` Kustomization red — do step 2 **before** merging.

1. **Create the private plans repo** `mtgibbs/homelab-plans` (private; issues on). Optionally create the labels
   `sec-researcher`, `accepted-risk`, `severity:critical|high|medium|low|info` (GitHub creates missing labels on
   issue create when the token may; the lookup does not depend on labels — it reads a marker in the issue body).
2. **Mint the sec-researcher LiteLLM key** on the Beelink LiteLLM: `models: [claude-haiku, claude-sonnet]` (never
   Opus), `max_budget: 3`, `budget_duration: 1d`, alias `agent-sec-researcher`. Store it in the **`homelab-agent`**
   vault as item `agent-sec-researcher`, field `litellm-key`. The MCP key is the reused
   `mcp-homelab-readonly/password`; don't mint one. Both aliases must exist in LiteLLM (`claude-haiku` is still open
   from slice 1, step 3); without `claude-sonnet` the weekly sweep falls back to Haiku.
3. **Mint the n8n GitHub token** — a fine-grained PAT (or App installation token) with **Issues: read and write** on
   `mtgibbs/homelab-plans` **only** (Metadata: read is implied). Store it in 1Password (e.g. `pi-cluster/github-plans`,
   field `token`) for rotation; n8n holds the working copy as Header-Auth credential `github-plans`
   (`Authorization: Bearer <token>`). Restrict the credential's allowed domains to `api.github.com`.
4. **No new Flux→n8n token.** `flux-notifications/n8n-agents.yaml` reuses `pi-cluster/n8n-agent-alert-webhook/token`
   (the same "in-cluster sender → n8n agent webhook" identity Alertmanager uses), so that item must exist — it is
   step 2 of the slice-2 checklist. If it does not, `flux-notifications` goes not-Ready (it also has `wait: true`).
5. **Merge.** CI pushes `agent-runner:0.3.0` and `agent-runtime:0.2.0`; Flux image automation bumps the runner tag.
   The manifest pins `agent-runtime:0.2.0` (not automated, as for the other agents). Until the 0.3.0 runner is live,
   the old runner refuses the sec-researcher manifest (unknown keys `checkout`, `by_event_type`) with 422 — nothing
   else is affected. Reconcile the source, then `agents` and `flux-notifications`.
6. **Import the n8n workflow** `clusters/pi-k3s/n8n/workflows/agent-sec-researcher.json` (credentials: patch
   `REPLACE_ON_IMPORT_agent_alert_token`, `REPLACE_ON_IMPORT_agent_runner`, `REPLACE_ON_IMPORT_github_plans`), activate
   it, and do the webhook-tier `restarted-at` roll so `/webhook/agent-sec-revision` is served
   (`docs/agent-sandbox-n8n.md`, "sec-researcher → Import").
7. **Verify live** (none of this could be checked from the PR):
   - `agents/agent-sec-researcher` and `flux-system/n8n-agent-flux-webhook` are `SecretSynced`; Provider
     `n8n-agents` and Alert `sec-researcher-revisions` are Ready.
   - **Checkout path (untested live):** a sec-researcher Job's `checkout` init container logs `"event": "checkout",
     "ok": true`. Runtime ≥ 0.2.1 retries connection errors for ~45 s (`checkout_attempt` lines show each try), so a
     brief refusal while kube-router programs a new pod's rules is absorbed; if it still fails with
     `… after <n> attempts`, kube-router is blocking agents → source-controller:9090: check
     NetworkPolicies `agents/agent-checkout-egress` and `flux-system/allow-agent-checkout`. **Positive control:** a
     throwaway pod in `agents` labelled `app.kubernetes.io/part-of: agent-sandbox, agent: sec-researcher` can
     `wget http://source-controller.flux-system.svc.cluster.local./gitrepository/flux-system/flux-system/<sha>.tar.gz`
     (`<sha>` = the GitRepository's current `.status.artifact.revision`);
     the same pod labelled `agent: media-investigator` cannot. There is **no `latest.tar.gz`** — source-controller
     serves artifacts only by sha (2026-11-13: a manual run on runner 0.3.0 failed "latest artifact not found (HTTP
     404)"). Runner ≥ 0.4.0 reads the current sha from the GitRepository (Role `flux-system/agent-runner-checkout-source`);
     a manual run refused with "no repository revision to check out … (kubernetes API error 403)" means that Role or
     its binding is missing.
   - Submit the form (`/form/agent-sec-run`) with a narrow focus: a push `sec-researcher: …` arrives, and either
     issues appear in `homelab-plans` or the push says why not.
   - Re-run the same focus: the existing issues show `unchanged`/`updated`, no duplicates. Close one as *not
     planned*; the next run reports it `skipped (accepted risk)`.
   - Merge a harmless PR that only bumps an image tag: n8n gets ONE Flux event (GitRepository `NewArtifact`),
     `Path Filter` says "no access-control change", no run. Merge one that touches a `networkpolicies.yaml`: one
     run. Between merges the `agent-sec-researcher` execution list stays quiet (the first Alert matched every
     Kustomization reconcile: ~250 executions/hour, all dropped at `Claim`).
   - **Negative:** POST to `/webhook/agent-sec-revision` without the bearer → 403.

## Activation checklist for `ops-investigator` (slice 2, human-only, in order)

The `agents` Kustomization has `wait: true`, so a missing 1Password item turns the **whole** Kustomization
red (and blocks media-investigator updates). Do steps 1–2 **before** merging.

1. **Mint the ops-investigator LiteLLM key** on the Beelink LiteLLM: `models: [hot-coder, claude-haiku]`,
   `max_budget: 3`, `budget_duration: 1d`, alias `agent-ops-investigator`. Store it in the
   **`homelab-agent`** vault as item `agent-ops-investigator`, field `litellm-key`. The MCP key is the
   reused `mcp-homelab-readonly/password`; don't mint one.
2. **Create the Alertmanager→n8n webhook token.** In the **`pi-cluster`** vault, create item
   `n8n-agent-alert-webhook` with field `token` set to a long random value (`openssl rand -hex 32`).
   The `monitoring` ExternalSecret `alertmanager-n8n-agents` reads it; Alertmanager sends it as
   `Authorization: Bearer <token>`. Until it exists, that ExternalSecret fails, the Secret is missing,
   and the Alertmanager pod cannot mount it (it will not start after its next roll).
3. **Give n8n the same token.** Create an n8n Header Auth credential (name `Authorization`, value
   `Bearer <token>`) and attach it to the `agent-alert` Webhook node, following
   `docs/agent-sandbox-n8n.md`. Import/activate the alert workflow there.
4. **`claude-haiku` alias** — same caveat as step 3 of the slice-1 checklist below: without the alias
   the fallback just fails, so the agent effectively runs on `hot-coder`.
5. **Merge**, reconcile the source, then `agents` and `monitoring` (`docs/flux-gitops.md`).
6. **Verify live.**
   - `agents/agent-ops-investigator` and `monitoring/alertmanager-n8n-agents` are `SecretSynced`.
   - NetworkPolicy `agent-media-investigator-egress` is gone (pruned) and `agent-mcp-homelab-egress`
     exists; a media-investigator run still reaches the MCP (the rename must not cut slice 1 off).
   - Alertmanager's status page lists receiver `n8n-agents`; Discord still receives the same alerts.
   - **Positive control:** fire a test warning alert (e.g. `amtool alert add` against Alertmanager, or a
     throwaway PrometheusRule) and watch n8n get a request with the bearer header, the runner start an
     `ops-investigator` Job, and the callback arrive. Then send one request **without** the header and
     confirm n8n refuses it (403) — a gate you have never seen refuse proves nothing.
   - The runner's daily cap (`runs_per_day: 12`), its concurrency gate (2 Jobs) and bounded queue (8 runs,
     45m) bound an alert storm; see "Bursts" below for the burst check.

## Bursts: the concurrency gate and queue (runner 0.2.0)

On 2026-11-11, enabling the `n8n-agents` route made Alertmanager flush 8 already-firing groups in a minute.
Runner 0.1.0 created 8 Jobs at once; the quota admitted 2 pods, and the other 6 Jobs sat in `FailedCreate
… exceeded quota` while their 15-minute deadlines ran. Since 0.2.0 the runner itself never has more than
`RUNNER_MAX_CONCURRENT` agent Jobs. Further runs are accepted (202 `"status":"queued"`) but get **no Job**
until a slot frees, then start in FIFO order, and their deadline counts from Job creation.

| Knob (`deployment.yaml`) | Default | Meaning |
|---|---|---|
| `RUNNER_MAX_CONCURRENT` | 2 | Agent Jobs alive at once. **Keep `resourcequota.yaml` `pods` = this + 1** (the runner's own pod). |
| `RUNNER_MAX_QUEUE` | 8 | Runs waiting. Beyond it POST /runs is 429 `{"error":"queue_full"}` (the daily-cap 429 body is unchanged). |
| `RUNNER_MAX_QUEUE_WAIT` | 45m | A run queued longer ends `exit_reason: queue_expired` with the normal callback; n8n records it and sends a quiet "not investigated (queue busy)" push. |

- The daily cap still counts at accept: a burst of 10 still uses 10 of ops-investigator's 12 runs/day. The
  Alertmanager route now excludes the Beelink/LiteLLM alerts the agent has no tools for, which removes most of
  those runs.
- `GET /runs/<id>` shows `queued` with `position`.
- `RUNNER_PAUSED=true` also stops queued runs from starting (they expire).
- Restarts: launched runs are re-adopted (as in 0.1.0) and queued runs are restored in order. A queued run's
  event sits in `/var/lib/agent-runner/queue/<run_id>.json` on the ledger PVC until its Job starts.
- **n8n:** `agent-alert.json`'s Wait limit is 75 min (45m queue + 15m run + grace). It is not read from Git,
  so **re-import it** after the 0.2.0 runner is live (`docs/agent-sandbox-n8n.md`, "Re-import after the
  burst-handling change"). `agent-run-manual.json` is unchanged; its 30-minute Wait can give up on a manual run
  that queued (known gap, documented there).
- **Image:** merging bumps `scripts/agentrunner/VERSION` to 0.2.0, CI pushes `agent-runner:0.2.0`, and Flux
  image automation commits the tag into `deployment.yaml`. Don't hand-bump it: with `strategy: Recreate`, a tag
  that isn't pushed yet takes the runner down (ImagePullBackOff) until CI finishes.
- **Verify live:** fire 4 test groups at once (test plan step 5a in `docs/agent-sandbox-n8n.md`). Expect 2 Jobs,
  2 `queued` runs that start as the first two finish, and no `FailedCreate` events in `agents`.

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
| `resourcequota.yaml` | **At most 2 agents run at once** (`pods: 3` = runner + 2). This is the backstop; the runner's own gate (`RUNNER_MAX_CONCURRENT=2`) is the first line. Compute is capped at runner + 2 × the LimitRange max. No NodePorts or LoadBalancers. The header explains why the cap is `pods` and not `count/jobs.batch`: finished Jobs stay around for an hour. |
| `limitrange.yaml` | Default 1 CPU / 512Mi limit, max 1 CPU / 1Gi per container. Manifests that leave out `resources` still pass the quota. |
| `networkpolicies.yaml` | **Default-deny in both directions.** Agents may reach only DNS and the LiteLLM gateway. Agents named in `agent-mcp-homelab-egress` (`media-investigator`, `ops-investigator`, `sec-researcher`) may also reach the homelab MCP on :3000. Agents named in `agent-checkout-egress` (`sec-researcher`) may reach Flux source-controller :9090 for their repo checkout, matched by `flux-system/allow-agent-checkout` (the only object here outside `agents`: Flux's own policies admit no cross-namespace traffic to :9090). The runner accepts traffic only from `n8n` on :8080, and may reach only DNS, the Kubernetes API (192.168.1.55:6443) and n8n on :5678. |
| `external-secret-runner.yaml` | The runner's bearer token, Tier 2, kept in the `pi-cluster` vault (Touch ID). |
| `external-secret-media-investigator.yaml` | The agent's own scoped LiteLLM key plus the **reused read-only** homelab-MCP key, both Tier 1, in the `homelab-agent` vault. Each agent gets its own Secret. |
| `manifests/media-investigator.yaml` | A read-only investigator with an allowlist of 7 read-only MCP tools. Tools that could make the MCP server contact an arbitrary host are left out. |
| `external-secret-ops-investigator.yaml` | Same shape as media-investigator's: its own scoped LiteLLM key plus the **reused read-only** homelab-MCP key, `homelab-agent` vault. |
| `external-secret-sec-researcher.yaml` | Same shape again: its own scoped LiteLLM key (Haiku + Sonnet only) plus the **reused read-only** MCP key. No GitHub credential: n8n files its plans. |
| `manifests/sec-researcher.yaml` | Read-only access-control review. `checkout:` gives it a read-only copy of the repo from the Flux artifact (no internet egress); 4 read-only MCP tools; `outputs: [plan]` only; Sonnet only for `security.sweep` (`model.by_event_type`). |
| `manifests/ops-investigator.yaml` | Read-only alert triage, started by Alertmanager via n8n. 15 read-only MCP tools, **including** `diagnose_dns` and `get_node_networking` (a DNS-lookup side channel, accepted for DNS triage — see the manifest header). Proposes fixes, never applies them. |
| `kustomization.yaml` | The `configMapGenerator` builds `agent-manifests` with a hash suffix, so any manifest edit rolls the runner. |
| `deployment.yaml` / `service.yaml` / `pvc.yaml` | Restricted-compliant runner on the Pi 5 workers, **ClusterIP only, no Ingress**. The dedupe and daily-cap ledger is on a PVC so it survives a restart. `RUNNER_PAUSED` is the kill switch. |
| `image-automation.yaml` | Flux bumps the runner's image tag automatically. The agent-runtime tag in each manifest is deliberately **not** automated. |

What this does **not** cover: the read-only MCP key limits *which tools* an agent can call, not
*what data* they return. `get_pod_logs` can read any namespace's logs. Agents also hold their own
LiteLLM key, so the **LiteLLM key's model allowlist and budget** are the real spend boundary.

## Activation checklist — slice 1 / media-investigator (human-only, in order)

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
   `networkpolicies.yaml`. A manifest with `checkout:` (CONTRACT §4a) must be added to BOTH lists in
   `agent-checkout-egress` and `flux-system/allow-agent-checkout`, and needs `agent-runtime` ≥ 0.2.0.
5. Regenerate the docs: `bash scripts/check-generated-docs.sh`.
