# LazyLibrarian + Ebook Stack

Operational notes for the LazyLibrarian + SABnzbd + Calibre-Web ebook pipeline.

## Service Architecture

| Service | Port | Role |
|---|---|---|
| LazyLibrarian | 5299 | Searches metadata (GoodReads/OpenLibrary), sends NZBs to SABnzbd |
| SABnzbd | 8080 | Downloads NZBs; category "books" → `/downloads/complete/usenet/books/` |
| Calibre-Web | 8083 | Web UI for Calibre library at `/books/` |
| Prowlarr | 9696 | Proxies NZB indexer searches (7 indexers: 5 torrent DISABLED, 2 NZB enabled) |

All services pinned to `pi5-worker-1`, shared NFS storage on QNAP (via `storage.lab.mtgibbs.dev`).

- **Ingresses**: `lazylibrarian.lab.mtgibbs.dev`, `calibre.lab.mtgibbs.dev`, `sabnzbd.lab.mtgibbs.dev`, `prowlarr.lab.mtgibbs.dev`
- **NFS paths**: `/cluster/media/books`, `/cluster/media/downloads`

## LazyLibrarian Config File Hazard (CRITICAL)

LazyLibrarian **overwrites `config.ini` on every graceful shutdown** — it writes its in-memory state back to disk on exit, stomping any manual edits.

**If you need to preserve config edits:**
1. Make the edit
2. Force-delete the pod without a grace period: `kubectl delete pod -n media <lazylibrarian-pod> --force --grace-period=0`
3. The pod terminates immediately (no graceful shutdown, no overwrite)
4. New pod starts and reads your edited `config.ini`

A normal `kubectl delete pod` triggers graceful termination which overwrites the file.

## Newznab Provider Config (CRITICAL — non-obvious)

### NZBgeek and nzb.su Do Not Support `t=book`

Neither NZBgeek nor nzb.su (via Prowlarr) support the `t=book` search type. Their caps XML does not include it (`book-search available="no"`). LazyLibrarian must use generic category search instead.

**Required `config.ini` settings for each Newznab provider (`[Newznab_0]`, `[Newznab_1]`, etc.):**

```ini
booksearch =           # empty — disables t=book
generalsearch = search # fallback to t=search
dltypes = A,E,M        # REQUIRED — without this, provider is silently skipped for ebook searches
manual = True          # prevents caps auto-detection from overwriting these settings
```

`dltypes` controls which download types the provider is used for. Values: `A` = audiobook, `E` = ebook, `M` = magazine. If `E` is absent, the provider is not queried for ebook searches despite being enabled.

### Working Provider Setup (as of 2026-02-05)

| Index | Provider | Access | Status |
|---|---|---|---|
| `[Newznab_0]` | NZBgeek | Direct at `https://api.nzbgeek.info` | Enabled |
| `[Newznab_1]` | nzb.su | Via Prowlarr at `http://prowlarr.media.svc.cluster.local:9696/7/api` | Enabled |

Prowlarr indexer IDs: 1-5 torrent (all DISABLED — need VPN), 6 NZBgeek, 7 nzb.su.

nzb.su tends to find books NZBgeek cannot (e.g., 2001, Harry Potter).

Note: NZBgeek often returns audiobooks for book searches — check download category before queuing.

## calibredb Integration

- Wrapper script at `/config/calibredb-wrapper.sh` adds `--with-library=/books`
- `imp_calibreoverwrite = True` in `[CALIBRE]` section is critical: enables `--automerge overwrite` flag
  - Without this, books with variant author names or title formats create duplicate entries
  - Examples: Tchaikovsky vs Czajkowski, "2001" vs "2001: A Space Odyssey"
- calibredb returns exit code 1 on permission errors (`apsw.ReadOnlyError`)

## NFS Permissions (Recurring Issue)

All media pods run as UID 1029, GID 100 (`abc:users`). Synology created files as `root:root`; QNAP should preserve UIDs via `no_all_squash` / "No mapping" squash setting.

If calibredb fails with permission errors:
```bash
# Check ownership on NFS path from inside pod
kubectl exec -n media deploy/lazylibrarian -- ls -la /books/

# Fix ownership (requires NAS-side access)
# On QNAP: chown -R 1029:100 /share/cluster/media/books/
```

`/books/metadata.db` must be writable by UID 1029 for calibredb to work.

## configparser Hazards

Python's `configparser` rewrites the ENTIRE file when writing. If a session uses configparser to modify `config.ini`, watch for:
- `BOOK_API` in `[API]` section getting wiped to empty — always re-set to `GoodReads`
- Newznab `dltypes`/`manual`/`booksearch` values being lost

Prefer force-deleting the pod (see above) over using configparser for config edits.

## Startup Behavior

- LazyLibrarian reads `config.ini` at startup only — must restart pod after config changes
- The `universal-calibre` Docker mod makes startup slow (~2 min on ARM64) — it downloads and installs calibre via apt on every pod start
- This is expected; do not assume the pod is stuck until 2+ minutes have elapsed

## Rebuild From Scratch Checklist

1. Edit `config.ini` via exec: `kubectl exec -n media deploy/lazylibrarian -- vi /config/config.ini`
2. Set `[Newznab_0]` and `[Newznab_1]` with the settings above
3. Set `[CALIBRE]`: `imp_calibreoverwrite = True`
4. Set `[API]`: `BOOK_API = GoodReads`
5. Force-delete the pod to preserve edits (do NOT use graceful delete)
