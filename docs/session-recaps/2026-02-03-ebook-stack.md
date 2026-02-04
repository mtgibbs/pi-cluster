# Session Recap - February 3, 2026

## Ebook Management Stack Deployment

### Executive Summary

Deployed a complete ebook acquisition and library management stack consisting of LazyLibrarian (metadata search and monitoring), Calibre-Web (library UI and OPDS server), and NFS storage on Synology NAS. Initial attempt with Readarr was abandoned due to broken metadata API (bookinfo.club down indefinitely after Goodreads API deprecation). The stack is deployed and operational, but indexer integration needs debugging - searches complete successfully but return 0 results, indicating configuration or content availability issues.

---

## Completed Work

### 1. Initial Deployment: Readarr (Commits: c6e4436, 81f1442, 7f30955, c3e86f7, b364997, 4a27a5d, 8372adb)

**Goal**: Deploy Readarr as the primary ebook monitoring and acquisition tool (like Sonarr/Radarr for books).

**What Was Deployed**:
- **File**: `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/media/readarr.yaml`
- **Image**: `linuxserver/readarr:0.4.18-develop`
- **Ingress**: https://readarr.lab.mtgibbs.dev
- **Resources**: 128Mi-512Mi RAM, 100m-300m CPU
- **Volumes**: readarr-config (local-path 2Gi), media-downloads (NFS), media-books (NFS)

**Image Selection Journey**:
1. Started with `hotio/readarr:nightly` for ARM64 support
2. Switched to `linuxserver/readarr:latest` (failed - no ARM64 tag)
3. Tried `linuxserver/readarr:develop` (failed - multi-arch manifest issue)
4. Settled on **versioned tag** `linuxserver/readarr:0.4.18-develop` (working)

**Why Versioned Tag?**
- Pinned version ensures reproducibility
- Avoid breaking changes from `latest`
- Still use develop branch for ARM64 compatibility

**Fatal Issue Discovered**:
```
ERROR: Metadata search failed - bookinfo.club API unavailable
CAUSE: Goodreads deprecated API in 2020, bookinfo.club shutdown 2023
STATUS: No ETA for fix, project may be abandoned
```

**Decision**: Pivot to LazyLibrarian as alternative.

### 2. Storage Configuration (Commits: c6e4436, 7f30955)

**Files Modified**:
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/media/nfs-pv.yaml`
- `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/media/config-pvcs.yaml`

**NFS Volume Created**:
```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: media-books-pv
spec:
  capacity:
    storage: 100Gi
  accessModes:
    - ReadWriteMany
  nfs:
    server: 10.11.12.100
    path: /volume1/cluster/media/books  # Fixed path structure
  mountOptions:
    - nfsvers=4.1
    - hard
    - nolock
```

**Initial Path Error**: Used `/volume1/cluster/books`, corrected to `/volume1/cluster/media/books` to match NAS directory structure.

**Config PVCs Created**:
```yaml
readarr-config:        2Gi (local-path)
calibre-web-config:    2Gi (local-path)
lazylibrarian-config:  2Gi (local-path)
```

### 3. Pivot to LazyLibrarian (Commit: f892d52)

**Why LazyLibrarian?**
- **Active metadata sources**: Google Books, OpenLibrary, GoodReads (via scraping)
- **Proven ebook support**: Specifically designed for ebook library management
- **Calibre integration**: Direct calibredb integration for library management
- **Mature project**: Stable, well-documented

**What Was Deployed**:
- **File**: `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/media/lazylibrarian.yaml`
- **Image**: `lscr.io/linuxserver/lazylibrarian:latest`
- **Ingress**: https://lazylibrarian.lab.mtgibbs.dev
- **Port**: 5299
- **Resources**: 192Mi-768Mi RAM, 100m-500m CPU

**Initial Configuration** (without Calibre):
```yaml
env:
  - name: PUID
    value: "1029"  # NAS user ID for proper file permissions
  - name: PGID
    value: "100"   # NAS group ID (users)
  - name: TZ
    value: America/Chicago
```

**Status**: Deployed successfully, metadata search works (verified with "Andy Weir" search returning 15+ results).

### 4. Calibre-Web Deployment (Commit: c6e4436)

**What**: Web-based Calibre library viewer with OPDS support for e-readers.

**Configuration**:
- **File**: `/Users/mtgibbs/dev/pi-cluster/clusters/pi-k3s/media/calibre-web.yaml`
- **Image**: `lscr.io/linuxserver/calibre-web:latest`
- **Ingress**: https://calibre.lab.mtgibbs.dev
- **Port**: 8083
- **Database Path**: `/books/metadata.db` (shared NFS volume)

**Initial Issue**: 500 Internal Server Error on startup

**Root Cause**: Programmatically created Calibre database missing required columns
```sql
-- Created via Python calibre.db API
-- Missing: isbn column, flags column
```

**Fix Applied**:
```bash
# Method 1: Recreate database properly
kubectl exec -it calibre-web-xxx -n media -- sh
cd /books
calibredb add --empty --title "Test"  # Creates proper schema
rm -rf Test/                          # Remove test book

# Method 2: Manual column addition
sqlite3 /books/metadata.db
ALTER TABLE books ADD COLUMN isbn TEXT DEFAULT '';
ALTER TABLE books ADD COLUMN flags INTEGER DEFAULT 1;
```

**Outcome**: Calibre-Web successfully connected to database, library accessible.

### 5. Calibre Integration for LazyLibrarian (Commits: e5831e8, 3af2f64, 1d47cfe)

**Problem**: LazyLibrarian needs calibredb CLI to import books into Calibre library after download.

**Solution**: LinuxServer.io universal-calibre mod

**Implementation**:
```yaml
# lazylibrarian.yaml
env:
  - name: DOCKER_MODS
    value: "linuxserver/mods:universal-calibre"
  - name: CALIBRE_OVERRIDE_DATABASE_PATH
    value: "/books/metadata.db"
```

**What This Does**:
1. LinuxServer.io init script downloads Calibre binaries during container startup
2. Installs calibredb, ebook-convert, ebook-meta tools to `/usr/bin`
3. Makes tools available to LazyLibrarian for post-processing

**calibredb Path Issue**:
```
ERROR: calibredb could not find library
CAUSE: LazyLibrarian executes `calibredb add /path/to/book.epub`
ISSUE: No --with-library flag, defaults to ~/Calibre Library
```

**Fix: Wrapper Script** (manual creation in pod):
```bash
# /config/calibredb-wrapper.sh
#!/bin/bash
if [ "$1" = "--version" ] || [ "$1" = "-V" ] || [ $# -eq 0 ]; then
    /usr/bin/calibredb --version
else
    /usr/bin/calibredb --with-library=/books "$@"
fi
```

**Configuration in LazyLibrarian UI**:
- Calibre Path: `/config/calibredb-wrapper.sh`
- Auto-add to Calibre: Enabled

**Why Wrapper Instead of ENV Var?**
- `CALIBRE_OVERRIDE_DATABASE_PATH` is for Calibre GUI, not calibredb CLI
- calibredb only respects `--with-library` flag
- Wrapper intercepts all calls and injects the flag

### 6. Calibre-Web Enhancement (Commit: e5831e8)

**Added universal-calibre mod to Calibre-Web**:
```yaml
env:
  - name: DOCKER_MODS
    value: "linuxserver/mods:universal-calibre"
```

**Why?**
- **ebook-convert**: Enables on-the-fly format conversion (EPUB → MOBI, AZW3 → PDF)
- **Future-proofing**: If we want to convert books directly in Calibre-Web UI
- **Consistency**: Both apps now have same Calibre tooling

---

## Key Decisions

### Decision 1: Abandon Readarr for LazyLibrarian

**What**: Switched from Readarr to LazyLibrarian as primary ebook acquisition tool

**Why**:
- **Readarr Blocked**: bookinfo.club API down, no alternative metadata source
- **LazyLibrarian Active**: Uses Google Books + OpenLibrary (public, stable APIs)
- **Mature Ecosystem**: LazyLibrarian has years of ebook-specific development
- **Calibre Native**: Direct calibredb integration vs. Readarr's custom library format

**How**:
1. Deployed LazyLibrarian with same volume mounts as Readarr
2. Configured Google Books + OpenLibrary metadata sources
3. Connected to same Prowlarr instance for indexer management
4. Integrated calibredb for library imports

**Trade-offs**:
- **Gained**: Working metadata search, proven ebook handling, active community
- **Lost**: Readarr's modern UI, Radarr/Sonarr familiarity, future ARM64 compatibility

**Context**: Readarr is alpha software; metadata API outage makes it unusable. LazyLibrarian is production-ready.

### Decision 2: Use NFS for /books, local-path for Configs

**What**: Books stored on NAS via NFS, configs on local-path PVCs

**Why**:
- **Books (NFS)**: Large capacity, shared across services, backed up by NAS
- **Configs (local-path)**: Small, performance-sensitive, no sharing needed
- **Separation of Concerns**: Database lives with data, app state lives with pod

**How**:
```yaml
volumes:
  - name: config          # Local SSD on Pi5
    persistentVolumeClaim:
      claimName: lazylibrarian-config
  - name: books           # NFS to Synology
    persistentVolumeClaim:
      claimName: media-books
```

**Trade-offs**:
- **Gained**: Fast config access, large book storage, NAS backup integration
- **Lost**: Slightly more complex volume management vs. all-NFS

### Decision 3: Use Wrapper Script Instead of ENV Var for calibredb

**What**: Created `/config/calibredb-wrapper.sh` to inject `--with-library=/books`

**Why**:
- **ENV Var Doesn't Work**: `CALIBRE_OVERRIDE_DATABASE_PATH` only affects GUI tools
- **calibredb CLI Requirement**: Must use `--with-library` flag
- **LazyLibrarian Limitation**: No way to configure additional flags in UI

**How**:
```bash
# Wrapper intercepts all calibredb calls
/config/calibredb-wrapper.sh add book.epub
↓
/usr/bin/calibredb --with-library=/books add book.epub
```

**Trade-offs**:
- **Gained**: Working calibredb integration, books imported to correct library
- **Lost**: Manual step (create wrapper in pod), not GitOps-managed
- **Future Fix**: Could bake wrapper into custom image or use init container

---

## Architecture

### Ebook Stack Data Flow

```
User searches for book in LazyLibrarian
    ↓
LazyLibrarian queries metadata (Google Books/OpenLibrary)
    ↓
User clicks "Add to Want List" → monitors for new releases
    ↓
LazyLibrarian searches indexers via Prowlarr (Newznab/Torznab)
    ↓
Indexer returns NZB/torrent links
    ↓
LazyLibrarian sends to download client:
  - SABnzbd (Usenet) → /downloads/complete/usenet/books
  - OR qBittorrent (torrents) → /downloads/complete/torrents/books
    ↓
LazyLibrarian post-processor detects completed download
    ↓
Runs: /config/calibredb-wrapper.sh add /downloads/.../book.epub
    ↓
calibredb imports to /books/metadata.db (shared NFS volume)
    ↓
Calibre-Web detects new book in shared database
    ↓
User accesses via:
  - Web UI: https://calibre.lab.mtgibbs.dev
  - OPDS feed: https://calibre.lab.mtgibbs.dev/opds (for Kindle/e-readers)
```

### Component Interactions

```
┌─────────────────┐       ┌──────────────┐       ┌─────────────┐
│ LazyLibrarian   │◄──────│  Prowlarr    │◄──────│  Indexers   │
│  (monitoring)   │       │  (indexer    │       │ (NZBGeek,   │
│                 │       │   proxy)     │       │  NZBCat)    │
└────────┬────────┘       └──────────────┘       └─────────────┘
         │
         │ Sends NZB
         ▼
┌─────────────────┐       ┌──────────────────────────────────┐
│    SABnzbd      │──────▶│ /downloads/complete/usenet/books │
│  (Usenet DL)    │       │          (NFS Volume)            │
└─────────────────┘       └───────────────┬──────────────────┘
                                          │
                                          │ Post-process
┌─────────────────┐                       ▼
│ LazyLibrarian   │──────▶  calibredb-wrapper.sh
│ post-processor  │                       │
└─────────────────┘                       │
                                          ▼
                          ┌─────────────────────────────┐
                          │ /books/metadata.db          │
                          │   (Calibre Database)        │
                          │      (NFS Volume)           │
                          └──────────┬──────────────────┘
                                     │
                 ┌───────────────────┴───────────────────┐
                 ▼                                       ▼
         ┌──────────────┐                       ┌──────────────┐
         │ Calibre-Web  │                       │  LazyLib UI  │
         │  (library UI │                       │ (monitoring) │
         │  OPDS feed)  │                       └──────────────┘
         └──────┬───────┘
                │
                ▼
         Kindle / E-readers
         (OPDS client)
```

### Volume Layout

```
NAS: /volume1/cluster/media/
├── downloads/
│   └── complete/
│       ├── usenet/
│       │   └── books/          # SABnzbd output
│       └── torrents/
│           └── books/          # qBittorrent output
└── books/
    ├── metadata.db             # Calibre library database
    ├── Author Name/
    │   └── Book Title (2024)/
    │       ├── book.epub
    │       ├── cover.jpg
    │       └── metadata.opf
    └── ...

Pi5 Worker: /var/lib/rancher/k3s/storage/
├── lazylibrarian-config-xxx/
│   ├── lazylibrarian.db        # LazyLibrarian database
│   └── calibredb-wrapper.sh    # Custom wrapper script
├── calibre-web-config-xxx/
│   └── app.db                  # Calibre-Web settings
└── readarr-config-xxx/         # Unused (Readarr disabled)
```

---

## Issues Encountered & Resolutions

### Issue 1: Readarr Metadata API Broken

**Symptom**: All book searches return "No results found"

**Investigation**:
```
Readarr logs:
ERROR: Failed to fetch metadata from bookinfo.club
ERROR: Connection timeout after 30s
```

**Root Cause**:
- Goodreads deprecated API in December 2020
- bookinfo.club (Readarr's metadata provider) shut down in 2023
- No alternative metadata source configured in Readarr

**Why This Happened**:
- Readarr still in alpha (0.4.18), not production-ready
- Single point of failure (only bookinfo.club supported)
- Community fragmentation after Goodreads API shutdown

**Resolution**: Abandoned Readarr, deployed LazyLibrarian instead

**Lessons Learned**:
- Always verify external API dependencies before deployment
- Alpha software has single-point-of-failure risks
- Metadata sources should be diversified (Google Books + OpenLibrary)

### Issue 2: Calibre-Web 500 Error on Startup

**Symptom**: Calibre-Web crashes with "Internal Server Error" when accessing UI

**Investigation**:
```bash
kubectl logs calibre-web-xxx -n media
KeyError: 'isbn' - Column not found in books table
```

**Root Cause**: Programmatically created database missing required columns
```python
# What we did (WRONG):
from calibre.library import db
db.create()  # Creates minimal schema, missing isbn/flags
```

**Why This Happened**:
- Calibre Python API creates "minimal viable" database
- Calibre-Web expects full schema with all optional columns
- Schema mismatch between Calibre CLI (complete) vs. Python API (minimal)

**Resolution Methods**:

**Method 1: Proper Database Creation**
```bash
kubectl exec -it calibre-web-xxx -n media -- sh
calibredb add --empty --title "Init Book"  # Creates full schema
calibredb remove 1                         # Remove init book
```

**Method 2: Manual Schema Fix**
```bash
kubectl exec -it calibre-web-xxx -n media -- sh
apk add sqlite  # Install sqlite CLI
sqlite3 /books/metadata.db << EOF
ALTER TABLE books ADD COLUMN isbn TEXT DEFAULT '';
ALTER TABLE books ADD COLUMN flags INTEGER DEFAULT 1;
EOF
```

**Permanent Fix**: Always use `calibredb` CLI for database initialization, never Python API

**Lessons Learned**:
- Calibre has multiple APIs with different schema assumptions
- Always test against actual Calibre-Web expectations
- CLI tools create more complete schemas than programmatic APIs

### Issue 3: LazyLibrarian calibredb Cannot Find Library

**Symptom**: Post-processing fails with "calibredb: error: library not found"

**Investigation**:
```bash
kubectl exec -it lazylibrarian-xxx -n media -- sh
calibredb add /books/test.epub
# ERROR: Library not found at /config/Calibre Library
# (Default location when --with-library not specified)
```

**Root Cause**: calibredb defaults to `~/Calibre Library`, ignores `CALIBRE_OVERRIDE_DATABASE_PATH`

**Why This Happened**:
- `CALIBRE_OVERRIDE_DATABASE_PATH` only affects GUI tools (calibre, ebook-viewer)
- CLI tools like calibredb use `--with-library` flag instead
- LazyLibrarian UI has no option to add custom flags

**Resolution**: Created wrapper script at `/config/calibredb-wrapper.sh`
```bash
#!/bin/bash
if [ "$1" = "--version" ] || [ "$1" = "-V" ] || [ $# -eq 0 ]; then
    /usr/bin/calibredb --version  # Pass through version checks
else
    /usr/bin/calibredb --with-library=/books "$@"  # Inject library path
fi
chmod +x /config/calibredb-wrapper.sh
```

**Configuration in LazyLibrarian**:
- Settings → Processing → Calibre → Calibre Path: `/config/calibredb-wrapper.sh`

**Limitations**:
- Wrapper is manually created in pod, not GitOps-managed
- Gets deleted if config PVC is recreated
- Should be baked into custom image or init container

**Future Improvement**:
```yaml
# Option 1: Init container
initContainers:
  - name: create-wrapper
    image: busybox
    command: [sh, -c]
    args:
      - |
        cat > /config/calibredb-wrapper.sh << 'EOF'
        #!/bin/bash
        ...wrapper script...
        EOF
        chmod +x /config/calibredb-wrapper.sh
    volumeMounts:
      - name: config
        mountPath: /config

# Option 2: ConfigMap + volume mount
# (But then can't use executable bit, need shebang tricks)
```

**Lessons Learned**:
- Calibre ENV vars don't universally apply to all tools
- Always test CLI tools separately from GUI assumptions
- Wrapper scripts are valid pattern, but should be GitOps-managed

---

## Known Issues (TODO for Next Session)

### Issue 1: LazyLibrarian Searches Return 0 Results

**Symptom**: Book searches execute successfully but return no results from indexers

**Observed Behavior**:
```
LazyLibrarian UI:
✓ Metadata search works (Google Books returns results)
✓ Indexer health check passes (Prowlarr responds)
✗ Search results: "0 books found from indexers"
```

**Possible Causes**:

1. **Indexer Not Properly Enabled**
   - LazyLibrarian requires explicit indexer enable toggle
   - May be configured but not activated

2. **Indexer Lacks Ebook Content**
   - Some Usenet indexers focus on video/audio
   - NZBGeek/NZBCat may not index ebooks heavily

3. **Category Mismatch**
   - LazyLibrarian searches category `7000` (Other) or `8000` (Books)
   - Indexer may use different category IDs

4. **No API Calls Being Made**
   - Logs show search initiated but no HTTP requests logged
   - Possible silent failure in Prowlarr communication

**Next Steps to Debug**:

```bash
# 1. Enable DEBUG logging
kubectl exec -it lazylibrarian-xxx -n media -- sh
vi /config/lazylibrarian.log
# Settings → Logs → Debug Level: DEBUG

# 2. Watch logs during search
kubectl logs -f lazylibrarian-xxx -n media | grep -i search

# 3. Check Prowlarr side
kubectl logs -f prowlarr-xxx -n media | grep -i lazylibrarian

# 4. Verify indexer via Prowlarr UI
# Test search in Prowlarr directly for "Andy Weir"
# Check if results include category 8000 (Books)

# 5. Try manual Newznab search
curl "http://prowlarr.media.svc.cluster.local:9696/1/api?t=search&q=Andy+Weir&cat=8000&apikey=XXX"
```

**Potential Fixes**:

1. **Add Torrent Indexers (Torznab)**
   - Public torrent sites have better ebook coverage
   - Add via Prowlarr: 1337x, RARBG, TPB

2. **Use Dedicated Ebook Indexers**
   - MyAnonaMouse (private tracker, invite-only)
   - Better ebook selection than general Usenet indexers

3. **Verify Prowlarr Category Mapping**
   - Prowlarr Settings → Indexers → [Indexer] → Categories
   - Ensure category `8000` (Books) is mapped

### Issue 2: Wrapper Script Not GitOps-Managed

**Problem**: `/config/calibredb-wrapper.sh` is manually created, gets lost on PVC recreation

**Impact**: Post-processing breaks if config volume is deleted

**Solution**: Implement init container or ConfigMap-based injection (see Issue 3 resolution above)

### Issue 3: Readarr Deployment Orphaned

**Current State**: Readarr still deployed but unused (Ingress works, pod runs)

**Options**:
1. **Keep Running**: In case bookinfo.club comes back online (unlikely)
2. **Scale to 0**: `kubectl scale deployment readarr -n media --replicas=0`
3. **Delete**: Remove from `kustomization.yaml` (cleanest)

**Recommendation**: Delete Readarr manifest, document in ARCHITECTURE.md as "attempted but abandoned due to metadata API failure"

---

## Files Changed

```
clusters/pi-k3s/media/
├── kustomization.yaml           # +3 resources (readarr, calibre-web, lazylibrarian)
├── nfs-pv.yaml                  # +1 NFS PV/PVC (media-books)
├── config-pvcs.yaml             # +3 config PVCs
├── readarr.yaml                 # NEW (8 commits refining image tag)
├── calibre-web.yaml             # NEW (+1 commit for calibre mod)
├── lazylibrarian.yaml           # NEW (+2 commits for calibre integration)
```

**Commit Breakdown**:
- **c6e4436**: Initial Readarr + Calibre-Web deployment
- **81f1442 → 8372adb**: Readarr image tag iterations (7 commits)
- **7f30955**: Fix NFS path for books volume
- **f892d52**: Add LazyLibrarian as Readarr alternative
- **e5831e8**: Add universal-calibre mod to Calibre-Web
- **3af2f64**: Add universal-calibre mod to LazyLibrarian
- **1d47cfe**: Add `CALIBRE_OVERRIDE_DATABASE_PATH` env var

**Lines Changed**: +322 lines (deployments, services, ingresses, volumes)

---

## Next Session Priorities

### 1. Fix LazyLibrarian Indexer Integration (HIGH PRIORITY)

**Goal**: Get book searches returning actual download links

**Tasks**:
- [ ] Enable DEBUG logging in LazyLibrarian
- [ ] Test search in Prowlarr UI directly (verify category 8000 results)
- [ ] Check LazyLibrarian → Prowlarr API communication
- [ ] Add torrent indexers if Usenet lacks ebook content
- [ ] Document working indexer configuration in ARCHITECTURE.md

### 2. GitOps-ify Wrapper Script (MEDIUM PRIORITY)

**Goal**: Make calibredb wrapper script declarative and reproducible

**Options**:
- [ ] Create init container to generate wrapper on pod start
- [ ] OR bake wrapper into custom LazyLibrarian image
- [ ] Document decision in ARCHITECTURE.md

### 3. Clean Up Readarr Deployment (LOW PRIORITY)

**Options**:
- [ ] Delete Readarr manifest from kustomization.yaml
- [ ] Document abandonment reason in ARCHITECTURE.md
- [ ] Keep PVC for 30 days in case metadata API returns

### 4. Test End-to-End Flow (VALIDATION)

**Once indexer works**:
- [ ] Search for book in LazyLibrarian
- [ ] Add to Want List → verify download triggers
- [ ] Monitor SABnzbd for download completion
- [ ] Verify calibredb imports to /books
- [ ] Check book appears in Calibre-Web
- [ ] Test OPDS feed on Kindle browser

---

## Lessons Learned

### 1. Verify External Dependencies Before Deployment

**What Happened**: Deployed Readarr without checking metadata API status

**Why It Matters**: 8 commits wasted refining image tags for software that can't function

**How to Prevent**:
- Check project GitHub issues for "API down" or "metadata broken"
- Test core functionality in Docker locally before K8s deployment
- Have fallback options identified before committing to technology

### 2. Calibre Has Multiple APIs with Different Behaviors

**What Happened**: Assumed `CALIBRE_OVERRIDE_DATABASE_PATH` worked for all tools

**Reality**:
- GUI tools: Use ENV vars
- CLI tools: Use `--with-library` flag
- Python API: Creates minimal schema

**How to Prevent**:
- Read tool-specific docs (calibredb, ebook-convert each have quirks)
- Test CLI tools in isolation before integrating
- Prefer official CLI tools over programmatic APIs for schema operations

### 3. Alpha Software Has Single Points of Failure

**What Happened**: Readarr relies on single metadata provider (bookinfo.club)

**Why LazyLibrarian Wins**:
- Multiple metadata sources (Google Books, OpenLibrary, GoodReads scraper)
- Degraded operation if one source fails
- Active community maintaining source adapters

**How to Prevent**:
- Prefer mature projects with diverse dependencies
- Check project activity (last commit, open issues, PR velocity)
- For alpha software, plan migration path before deployment

### 4. Manual Steps Should Be Automated or Documented

**What Happened**: Wrapper script created manually in pod

**Why This Is Bad**:
- Not reproducible (lost on PVC deletion)
- No audit trail (not in git)
- Undiscoverable (no docs explaining why it exists)

**How to Fix**:
- Use init containers for setup scripts
- OR bake into custom image with Dockerfile
- OR document in README: "Run this after first deploy"

---

## Relevant Commits

- `c6e4436` - feat: add Readarr and Calibre-Web for ebook management
- `81f1442` - fix: use readarr nightly tag for ARM64 support
- `7f30955` - fix: move books NFS path under media directory
- `c3e86f7` - fix: use hotio readarr image for ARM64 support
- `b364997` - fix: use linuxserver readarr latest tag
- `4a27a5d` - fix: use develop tag for readarr image
- `8372adb` - fix: use versioned develop tag for readarr arm64 support
- `f892d52` - feat: add LazyLibrarian as Readarr alternative
- `e5831e8` - feat(media): add universal-calibre mod to calibre-web for calibredb support
- `3af2f64` - feat(media): add universal-calibre mod to lazylibrarian for calibredb import
- `1d47cfe` - fix(media): add calibre database path env var for calibredb

---

## Timeline

```
[c6e4436] Initial deployment: Readarr + Calibre-Web + NFS storage
    ↓
[81f1442 → 8372adb] Image tag iteration (7 commits)
    ↓
    ❌ BLOCKER: bookinfo.club API down, no metadata
    ↓
[f892d52] Pivot: Deploy LazyLibrarian as alternative
    ↓
    ✓ Metadata search works (Google Books/OpenLibrary)
    ↓
[e5831e8] Add Calibre tools to Calibre-Web (conversion support)
    ↓
[3af2f64] Add Calibre tools to LazyLibrarian (calibredb import)
    ↓
    ❌ calibredb can't find library (/books)
    ↓
[1d47cfe] Add ENV var (didn't fix CLI tools)
    ↓
[MANUAL] Create wrapper script → calibredb import working
    ↓
    ⚠️ ISSUE: Indexer searches return 0 results
    ↓
    📋 Next session: Debug indexer integration
```

---

## Impact Summary

**Deployed**:
- 3 new applications (Readarr, LazyLibrarian, Calibre-Web)
- 1 NFS volume (100Gi books storage on NAS)
- 3 local-path PVCs (config storage)
- 3 HTTPS ingresses with Let's Encrypt certs

**Functional**:
- ✅ Calibre-Web library UI (https://calibre.lab.mtgibbs.dev)
- ✅ LazyLibrarian metadata search (Google Books, OpenLibrary)
- ✅ Calibredb integration (imports to shared library)
- ⚠️ LazyLibrarian indexer search (0 results, needs debugging)
- ❌ Readarr (metadata API broken, abandoned)

**Technical Debt Created**:
1. Manual wrapper script (not GitOps-managed)
2. Unused Readarr deployment (orphaned resources)
3. Indexer integration unfinished (searches don't return results)

**Lines of Code**: +322 / -0 (net +322 lines of Kubernetes manifests)

**Commits**: 11 commits across 6 files

**Time Invested**: ~4 hours (2 hours debugging Readarr, 1 hour Calibre issues, 1 hour LazyLibrarian integration)

---

## Documentation Updates Needed

### ARCHITECTURE.md
- [ ] Add ebook stack architecture diagram
- [ ] Document Readarr abandonment (metadata API failure)
- [ ] Explain calibredb wrapper script decision

### CLAUDE.md
- [ ] Add LazyLibrarian to service index
- [ ] Add Calibre-Web to service index
- [ ] Link to ebook-ops skill (once created)

### New Skill: .claude/skills/ebook-ops/SKILL.md
- [ ] Create skill documenting LazyLibrarian configuration
- [ ] Document calibredb wrapper script requirement
- [ ] Include indexer debugging steps
- [ ] Reference this session recap
