---
name: media-services
description: Expert knowledge for media applications (Jellyfin, Immich). Use when managing media storage, NFS mounts, or application-specific configurations.
allowed-tools: Bash, Read, Grep, Glob, Edit, Write
---

# Media Services (Jellyfin + Immich)

## Storage Architecture
All media is stored on the Synology NAS (`192.168.1.60`) and mounted via NFS.

### Common NFS Settings
- **Protocol**: NFSv3 (Required for Pi ARM compatibility with Synology)
- **Permissions**: Map all users to admin (Synology side) or ensure UID 568 matches.

## Immich (Photos)
- **URL**: `https://immich.lab.mtgibbs.dev`
- **Version**: v2.4.x (PostgreSQL with pgvector)
- **Storage**:
    - `pv.yaml`: Mounts `/volume1/photo` to `/data`.
    - Env Var: `IMMICH_MEDIA_LOCATION=/data`
- **Hardware**: High CPU usage on Pi 5 is known (ML job retry loop). ML features are disabled but jobs still queue.
- **Monitoring**: Metrics on ports 8081/8082, scraped by Prometheus.

## Jellyfin (Video)
- **URL**: `https://jellyfin.lab.mtgibbs.dev`
- **Storage**:
    - `pv.yaml`: Mounts `/volume1/video`.
- **Ingress**: TLS via Let's Encrypt.

## Troubleshooting

### NFS Mount Issues
If pods are stuck in `ContainerCreating`:
1. Check Synology NFS permissions (IP allowlist).
2. Verify NFSv3 is enabled on NAS.
3. Check `showmount -e 192.168.1.60` from a worker node.

### Jellyfin: Media Not Appearing After Download
If a show/movie was downloaded but doesn't appear in Jellyfin after a library scan:

**Root Cause**: The item may exist in the database with incomplete metadata (NULL `DateLastRefreshed`). Jellyfin won't display items with failed/interrupted metadata fetches.

**Solution 1 - UI (if item is visible):**
1. Click the item → three dots → "Refresh Metadata"
2. Check "Replace all metadata" → Save

**Solution 2 - API (if item is NOT visible):**
```bash
# First, find the item ID in the database
kubectl -n jellyfin exec -it deploy/jellyfin -- sqlite3 /config/data/library.db \
  "SELECT Id, Name FROM TypedBaseItems WHERE Name LIKE '%SHOW_NAME%' AND Type LIKE '%Series%';"

# Then trigger a full metadata refresh
kubectl -n jellyfin exec -it deploy/jellyfin -- curl -X POST \
  "http://localhost:8096/Items/ITEM_ID_HERE/Refresh?metadataRefreshMode=FullRefresh&imageRefreshMode=FullRefresh" \
  -H "X-Emby-Token: YOUR_API_KEY"
```

**Get API Key**: Jellyfin Dashboard → API Keys → Create

### Immich Database
To connect to the database for debugging:
```bash
kubectl -n immich exec -it deploy/immich-postgresql -- psql -U immich -d immich
```
