# Session Recap — 2026-05-24 (Health Check → pi3 Decommission as Serving Node)

This recap covers the second arc of 2026-05-24, beginning after the AI control panel work documented in `docs/recaps/2026-05-24-ai-controlpanel-and-context-budget.md`. A routine health check surfaced four apparent failures simultaneously. They were not four independent failures — they were one shared dependency going down. That root-cause diagnosis redirected the session from symptom chasing to a deliberate structural fix: decommission the antique LLM workloads from the Pi cluster, taint the 1 GB Pi 3 to its intended batch-only role, and evict the serving + monitoring workloads that never belonged on it. One open item — Immich offline — was identified as unrelated drift and deliberately deprioritized.

---

## The Diagnostic Discipline Moment

The session opened with a user-reported health check: Immich offline, homepage problems, SABnzbd "intermittently disappearing," and the AI-mode control-panel link failing. The instinct is to treat these as four separate problems. They are not.

Before investigating any individual symptom, the question to ask is: **do any of these share a common dependency?** The shared dependency here is `ingress-nginx` — the single front door for LAN-facing services. `ingress-nginx` had landed on `pi3-worker-2`, a 1 GB Raspberry Pi 3. At ~19:06 that node had gone `NodeNotReady` under memory pressure, flapping for approximately nine minutes before recovering on its own by ~19:15. Every service routed through its ingress appeared dead during that window. None of the services themselves were actually unhealthy (except Immich, which had a separate, unrelated cause).

**The lesson from the incident report (`docs/incidents/2026-05-24-pi3-worker-2-overload.md`):** "many services down at once usually means one shared dependency, not many independent failures. Check the front door before the rooms."

---

## Chapter 1 — CARL + Pi-side Ollama: Decommission the Antiques

### Why

CARL (Canvas reminder bot) and the Pi-cluster Ollama deployment were both dead weight:

- **CARL** was a stateless notification service that had not been actively used. Its only reason to exist was as an Ollama consumer — the same Ollama it was co-located with.
- **Pi-side Ollama** was fully superseded by the Beelink. Everything that called it (`local-llm-mcp`, Dewey, qwen3 coder) now calls Beelink Ollama via LiteLLM. The Pi-side deployment was pure memory overhead with spiky, unaccounted model-RAM — exactly the kind of pressure that contributes to a 1 GB node OOM-flapping.

Both had a pre-existing decommission spec (`specs/decommission-carl-pi-ollama/spec.md`) that was already marked as the correct next step. The health-check incident made executing it immediate rather than eventual.

### What was done

Commit `12ba63d` (2026-05-24 ~16:22) removed the full GitOps manifests for both services:

- Deleted `clusters/pi-k3s/carl/` (7 files: Deployment, ExternalSecret, ImageAutomation, Ingress, Kustomization, Namespace, Service)
- Deleted `clusters/pi-k3s/ollama/` (5 files: Deployment, ExternalSecret, Kustomization, Namespace, PVC, Service)
- Removed the CARL entry from `clusters/pi-k3s/homepage/configmap.yaml`
- Removed both Flux Kustomization references from `clusters/pi-k3s/flux-system/infrastructure.yaml` (with `prune: true` set, Flux garbage-collected the in-cluster resources automatically)

**Data safety:** Ollama's PVC held only re-pullable model weights — no user data. CARL is stateless. Both teardowns were pure resource recovery.

Commit `c1465f4` (2026-05-24 ~16:26) marked `specs/decommission-carl-pi-ollama/spec.md` as Done.

### Important scope boundary

**Beelink Ollama was not touched.** The teardown target was the Pi-cluster Ollama deployment only. The Beelink continues to serve all LLM requests. This is a pure memory-recovery operation on the Pi side.

---

## Chapter 2 — pi3-worker-2: Attacking the Root Cause

### The diagnosis

`pi3-worker-2` (`192.168.1.51`) is a **Raspberry Pi 3 with 1 GB RAM**. Its intended role is a dumb batch runner — a place for weekly/one-off scheduled jobs that need a node but not a capable one. It was never intended to be a serving node.

Two distinct mechanisms had put critical workloads on it:

**(a) Deliberately mis-pinned via nodeAffinity:**

`homepage` and `mtgibbs-site` both carried `nodeAffinity: prefers pi3-worker-2 (lightweight)`. The label was wrong. `mtgibbs-site` is a Next.js app — a Node.js runtime — and had accumulated **50 container restarts** from OOM thrashing on a 1 GB node. `homepage` is the always-on cluster dashboard; it blips visibly whenever its node does. Neither is lightweight. The affinity had pinned them to exactly the node least capable of running them.

**(b) Unconstrained workloads that landed there by scheduler default:**

Because `pi3-worker-2` had **no taint**, the scheduler treated it as a fully available node. These landed there opportunistically:

| Workload | Why this hurt |
|---|---|
| `ingress-nginx-controller` | The front door for all LAN-facing services |
| `alertmanager-...-0` | Monitoring control plane |
| `kube-prometheus-...-operator` | Monitoring control plane |
| `loki-canary` | Lightweight but shouldn't be on the weakest node |
| `node-exporter` | Expected on every node — this one is fine |

When the node flapped, `ingress-nginx` went with it. That is what turned a single-node OOM event into a network-wide service outage.

**Bonus finding:** `ingress-nginx` is a DaemonSet deployed to the three worker nodes, not a single-replica Deployment. This means it runs on all three workers — the Pi 3 was not actually the only instance. The outage during the flap window was caused by the DaemonSet pod on pi3 dying and probe failures surfacing before the Pi 5 instances' healthchecks re-stabilized the ingress path. It is not a permanent SPOF, but the Pi 3 carrying any piece of ingress was still wrong.

### Fix: Strip the affinity (commit `a4a0207`)

Commit `a4a0207` (2026-05-24 ~17:28) removed the `prefers pi3-worker-2` nodeAffinity blocks from:

- `clusters/pi-k3s/homepage/deployment.yaml`
- `clusters/pi-k3s/mtgibbs-site/deployment.yaml`

With the affinity removed, both rescheduled onto the 8 GB Pi 5 workers where they belong. The `mtgibbs-site` restart count stopped accumulating immediately.

### Fix: Taint pi3 batch-only (live + codified)

`pi3-worker-2` received a `role=batch:NoSchedule` taint applied live via kubectl. This prevents any new pod from scheduling on it unless the pod explicitly declares a matching toleration. The only DaemonSet pods still running on it after eviction are `node-exporter` — by design.

**The persistence problem:** a `kubectl taint` survives a node restart but not a node rebuild/rejoin. It is ephemeral from the GitOps perspective.

### Fix: Codify in node-config IaC (commit `0ac971f`)

Commit `0ac971f` (2026-05-24 ~17:52) established a new `node-config/` directory in the repo — **outside** `clusters/` (not in the Flux path) — for host-level k3s configuration that must persist across node rebuilds:

```
node-config/
├── README.md
└── pi3-worker-2.yaml     # /etc/rancher/k3s/config.yaml source of truth
```

`pi3-worker-2.yaml` encodes the taint (`role=batch:NoSchedule`) and label (`role=batch`) as k3s agent configuration. Applying it is manual today (`sudo install ... /etc/rancher/k3s/config.yaml`), but the file is the authoritative reference so a node rebuild starts from the correct role. The `README.md` documents the apply procedure and the per-node role table.

The incident was marked **Resolved** in `docs/incidents/2026-05-24-pi3-worker-2-overload.md` at this commit.

### The alertmanager PVC problem

Alertmanager had a `local-path` PV provisioned on pi3 — local-path PVs are hard-pinned to the node that provisioned them. When pi3 was tainted and alertmanager evicted, the pod went `Pending` because it couldn't schedule onto any other node while still bound to that PV.

Alertmanager's data (alert history) has low value — it is not backup-worthy and reconstructs from Prometheus on restart. The PVC was deleted and alertmanager was allowed to re-provision a fresh local-path PV on `pi5-worker-1`. It came up cleanly.

**Lesson:** `local-path` PVs are a node-affinity trap. Any pod using one is silently pinned to the node that first provisioned it. For monitoring control-plane components, this is worth tracking. Any future component that matters should use NFS-backed storage (schedulable anywhere) unless it is explicitly and intentionally node-local.

---

## Chapter 3 — Immich: Separate Problem, Deprioritized

During the health check, Immich was confirmed offline — `immich-server` at `replicas: 0`. This was not caused by the pi3 flap. Immich's pods run on the Pi 5s; the flap would not have affected them.

The `replicas: 0` state is drift: something (likely a manual `kubectl scale` during a debugging session at some prior point) set the replica count to zero, and the HelmRelease does not explicitly pin `replicas: 1` in its values, so Flux left it alone.

The user deprioritized the fix — memory headroom now exists on the Pi 5s (CARL + Pi-side Ollama gone), so Immich can come back up without pressure. The open item was logged in commit `527815c` (2026-05-24 ~17:55) in `docs/known-issues.md`.

**Fix when ready:** scale `immich-server` back to 1 replica (`kubectl scale deployment immich-server -n immich --replicas=1`) and pin `replicas: 1` explicitly in the HelmRelease values so it can't drift to zero again.

---

## End State

| Component | Before | After |
|---|---|---|
| CARL (Pi cluster) | Running (unused, wasting RAM) | Decommissioned — manifests removed, Flux pruned |
| Ollama (Pi cluster) | Running (superseded by Beelink) | Decommissioned — manifests + PVC removed |
| `pi3-worker-2` taint | None (scheduler fills freely) | `role=batch:NoSchedule` (live + codified in `node-config/`) |
| `homepage` scheduling | prefers pi3-worker-2 | No affinity — schedules on Pi 5s |
| `mtgibbs-site` scheduling | prefers pi3-worker-2 (50 restarts/OOM) | No affinity — schedules on Pi 5s |
| `ingress-nginx` on pi3 | Running (DaemonSet, shouldn't be there) | Evicted by taint — Pi 5s only |
| `alertmanager` on pi3 | Running (PV hard-pinned to pi3) | Reprovisioned on pi5-worker-1 |
| `pi3-worker-2` load | `ingress + monitoring + homepage + site + node-exporter` | `node-exporter` only |
| Immich | `replicas: 0` (offline, drift) | Still `replicas: 0` — logged in `known-issues.md`, deprioritized |

---

## Commits

| Hash | Date | Subject |
|---|---|---|
| `12ba63d` | 2026-05-24 ~16:22 | chore(teardown): decommission CARL + Pi-side Ollama (free Pi RAM) |
| `c1465f4` | 2026-05-24 ~16:26 | docs(spec): mark decommission-carl-pi-ollama Done (executed 2026-05-24) |
| `0eb2a5d` | 2026-05-24 ~17:25 | docs(incident): pi3-worker-2 overload → ingress outage (2026-05-24) |
| `a4a0207` | 2026-05-24 ~17:28 | fix(scheduling): stop pinning homepage + mtgibbs-site to the 1GB Pi 3 |
| `0ac971f` | 2026-05-24 ~17:52 | chore(node-config): codify pi3-worker-2 batch-only taint/label as IaC |
| `527815c` | 2026-05-24 ~17:55 | docs(known-issues): log Immich offline (immich-server replicas:0) as open |

---

## Key Lessons

### Many services down at once means one shared dependency

When a health check surfaces multiple apparent failures simultaneously, the first question is not "what's wrong with each service" — it is "what do all of these share?" Here, the shared dependency was `ingress-nginx`. Once identified, all symptoms except Immich collapsed into a single explanation. Immich's true cause (replica drift) was then correctly identified as separate.

### "Lightweight" is a runtime claim, not a label

The `homepage` and `mtgibbs-site` deployments carried nodeAffinity to a 1 GB Pi 3 under the reasoning that they were lightweight. `mtgibbs-site` is a Next.js app — not lightweight by any runtime measure — and had 50 OOM restarts to prove it. Affinity to a resource-constrained node should be justified by measured resource budgets, not intuition about what "should" be small.

### A weak node needs a taint, not trust

Without a taint, the Kubernetes scheduler treats a 1 GB node as a fair candidate for any workload that fits at schedule time. "Fits at schedule time" is not the same as "can survive the next memory spike." The taint is the mechanism for enforcing the node's actual role; everything else is just documentation.

### Node taints are not persistent across rebuilds — codify them

`kubectl taint` is ephemeral at the GitOps level. A node rebuild or rejoin would have lost the taint entirely, returning pi3 to untainted-general-purpose status. Codifying the taint in `/etc/rancher/k3s/config.yaml` (tracked in `node-config/`) means the node's role survives infrastructure operations. Apply-by-hand is acceptable for now; the file is the source of truth.

### local-path PVs are a hidden node-affinity trap

A PVC provisioned by `local-path` is bound to the node that provisioned it. Any pod using one is silently unschedulable anywhere else — including during node evictions or taints. This is a predictable failure mode for monitoring components (alertmanager, Loki, etc.) that use local-path for simplicity. Future components whose uptime matters should use NFS-backed storage.

---

## What Remains

- [ ] **Immich:** scale `immich-server` to 1 replica and pin `replicas: 1` in the HelmRelease values to prevent future drift. Memory headroom now exists.
- [ ] **ingress-nginx replica count:** ingress-nginx is a DaemonSet (3-node worker coverage), so the Pi 3 instance was not the only one — true SPOF risk is lower than it appeared. Worth confirming whether the ingress DaemonSet has anti-affinity configured and whether a Pi 5 node loss would still leave ingress healthy.
- [ ] **Remaining local-path PVs:** audit which other monitoring/control-plane pods have local-path PVs, and whether any of them are similarly pinned to nodes that could be tainted in future.
- [ ] **node-config provisioning automation:** `node-config/README.md` notes that apply is manual. If the Pi cluster gains Ansible coverage, the node-config files are natural candidates for automation.

---

## Related Documentation

- `docs/incidents/2026-05-24-pi3-worker-2-overload.md` — full incident record: timeline, root cause, remediation steps
- `node-config/README.md` — per-node k3s config IaC, apply procedure, node role table
- `node-config/pi3-worker-2.yaml` — the taint + label source of truth for pi3-worker-2
- `docs/known-issues.md` — Immich offline (open item)
- `specs/decommission-carl-pi-ollama/spec.md` — teardown spec, now marked Done
- `ARCHITECTURE.md` — node topology; pi3-worker-2 role documented
