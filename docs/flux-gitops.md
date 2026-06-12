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
