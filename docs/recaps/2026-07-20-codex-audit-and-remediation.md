# Recap — Codex harness audit → verify → remediate (2026-07-20)

The `coding-harness-codex` executor (newly stood up earlier the same session) produced
an unprompted 410-line homelab resilience/security review. This session read it,
verified every finding against the live cluster, and shipped six fixes end-to-end. The
audit itself, with a full disposition, now lives at
`docs/research/2026-07-20-homelab-resilience-audit.md`.

## 1. Rescue + verification approach

The audit was committed to a **tmpfs worktree inside the codex container**
(`/tmp/oc-homelab-audit-handoff`) — one restart from gone. First act was to copy it out.

Then four read-only subagents verified it in parallel against the live cluster
(MCP + `ssh pi-k3s` reads only, one permitted single probe to the log endpoint):
backup coverage; RBAC + pod-security; external exposure; restore/CI/monitoring. The
rule given to each: challenge the findings, name what's **not** worth fixing, and treat
two questions as decisive — is K3s netpol enforcement on, and does an external heartbeat
exist.

**Outcome:** 8/11 findings confirmed, 2 partial, and **3 factual errors** corrected
(Prometheus is on worker-2 not the control-plane SD; nothing is being skipped by backups
*today*; the Loki canary is actually running). Decisive facts: netpol enforcement **is**
on (NetworkPolicies would work), and **no external heartbeat existed**.

## 2. Six PRs shipped — verify before ship

Every fix was validated against the real thing, not just YAML-linted:

- **#64 backup retention** — the audit flagged one bug; verification found **two**, both
  live. (a) The `rm -rf` ran an unfiltered glob over a shared parent, deleting
  `git-mirrors/` every Sunday (re-cloned 90 min later, so both jobs stayed green). (b)
  `keep 4` counted **nights, not weeks** — the Beelink writes a nightly dated dir — so the
  cluster had exactly **one** restore point at any moment. Fix: scope deletion to
  `YYYY-MM-DD` dirs, `KEEP_DIRS=30`. An 8-week simulation showed 1 → 5 surviving cluster
  sets.
- **#65 homepage RBAC** — the SA could `get/list` all 129 cluster Secrets, including the
  1Password vault token and the Flux deploy key. Proven unused (every widget cred comes
  from env). Verified conferred with `kubectl auth can-i --as=…`. Dropped.
- **#66 Loki compactor** — `retention_period` was inert (no `compactor:` block); Loki had
  retained every line since deploy. Verified the fix with `loki -verify-config` on the
  real 3.6.7 binary, and empirically proved `delete_request_store` is mandatory.
- **#67 K3s datastore backup** — the control-plane datastore (SQLite/kine) had **zero**
  coverage. New weekly job: `sqlite .backup` from a read-only mount + token/tls/cred tar.
  Verified end-to-end against the live datastore (`integrity_check: ok`, 3855 rows).
- **#68 Watchdog → external heartbeat** — `Watchdog` was routed to `null`. Now pings an
  off-site healthchecks.io check (chosen over self-host because only off-site catches a
  whole-home outage). Verified with `amtool check-config`.
- **#69 Tailscale least-privilege** — `tag:k8s-operator` → admins only; member→LAN grant
  scoped to the 3 advertised /32s. Done proactively ahead of the stated family-access
  goal. Validated by the `tailscale-acl` CI dry-run before merge.

## 3. Two bugs the dry-runs caught before they shipped

- **#67:** the first draft set `readOnlyRootFilesystem: true`, which is **incompatible
  with runtime `apk add`** (installs to `/usr` on the root fs). An ephemeral end-to-end
  test pod failed with `Unable to open log: Read-only file system` — caught it before the
  weekly schedule ever ran it. Dropped the flag to match the other backup jobs.
- **#66:** verified `loki.compactor` is a real chart values key (6.55.0
  `values.yaml:576`) rather than guessing — the exact bug class that had left
  `lokiCanary.enabled: false` in Git with three canary pods running.

## 4. The heartbeat human-gate

#68's `valuesFrom` needs a secret. Created the healthchecks.io check (period 15m / grace
10m), then stored the ping URL in 1Password directly via `op` (signed in with Touch ID
mid-session) at `op://pi-cluster/healthchecks/watchdog-ping-url`, and confirmed the
reference resolves before merge.

## 5. Reconcile cascade — a scare that wasn't

After merging #64, `flux get` showed `pihole not ready` and a batch of red
kustomizations. Diagnosis (not panic): forcing the GitRepo source to each new commit
triggers a normal `dependsOn` cascade — downstream shows "dependency not ready"
transiently. Confirmed DNS never dropped with `diagnose_dns google.com` → all paths
healthy. The cascade settled to 36/36 kustomizations + 7/7 HelmReleases green.

> Gotcha logged: `diagnose_dns` **requires** a `domain` arg — a bare call digs an empty
> string and returns a bogus "Unbound SERVFAIL". The real test with a domain was clean.

## State at close

- All six PRs (#64–#69) merged and reconciled to `b1a8e4e`; whole Flux tree green.
- Each change confirmed in the running cluster/tailnet, not just on `main`.
- DNS healthy throughout.

## Open items

- **Backup coverage drift** (the one remaining confirmed P0): Mealie + Matrix Postgres
  dumps and the `mealie-data` / `synapse-data` / `ntfy-data` PVCs are still unprotected.
  `mealie-data` (hand-typed family recipes, single copy) is the sharpest.
- **Edge auth** for `logs.mtgibbs.dev` (Cloudflare-side; #66 closed only the Loki
  retention amplifier).
- Restore-canary rotation; repo-wide CI (`kustomize`/`kubeconform` + enable
  `secret-hygiene`, make `review-hub` required); backup SSH `known_hosts` pin.
- Confirm the healthchecks.io **email integration** is attached.
- Housekeeping: the global git identity still reads `Hot Coder (qwen)` (all commits this
  session used `-c user.name/email` overrides); the Discord webhook URL was printed into
  the session transcript while decoding the alert config (optional rotate); stale
  auto-approver comment at `tailscale-config/connector.yaml:16-17`.

## Commits

Merged to `main`: #64 (retention), #65 (homepage RBAC), #66 (Loki compactor),
#67 (K3s datastore backup), #68 (Watchdog heartbeat), #69 (Tailscale ACL).
Merge HEAD at close: `b1a8e4e`.
