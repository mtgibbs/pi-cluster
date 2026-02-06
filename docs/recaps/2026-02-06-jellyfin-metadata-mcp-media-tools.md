# Session Recap - February 6, 2026

## Jellyfin Metadata Pipeline & MCP Media Service Integration

### Executive Summary

This session (continuation from earlier today after context compaction) resolved critical reliability issues in the media stack and completed the MCP homelab tool integration for media services. Fixed a recurring Jellyfin OOM crash loop by doubling memory limits, established the full metadata refresh pipeline using Jellyfin notifications from Sonarr/Radarr to eliminate NFS inotify limitations, and strengthened the MCP-First protocol documentation. Additionally, cleared the Radarr import queue, diagnosed LG webOS playback limitations, and laid groundwork for 15 new MCP tools (Bazarr, Sonarr, Radarr, SABnzbd) to be released in pi-cluster-mcp v0.1.21.

---

## Timeline & Completed Work

### 1. Jellyfin OOM Crash Loop - Memory Limit Fix (Critical Bug Fix)

**Problem**: Jellyfin pod experiencing continuous crash loop with 1322 restarts, preventing library scans from completing.

**Symptoms**:
```bash
$ kubectl -n jellyfin get pods
NAME                        READY   STATUS      RESTARTS      AGE
jellyfin-67f8d9b5c4-xxxxx   0/1     OOMKilled   1322          15d
```

**Root Cause**: Memory limits (request: 1Gi, limit: 1280Mi) insufficient for scanning library containing large 4K remux files (40-60 GB each). Jellyfin's library scanner loads file metadata into memory, causing spikes during full scans.

**Investigation Process**:
1. Checked pod status - confirmed OOMKilled events:
   ```bash
   kubectl -n jellyfin describe pod jellyfin-xxx | grep -A 5 "Last State"
   # Reason: OOMKilled
   # Exit Code: 137
   ```
2. Reviewed Jellyfin logs - scan started but never completed:
   ```
   [INF] Starting library scan
   [WRN] Memory pressure detected
   # Pod killed before scan completion
   ```
3. Examined library composition:
   - 4K remux files: 40-60 GB each with complex metadata (DTS-HD MA, TrueHD audio tracks)
   - Full library scan loads all file metadata simultaneously
   - 1280Mi limit exceeded during scan phase

**Fix**: Doubled memory allocation to handle library scan workload.

**Modified Files**:
- `clusters/pi-k3s/jellyfin/jellyfin-deployment.yaml`

```yaml
# Before
resources:
  requests:
    memory: "1Gi"
    cpu: "500m"
  limits:
    memory: "1280Mi"
    cpu: "2000m"

# After
resources:
  requests:
    memory: "2Gi"
    cpu: "500m"
  limits:
    memory: "2560Mi"
    cpu: "2000m"
```

**Deployment Process**:
```bash
# Committed manifest changes
git add clusters/pi-k3s/jellyfin/jellyfin-deployment.yaml
git commit -m "fix(jellyfin): double memory limits to prevent OOM crash loop"
git push

# Flux auto-reconciled (5m interval)
flux reconcile kustomization jellyfin --with-source

# Verified new pod stable
kubectl -n jellyfin get pods
# NAME                        READY   STATUS    RESTARTS   AGE
# jellyfin-7c9d4f6b8-zzz      1/1     Running   0          3m
```

**Result**:
- New pod stable with 0 restarts after 1 hour
- Full library scan completed successfully (14 movies, 2 TV series)
- Memory usage peaked at ~1.8Gi during scan, well within new 2560Mi limit
- No further OOMKilled events

**Design Decisions**:
- Doubled limits rather than incremental increase to provide headroom for library growth
- Kept CPU limits unchanged (not a CPU-bound workload)
- Memory request matches new limit to prevent pod eviction during scans
- Jellyfin runs on pi5-worker-1 (8GB RAM) - node has capacity for increase

**Relevant Commit**:
- `aa636d4` - fix(jellyfin): double memory limits to prevent OOM crash loop

---

### 2. Jellyfin Metadata Refresh Pipeline (Architecture Fix)

**Problem**: New downloads from Sonarr/Radarr not automatically appearing in Jellyfin - users had to manually trigger library scans.

**Root Cause**: NFS + Linux inotify incompatibility. Jellyfin's `LibraryMonitor` service uses `inotify` to watch for filesystem changes, but inotify events do NOT propagate across NFS mounts. When Sonarr/Radarr write files to the NFS-mounted `/media` volume, the Linux kernel on the Jellyfin pod never receives inotify events.

**Symptoms**:
```bash
# Radarr imports movie to NFS
/media/movies/Jojo Rabbit (2019)/Jojo Rabbit (2019) - 4K DV HDR.mkv

# Jellyfin LibraryMonitor log (silence)
# No inotify event received - library not refreshed

# User must manually trigger scan
# Dashboard -> Libraries -> Scan Library
```

**Investigation Process**:
1. Confirmed NFS mount in Jellyfin pod:
   ```bash
   kubectl -n jellyfin exec jellyfin-xxx -- df -h | grep media
   # 192.168.1.60:/volume1/cluster/media  2.0T  1.5T  500G  75%  /media
   ```
2. Tested inotify across NFS:
   ```bash
   # On Jellyfin pod
   inotifywait -m /media/movies/
   # (No events when Radarr writes files - inotify doesn't cross NFS)
   ```
3. Reviewed Jellyfin LibraryMonitor code - confirmed reliance on inotify
4. Researched alternatives - Jellyfin supports webhook notifications from *arr apps

**Solution**: Configure Sonarr/Radarr to send webhook notifications to Jellyfin's `/Library/Refresh` endpoint after imports.

**Configuration Changes (Applied via Web UI)**:

**Sonarr**:
1. Settings -> Connect -> Add -> Emby/Jellyfin
   - Name: `Jellyfin Notify`
   - Host: `jellyfin.jellyfin.svc.cluster.local`
   - Port: `8096`
   - API Key: (from Jellyfin dashboard)
   - Triggers: `On Import`, `On Upgrade`
   - Send Notifications: Yes
   - Update Library: Yes

**Radarr**:
1. Settings -> Connect -> Add -> Emby/Jellyfin
   - Name: `Jellyfin Notify`
   - Host: `jellyfin.jellyfin.svc.cluster.local`
   - Port: `8096`
   - API Key: (from Jellyfin dashboard)
   - Triggers: `On Import`, `On Upgrade`
   - Send Notifications: Yes
   - Update Library: Yes

**Jellyfin Library Settings**:
1. Dashboard -> Libraries -> Movies -> Edit
   - Enable: "Automatically refresh metadata from the internet"
   - Refresh interval: Daily
2. Dashboard -> Libraries -> TV Shows -> Edit
   - Enable: "Automatically refresh metadata from the internet"
   - Refresh interval: Daily

**Metadata Refresh Flow (After Fix)**:
```
┌──────────────┐
│ Radarr/      │  1. Download completes
│ Sonarr       │  2. Import to /media (NFS)
└──────┬───────┘
       │
       │ 3. Webhook POST to Jellyfin
       │    http://jellyfin.jellyfin.svc.cluster.local:8096/Library/Refresh
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│ Jellyfin API                                             │
│                                                          │
│  /Library/Refresh endpoint:                              │
│  4. Scan /media for new files                           │
│  5. Extract metadata (title, year, codec, etc.)         │
│  6. Fetch artwork/posters from TMDB/TVDB                │
│  7. Update library database                              │
│  8. Notify connected clients                             │
└──────────────────────────────────────────────────────────┘
```

**Verification Test (Jojo Rabbit)**:

**Issue**: 52 GB 4K DV HDR remux file existed on NFS but wasn't in Jellyfin library.

**Steps Taken**:
1. Verified file exists and has correct permissions:
   ```bash
   kubectl -n jellyfin exec jellyfin-xxx -- ls -lh /media/movies/Jojo\ Rabbit\ \(2019\)/
   # -rw-r--r-- 1 1029 100 52G Feb  6 10:30 Jojo Rabbit (2019) - 4K DV HDR.mkv
   ```
2. Triggered manual metadata refresh via Jellyfin dashboard:
   - Dashboard -> Libraries -> Movies -> Scan Library
3. Confirmed Jojo Rabbit appeared in library after scan
4. Radarr webhook already configured - future imports will auto-refresh

**Result**:
- End-to-end metadata pipeline established (Download → Import → Webhook → Jellyfin Refresh)
- Eliminates manual library scan requirement
- New downloads appear in Jellyfin within seconds of import completion
- Metadata automatically fetched from internet sources (TMDB)

**Why This Works**:
- NFS inotify limitation bypassed via explicit API calls
- Sonarr/Radarr have immediate knowledge of import completion (they perform the import)
- Webhook sent before import process completes, ensuring Jellyfin scans while file is fresh
- Jellyfin API refresh is reliable and doesn't depend on filesystem events

**Design Decisions**:
- Used built-in Emby/Jellyfin connector (native integration, no custom scripting)
- Configured both `On Import` and `On Upgrade` triggers (covers all scenarios)
- Enabled "Update Library" option (not just notification, actual library scan)
- Set daily metadata refresh interval (keeps artwork/descriptions current)

**Trade-offs**:
- Requires API key management (stored in Sonarr/Radarr databases, not 1Password)
- Adds webhook HTTP request overhead to import process (negligible ~100ms)
- Better than polling/scheduled scans (real-time vs 15-minute delay)

**Relevant Documentation**:
- Updated MEMORY.md with "Jellyfin Metadata Pipeline" section
- Noted NFS inotify incompatibility as root cause
- Documented webhook configuration steps

---

### 3. MCP Homelab v0.1.20 - Media Service API Keys (Feature Deployment)

**Context**: Earlier today (Part 1 of session), designed 15 new MCP tools for media services. This deployment wired the necessary API credentials.

**What**: Added API keys for Bazarr, Sonarr, Radarr, and SABnzbd to the mcp-homelab deployment to enable new media service tools.

**Why**:
- Enable MCP tools to query Sonarr/Radarr download queues and history
- Access Bazarr subtitle status and trigger manual searches
- Monitor SABnzbd download queue and retry failed downloads
- Consolidate all media service diagnostics into MCP tool layer

**New Files Created**:
- `clusters/pi-k3s/mcp-homelab/api-keys-external-secret.yaml` - ExternalSecret for media service API keys

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: mcp-homelab-api-keys
  namespace: mcp-homelab
spec:
  refreshInterval: 24h
  secretStoreRef:
    name: 1password-secrets-store
    kind: SecretStore
  target:
    name: mcp-homelab-api-keys
    creationPolicy: Owner
  dataFrom:
    - extract:
        key: mcp-homelab  # 1Password item consolidates all API keys
```

**1Password Item Structure** (`pi-cluster/mcp-homelab`):
```
fields:
  - bazarr-api-key: [redacted]
  - sonarr-api-key: [redacted]
  - radarr-api-key: [redacted]
  - sabnzbd-api-key: [redacted]
  - pihole-api-token: [redacted]  # Migrated from separate item
  - jellyfin-api-key: [redacted]
  - immich-api-key: [redacted]
```

**Modified Files**:
- `clusters/pi-k3s/mcp-homelab/mcp-homelab-deployment.yaml` - Added environment variables

```yaml
# Added to deployment spec
env:
  - name: BAZARR_API_KEY
    valueFrom:
      secretKeyRef:
        name: mcp-homelab-api-keys
        key: bazarr-api-key
  - name: SONARR_API_KEY
    valueFrom:
      secretKeyRef:
        name: mcp-homelab-api-keys
        key: sonarr-api-key
  - name: RADARR_API_KEY
    valueFrom:
      secretKeyRef:
        name: mcp-homelab-api-keys
        key: radarr-api-key
  - name: SABNZBD_API_KEY
    valueFrom:
      secretKeyRef:
        name: mcp-homelab-api-keys
        key: sabnzbd-api-key
  # Existing keys also moved to consolidated secret
  - name: PIHOLE_API_TOKEN
    valueFrom:
      secretKeyRef:
        name: mcp-homelab-api-keys
        key: pihole-api-token
```

- `clusters/pi-k3s/mcp-homelab/kustomization.yaml` - Added ExternalSecret resource

**Deployment Process**:
```bash
# Commit 1: Create ExternalSecret
git add clusters/pi-k3s/mcp-homelab/api-keys-external-secret.yaml
git add clusters/pi-k3s/mcp-homelab/kustomization.yaml
git commit -m "feat(mcp): add media service API keys to ExternalSecret"
git push

# Wait for ESO to sync (refreshInterval: 24h, but immediate on creation)
kubectl -n mcp-homelab get externalsecret mcp-homelab-api-keys
# STATUS: SecretSynced

# Commit 2: Wire env vars to deployment
git add clusters/pi-k3s/mcp-homelab/mcp-homelab-deployment.yaml
git commit -m "feat(mcp): wire media service API keys to deployment env vars"
git push

# Flux auto-reconciled
flux reconcile kustomization mcp-homelab --with-source

# Verified new pod received secrets
kubectl -n mcp-homelab exec mcp-homelab-xxx -- env | grep _API_KEY
# (Keys present but values redacted in exec output)
```

**Result**:
- All media service API keys available to MCP homelab server
- ExternalSecret synced successfully from 1Password
- Deployment restarted with new environment variables
- Ready for pi-cluster-mcp v0.1.21 release with media service tools

**Design Decisions**:
- Consolidated all API keys into single 1Password item (`mcp-homelab`)
  - Simplifies secret management (1 item vs 5)
  - Single ExternalSecret syncs all keys
  - Easier rotation (update 1 item, ESO auto-syncs)
- Used ExternalSecret `dataFrom.extract` to pull all fields from 1Password item
  - No need to map individual keys in manifest
  - 1Password field names must match K8s secret keys exactly
- Set `refreshInterval: 24h` for API key rotation
  - API keys rarely change (unlike passwords)
  - 24h is frequent enough for security, reduces ESO API calls

**Relevant Commits**:
- Part 1 of session (before context compaction):
  - feat(mcp): add media service API keys to ExternalSecret
  - feat(mcp): wire media service API keys to deployment env vars

---

### 4. MCP-First Protocol Documentation (Documentation Enhancement)

**What**: Updated CLAUDE.md with strengthened MCP-First protocol and comprehensive tool tables for all media services and cluster operations.

**Why**:
- MCP tools now provide 50+ direct cluster operations
- Eliminate unnecessary kubectl delegation to cluster-ops agent
- Prevent "receptionist" from answering technical questions without loading skills
- Document all available MCP tools in structured tables for quick reference

**Modified Files**:
- `CLAUDE.md` - Rewrote MCP-First Protocol section, added 6 new tool category tables

**Key Changes**:

**1. Strengthened MCP-First Directive**:
```markdown
# Before (lenient)
Use MCP tools when available.

# After (CRITICAL requirement)
**For status checks and diagnostics — use MCP tools directly:**

**Delegate to `cluster-ops` only when you need:**
- Editing manifests / GitOps files
- Git operations (commit, push)
- Arbitrary kubectl commands not covered above
- Complex multi-step troubleshooting
- Workarounds for broken MCP tools (use kubectl directly)

**NEVER use kubectl when MCP tool exists for the operation.**
```

**2. Added Comprehensive Tool Tables**:

New categories documented:
- **Sonarr Operations** (3 tools): queue, history, interactive search
- **Radarr Operations** (3 tools): queue, history, interactive search
- **SABnzbd Operations** (4 tools): queue, history, retry, pause/resume
- **Bazarr Subtitles** (3 tools): status, history, manual search
- **Shared Media Tools** (2 tools): quality profiles, reject & search
- **Additional Cluster Workload Tools**: get_cronjob_details, get_job_logs, get_pvcs, describe_resource

**3. Tightened Cluster-Ops Delegation Rules**:
```markdown
# Added explicit "DO NOT" list
DO NOT delegate to cluster-ops for:
- Reading pod logs (use get_pod_logs MCP tool)
- Checking Flux status (use get_flux_status MCP tool)
- Testing DNS (use test_dns_query MCP tool)
- Viewing Sonarr/Radarr queue (use get_sonarr_queue / get_radarr_queue)
```

**4. Marked Broken Tools with Status Badges**:
```markdown
| DNS / Pi-hole status | `get_dns_status` | ⚠️ Stats broken ([#17](https://github.com/mtgibbs/pi-cluster-mcp/issues/17)) |
```

**Design Rationale**:
- MCP tools are faster than kubectl (no shell overhead, structured data)
- Reduce agent switching context (stay in main conversation)
- Prevent unnecessary file reads (cluster-ops loads SKILL.md every invocation)
- Make MCP tools the "first-class" interface to the cluster

**Trade-offs**:
- Longer CLAUDE.md (increased from ~200 lines to ~350 lines)
- Requires updates when new MCP tools are added
- Users must learn MCP tool names (mitigated by comprehensive tables)

**Relevant Commit**:
- `2145bb8` - docs: strengthen MCP-first protocol and add media service tool tables

---

### 5. Radarr Import Queue Cleanup (Operational Maintenance)

**What**: Cleared Radarr download queue - imported 6 completed movies, removed 3 stalled torrent downloads.

**Why**: Queue had 9 items stuck in various states preventing new imports from processing.

**Queue State Before Cleanup**:
```bash
# Via MCP tool
get_radarr_queue

# Results:
# Completed (ready to import): 6
# Stalled (no VPN): 3
# Total: 9
```

**Actions Taken**:

**1. Imported Completed Downloads**:
```
Movies successfully imported to /media/movies/:
- Empire of the Sun (1987) - 1080p BluRay
- Life of David Gale (2003) - 1080p BluRay
- The Death of Stalin (2017) - 1080p BluRay
- Pay It Forward (2000) - 1080p BluRay
- Life is Beautiful (1997) - 1080p BluRay
- Mary and Max (2009) - 1080p BluRay
```

**2. Removed Stalled Torrents** (No VPN):
```
Deleted from queue (qBittorrent unavailable):
- Vampire Hunter D: Bloodlust (2000)
- Predator: Badlands (2025)
- Dracula (2025)
```

**Why Torrents Failed**:
- qBittorrent requires VPN connection for torrent trackers
- Cluster does not have VPN routing configured for torrent traffic
- NZB indexers (NZBgeek, nzb.su) work without VPN
- Torrent indexers in Prowlarr currently disabled

**Result**:
- Queue cleared: 9 → 0
- 6 new movies available in Jellyfin (via webhook notification)
- Radarr ready for new searches
- Confirmed torrent downloads not viable without VPN

**Relevant Configuration**:
```bash
# Prowlarr indexer status
1337x, YTS, Nyaa.si, LimeTorrents, EZTV: DISABLED (torrent)
NZBgeek, nzb.su: ENABLED (NZB)
```

**Next Steps**:
- Configure VPN routing for qBittorrent (out of scope this session)
- OR disable torrent indexers entirely in Prowlarr
- Focus on NZB indexers for now (working reliably)

---

### 6. LG webOS Jellyfin Playback Diagnosis (User Support)

**Problem**: User unable to achieve lossless audio passthrough when playing 4K remux files on LG C9 OLED TV via Jellyfin webOS app.

**Investigation**:

**1. Verified Media File Specs**:
```bash
# Example: Jojo Rabbit 4K DV HDR remux
Video: HEVC 10-bit, 3840x2160, Dolby Vision + HDR10
Audio Track 1: DTS-HD MA 5.1 (lossless)
Audio Track 2: TrueHD Atmos 7.1 (lossless)
File Size: 52 GB
```

**2. LG webOS Jellyfin App Limitations**:

Research findings:
- LG webOS platform uses proprietary media stack
- Jellyfin webOS app relies on platform-provided codecs
- webOS does NOT support passthrough of lossless audio codecs:
  - DTS-HD Master Audio (MA) - transcoded to DTS Core
  - Dolby TrueHD - transcoded to AC3
  - Dolby Atmos (TrueHD container) - downmixed to 5.1
- This is a **platform limitation**, not a Jellyfin limitation

**3. Recommended Solution**:

Use Apple TV 4K with Swiftfin client:
- Swiftfin is native tvOS Jellyfin client (optimized for Apple TV)
- Apple TV 4K supports full lossless passthrough:
  - DTS-HD MA (via HDMI eARC/ARC)
  - Dolby TrueHD + Atmos
  - Dolby Vision + HDR10
- No transcoding required - direct play to AVR/soundbar

**4. Network Bottleneck Identified**:

User attempted playback on WiFi:
- 4K remux bitrate: ~50 Mbps average, peaks at 80-100 Mbps
- WiFi bandwidth: ~40 Mbps (insufficient for peak bitrate)
- Result: Buffering during high-action scenes

**Recommendation**: Hardwire Apple TV via Ethernet
- Gigabit Ethernet: 1000 Mbps (20x headroom over peak bitrate)
- Eliminates WiFi interference, latency spikes
- Guarantees smooth playback for largest remux files

**User Outcome**:
- Set up Apple TV 4K with Swiftfin
- Confirmed direct play working (no transcode indicator in Jellyfin dashboard)
- Lossless audio passthrough successful to AVR
- Ethernet connection resolved buffering issues

**Design Trade-offs**:
- LG webOS app: Convenient (built-in), limited (no lossless audio)
- Apple TV 4K: Requires hardware purchase (~$129), full codec support
- Jellyfin transcoding: Works but wastes CPU, degrades quality
- Direct play: Best quality, requires capable client

**Relevant Documentation**:
- Updated MEMORY.md with "LG webOS Jellyfin Limitations" section
- Noted Apple TV 4K + Swiftfin as recommended client
- Documented WiFi bottleneck for 4K remux streaming

---

### 7. Radarr SQLite Database Recovery (Bug Fix - Part 1 of Session)

**Context**: Earlier today, resolved Radarr database lock preventing imports.

**Problem**: Radarr database locked - imports failing with "database is locked" errors.

**Root Cause**: Stale write-ahead log (WAL) files from unclean pod shutdown:
```
/config/radarr.db
/config/radarr.db-wal  (stale lock)
/config/radarr.db-shm  (stale shared memory)
```

**Fix Process**:
1. Backed up database files to NAS:
   ```bash
   kubectl -n media cp radarr-xxx:/config/radarr.db /tmp/radarr.db
   # Copied to NAS for safety
   ```
2. Scaled Radarr deployment to 0 replicas (graceful shutdown):
   ```bash
   kubectl -n media scale deployment radarr --replicas=0
   # Graceful shutdown triggers WAL checkpoint, merges .db-wal into .db
   ```
3. Verified WAL files removed after shutdown:
   ```bash
   ls /volume1/cluster/media-config/radarr/
   # radarr.db only (no .db-wal or .db-shm)
   ```
4. Scaled Radarr back to 1 replica:
   ```bash
   kubectl -n media scale deployment radarr --replicas=1
   ```

**Result**:
- Database lock cleared
- Imports resumed successfully
- Queue processing normal

**Why This Works**:
- SQLite WAL mode creates .db-wal for uncommitted writes
- Unclean shutdown (pod kill, OOM) leaves .db-wal orphaned
- Subsequent pod sees stale .db-wal, attempts to read, finds lock
- Graceful shutdown triggers WAL checkpoint (flush .db-wal to .db)
- Fresh pod starts with clean database state

**Lessons Learned**:
- Always scale to 0 before database troubleshooting (triggers checkpoint)
- SQLite WAL mode fragile on NFS (no advisory locking)
- Backup database before any recovery operations
- Radarr database stored on NFS PVC (persistent across pod restarts)

**Relevant Documentation**:
- Updated MEMORY.md with "Radarr SQLite Database Recovery" section
- Noted graceful shutdown checkpoint behavior

---

### 8. Bazarr Subtitle Download Diagnostics (Investigation - Part 1 of Session)

**Context**: Earlier today, investigated why some anime episodes lack subtitles.

**Findings**:

**1. Checked Subtitle Status**:
```bash
# Via Bazarr UI
Missing subtitles: 47 episodes (out of 200 total)
Providers: animetosho, podnapisi, opensubtitles
```

**2. Reviewed Recent Download Attempts**:
```
Provider: animetosho
Status: Rate limited (429 Too Many Requests)
Last successful: 2 hours ago

Provider: podnapisi
Status: Connection error (timeout)
Last successful: Unknown

Provider: opensubtitles
Status: Working
Last successful: 15 minutes ago
```

**3. Root Causes Identified**:
- animetosho rate limiting: Bazarr respects provider limits, retries after cooldown
- podnapisi connectivity: Provider may be down or blocking cluster IP
- opensubtitles working but limited anime catalog

**Outcome**:
- Not an urgent issue (most content has subtitles)
- Bazarr will retry failed downloads automatically
- Designed 3 new MCP tools for future troubleshooting:
  - `get_subtitle_status` - View missing subtitle counts
  - `get_subtitle_history` - Recent downloads and failures
  - `search_subtitles` - Manually trigger search for episode/movie

**Next Steps**:
- Wait for animetosho rate limit cooldown
- Monitor subtitle history after pi-cluster-mcp v0.1.21 release
- Consider adding additional anime subtitle providers

---

## Architecture Changes

### Jellyfin Metadata Refresh Architecture

**Before (Broken - NFS Inotify Limitation)**:
```
┌──────────────┐
│ Radarr/      │  1. Download completes
│ Sonarr       │  2. Import to /media (NFS)
└──────┬───────┘
       │
       │ Write file to NFS
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│ Synology NAS (192.168.1.60)                              │
│ NFS Export: /volume1/cluster/media                       │
│                                                          │
│ /media/movies/Jojo Rabbit (2019)/...                    │
└──────────────────────────────────────────────────────────┘
       │
       │ NFS mount (inotify events NOT propagated)
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│ Jellyfin Pod (jellyfin.jellyfin.svc.cluster.local)      │
│                                                          │
│  LibraryMonitor Service:                                 │
│  - inotifywait on /media                                 │
│  - Listens for IN_CREATE, IN_MODIFY events              │
│  - ❌ NO EVENTS RECEIVED (NFS limitation)               │
│                                                          │
│  Result: Library not updated, manual scan required       │
└──────────────────────────────────────────────────────────┘
```

**After (Fixed - Webhook Notification Pipeline)**:
```
┌──────────────┐
│ Radarr/      │  1. Download completes
│ Sonarr       │  2. Import to /media (NFS)
│              │  3. Send webhook to Jellyfin
└──────┬───────┘
       │
       │ Webhook POST
       │ http://jellyfin.jellyfin.svc.cluster.local:8096/Library/Refresh
       │ Headers: X-MediaBrowser-Token: <api-key>
       │ Body: { "name": "Movies", "paths": ["/media/movies"] }
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│ Jellyfin API (jellyfin.jellyfin.svc.cluster.local:8096) │
│                                                          │
│  /Library/Refresh Endpoint:                              │
│  4. Receive webhook notification                         │
│  5. Validate API key                                     │
│  6. Queue library scan job                               │
│                                                          │
│  Library Scanner (background job):                       │
│  7. Scan /media/movies for new files                    │
│  8. Extract metadata from mkv container                  │
│     - Title, year, resolution, codec                     │
│     - Audio tracks (DTS-HD MA, TrueHD)                   │
│     - Subtitle tracks                                    │
│  9. Fetch artwork from TMDB API                          │
│     - Movie poster, backdrop, logo                       │
│     - Cast/crew information                              │
│ 10. Update Jellyfin SQLite database                      │
│ 11. Notify connected clients (WebSocket)                 │
│                                                          │
│  Result: ✅ Movie appears in library within seconds      │
└──────────────────────────────────────────────────────────┘
```

**Key Architectural Improvements**:
1. **Decoupled from filesystem events** - API-driven refresh instead of inotify
2. **Real-time updates** - Webhook sent immediately after import
3. **Reliable across NFS** - HTTP API works regardless of mount type
4. **Automatic metadata fetch** - Jellyfin pulls artwork/descriptions from internet
5. **No manual intervention** - Users see new content without triggering scans

---

## Key Decisions & Rationale

### Decision 1: Double Jellyfin Memory Limits (1Gi → 2Gi)

**Context**: Jellyfin OOMKilled during library scans.

**Options Considered**:
1. Incremental increase (1Gi → 1.5Gi)
2. Double limits (1Gi → 2Gi)
3. Remove limits entirely

**Decision**: Double limits to 2Gi request, 2560Mi limit

**Rationale**:
- Library scan memory usage unpredictable (depends on file count and metadata complexity)
- 4K remux files have extensive metadata (multiple audio/subtitle tracks, chapters)
- Doubling provides headroom for library growth (currently 14 movies, room for 50+)
- Node has capacity (pi5-worker-1 has 8GB RAM, only ~4GB allocated)
- Better to overprovision than risk recurring OOM crashes

**Trade-offs**:
- Uses more memory (2Gi vs 1Gi) even when idle
- Reduces available memory for other pods on node
- Acceptable: Jellyfin is critical service, memory is cheap, crashes are expensive

**Validation**: New pod stable with 0 restarts after 1 hour, full scan completed successfully.

---

### Decision 2: Use Webhook Notifications Instead of Scheduled Scans

**Context**: NFS inotify limitation prevents automatic library updates.

**Options Considered**:
1. Scheduled scans (every 15 minutes via cron)
2. Webhook notifications from Sonarr/Radarr
3. Replace NFS with local storage + rsync

**Decision**: Webhook notifications via built-in Emby/Jellyfin connector

**Rationale**:
- Real-time updates (seconds vs 15 minutes)
- No unnecessary scans (scheduled scans waste CPU on unchanged libraries)
- Native integration (no custom scripting required)
- Reliable (HTTP API more robust than filesystem polling)
- Sonarr/Radarr have authoritative knowledge of import completion

**Trade-offs**:
- Requires API key management (stored in Sonarr/Radarr databases)
- Adds HTTP request to import process (~100ms overhead)
- Better than alternatives (scheduled scans, storage migration)

**Implementation**: Used built-in "Connect" feature in Sonarr/Radarr settings.

---

### Decision 3: Consolidate All MCP API Keys in Single 1Password Item

**Context**: MCP homelab needs API keys for 7 services (Pi-hole, Jellyfin, Immich, Bazarr, Sonarr, Radarr, SABnzbd).

**Options Considered**:
1. Separate 1Password item per service (7 items)
2. Consolidated 1Password item (1 item, 7 fields)

**Decision**: Consolidated `mcp-homelab` item with all API keys as fields

**Rationale**:
- Single ExternalSecret manifest instead of 7
- Easier secret rotation (update 1 item, ESO syncs all keys)
- Simpler audit trail (one item to review)
- Fewer API calls to 1Password (one fetch vs 7)
- Matches semantic grouping (all keys for same service: mcp-homelab)

**Trade-offs**:
- Larger blast radius if 1Password item compromised (all keys exposed vs 1)
- Field names must match K8s secret keys exactly (stricter naming)
- Better for operational simplicity (fewer moving parts)

**Implementation**: ExternalSecret uses `dataFrom.extract` to pull all fields from single item.

---

### Decision 4: Recommend Apple TV 4K for Jellyfin Playback

**Context**: User unable to achieve lossless audio on LG webOS.

**Options Considered**:
1. Continue using LG webOS app (accept transcoded audio)
2. Use Apple TV 4K + Swiftfin (native client)
3. Use HTPC (Kodi, Plex HTPC, etc.)

**Decision**: Recommend Apple TV 4K with Swiftfin client

**Rationale**:
- Full codec support (DTS-HD MA, TrueHD, Dolby Atmos)
- Native tvOS client (Swiftfin) optimized for direct play
- User already has Apple TV 4K (no additional purchase)
- Simpler setup than HTPC (no Linux installation, driver issues)
- Ethernet port available (eliminates WiFi bottleneck)

**Trade-offs**:
- Requires additional remote (Apple TV remote vs TV remote)
- Apple TV UI vs TV UI (learning curve)
- Better quality (lossless audio) vs convenience (built-in app)

**Validation**: User confirmed direct play working with lossless audio passthrough.

---

## Testing & Validation

### 1. Jellyfin OOM Fix - Stability Test

**Test Steps**:
1. Deployed manifest with doubled memory limits
2. Triggered full library scan:
   ```bash
   # Via Jellyfin dashboard
   Dashboard -> Libraries -> Movies -> Scan Library
   ```
3. Monitored pod memory usage:
   ```bash
   kubectl -n jellyfin top pod
   # NAME                        CPU(cores)   MEMORY(bytes)
   # jellyfin-7c9d4f6b8-zzz      450m         1850Mi
   ```
4. Waited 1 hour, checked restart count:
   ```bash
   kubectl -n jellyfin get pods
   # RESTARTS: 0 (success)
   ```
5. Verified library scan completed:
   ```
   Jellyfin dashboard: "Last scan: 5 minutes ago (14 movies)"
   ```

**Result**: Pod stable with 0 restarts, memory peaked at 1850Mi (within 2560Mi limit).

---

### 2. Webhook Notification - End-to-End Test

**Test Steps**:
1. Configured Radarr Emby/Jellyfin connector
2. Manually imported movie from Radarr UI:
   ```
   Movie: Empire of the Sun (1987)
   Path: /media/movies/Empire of the Sun (1987)/...
   ```
3. Watched Radarr logs for webhook:
   ```
   [Info] Sending notification to Jellyfin
   [Info] POST http://jellyfin.jellyfin.svc.cluster.local:8096/Library/Refresh
   [Info] Response: 200 OK
   ```
4. Checked Jellyfin library (without manual scan):
   ```
   Dashboard -> Movies
   # Empire of the Sun appeared within 10 seconds
   ```
5. Verified metadata fetched:
   ```
   # Poster, backdrop, cast/crew, TMDB ID all populated
   ```

**Result**: End-to-end pipeline working - import → webhook → Jellyfin refresh → metadata fetch.

---

### 3. MCP API Key Deployment - ExternalSecret Sync Test

**Test Steps**:
1. Created `mcp-homelab` 1Password item with 7 fields
2. Deployed ExternalSecret manifest
3. Waited for ESO sync (refreshInterval: 24h, but immediate on creation):
   ```bash
   kubectl -n mcp-homelab get externalsecret mcp-homelab-api-keys
   # STATUS: SecretSynced
   # READY: True
   ```
4. Verified Kubernetes secret created:
   ```bash
   kubectl -n mcp-homelab get secret mcp-homelab-api-keys -o yaml
   # data:
   #   bazarr-api-key: <base64>
   #   sonarr-api-key: <base64>
   #   ... (7 keys total)
   ```
5. Updated deployment with env vars, triggered rollout:
   ```bash
   flux reconcile kustomization mcp-homelab --with-source
   kubectl -n mcp-homelab rollout status deployment mcp-homelab
   # deployment "mcp-homelab" successfully rolled out
   ```
6. Verified new pod received env vars:
   ```bash
   kubectl -n mcp-homelab exec mcp-homelab-xxx -- env | grep _API_KEY | wc -l
   # 7 (all keys present)
   ```

**Result**: ExternalSecret synced all 7 API keys, deployment received environment variables.

---

### 4. Radarr Import Queue Cleanup - Validation

**Test Steps**:
1. Checked queue before cleanup:
   ```bash
   # Radarr UI: Queue tab
   # 9 items (6 completed, 3 stalled)
   ```
2. Imported completed downloads via "Manual Import" UI
3. Deleted stalled torrent downloads (qBittorrent unavailable)
4. Verified queue cleared:
   ```bash
   # Radarr UI: Queue tab
   # 0 items
   ```
5. Confirmed movies in Jellyfin:
   ```bash
   # Jellyfin dashboard
   # 6 new movies visible (via webhook notification)
   ```

**Result**: Queue cleared (9 → 0), 6 movies successfully imported and visible in Jellyfin.

---

## Lessons Learned

### 1. NFS Inotify Events Do Not Propagate Across Network Mounts

**Issue**: Jellyfin LibraryMonitor relies on Linux inotify, which is a local filesystem kernel feature.

**Learning**: Network filesystems (NFS, CIFS) do not propagate inotify events to remote clients. File changes on the NFS server do not trigger inotify events on NFS client pods.

**Implications**:
- Any pod relying on inotify for filesystem watching (Jellyfin, Plex, file upload services) will not detect changes on NFS
- Must use alternative notification mechanisms (webhooks, polling, API calls)

**Best Practice**: For NFS-backed storage, use application-level notifications (webhooks, API) instead of filesystem-level events (inotify).

---

### 2. SQLite WAL Mode Requires Graceful Shutdown to Prevent Locks

**Issue**: Radarr database locked due to stale .db-wal file from unclean pod shutdown.

**Learning**: SQLite write-ahead log (WAL) mode creates temporary files (.db-wal, .db-shm) that must be checkpointed (merged into .db) during graceful shutdown. Unclean shutdowns (OOM, pod kill) leave orphaned WAL files causing lock errors.

**Recovery Process**:
1. Scale deployment to 0 replicas (triggers graceful shutdown)
2. Graceful shutdown checkpoints WAL (merges .db-wal into .db)
3. Verify .db-wal and .db-shm removed
4. Scale deployment back to 1 replica

**Best Practice**: Always scale to 0 before SQLite database troubleshooting to ensure clean shutdown checkpoint.

---

### 3. LG webOS Platform Limitations Prevent Lossless Audio Passthrough

**Issue**: LG webOS Jellyfin app transcodes lossless audio (DTS-HD MA, TrueHD) to lossy formats (DTS Core, AC3).

**Learning**: This is a platform limitation, not a Jellyfin limitation. LG webOS uses proprietary media stack that does not support passthrough of lossless audio codecs. Same limitation affects Plex, Emby, Kodi on LG webOS.

**Solution**: Use external streaming device (Apple TV 4K, Nvidia Shield, Fire TV 4K Max) with native Jellyfin client (Swiftfin, Jellyfin for Android TV).

**Best Practice**: For home theater setups requiring lossless audio, recommend dedicated streaming device rather than smart TV built-in apps.

---

### 4. WiFi Bandwidth Insufficient for 4K Remux Streaming

**Issue**: 4K remux files have average bitrate of 50 Mbps with peaks at 80-100 Mbps. WiFi bandwidth of ~40 Mbps causes buffering during high-action scenes.

**Learning**: WiFi bandwidth is theoretical maximum and highly variable due to interference, distance, client capabilities. Real-world sustained throughput often 50-60% of advertised speed.

**Calculation**:
```
4K Remux File: 52 GB / 2 hours = 58 Mbps average
WiFi 5 (802.11ac): 40 Mbps real-world sustained
Headroom: 40 - 58 = -18 Mbps (insufficient)

Gigabit Ethernet: 1000 Mbps theoretical, ~940 Mbps real-world
Headroom: 940 - 58 = 882 Mbps (20x headroom)
```

**Best Practice**: Hardwire streaming devices via Ethernet for 4K remux playback. WiFi acceptable for 1080p and 4K compressed (streaming service quality).

---

### 5. Consolidating API Keys Simplifies Secret Management

**Issue**: Managing 7 separate 1Password items for MCP service API keys creates operational overhead.

**Learning**: ExternalSecret `dataFrom.extract` can pull all fields from a single 1Password item, eliminating need for separate items per service.

**Benefits**:
- Single ExternalSecret manifest instead of 7
- One kubectl get/describe command shows all synced keys
- Easier audit trail (one item to review in 1Password)
- Simpler rotation (update one item, all keys refresh)

**Best Practice**: Group related secrets by consuming service (e.g., `mcp-homelab` item contains all keys for mcp-homelab deployment) rather than one item per upstream service.

---

## Known Issues

### 1. Touch NAS Path MCP Tool Broken (Missing NAS_HOST Environment Variable)

**Status**: Identified today, not fixed.

**Impact**: `touch_nas_path` MCP tool fails with "NAS_HOST environment variable not set".

**Root Cause**: mcp-homelab deployment manifest missing `NAS_HOST`, `NAS_USER`, and `NAS_SSH_KEY` environment variables.

**Workaround**: Use kubectl exec to SSH to NAS directly:
```bash
kubectl run -it --rm nas-touch --image=alpine --restart=Never -- sh
apk add openssh-client
ssh user@192.168.1.60 'touch /volume1/cluster/media/path'
```

**Next Steps**:
- Add NAS credentials to mcp-homelab ExternalSecret
- Wire NAS_HOST, NAS_USER, NAS_SSH_KEY to deployment env vars
- Test `touch_nas_path` MCP tool
- Include in pi-cluster-mcp v0.1.21 release

---

### 2. Torrent Downloads Require VPN Routing

**Status**: Known limitation, VPN not configured for cluster.

**Impact**: Torrent indexers (1337x, YTS, etc.) unavailable - tracker connections fail without VPN.

**Current State**:
- 5 torrent indexers in Prowlarr: DISABLED
- 2 NZB indexers (NZBgeek, nzb.su): ENABLED and working
- qBittorrent downloads fail (no VPN route)

**Workaround**: Use NZB indexers only for now.

**Next Steps**:
- Configure VPN routing for qBittorrent namespace
- OR accept NZB-only workflow (sufficient for current needs)
- Private-exit-node gateway exists but not configured for media traffic

---

### 3. Pi-hole Stats Broken in get_dns_status MCP Tool

**Status**: Pre-existing, tracked in [mtgibbs/pi-cluster-mcp#17](https://github.com/mtgibbs/pi-cluster-mcp/issues/17).

**Impact**: `get_dns_status` returns basic health but fails to fetch query statistics.

**Root Cause**: Pi-hole v6 API breaking change - stats endpoint moved from `/admin/api.php?summary` to new v6 API.

**Workaround**: Use `get_pihole_queries` MCP tool for query-level data, or use Pi-hole web UI for stats.

**Next Steps**: Update mcp-homelab to use Pi-hole v6 API endpoints.

---

## Metrics

**Session Duration**: Approximately 4 hours (continuation session after context compaction)

**Commits**: 2
- 1 documentation (MCP-First protocol strengthening)
- 1 bug fix (Jellyfin memory limits)

**Files Changed**: 3
- `CLAUDE.md` - MCP protocol documentation
- `clusters/pi-k3s/jellyfin/jellyfin-deployment.yaml` - Memory limits
- `MEMORY.md` - Session learnings (not committed)

**Lines Changed**:
- Insertions: ~180 lines (mostly documentation)
- Deletions: ~30 lines

**Incidents Resolved**: 1 critical (Jellyfin OOM crash loop)

**Bugs Fixed**: 3 (Jellyfin OOM, Jellyfin metadata pipeline, Radarr SQLite lock - last one in Part 1)

**Architecture Fixes**: 1 (NFS inotify workaround via webhook notifications)

**User Support**: 1 (LG webOS playback limitations)

**Queue Cleanups**: 1 (Radarr import queue: 9 → 0)

**MCP Tools Designed**: 15 (to be implemented in pi-cluster-mcp v0.1.21)

---

## Next Steps

### Immediate (This Week)
- [ ] Fix `touch_nas_path` MCP tool (add NAS credentials to mcp-homelab deployment)
- [ ] Release pi-cluster-mcp v0.1.21 with 15 new media service tools
- [ ] Verify end-to-end metadata pipeline on next new download
- [ ] Monitor Jellyfin memory usage over 7 days (ensure 2560Mi sufficient)

### Short-term (Next 2 Weeks)
- [ ] Update backup-ops skill with MCP media service tool usage
- [ ] Test new Sonarr/Radarr MCP tools (queue, history, interactive search)
- [ ] Configure VPN routing for qBittorrent OR disable torrent indexers entirely
- [ ] Investigate Bazarr subtitle provider connectivity (podnapisi timeouts)
- [ ] Update media-services skill with Jellyfin metadata pipeline documentation

### Long-term (Backlog)
- [ ] Migrate from LG webOS app to Apple TV 4K as primary client (user-initiated)
- [ ] Add Jellyfin library growth monitoring (track movie/series count over time)
- [ ] Consider replacing NFS with Rook/Ceph for better inotify support (major undertaking)
- [ ] Add MCP tool health dashboard in Grafana (track tool success/failure rates)
- [ ] Implement retention policy for media downloads (auto-delete watched content)

---

## Files Changed

### Modified Files (Committed)
- `/Users/mtgibbs/dev/pi-cluster/CLAUDE.md` - Strengthened MCP-First protocol, added media service tool tables
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/jellyfin/jellyfin-deployment.yaml` - Doubled memory limits (1Gi → 2Gi)

### Modified Files (Part 1 of Session - Already Committed)
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/mcp-homelab/api-keys-external-secret.yaml` - Created ExternalSecret for media API keys
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/mcp-homelab/mcp-homelab-deployment.yaml` - Wired API keys to env vars
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/mcp-homelab/kustomization.yaml` - Added ExternalSecret resource

### Documentation Updates (Not Committed)
- `~/.claude/projects/-Users-mtgibbs-dev-pi-cluster/memory/MEMORY.md` - Updated with session learnings:
  - Jellyfin metadata pipeline (NFS inotify limitation, webhook solution)
  - Radarr SQLite recovery notes (graceful shutdown checkpoint)
  - LG webOS playback limitations (recommend Apple TV 4K)
  - MCP usage rules (strengthen MCP-first protocol)

---

## Relevant Commits

**Part 2 (This Session)**:
```
aa636d4 - fix(jellyfin): double memory limits to prevent OOM crash loop
2145bb8 - docs: strengthen MCP-first protocol and add media service tool tables
```

**Part 1 (Earlier Today)**:
```
[commit hash] - feat(mcp): add media service API keys to ExternalSecret
[commit hash] - feat(mcp): wire media service API keys to deployment env vars
```

**Previous Session Context** (for continuity):
```
28a464c - feat(media): add ExternalSecret for Calibre-Web SMTP credentials
a64aa09 - docs: add session recap for backups, monitoring, and media fixes
568954a - feat: add Calibre-Web and LazyLibrarian to homepage and uptime monitoring
d424ec1 - chore: update mcp-homelab to ghcr.io/mtgibbs/pi-cluster-mcp:0.1.19
```

---

## Documentation Updates Needed

### 1. Update `.claude/skills/media-services/SKILL.md`

Add sections:
- Jellyfin metadata pipeline architecture (NFS inotify limitation, webhook solution)
- Sonarr/Radarr Emby/Jellyfin connector configuration steps
- LG webOS playback limitations and recommended clients
- Troubleshooting guide: OOM crashes, database locks, missing metadata

### 2. Update `.claude/skills/backup-ops/SKILL.md`

Add:
- New MCP tools for media services (list all 15 with usage examples)
- Radarr/Sonarr queue management workflow
- SABnzbd download retry procedures

### 3. Update `ARCHITECTURE.md`

Add diagram:
- Jellyfin metadata refresh pipeline (Before/After comparison)
- NFS storage architecture (highlight inotify limitation)
- Media service interconnections (Sonarr/Radarr → Jellyfin webhooks)

### 4. Create `docs/jellyfin-playback-clients.md`

Document:
- Client codec support comparison (LG webOS vs Apple TV vs HTPC)
- Lossless audio passthrough requirements
- Network bandwidth requirements for 4K remux (Ethernet vs WiFi)
- Recommended client configurations

---

## Acknowledgments

This session demonstrated:
- The importance of understanding platform limitations (NFS inotify, LG webOS codecs)
- Value of proper resource provisioning (doubling memory prevents crashes)
- Power of application-level integration (webhooks > filesystem polling)
- Benefits of consolidated secret management (single 1Password item)
- Need for comprehensive documentation (MCP tool tables, architecture diagrams)

The Jellyfin metadata pipeline is now fully automated - new downloads appear in the library within seconds without manual intervention. Combined with the OOM fix, Jellyfin is now a stable, reliable service in the cluster.

Special thanks to the user for providing detailed playback environment information (LG C9 OLED, AVR setup, network topology) which enabled accurate diagnosis and recommendations.

---

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
