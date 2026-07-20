# Homelab Resilience & Security Audit — 2026-07-20

**Source:** the `coding-harness-codex` (OpenAI Codex CLI) executor, in a read-only
static-review pass over this repository. The original 410-line handoff is preserved
verbatim at the bottom of this file; it was rescued from a tmpfs worktree inside the
container before it could be lost.

**This top section is the disposition** — added by the orchestrating session that
verified each finding against the live cluster with four independent read-only
subagents. Where the audit and the live cluster disagreed, the live cluster wins and
the correction is recorded here.

Read the disposition for what is true and what was done. Read the verbatim handoff
for the original reasoning and evidence (with the caveat that three of its factual
claims were wrong — see Corrections).

---

## Decisive facts the static review could not establish

- **K3s network-policy enforcement IS on** (kube-router v2.6.3; 6 nftables chains).
  NetworkPolicies would take effect here — the audit's implicit "maybe it's disabled"
  escape hatch does not apply.
- **No external heartbeat existed.** Prometheus's `Watchdog` was routed to `null` and
  the only alert path was in-cluster Discord, so nothing would fire if the cluster (or
  the house) went dark. Fixed — see #68.
- **The tailnet is effectively single-user today** (Matt across several devices), with
  **whole-family access as the stated goal**. That makes the Tailscale finding low-risk
  now but a real hole once non-admin members exist — so it was fixed proactively (#69).

## Corrections — audit claims that were factually wrong

1. **"Prometheus is on the control-plane microSD."** It is on `pi5-worker-2`
   (node-affine PV); Alertmanager is on `pi5-worker-1`. A stale manifest comment misled
   the review. Better isolation than claimed.
2. **"Backup jobs can report success after omitting data."** True as written in the
   code, but **nothing is actually being skipped today** — the 2026-07-19 run copied all
   19 targets. Latent hazard, not an active one.
3. **"Loki self-monitoring and canary disabled."** The `loki-canary` DaemonSet is
   **running** 3/3 (chart 6.x moved the key, so `enabled: false` is a no-op). The
   finding's *conclusion* survives by a different route — the canary has no
   ServiceMonitor, so its signal is scraped by nothing.

## Disposition of every finding

| # | Finding | Verdict | Outcome |
|---|---------|---------|---------|
| P0 | Retention deletion not scoped to dated dirs (`git-mirrors/` deleted weekly) | **Confirmed — understated; it was actively firing** | **Fixed, #64** |
| — | (found during verification) Retention window counted nights not weeks → only 1 cluster restore point ever | **Confirmed live** | **Fixed, #64** |
| P0 | Backup coverage drift — Mealie/Matrix/ntfy PVCs + Mealie/Matrix Postgres unprotected (14 uncovered local-path PVCs total) | **Confirmed** | **Open** — not yet shipped |
| P0 | Jobs soft-skip missing targets and still report success | Confirmed in code; nothing skipped today | Open (harden fail-closed) |
| P1 | Restore testing covers one class (Sonarr SQLite only) | **Confirmed** | Open (rotate canary) |
| P1 | Homepage has cluster-wide Secret read | **Confirmed — could read the 1Password vault token + Flux deploy key; provably unused** | **Fixed, #65** |
| P1 | Application NetworkPolicy / PSA isolation implicit | Confirmed; netpol enforcement **is on** | Open (staged; some parts not worth doing — see handoff) |
| P1 | Tailscale member privilege (any member can own `tag:k8s-operator` + auto-approve exit node) | Partial — reachability overstated (only 3 /32s advertised); privilege issue real | **Fixed, #69** |
| P1 | Backup SSH does not authenticate the NAS host (`StrictHostKeyChecking=no`, 26 sites) | Confirmed; risk **low** (needs pre-existing LAN/repo compromise) | Open (P3, cheap `known_hosts` pin) |
| P1 | Public log ingestion accepts unauthenticated writes (`logs.mtgibbs.dev`) | **Confirmed live** (HTTP 200, no auth, event persisted) | **Half-fixed:** Loki retention amplifier closed (#66); edge auth (Cloudflare WAF / Vector basic-auth) still open |
| P2 | Control-plane recovery not reproducible | Confirmed; K3s datastore had **zero** backup coverage | **Datastore layer fixed, #67**; bare-metal node provisioning still manual |
| P2 | No repo-wide manifest validation gate; review-hub not a required check; image-automation commits to `main` | **Confirmed** (both substantive validators *skipped* on PR #59; branch protection has no required checks) | Open (add `kustomize build` + `kubeconform`; enable `secret-hygiene`) |
| P2 | Monitoring shares the failure domain it monitors | Partial (2 factual errors) but core conclusion stands — no external heartbeat | **Fixed, #68** |
| — | (incidental) Loki `retention_period` inert — no compactor block; retaining everything since deploy | **Confirmed live** | **Fixed, #66** |
| — | (incidental) Loki label cardinality injection via templated `app`/`dyno` | Confirmed | Open |

## Shipped this cycle (all merged + reconciled to `b1a8e4e`, tree green)

- **#64** — backup retention: scope deletion to `YYYY-MM-DD` dirs; `KEEP_DIRS=30` (nights, not a raw count of 4).
- **#65** — homepage RBAC: drop cluster-wide `secrets`/`configmaps` read.
- **#66** — Loki compactor: `retention_enabled: true` (verified with `loki -verify-config`).
- **#67** — K3s datastore backup: weekly `sqlite .backup` + token/tls/cred (verified end-to-end against the live datastore).
- **#68** — Watchdog → external healthchecks.io heartbeat (verified with `amtool check-config`).
- **#69** — Tailscale least-privilege ACL (validated by the `tailscale-acl` CI dry-run).

## Still open (ranked, none blocking)

1. **Backup coverage drift** — bring Mealie + Matrix Postgres into `postgres-backup`, and
   `mealie-data` / `synapse-data` / `ntfy-data` PVCs into the rsync jobs. Highest-value
   remaining item; `mealie-data` (hand-typed family recipes, one copy) is the sharpest.
2. **Edge auth for `logs.mtgibbs.dev`** — Cloudflare WAF header-match rule and/or Vector
   basic-auth (Cloudflare-side, non-GitOps, human task).
3. **Restore-canary rotation** across SQLite / Postgres / MariaDB / the new K3s snapshot.
4. **Repo-wide CI validation** — `kustomize build` + `kubeconform`; enable `secret-hygiene`
   in `.review-hub.yml`; promote `review-hub` to a required status check.
5. **Backup SSH `known_hosts` pinning** (low; cheap; do it whenever).

## Deliberately NOT doing (would cost more than it's worth here)

- Cluster-wide default-deny NetworkPolicies / `enforce=restricted` PSA — would break
  LinuxServer.io workloads, both Pi-holes, the Tailscale exit node, and node-exporter for
  near-zero marginal safety on a single-user LAN.
- Port-scoping the Tailscale grants — waits until family devices are actually members;
  premature narrowing has bitten this tailnet before.
- Per-file backup checksums, HA Alertmanager, image-update-as-PR — ceremony for a homelab.

---
---

> **The remainder of this file is the codex harness's original handoff, unedited.**
> Three of its factual claims are wrong (see Corrections above), and several findings
> have since been fixed (see Disposition). It is preserved as-is for provenance and for
> the original evidence and reasoning.

---

# Homelab repository review handoff — 2026-07-20

## Status and purpose

This is a read-only review packet for a second agent. It is not an implementation
spec and does not authorize cluster changes.

The first-pass review sampled the GitOps repository for resilience, backup and
restore behavior, security boundaries, observability, and delivery safeguards.
No live-cluster queries were performed, no secrets were inspected, and no local
or cluster state was changed.

The next agent should:

1. Challenge the findings below and correct false assumptions.
2. Look for compensating controls that may exist outside this repository.
3. Re-rank the work by likelihood, impact, and effort.
4. Convert only accepted findings into narrowly scoped specs.

Live-cluster validation belongs to the orchestrator using its approved homelab
tools. Do not use `kubectl` from a local coding-agent session.

## What is already strong

The repository already demonstrates several mature practices:

- Flux dependency ordering and reconciliation.
- Secrets supplied through External Secrets and 1Password references.
- Resource requests/limits and health probes on most long-running workloads.
- Prometheus, Alertmanager, Grafana, Loki, Vector, Uptime Kuma, and Flux
  notifications.
- Multiple data-specific backup jobs, backup-failure alerts, and a restore
  canary.
- Incident write-ups and configuration comments that preserve operational
  context.
- Renovate with human-reviewed pull requests rather than dependency automerge.

The useful review target is therefore inconsistent adoption and hidden
failure semantics, not missing foundational tooling.

## Findings to verify

### P0 — Backup jobs can report success after omitting required data

Evidence:

- `clusters/pi-k3s/backup-jobs/backup-cronjob.yaml:50-73` declares the PVC
  inventory but warns and continues when a PVC directory is absent.
- `clusters/pi-k3s/backup-jobs/worker2-backup-cronjob.yaml:50-73` and
  `media-backup-cronjob.yaml:50-73` use the same soft-skip pattern.
- `clusters/pi-k3s/backup-jobs/postgres-backup-cronjob.yaml:59-63` treats an
  unreachable PostgreSQL target as a successful skip.
- `clusters/pi-k3s/backup-jobs/prometheusrule.yaml` primarily reasons about
  Kubernetes Job success and last-success timestamps. Those signals cannot
  detect a zero-target or partial-target success.

Risk:

A backup CronJob can update `lastSuccessfulTime` while one or more intended
datasets were not copied. Existing alerts can therefore be green when the
recovery point is incomplete.

Questions for the next agent:

- Are any of these targets intentionally optional?
- Is there an external QNAP/Synology alert or file-count check that compensates?
- Can the jobs emit and validate an expected-target manifest without coupling
  monitoring to log parsing?

Probable direction if confirmed:

- Make required targets fail closed.
- Model optional targets explicitly.
- Record per-target timestamp, size, and checksum/status.
- Alert when the expected target set is incomplete.

### P0 — Backup coverage has drifted behind stateful application growth

Evidence:

- `postgres-backup-cronjob.yaml:85-86` backs up only Immich and n8n PostgreSQL.
- Mealie declares a local-path database PVC in
  `clusters/pi-k3s/mealie/postgresql.yaml`.
- Matrix declares local-path PostgreSQL and Synapse PVCs in
  `clusters/pi-k3s/matrix/pvc.yaml`.
- ntfy declares a local-path PVC in `clusters/pi-k3s/ntfy/pvc.yaml`.
- None of those names appear in the three local-path PVC backup inventories or
  PostgreSQL dump target list reviewed above.

Risk:

New stateful services can be deployed successfully without entering the backup
contract. Flux prune protection prevents accidental object deletion but does
not protect against node or media failure.

Questions for the next agent:

- Which of Mealie, Matrix, and ntfy contains data the owner actually wants to
  preserve?
- Are any PVCs intentionally disposable or reconstructed from another source?
- Does the NAS have storage-level protection for any of these paths?

Probable direction if confirmed:

Create a single declarative backup inventory with owner, data class, target,
RPO, retention, restore test, and optional/required status. Require every
stateful workload to be classified, even when the answer is "disposable."

### P0 — Retention cleanup is broader than its comment implies

Evidence:

`clusters/pi-k3s/backup-jobs/backup-cronjob.yaml:75-81` runs:

```sh
cd ${NAS_PATH} && ls -dt */ 2>/dev/null | tail -n +5 | xargs -r rm -rf
```

The shared parent also contains non-date directories such as `git-mirrors/`.
The command retains four top-level directories total, not four date-formatted
backup sets, and is not restricted to `YYYY-MM-DD` names.

Risk:

A sufficiently old non-date directory can be selected for deletion. Even when
that does not happen, the presence of non-date directories changes effective
dated-backup retention.

Questions for the next agent:

- What top-level directory names currently exist on the backup share?
- Do NAS snapshots or permissions prevent this job from removing other trees?
- Is retention supposed to be four weekly restore points or something longer?

Probable direction if confirmed:

Move retention into a separately reviewed job and restrict deletion to
validated date-formatted directories under a dedicated prefix. Treat unexpected
names as an error, not deletion candidates.

### P1 — Restore testing covers one narrow backup class

Evidence:

`clusters/pi-k3s/backup-jobs/restore-test-cronjob.yaml:54-73` restores only the
latest Sonarr SQLite database and checks its integrity plus an application
table.

Risk:

This is a good canary for rsync, SSH, and one SQLite backup, but it does not
prove PostgreSQL custom dumps, MariaDB dumps, other PVCs, NFS libraries, or
bare-metal cluster recovery.

Additional failure-domain concern:

`docs/game-preservation.md:178` already notes that the game library and dated
backup tree live on the same QNAP.

Probable direction if confirmed:

- Rotate automated canaries across SQLite, PostgreSQL, and MariaDB.
- Periodically restore one full application into scratch resources.
- Establish an immutable or off-appliance copy for irreplaceable data.
- Rehearse a control-plane replacement and record measured RPO/RTO.

### P1 — Homepage has cluster-wide Secret read access

Evidence:

`clusters/pi-k3s/homepage/rbac.yaml:12-14` grants `get` and `list` on
cluster-wide `secrets`. The Deployment separately receives selected widget
credentials through explicit Secret references.

Risk:

A Homepage container compromise could expose credentials from every namespace,
making a dashboard vulnerability a cluster-wide credential compromise.

Questions for the next agent:

- Does the deployed Homepage Kubernetes integration actually require Secret
  reads?
- If it does, which exact namespaces or named Secrets are required?

Probable direction if confirmed:

Remove Secret permission or replace the ClusterRole rule with the narrowest
namespace/resourceNames-based Roles that support the intended widgets.

### P1 — Application network and pod isolation is largely implicit

Evidence from repository-wide searches:

- The only `NetworkPolicy` resources found are generated Flux policies in
  `clusters/pi-k3s/flux-system/gotk-components.yaml`.
- Application namespace manifests do not carry Pod Security Admission
  `enforce`, `audit`, or `warn` labels.
- Only a subset of pods have a full non-root, dropped-capability,
  no-privilege-escalation, seccomp, and read-only-root-filesystem posture.
- Ordinary application pods generally do not disable automatic service-account
  token mounting.

Risk:

A compromised workload has broad east-west reach and often receives an
unneeded Kubernetes API credential. Hardening expectations are not enforced at
namespace admission time.

Questions for the next agent:

- Is K3s network-policy enforcement enabled on all nodes?
- Which namespaces legitimately require broad LAN, NFS, or internet egress?
- Which LinuxServer or host-network workloads prevent immediate restricted PSA?

Probable direction if confirmed:

Start with PSA `warn`/`audit` and an inventory report. Then stage default-deny
policies with explicit DNS, ingress, monitoring, database, NFS, and required
internet allowances. Avoid a single all-at-once enforcement change.

### P1 — Tailscale policy permits broad member privilege and reachability

Evidence:

- `tailscale/policy.hujson:21-24` lets both admins and all members assign
  `tag:k8s-operator`.
- `tailscale/policy.hujson:26-28` lets that tag auto-approve exit nodes.
- `tailscale/policy.hujson:30-40` gives members all-port access to peers,
  Kubernetes-tagged nodes, the inference host, and the entire home LAN.

Risk:

Any member account can acquire an infrastructure tag, and a compromised member
device gets a large lateral-movement surface.

Questions for the next agent:

- Is every tailnet member intended to be an infrastructure administrator?
- Are family accounts and automation identities separated?
- Which actual destinations and ports are needed for daily use?

Probable direction if confirmed:

Limit infrastructure tag ownership to admins or a dedicated provisioning
identity, then replace broad `*` grants with role-specific access.

### P1 — Backup SSH does not authenticate the NAS host

Evidence:

Backup and restore jobs consistently pass `StrictHostKeyChecking=no`, including
`backup-cronjob.yaml:45-47,66-69` and
`restore-test-cronjob.yaml:49-52`.

Risk:

DNS or routing compromise can redirect backup jobs to an impersonated SSH
server. The result could be backup exfiltration, false success, or hostile
restore input.

Probable direction if confirmed:

Mount a pinned `known_hosts` file from a GitOps ConfigMap or appropriate
1Password-backed Secret and require strict host verification.

### P1 — Public log ingestion appears to accept unauthenticated writes

Evidence:

- `clusters/pi-k3s/cloudflare-tunnel/config.yaml:11-13` publishes
  `logs.mtgibbs.dev` directly to Vector's HTTP source.
- `clusters/pi-k3s/log-aggregation/vector-configmap.yaml:19-27` captures the
  `Logplex-Drain-Token` header but the reviewed transforms do not validate it.

Risk:

Unless a Cloudflare-side policy exists outside Git, anyone discovering the
hostname can inject logs, pollute dashboards, and consume Loki storage.

Questions for the next agent:

- Is Cloudflare Access, a WAF rule, or another external control protecting the
  route?
- Can Vector validate a fixed drain token or can the tunnel enforce a secret
  header?

### P2 — Control-plane recovery is not yet reproducible

Evidence:

- `README.md:74-83` documents one Pi 5 control-plane node backed by microSD and
  hosting critical workloads.
- `node-config/README.md:8-20` explicitly says node configuration is currently
  apply-by-hand.
- The review found no repository-managed K3s datastore snapshot job or complete
  main-node provisioning definition.
- `docs/known-issues.md:27-35` records unresolved cross-node overlay networking
  failure on the control-plane node and a host-network workaround.

Risk:

GitOps reconstructs Kubernetes objects, but failure of the only server still
requires manual host provisioning, K3s/bootstrap recovery, and local-path data
placement. The unresolved CNI fault also weakens assumptions about failover and
service reachability.

Probable direction if confirmed:

Prioritize reliable server storage, datastore/bootstrap backups, repeatable node
provisioning, and a replacement rehearsal before deciding whether three-server
HA is worth the hardware and operational cost.

### P2 — Manifest delivery lacks a repository-wide validation gate

Evidence:

The only workflows under `.github/workflows/` are:

- `build-review-hub.yml`
- `tailscale-acl.yml`
- `triggerable-lint.yml`

`triggerable-lint.yml` validates one CronJob contract, not the full manifest
tree. No repository-wide Kustomize render, Kubernetes schema validation,
policy-as-code check, or secret scan was found.

In addition, ImageUpdateAutomation resources such as
`clusters/pi-k3s/local-llm-mcp/image-automation.yaml:35-46` commit image updates
directly to `main`.

Risk:

Malformed or policy-regressing YAML can reach Flux without a general admission
check. Direct image-update commits bypass any PR-only validation.

Probable direction if confirmed:

- Render every child Kustomization in CI.
- Run Kubernetes/CRD-aware schema validation.
- Add targeted policy checks for secrets, RBAC, mutable tags, privileged pods,
  host paths, and missing resource limits.
- Decide whether image automation should open PRs or receive equivalent
  provenance and post-commit validation.

### P2 — Monitoring shares the failure domain it monitors

Evidence:

- `clusters/pi-k3s/monitoring/helmrelease.yaml:84-91` stores Prometheus on a
  local-path PVC on the control-plane microSD.
- `monitoring/helmrelease.yaml:113-140` routes alerts through in-cluster
  Alertmanager to Discord.
- `clusters/pi-k3s/log-aggregation/loki-helmrelease.yaml:48-63` uses one
  node-pinned, local-path Loki instance.
- `loki-helmrelease.yaml:83-88` disables Loki self-monitoring and the canary.

Risk:

A cluster, control-plane storage, DNS, power, or internet failure can take down
both the monitored service and its alert path. TCP health on Vector does not
prove that an event was persisted and queryable in Loki.

Probable direction if confirmed:

Add one external heartbeat and one end-to-end log synthetic. Monitoring history
does not necessarily need full backup coverage, but the intended loss tolerance
should be explicit.

## Cross-cutting supply-chain notes

These are lower priority than the recovery and privilege findings:

- Most container images use version tags without digest pins.
- The Loki chart uses the floating constraint `6.x`.
- Several jobs install packages at runtime with `apk add`, making execution
  dependent on network availability and current package repositories.
- Renovate coverage is good but intentionally excludes several Flux-managed
  application paths.

The next agent should decide where immutability is worth the maintenance cost.
At minimum, backup/restore and privileged operational images deserve stronger
pinning than ordinary user-facing applications.

## Suggested review order

1. Validate backup target inventory and inspect current NAS top-level layout.
2. Confirm whether the retention command can touch `git-mirrors/` or other
   non-date directories.
3. Identify unprotected stateful PVCs and owner-approved RPOs.
4. Verify external compensating controls: NAS snapshots, offsite copy,
   Cloudflare rules, and outside-in monitoring.
5. Review Homepage RBAC and Tailscale tag ownership.
6. Diagnose the known cross-node overlay networking fault.
7. Design incremental PSA/NetworkPolicy rollout.
8. Add repository-wide validation before expanding automatic delivery.

## Explicit non-findings and limitations

- This review did not inspect live scheduling, current pod state, NAS contents,
  Cloudflare account policy, Tailscale account state, UPS behavior, router
  configuration, or storage snapshots.
- Absence from Git does not prove a control is absent operationally.
- No local `kustomize`, `kubeconform`, or `yamllint` executable was available
  during the first pass, so manifests were source-reviewed rather than fully
  rendered and schema-validated.
- The existing known-issues and roadmap documents already acknowledge portions
  of the recovery, data-backstop, and networking work. The purpose here is to
  highlight where those acknowledged items still affect current risk.

