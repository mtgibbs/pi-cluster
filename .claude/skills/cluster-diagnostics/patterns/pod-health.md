# Pattern: pod / workload not healthy

**When:** a pod is failing, crashing, stuck Pending, or a Service is unreachable, and it is *not*
tied to a specific deploy you just made. The generic "something in the cluster is unwell" entry
point. If it IS right after a deploy or merge, use [deploy-health.md](deploy-health.md) instead —
that one starts from Flux and the dependency order.

## Layers (each independent — fan out one worker per layer)

| # | Layer | Tool(s) | Healthy verdict | Red flags |
|---|---|---|---|---|
| 1 | Workload state | `get_cluster_health` | pods Running + ready, restarts flat | CrashLoop, ImagePull, Pending, restart count climbing |
| 2 | Why this pod | `get_pod_logs`, `describe_resource(kind="pod")` | clean startup, no repeated error | see the state table below; `describe` events name the cause |
| 3 | Storage | `get_pvcs` | Bound, capacity headroom | Pending (no StorageClass/space), Lost, PVC bound elsewhere |
| 4 | Reachability | `describe_resource(kind="service")`, `curl_ingress`, `test_pod_connectivity` | endpoints populated, HTTP answers | **no endpoints = selector doesn't match pod labels** |
| 5 | Node pressure | `get_cluster_health` (node section) | allocatable headroom on the target node | memory/CPU exhausted → evictions, Pending |

## Pod state → what it actually means

| State | Usual cause |
|---|---|
| **Pending** | No node fits: resource requests too big, nodeSelector unsatisfiable, or PVC unbound |
| **CrashLoopBackOff** | The app itself exits. `get_pod_logs(previous=true)` is the money call — missing config/secret, port conflict (hostNetwork), or a failing health probe |
| **ImagePullBackOff** | Registry auth or the tag doesn't exist. Private `ghcr.io/mtgibbs/*` → the `ghcr-pull-secret` reuse, see `[[secrets-graph]]` |
| **ContainerCreating** (stuck) | Volume mount failing or an init container hanging — check `describe_resource` events, then the NFS mount |
| **Running but not ready** | Readiness probe failing. The app is up; the probe disagrees. Check probe path/port/timing before blaming the app |

## Pi-specific constraints that cause these

These are the house-specific reasons a generic k8s answer will be wrong here:

- **8GB per node.** Prometheus is the memory hog. "Pending" on `pi-k3s` is usually genuine capacity,
  not a scheduling bug. `pi3-worker-2` has **1GB** — almost nothing fits there; check `nodeSelector`
  before concluding the scheduler misbehaved.
- **ARM64 only.** An `ImagePullBackOff` or an instant crash on a brand-new image is often an
  `amd64`-only image, not a credential problem.
- **Pi-hole runs hostNetwork** → port 80 is occupied on that node; ingress uses 443 only.
- **SD-card I/O is slow** on the master (NVMe is the standing fix). Slow PVC reads and probe timeouts
  can be storage latency rather than app fault.
- **Single control-plane node.** Evicting or rescheduling a `pi-k3s`-pinned pod = downtime, not a
  failover. `local-path` PVCs are node-bound: a pod with one *cannot* move nodes.

## Discipline for THIS scenario

- **Read the events before the logs.** `describe_resource` events name scheduling/mount/probe causes
  that logs never show — a Pending pod has no logs at all.
- **`previous=true` on a CrashLoop.** Current-container logs on a restarting pod are frequently empty
  or truncated; the crash evidence is in the previous container.
- **No endpoints is a label bug, not a network bug.** Before reaching for connectivity tools, confirm
  the Service selector actually matches the pod labels.

## Synthesis

Name the earliest failing layer and the specific cause (which probe, which missing key, which node
had no room). Downstream layers are usually symptoms. If the fix is a manifest or secret change,
state it precisely and hand it to `cluster-ops` — don't apply it here.
