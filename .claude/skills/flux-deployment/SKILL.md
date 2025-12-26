---
name: flux-deployment
description: Deploy and troubleshoot Flux GitOps configurations for Pi K3s cluster. Use when deploying Kustomizations, managing HelmReleases, debugging Flux sync issues, or committing and pushing changes.
allowed-tools: Bash, Read, Grep, Glob, Edit, Write
---

# Flux GitOps Deployment

## When to Use This Skill

Use this skill when:
- Deploying new Flux Kustomizations or HelmReleases
- Troubleshooting failed deployments or sync issues
- Reconciling Flux resources manually
- Adding new services to the GitOps workflow
- Debugging ExternalSecret synchronization issues

## Environment

```bash
export KUBECONFIG=~/dev/pi-cluster/kubeconfig
```

## Key Commands

```bash
# Check overall Flux status
flux get all
flux get kustomizations
flux get helmrelease -A

# Force reconciliation
flux reconcile source git flux-system
flux reconcile kustomization <name>
flux reconcile helmrelease <name> -n <namespace>

# Debug failed resources
kubectl describe kustomization <name> -n flux-system
kubectl logs -n flux-system deploy/kustomize-controller
kubectl logs -n flux-system deploy/helm-controller
kubectl logs -n flux-system deploy/source-controller

# Check Git sync status
flux get source git flux-system
```

## Dependency Chain

The cluster uses this order (defined in `flux-system/infrastructure.yaml`):

1. **external-secrets** → ESO operator + CRDs
2. **external-secrets-config** → ClusterSecretStore (depends on #1)
3. **ingress** → nginx-ingress controller
4. **cert-manager** → cert-manager CRDs + controllers
5. **cert-manager-config** → ClusterIssuers + Cloudflare secret (depends on #2, #4)
6. **pihole** → ExternalSecret + workloads (depends on #2)
7. **monitoring** → kube-prometheus-stack (depends on #2, #3, #5)
8. **uptime-kuma** → Status page (depends on #2, #3, #5)
9. **homepage** → Dashboard (depends on #3, #5)
10. **external-services** → Reverse proxies (depends on #3, #5)
11. **backup-jobs** → Weekly backups (depends on #6, #7, #8)

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
