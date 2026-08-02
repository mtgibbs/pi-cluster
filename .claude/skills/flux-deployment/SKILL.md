---
name: flux-deployment
description: Deploy and troubleshoot Flux GitOps configurations for Pi K3s cluster. Use when deploying Kustomizations, managing HelmReleases, debugging Flux sync issues, or committing and pushing changes.
allowed-tools: Bash, Read, Grep, Glob, Edit, Write
---

# Flux GitOps Deployment

## MCP Quick Actions (USE FIRST)

| Operation | MCP Tool |
| :--- | :--- |
| Flux sync status (Kustomizations + HelmReleases) | `get_flux_status` |
| Force reconciliation | `reconcile_flux(resource="type/namespace/name")` |
| ExternalSecret sync status | `get_secrets_status` |
| Force secret resync | `refresh_secret(namespace, name)` |

## When to Use This Skill

Use this skill when:
- Deploying new Flux Kustomizations or HelmReleases
- Troubleshooting failed deployments or sync issues
- Reconciling Flux resources manually
- Adding new services to the GitOps workflow
- Debugging ExternalSecret synchronization issues

## Environment — where you're running matters

**In the coding-harness container there is no `flux` or `kubectl` CLI and no kubeconfig.** Use the
MCP table above; that covers status and reconcile, which is most of this skill. The `flux`/`kubectl`
snippets below are **reference for the laptop path** (or for telling the user what to run) — not
commands to attempt from here. Don't `export KUBECONFIG=...`; there's no file to point at.

## Key Commands (laptop path)

```bash
# Check overall Flux status          [MCP: get_flux_status]
flux get all
flux get kustomizations
flux get helmrelease -A

# Force reconciliation               [MCP: reconcile_flux]
flux reconcile source git flux-system
flux reconcile kustomization <name>
flux reconcile helmrelease <name> -n <namespace>

# Debug failed resources             [no MCP equivalent — laptop only]
kubectl describe kustomization <name> -n flux-system
kubectl logs -n flux-system deploy/kustomize-controller
kubectl logs -n flux-system deploy/helm-controller
kubectl logs -n flux-system deploy/source-controller

# Check Git sync status              [MCP: get_flux_status]
flux get source git flux-system
```

## Dependency Chain

**Single source of truth: [`docs/flux-gitops.md`](../../../docs/flux-gitops.md).** The chain used to
be duplicated here and drifted out of date; read it there. The generated deploy-order DAG in
[`docs/domain-map.md`](../../../docs/domain-map.md) is derived from the actual `dependsOn` fields in
`flux-system/infrastructure.yaml`, so it's the authoritative version — this skill deliberately no
longer carries a hand-maintained copy.

That doc also holds the deep gotchas this skill doesn't repeat: **reconcile the source before the
Kustomization**, which PV fields are mutable vs immutable (`mountOptions` yes, `nfs.server`/`nfs.path`
no), the Kustomize namespace-transformer rule, and why `main` is force-push-guarded but not PR-required.

## Adding New Service to Flux

1. Create directory: `clusters/pi-k3s/<service-name>/`
2. Add manifests: namespace, deployment, service, ingress, etc.
3. Create `kustomization.yaml` listing all resources
4. Add Kustomization to `flux-system/infrastructure.yaml` with proper `dependsOn`
5. Commit and push
6. Reconcile: `flux reconcile source git flux-system`

## Common Issues

### Kustomization Stuck "Not Ready"
```bash
# Check events
kubectl describe kustomization <name> -n flux-system

# Common causes:
# - Missing dependencies (check dependsOn)
# - Invalid YAML (kustomize build locally to test)
# - Missing namespace (add namespace.yaml to resources)
```

### HelmRelease Failing
```bash
# Check release status
kubectl describe helmrelease <name> -n <namespace>
helm history <name> -n <namespace>

# Common causes:
# - Invalid values (check HelmRelease spec.values)
# - Missing CRDs (check if operator deployed first)
# - Resource conflicts (check for existing resources)
```

### ExternalSecret Not Syncing
```bash
# Check ClusterSecretStore
kubectl get clustersecretstores
kubectl describe clustersecretstore onepassword

# Check ExternalSecret
kubectl get externalsecrets -A
kubectl describe externalsecret <name> -n <namespace>

# Check ESO logs
kubectl logs -n external-secrets deploy/external-secrets
```

### Git Not Syncing
```bash
# Check source status
flux get source git flux-system

# Force refresh
flux reconcile source git flux-system

# Check for auth issues
kubectl logs -n flux-system deploy/source-controller
```

## Deployment Checklist

- [ ] All YAML files valid (no syntax errors)
- [ ] kustomization.yaml lists all resources
- [ ] Namespace exists or is created first
- [ ] Dependencies in infrastructure.yaml are correct
- [ ] ExternalSecrets reference existing 1Password items
- [ ] Ingress uses correct host and TLS secret name
- [ ] Resource limits appropriate for Pi (8GB RAM total)
