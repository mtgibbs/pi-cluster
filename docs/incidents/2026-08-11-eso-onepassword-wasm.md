# Incident: ClusterSecretStore `onepassword` WASM trap → 53/56 ExternalSecrets stopped refreshing (2026-08-11)

- **Date:** onset 2026-08-11 between **20:28 and 20:57 UTC**; detected 2026-08-12 ~18:55 UTC (**~40 h undetected**)
- **Severity:** High-latent — no user-visible outage, no data loss, but **all secret rotation was dead** and no new secret could be created cluster-wide
- **Status:** ✅ **Resolved 2026-08-13 17:02 UTC** (~44.5 h total). Fixed by the pod roll that merging the observability PR (#159) triggered — see §4.1. Root cause confirmed as in-process WASM state; the service-account token is exonerated.
- **Detected via:** *accidentally*. A routine docs merge triggered a Flux re-reconcile; the resulting `get_flux_status` showed nearly every Kustomization not-ready. **Nothing alerted.**

---

## 1. TL;DR

`ClusterSecretStore/onepassword` could not initialise its provider client. The
`onepasswordSDK` provider runs the 1Password SDK as an **Extism/WASM plugin**, and
`init_client()` trapped:

```
wasm error: out of bounds memory access
  op_extism_core.wasm._ZN10extism_pdk6extism10load_input(i32)
  op_extism_core.wasm._ZN10extism_pdk11input_bytes(i32)
  op_extism_core.wasm.init_client() i32
```

Every ExternalSecret then failed with `ClusterSecretStore "onepassword" is not ready` —
**53 of 56**. One broken component, 53 identical echoes.

**The reason this ran 40 hours is the interesting part, not the WASM bug.** Failing
ExternalSecrets keep their last-synced value, so every materialised Kubernetes Secret
stayed intact and every workload kept running. The cluster looked fine. What was actually
dead was the *refresh* plane: no rotation, and no new secret could ever be created. It
would have become a real outage the moment any pod needing a fresh secret restarted.

---

## 2. Timeline (UTC)

| When | What |
|---|---|
| 2026-08-11 19:22–20:28 | Last successful syncs (`nfs-credentials`, `mtgibbs-github`, `new-horizons-secrets`) |
| 2026-08-11 **20:28–20:57** | **Store dies.** No sync succeeds after 20:28 |
| 2026-08-11 20:57–21:09 | Every dependent Flux Kustomization flips not-ready |
| 2026-08-11 → 08-12 | 40 h of silence. Renovate CronJobs fail every run; nobody notified |
| 2026-08-12 ~18:52 | Unrelated docs merge → Flux re-reconciles all Kustomizations |
| 2026-08-12 ~18:55 | `get_flux_status` run as a routine post-merge check shows the cascade |
| 2026-08-13 | Root-caused to the WASM trap; observability gap identified |

---

## 3. Root cause

The proximate cause is a trap inside the WASM plugin that backs the 1Password SDK
provider. What makes it interesting is everything it **isn't**:

| Hypothesis | Ruled out by |
|---|---|
| A GitOps change | No commits to `external-secrets*` since before 2026-08-01; chart pinned `1.2.0`, last Helm change 2026-01-28 |
| Crash-loop / bad startup | Controller pod: **0 restarts** |
| cgroup OOM-kill | `resources: {}` — no limits were set at all |
| Node memory pressure | All four nodes `Ready`, no pressure conditions |
| An expired service-account token | An expired token returns an **auth error**, not a WASM trap |

Nothing changed in Git, in the image, or on the nodes. What changed was **in-process
state** in a controller that had been running without restart since at least the last
rollout (Deployment created 2025-12-24, revision 5). The provider instantiates a client
per store validation, driven by ~56 ExternalSecrets reconciling on interval; the most
consistent explanation is that the Extism host's linear memory was progressively consumed
until allocation failed, after which the trap is deterministic and never self-heals.

**Not fully excluded:** a *malformed* (as opposed to expired) token could panic the Rust
SDK inside the WASM sandbox and surface identically. Distinguishing the two requires
reading `external-secrets/onepassword-service-account`, which the harness cannot do.
The restart below discriminates between them.

---

## 4. Remediation

```sh
kubectl -n external-secrets rollout restart deploy/external-secrets
kubectl -n external-secrets get clustersecretstore onepassword -w
```

- **Store goes Ready** → in-process WASM state confirmed; ESO re-reconciles all 53 on its own.
- **Fails identically** → the bootstrap credential is at fault.
  `external-secrets/onepassword-service-account` (key `token`) is created **manually**, is
  **not in Git**, and is recreated per `.claude/skills/secrets-management/SKILL.md`.

**A restart is genuinely required — retrying is not enough.** ESO retried client creation
continuously for 40 hours and never recovered, because retrying *within the same process*
does not reset the WASM host memory. Only a process restart does. (This tripped up the
initial analysis in-session: the continuous retries were misread as evidence that a
restart wouldn't help. The opposite is true.)

### 4.1 What actually happened (2026-08-13)

The fix arrived as a side effect of the remedy for the *observability* gap. Adding
`resources:` to the HelmRelease values mutates the **Deployment pod template**, so merging
#159 made Flux run a Helm upgrade, which rolled the controller — deployment revision 5 → 6,
ReplicaSet `67dffb589f` → `598fd94748`. A fresh process meant a fresh Extism host.

Recovery was immediate and unambiguous in the controller log:

```
17:02:22  error  ... err: ClusterSecretStore "onepassword" is not ready   (last error)
17:02:29  info   reconciled secret  {operator-oauth, tailscale}
17:02:31  info   reconciled secret  {matrix-db-password, backup-jobs}
17:02:34  info   reconciled secret  {cloudflare-api-token, cert-manager}
17:02:36  info   reconciled secret  {vector-ntfy, log-aggregation}
```

ESO then drained the backlog at roughly one secret every 2 s. No further WASM traps.

**This settled the open question.** The §3 analysis could not separate "WASM host memory
exhausted" from "malformed token panicking the SDK", and the initial write-up said a
rolling restart wouldn't discriminate them. It did: **the token was never touched**, and
the same token works in a fresh process. A malformed value would have failed identically
after the restart. Root cause is in-process runtime state; the credential is fine.

**Two harness gaps this exposed, both now addressed:**

- `restart_deployment`'s whitelist was applications-only, so the agent could diagnose this
  and not act on it. Fixed in `pi-cluster-mcp#53` (controller only; webhook and the Flux
  controllers deliberately excluded).
- `reconcile_flux` accepts only `kustomization` and `helmrelease`, not `gitrepository`. The
  documented **reconcile-source-first** order is therefore not fully expressible through the
  MCP — reconciling the Kustomization before the source has fetched the new commit is a
  no-op, which cost a confused minute here. The GitRepository's own 1 m interval covers it,
  but the tool should grow the type.

---

## 5. Why nobody knew (the real defect)

**External Secrets Operator had no metrics scraped.** Not "no alert rule" — no telemetry
at all. The chart's `serviceMonitor` was never enabled, so the controller's `:8080`
endpoint existed and was never read. Any alert rule written against ESO metrics would have
matched nothing and reported healthy, which is worse than having no rule.

Compounding it:

- **The failure is silent by construction.** Materialised Secrets persist, so every
  workload stayed up and every dashboard stayed green. There is no symptom to notice
  without instrumenting the refresh path specifically.
- **The pod looked perfect.** `Running`, `1/1`, `0 restarts`. A liveness probe on process
  health would not have fired — the process was healthy; its embedded WASM runtime wasn't.
- **`resources: {}`** meant there was no memory ceiling to convert a slow degradation into
  a restart. With a limit, the kernel would have recycled the pod and the cluster would
  have self-healed within minutes.
- **Detection was luck.** It surfaced only because an unrelated docs merge caused a Flux
  re-reconcile that a human happened to look at.

---

## 6. Fixes

Shipped with this document:

1. **`serviceMonitor.enabled: true`** on the ESO HelmRelease, labelled
   `release: kube-prometheus` to match the operator's selector. *Prerequisite for
   everything else* — without it the rules below are decorative.
2. **`prometheusrule-external-secrets.yaml`** — three alerts:
   `ClusterSecretStoreNotReady` (primary; the store is the cause, the 53 secrets are
   echoes), `ExternalSecretsFailingToSync` (partial failure the store alert can't see),
   and `ExternalSecretsOperatorDown` (because the first two are blind if the operator is
   gone).
3. **Memory limit (512Mi)** on the controller — deliberate self-healing, not capacity
   planning. It converts "degrades silently forever" into "OOM-restarts and recovers".

Still open:

- **Consider an ESO chart upgrade** from `1.2.0` if upstream has a fix for WASM/SDK
  client-lifetime leakage. Worth a look before assuming the limit alone is enough.
- **Audit for the same shape elsewhere.** The pattern — *a long-lived controller whose
  embedded runtime dies while the process stays healthy* — is not unique to ESO, and
  liveness probes are structurally blind to it.
- **Watch whether it recurs.** If the WASM host leaks on a fixed schedule, the 512Mi limit
  converts a 40-hour silent outage into a periodic self-healing restart — acceptable, but
  the leak itself would still be worth reporting upstream. Uptime since 2026-08-13 17:02
  is the number to watch.

---

## 7. Lessons

- **A component with no metrics has no alerts, however many alert rules you write.** The
  gap here was one missing `serviceMonitor.enabled`, three layers below where anyone
  would think to look.
- **"Everything still works" is not the same as "everything is fine."** Cached state made
  a total control-plane failure invisible. Alert on the *refresh path*, not the artefact.
- **Resource limits are a self-healing mechanism, not just a capacity guardrail.** The
  absence of a limit is what let this run 40 hours instead of 4 minutes.
- **Retry-in-process ≠ restart.** For anything embedding a runtime (WASM, JIT, plugin
  host), a hot retry loop can hide a condition only a process restart clears — and its
  persistence is easily misread as proof that restarting won't help.
- **One cause, 53 symptoms.** Alert on the cause. Paging per-secret would have produced
  53 pages and one insight.
