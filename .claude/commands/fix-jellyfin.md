---
description: Fix media not appearing in Jellyfin after download
allowed-tools: Bash(KUBECONFIG=~/dev/pi-cluster/kubeconfig kubectl:*)
---

# Fix Jellyfin Media

Troubleshoots and fixes media that was downloaded but isn't appearing in Jellyfin.

**Usage**: `/fix-jellyfin <show or movie name>`

## Steps

1. **Search for the item in Jellyfin's database**:
   ```bash
   KUBECONFIG=~/dev/pi-cluster/kubeconfig kubectl -n jellyfin exec -it deploy/jellyfin -- \
     sqlite3 /config/data/library.db \
     "SELECT Id, Name, Type, DateLastRefreshed FROM TypedBaseItems WHERE Name LIKE '%SEARCH_TERM%' AND Type IN ('MediaBrowser.Controller.Entities.TV.Series', 'MediaBrowser.Controller.Entities.Movies.Movie');"
   ```
   Replace `SEARCH_TERM` with the user's input (use `%` wildcards for partial matching).

2. **Check if metadata is incomplete**:
   - If `DateLastRefreshed` is NULL or empty, the metadata fetch failed
   - This is why the item doesn't appear in the UI

3. **Get API key from the secret**:
   ```bash
   KUBECONFIG=~/dev/pi-cluster/kubeconfig kubectl -n jellyfin get secret jellyfin-api-key -o jsonpath='{.data.api-key}' | base64 -d
   ```
   If no secret exists, tell user to get it from: Jellyfin Dashboard → API Keys

4. **Trigger full metadata refresh**:
   ```bash
   KUBECONFIG=~/dev/pi-cluster/kubeconfig kubectl -n jellyfin exec -it deploy/jellyfin -- \
     curl -s -X POST "http://localhost:8096/Items/ITEM_ID/Refresh?metadataRefreshMode=FullRefresh&imageRefreshMode=FullRefresh" \
     -H "X-Emby-Token: API_KEY"
   ```
   Replace `ITEM_ID` with the ID from step 1 and `API_KEY` from step 3.

5. **Verify the fix**:
   ```bash
   KUBECONFIG=~/dev/pi-cluster/kubeconfig kubectl -n jellyfin exec -it deploy/jellyfin -- \
     curl -s "http://localhost:8096/Items/ITEM_ID?api_key=API_KEY" | head -c 500
   ```
   Check that metadata fields are now populated.

## Output

Report to user:
- Whether item was found in database
- What the issue was (NULL metadata, missing entirely, etc.)
- Whether the fix was successful
- Tell them to refresh their browser to see the item

## If Item Not Found in Database

The files may not be in the expected location. Check:
```bash
KUBECONFIG=~/dev/pi-cluster/kubeconfig kubectl -n jellyfin exec -it deploy/jellyfin -- \
  ls -la "/media/tv/" | grep -i "SEARCH_TERM"
```

If files exist but aren't in database, a library scan is needed first, then run this command again.
