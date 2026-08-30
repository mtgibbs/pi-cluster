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
| `pi5-worker-2.yaml` | pi5-worker-2 (Pi 5) | **harness fleet workers** — labeled `harness-fleet=true`, no taint. The `nodeSelector` on every Job the dispatcher renders; without the label a dispatched run sits Pending. Additive: the node keeps taking ordinary workloads. |

**Apply (per node):**
```bash
sudo install -m 0644 node-config/<node>.yaml /etc/rancher/k3s/config.yaml
# taint/label apply on next k3s (re)start or rejoin; set live now via kubectl if needed.
```

⚠️ **Check before you install over an existing file.** That command replaces
`/etc/rancher/k3s/config.yaml` wholesale. `pi3-worker-2` had no prior config, so it was
safe there; a node that was installed with server/token or kubelet args in that file
would lose them, and an agent that loses its config does not fail at install time — it
fails at the next restart, possibly weeks later. Read the file first and merge the keys
if it exists.

**A label here is not live until k3s restarts.** These files are rebuild persistence.
Setting the label on a running node is a second, separate step:

```bash
kubectl label node <node> <key>=<value> --overwrite    # live, now
```

Both are needed: the `kubectl` half takes effect immediately and is lost on rebuild;
this file survives the rebuild and takes effect on restart. Doing only one is the trap —
a label that works today and vanishes on the next reprovision, or one that is committed
and does nothing for weeks.
