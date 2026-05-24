# Incident: pi3-worker-2 overload → node flap → ingress outage (2026-05-24)

- **Date:** 2026-05-24, ~19:06–19:15 (flap window)
- **Severity:** Medium — intermittent, network-wide service blips; no data loss
- **Status:** Root cause identified; **remediation pending** (node-role enforcement — see §6)
- **Detected via:** routine health check (user reported Immich offline, homepage problems, SABnzbd intermittently disappearing, AI-mode link failing)

---

## 1. TL;DR

`pi3-worker-2` — a **Raspberry Pi 3 with 1 GB RAM** (`192.168.1.51`) — was running **serving and
control-plane-adjacent infrastructure it was never sized to carry**. Under memory pressure its
kubelet went `NodeNotReady` (~19:06), taking down everything scheduled on it — including the
**`ingress-nginx` controller**, which is the single front door for most LAN services. That's why
*multiple unrelated services appeared to fail at once*: they didn't — their **ingress** did.

The node recovered on its own by ~19:15. The symptoms were transient, but the **scheduling policy
that put critical workloads on the weakest node is the real defect.**

---

## 2. Intended role of pi3-worker-2 (the design intent)

`pi3-worker-2` is a **dumb batch runner** — a place for one-off / scheduled jobs (weekly cron-style
containers, throwaway scripts) that need a node but not much of one. It is **not** a serving node:

- **NOT** for ingress / reverse-proxy
- **NOT** for monitoring control-plane (Prometheus operator, Alertmanager)
- **NOT** for always-on web apps

At 1 GB RAM (vs 8 GB on every Pi 5), it can hold a transient job or two — nothing resident and
memory-hungry.

---

## 3. What was actually running on it (the leak)

Two distinct ways critical workloads ended up there:

**(a) Deliberately mis-pinned — `nodeAffinity: prefers Pi 3 (lightweight)`:**

| Workload | Reality |
|---|---|
| `mtgibbs-site` (Next.js) | **NOT lightweight** — a Node.js runtime; observed **50 restarts** (OOM thrash) |
| `homepage` | Always-on dashboard; the *first* thing you notice when it blips |

> The "lightweight" label was the mistake. A Next.js site on 1 GB is a guaranteed OOM loop.

**(b) Unconstrained — no affinity, scheduler just placed them there:**

- `ingress-nginx-controller` ← the damaging one: it's the front door, and it's effectively a SPOF here
- `alertmanager-...-0`
- `kube-prometheus-...-operator`
- `loki-canary`
- `node-exporter` (DaemonSet — *expected* on every node, not a problem)

Nothing **tainted** the node, so the scheduler treated the 1 GB Pi 3 as fair game for anything.

---

## 4. Timeline & impact

- **~19:06** — `pi3-worker-2` kubelet → `NodeNotReady` (memory exhaustion). All its pods flagged.
- **19:06–19:15** — liveness/readiness probes fail for `ingress-nginx`, `alertmanager`,
  `prometheus-operator`, `mtgibbs-site`, `loki-canary`. **ingress-nginx down → LAN services
  routed through it (homepage, *arr, etc.) intermittently unreachable.**
- **~19:15** — node recovered; pods resumed.

**Mapped to the reported symptoms:**

| Symptom | Actual cause |
|---|---|
| "Homepage loading problems" | ingress-nginx (on pi3) flapping |
| "AI mode link not working" (HTTP 000) | transient — the flap window; the Beelink endpoint itself was healthy |
| "SABnzbd intermittently disappears" | its homepage widget losing the ingress path; SABnzbd pod (on pi5-worker-2) was fine |
| "Immich offline" | **separate, unrelated** — `immich-server` is scaled to `replicas: 0` (drift); not caused by the flap |

---

## 5. Contributing factor (addressed same day)

Pi-side **Ollama + CARL** were still resident on the cluster — legacy LLM workloads fully superseded
by the Beelink, holding **spiky, unaccounted model RAM**. Decommissioned 2026-05-24 (commit
`12ba63d`, `specs/decommission-carl-pi-ollama`), freeing cluster memory. This reduces overall
pressure but does **not** fix the core issue: critical workloads are still scheduled onto the 1 GB node.

---

## 6. Remediation (the actual fix — pending)

Enforce the node's intended role so the scheduler can't put serving/critical workloads on it:

1. **Taint `pi3-worker-2`** so nothing lands there unless it explicitly opts in:
   ```
   kubectl taint nodes pi3-worker-2 role=batch:NoSchedule
   ```
   (Codify via the node's GitOps/bootstrap config, not a one-off `kubectl`.)
2. **Remove the `prefers Pi 3` nodeAffinity** from `homepage` and `mtgibbs-site` — they are serving
   apps and belong on the 8 GB Pi 5s. (`clusters/pi-k3s/homepage/deployment.yaml`,
   `clusters/pi-k3s/mtgibbs-site/deployment.yaml`.)
3. **Let `ingress-nginx` + monitoring** schedule on the Pi 5s (removing the taint barrier + their
   lack of affinity means they'll avoid the tainted Pi 3 automatically).
4. **Batch/one-off jobs** that *should* use the Pi 3 get a matching `toleration` + `nodeSelector`
   (`role=batch`). That's the node's whole purpose.

**Net end state:** `pi3-worker-2` = dedicated dumb runner for scheduled/one-off jobs; all serving,
ingress, and monitoring lives on the Pi 5s. A 1 GB node flapping should then take down *only* a
throwaway job, never the front door.

> **Bigger question worth a beat:** is `ingress-nginx` single-replica? If so, even off the Pi 3 it's
> a SPOF on one Pi 5. Consider whether it warrants a second replica with anti-affinity. (Out of scope
> for this incident; noted.)

---

## 7. Lessons

- **"Lightweight" is a runtime claim, not a wish.** A Next.js app is not lightweight; don't pin
  memory-hungry serving apps to a 1 GB node by calling them light.
- **A weak node needs a taint, not trust.** Without a taint, the scheduler will fill any node with
  free memory-at-schedule-time — including the one that can least afford a spike.
- **"Many services down at once" usually means one shared dependency** (here: ingress), not many
  independent failures. Check the front door before the rooms.

---

## Related

- Decommission of the contributing memory load: `specs/decommission-carl-pi-ollama/spec.md`
- Node topology: `ARCHITECTURE.md`
- Separate open item surfaced same day: `immich-server` at `replicas: 0` (drift) — restore + pin.
