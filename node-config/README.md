# node-config

Per-node **k3s** configuration (`/etc/rancher/k3s/config.yaml`) for the Pi cluster.

This is **host-level** config (node taints, labels, kubelet args) — *not* Kubernetes
manifests, so it lives **outside** `clusters/` (Flux must not try to apply it).

> ⚠️ **There is no provisioning automation consuming these yet.** They are the
> source-of-truth + apply-by-hand reference: copy the file to the node's
> `/etc/rancher/k3s/config.yaml` during setup or a rebuild. Tracked here so node
> **roles survive a rebuild** (a `kubectl taint` does not).

| File | Node | Role |
|---|---|---|
| `pi3-worker-2.yaml` | pi3-worker-2 (1GB Pi 3, 192.168.1.51) | **batch-only** — tainted `role=batch:NoSchedule`, labeled `role=batch`. Weekly/one-off jobs only; no serving/ingress/monitoring. |

**Apply (per node):**
```bash
sudo install -m 0644 node-config/<node>.yaml /etc/rancher/k3s/config.yaml
# taint/label apply on next k3s (re)start or rejoin; set live now via kubectl if needed.
```
