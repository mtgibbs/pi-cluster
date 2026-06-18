# Flux GitOps Reference

## Dependency Chain

Kustomizations are applied in order via `dependsOn`:

```
1.  external-secrets        → Installs ESO operator + CRDs
2.  external-secrets-config → Creates ClusterSecretStore (needs CRDs)
3.  ingress                 → nginx-ingress controller
4.  cert-manager            → Installs cert-manager CRDs + controllers
5.  cert-manager-config     → Creates ClusterIssuers + Cloudflare secret (needs cert-manager + ESO)
6.  pihole                  → Creates ExternalSecret + workloads (needs SecretStore)
7.  monitoring              → kube-prometheus-stack + Grafana (needs secrets, ingress, certs)
8.  uptime-kuma             → Status page (needs secrets, ingress, certs)
9.  homepage                → Unified dashboard (needs ingress, certs)
10. external-services       → Reverse proxies for home infrastructure (needs ingress, certs)
11. flux-notifications      → Discord deployment notifications (needs ESO)
12. backup-jobs             → PVC + PostgreSQL backups (needs ESO, workloads)
13. immich                  → Photo management (needs ESO, ingress, certs)
14. jellyfin                → Media server (needs ingress, certs)
15. mtgibbs-site            → Personal website (needs ingress, certs)
16. tailscale               → Tailscale Operator (needs ESO for OAuth credentials)
17. tailscale-config        → Connector + ProxyClass CRDs (needs tailscale operator running)
```

## Deploying changes — reconcile the SOURCE first (gotcha)

A Kustomization reconcile applies against whatever revision the **GitRepository source**
currently holds. Pushing a commit does **not** instantly update the source — Flux polls it on
an interval. So if you push and immediately reconcile only the Kustomization, Flux re-applies
the **old** revision (silently — the Kustomization still goes `Ready`).

**Always reconcile the source before the Kustomization:**
```bash
flux reconcile source git flux-system        # fetch the new commit FIRST
flux reconcile kustomization homepage         # then apply it
```
The `/deploy` slash command does this in order. The `mcp__homelab__reconcile_flux` tool only
pokes **Kustomizations**, not the git source — when deploying via MCP, force the source with
the `flux` CLI first (or wait for the next poll), or you'll deploy a stale revision. Confirm by
checking the applied revision matches your commit (`get_flux_status` → `Applied revision`).

> For ConfigMap-mounted apps (homepage, autokuma) there's a *second* step: the new ConfigMap
> doesn't reach the pod until it restarts (an initContainer copies it at startup). After the
> Kustomization applies, `restart_deployment` the workload. Verify the served artifact actually
> changed (e.g. byte size of `/api/config/custom.css`), not just that the pod is Ready.

## Changing PV fields: `mountOptions` (mutable) vs `nfs.server`/`nfs.path` (immutable)

**`mountOptions` is MUTABLE** — verified 2026-06-18 on `jellyfin-video-nfs` (`timeo=600`→`150`).
Editing it in git and reconciling **patches the bound PV in place** (Flux applies cleanly, the
Kustomization stays Ready). It only goes **live** once the consumer **remounts**, so the whole
procedure is just edit → push → bounce the consumer:
```bash
kubectl -n <ns> rollout restart deploy/<app>     # e.g. -n jellyfin deploy/jellyfin
```
No PV delete, no PVC dance, no deadlock.

**Only `nfs.server` and `nfs.path` (the volume *source*) are IMMUTABLE.** Editing those is rejected
by the API → the Kustomization goes NotReady → *those* need the full **delete + recreate** of the PV
*and* its PVC. (The 2026-06-16 "mount-options" deadlock was really an `nfs.server` change: commit #16
hardcoded the QNAP IP **and** tweaked options in one go, and it was the **server** change that got
rejected — not the options.) For an NFS PV that's just a pointer (`Retain` policy, data lives on the
NAS), recreate is safe — **no data loss**. The swap for those source-field changes — keep the
Kustomization SUSPENDED the whole time:

> **The trap (learned 2026-06-16, the media-PV mount-options swap):** if the Kustomization is
> *active* during the swap, Flux re-applies the Deployments (`replicas:1`) and re-spawns
> consumer pods **while the PVC is mid-delete**. Those Pending pods hold the PVC's
> `pvc-protection` finalizer → the PVC sticks in `Terminating` → the new PVC can't be created →
> pods stay Pending. **Deadlock.**

**Correct procedure — keep the Kustomization SUSPENDED the entire time:**
```bash
K=media; NS=media; APPS="sabnzbd qbittorrent radarr sonarr lidarr readarr lazylibrarian calibre-web bazarr"
flux suspend kustomization $K                                  # 1. freeze — stops pod re-spawns
gh pr merge <PR> --squash                                     # 2. land the new manifest
kubectl -n $NS scale deploy $APPS --replicas=0                # 3. drop ALL pod references
kubectl wait --for=delete pod -n $NS -l '<selector>' --timeout=120s
kubectl -n $NS delete pvc <pvcs...> && kubectl delete pv <pvs...>   # 4. PVCs first, then PVs
flux reconcile source git flux-system
flux resume kustomization $K && flux reconcile kustomization $K     # 5. ONLY NOW resume → recreates PV/PVC + scales up
# 6. verify: PVs Bound w/ new opts, pods Running (Running ⇒ mounted OK), a RW write succeeds
```

**If a PVC is already stuck `Terminating`** (you resumed too early): scale its consumers to 0,
then force-clear the finalizer — safe for an NFS-pointer PVC (no data on it):
```bash
kubectl patch pvc <name> -n <ns> -p '{"metadata":{"finalizers":null}}' --type=merge
```
Then delete the now-`Released` PV (`Retain` leaves a stale `claimRef` that blocks rebinding) and
let Flux recreate both. See `.claude/skills/media-services/SKILL.md` for the NFS mount-options
rationale (soft for read-only, hard for read-write).

## Kustomize Best Practices

### Namespace Transformer (IMPORTANT)

**Never use `namespace:` in kustomization.yaml when deploying HelmReleases.**

When you set `namespace: <name>` in a `kustomization.yaml`, Kustomize applies a namespace transformer that overrides ALL resources, ignoring their declared namespaces.

**Why it matters for Flux:**
- `HelmRepository` must be in `flux-system` (where source-controller runs)
- `HelmRelease` can be in any namespace, but references `HelmRepository` in `flux-system`
- If `HelmRepository` gets namespace-transformed, Flux can't find it

**Correct pattern:**
```yaml
# GOOD - Let resources declare their own namespaces
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
# Don't set namespace here - resources have explicit namespaces
resources:
  - namespace.yaml      # Creates 'myapp' namespace
  - helmrelease.yaml    # Contains HelmRepo (flux-system) + HelmRelease (myapp)
```

## Branch protection — force-push guard only (intentional)

`main` is protected against **force-pushes and branch deletion** (`enforce_admins: true`, so it
applies to the owner too) — but has **no required-PR, required-review, or required-status-check**
rule. This is deliberate.

**Why force-push-only, not full protection:** Flux `ImageUpdateAutomation` (mtgibbs-site,
mcp-homelab, review-hub, local-llm-mcp, kiwix-mcp, private-exit-node) commits image-tag bumps
**directly to `main`** as the Flux bot. A required-PR rule would reject those bot pushes and
silently halt image automation. Force-push/deletion blocking does **not** interfere — those are
normal fast-forward pushes — so the guard stops history-destroying force-pushes without any PR
friction and without breaking Flux. (Flux *reading* from `main` is unrelated to branch
protection; it's the *write-back* image automation that constrains the choice.)

**Manage it:**
```bash
# View current protection
gh api repos/mtgibbs/pi-cluster/branches/main/protection

# Temporarily lift (to intentionally force-push), then re-apply afterward
gh api -X DELETE repos/mtgibbs/pi-cluster/branches/main/protection

# (Re-)apply the guard
gh api -X PUT repos/mtgibbs/pi-cluster/branches/main/protection --input - <<'JSON'
{ "required_status_checks": null, "enforce_admins": true,
  "required_pull_request_reviews": null, "restrictions": null,
  "allow_force_pushes": false, "allow_deletions": false }
JSON
```

**Backstop:** the weekly `git-mirror-backup` job mirrors this repo to the QNAP, so even a
worst-case history loss has a recovery copy.

Applied 2026-06-15.
