# Log Drain & Hardware Expansion Plan

## Overview

This plan covers expanding the Pi K3s cluster with additional Pi 5 nodes and implementing a log aggregation system for Heroku applications using Cloudflare Tunnels.

**Status**: Draft - pending hardware acquisition

## Phase 1: Hardware Expansion

### Shopping List

| Item | Qty | Purpose | Approx Cost |
|------|-----|---------|-------------|
| Raspberry Pi 5 (8GB) | 2 | Worker nodes | ~$80 each |
| USB-C Power Supply (27W) | 2 | Power (or PoE+ HATs) | ~$12 each |
| MicroSD Card (32GB+) | 2 | Boot media | ~$10 each |
| Ethernet cables | 2 | Network | ~$5 each |

**Alternative power option**: PoE+ HATs (~$20 each) + PoE+ switch if consolidating power

### New Node Setup

Follow existing `docs/pi-worker-setup.md` for each new Pi 5:

1. Flash Raspberry Pi OS Lite (64-bit)
2. Configure hostname: `pi5-worker-1`, `pi5-worker-2`
3. Set static IPs via DHCP reservation:
   - `pi5-worker-1`: 192.168.1.54
   - `pi5-worker-2`: 192.168.1.52
4. Enable cgroups, disable swap
5. Join to K3s cluster using node token from 1Password

```bash
# On each new Pi 5 (after OS setup)
curl -sfL https://get.k3s.io | K3S_URL=https://192.168.1.55:6443 K3S_TOKEN=<token> sh -
```

### Updated Cluster Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           K3s Cluster (5 nodes)                                 │
│                                                                                 │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐                    │
│  │  pi-k3s (Pi 5) │  │ pi5-worker-1   │  │ pi5-worker-2   │                    │
│  │  192.168.1.55  │  │ 192.168.1.54   │  │ 192.168.1.52   │                    │
│  │  8GB (master)  │  │ 8GB (worker)   │  │ 8GB (worker)   │                    │
│  │                │  │                │  │                │                    │
│  │ • Pi-hole      │  │ • Immich       │  │ • Prometheus   │                    │
│  │ • Unbound      │  │ • PostgreSQL   │  │ • Grafana      │                    │
│  │ • Flux         │  │ • Jellyfin     │  │ • Loki         │                    │
│  │ • cert-manager │  │ • Valkey       │  │ • Alertmanager │                    │
│  │ • ESO          │  │                │  │                │                    │
│  │ • ingress      │  │                │  │                │                    │
│  └────────────────┘  └────────────────┘  └────────────────┘                    │
│                                                                                 │
│  ┌────────────────┐  ┌────────────────┐                                        │
│  │ pi3-worker-1   │  │ pi3-worker-2   │                                        │
│  │ 192.168.1.53   │  │ 192.168.1.51   │                                        │
│  │ 1GB (worker)   │  │ 1GB (worker)   │                                        │
│  │                │  │                │                                        │
│  │ • cloudflared  │  │ • Homepage     │                                        │
│  │ • Vector       │  │ • mtgibbs-site │                                        │
│  └────────────────┘  └────────────────┘                                        │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Phase 2: Workload Redistribution

After new nodes are online, migrate heavy workloads off pi-k3s.

### Step 2.1: Add Node Affinity to Immich

Update `clusters/pi-k3s/immich/helmrelease.yaml` to prefer pi5-worker-1:

```yaml
spec:
  values:
    server:
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: kubernetes.io/hostname
                    operator: In
                    values:
                      - pi5-worker-1
    # Same for microservices, machine-learning pods
```

### Step 2.2: Add Node Affinity to Monitoring

Update `clusters/pi-k3s/monitoring/helmrelease.yaml` to prefer pi5-worker-2:

```yaml
spec:
  values:
    prometheus:
      prometheusSpec:
        nodeSelector:
          kubernetes.io/hostname: pi5-worker-2
    grafana:
      nodeSelector:
        kubernetes.io/hostname: pi5-worker-2
    alertmanager:
      alertmanagerSpec:
        nodeSelector:
          kubernetes.io/hostname: pi5-worker-2
```

### Step 2.3: Verify Migration

```bash
# Check pod distribution
kubectl get pods -A -o wide | grep -E "(pi-k3s|pi5-worker)"

# Verify memory usage per node
kubectl top nodes
```

**Target state**: pi-k3s under 50% memory usage

## Phase 3: Cloudflare Tunnel Setup

### Prerequisites

1. Cloudflare account with domain (mtgibbs.dev)
2. Create tunnel in Cloudflare Zero Trust dashboard
3. Store tunnel credentials in 1Password

### Step 3.1: Create 1Password Items

Create item `cloudflare-tunnel` in `pi-cluster` vault:
- `tunnel-id`: The tunnel UUID from Cloudflare dashboard
- `tunnel-token`: The tunnel token/credentials JSON
- `account-id`: Your Cloudflare account ID

### Step 3.2: Create Cloudflare Tunnel Namespace

```yaml
# clusters/pi-k3s/cloudflare-tunnel/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: cloudflare-tunnel
```

### Step 3.3: Create ExternalSecret

```yaml
# clusters/pi-k3s/cloudflare-tunnel/external-secret.yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: cloudflare-tunnel
  namespace: cloudflare-tunnel
spec:
  refreshInterval: 24h
  secretStoreRef:
    name: onepassword
    kind: ClusterSecretStore
  target:
    name: cloudflare-tunnel
    creationPolicy: Owner
  data:
    - secretKey: TUNNEL_TOKEN
      remoteRef:
        key: cloudflare-tunnel/tunnel-token
```

### Step 3.4: Deploy cloudflared

```yaml
# clusters/pi-k3s/cloudflare-tunnel/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cloudflared
  namespace: cloudflare-tunnel
spec:
  replicas: 1
  selector:
    matchLabels:
      app: cloudflared
  template:
    metadata:
      labels:
        app: cloudflared
    spec:
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: kubernetes.io/hostname
                    operator: In
                    values:
                      - pi3-worker-1
      containers:
        - name: cloudflared
          image: cloudflare/cloudflared:latest
          args:
            - tunnel
            - --no-autoupdate
            - run
          env:
            - name: TUNNEL_TOKEN
              valueFrom:
                secretKeyRef:
                  name: cloudflare-tunnel
                  key: TUNNEL_TOKEN
          resources:
            requests:
              cpu: 10m
              memory: 64Mi
            limits:
              cpu: 100m
              memory: 128Mi
```

### Step 3.5: Configure Tunnel Routes in Cloudflare Dashboard

| Hostname | Service | Path |
|----------|---------|------|
| `logs.mtgibbs.dev` | `http://vector.log-aggregation.svc.cluster.local:8080` | /* |

## Phase 4: Loki Installation

### Step 4.1: Create Log Aggregation Namespace

```yaml
# clusters/pi-k3s/log-aggregation/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: log-aggregation
```

### Step 4.2: Create Loki HelmRelease

```yaml
# clusters/pi-k3s/log-aggregation/loki-helmrelease.yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: grafana
  namespace: flux-system
spec:
  interval: 24h
  url: https://grafana.github.io/helm-charts
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: loki
  namespace: log-aggregation
spec:
  interval: 30m
  chart:
    spec:
      chart: loki
      version: "6.x"  # Check for latest
      sourceRef:
        kind: HelmRepository
        name: grafana
        namespace: flux-system
  values:
    deploymentMode: SingleBinary
    loki:
      auth_enabled: false
      commonConfig:
        replication_factor: 1
      storage:
        type: filesystem
      schemaConfig:
        configs:
          - from: "2024-01-01"
            store: tsdb
            object_store: filesystem
            schema: v13
            index:
              prefix: index_
              period: 24h
    singleBinary:
      replicas: 1
      nodeSelector:
        kubernetes.io/hostname: pi5-worker-2
      resources:
        requests:
          cpu: 100m
          memory: 512Mi
        limits:
          cpu: 500m
          memory: 1Gi
      persistence:
        enabled: true
        size: 10Gi
        storageClass: local-path  # Or NFS for durability
    # Disable components not needed for single binary
    backend:
      replicas: 0
    read:
      replicas: 0
    write:
      replicas: 0
    gateway:
      enabled: false
```

### Step 4.3: Add Loki Datasource to Grafana

Update `clusters/pi-k3s/monitoring/helmrelease.yaml`:

```yaml
spec:
  values:
    grafana:
      additionalDataSources:
        - name: Loki
          type: loki
          url: http://loki.log-aggregation.svc.cluster.local:3100
          access: proxy
          isDefault: false
```

## Phase 5: Vector Log Receiver

### Step 5.1: Deploy Vector

```yaml
# clusters/pi-k3s/log-aggregation/vector-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vector
  namespace: log-aggregation
spec:
  replicas: 1
  selector:
    matchLabels:
      app: vector
  template:
    metadata:
      labels:
        app: vector
    spec:
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: kubernetes.io/hostname
                    operator: In
                    values:
                      - pi3-worker-1
      containers:
        - name: vector
          image: timberio/vector:latest-alpine
          args:
            - --config-dir
            - /etc/vector
          ports:
            - containerPort: 8080
              name: heroku-drain
          volumeMounts:
            - name: config
              mountPath: /etc/vector
          resources:
            requests:
              cpu: 10m
              memory: 64Mi
            limits:
              cpu: 200m
              memory: 128Mi
      volumes:
        - name: config
          configMap:
            name: vector-config
---
apiVersion: v1
kind: Service
metadata:
  name: vector
  namespace: log-aggregation
spec:
  selector:
    app: vector
  ports:
    - port: 8080
      targetPort: heroku-drain
      name: heroku-drain
```

### Step 5.2: Vector Configuration

```yaml
# clusters/pi-k3s/log-aggregation/vector-configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: vector-config
  namespace: log-aggregation
data:
  vector.yaml: |
    sources:
      heroku_logs:
        type: heroku_logs
        address: "0.0.0.0:8080"

    transforms:
      parse_heroku:
        type: remap
        inputs:
          - heroku_logs
        source: |
          # Extract app name and dyno from Heroku log format
          .app = .app_name
          .dyno = .proc_id
          .level = if contains(string!(.message), "error") || contains(string!(.message), "Error") {
            "error"
          } else if contains(string!(.message), "warn") || contains(string!(.message), "Warn") {
            "warn"
          } else {
            "info"
          }

    sinks:
      loki:
        type: loki
        inputs:
          - parse_heroku
        endpoint: http://loki.log-aggregation.svc.cluster.local:3100
        encoding:
          codec: text
        labels:
          source: heroku
          app: "{{ app }}"
          dyno: "{{ dyno }}"
          level: "{{ level }}"
```

## Phase 6: Heroku Log Drain Configuration

After Vector and Cloudflare Tunnel are running:

```bash
# Add log drain to each Heroku app
heroku drains:add https://logs.mtgibbs.dev/events -a mtgibbs-tracking
heroku drains:add https://logs.mtgibbs.dev/events -a mtgibbs-xyz  # if applicable

# Verify drain is active
heroku drains -a mtgibbs-tracking
```

## Phase 7: Grafana Dashboards & Alerts

### Sample Log Query (LogQL)

```logql
# All errors from umami-tracking
{app="mtgibbs-tracking", level="error"}

# Search for specific text
{app="mtgibbs-tracking"} |= "failed"

# Rate of errors over time
rate({app="mtgibbs-tracking", level="error"}[5m])
```

### Sample Alert Rule

```yaml
# clusters/pi-k3s/log-aggregation/loki-alerts.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: loki-alerts
  namespace: log-aggregation
spec:
  groups:
    - name: heroku-logs
      rules:
        - alert: HerokuAppErrors
          expr: |
            sum(rate({app=~".+"} |= "error" [5m])) by (app) > 0.1
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "High error rate in {{ $labels.app }}"
            description: "Heroku app {{ $labels.app }} is logging errors"
```

## Kustomization Updates

### New Kustomization for Log Aggregation

```yaml
# Add to clusters/pi-k3s/flux-system/infrastructure.yaml
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: cloudflare-tunnel
  namespace: flux-system
spec:
  interval: 10m
  path: ./clusters/pi-k3s/cloudflare-tunnel
  prune: true
  sourceRef:
    kind: GitRepository
    name: flux-system
  dependsOn:
    - name: external-secrets-config
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: log-aggregation
  namespace: flux-system
spec:
  interval: 10m
  path: ./clusters/pi-k3s/log-aggregation
  prune: true
  sourceRef:
    kind: GitRepository
    name: flux-system
  dependsOn:
    - name: external-secrets-config
    - name: monitoring  # For Grafana datasource
    - name: cloudflare-tunnel
```

## Verification Checklist

After implementation:

- [ ] New Pi 5 nodes show as Ready in `kubectl get nodes`
- [ ] Memory usage on pi-k3s is under 50%
- [ ] Immich pods running on pi5-worker-1
- [ ] Monitoring pods running on pi5-worker-2
- [ ] cloudflared pod running on pi3-worker-1
- [ ] Vector pod running on pi3-worker-1
- [ ] Loki pod running on pi5-worker-2
- [ ] Cloudflare tunnel shows "Healthy" in dashboard
- [ ] Heroku drain shows "Added" status
- [ ] Logs visible in Grafana Explore with Loki datasource
- [ ] Test alert fires when injecting error log

## Estimated Timeline

1. **Hardware setup**: 1-2 hours per Pi 5 (OS install, K3s join)
2. **Workload migration**: 30 minutes (update manifests, reconcile)
3. **Cloudflare tunnel**: 1 hour (dashboard config + deploy)
4. **Loki + Vector**: 1 hour (deploy + configure)
5. **Heroku drain**: 15 minutes
6. **Dashboards/alerts**: 1-2 hours (build out as needed)

## Future Enhancements

- [ ] Add more Heroku apps to drain
- [ ] Public status page via Cloudflare tunnel
- [ ] Expose Grafana dashboards externally (read-only)
- [ ] Log-based autoscaling triggers
- [ ] Centralized logging for cluster pods (Promtail)
