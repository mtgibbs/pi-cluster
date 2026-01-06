# Spotify Secrets for mtgibbs.xyz

## Status: Pending

## Overview
Add Spotify credentials to enable music stats display on mtgibbs.xyz.

---

## Step 1: 1Password Item (Manual)

Create a new item in the **`pi-cluster`** vault:

| Setting | Value |
|---------|-------|
| **Item name** | `mtgibbs-spotify` |
| **Field 1** | `client-id` = Spotify App Client ID |
| **Field 2** | `client-secret` = Spotify App Client Secret |
| **Field 3** | `refresh-token` = Generated via `scripts/get-refresh-token.js` |

---

## Step 2: Kubernetes Manifests

### New File: `clusters/pi-k3s/mtgibbs-site/external-secret.yaml`

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: mtgibbs-spotify
  namespace: mtgibbs-site
spec:
  refreshInterval: 24h
  secretStoreRef:
    name: onepassword
    kind: ClusterSecretStore
  target:
    name: mtgibbs-spotify
    creationPolicy: Owner
  data:
    - secretKey: SPOTIFY_CLIENT_ID
      remoteRef:
        key: mtgibbs-spotify/client-id
    - secretKey: SPOTIFY_CLIENT_SECRET
      remoteRef:
        key: mtgibbs-spotify/client-secret
    - secretKey: SPOTIFY_REFRESH_TOKEN
      remoteRef:
        key: mtgibbs-spotify/refresh-token
```

### Update: `clusters/pi-k3s/mtgibbs-site/deployment.yaml`

Add `envFrom` to the container spec:

```yaml
containers:
  - name: mtgibbs-site
    # ... existing config ...
    envFrom:
      - secretRef:
          name: mtgibbs-spotify
          optional: true
    env:
      - name: NODE_ENV
        value: "production"
```

### Update: `clusters/pi-k3s/mtgibbs-site/kustomization.yaml`

Add the new resource:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - namespace.yaml
  - deployment.yaml
  - service.yaml
  - ingress.yaml
  - image-automation.yaml
  - external-secret.yaml  # Add this line
```

---

## Corrections from Original Guide

| Original Guide | Corrected |
|----------------|-----------|
| `external-secrets.io/v1beta1` | `external-secrets.io/v1` |
| `onepassword-store` | `onepassword` |
| `property: "SPOTIFY_CLIENT_ID"` | `key: mtgibbs-spotify/client-id` |
| `refreshInterval: "1h"` | `refreshInterval: 24h` |

---

## Deployment Steps

1. Create 1Password item with credentials
2. Apply the Kubernetes manifest changes
3. Commit and push to trigger Flux sync
4. Verify ExternalSecret synced: `kubectl get externalsecrets -n mtgibbs-site`
5. Verify secret created: `kubectl get secrets -n mtgibbs-site`
6. Pod will restart automatically and pick up new env vars
