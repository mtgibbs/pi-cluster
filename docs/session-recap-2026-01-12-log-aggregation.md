# Session Recap - January 12, 2026

## Log Aggregation Infrastructure for Heroku Applications

### Completed

**1. Cloudflare Tunnel for External Log Ingestion**
- Deployed cloudflared with GitOps-managed ingress routes for `logs.mtgibbs.dev`
- Configured tunnel to route external Heroku log drain traffic to internal Vector service
- Used init container pattern to convert base64-encoded tunnel token to credentials.json format
- Added liveness/readiness probes using cloudflared metrics endpoint (`/ready` on port 2000)
- Scheduled on Pi 5 workers to avoid Pi 3 memory constraints

**Why**: Enable external Heroku applications to drain logs into the cluster for centralized monitoring and troubleshooting.

**How**:
- ExternalSecret syncs tunnel token from 1Password (`cloudflare-tunnel/tunnel-token` and `cloudflare-tunnel/tunnel-id`)
- Init container decodes token and creates credentials.json with AccountTag, TunnelID, TunnelSecret
- ConfigMap defines ingress route: `logs.mtgibbs.dev` → `http://vector.log-aggregation.svc.cluster.local:8080`
- CNAME DNS record points `logs.mtgibbs.dev` → `<tunnel-id>.cfargotunnel.com`

**2. Loki Log Storage and Aggregation**
- Deployed Loki v6 in single-binary mode using Grafana Helm chart
- Configured filesystem storage with 7-day retention (168h)
- Pinned to pi5-worker-2 with 10Gi local-path persistent storage
- Disabled distributed components (backend, read, write) for small-cluster optimization
- Disabled caching (chunksCache, resultsCache) to reduce memory footprint

**Why**: Provide long-term log storage and querying capability for application troubleshooting.

**How**:
- HelmRelease in `log-aggregation` namespace with custom values
- Single binary deployment: 1 replica with 256Mi request / 512Mi limit
- Storage: TSDB schema (v13) on local filesystem, 24h index period
- Exposes port 3100 for log ingestion and querying

**3. Vector Log Processing Pipeline**
- Deployed Vector as HTTP endpoint to receive Heroku log drain POSTs
- Implemented VRL (Vector Remap Language) transforms to parse Heroku syslog format
- Extracts structured data: app name, dyno type, log level, timestamp
- Routes logs to Loki with labels for filtering (source, app, dyno, level)
- Console sink enabled for debugging (can be removed later)

**Why**: Transform unstructured Heroku syslog logs into structured, queryable data.

**How**:
- ConfigMap defines Vector pipeline: HTTP source (port 8080) → VRL transform → Loki sink
- Parses Heroku log format: `<timestamp> <app> <dyno> - <message>`
- Infers log level from message content (error, warn, debug, info)
- Labels logs with extracted metadata for Loki label filtering
- Scheduled on Pi 5 workers to avoid Pi 3 networking issues

**4. Grafana Loki Datasource**
- Added Loki as datasource in Grafana (kube-prometheus-stack HelmRelease)
- Configured with cluster-internal endpoint: `http://loki.log-aggregation.svc.cluster.local:3100`
- Enabled for log visualization and correlation with metrics

**Why**: Unified observability dashboard with both metrics (Prometheus) and logs (Loki).

**5. Uptime Kuma Monitoring**
- Added 3 new monitors via AutoKuma GitOps:
  - **Loki HTTP Check**: Verifies Loki API is accessible (`http://loki.log-aggregation.svc.cluster.local:3100/ready`)
  - **Vector HTTP Check**: Verifies Vector is accepting logs (`http://vector.log-aggregation.svc.cluster.local:8080`)
  - **Log Drain Endpoint Check**: Verifies external drain is reachable (`https://logs.mtgibbs.dev`)
- Discord alerts enabled via default notification

**Why**: Proactive alerting if log ingestion pipeline fails.

**6. Homepage Dashboard Integration**
- Added new "Logs" section to Homepage dashboard
- Displays Loki service status with siteMonitor health check
- Shows log drain endpoint status with external URL monitoring

**Why**: Centralized visibility into log infrastructure health.

### Problems Encountered and Solutions

**1. ExternalSecret Key Format Issue**

**Problem**: Used `key: cloudflare-tunnel` + `property: tunnel-token` in ExternalSecret, but ESO SDK provider requires path-style format.

**Solution**: Changed to `key: cloudflare-tunnel/tunnel-token` format. ESO interprets this as vault item "cloudflare-tunnel" with field "tunnel-token".

**Lesson**: 1Password SDK provider uses path notation (`item/field`), not object notation with separate property field.

**2. Cloudflare Tunnel Configuration Strategy**

**Problem**: Initially tried dashboard-managed routes in Cloudflare Zero Trust UI, but couldn't reliably GitOps-manage route changes.

**Solution**: Switched to local config file approach:
- ConfigMap contains `config.yaml` with ingress route definitions
- Init container converts tunnel token to credentials.json format
- cloudflared runs with `--config` and `--credentials-file` flags
- All tunnel configuration now in git (except token secret)

**Lesson**: Local config file approach enables full GitOps control of tunnel routes.

**3. Vector Health Probe Failures**

**Problem**: Configured liveness/readiness probes to check `/health` on port 8686, but Vector API doesn't expose that path. Probes failed continuously with 404 errors.

**Solution**: Changed to TCP socket check on port 8080 (HTTP log ingestion endpoint):
```yaml
livenessProbe:
  tcpSocket:
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 10
readinessProbe:
  tcpSocket:
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 5
```

**Lesson**: When HTTP health endpoints are unavailable, TCP checks verify service is listening and accepting connections.

**4. Loki chunks-cache Pending State**

**Problem**: Loki HelmRelease deployed but chunks-cache and results-cache pods remained in Pending state with "Insufficient memory" errors. Cluster (especially pi3-worker-2) couldn't accommodate additional memory overhead.

**Solution**: Disabled caching entirely in HelmRelease:
```yaml
chunksCache:
  enabled: false
resultsCache:
  enabled: false
```

**Why**: Small cluster with limited workload doesn't benefit significantly from caching. Log queries are infrequent enough that cache overhead isn't justified.

**Lesson**: Default Helm values assume datacenter resources. Resource-constrained clusters need aggressive disabling of optional components.

**5. DNS Not Resolving for logs.mtgibbs.dev**

**Problem**: Cloudflare tunnel deployed successfully, but external log drain couldn't resolve `logs.mtgibbs.dev`.

**Solution**: Added CNAME record in Cloudflare DNS:
- `logs.mtgibbs.dev` CNAME → `<tunnel-id>.cfargotunnel.com`
- Proxy OFF (orange cloud disabled) for tunnel endpoints

**Lesson**: Cloudflare tunnels require DNS record pointing to `.cfargotunnel.com` domain, even though tunnel is managed in Zero Trust dashboard.

**6. pi3-worker-2 Memory Overload (70% Utilization)**

**Problem**: Pi 3 node (1GB RAM) was at 70% memory usage before log aggregation deployment. Adding cloudflared and Vector caused scheduling failures and memory pressure warnings.

**Solution**: Updated nodeAffinity in both deployments to prefer Pi 5 workers:
```yaml
affinity:
  nodeAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        preference:
          matchExpressions:
            - key: kubernetes.io/hostname
              operator: In
              values:
                - pi5-worker-1
                - pi5-worker-2
```

**Impact**: Moved ~128Mi (cloudflared + Vector) from Pi 3 to Pi 5 workers. pi3-worker-2 now at ~50% memory, healthier for lightweight services.

**Lesson**: Pi 3 hardware (1GB RAM, Cortex-A53) suitable only for lightweight stateless web apps. Infrastructure services (proxies, log forwarders) require Pi 5 resources.

**7. Flux source-controller Stuck State**

**Problem**: Pushed new commits to main branch, but Flux wasn't detecting changes. `flux reconcile source git flux-system` showed no new commits despite GitHub showing them.

**Solution**: Restarted source-controller pod to clear stuck state:
```bash
kubectl -n flux-system delete pod -l app=source-controller
```

**Why**: source-controller occasionally gets into state where git polling stops working. Restart clears internal cache and resumes polling.

**Lesson**: When Flux isn't detecting commits, check source-controller logs and consider restart as first troubleshooting step.

### Key Decisions

**1. Single-Binary Loki Deployment**

**Decision**: Use Loki single-binary mode instead of microservices (read, write, backend components).

**Why**:
- Small cluster with limited resources (Pi 5 nodes, no shared storage)
- Log volume is low (single Heroku application, infrequent deployments)
- Microservices mode requires distributed storage (object storage like S3)
- Single binary simplifies operations and debugging

**Trade-offs**:
- No horizontal scaling capability
- Single point of failure (acceptable for learning cluster)
- But: significantly lower resource usage, simpler troubleshooting

**2. Filesystem Storage for Loki**

**Decision**: Use filesystem backend with local-path storage instead of object storage (S3, GCS).

**Why**:
- Pi cluster doesn't have object storage (MinIO would add complexity)
- Log retention is short (7 days), storage needs are minimal
- local-path PVC provides sufficient persistence for learning use case

**Trade-offs**:
- Loki pod pinned to single node (nodeSelector for pi5-worker-2)
- No replication (data loss if node fails)
- But: zero operational overhead, no cloud dependencies

**3. Vector as HTTP Endpoint (Not Syslog)**

**Decision**: Configure Vector to receive logs via HTTP POST instead of syslog protocol.

**Why**:
- Heroku log drains support both syslog and HTTPS endpoints
- HTTPS provides TLS encryption in transit (Cloudflare tunnel handles termination)
- HTTP is stateless (no connection state to manage)
- Easier to test with curl/Postman

**Trade-offs**:
- Requires Cloudflare tunnel for external access (can't use native K8s LoadBalancer)
- But: better security posture, easier debugging

**4. Cloudflare Tunnel Token Authentication**

**Decision**: Use tunnel token authentication instead of cert-based authentication.

**Why**:
- Token authentication simpler to GitOps-manage (single secret vs. cert + key)
- Tokens can be rotated in Cloudflare dashboard without cluster changes
- Init container pattern converts token to credentials.json format required by cloudflared

**Trade-offs**:
- Token is long-lived (no automatic rotation)
- Requires custom init container logic
- But: aligns with 1Password secrets workflow, easier initial setup

**5. Loki as Grafana Datasource (Not Separate Dashboard)**

**Decision**: Add Loki datasource to existing Grafana instance instead of deploying separate Loki UI.

**Why**:
- Grafana is already deployed and trusted (TLS, authentication)
- Unified dashboard experience (metrics + logs in same UI)
- No additional resource overhead

**Trade-offs**:
- No standalone Loki API for external tools
- But: sufficient for learning cluster use case

**6. VRL Transform for Log Parsing**

**Decision**: Use Vector Remap Language (VRL) to parse and enrich logs instead of relying on Loki's LogQL parsing at query time.

**Why**:
- Parse-time enrichment is more efficient than query-time parsing
- Extracted labels (app, dyno, level) enable fast Loki label filtering
- VRL is more powerful than LogQL for complex parsing logic

**Trade-offs**:
- More complex Vector configuration
- Changes require pod restart (not dynamic)
- But: better query performance, cleaner Loki storage

### Commits Made

| Commit | Description |
|--------|-------------|
| `a7e3960` | feat(cloudflare-tunnel): Add Cloudflare Tunnel for external access |
| `a86a13c` | fix(cloudflare-tunnel): Use correct 1Password key format |
| `8e05735` | fix(cloudflare-tunnel): Enable metrics server for health probes |
| `79119bb` | feat(cloudflare-tunnel): GitOps-managed ingress routes |
| `7319ebf` | fix(cloudflare-tunnel): Add tunnel ID to run command |
| `6983d3c` | feat(log-aggregation): Add Loki + Vector for Heroku log drain |
| `2c55b7a` | fix(log-aggregation): Disable Loki caching for resource constraints |
| `b0d47db` | feat(monitoring): Add log aggregation monitors and Homepage widget |
| `f306770` | fix(log-aggregation): Fix Vector health probes to use TCP on port 8080 |
| `eefcd6e` | fix(scheduling): Move Vector and cloudflared to Pi 5 workers |
| `248dbb1` | docs: Update CLAUDE.md and cluster-ops agent |

### Architecture Changes

**New Namespaces**:
- `cloudflare-tunnel`: Cloudflare tunnel proxy for external access
- `log-aggregation`: Loki and Vector for log storage and processing

**New Services**:
- **Cloudflare Tunnel**: External HTTPS ingress via Cloudflare network
  - Tunnel endpoint: `logs.mtgibbs.dev` (public DNS)
  - Routes to: `http://vector.log-aggregation.svc.cluster.local:8080`
  - Authentication: Tunnel token from 1Password
  - Scheduled on: Pi 5 workers (nodeAffinity preference)

- **Loki**: Log aggregation and storage
  - Version: Loki v6 (Helm chart 6.x)
  - Deployment mode: Single binary
  - Storage: 10Gi local-path PVC on pi5-worker-2
  - Retention: 7 days (168h)
  - Endpoint: `http://loki.log-aggregation.svc.cluster.local:3100`

- **Vector**: Log processing pipeline
  - HTTP endpoint: Port 8080 (receives Heroku logs)
  - API endpoint: Port 8686 (health checks)
  - Transforms: VRL parsing of Heroku syslog format
  - Sinks: Loki (primary) + console (debug)
  - Scheduled on: Pi 5 workers (nodeAffinity preference)

**Log Flow**:
```
Heroku Application
    │
    │ HTTPS POST (log drain)
    ▼
logs.mtgibbs.dev (Cloudflare Tunnel)
    │
    │ HTTP (internal)
    ▼
Vector (log-aggregation namespace)
    │
    │ Parse & transform (VRL)
    │ Labels: source, app, dyno, level
    ▼
Loki (log-aggregation namespace)
    │
    │ Storage: filesystem (10Gi PVC)
    │ Retention: 7 days
    ▼
Grafana Datasource
    │
    │ LogQL queries
    ▼
Grafana Dashboard (monitoring namespace)
```

**Flux Dependencies**:
```
external-secrets
    │
    ├─> cloudflare-tunnel (needs tunnel token)
    │
    └─> log-aggregation (ready, no secrets yet)
        │
        └─> monitoring (Grafana datasource)
```

**Resource Allocation**:
| Component | CPU Request | CPU Limit | Memory Request | Memory Limit | Storage |
|-----------|-------------|-----------|----------------|--------------|---------|
| cloudflared | 10m | 100m | 64Mi | 128Mi | - |
| Vector | 50m | 500m | 128Mi | 256Mi | - |
| Loki | 100m | 500m | 256Mi | 512Mi | 10Gi |

**Total Overhead**: ~160m CPU, ~448Mi memory, 10Gi storage

### Monitoring and Observability

**Uptime Kuma Monitors**:
1. **Loki HTTP Check**: `http://loki.log-aggregation.svc.cluster.local:3100/ready` (internal)
2. **Vector HTTP Check**: `http://vector.log-aggregation.svc.cluster.local:8080` (internal TCP)
3. **Log Drain Endpoint Check**: `https://logs.mtgibbs.dev` (external)

**Homepage Dashboard**:
- New "Logs" section with Loki service tile
- siteMonitor integration for real-time status
- Log drain endpoint visibility

**Grafana Integration**:
- Loki datasource configured in kube-prometheus-stack
- Ready for log visualization and correlation with metrics
- Future: Create dashboards for Heroku application logs

### Testing and Validation

**1. Cloudflare Tunnel Connectivity**
```bash
# Test external endpoint
curl -X POST https://logs.mtgibbs.dev -d "test log message"
# Expected: 200 OK (Vector receives and processes)
```

**2. Vector Log Processing**
```bash
# Check Vector logs for received messages
kubectl -n log-aggregation logs -f deploy/vector
# Expected: JSON output showing parsed log with labels
```

**3. Loki Storage**
```bash
# Query Loki for ingested logs
kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80
# Open Grafana → Explore → Loki datasource
# Query: {source="heroku"}
```

**4. Health Probes**
```bash
# Check Vector readiness
kubectl -n log-aggregation get pods
# Expected: vector pod in Ready state

# Check Loki readiness
curl http://loki.log-aggregation.svc.cluster.local:3100/ready
# Expected: "ready"
```

### Next Steps

**Immediate**:
- [ ] Configure Heroku application log drain to use `https://logs.mtgibbs.dev`
- [ ] Test end-to-end flow with real Heroku logs
- [ ] Create Grafana dashboard for Heroku application logs

**Future Enhancements**:
- [ ] Add Prometheus metrics for Vector (log ingestion rate, parsing errors)
- [ ] Create Grafana dashboard with log query examples
- [ ] Add LogQL alert rules for application errors
- [ ] Consider adding promtail for Kubernetes pod logs (not just Heroku)
- [ ] Evaluate Loki retention policy (7 days may be too short)
- [ ] Add Loki compactor for storage optimization
- [ ] Consider remote object storage backend for longer retention

**Documentation**:
- [ ] Update ARCHITECTURE.md with log aggregation diagram
- [ ] Create monitoring-ops skill with Loki query examples
- [ ] Document Heroku log drain setup procedure
- [ ] Create runbook for Vector/Loki troubleshooting

### Lessons Learned

**1. Resource Constraints Matter**
- Default Helm values assume datacenter-scale resources
- Aggressive feature disabling (caching, monitoring, test pods) is necessary for Pi clusters
- Pi 3 hardware unsuitable for infrastructure services (DNS, proxies, log forwarders)

**2. ExternalSecret Key Formats Are Provider-Specific**
- 1Password SDK provider uses path notation: `item/field`
- AWS Secrets Manager uses separate `key` + `property` fields
- Always consult ESO provider documentation for key format

**3. Health Probe Design Requires Understanding Application**
- Not all applications expose `/health` or `/healthz` endpoints
- TCP checks are universal fallback for services without HTTP health endpoints
- Metrics endpoints (`/metrics`, `/ready`) often work when `/health` doesn't

**4. GitOps Tunnel Configuration Beats Dashboard Management**
- Dashboard-managed tunnel routes are opaque to git history
- Local config file approach enables full GitOps audit trail
- Init containers bridge gap between secret formats (token → credentials.json)

**5. Node Affinity Prevents Scheduling Surprises**
- Pi 3 nodes can't reliably run infrastructure services
- Explicit nodeAffinity preferences prevent Kubernetes from over-scheduling Pi 3
- Use `preferredDuringSchedulingIgnoredDuringExecution` for soft constraints (allows fallback)

### Related Documentation

- **Architecture**: ARCHITECTURE.md (needs update with log aggregation diagram)
- **Skills**: monitoring-ops skill (add Loki section)
- **Runbooks**: Known issues (add Flux source-controller stuck state)
- **Previous Session**: session-recap-2026-01-11-tailscale-vpn.md (Tailscale deployment)

### Session Statistics

- **Duration**: ~4 hours
- **Commits**: 11
- **Files Changed**: 12 files, 382 insertions, 44 deletions
- **Namespaces Added**: 2 (cloudflare-tunnel, log-aggregation)
- **Services Deployed**: 3 (cloudflared, Vector, Loki)
- **Monitors Added**: 3 (Loki, Vector, Log Drain)
- **Problems Solved**: 7 (ExternalSecret format, tunnel config, health probes, memory, DNS, scheduling, Flux state)

---

**Session completed**: 2026-01-12 (documented by recap-architect agent)
