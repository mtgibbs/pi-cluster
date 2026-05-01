# QNAP Cutover Runbook (v2)

**Author:** Lessons from 2026-04-30 failed attempt
**Goal:** Migrate cluster NFS storage from Synology (192.168.1.60) to QNAP (192.168.1.61) via `storage.lab.mtgibbs.dev` DNS abstraction. Avoid the failure modes from the v1 attempt.

## Why v1 Failed (Don't Repeat)

1. **Wrong export path.** PVs used `/share/cluster/...` but QNAP exports `/cluster`.
2. **NFS lock manager unreachable.** rpc.statd/lockd not advertised on QNAP. Mounts without `nolock` returned misleading "Connection refused".
3. **Generic mount tests.** Validated parent path `/share/cluster` worked, never tested each PV's exact path + readOnly + mountOptions combo.
4. **Sticky kubelet NFS mounts.** Pods that survived the swap kept old mounts to Synology. Validation tested wrong storage.
5. **Flux race during scale-down.** Flux re-scaled deployments while we were trying to drain them.
6. **media→jellyfin hard dependency.** Jellyfin's mount failure cascaded to the entire media stack.
7. **UID drift.** `rsync --numeric-ids` preserved Synology UIDs that don't match QNAP service accounts.

## Pre-Cutover Phase (Day Before)

### 1. Run Readiness Check

```sh
sh migration/qnap-readiness-check.sh
```

**Pass criteria:**
- DNS: `storage.lab.mtgibbs.dev` → `192.168.1.61`
- `showmount -e`: lists `/cluster <subnet>` (note: it's `/cluster` not `/share/cluster`)
- `rpcinfo -p`: portmapper + mountd + nfs at minimum

**Action items based on output:**

- **If `lockd`/`statd` MISSING:** keep `nolock` in every NFS PV's `mountOptions`. (QNAP NFS lock manager isn't reachable; trying to lock will fail.)
- **If showmount shows different export name than `/cluster`:** update PV manifests to match.

### 2. Run Pre-Flight Bench

```sh
kubectl apply -f migration/preflight-bench.yaml

# Wait ~60s for all jobs to complete
kubectl get jobs -n default | grep preflight

# Each must show 1/1 Completions. Get the OK lines:
for j in $(kubectl get jobs -n default -o name | grep preflight); do
  echo "=== $j ==="
  kubectl logs $j -n default --tail=3
done

# All 8 should print "PREFLIGHT OK <name>". Any FAIL = stop, fix, retry.

kubectl delete -f migration/preflight-bench.yaml
```

**This is the single most important pre-cutover step.** If any of the 8 mounts can't bench-mount, the cutover will break that workload. Fix BEFORE swapping any production PV.

Specifically critical:
- `preflight-jellyfin-video-ro` — read-only mount. This is the one that broke v1.
- `preflight-immich-library` — has `rsize`/`wsize` mountOptions.
- `preflight-calendar` + `preflight-n8n-calendar` — share the same path; both must work.

### 3. Fix UID Ownership On QNAP (If Migrating Backups Too)

```sh
# SSH into QNAP as admin
sudo chown -R cluster-backup:everyone /share/cluster/backups
sudo chmod -R g+w /share/cluster/backups
```

Other paths (media, photos) typically don't need this — pod UIDs match the migrated UIDs. Verify by spot-checking ownership: `ls -la /share/cluster/media/video | head -3`.

### 4. Decouple Flux Graph

Verify `clusters/pi-k3s/flux-system/infrastructure.yaml` does NOT have `media → dependsOn → jellyfin`. (This was removed during v1's recovery; keep it removed.)

## Cutover Phase

### Pre-flight Once More

```sh
# Right before kicking off, re-run preflight bench. State could have shifted.
kubectl apply -f migration/preflight-bench.yaml
sleep 60
# All 8 must succeed.
kubectl delete -f migration/preflight-bench.yaml
```

### 1. Suspend Flux For Affected Namespaces

```sh
flux suspend kustomization -n flux-system jellyfin immich media calendar n8n
```

### 2. Scale All NFS Workloads To 0

```sh
kubectl -n jellyfin scale deploy/jellyfin --replicas=0
kubectl -n immich scale deploy/immich-server --replicas=0
kubectl -n media scale deploy --all --replicas=0
kubectl -n calendar scale deploy --all --replicas=0
kubectl -n n8n scale deploy/n8n --replicas=0
```

### 3. Wait For Full Drain

```sh
until [ "$(kubectl get pod -A --no-headers 2>/dev/null | grep -E '^(jellyfin|immich|media|calendar|n8n) ' | grep -v Completed | wc -l | tr -d ' ')" = "0" ]; do
  echo "draining... $(date)"
  sleep 5
done
echo "all drained"
```

### 4. Final Delta rsync

```sh
kubectl delete job synology-to-qnap-migration -n default --ignore-not-found
kubectl apply -f migration/synology-to-qnap.yaml
# Wait for Succeeded
kubectl wait --for=condition=complete --timeout=30m job/synology-to-qnap-migration -n default
```

### 5. Flip DNS storage.lab → .61

Edit `clusters/pi-k3s/pihole/pihole-custom-dns.yaml` — change `storage.lab.mtgibbs.dev` to `192.168.1.61`. Commit + push.

```sh
flux reconcile source git -n flux-system flux-system
flux reconcile kustomization -n flux-system pihole
# Wait for Pi-hole pods to be Running on the new ConfigMap
sleep 15
kubectl -n pihole rollout restart deploy/pihole deploy/pihole-secondary
sleep 30
```

Verify:

```sh
kubectl run dns-verify --image=alpine:3.19 --rm -it --restart=Never -n default -- \
  sh -c "apk add -q bind-tools && nslookup storage.lab.mtgibbs.dev"
# Must return 192.168.1.61
```

### 6. Update PV Manifests

Apply these path/option changes via Git on the migration branch:

- `server: 192.168.1.60` → `server: storage.lab.mtgibbs.dev`
- `path: /volume1/cluster/...` → `path: /cluster/...` (note: NOT `/share/cluster`)
- Add `nolock` to every PV's mountOptions (keep existing options)

Backup CronJobs: `NAS_USER="mtgibbs"` → `NAS_USER="cluster-backup"`, `NAS_PATH=/volume1/cluster/backups` → `/cluster/backups`.

Commit, push, merge to main.

### 7. Delete Old PVs+PVCs So Flux Can Recreate

```sh
kubectl -n jellyfin delete pvc jellyfin-video --wait=false
kubectl -n immich delete pvc immich-library --wait=false
kubectl -n calendar delete pvc calendar-data --wait=false
kubectl -n n8n delete pvc n8n-calendar --wait=false
kubectl -n media delete pvc media-downloads media-library media-music media-books --wait=false
kubectl delete pv jellyfin-video-nfs immich-library-nfs calendar-nfs n8n-calendar-nfs media-downloads-nfs media-library-nfs media-music-nfs media-books-nfs --wait=false

# Patch finalizers if stuck (PV protection)
sleep 10
for r in pv/jellyfin-video-nfs pv/immich-library-nfs pv/calendar-nfs pv/n8n-calendar-nfs pv/media-downloads-nfs pv/media-library-nfs pv/media-music-nfs pv/media-books-nfs; do
  kubectl get $r 2>/dev/null && kubectl patch $r -p '{"metadata":{"finalizers":null}}' --type=merge
done
```

### 8. Resume Flux + Reconcile

```sh
flux resume kustomization -n flux-system jellyfin immich media calendar n8n
flux reconcile source git -n flux-system flux-system
flux reconcile kustomization -n flux-system jellyfin immich media calendar n8n
```

### 9. Verify All 8 New PVs Bound + Pods Running

```sh
kubectl get pv | grep nfs   # All 8 should show Bound to *-nfs PVCs at /cluster/...

kubectl get pod -A | grep -vE 'Running|Completed' | grep -vE '^NAMESPACE|kube-system'
# Should be empty. Anything stuck = stop and diagnose.
```

### 10. REAL Mount Verification

```sh
for ns in jellyfin immich media calendar n8n; do
  for pod in $(kubectl -n $ns get pod --no-headers 2>/dev/null | grep Running | awk '{print $1}'); do
    m=$(kubectl -n $ns exec $pod -- mount 2>/dev/null | grep -E 'storage.lab|192.168.1.6')
    [ -n "$m" ] && echo "=== $ns/$pod ===" && echo "$m"
  done
done
```

**Every NFS mount must show `192.168.1.61:/cluster/...` (QNAP).** ANY pod showing `192.168.1.60` or `/volume1/cluster` = sticky mount, force-recreate that pod (`kubectl delete pod ...`).

### 11. Trigger Backup Smoke Test

```sh
kubectl -n backup-jobs create job --from=cronjob/postgres-backup smoke-postgres-$(date +%s)
# Wait, check logs
```

Should complete cleanly with rsync to QNAP.

## Known QNAP Quirks

- **NFSv4 sub-path mounts unreliable.** Use NFSv3 (default) for sub-path PVs. Don't add `nfsvers=4` to mountOptions unless mounting the export root.
- **Lock manager not advertised.** Always include `nolock` in mountOptions, OR enable NLM in QNAP NFS Advanced settings (try first; if QTS doesn't expose this toggle on your version, stick with `nolock`).
- **Firmware updates can change MCP transport.** Watch for `.mcp.json` `type: sse` vs `type: http` after firmware updates.
- **SSH allowlist is admin-group only.** Service users for SSH (e.g. `cluster-backup`) must be added to `administrators` group. Use the QTS UI for SSH key deployment (Edit User Properties → SSH Public Keys), not `~/.ssh/authorized_keys` directly — the UI's setting survives firmware updates.

## Rollback Plan

If anything breaks irrecoverably during cutover:

1. Revert the migration commit on main (keeps Synology paths).
2. Flip Pi-hole `storage.lab` back to `192.168.1.60`.
3. Delete the QNAP PVs+PVCs, let Flux recreate Synology ones.
4. Restart Pi-hole pods to reload DNS.

Synology stays online RO during the cutover for exactly this purpose.
