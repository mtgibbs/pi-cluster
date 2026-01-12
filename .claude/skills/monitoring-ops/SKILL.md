---
name: monitoring-ops
description: Expert knowledge for cluster observability. Use when configuring Prometheus/Grafana, Alertmanager, Uptime Kuma, or the Homepage dashboard.
allowed-tools: Bash, Read, Grep, Glob, Edit, Write
---

# Monitoring Operations

## Stack Overview
- **Core**: `kube-prometheus-stack` (Prometheus, Grafana, Alertmanager)
- **Status Page**: Uptime Kuma (with AutoKuma for GitOps)
- **Dashboard**: Homepage (unified view)

## Prometheus & Alerting

### Configuration
- Managed via Flux HelmRelease in `monitoring` namespace.
- **Alertmanager**: Routes alerts to Discord.
- **Webhook**: Synced from 1Password (`alertmanager/discord-alerts-webhook-url`).

### Active Rules
- **Immich**: Server down, Queue stuck, Slow queries.
- **Kubernetes**: Standard node/pod health checks.

## Uptime Kuma
- **URL**: `https://status.lab.mtgibbs.dev`
- **AutoKuma**: Manages monitors via `ConfigMap/autokuma-monitors`.
- **Storage**: 100Mi PVC for `sled` database (Critical: prevents duplicate monitors on restart).
- **Credentials**: Synced from 1Password (`uptime-kuma` item).

## Homepage Dashboard
- **URL**: `https://home.lab.mtgibbs.dev`
- **Config**: GitOps-managed via `ConfigMap`.
- **Live Widgets**:
    - **Pi-hole**: v6 API integration.
    - **Immich/Jellyfin**: API keys via Environment Variables (`HOMEPAGE_VAR_*`).
    - **Kubernetes**: Node stats (requires ServiceAccount with ClusterRole).
- **Secrets**: API keys synced via multiple ExternalSecrets.

## Troubleshooting

### Grafana Access
```bash
# Get admin password
kubectl get secret grafana-admin -n monitoring -o jsonpath="{.data.admin-password}" | base64 -d
```

### Check Alertmanager Status
```bash
kubectl -n monitoring port-forward svc/prometheus-kube-prometheus-alertmanager 9093:9093
# Access at http://localhost:9093
```

### AutoKuma Issues
If monitors are duplicated:
1. Check if `autokuma-pvc` is bound.
2. Verify `strategy: Recreate` is set on the deployment.
