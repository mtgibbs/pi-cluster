# Homelab MCP - Cluster Integration Plan

After the `homelab-mcp` repo is complete with CI pushing to GHCR, these changes are needed in `pi-cluster` to deploy it.

## Prerequisites
- [ ] `homelab-mcp` repo created and scaffolded
- [ ] CI/CD working, pushing to `ghcr.io/mtgibbs/homelab-mcp:latest`
- [ ] 1Password items created:
  - `synology-mcp-ssh` (SSH private key for NAS)
  - `mcp-homelab-api-key` (API key for SSE auth)
  - `jellyfin-api-key` (already exists, reuse)

## 1. Create Namespace + RBAC

**File: `clusters/pi-k3s/mcp-homelab/namespace.yaml`**
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: mcp-homelab
```

**File: `clusters/pi-k3s/mcp-homelab/serviceaccount.yaml`**
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: mcp-homelab
  namespace: mcp-homelab
```

**File: `clusters/pi-k3s/mcp-homelab/clusterrole.yaml`**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: mcp-homelab
rules:
  # Read-only: Core resources
  - apiGroups: [""]
    resources: [pods, services, nodes, events, configmaps, persistentvolumeclaims, namespaces]
    verbs: [get, list, watch]

  # Read-only: Apps
  - apiGroups: ["apps"]
    resources: [deployments, statefulsets, daemonsets, replicasets]
    verbs: [get, list, watch]

  # Read-only: Flux
  - apiGroups: ["kustomize.toolkit.fluxcd.io"]
    resources: [kustomizations]
    verbs: [get, list, watch]
  - apiGroups: ["helm.toolkit.fluxcd.io"]
    resources: [helmreleases]
    verbs: [get, list, watch]
  - apiGroups: ["source.toolkit.fluxcd.io"]
    resources: [gitrepositories, helmrepositories, helmcharts]
    verbs: [get, list, watch]
  - apiGroups: ["image.toolkit.fluxcd.io"]
    resources: [imagerepositories, imagepolicies, imageupdateautomations]
    verbs: [get, list, watch]

  # Read-only: Cert-manager
  - apiGroups: ["cert-manager.io"]
    resources: [certificates, certificaterequests, issuers, clusterissuers, challenges, orders]
    verbs: [get, list, watch]

  # Read-only: External Secrets
  - apiGroups: ["external-secrets.io"]
    resources: [externalsecrets, clustersecretstores, secretstores]
    verbs: [get, list, watch]

  # Read-only: Networking
  - apiGroups: ["networking.k8s.io"]
    resources: [ingresses, ingressclasses]
    verbs: [get, list, watch]

  # Read-only: Tailscale
  - apiGroups: ["tailscale.com"]
    resources: [connectors, proxyclasses]
    verbs: [get, list, watch]

  # Read-only: Batch
  - apiGroups: ["batch"]
    resources: [jobs, cronjobs]
    verbs: [get, list, watch]

  # Read-only: Metrics
  - apiGroups: ["metrics.k8s.io"]
    resources: [nodes, pods]
    verbs: [get, list]

  # Action: Restart deployments (patch for rollout)
  - apiGroups: ["apps"]
    resources: [deployments]
    verbs: [patch]

  # Action: Trigger Flux reconcile
  - apiGroups: ["kustomize.toolkit.fluxcd.io"]
    resources: [kustomizations]
    verbs: [patch]
  - apiGroups: ["helm.toolkit.fluxcd.io"]
    resources: [helmreleases]
    verbs: [patch]
  - apiGroups: ["source.toolkit.fluxcd.io"]
    resources: [gitrepositories]
    verbs: [patch]

  # Action: Force ExternalSecret refresh
  - apiGroups: ["external-secrets.io"]
    resources: [externalsecrets]
    verbs: [patch]

  # Action: Create manual backup jobs
  - apiGroups: ["batch"]
    resources: [jobs]
    verbs: [create]

  # Action: Exec into Jellyfin pod for metadata fix
  - apiGroups: [""]
    resources: [pods/exec]
    verbs: [create]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: mcp-homelab
subjects:
  - kind: ServiceAccount
    name: mcp-homelab
    namespace: mcp-homelab
roleRef:
  kind: ClusterRole
  name: mcp-homelab
  apiGroup: rbac.authorization.k8s.io
```

## 2. Create ExternalSecrets

**File: `clusters/pi-k3s/mcp-homelab/externalsecret.yaml`**
```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: synology-ssh-key
  namespace: mcp-homelab
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword
  target:
    name: synology-ssh-key
  data:
    - secretKey: id_rsa
      remoteRef:
        key: synology-mcp-ssh
        property: private-key
---
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: mcp-api-key
  namespace: mcp-homelab
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword
  target:
    name: mcp-api-key
  data:
    - secretKey: api-key
      remoteRef:
        key: mcp-homelab-api-key
        property: api-key
---
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: jellyfin-api-key
  namespace: mcp-homelab
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword
  target:
    name: jellyfin-api-key
  data:
    - secretKey: api-key
      remoteRef:
        key: jellyfin-api-key
        property: api-key
```

## 3. Create Deployment

**File: `clusters/pi-k3s/mcp-homelab/deployment.yaml`**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-homelab
  namespace: mcp-homelab
spec:
  replicas: 1
  selector:
    matchLabels:
      app: mcp-homelab
  template:
    metadata:
      labels:
        app: mcp-homelab
    spec:
      serviceAccountName: mcp-homelab
      containers:
        - name: mcp-homelab
          image: ghcr.io/mtgibbs/homelab-mcp:latest
          ports:
            - containerPort: 3000
              name: sse
          env:
            - name: MCP_TRANSPORT
              value: "sse"
            - name: MCP_PORT
              value: "3000"
            - name: SYNOLOGY_HOST
              value: "192.168.1.60"
            - name: SYNOLOGY_USER
              value: "mcp"
            - name: MCP_API_KEY
              valueFrom:
                secretKeyRef:
                  name: mcp-api-key
                  key: api-key
            - name: JELLYFIN_API_KEY
              valueFrom:
                secretKeyRef:
                  name: jellyfin-api-key
                  key: api-key
          volumeMounts:
            - name: ssh-key
              mountPath: /secrets/ssh
              readOnly: true
          resources:
            requests:
              memory: "64Mi"
              cpu: "50m"
            limits:
              memory: "256Mi"
              cpu: "500m"
          livenessProbe:
            httpGet:
              path: /health
              port: 3000
            initialDelaySeconds: 10
            periodSeconds: 30
          readinessProbe:
            httpGet:
              path: /health
              port: 3000
            initialDelaySeconds: 5
            periodSeconds: 10
      volumes:
        - name: ssh-key
          secret:
            secretName: synology-ssh-key
            defaultMode: 0400
```

## 4. Create Service + Ingress

**File: `clusters/pi-k3s/mcp-homelab/service.yaml`**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: mcp-homelab
  namespace: mcp-homelab
spec:
  selector:
    app: mcp-homelab
  ports:
    - port: 3000
      targetPort: 3000
      name: sse
```

**File: `clusters/pi-k3s/mcp-homelab/ingress.yaml`**
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: mcp-homelab
  namespace: mcp-homelab
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - mcp.lab.mtgibbs.dev
      secretName: mcp-homelab-tls
  rules:
    - host: mcp.lab.mtgibbs.dev
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: mcp-homelab
                port:
                  number: 3000
```

## 5. Create Kustomization

**File: `clusters/pi-k3s/mcp-homelab/kustomization.yaml`**
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: mcp-homelab
resources:
  - namespace.yaml
  - serviceaccount.yaml
  - clusterrole.yaml
  - externalsecret.yaml
  - deployment.yaml
  - service.yaml
  - ingress.yaml
```

## 6. Add Flux Kustomization

**File: `clusters/pi-k3s/flux-system/mcp-homelab.yaml`**
```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: mcp-homelab
  namespace: flux-system
spec:
  interval: 10m
  path: ./clusters/pi-k3s/mcp-homelab
  prune: true
  sourceRef:
    kind: GitRepository
    name: flux-system
  dependsOn:
    - name: external-secrets-config
    - name: ingress-nginx
    - name: cert-manager
```

## 7. Add DNS Record

In Cloudflare (or Pi-hole custom DNS):
```
mcp.lab.mtgibbs.dev → 192.168.1.55
```

## 8. Configure Claude Desktop

**File: `~/Library/Application Support/Claude/claude_desktop_config.json`**
```json
{
  "mcpServers": {
    "homelab": {
      "transport": "sse",
      "url": "https://mcp.lab.mtgibbs.dev/sse",
      "headers": {
        "X-API-Key": "<get-from-1password>"
      }
    }
  }
}
```

## 9. Create 1Password Items

Before deploying, create these items in `pi-cluster` vault:

### synology-mcp-ssh
- Type: SSH Key or Secure Note
- Field `private-key`: SSH private key for user `mcp` on Synology
- Generate new key: `ssh-keygen -t ed25519 -f mcp-synology -C "mcp-homelab"`
- Add public key to Synology: `ssh-copy-id -i mcp-synology.pub mcp@192.168.1.60`

### mcp-homelab-api-key
- Type: API Credential or Password
- Field `api-key`: Generate with `openssl rand -hex 32`

## 10. Synology User Setup

Create limited user on Synology for MCP SSH access:
```bash
# On Synology (as admin)
synouser --add mcp "" "MCP Homelab" 0 "" 0

# Or via DSM UI:
# Control Panel → User & Group → Create
# - Username: mcp
# - No admin privileges
# - Only access to /volume1/cluster/media (for touch operations)
```

## Deployment Order

1. Create 1Password items
2. Create Synology user + add SSH key
3. Add DNS record
4. Apply Flux Kustomization to pi-cluster repo
5. Push and reconcile: `/deploy`
6. Verify pod running: `kubectl get pods -n mcp-homelab`
7. Verify ExternalSecrets synced: `kubectl get externalsecrets -n mcp-homelab`
8. Test SSE endpoint: `curl -H "X-API-Key: <key>" https://mcp.lab.mtgibbs.dev/health`
9. Configure Claude Desktop
10. Test from Claude Desktop: "What's the cluster health?"

## Verification Commands

```bash
# Check deployment
kubectl get all -n mcp-homelab

# Check RBAC works
kubectl auth can-i list pods --as=system:serviceaccount:mcp-homelab:mcp-homelab -A
kubectl auth can-i delete pods --as=system:serviceaccount:mcp-homelab:mcp-homelab -A  # Should be "no"

# Check secrets synced
kubectl get externalsecrets -n mcp-homelab

# Test SSE endpoint
curl -H "X-API-Key: $(op read 'op://pi-cluster/mcp-homelab-api-key/api-key')" \
  https://mcp.lab.mtgibbs.dev/health

# Check logs
kubectl logs -n mcp-homelab -l app=mcp-homelab -f
```
