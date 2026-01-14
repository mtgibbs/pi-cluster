# Session Recap - January 13, 2026

## Completed

- **Deployed CARL (Canvas Assignment Reminder Liaison)** - New service to send assignment reminders from Canvas LMS
  - Initial deployment at v0.1.0 with GitOps image automation configured
  - REST API server running on port 8080 with health checks
  - Ingress configured at `carl.lab.mtgibbs.dev`

- **Deployed Ollama local LLM server** - On-cluster language model inference for CARL
  - Pinned to pi5-worker-1 (ARM64 Pi 5) for performance
  - Auto-pull model on startup from 1Password configuration
  - Persistent storage for model cache (2Gi PVC)
  - Resource limits: 2 CPU / 4Gi memory

- **Integrated CARL with Ollama** - Enhanced intent detection using local LLM
  - CARL queries Ollama API at `http://ollama.ollama.svc.cluster.local:11434`
  - Model selection configured via 1Password (OLLAMA_MODEL)
  - Enables smarter assignment reminder logic without external API dependencies

- **Configured secrets management for both services**
  - CARL: All credentials moved to single 1Password item (`CARL`)
    - Canvas API credentials (CANVAS_API_URL, CANVAS_API_TOKEN)
    - Ollama integration (OLLAMA_URL, OLLAMA_MODEL)
  - Ollama: Model configuration via 1Password (`OLLAMA_MODEL` field)
  - Both services using ExternalSecret for automatic secret sync

- **Set up Flux image automation**
  - CARL: Semver policy tracking `v*.*.*` releases from `ghcr.io/mtgibbs/carl`
  - Both services auto-update when new images are pushed

## Key Decisions

### Decision: Deploy Ollama on-cluster instead of external LLM API
**Why**:
- Avoid external API costs and rate limits
- Keep sensitive Canvas/student data within cluster boundary
- Faster inference due to local network latency
- Learning opportunity for deploying ML workloads on ARM

**How**:
- Used official `ollama/ollama:latest` image (ARM64 compatible)
- Pinned to pi5-worker-1 for consistent performance and storage locality
- Custom startup script to auto-pull model before server starts
- Model name configurable via 1Password (currently using llama3.2 or similar)

**Trade-offs**:
- Resource overhead: 2-4GB memory dedicated to Ollama
- Model storage requires persistent volume
- Pi 5 ARM performance is slower than x86 GPU inference
- But: no external dependencies, zero cost, full control

### Decision: Use startup script for model pulling instead of init container
**Why**:
- Ollama server must be running to execute `ollama pull` command
- Init containers run before main container starts (can't communicate with server)
- Startup script ensures model is available before accepting traffic

**How**:
```bash
ollama serve &
until ollama list >/dev/null 2>&1; do sleep 2; done
ollama pull "$OLLAMA_MODEL"
wait $SERVER_PID
```

**Trade-offs**:
- Container start time increased (model pull can take 1-2 minutes)
- Readiness probe delayed (60s initial delay)
- But: simple solution that works reliably

### Decision: Consolidate all CARL config under single 1Password item
**Why**:
- Initial deployment used separate items for Canvas and Ollama config
- Single item simplifies secret management and reduces ExternalSecret resources
- Clearer ownership: all CARL-related credentials in one place

**How**:
- Migrated fields to `CARL` item in 1Password `pi-cluster` vault
- Updated ExternalSecret to reference single item with multiple keys
- Git history: commit `bea800a` shows consolidation

### Decision: Use commit SHA tags initially, then switch to semver
**Why**:
- Development workflow used commit SHA tags (e.g., `sha-abc123`)
- Flux ImagePolicy regex pattern couldn't parse SHA tags
- Semver tags (v0.1.0, v0.2.0) work better with Flux's semantic versioning

**How**:
- Updated CARL CI/CD to publish semver releases
- Changed ImagePolicy to semver pattern: `^v(?P<version>[0-9]+\.[0-9]+\.[0-9]+)$`
- Current stable version: v0.3.3

**Trade-offs**:
- Requires manual semver tagging in CI/CD
- No automatic patch version bumps on every commit
- But: clearer versioning, better changelog management

## Architecture Changes

Added two new services to the cluster:

```
┌───────────────────────────────────────────────────────────────────┐
│                        carl namespace                             │
│                                                                   │
│  CARL (Canvas Assignment Reminder Liaison)                       │
│  • REST API server for Canvas LMS integration                    │
│  • Queries Ollama for LLM-enhanced intent detection              │
│  • Image: ghcr.io/mtgibbs/carl:0.3.3 (auto-deployed via Flux)   │
│  • Ingress: carl.lab.mtgibbs.dev                                 │
│  • Secrets: Canvas API credentials, Ollama URL from 1Password    │
│  • Resources: 100m CPU / 128Mi memory (requests)                 │
│                                                                   │
│  ConfigMap: carl-config                                           │
│  ExternalSecret: carl-config (syncs from 1Password CARL item)    │
└───────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────┐
│                       ollama namespace                            │
│                                                                   │
│  Ollama Local LLM Server                                          │
│  • Self-hosted language model inference (ARM64)                  │
│  • Pinned to pi5-worker-1 for performance                        │
│  • Auto-pulls model from 1Password config on startup             │
│  • Image: ollama/ollama:latest                                   │
│  • Service: ollama.ollama.svc.cluster.local:11434                │
│  • PVC: ollama-models (2Gi) for model storage                    │
│  • Resources: 500m-2 CPU / 2-4Gi memory                          │
│                                                                   │
│  ExternalSecret: ollama-config (syncs OLLAMA_MODEL)              │
└───────────────────────────────────────────────────────────────────┘

Data Flow:
  CARL → Ollama (ClusterIP service) → LLM inference
  CARL → Canvas API (external) → Assignment data
```

## Troubleshooting Steps Taken

### Issue 1: Image pull authentication failure
**Problem**: Initial deployment failed with `ErrImagePull` on GHCR image.

**Root Cause**: Private GitHub Container Registry requires authentication.

**Solution**:
- Made `ghcr.io/mtgibbs/carl` repository public
- Alternative would be creating imagePullSecret with GHCR token

### Issue 2: Security context prevented container start
**Problem**: Container failed with permission errors when `runAsNonRoot: true` was set.

**Root Cause**: CARL application code wasn't configured to run as non-root user.

**Solution**:
- Added proper user configuration (runAsUser: 1000)
- Ensured application code doesn't require root privileges
- Commit: `5d15ea8`

### Issue 3: Ollama startup script DNS resolution failure
**Problem**: `curl` commands in startup script couldn't resolve hostnames.

**Root Cause**: Used `curl` for health check, but base Ollama image doesn't include curl.

**Solution**:
- Switched to `ollama list` command for server readiness check
- Native Ollama CLI doesn't require DNS resolution
- More reliable than HTTP health checks during startup
- Commit: `41c43da`

### Issue 4: Flux ImagePolicy couldn't parse commit SHA tags
**Problem**: Auto-deployment not working with `sha-abc123` tag format.

**Root Cause**: Flux semver policy expects version numbers, not arbitrary strings.

**Solution**:
- Updated CI/CD to publish semver releases (v0.1.0, v0.2.0, etc.)
- Changed ImagePolicy pattern to match semver tags
- Commit: `094f9ab` switched to semver releases

## Version History

- **v0.1.0**: Initial deployment with Canvas API integration
- **v0.2.0**: Added Ollama integration for LLM features
- **v0.3.0**: Moved OLLAMA_MODEL to 1Password
- **v0.3.1**: Bug fixes (image automation)
- **v0.3.3**: Current stable release

## Repository Structure

```
clusters/pi-k3s/
├── carl/
│   ├── namespace.yaml
│   ├── deployment.yaml              # CARL app (ghcr.io/mtgibbs/carl:0.3.3)
│   ├── service.yaml                 # ClusterIP :8080
│   ├── ingress.yaml                 # carl.lab.mtgibbs.dev
│   ├── image-automation.yaml        # Flux ImagePolicy + ImageUpdateAutomation
│   ├── external-secret.yaml         # Syncs CARL item from 1Password
│   └── kustomization.yaml
├── ollama/
│   ├── namespace.yaml
│   ├── deployment.yaml              # Ollama server (pinned to pi5-worker-1)
│   ├── service.yaml                 # ClusterIP :11434
│   ├── pvc.yaml                     # 2Gi for model storage
│   ├── external-secret.yaml         # Syncs OLLAMA_MODEL from 1Password
│   └── kustomization.yaml
```

## Relevant Commits

```
565d437 - chore: update carl to ghcr.io/mtgibbs/carl:0.3.3
5f01753 - chore: update carl to ghcr.io/mtgibbs/carl:0.3.1
1518aea - chore: update carl to ghcr.io/mtgibbs/carl:0.3.0
2d4073a - chore: update carl to ghcr.io/mtgibbs/carl:0.2.0
41c43da - fix(ollama): Use ollama list for startup check
1826bfd - feat(ollama): Auto-pull model from 1Password config
63fccf3 - refactor(carl): Move OLLAMA_MODEL to 1Password
bea800a - refactor(carl): Consolidate config under CARL 1Password item
432de83 - feat(carl): Add Ollama integration for LLM features
8790bef - feat(ollama): Add local LLM server for CARL
094f9ab - chore(carl): Pin to semver release v0.1.0
5d15ea8 - fix(carl): Update security context and switch to semver policy
c56d9ca - fix(carl): Update image policy for commit SHA tags
51114dd - fix(carl): Remove runAsNonRoot constraint
281e600 - feat(carl): Add Canvas Assignment Reminder Liaison service
```

## Next Steps

- Monitor CARL logs to verify assignment reminder logic works as expected
- Tune Ollama resource limits based on actual inference performance
- Consider adding Prometheus metrics for CARL API endpoints
- Document CARL API endpoints and webhook integration
- Add health monitoring alerts for both services in Alertmanager
