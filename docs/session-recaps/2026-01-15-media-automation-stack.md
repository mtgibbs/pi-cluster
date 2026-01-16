# Session Recap - 2026-01-15

## Media Automation Stack Deployment

**Duration**: ~3 hours
**Status**: Completed and operational
**Namespace**: `media`
**Target Node**: `pi5-worker-1` (192.168.1.56)

---

## Completed

### Infrastructure Deployed
- **qBittorrent + Gluetun VPN**: Torrent client with Mullvad WireGuard sidecar for privacy
- **Prowlarr**: Centralized indexer manager (1337x configured via FlareSolverr)
- **FlareSolverr**: CloudFlare bypass proxy using headless Chromium (1Gi memory)
- **Sonarr**: TV show acquisition and organization automation
- **Radarr**: Movie acquisition and organization automation
- **Jellyseerr**: User-facing request management UI with Jellyfin authentication

### Storage Configuration
Created NFS PersistentVolumes on Synology NAS (192.168.1.60):
- `media-downloads` (10Gi) → `/volume1/cluster/media/downloads`
- `media-library` (500Gi) → `/volume1/cluster/media/video`

Created local-path PVCs for application configs (5Gi each):
- `qbittorrent-config`
- `prowlarr-config`
- `sonarr-config`
- `radarr-config`
- `jellyseerr-config`

### Service Integration
Configured complete data flow pipeline:
1. **Jellyseerr → Sonarr/Radarr**: Request submission with user authentication
2. **Sonarr/Radarr → Prowlarr**: Automatic indexer sync for search
3. **Prowlarr → FlareSolverr**: CloudFlare-protected indexer access (1337x)
4. **Sonarr/Radarr → qBittorrent**: Download client configuration
5. **qBittorrent → Mullvad VPN**: All torrent traffic routed through WireGuard
6. **NFS Storage → Jellyfin**: Media library auto-detection

### Ingress Configuration
All services accessible via TLS (cert-manager + Let's Encrypt):
- https://requests.lab.mtgibbs.dev (Jellyseerr)
- https://prowlarr.lab.mtgibbs.dev
- https://sonarr.lab.mtgibbs.dev
- https://radarr.lab.mtgibbs.dev
- https://qbit.lab.mtgibbs.dev

### Secrets Management
Created ExternalSecret for VPN credentials:
- **1Password Item**: `mullvad-credentials`
- **Keys**:
  - `WIREGUARD_PRIVATE_KEY`
  - `WIREGUARD_ADDRESSES`

---

## Key Decisions

### Decision 1: All Services Pinned to pi5-worker-1
**Why**: NFS mount reliability and consistent storage access patterns
**How**: nodeAffinity with `kubernetes.io/hostname: pi5-worker-1`
**Trade-off**: Single node dependency, but eliminates NFS mount inconsistencies across workers

### Decision 2: Gluetun VPN Sidecar Pattern
**Why**: Isolate all torrent traffic through Mullvad VPN for privacy
**How**: Gluetun container with NET_ADMIN capability, qBittorrent shares network namespace
**Result**: All downloads exit via WireGuard tunnel (USA servers)

### Decision 3: Prowlarr as Indexer Hub
**Why**: Eliminate duplicate indexer configuration across Sonarr/Radarr
**How**: Prowlarr automatically syncs configured indexers to *arr apps via API
**Benefit**: Single source of truth for indexer management

### Decision 4: FlareSolverr for CloudFlare Bypass
**Why**: 1337x indexer protected by CloudFlare challenges
**How**: Headless Chromium proxy solves challenges, tags match Prowlarr indexers
**Memory**: Increased from 512Mi to 1Gi (Chromium requirement)

### Decision 5: Separate NFS PVs for Downloads and Library
**Why**: Different retention policies (downloads are temporary, library is permanent)
**How**: Manual NFS PV provisioning with distinct paths on Synology
**Structure**:
- Downloads: `/volume1/cluster/media/downloads`
- Library: `/volume1/cluster/media/video/{tv,movies}`

---

## Issues Resolved

### Issue 1: NFS Mount Failures on pi5-worker-1
**Problem**: Pods failed to start with "Stale NFS file handle" errors
**Root Cause**: Previous NFS mount configuration changes left kernel client in inconsistent state
**Resolution**: Rebooted pi5-worker-1 to clear stale NFS handles
**Prevention**: Use consistent NFS mount paths, avoid frequent remounting

### Issue 2: FlareSolverr Container Crashes
**Problem**: FlareSolverr pod CrashLoopBackOff with OOM errors
**Root Cause**: Chromium headless browser requires more than 512Mi memory
**Resolution**: Increased memory limits to 1Gi
**Evidence**: Stable operation after memory increase

### Issue 3: Prowlarr Not Using FlareSolverr
**Problem**: 1337x indexer failing despite FlareSolverr running
**Root Cause**: Missing tag matching between FlareSolverr proxy and indexer configuration
**Resolution**: Added `flaresolverr` tag to both proxy definition and indexer settings
**Result**: Successful indexer queries through CloudFlare bypass

### Issue 4: Jellyfin TV Library Missing
**Problem**: Jellyfin only had Movies library, TV shows not visible
**Root Cause**: TV library not created during Jellyfin initial setup
**Resolution**: Added `/media/tv` library in Jellyfin web UI (NFS mount to `/volume1/cluster/media/video/tv`)
**Verification**: Library scan detected test TV show episodes

---

## Data Flow Architecture

```
User Request (Jellyseerr)
  ↓
Sonarr/Radarr receives request (authenticated via Jellyfin)
  ↓
Prowlarr searches configured indexers (1337x via FlareSolverr proxy)
  ↓
qBittorrent downloads torrent via Mullvad VPN (WireGuard tunnel)
  ↓
Files saved to NFS: /volume1/cluster/media/downloads
  ↓
Sonarr/Radarr renames and organizes files to library path
  ↓
Jellyfin auto-detects new media in /volume1/cluster/media/video/{tv,movies}
  ↓
User watches content in Jellyfin
```

---

## Files Created/Modified

### New Files
```
clusters/pi-k3s/media/
├── namespace.yaml              # media namespace
├── external-secret.yaml        # Mullvad VPN credentials from 1Password
├── nfs-pv.yaml                # NFS PVs for downloads and library
├── config-pvcs.yaml           # Local-path PVCs for app configs
├── qbittorrent.yaml           # Torrent client + Gluetun VPN sidecar
├── prowlarr.yaml              # Indexer manager
├── flaresolverr.yaml          # CloudFlare bypass proxy (1Gi memory)
├── sonarr.yaml                # TV show automation
├── radarr.yaml                # Movie automation
├── jellyseerr.yaml            # Request UI
└── kustomization.yaml         # Kustomize manifest
```

### Modified Files
```
clusters/pi-k3s/jellyfin/deployment.yaml  # Added /media/tv library path
```

### Relevant Commits
```
98d22d5 fix: increase FlareSolverr memory to 1Gi for Chromium
e26f05e feat: Add FlareSolverr for CloudFlare-protected indexers
33a6042 fix: Use direct NFS paths instead of subPaths
87d3c8e fix: Mount parent media directory with subPaths
19167ec fix: Remove NFS mountOptions causing mount failures
435bd47 fix: Remove non-existent cleanuparr image
c95bb6a feat: Add media automation stack with VPN
```

---

## Architecture Updates

### ARCHITECTURE.md Changes
1. Added `media namespace` section to Kubernetes Architecture diagram (line 438-505)
2. Added **Decision 35: Media Automation Stack with VPN-Protected Downloads** (line 1723-1843)

### Key Documentation Sections
- **Namespace Layout**: Comprehensive overview of all 6 media services
- **Storage Architecture**: NFS PVs and local-path PVCs explained
- **Data Flow**: End-to-end request-to-watch pipeline
- **Security**: VPN isolation, CloudFlare bypass, secrets management
- **Integration**: Jellyfin OAuth authentication and library scanning

---

## Configuration Notes

### Prowlarr Indexer Configuration
- **Indexer**: 1337x
- **Proxy**: FlareSolverr (http://flaresolverr:8191)
- **Tags**: `flaresolverr` (must match proxy tags)
- **Sync**: Automatic to Sonarr and Radarr

### qBittorrent Download Client
- **Username**: admin
- **Password**: adminadmin (default, change via web UI)
- **Port**: 8080
- **Category Mappings**:
  - Sonarr → `tv-sonarr`
  - Radarr → `radarr`

### Jellyseerr Integration
- **Jellyfin URL**: http://jellyfin.jellyfin.svc.cluster.local:8096
- **Authentication**: Jellyfin user accounts (OAuth)
- **Sonarr URL**: http://sonarr.media.svc.cluster.local:8989
- **Radarr URL**: http://radarr.media.svc.cluster.local:7878

---

## Resource Usage

### Memory Allocation
| Service | Requests | Limits |
|---------|----------|--------|
| Gluetun VPN | 64Mi | 256Mi |
| qBittorrent | 128Mi | 512Mi |
| Prowlarr | 128Mi | 512Mi |
| **FlareSolverr** | **512Mi** | **1Gi** |
| Sonarr | 128Mi | 512Mi |
| Radarr | 128Mi | 512Mi |
| Jellyseerr | 128Mi | 512Mi |

**Total**: ~1.2Gi requests, ~3.8Gi limits (single node: pi5-worker-1)

### CPU Allocation
| Service | Requests | Limits |
|---------|----------|--------|
| Gluetun VPN | 50m | 200m |
| qBittorrent | 100m | 500m |
| Prowlarr | 100m | 500m |
| FlareSolverr | 100m | 500m |
| Sonarr | 100m | 500m |
| Radarr | 100m | 500m |
| Jellyseerr | 100m | 500m |

**Total**: ~750m requests, ~3.7 CPUs limits

### Storage Usage
- **NFS Downloads**: 10Gi (shared across all apps)
- **NFS Library**: 500Gi (movies + TV shows for Jellyfin)
- **Config PVCs**: 5Gi × 5 = 25Gi (local-path on pi5-worker-1)

---

## Testing & Verification

### Smoke Tests Performed
1. **VPN Connectivity**: Verified qBittorrent traffic exits via Mullvad (USA IP)
2. **Prowlarr Indexer**: Successfully searched 1337x via FlareSolverr proxy
3. **Sonarr/Radarr Integration**: Confirmed Prowlarr indexers synced automatically
4. **Download Client**: qBittorrent accessible from Sonarr/Radarr
5. **NFS Mounts**: Downloads saved to Synology NAS successfully
6. **Jellyseerr Auth**: Logged in with Jellyfin user account
7. **Ingress TLS**: All 5 HTTPS endpoints respond with valid certificates

### Test Request Flow
1. Logged into Jellyseerr with Jellyfin account
2. Searched for TV show: "The Office"
3. Submitted request to Sonarr
4. Verified Sonarr received request and searched Prowlarr
5. Confirmed qBittorrent received torrent and began downloading
6. Observed files landing in `/volume1/cluster/media/downloads`
7. (Pending): File moves to `/volume1/cluster/media/video/tv` after download completion

---

## Security Posture

### VPN Isolation
- All torrent traffic encrypted via Mullvad WireGuard
- qBittorrent cannot egress without VPN tunnel active
- Gluetun container restart kills qBittorrent connections

### Secrets Management
- VPN credentials synced from 1Password (never committed to Git)
- API keys stored in application configs (persisted on local-path PVCs)
- Future enhancement: Move API keys to 1Password ExternalSecrets

### Network Policies
- FlareSolverr only accessible within cluster (ClusterIP)
- qBittorrent web UI exposed via Ingress (authenticated)
- All services require HTTPS via nginx-ingress + cert-manager

---

## Next Steps

### Immediate Tasks
- [ ] Monitor download completion and file organization
- [ ] Verify Jellyfin library scanning picks up new media
- [ ] Test end-to-end workflow with real content request
- [ ] Configure quality profiles in Sonarr/Radarr (720p/1080p)

### Future Enhancements
- [ ] Add more indexers to Prowlarr (YTS, RARBG alternatives)
- [ ] Configure Sonarr/Radarr quality profiles and custom formats
- [ ] Set up automated cleanup of completed downloads
- [ ] Add Prometheus metrics for *arr apps (if exporters exist)
- [ ] Consider Bazarr for subtitle automation
- [ ] Implement Prometheus alerting for failed downloads or stuck queues
- [ ] Add Homepage dashboard widgets for *arr apps

### Monitoring Considerations
- No native Prometheus exporters for *arr apps (limited observability)
- Consider scraping application logs for error patterns
- Monitor NFS mount health on pi5-worker-1
- Track qBittorrent download success rate

---

## Lessons Learned

### NFS Mount Reliability
- Consistent NFS paths eliminate mount inconsistency across pod restarts
- Avoid frequent NFS mount configuration changes (causes stale handles)
- Node reboots are sometimes necessary to clear kernel NFS client state
- Always verify NFS mounts with `mount | grep nfs` on worker nodes

### VPN Sidecar Pattern
- NET_ADMIN capability required for VPN tunnel creation
- Shared network namespace ensures traffic routing through VPN
- Gluetun is excellent for multi-provider VPN support (Mullvad, NordVPN, etc.)
- Always test VPN IP leakage with public IP check tools

### FlareSolverr Resource Requirements
- Chromium headless browser needs 1Gi memory minimum
- Initial 512Mi allocation caused frequent OOMKills
- Tag matching between proxy and indexers is critical (not automatic)
- Monitor FlareSolverr logs for CloudFlare challenge success rate

### *arr Suite Configuration
- Prowlarr eliminates 90% of indexer configuration duplication
- API keys must be manually generated in each app
- Quality profiles are critical for disk space management
- Download client categories ensure proper file organization

### Kubernetes nodeAffinity
- Pinning workloads to single node simplifies NFS mount management
- Trade-off: no HA, but eliminates storage access inconsistencies
- Always document why services are pinned to specific nodes
- Consider PVC node affinity for stateful workloads

---

## References

### Documentation
- [Gluetun VPN Documentation](https://github.com/qdm12/gluetun)
- [Prowlarr Setup Guide](https://wiki.servarr.com/prowlarr)
- [FlareSolverr GitHub](https://github.com/FlareSolverr/FlareSolverr)
- [Kubernetes NFS PersistentVolumes](https://kubernetes.io/docs/concepts/storage/volumes/#nfs)

### Internal Docs
- `/Users/mtgibbs/dev/pi-cluster/ARCHITECTURE.md` - Decision 35 (line 1723-1843)
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/media/` - Deployment manifests

### Commit Range
- Initial deployment: `c95bb6a` (feat: Add media automation stack with VPN)
- Final stable state: `98d22d5` (fix: increase FlareSolverr memory to 1Gi for Chromium)

---

**Session Summary**: Successfully deployed complete media automation pipeline with VPN-protected downloads, centralized indexer management, and user-facing request system. Resolved NFS mount issues, FlareSolverr memory constraints, and CloudFlare bypass configuration. All services operational and integrated with existing Jellyfin media server.
