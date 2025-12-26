---
name: add-service
description: Scaffold and deploy a new service to the Pi K3s cluster. Use when adding new applications, creating the full GitOps structure, or setting up ingress and secrets for new services.
allowed-tools: Bash, Read, Grep, Glob, Edit, Write
---

# Add New Service to Cluster

## When to Use This Skill

Use this skill when:
- Adding a completely new application to the cluster
- Creating the full GitOps structure for a service
- Setting up ingress with TLS for a new service
- Integrating a service with 1Password secrets
- Adding a service to Homepage dashboard

## Service Checklist

- [ ] Create service directory structure
- [ ] Create namespace.yaml
- [ ] Create deployment.yaml with resource limits
- [ ] Create service.yaml
- [ ] Create ingress.yaml with TLS
- [ ] Create external-secret.yaml (if secrets needed)
- [ ] Create kustomization.yaml
- [ ] Add to flux-system/infrastructure.yaml
- [ ] Add to Homepage dashboard
- [ ] Add monitor to AutoKuma (if applicable)
- [ ] Commit and deploy

## Directory Structure

```
clusters/pi-k3s/<service-name>/
├── kustomization.yaml
├── namespace.yaml
├── deployment.yaml
├── service.yaml
├── ingress.yaml
└── external-secret.yaml  (if secrets needed)
```

## Template Files

### namespace.yaml
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: <service-name>
```

### deployment.yaml
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: <service-name>
  namespace: <service-name>
spec:
  replicas: 1
  selector:
    matchLabels:
      app: <service-name>
  template:
    metadata:
      labels:
        app: <service-name>
    spec:
      containers:
        - name: <service-name>
          image: <image>:<tag>
          ports:
            - containerPort: <port>
          resources:
            requests:
              memory: "64Mi"
              cpu: "50m"
            limits:
              memory: "256Mi"
              cpu: "200m"
          # Add env, volumeMounts as needed
```

### service.yaml
```yaml
apiVersion: v1
kind: Service
metadata:
  name: <service-name>
  namespace: <service-name>
spec:
  selector:
    app: <service-name>
  ports:
    - port: 80
      targetPort: <container-port>
```

### ingress.yaml
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: <service-name>
  namespace: <service-name>
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - <subdomain>.lab.mtgibbs.dev
      secretName: <service-name>-tls
  rules:
    - host: <subdomain>.lab.mtgibbs.dev
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: <service-name>
                port:
                  number: 80
```

### external-secret.yaml
```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: <service-name>-secret
  namespace: <service-name>
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword
  target:
    name: <service-name>-secret
    creationPolicy: Owner
  data:
    - secretKey: PASSWORD
      remoteRef:
        key: <1password-item>/password
```

### kustomization.yaml
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: <service-name>
resources:
  - namespace.yaml
  - external-secret.yaml  # if needed
  - deployment.yaml
  - service.yaml
  - ingress.yaml
```

## Add to Flux

Add to `clusters/pi-k3s/flux-system/infrastructure.yaml`:

```yaml
---
# N. <Service Name> - <brief description>
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: <service-name>
  namespace: flux-system
spec:
  dependsOn:
    - name: external-secrets-config  # if using secrets
    - name: cert-manager-config      # if using ingress
  interval: 10m
  path: ./clusters/pi-k3s/<service-name>
  prune: true
  sourceRef:
    kind: GitRepository
    name: flux-system
  wait: true
  timeout: 5m
```

## Add to Homepage

Edit `clusters/pi-k3s/homepage/configmap.yaml`:

```yaml
services.yaml: |
  - <Category>:
      - <Service Name>:
          icon: <icon>.png
          href: https://<subdomain>.lab.mtgibbs.dev
          description: <Brief description>
          siteMonitor: https://<subdomain>.lab.mtgibbs.dev
```

## Add AutoKuma Monitor

Edit `clusters/pi-k3s/uptime-kuma/autokuma-monitors.yaml`:

```yaml
data:
  <service-name>.json: |
    {
      "monitor_name": "<Service Name>",
      "monitor_type": "http",
      "monitor_url": "https://<subdomain>.lab.mtgibbs.dev/",
      "monitor_interval": 60,
      "monitor_maxretries": 3
    }
```

## Resource Limits Guide

Pi has 8GB RAM. Be conservative:

| Workload Type | Memory Request | Memory Limit |
|---------------|----------------|--------------|
| Tiny (static sites) | 32Mi | 128Mi |
| Small (simple apps) | 64Mi | 256Mi |
| Medium (APIs, DBs) | 128Mi | 512Mi |
| Large (Prometheus) | 256Mi | 1Gi |

## Deployment Steps

1. Create all files in `clusters/pi-k3s/<service-name>/`
2. Add Kustomization to `infrastructure.yaml`
3. Add to Homepage (optional)
4. Add AutoKuma monitor (optional)
5. Create 1Password item if secrets needed
6. Commit and push
7. Reconcile: `flux reconcile source git flux-system`
8. Verify: `kubectl get pods -n <service-name>`
