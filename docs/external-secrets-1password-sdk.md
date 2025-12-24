# External Secrets Operator - 1Password SDK Provider

Reference documentation for configuring ESO with 1Password Service Accounts.

Source: https://external-secrets.io/latest/provider/1password-sdk/

## Overview

The 1Password SDK provider enables External Secrets Operator to integrate with 1Password
**without requiring a Connect Server**. Uses service account tokens directly.

**Critical Requirement:** Documents must have unique label names across the vault,
otherwise throws error: "found multiple labels with the same key".

## SecretStore / ClusterSecretStore Configuration

Stores are **vault-specific** - a single ExternalSecret cannot access multiple vaults.

### SecretStore (namespace-scoped)

```yaml
apiVersion: external-secrets.io/v1   # ESO 1.x uses v1
kind: SecretStore
metadata:
  name: onepassword-sdk
spec:
  provider:
    onepasswordSDK:
      vault: my-vault-name        # The 1Password vault name
      auth:
        serviceAccountSecretRef:
          name: op-service-account-token   # K8s secret containing token
          key: token                        # Key within the secret
```

### ClusterSecretStore (cluster-scoped)

```yaml
apiVersion: external-secrets.io/v1   # ESO 1.x uses v1
kind: ClusterSecretStore
metadata:
  name: onepassword-sdk
spec:
  provider:
    onepasswordSDK:
      vault: my-vault-name
      auth:
        serviceAccountSecretRef:
          name: op-service-account-token
          namespace: external-secrets    # Required for ClusterSecretStore
          key: token
```

## ExternalSecret Configuration

Secret references use format: `<item>/[section/]<field>`

For OTP fields: `<item>/[section/]one-time password?attribute=otp`

```yaml
apiVersion: external-secrets.io/v1   # ESO 1.x uses v1
kind: ExternalSecret
metadata:
  name: my-secret
  namespace: my-namespace
spec:
  secretStoreRef:
    kind: ClusterSecretStore    # or SecretStore
    name: onepassword-sdk
  target:
    name: my-k8s-secret         # Name of K8s secret to create
    creationPolicy: Owner       # ESO owns the secret lifecycle
  data:
    - secretKey: PASSWORD       # Key in the K8s secret
      remoteRef:
        key: my-item/password   # 1Password item/field reference
```

## Multiple Fields Example

```yaml
apiVersion: external-secrets.io/v1   # ESO 1.x uses v1
kind: ExternalSecret
metadata:
  name: database-credentials
spec:
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword-sdk
  target:
    name: db-secret
  data:
    - secretKey: DB_USER
      remoteRef:
        key: database/username
    - secretKey: DB_PASS
      remoteRef:
        key: database/password
    - secretKey: DB_HOST
      remoteRef:
        key: database/server
```

## PushSecret (Write secrets TO 1Password)

```yaml
apiVersion: external-secrets.io/v1alpha1
kind: PushSecret
metadata:
  name: pushsecret-example
spec:
  deletionPolicy: Delete        # Delete from 1Password when PushSecret deleted
  refreshInterval: 1h
  secretStoreRefs:
    - name: onepassword-sdk
      kind: SecretStore
  selector:
    secret:
      name: source-secret       # K8s secret to push
  data:
    - match:
        secretKey: my-key       # Key in K8s secret
      remoteRef:
        remoteKey: 1pw-item     # 1Password item name
        property: password      # Field name in 1Password
```

## Key Differences from Connect Provider

| Feature | SDK Provider | Connect Provider |
|---------|-------------|------------------|
| Provider name | `onepasswordSDK` | `onepassword` |
| Auth field | `serviceAccountSecretRef` | `connectTokenSecretRef` |
| Connect host | Not needed | Required (`connectHost`) |
| Infrastructure | None | Requires Connect server |
| Key format | `item/field` | Uses `key` + `property` |

## Troubleshooting

1. **"found multiple labels with the same key"** - Ensure unique item names in vault
2. **Auth errors** - Verify service account has access to the specified vault
3. **Field not found** - Check item/field path format: `item-name/field-name`
