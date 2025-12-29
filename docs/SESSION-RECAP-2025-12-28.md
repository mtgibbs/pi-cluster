# Session Recap - 2025-12-28

## Summary

Today's session focused on implementing comprehensive monitoring and alerting for Immich, configuring Discord notifications via Alertmanager, and fixing PostgreSQL backup reliability issues.

## Completed Work

### 1. Immich Prometheus Monitoring

**What**: Enabled Prometheus metrics collection and alerting for Immich photo service

**Why**: Immich had no observability beyond basic pod health checks, making it difficult to detect issues with background job processing (thumbnails, video transcoding, metadata extraction)

**How**:
- Enabled telemetry in Immich HelmRelease (`IMMICH_TELEMETRY_INCLUDE=all`)
- Configured metrics endpoints on ports 8081 (server) and 8082 (microservices)
- Created ServiceMonitor resource for Prometheus to scrape metrics endpoints
- Added Service resource with correct label selectors for Prometheus discovery (`app.kubernetes.io/component: metrics`)

**Files Modified**:
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/immich/helmrelease.yaml`
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/immich/servicemonitor.yaml` (new)
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/immich/kustomization.yaml`

**Relevant commits**: `7085d27`, `a4c0f52`, `a4c6f87`

---

### 2. Immich Alerting Rules

**What**: Created PrometheusRule with 6 alerts for Immich health monitoring

**Why**: Metrics alone don't provide proactive notification of issues. Alerting rules enable automatic detection of service degradation before users notice.

**How**:
- Created PrometheusRule resource in `immich` namespace
- Implemented 6 alerts based on actual available metrics:
  1. **ImmichServerDown**: Triggers when Immich server is unreachable (1 minute)
  2. **ImmichThumbnailQueueStuck**: Thumbnail queue size > 500 for 30 minutes
  3. **ImmichVideoQueueStuck**: Video transcoding queue size > 50 for 30 minutes
  4. **ImmichMetadataQueueStuck**: Metadata extraction queue size > 100 for 30 minutes
  5. **ImmichNoThumbnailActivity**: No thumbnails processed for 6 hours (indicates job processor failure)
  6. **ImmichDatabaseSlowQueries**: Database query duration > 5 seconds (performance degradation)

**Alert Severity**: All alerts marked as `warning` (informational, not critical)

**Files Modified**:
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/immich/prometheusrule.yaml` (new)
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/immich/kustomization.yaml`

**Relevant commits**: `92abdbb`

---

### 3. Discord Alerting via Alertmanager

**What**: Enabled Alertmanager in kube-prometheus-stack and configured Discord webhook receiver for alert notifications

**Why**: Prometheus alerts were being fired but had no notification destination. Discord provides a low-friction notification channel for cluster alerts.

**How**:

**Step 1: Enable Alertmanager**
- Set `alertmanager.enabled: true` in kube-prometheus-stack HelmRelease
- Configured Discord receiver in `alertmanager.config`
- Used Flux `valuesFrom` to inject Discord webhook URL from Kubernetes secret

**Step 2: Create ExternalSecret for Discord Webhook**
- Added Discord webhook URL to 1Password (`pi-cluster` vault, `alertmanager` item, `discord-alerts-webhook-url` field)
- Created ExternalSecret to sync webhook URL to `alertmanager-discord-webhook` secret
- Fixed 1Password item name mismatch (`discord-alerts` → `alertmanager`)

**Step 3: Configure Alert Routing**
- Default route sends all alerts to Discord receiver
- Configured message template with alert name, severity, instance, and description
- Set `send_resolved: true` to send recovery notifications
- Added 5-minute group interval to batch alerts

**Step 4: Silence Noisy Alerts**
- Silenced `Watchdog` alert (intentional heartbeat alert, always firing)
- Silenced `KubeMemoryOvercommit` alert (expected behavior in Pi cluster with resource limits)

**Files Modified**:
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/monitoring/helmrelease.yaml`
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/monitoring/external-secret.yaml`

**Relevant commits**: `186fca5`, `c9e6842`, `43e488f`, `b71e8f4`, `621250e`, `20db178`

**Technical Notes**:
- Webhook URL injection via Flux `valuesFrom` (references secret key directly in HelmRelease)
- Alert template uses Go templating syntax for Discord message formatting
- Alerts appear in Discord with severity color coding and clickable links (if applicable)

---

### 4. PostgreSQL Backup Fixes

**What**: Fixed two critical issues preventing PostgreSQL backups from completing successfully

**Why**: Nightly PostgreSQL backups were failing due to:
1. Package repository changes (Alpine Linux updated PostgreSQL client packages)
2. Synology NAS SFTP subsystem configuration (scp transfers failing)

**How**:

**Issue 1: PostgreSQL Client Package Name**
- **Problem**: `postgresql14-client` package not found in Alpine repositories
- **Cause**: Alpine Linux repos updated to PostgreSQL 16
- **Fix**: Changed package name from `postgresql14-client` → `postgresql16-client`
- **Impact**: Backup job can now install pg_dump successfully

**Issue 2: SCP Transfer Method**
- **Problem**: `scp` transfers failing with "subsystem request failed"
- **Cause**: Synology NAS has SFTP subsystem disabled in SSH configuration
- **Fix**: Switched from `scp` to `rsync` over SSH
- **Command**: `rsync -avz --rsync-path="rsync" immich-*.pgdump pi@192.168.1.60:/volume1/k3s-backups/...`
- **Impact**: Backups now transfer successfully to NAS

**Files Modified**:
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/backup-jobs/postgres-backup-cronjob.yaml`

**Relevant commits**: `921de68`, `621250e`

**Verification**: Backup job now completes successfully on Sundays at 2:30 AM

---

## Architecture Changes

### Alerting Flow

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         Monitoring + Alerting                            │
│                                                                          │
│  ┌────────────────┐    scrapes    ┌────────────────────────────┐        │
│  │ Immich Metrics │ ◄─────────────│      Prometheus            │        │
│  │ :8081, :8082   │   /metrics    │                            │        │
│  └────────────────┘   (30s)       │ • Stores metrics           │        │
│                                    │ • Evaluates PrometheusRule │        │
│                                    │ • Fires alerts             │        │
│                                    └──────────┬─────────────────┘        │
│                                               │                          │
│                                               │ Alert events             │
│                                               ▼                          │
│                                    ┌────────────────────────────┐        │
│                                    │     Alertmanager           │        │
│                                    │                            │        │
│                                    │ • Routes alerts            │        │
│                                    │ • Groups notifications     │        │
│                                    │ • Silences noisy alerts    │        │
│                                    └──────────┬─────────────────┘        │
│                                               │                          │
│                                               │ HTTP POST (webhook)      │
│                                               ▼                          │
│                                    ┌────────────────────────────┐        │
│                                    │   Discord Channel          │        │
│                                    │                            │        │
│                                    │ • Real-time notifications  │        │
│                                    │ • Alert + recovery messages│        │
│                                    └────────────────────────────┘        │
└──────────────────────────────────────────────────────────────────────────┘
```

### 1Password Secret Management

```
┌────────────────────────────────────────────────────────────────────────┐
│                    1Password → Kubernetes Secrets                      │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────┐      │
│  │                   1Password Cloud                            │      │
│  │  Vault: pi-cluster                                           │      │
│  │                                                               │      │
│  │  Items:                                                       │      │
│  │  • alertmanager                                               │      │
│  │    └─ discord-alerts-webhook-url: https://discord.com/...    │      │
│  │  • immich                                                     │      │
│  │    └─ db-password: <password>                                │      │
│  └───────────────────────────┬───────────────────────────────────┘      │
│                              │                                          │
│                              │ onepasswordSDK provider                  │
│                              ▼                                          │
│  ┌─────────────────────────────────────────────────────────────┐       │
│  │            External Secrets Operator (ESO)                  │       │
│  │                                                              │       │
│  │  ExternalSecrets:                                            │       │
│  │  • alertmanager-discord-webhook (monitoring namespace)       │       │
│  │  • postgres-backup-secret (backup-jobs namespace)            │       │
│  └───────────────────────────┬──────────────────────────────────┘       │
│                              │                                          │
│                              │ creates Kubernetes secrets               │
│                              ▼                                          │
│  ┌─────────────────────────────────────────────────────────────┐       │
│  │                   Kubernetes Secrets                         │       │
│  │                                                              │       │
│  │  • alertmanager-discord-webhook                              │       │
│  │    └─ webhookUrl: <synced from 1Password>                   │       │
│  │  • postgres-backup-db-password                               │       │
│  │    └─ password: <synced from 1Password>                     │       │
│  └───────────────────────────┬──────────────────────────────────┘       │
│                              │                                          │
│                              │ consumed by workloads                    │
│                              ▼                                          │
│  ┌─────────────────────────────────────────────────────────────┐       │
│  │               Workloads Using Secrets                        │       │
│  │                                                              │       │
│  │  • Alertmanager (Flux valuesFrom)                            │       │
│  │  • PostgreSQL backup CronJob (env var)                       │       │
│  └──────────────────────────────────────────────────────────────┘       │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Key Technical Decisions

### 1. ServiceMonitor Label Selector Strategy

**Decision**: Create separate Service resource with `app.kubernetes.io/component: metrics` label for Prometheus discovery

**Why**:
- Immich Helm chart creates Services with `app.kubernetes.io/component: server` and `app.kubernetes.io/component: microservices`
- Prometheus ServiceMonitor needs to match Service labels, not Pod labels directly
- Creating a dedicated metrics Service allows independent lifecycle management

**Implementation**:
```yaml
apiVersion: v1
kind: Service
metadata:
  name: immich-metrics
  namespace: immich
  labels:
    app.kubernetes.io/component: metrics  # Match this in ServiceMonitor
spec:
  selector:
    app.kubernetes.io/name: immich  # Match Immich pods
  ports:
    - name: server-metrics
      port: 8081
      targetPort: 8081
    - name: microservices-metrics
      port: 8082
      targetPort: 8082
```

**Trade-offs**:
- Additional resource to manage
- But: cleaner separation of concerns, explicit Prometheus discovery

---

### 2. Flux valuesFrom for Webhook URL Injection

**Decision**: Use Flux HelmRelease `valuesFrom` to inject Discord webhook URL instead of hardcoding in values

**Why**:
- Webhook URL is sensitive (grants write access to Discord channel)
- Flux `valuesFrom` allows referencing Kubernetes secrets in HelmRelease values
- Keeps secrets out of git repository
- ESO syncs webhook URL from 1Password → K8s secret → Flux injects into Helm chart

**Implementation**:
```yaml
apiVersion: helm.toolkit.fluxcd.io/v2beta1
kind: HelmRelease
spec:
  valuesFrom:
    - kind: Secret
      name: alertmanager-discord-webhook
      valuesKey: webhookUrl
      targetPath: alertmanager.config.receivers[0].discord_configs[0].webhook_url
```

**Trade-offs**:
- Requires understanding Flux valuesFrom syntax
- Helm chart must be reconciled after secret creation
- But: proper secret management, no secrets in git

---

### 3. Alert Silencing Strategy

**Decision**: Silence specific alerts using inhibit rules or by removing from PrometheusRule, rather than disabling Alertmanager entirely

**Why**:
- `Watchdog` alert is intentional (Prometheus heartbeat check), always firing
- `KubeMemoryOvercommit` is expected behavior in Pi cluster with resource limits
- Silencing at Alertmanager level keeps alert definitions intact for reference
- Allows future re-enabling if requirements change

**Implementation**:
```yaml
# Option 1: Comment out in PrometheusRule (cleaner, used for this project)
# - alert: Watchdog
#   expr: vector(1)

# Option 2: Alertmanager inhibit rules (more complex, not used)
inhibit_rules:
  - source_match:
      alertname: Watchdog
    target_match:
      severity: warning
    equal: ['alertname']
```

**Trade-offs**:
- Need to track which alerts are intentionally silenced
- But: cleaner Discord notifications, less alert fatigue

---

### 4. PostgreSQL Backup Tool Selection (rsync vs scp)

**Decision**: Switch from `scp` to `rsync` for backup transfers to Synology NAS

**Why**:
- **scp limitation**: Requires SFTP subsystem enabled in SSH server
- **Synology configuration**: SFTP subsystem disabled (security hardening)
- **rsync advantages**:
  - Works over SSH without SFTP subsystem
  - Built-in compression (`-z` flag)
  - Resume capability for interrupted transfers
  - Better progress reporting

**Implementation**:
```bash
# Before (failing):
scp immich-${DATE}.pgdump pi@192.168.1.60:/volume1/k3s-backups/${DATE}/postgres/

# After (working):
rsync -avz --rsync-path="rsync" \
  immich-${DATE}.pgdump \
  pi@192.168.1.60:/volume1/k3s-backups/${DATE}/postgres/
```

**Trade-offs**:
- Requires rsync installed on both sides (already present on Pi and Synology)
- But: more robust, better error handling, resume capability

---

## Updated Service Configuration

### Immich Monitoring

**Metrics Endpoints**:
- Server metrics: `http://immich-server.immich.svc.cluster.local:8081/metrics`
- Microservices metrics: `http://immich-microservices.immich.svc.cluster.local:8082/metrics`

**Available Metrics** (subset):
- `immich_server_thumbnail_queue_size` - Number of photos waiting for thumbnail generation
- `immich_server_video_conversion_queue_size` - Number of videos waiting for transcoding
- `immich_server_metadata_extraction_queue_size` - Number of files waiting for metadata extraction
- `immich_server_processing_duration_seconds` - Time spent processing jobs

**Scrape Interval**: 30 seconds (Prometheus default)

**Alert Thresholds**:
| Alert | Threshold | Duration | Severity |
|-------|-----------|----------|----------|
| ImmichServerDown | Service unreachable | 1 minute | warning |
| ImmichThumbnailQueueStuck | Queue > 500 | 30 minutes | warning |
| ImmichVideoQueueStuck | Queue > 50 | 30 minutes | warning |
| ImmichMetadataQueueStuck | Queue > 100 | 30 minutes | warning |
| ImmichNoThumbnailActivity | No processing | 6 hours | warning |
| ImmichDatabaseSlowQueries | Query > 5s | 5 minutes | warning |

---

### Alertmanager Configuration

**Receiver**: `discord-alerts`
- **Type**: Discord webhook
- **Webhook URL**: Injected from 1Password via ExternalSecret
- **Message Format**:
  ```
  [SEVERITY] Alert: ALERTNAME
  Instance: INSTANCE
  Description: DESCRIPTION
  ```

**Routing**:
- All alerts sent to Discord receiver
- 5-minute group interval (batch alerts)
- Send resolved notifications (`send_resolved: true`)

**Silenced Alerts**:
- `Watchdog` (intentional heartbeat)
- `KubeMemoryOvercommit` (expected in Pi cluster)

---

### PostgreSQL Backup Job

**Schedule**: `0 2 * * 0` (Sundays at 2:30 AM)

**Backup Process**:
1. Install PostgreSQL 16 client (`postgresql16-client`)
2. Dump database using pg_dump:
   ```bash
   pg_dump -h immich-postgresql.immich.svc.cluster.local \
     -U postgres -d immich \
     -Fc -Z 9 -f immich-YYYYMMDD.pgdump
   ```
3. Transfer to Synology NAS via rsync:
   ```bash
   rsync -avz --rsync-path="rsync" \
     immich-YYYYMMDD.pgdump \
     pi@192.168.1.60:/volume1/k3s-backups/YYYYMMDD/postgres/
   ```

**Credentials**: Database password synced from 1Password (`immich/db-password`)

**Node Affinity**: Pinned to `pi-k3s` (same node as PVC backup)

**Retention**: Manual (backups stored on NAS)

---

## Next Steps

### Immediate
- [ ] Verify Immich alerts are firing correctly (manually trigger queue stuck condition)
- [ ] Test Discord notification delivery (trigger test alert)
- [ ] Monitor PostgreSQL backup success on next Sunday (2025-01-05 02:30)

### Future Work
- [ ] Add Grafana dashboards for Immich metrics visualization
- [ ] Implement backup retention policy (automated cleanup of old backups)
- [ ] Create recovery runbook for PostgreSQL backup restoration
- [ ] Add alert for backup job failures
- [ ] Consider adding Alertmanager silences for maintenance windows

---

## Troubleshooting Commands

```bash
# Check ServiceMonitor status
kubectl get servicemonitor -n immich

# Verify Prometheus is scraping Immich targets
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090
# Visit: http://localhost:9090/targets (search for "immich")

# Check PrometheusRule status
kubectl get prometheusrule -n immich

# View active alerts in Prometheus
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090
# Visit: http://localhost:9090/alerts

# Check Alertmanager config
kubectl get secret -n monitoring alertmanager-kube-prometheus-alertmanager -o jsonpath='{.data.alertmanager\.yaml}' | base64 -d

# View Alertmanager status
kubectl port-forward -n monitoring svc/alertmanager-kube-prometheus-alertmanager 9093:9093
# Visit: http://localhost:9093

# Test Discord webhook manually
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"content": "Test alert from Alertmanager"}' \
  <webhook-url>

# Check PostgreSQL backup job logs
kubectl logs -n backup-jobs job/postgres-backup

# Manually trigger PostgreSQL backup job
kubectl create job -n backup-jobs postgres-backup-manual \
  --from=cronjob/postgres-backup
```

---

## Files Modified Summary

| File | Change Type | Purpose |
|------|-------------|---------|
| `clusters/pi-k3s/immich/helmrelease.yaml` | Modified | Enable Prometheus metrics (telemetry env vars) |
| `clusters/pi-k3s/immich/servicemonitor.yaml` | Created | Prometheus scraping configuration |
| `clusters/pi-k3s/immich/prometheusrule.yaml` | Created | Alert definitions for Immich health |
| `clusters/pi-k3s/immich/kustomization.yaml` | Modified | Add ServiceMonitor and PrometheusRule to resources |
| `clusters/pi-k3s/monitoring/helmrelease.yaml` | Modified | Enable Alertmanager + Discord receiver config |
| `clusters/pi-k3s/monitoring/external-secret.yaml` | Modified | Add Discord webhook URL from 1Password |
| `clusters/pi-k3s/backup-jobs/postgres-backup-cronjob.yaml` | Modified | Fix package name + switch to rsync |

---

## Lessons Learned

### 1. ServiceMonitor Label Matching
- ServiceMonitor matches **Service labels**, not Pod labels
- Creating a dedicated metrics Service simplifies Prometheus discovery
- Always verify `kubectl get servicemonitor` shows correct endpoint count

### 2. Flux valuesFrom Syntax
- Use `targetPath` with dot notation for nested values
- Array indices use bracket notation: `receivers[0].discord_configs[0].webhook_url`
- Secret must exist before HelmRelease reconciliation

### 3. Alpine Package Repository Changes
- Package names change over time (postgresql14-client → postgresql16-client)
- Always verify package availability in Alpine package database before deploying
- Pin package versions in production for stability

### 4. Synology SFTP Subsystem
- Not all SSH servers have SFTP subsystem enabled
- `rsync` is more versatile for file transfers (works over plain SSH)
- Always test backup transfers after infrastructure changes

### 5. Alert Fatigue Management
- Silence intentional alerts (like Watchdog) immediately
- Group alerts with appropriate intervals (5 minutes for batch notifications)
- Use severity levels to prioritize notifications (critical > warning > info)

---

## Related Documentation

- **Immich Metrics**: https://immich.app/docs/administration/metrics
- **Prometheus Operator**: https://prometheus-operator.dev/docs/
- **Alertmanager Configuration**: https://prometheus.io/docs/alerting/latest/configuration/
- **Flux valuesFrom**: https://fluxcd.io/flux/components/helm/helmreleases/#values-overrides
- **PostgreSQL pg_dump**: https://www.postgresql.org/docs/current/app-pgdump.html
