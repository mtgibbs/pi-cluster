---
name: secrets-management
description: >
  AUTHORING and troubleshooting secrets — how to write an ExternalSecret, structure the 1Password
  item, wire it into a Deployment, debug a failed sync, and bootstrap ESO on a fresh cluster.
  Pairs with `secrets-graph`: load THAT one first to decide *which* credential to use (reuse
  before mint, blast radius); load THIS one to actually write and debug the manifest.
allowed-tools: Bash, Read, Grep, Glob, Edit, Write
---

# Secrets Management with ESO + 1Password

> **Decide before you author.** If the question is "do we already have a credential for this?" or
> "what breaks if I rotate this?", that's `[[secrets-graph]]` + `docs/secrets-map.md` — go there
> first. **Reuse before mint.** This skill assumes the decision is made and you're writing the
> manifest.

## MCP Quick Actions (USE FIRST)

| Operation | MCP Tool |
| :--- | :--- |
| All ExternalSecrets sync status | `get_secrets_status` |
| Force ExternalSecret resync | `refresh_secret(namespace, name)` |

## When to Use This Skill

Use this skill when:
- Creating new ExternalSecrets for applications
- Troubleshooting secret synchronization issues
- Setting up 1Password items for new services
- Bootstrapping the cluster secrets infrastructure
- Verifying secret sync status

## Environment — where you're running matters

**In the coding-harness container there is no `kubectl`, and no `op`/1Password CLI.** You can author
the ExternalSecret manifest (Edit/Write + PR) and check sync via `get_secrets_status` /
`refresh_secret`. You **cannot** create or read the 1Password item itself — that needs `op` from the
laptop. So the usual split is: you write the manifest and name the exact `op://` path and fields
required; the user (or laptop agent) mints the item. Say which half you did.

## Architecture

```
1Password Cloud (pi-cluster vault)
        │
        ▼
ClusterSecretStore (onepassword)
        │
        ▼
ExternalSecret (per namespace)
        │
        ▼
Kubernetes Secret (created automatically)
```

## Configuration

### ClusterSecretStore
- **Name**: `onepassword`
- **Provider**: `onepasswordSDK` (service account, no Connect server)
- **Vault**: `pi-cluster`
- **Auth**: Service account token in `external-secrets/onepassword-service-account`

### 1Password Items Required

| Item | Fields | Used By |
|------|--------|---------|
| `pihole` | `password` | Pi-hole admin |
| `grafana` | `admin-user`, `admin-password` | Grafana login |
| `cloudflare` | `api-token` | Let's Encrypt DNS-01 |
| `uptime-kuma` | `username`, `password` | Uptime Kuma + AutoKuma |
| `synology_backup` | `private key` | Backup SSH key |

## Creating a New ExternalSecret

### 1. Create 1Password Item

In the `pi-cluster` vault:
- Create new item with required fields
- Use descriptive field names (will be referenced in ExternalSecret)

### 2. Create ExternalSecret Manifest

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: <app>-secret
  namespace: <namespace>
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword
  target:
    name: <app>-secret        # K8s secret name created
    creationPolicy: Owner
  data:
    - secretKey: PASSWORD      # Key in K8s secret
      remoteRef:
        key: <1password-item>/<field-name>   # e.g., myapp/password
```

### 3. Reference in Deployment

```yaml
env:
  - name: PASSWORD
    valueFrom:
      secretKeyRef:
        name: <app>-secret
        key: PASSWORD
```

## Troubleshooting

### Check ClusterSecretStore Status
```bash
kubectl get clustersecretstores
kubectl describe clustersecretstore onepassword
```

### Check ExternalSecret Status
```bash
kubectl get externalsecrets -A
kubectl describe externalsecret <name> -n <namespace>

# Status should show:
# - SecretSynced: True
# - refreshTime: Recent timestamp
```

### Check ESO Operator
```bash
kubectl get pods -n external-secrets
kubectl logs -n external-secrets deploy/external-secrets
```

### Common Errors

**"SecretStore not found"**
- ClusterSecretStore not ready
- Check onepassword-service-account secret exists

**"item not found"**
- 1Password item name doesn't match
- Check vault name (must be `pi-cluster`)
- Verify service account has access to vault

**"field not found"**
- Field name in 1Password doesn't match remoteRef.key
- Check for spaces vs underscores (e.g., "private key" vs "private_key")

**"unauthorized"**
- Service account token expired or invalid
- Re-create onepassword-service-account secret

**"wasm error: out of bounds memory access" in `init_client()`** — the whole store dies
- Seen 2026-08-11: `ClusterSecretStore/onepassword` stopped validating and **53 of 56
  ExternalSecrets** failed with `ClusterSecretStore "onepassword" is not ready`.
- The `onepasswordSDK` provider runs the 1Password SDK as an **Extism/WASM plugin**. This
  trap is the WASM host failing to allocate, *not* an auth problem — an expired or wrong
  token gives `unauthorized` instead.
- **It is invisible.** Failing ExternalSecrets keep their last-synced value, so every
  materialised Secret stays intact and every workload keeps running. Rotation is dead and
  no NEW secret can be created, but nothing looks broken. The pod reports `Running 1/1`
  with **0 restarts**.
- **Fix: restart the controller.**
  ```bash
  kubectl -n external-secrets rollout restart deploy/external-secrets
  kubectl -n external-secrets get clustersecretstore onepassword -w
  ```
  **A retry loop is not a restart.** ESO retried client creation continuously for 40 hours
  and never recovered — retrying inside the same process does not reset the WASM host
  memory. Don't read the persistent failures as evidence a restart won't help; it's the
  opposite.
- If it fails **identically** after a restart, suspect the bootstrap token
  (`external-secrets/onepassword-service-account`, key `token`) — a malformed value can
  panic the SDK inside the sandbox and present the same way. Recreate it (see
  Bootstrapping below).
- Full analysis: `docs/incidents/2026-08-11-eso-onepassword-wasm.md`

## Bootstrapping (Fresh Cluster)

The 1Password service account token must be created manually:

```bash
# Get token from 1Password CLI
op read "op://Development - Private/pi-cluster-operator/credential"

# Create secret
kubectl create namespace external-secrets
kubectl create secret generic onepassword-service-account \
  --namespace=external-secrets \
  --from-literal=token="<token>"
```

## Best Practices

1. **One ExternalSecret per app**: Keeps secrets scoped appropriately
2. **Use secretStoreRef.kind: ClusterSecretStore**: Allows cross-namespace access
3. **Set refreshInterval**: 1h is reasonable, shorter for frequently rotated
4. **Use creationPolicy: Owner**: Secret deleted when ExternalSecret deleted
5. **Match field names**: Be consistent between 1Password and K8s
6. **Verify sync**: Always check `kubectl get externalsecrets` after deployment
