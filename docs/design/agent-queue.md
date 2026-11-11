# Agent queue — topic-subscribed, ephemeral, least-privilege agents

**Status:** Draft design, not built. Nothing here is deployed.
**Date:** 2026-11-10
**Scope:** pi-cluster (the instance) and `mtgibbs/jig` (the dispatcher it already runs).
**Asks of Matt:** the [Open questions](#7-open-questions-for-matt) at the end.

## 0. The idea, and the one-paragraph answer

Matt's idea is this. Specialized agents each subscribe to a topic. Each runs in a short-lived sandbox that holds only the
tools, MCPs and credentials its task needs, does one job, and is torn down. n8n routes work between the agents as the
state machine.

Examples:
- An `auto-ops` topic. Errors go in, a fixer opens a PR, and a reviewer reviews it.
- PR judges as subscribers of a "PR opened" topic.

**The answer is that most of the parts already exist, but as three separate one-trigger systems with no common contract
between them:**

| | Trigger | Runtime | Credentials |
|---|---|---|---|
| **review-hub** | GitHub App webhook | in-process threads | its own App key and LiteLLM key |
| **jig fleet dispatcher** | `POST /runs`, which nothing calls | K8s Job | shared per-strategy secret |
| **n8n** | per-workflow webhooks | inline LiteLLM calls | credentials hand-made in n8n's DB |

What's missing is the composable middle:
- **a shared event envelope**;
- **a declarative per-agent manifest** covering image, model, tools, secrets, budget and output;
- **a router** that maps topics to agents;
- **a common verdict/result contract**, so one agent's output is another's input;
- **network confinement**: there is no NetworkPolicy outside `flux-system` today.

The design below adds only those five things and reuses the rest. The human merge checkpoint stays where it is.

---

## 1. Inventory — what exists

Full detail lives in the two inventory reports this doc was written from. The table is the part the design depends on.

| Piece | What it does | Trigger | Credentials | Composability gap |
|---|---|---|---|---|
| **n8n** (`clusters/pi-k3s/n8n/`) | Queue mode (Bull on Valkey with AOF, Postgres, 3 workers, a separate webhook tier). Eight workflows: email intake, digest, feed, ack, menu, calendar, reminders. | Per-workflow webhooks plus two schedules | One ESO secret (`n8n` item) for platform keys. Workflow creds (LiteLLM key, DB) were **hand-created in n8n's encrypted DB**. | Workflow JSON in `workflows/` is a copy, **not applied by Flux**; import is manual. Model names are hard-coded per workflow. The aimode gate is copy-pasted. Every webhook has its own payload shape. **Nothing dispatches an agent or touches GitHub.** |
| **jig fleet dispatcher** (`clusters/pi-k3s/harness-fleet/`, code in `mtgibbs/jig`) | Validate → map → launch → record. `POST /runs {repo, spec, strategy, idempotency_key}` renders a Job: `activeDeadlineSeconds 1800`, `backoffLimit 0`, `ttlSecondsAfterFinished 3600`, nodeSelector `harness-fleet=true` (pi5-worker-2). JSONL ledger dedupes on the idempotency key. | Bearer-authed HTTP, ClusterIP only. **Nothing calls it**; the transport was "undecided". | The dispatch token is separate from worker secrets. Each worker secret (`harness-worker-<strategy>`) carries a clone PAT (read), an outcome PAT (Contents/PR/Workflows RW, **unconsumed**), a LiteLLM key, and the report token. | One verb (`fix`), so a run can only be "build this spec". No event payload or context, so it can't be handed an alert or a diff. Strategy→image/secret mapping is an env-var naming convention. **jig#132: the worker image has no model binding, so no dispatched run has ever called a model.** No PR egress. ResourceQuota `count/jobs: 2` rejects extra Jobs instead of queueing them. No NetworkPolicy. Pods use the `default` SA. |
| **harness-coordinator** (`clusters/pi-k3s/harness/`) | Run board and report sink (`jig.lab`). Workers push status, attempts and artifacts outbound. State is `state.json`, capped at 200 runs. | Worker push | `harness-coordinator/token` | It is a status board, not a ledger: capped, no chain/correlation concept, `/evidence` returns 501. |
| **jig loop** (`mtgibbs/jig`) | Spec-gated ralph build loop: per-task `verify.sh` is the only voice that says done. Mutant-tested gates. Codex judge loop. `loop-doctor` fault classifier. | `run-loop.sh` / `run-task.sh` | Env contract only: "the harness ships no credentials" | **There is no per-agent manifest.** The spec's `Tools:`/`MCP:`/`Permissions:` header fields are only presence-checked, and `Permissions` is **recorded, not enforced**. Strategy `.conf` is sourced shell. No model, budget or token fields; `metrics.jsonl` `spend.*` is null everywhere. The judge strategies need `oc` and an interactive Codex session, so **they can't run in the fleet**. |
| **review-hub** (`clusters/pi-k3s/review-hub/`, `scripts/reviewhub/`) | GitHub App (`review-bot`, id 3998878) `pull_request` webhook → HMAC check → 202 → background thread → mint 1h installation token → read `.review-hub.yml` opt-in → `validators_for()` → ThreadPool(4) → one Check Run per validator, a rollup `review-hub` Check Run (fail-safe), and an upserted report comment. 11 validators, eval-first (P/R 1.00 at reps=5). | GitHub App webhook through the Cloudflare tunnel (`^/webhook$` only) | ESO `review-hub` item: App key, webhook secret, LiteLLM key. Short-lived installation tokens: **the right pattern**. | In-flight reviews are lost if the pod restarts. The registry is Python, so a new validator means an image rebuild. One model and repeat count for everyone (`hot-coder` ×5). Validators are text-only and never check out code. Only `pull_request` is handled. Verdicts exist only as Check Runs, so nothing else can subscribe to them. |
| **CI gates** (`.github/workflows/`) | `generated-docs-drift` (the drift gate, every PR), `triggerable-lint`, `build-review-hub`, `tailscale-acl` | GitHub Actions | None, or Actions secrets | These are deterministic checks, not agents, and that's correct. Gap: **pi-cluster has no required checks** (2026-11-09 audit), so nothing yet makes a gate a gate. |
| **agent-bus** (`docs/agent-bus.md`, `clusters/pi-k3s/matrix/`) | Matrix `#agents`/`#tasks`, one user per agent, thread root = correlation id | Manual chat | `agent-bus-*` items | The Phase 2 listener (`@qwen run …`, human `go`) is unbuilt. Today it's a human-readable channel, not a machine bus. |
| **Other in-cluster LLM callers** | `model-watch` CronJob, `new-horizons`, `local-llm-mcp`, the Mealie bootstrap Job | various | One LiteLLM virtual key each: **the right pattern** | n/a. Proves per-workload keys work. **No in-cluster workload calls Claude today.** |
| **LiteLLM** (Beelink, `ai.lab.mtgibbs.dev` → 192.168.1.70) | Aliases incl. `hot-coder`, which `aimode` repoints between family and work models. Virtual keys support model allowlists and TPM/RPM limits. | — | Master key on the Beelink | **No key has `max_budget` set.** That's fine for unpriced local models; it is not fine once Claude is routed through it. |

### Prior decisions this design must obey

- **PR-gated agents.** Permissive inside the sandbox, gated at the repo boundary. The bot never merges; a human does.
  (`feedback_agent_safety_pr_gated`, `project_triggerable_judge`, global CLAUDE.md "PR to publish — always".)
- **Reactive, not scheduled.** Use webhooks and watches, not polling CronJobs. An outbound long-poll counts as reactive.
- **Credentials scale by role, not by repo.** One identity per bot role, short-lived tokens minted per use, and a new repo
  costs zero new credentials.
- **Container config comes from outside.** Agents never mutate their own runtime or config.
- **Fleet simplicity.** The dispatcher stays describable in a paragraph. No LLM router: dispatch is a fixed table. No
  green gate → no PR.
- **Judges are fail-closed.** An errored vote blocks; it is not counted as a pass. Majority-of-N against stochastic
  judges. Lint owns the provable checks, the LLM owns the reasoning ones. *Green is not proof*: every gate gets a positive
  control.
- **Security audit 2026-11-09, finding #5.** The `mcp-homelab` SA (patch deployments + create jobs, cluster-wide) is
  reachable from containers that have unfiltered LAN egress, so prompt injection → cluster. **This design must not create
  a second path like that.**

---

## 2. Architecture

```
  sources                    switchboard                    compute                     gates (human last)
 ─────────                   ───────────                    ───────                     ──────────────────
 Alertmanager ─┐                                         ┌─ Job: ops-fixer ──┐
 GitHub App ───┼─▶ n8n  ingress adapters ─▶ envelope ─▶  │  (sandboxed,      │──▶ branch + DRAFT PR
 (review-hub   │   dedupe · route · chain state          │   scoped creds)   │         │
  receiver)    │        │            ▲                    └───────────────────┘         ▼
 Flux notif. ──┤        │            │ result/verdict      ┌─ Job: pr-reviewer ┐   Check Runs:
 Matrix #tasks ┘        ▼            │ events             │                   │──▶ review-hub rollup,
                  jig dispatcher ────┘                    └───────────────────┘   drift gate, agent judges
                  (only identity that                     review-hub (in-proc        │
                   can create Jobs)                        text judges, unchanged)    ▼
                                                                              HUMAN approves + merges
                                                                                       │
                                                                                     Flux
```

There are four layers with one rule: **each layer has exactly one job, and none of them can do the next layer's job.**

| Layer | Owns | Must NOT be able to |
|---|---|---|
| **n8n (switchboard)** | Normalize, dedupe, route, chain state, waits/timeouts, notify the human | Create compute, hold agent credentials, merge |
| **dispatcher** (jig, extended) | Resolve the agent manifest, mint per-run tokens, render and launch the Job, watch it, report the result | Decide *what* to run (it maps; it doesn't choose), merge |
| **agent Job** | One task, then exit, emitting one result | Launch compute, reach the LAN, hold a credential outside its manifest, push to `main`, merge |
| **gates + human** | Verdicts (Check Runs), approval, merge | n/a: this is the checkpoint |

### 2.1 Topic and event schema

A CloudEvents-shaped envelope, deliberately small. Every source adapter in n8n produces one, and every agent result is
one. **It carries refs, not content.** For example, "PR 258 at sha abc" rather than the diff, and an alert fingerprint plus
labels rather than a log dump. The agent fetches what it needs with its own scoped token. This keeps n8n out of the
sensitive-data path, the same principle as the inbound-mail Worker's refs-only JSON.

```jsonc
{
  "specversion": "agentq/1",
  "id": "01JD…",                    // ULID, unique per event
  "topic": "ops.alert",             // see the topic table
  "source": "alertmanager",         // adapter that produced it
  "subject": "pi-cluster:FluxKustomizationNotReady:media",  // what it is about
  "dedupe_key": "sha256(topic|subject|fingerprint)",          // see below
  "correlation_id": "01JD…",        // the chain (incident / PR) this belongs to; = id for chain roots
  "causation_id": "01JC…",          // the event that directly caused this one
  "hop": 0,                         // incremented on every agent-emitted event
  "actor": {"kind": "system|agent|human", "name": "alertmanager"},
  "trust": "internal|external",     // external = may contain attacker-controlled text (PR bodies, issue text, email)
  "time": "2026-11-10T14:03:00Z",
  "data": { /* topic-specific, schema-validated, refs only, ≤ 16 KiB */ }
}
```

**Topics.** Start with these. They're names, not infrastructure: in n8n a topic is a routing key.

| Topic | Producer | `data` (refs) | Typical subscribers |
|---|---|---|---|
| `ops.alert` | Alertmanager webhook (allowlisted alertnames only) | alertname, labels, fingerprint, status, generatorURL | `ops-fixer` |
| `ops.workitem` | Human (Matrix `#tasks`, n8n form), loop-doctor | repo, free-text ask (trust=external), requested_by | `ops-fixer` |
| `flux.failed` | Flux notification-controller → n8n | kind, name, namespace, revision, message | `ops-fixer` |
| `pr.opened` / `pr.updated` | GitHub App webhook via review-hub receiver | repo, number, head_sha, author, labels, changed_paths | review-hub (in-proc), `pr-reviewer`, … |
| `pr.verdict` | each judge | repo, number, head_sha, judge, conclusion, findings_ref | n8n chain state (merge-readiness summary) |
| `agent.result` | dispatcher (on Job completion) | run_id, agent, outcome (`shipped`/`noop`/`deferred`/`failed`), refs (pr url, report) | n8n chain state |
| `human.decision` | ntfy action / Matrix `go` / PR approval | correlation_id, decision | n8n (resumes a Wait) |
| `deadletter` | n8n / dispatcher | original envelope + reason | Matt (ntfy + Matrix) |

**Idempotency and dedupe:**
- `dedupe_key` is computed by the **adapter**, which knows the domain:
  - alerts → the Alertmanager fingerprint;
  - PRs → `repo#number@head_sha`;
  - Flux → `kind/ns/name@revision`.
- n8n inserts into an `agentq_events` table with a `UNIQUE(dedupe_key)` constraint, and a conflict is a no-op. Firing
  alerts re-send every `repeat_interval`, so this matters on day one.
- **Chain-level dedupe is separate from event dedupe.** An incident that keeps firing must not spawn a second fixer while
  the first one's PR is still open. n8n looks up the open chain for `subject` and attaches the new event to it rather
  than opening a new one. See §2.5.
- The dispatcher already dedupes on `idempotency_key`; n8n passes `event.id + agent`. So a retried n8n execution can't
  launch the same agent twice for the same event.

### 2.2 n8n as the state machine — and where it stops

**n8n owns:**
1. **Ingress adapters.** One webhook per source (Alertmanager, review-hub forward, Flux, Matrix). Each one validates the
   source, maps to the envelope, and computes `dedupe_key`. Nothing else differs between sources.
2. **One router workflow** (`agentq-router`). Dedupe insert → look up subscribers for `topic` → evaluate each
   subscription's filter → apply limits (§2.5) → `POST` to the dispatcher. The subscription table is **not hand-built in
   the n8n UI**. It's the `subscribes:` block of the agent manifests in Git (§2.3), rendered into a ConfigMap that the
   router reads. Adding an agent is a PR, never a UI click (`feedback_everything_as_code`).
3. **Chain state.** `agentq_chains(correlation_id, subject, state, hop, attempts, open_pr, opened_at, closed_at)` lives in
   the existing n8n Postgres. States: `open → fixing → in_review → awaiting_human → closed(merged|rejected|expired)`.
4. **Waits and timeouts.** For example, "PR open with no human decision in 72h → close as expired, notify". n8n's
   Wait-with-webhook-resume does this natively, and it's the main reason n8n is a good fit here.
5. **Human notifications.** ntfy and Matrix, with links: "ops-fixer opened draft PR #N for `FluxKustomizationNotReady:media`".

**n8n does NOT own:**
- **Compute.** It can't create Jobs; only the dispatcher's SA can.
- **Agent credentials.** n8n holds exactly one new secret, the dispatch API token.
- **Verdicts.** These are GitHub Check Runs, the system of record. `pr.verdict` events are a *copy* for chain state.
- **Merge.** Nobody but the human owns merge.

**Where n8n stops being the right tool.** Name these now so it's obvious when to swap it out:
- **Logic that needs review.** If routing grows beyond "topic + simple filter + limits" (scoring, multi-agent auctions,
  an LLM picking the agent), that logic belongs in reviewable code, not workflow JSON. The fleet decision "no LLM router"
  already forbids the worst of it.
- **Delivery guarantees.** Bull on Valkey with AOF is decent, but an n8n execution that dies mid-route is retried at the
  workflow level, not the message level. Because both the event insert and the dispatcher are idempotent, at-least-once
  is enough. If we ever need replay of a topic from offset X, or more than one consumer group, that's **NATS JetStream**,
  which is a single small binary and fits on a Pi. The envelope is transport-agnostic on purpose, so the swap replaces
  the router, not the agents.
- **Volume.** Tens of events per day is n8n's sweet spot. Hundreds per minute isn't, but nothing here will produce that.
- **GitOps drift.** n8n workflow JSON isn't applied by Flux today. The router is the one workflow where that's
  unacceptable, so this design adds a `n8n import:workflow` sync Job (Flux-applied, keyed on the JSON's hash) for the
  `agentq-*` workflows. This is a follow-up and can also fix the other eight.

**Rejected alternatives** (briefly):
- **Argo Events + Argo Workflows.** It's the K8s-native version of exactly this, but it's 4+ controllers on Pis, a second
  workflow language, and n8n already runs in queue mode.
- **Kueue** for Job queueing. It fixes the "quota rejects instead of queueing" gap, but the dispatcher returning 429 and
  n8n retrying with backoff does the same at this scale.
- **A bespoke Go router.** That's just n8n's router workflow written again, with none of the UI.

### 2.3 Agent definitions — a declarative manifest per agent

One YAML per agent, in Git, at `agents/<name>.yaml`. This repo is the instance, so the manifests live here. The schema
and the dispatcher code that reads it are framework and go to jig, following the ADR-008 litmus. The manifest is
**the single answer to "what can this agent touch?"**. Everything else is rendered from it: the Job, the NetworkPolicy
selection, the ExternalSecret, the LiteLLM key's model allowlist, and the router subscription.

```yaml
apiVersion: agentq.mtgibbs.dev/v1      # schema only; a ConfigMap, not a CRD (no controller to run)
kind: Agent
metadata:
  name: ops-fixer
  version: 1                           # bump = new LiteLLM key alias + new ledger series
spec:
  purpose: "Diagnose an allowlisted ops alert in pi-cluster and propose a fix as a DRAFT PR."
  subscribes:
    - topic: ops.alert
      filter: 'data.alertname in ["FluxKustomizationNotReady","ExternalSecretSyncError","KubePodCrashLooping"] && data.status == "firing"'
    - topic: flux.failed
  runtime:
    image: ghcr.io/mtgibbs/agent-runtime-claude:0.1.0   # Claude Code CLI on harness-base; or loop-executor-opencode
    entry: [agent-run, --task, ops-fix]                   # prompt template baked in the image, versioned with it
  model:
    via: litellm                       # ALL model traffic goes through LiteLLM (see 2.4)
    alias: agent-claude-sonnet         # LiteLLM alias → Anthropic; or hot-coder (Beelink)
    fallback: hot-coder                # used when the budget is exhausted or Anthropic is unreachable; omit = fail
  tools:
    builtin: [read, edit, bash:git, bash:kubeconform, bash:rg]    # enforced via the runtime's allowlist flags
    mcp:
      - server: homelab-readonly       # NOT homelab-admin; see 2.4
        tools: [get_flux_status, get_pod_logs, get_events, diagnose_dns, list_pods]
  repos:
    - name: mtgibbs/pi-cluster
      access: branch-pr                # read | branch-pr. There is no "merge" value.
      paths_allow: ["clusters/pi-k3s/**", "docs/**"]
      paths_deny:  ["clusters/pi-k3s/flux-system/**", "**/external-secret*.yaml", ".github/**", "agents/**"]
  secrets: []                          # standing secrets (ESO). Empty: everything is per-run (2.4)
  egress: profile/agent-default        # names a NetworkPolicy set (2.4)
  budget:
    timeout: 20m                       # → activeDeadlineSeconds
    max_usd_per_run: 2.00              # → per-run LiteLLM key max_budget
    max_runs_per_day: 6
    max_attempts_per_chain: 1          # retries = new chain step, not a hidden loop
  output:
    emits: [agent.result]              # the agent may emit only these topics
    contract: result/v1                # outcome ∈ shipped|noop|deferred|failed, refs, summary ≤ 2 KiB
    pr:
      draft: true
      labels: [agent:ops-fixer, needs-human]
      body_must_include: [correlation_id, alert_ref, "what I changed", "how I verified"]
```

Why each field earns its place:
- `subscribes` is the router table.
- `runtime` and `model` are the Job and its key.
- `tools`, `repos`, `egress` and `secrets` are the sandbox.
- `budget` is the blast radius.
- `output` is what makes chaining work. A downstream subscriber depends on `result/v1`, never on an agent's prose.

**Judges are agents with `access: read` and `emits: [pr.verdict]`.** There is no separate concept (§2.5).

**Spec enforcement.** The dispatcher refuses a manifest that doesn't validate, and the refusal is a 422, not a degraded
run. That is the same "credentials with nowhere to run are refused at dispatch" stance the fleet already takes. A pi-cluster
CI check (`agents-lint`, deterministic) validates every manifest on PR:
- `paths_deny` must include `agents/**` and `.github/**` for any `branch-pr` agent;
- no `homelab-admin`;
- every `emits` topic must exist.

### 2.4 Sandboxing

There is one Job per task in a new namespace, `agentq`. It is separate from `harness-fleet` so that the PSA, quota and
NetworkPolicy can be strict without disturbing the build-loop fleet. Both namespaces share the dispatcher.

**Pod**

The rendered Job sets all of this explicitly. Unlike the fleet's minimal Job, it does not rely on namespace defaults,
because a sandbox you have to infer isn't one.
- `automountServiceAccountToken: false`, with a dedicated SA `agentq-run` that has **no RBAC bindings**. An agent has
  zero K8s API access; cluster reads go through the read-only MCP.
- `runAsNonRoot`, uid 10001, `readOnlyRootFilesystem`, `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`,
  `seccompProfile: RuntimeDefault`.
- Namespace label `pod-security.kubernetes.io/enforce: restricted`. This would be the first app namespace with PSA, per
  the audit.
- Workspace is an `emptyDir` with a `sizeLimit` (1–2 GiB) mounted at `/work`, plus `HOME` and `TMPDIR` under it. This
  avoids the noexec-`/tmp` trap.
- `activeDeadlineSeconds` from `budget.timeout`, `backoffLimit: 0` (retries are explicit chain steps, never hidden),
  `ttlSecondsAfterFinished: 3600`.
- Resources are explicit. The opencode RSS peak was measured at ~300 MB; Claude Code is heavier, so start at
  `512Mi/1Gi`.
- `nodeSelector agentq=true`. The node is an [open question](#7-open-questions-for-matt): pi5-worker-2 already carries
  n8n, the exit node and the MCPs.

**Network**

This is the gap the 2026-11-09 audit flagged, and it is **a prerequisite, not a follow-up.** k3s enforces NetworkPolicy
with its embedded kube-router.
- `default-deny` for both ingress and egress in `agentq`.
- `profile/agent-default` allows:
  - kube-dns on 53;
  - the LiteLLM host `192.168.1.70/32:443` (`ai.lab`);
  - the read-only MCP service, by namespaceSelector and port;
  - `0.0.0.0/0:443` **except** `10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16`. That gives GitHub and the package registries,
    and **no LAN**: no UDM, Pi-hole admin, QNAP or Postgres. This directly closes the lateral-movement half of audit
    finding #5 for this path.
- Optional upgrade: a domain allowlist through an in-cluster squid, reusing the `specs/harness-egress-allowlist` format,
  to narrow `443` down to `github.com`, `api.github.com`, `ghcr.io` and the registries. It isn't required for slice 1:
  the threat that matters is the LAN, and the CIDR rule already handles it.

**Credentials: nothing standing, everything minted per run and scoped to the manifest**

| Credential | How it's minted | Scope | Lifetime |
|---|---|---|---|
| GitHub token | The dispatcher mints a **GitHub App installation token** with the `repositories` and `permissions` request fields narrowed to the manifest: one repo, `contents:read` (or `+write`), `pull_requests:write`, `checks:write` for judges. | One repo, the manifest's access level only | 1h. GitHub's max; a 20m Job uses it once. |
| LiteLLM key | The dispatcher calls `/key/generate` with `models=[alias, fallback]`, `max_budget=max_usd_per_run`, `duration=timeout+5m`, and metadata `{agent, run_id, correlation_id}`. | The manifest's models, a hard spend cap | The Job's lifetime. It expires on its own, and the dispatcher also deletes it on completion. |
| MCP | A `homelab-readonly` endpoint with its own key. **Not** the `mcp-homelab` SA that holds patch/create (audit #5). | Read tools only, which the server enforces, not just the client | Static per-role key. It's acceptable because the tools behind it are read-only; rotate it with the audit fix. |

How the minted tokens reach the Job:
- They are written to a per-run Secret whose `ownerReferences` point at the Job, so GC deletes the Secret when the Job's
  TTL expires.
- The Secret is mounted as a file. The entrypoint reads it into the tool config and unsets it, the same pattern jig's
  `entrypoint.sh` already uses for `HARNESS_CLONE_PAT`.

**Identities.** There are two new GitHub Apps, one per role (credentials scale by role):
- **`agentq-writer`** is installed on the repos where agents may open PRs. It is used by fixers.
- **`review-bot`** (the existing App) also serves agent judges, so verdicts appear under the same identity.

Neither App has bypass rights on any ruleset, and neither is `mtgibbs`. This fixes the "bot and human are
indistinguishable" problem noted for the harness containers.

**Who holds the minting keys.** The dispatcher holds the App private key and a LiteLLM *key-management* credential, and
that makes the dispatcher the crown jewel. Its containment:
- ClusterIP only;
- NetworkPolicy ingress only from n8n;
- bearer auth;
- RBAC: Jobs and Secrets, in `agentq` and `harness-fleet` only;
- an allowlist of agents.

LiteLLM's master key should **not** go there. Mint a LiteLLM admin/team key that can only create keys under an `agentq`
team with a team-level `max_budget`. If LiteLLM's non-Enterprise RBAC can't express that, fall back to per-agent static
keys with `max_budget` + `budget_duration: 1d` delivered by ESO, and accept daily rather than per-run caps.
([Open question](#7-open-questions-for-matt).)

**Routing Claude through LiteLLM.** Matt now has Claude API credits to spend, so Claude becomes a first-class model
choice per agent, not a fallback. Recommendation: **the Anthropic API key lives only in LiteLLM** (one ESO-delivered
key, under an `anthropic/*` model alias), and agents only ever see a scoped, budgeted LiteLLM virtual key.
- Gains:
  - One revocation point.
  - Per-agent and per-run spend caps that the Anthropic console can't express per run.
  - Spend lands in the existing `litellm_key_spend_usd` exporter, which LiteLLM can price because Anthropic models
    carry list prices.
  - The agent manifest can switch between `hot-coder` and Claude by changing one line.
- Cost: Claude calls now depend on the Beelink being up. The `fallback` field handles "Claude down → hot-coder"; nothing
  handles "Beelink down". That's acceptable, since a Beelink outage is already an incident that the Beelink alerts cover.
- Claude Code can talk to LiteLLM's Anthropic-compatible `/v1/messages` passthrough with `ANTHROPIC_BASE_URL` set to
  `ai.lab`, so the Claude runtime image needs no special client.

### 2.5 Composition — chaining, the human checkpoint, loop and blast-radius limits

**Chaining is only topic → agent → result → topic.** An agent never calls another agent. It emits one `agent.result`
(and judges emit `pr.verdict`), and n8n decides what that causes. That keeps every edge in the graph visible in one
router and recorded in one ledger.

**Are the judges the same kind of thing? Yes at the contract, no at the runtime.**
- *Same contract.* A judge subscribes to `pr.opened`/`pr.updated`, holds `access: read`, emits `pr.verdict`, and writes
  a GitHub Check Run named after itself. The drift gate, review-hub's validators and a new agentic reviewer all have the
  same *output shape*: a Check Run with a conclusion, plus findings.
- *Three runtimes, chosen by what the judge needs:*
  1. **Deterministic gates** (drift gate, `triggerable-lint`, `agents-lint`) **stay in GitHub Actions.** They need no
     model or secrets, and Actions is already the right sandbox. They are not agents; making them topic subscribers would
     add a hop that only adds failure modes.
  2. **Text judges** (review-hub's 11 validators) **stay in review-hub's in-process pool.** Each verdict is one stateless
     LLM call ×5. A Job per vote would mean ~55 pod starts per PR on Pis for no isolation gain, since they hold no write
     credential and run no code. The changes: review-hub's receiver becomes the **`pr.*` adapter** (it already has the
     HMAC-verified webhook, so this needs no second public endpoint), it forwards an envelope to n8n, and it emits
     `pr.verdict` from its rollup.
  3. **Agentic judges** (they need a checkout, run tests, or use tools: `pr-reviewer`, a Codex-style adversarial judge)
     **are agentq Jobs**, subscribed through manifests like any other agent. This is the new capability.
- So "a PR was opened" *is* just another topic. The difference is that subscribers 1 and 2 are wired directly to GitHub
  and don't need n8n to reach them. n8n sees their verdicts but doesn't schedule them.

**The human checkpoint is structural, not procedural.** Every one of these must hold, and each is enforced by something
other than the agent's good behaviour:
1. Agent tokens have no merge and no bypass. Merge isn't in the App's permission set for the protected branch. Branch
   protection or a ruleset requires **1 human approval from a CODEOWNER**, and the App isn't one.
2. Required checks on `main` are the `review-hub` rollup + `generated-docs-drift` + `agents-lint`. **pi-cluster has no
   required checks today, so this is a prerequisite.** The Flux ImageUpdateAutomation deploy key keeps its ruleset bypass;
   the agent Apps never get one.
3. Fixer PRs open as **drafts**, labelled `needs-human`. A judge can comment and fail a check, but it cannot approve: an
   approving review from `review-bot` counts for nothing under the CODEOWNER rule.
4. `paths_deny` includes `agents/**` and `.github/**`, so an agent can't widen its own sandbox or edit the gates that judge
   it. This is enforced twice: `agents-lint` fails any agent-authored PR that touches a denied path, and CODEOWNERS on
   those paths requires Matt specifically.

**Loop and blast-radius limits.** Each is enforced in the router or the dispatcher, never by the agent:

| Limit | Value (start) | Enforced by |
|---|---|---|
| `hop` max per chain | 4 (alert → fixer → judges → summary) | router drops and dead-letters at `hop > 4` |
| One open fixer chain per `subject` | 1 | router: a repeat alert attaches to the open chain; no new run |
| Attempts per chain | `max_attempts_per_chain` (1 for fixers) | router; a second attempt needs a `human.decision: retry` |
| Agent-authored events can't trigger a fixer | always | router: `actor.kind == agent` events route only to judges/notify. A fixer's PR failing CI does **not** summon the fixer again. |
| Runs per agent per day | `max_runs_per_day` | router counter in `agentq_chains` |
| Concurrent Jobs | 2 (ResourceQuota) | quota; dispatcher returns 429; router retries with backoff, then dead-letters |
| Spend | per-run key `max_budget`; team daily cap | LiteLLM |
| Repos/paths | manifest `repos` | minted token scope (repo) + `agents-lint` and CODEOWNERS (paths) |
| Global kill switch | `AGENTQ_PAUSED=true` | the dispatcher refuses all launches; the router parks events as `paused`. Flipped by PR or `kubectl set env` |

**Prompt-injection posture.** `trust: external` data (PR bodies, issue text, free-text work items, alert annotations that
quote logs) is passed to the agent as clearly fenced data, never as instructions. This is a mitigation, not a defense.
**The real defense is that a fully hijacked agent can still only:**
- open a draft PR, on one repo, outside denied paths;
- spend at most `max_usd_per_run`;
- reach no LAN host.

The design assumes injection succeeds and bounds what follows.

### 2.6 Observability

- **Logs → Loki.** Agents log JSON to stdout with `run_id`, `agent`, `correlation_id`, `hop`. The existing log pipeline
  picks up pod logs. Job pod labels carry the same keys, so `{namespace="agentq", correlation_id="…"}` reconstructs a
  whole chain across the fixer and agentic judges. Model transcripts **do not** go to Loki: they can contain fetched
  secrets-adjacent content, so they go to the run artifact, below.
- **Run ledger: one table, one writer per column.** `agentq_runs` in the n8n Postgres:
  - `run_id, agent, agent_version, correlation_id, event_id, started, finished, outcome, exit_reason, model_alias, tokens_in, tokens_out, usd, pr_url, artifact_ref`.
  - The dispatcher writes launch and finish. LiteLLM spend is joined by key alias.
  - The dispatcher's JSONL ledger stays as its own dedupe store. The coordinator stays the build-loop board.
  - `outcome` is the jig `run_summary` taxonomy (`shipped`/`deferred`/`noop`/`failed`; unknown → `failed`), so the
    loop-doctor's fault classes apply directly, and `null ≠ 0` for spend.
- **Artifacts.** The transcript, final diff and result JSON go into a bounded, per-run tarball. Where to put them is an
  open detail: the coordinator's artifact push capped at 1 MiB, or R2 or MinIO, with a TTL of 30 days. The PR body links
  it.
- **Metrics and alerts.** Prometheus already scrapes LiteLLM spend. Add:
  - `agentq_runs_total{agent,outcome}`, exported from the ledger;
  - alerts for `failed` rate, daily spend > 80% of cap, a dead-letter that is non-empty, and the kill-switch state;
  - a positive control for each alert, per *green is not proof*: a weekly synthetic `ops.workitem` "noop canary" that
    must produce `outcome=noop` within 10m.
- **Grafana:** one "agentq" dashboard covering runs by outcome, spend by agent, chain durations and open chains awaiting
  human.

### 2.7 Failure handling

| Failure | Behaviour |
|---|---|
| Duplicate or redelivered event | `UNIQUE(dedupe_key)`, a no-op. The dispatcher idempotency key is the second line. |
| Dispatcher down, or 429 | The router retries ×3 with backoff, then sends to `deadletter`, which goes to ntfy and Matrix. The event stays in `agentq_events` for replay. |
| Manifest invalid / agent not allowlisted | 422 from the dispatcher → `deadletter`. Never a degraded run. |
| Job exceeds `timeout` | `activeDeadlineSeconds` kills it. The dispatcher's Job **watch** (reactive, not polling) emits `agent.result{outcome: failed, exit_reason: deadline}`. The per-run key and Secret are revoked on any terminal state. |
| Agent exits 0 but emits no valid `result/v1` | `failed` (fail-loud, unknown → failed) |
| Model unreachable / budget exhausted | If `fallback` is set, the runtime retries on the fallback alias; otherwise `failed`. Not silent. |
| Beelink in family `aimode` (`hot-coder` repointed to the small model) | Agents whose manifest pins a work-mode-only alias are **parked**, not run on the wrong model. This reuses the `pending_inbound_mail` park-and-drain pattern, with the `ai-family-ready` / `ai-work-ready` webhook as the drain trigger. |
| Judge errors | Fail-closed, as review-hub does today: an errored vote is a block, with a reason in the report. |
| Agent opened a PR, then the chain times out waiting for a human | After 72h, n8n comments, closes the PR (agent PRs only, by label), and records `closed(expired)`. Nothing merges by default. |
| Fixer is wrong | The judges catch it, or the human rejects. Rejection is a `human.decision`, recorded on the chain. Repeated rejections of an agent are a ledger query that tells us its eval needs work. |

---

## 3. The examples on the new design

### 3.1 Auto-ops, end to end

```
1  Alertmanager fires FluxKustomizationNotReady{name="media"}       (critical, still also goes to Discord)
2  → n8n /webhook/agentq/alertmanager   (in-cluster URL, no tunnel; a new receiver appended AFTER receivers[2])
   adapter: alertname ∈ allowlist? → envelope{topic: ops.alert, dedupe_key: fingerprint, trust: internal}
3  router: insert agentq_events (dup → stop) · open chain for subject? (yes → attach, stop) · new chain, hop 0
   subscribers(ops.alert) = [ops-fixer]; filter passes; daily cap ok; not paused
4  → POST dispatcher /runs {agent: ops-fixer, event, idempotency_key: event.id+agent}
5  dispatcher: load manifest → mint App token (pi-cluster, contents:write, pull_requests:write)
               → mint LiteLLM key (agent-claude-sonnet + hot-coder, $2, 25m) → per-run Secret
               → render Job (agentq ns, no SA token, restricted PSA, egress profile) → ledger: launched
6  Job: clone → MCP read-only: get_flux_status, get_events, get_pod_logs → diagnose
        → edit within paths_allow → run local deterministic checks (kubeconform, check-generated-docs.sh)
        → no green local check → outcome=deferred with diagnosis only (no green gate → no PR)
        → green → push branch agentq/ops-fixer/<run_id>, open DRAFT PR (labels: agent:ops-fixer, needs-human)
        → emit result/v1 {outcome: shipped, pr_url}
7  dispatcher watch: Job complete → revoke key, delete Secret → agent.result → n8n → chain: in_review, hop 1
   n8n notifies Matt (ntfy + Matrix thread keyed by correlation_id): diagnosis + PR link
8  GitHub: pull_request opened → review-hub (rollup + opted-in validators) and Actions (drift gate, agents-lint)
   review-hub forwards pr.opened envelope → router → pr-reviewer agent Job (agentic judge, read-only, Check Run)
   all verdicts → pr.verdict → chain shows "3/3 checks green, awaiting human"
9  Matt reviews, marks ready, approves, merges.  ← the checkpoint; nothing above could do this
10 Flux reconciles. The alert resolves → Alertmanager "resolved" → adapter → chain closed(merged).
   If it does NOT resolve within N min of the merge, the router attaches the next firing to the same chain as
   `fix_ineffective` and notifies. It does not auto-retry (max_attempts_per_chain: 1).
```

### 3.2 The judges, end to end

```
PR opened/updated on any opted-in repo (by a human, renovate, or an agent)
 ├─ GitHub Actions: generated-docs-drift, triggerable-lint, agents-lint   → Check Runs   (unchanged; deterministic)
 ├─ review-hub receiver (HMAC) → its validators in-proc (×5 votes)        → Check Runs + rollup (unchanged)
 │      └─ new: forward envelope{topic: pr.opened, dedupe_key: repo#n@sha} → n8n
 └─ n8n router: subscribers(pr.opened) filtered by repo/paths/labels/author
        └─ e.g. pr-reviewer (agentic): dispatcher mints a review-bot token narrowed to {contents:read, checks:write,
           pull_requests:write(comment)} on that one repo → Job checks out head_sha, runs tests/tools, posts
           Check Run "agentq/pr-reviewer" + one review comment → emits pr.verdict
 required check: review-hub rollup (extended to include agentq judges' Check Runs by name), drift gate, agents-lint
 merge: human only
```

Adding a new judge becomes:
- an `agents/<judge>.yaml` PR that subscribes to `pr.opened` with a filter;
- its eval set under `specs/validators/<name>/`. The eval-first discipline carries over: a judge doesn't ship without
  P/R measured.

It does **not** need a review-hub image rebuild or a branch-protection edit, because the rollup covers it.

---

## 4. Minimal first slice — one topic, one agent, one judge

The goal is the smallest thing that proves the *composition* (envelope → router → sandboxed Job → PR → judge → human),
built mostly from parts that already run.

**Topic:** `ops.alert`, fed by Alertmanager, with an allowlist of **one** alertname. A good first pick is one whose fix is
always a manifest edit and is easy to induce on purpose, e.g. `FluxKustomizationNotReady` on a throwaway test
Kustomization.

**Agent:** `ops-fixer`, Claude via LiteLLM (credits available), with `hot-coder` as fallback, read-only homelab MCP, and
draft PRs against pi-cluster only.

**Judge:** the existing **review-hub** plus the existing **drift gate**, with no new judge code. The only judge change is
that the rollup becomes a **required check** on pi-cluster `main`. The agentic `pr-reviewer` is slice 2.

**Phase 0, shadow (1 week).** Same everything, except that the agent's token is `contents:read` only. It writes its
proposed diff and diagnosis to the run artifact and posts them to the Matrix thread, and opens no PR. Matt reads ~5 of
these before anything can push.

### Work items, smallest set

| # | Where | What | Reuses |
|---|---|---|---|
| 1 | pi-cluster | **Required checks + CODEOWNERS on `main`**: review-hub rollup, drift gate, 1 CODEOWNER approval. Keep the Flux deploy-key bypass. | review-hub rollup (exists), drift gate (exists) |
| 2 | pi-cluster | `agentq` namespace: PSA restricted, `default-deny` + `agent-default` NetworkPolicies, `agentq-run` SA with no RBAC and no automount, ResourceQuota 2, LimitRange, node label | `harness-fleet` scaffolding as the template |
| 3 | jig | Dispatcher v0.2: accept `{agent, event}` alongside `{strategy}`; load `agents/*.yaml` from a mounted ConfigMap; render the hardened Job from the manifest; mint per-run GitHub App and LiteLLM tokens into an owner-referenced Secret; Job watch → result callback; `AGENTQ_PAUSED`. Keeps the strategy path for the build loop. | dispatcher 0.1.2, its ledger, idempotency, entrypoint unset-after-read pattern |
| 4 | jig | `agent-runtime-claude` image: `harness-base` + Claude Code CLI + `agent-run` wrapper (renders the prompt from the envelope, enforces the tools allowlist via `--allowedTools`, writes `result/v1`). This also sidesteps jig#132 for this path. | `harness-base`, `build-images.yml` smoke |
| 5 | pi-cluster | `agents/ops-fixer.yaml` + `agents-lint` CI (deterministic). Mark `agents/` and `.github/` CODEOWNER = Matt. | drift-gate workflow shape |
| 6 | n8n | `agentq-alertmanager` adapter + `agentq-router` workflows (JSON in Git); `agentq_events`/`agentq_chains`/`agentq_runs` tables; dispatch token as an n8n credential *sourced from ESO env*, not hand-typed | queue mode, Postgres, the inbound-mail park/drain pattern |
| 7 | monitoring | Alertmanager: a new receiver **appended after `receivers[2]`** (the healthchecks `targetPath` index) + a route for the one allowlisted alertname, `continue: true` so Discord still fires | existing Alertmanager config |
| 8 | Beelink / laptop | GitHub App `agentq-writer` (installed on pi-cluster only, to start); LiteLLM `anthropic` alias + Anthropic key via ESO; an `agentq` LiteLLM team with `max_budget`; a `homelab-readonly` MCP key. **Human-only steps: `op`, App creation.** | `ghcr-pull-secret`, ESO, the `review-hub` App as the pattern |
| 9 | — | Positive controls: induce the alert on a test Kustomization → expect a shadow diagnosis; send a duplicate → expect a no-op; flip `AGENTQ_PAUSED` → expect parked; give the agent a `paths_deny` bait → expect `agents-lint` red | *green is not proof*; two-direction gate validation |

**Explicitly not in slice 1:**
- the agentic `pr-reviewer`;
- the `pr.*` forward from review-hub;
- Flux and Matrix adapters;
- the squid domain allowlist;
- artifact store beyond the coordinator's 1 MiB push;
- the n8n workflow-sync Job (import the two workflows by hand once and record their hashes).

**Done for slice 1:** an induced alert produces a draft PR from `agentq-writer`, the required checks run on it, Matt
merges or rejects it, the chain closes in the ledger with spend recorded, and every positive control in item 9 has gone
red once.

---

## 5. What this deliberately does not do

- **No autonomous merge, ever**, including for "trivial" fixes. If auto-merge is ever wanted for a narrow class (e.g.
  Renovate patch bumps), that's a separate decision with its own gate. It is not a field in an agent manifest.
- **No `homelab-admin` MCP in any agent.** Mutations reach the cluster as PRs, and Flux applies them. The agent never
  touches the cluster directly.
- **No LLM in the router.** Subscriptions are filters, not judgment.
- **No agent-to-agent calls.** Every edge goes through the router and the ledger.
- **No standing GitHub PATs for new agents.** The fleet's `clone-token`/`outcome-pat` stay for the build loop. The agentq
  path uses minted App tokens, and the build loop can migrate later.

## 6. Relationship to jig and ADR-008

The manifest schema, the dispatcher's agent path, the `agent-run` wrapper and the result/verdict contracts are
**framework**: a different cluster would use them unchanged, so they belong in `mtgibbs/jig`. Everything else is
**instance** and lives in pi-cluster:
- `agents/*.yaml`;
- the NetworkPolicies;
- the n8n workflows and tables;
- the App IDs;
- the allowlisted alertnames.

This is the ADR-008 seam applied again, and it's why the router table is rendered from manifests rather than living in
n8n.

---

## 7. Open questions for Matt

1. **Claude spend path and caps.** Should the Anthropic key live only in LiteLLM, with per-run virtual keys carrying
   `max_budget` (recommended), or should each agent role get its own Anthropic workspace key? And what are the numbers:
   the per-run cap and the daily agentq team cap?
2. **Required checks on pi-cluster `main`.** Turning on the review-hub rollup + drift gate + 1 CODEOWNER approval is the
   prerequisite that makes the human checkpoint structural rather than a habit. OK to do that first, as its own PR, with
   the Flux deploy-key bypass kept?
3. **Fixer write scope.** Should the agentq fixer be **denied** `.github/**`, `flux-system/**` and ExternalSecrets?
   (Recommended. It's the opposite of the fleet's OQ1, where build workers got Workflows: write.) Should it start with a
   one-week shadow phase (no PRs), or open draft PRs from day one?
4. **Node placement.** Run agentq Jobs on pi5-worker-2 alongside n8n, the exit node and the MCPs, or dedicate and taint a
   node for agents?
5. **Where the dispatcher grows.** Extend the jig dispatcher with an agent path (recommended: one Job-creating identity
   in the cluster), or stand up a separate agentq dispatcher so the build-loop fleet stays untouched?
