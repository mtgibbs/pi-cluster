# Session Recap - 2026-02-05: LazyLibrarian Ebook Pipeline Debugging

## Executive Summary

The LazyLibrarian ebook search and download pipeline was completely non-functional, returning 0 results for all searches. Through systematic debugging, we identified and fixed 5 distinct issues across the stack, resulting in a fully working end-to-end pipeline that successfully downloaded and catalogued all 5 test books.

**Duration**: ~4 hours
**Commits**: d0ffc46, 1d47cfe, 3af2f64, e5831e8, f892d52
**Status**: ✅ Fully operational

---

## Issues Found and Fixed

### 1. NZBgeek Search Type Mismatch (Root Cause of 0 Results)

**What**: LazyLibrarian was using `t=book` Newznab search type, which NZBgeek doesn't support.

**Why**:
- NZBgeek's Newznab capabilities XML has no `<book-search>` entry
- LazyLibrarian's auto-capability detection was setting `BOOKSEARCH = 'book'` based on a heuristic (bookcat == 7000)
- This resulted in search URLs like `?t=book&cat=7020` which returned empty results from NZBgeek

**How**:
Manually edited `/config/config.ini` in the LazyLibrarian pod:
```ini
[Newznab_0]
booksearch =
generalsearch = search
manual = True
```

**Result**: Searches now use `t=search&cat=7020` which returns proper ebook results.

---

### 2. Missing DLTYPES Config (Provider Silently Skipped)

**What**: The `dltypes` field was missing from the Newznab provider configuration.

**Why**:
- Code in `iterate_over_znab_sites()` checks `'E' not in provider['DLTYPES']`
- If `DLTYPES` is empty, the provider is silently skipped for ebook searches
- Even after fixing the search type, searches returned 0 because NZBgeek was being ignored

**How**:
```ini
[Newznab_0]
dltypes = A,E,M
```

**Trade-offs**: This was a critical missing configuration that had no visible error message — pure silent failure.

---

### 3. SABnzbd Download Directory Permissions

**What**: SABnzbd couldn't write downloaded ebooks to the NFS mount.

**Why**:
- `/downloads/complete/usenet/books/` was owned by `root:root` on the Synology NAS
- SABnzbd runs as UID 1029 (matching Calibre) and couldn't create subdirectories
- All downloads failed with `PermissionError: [Errno 13]`

**How**:
SSH to Synology NAS:
```bash
chown 1029:100 /volume1/cluster/media/downloads/complete/usenet/books/
```

**Context**: This was discovered by tailing SABnzbd logs (`/config/logs/sabnzbd.log`) which showed permission errors that weren't visible in the web UI.

---

### 4. Calibre metadata.db Permissions

**What**: `calibredb` couldn't write to the Calibre database after downloads completed.

**Why**:
- `/books/metadata.db` was owned by `root:root` on NFS
- LazyLibrarian runs as UID 1029 and uses `calibredb` to import books
- All imports failed with `calibredb rc 1` (apsw.ReadOnlyError)

**How**:
```bash
chown -R 1029:100 /volume1/cluster/media/books/
```

**Context**: LazyLibrarian logs showed "calibredb rc 1" errors but no specifics. Had to exec into the pod and manually run calibredb to see the actual error.

---

### 5. Calibre Duplicate Entries (No Automerge)

**What**: Re-downloading the same book created duplicate entries in Calibre.

**Why**:
- `IMP_CALIBREOVERWRITE` was not set, so calibredb used strict title+author matching
- Different NZB sources embed different epub metadata (pen name vs birth name, title variants)
- Each download with slightly different metadata created a new Calibre entry
- Example: "Arthur C. Clarke" vs "Arthur Charles Clarke"

**How**:
```ini
[General]
imp_calibreoverwrite = True
```

This enables `calibredb add --automerge overwrite`, which uses fuzzy matching and updates existing entries.

---

### 6. BOOK_API Config Wiped by configparser

**What**: Python's configparser was wiping the `BOOK_API` setting when we edited config.ini.

**Why**:
- configparser rewrites the entire config file when saving changes
- `BOOK_API` is set at runtime by LazyLibrarian based on enabled metadata sources
- After our edits, `BOOK_API` in the `[API]` section was empty
- Library scans crashed with `KeyError: ''`

**How**: Always re-set `book_api = GoodReads` when editing config programmatically.

**Additional Discovery**: LazyLibrarian overwrites config.ini on graceful shutdown. To preserve manual config edits, must use:
```bash
kubectl delete pod -n media lazylibrarian-xxx --force --grace-period=0
```

---

## Additional Configuration

### Added Second Newznab Provider (nzb.su)

**What**: Configured nzb.su via Prowlarr proxy as a second search provider.

**Why**:
- Improved search coverage — nzb.su found books NZBgeek couldn't:
  - "2001: A Space Odyssey"
  - "Harry Potter and the Philosopher's Stone"
- Redundancy in case one provider is down

**How**:
```ini
[Newznab_1]
host = prowlarr.media.svc.cluster.local:9696/7/
apikey = [from 1Password]
generalsearch = search
booksearch =
manual = True
dltypes = A,E,M
```

**Note**: nzb.su also doesn't support `t=book` — same fix applies.

---

## Final Test Results

### Books Successfully Downloaded and Catalogued

| Book | Author | Source | Status |
|------|--------|--------|--------|
| Foundation | Isaac Asimov | NZBgeek | ✅ In Calibre |
| 1984 | George Orwell | NZBgeek | ✅ In Calibre |
| Dune | Frank Herbert | NZBgeek | ✅ In Calibre |
| 2001: A Space Odyssey | Arthur C. Clarke | nzb.su | ✅ In Calibre |
| Harry Potter (Philosopher's Stone) | J.K. Rowling | nzb.su | ✅ In Calibre |

**Pipeline Status**: 5/5 books (100% success rate)

---

## Architecture Diagram

```
┌─────────────────┐     ┌──────────┐     ┌──────────┐
│  LazyLibrarian  │────▶│ SABnzbd  │────▶│ calibredb│
│  (search+mgmt)  │     │(download)│     │ (import) │
└────────┬────────┘     └──────────┘     └────┬─────┘
         │                                     │
    ┌────▼────┐                          ┌─────▼─────┐
    │ Prowlarr│                          │  /books/  │
    │ (proxy) │                          │(Calibre DB)│
    └────┬────┘                          └─────┬─────┘
         │                                     │
  ┌──────▼──────┐                       ┌──────▼──────┐
  │NZBgeek│nzb.su│                      │ Calibre-Web │
  └───────┴──────┘                      │  (reader)   │
                                        └─────────────┘
```

**Data Flow**:
1. LazyLibrarian searches NZBgeek + nzb.su (via Prowlarr) using `t=search&cat=7020`
2. User selects NZB, LazyLibrarian sends to SABnzbd
3. SABnzbd downloads to `/downloads/complete/usenet/books/<author>/<title>/`
4. LazyLibrarian post-processing runs `calibredb add --automerge overwrite`
5. Book appears in Calibre-Web at `calibre-web.local.mtgibbs.me`

---

## Key Technical Discoveries

### 1. Newznab Capabilities are Provider-Specific
Not all Newznab indexers support all search types. Always check the capabilities XML (`/api?t=caps`) before assuming `t=book` will work.

**NZBgeek caps**:
```xml
<searching>
  <search available="yes" supportedParams="q"/>
  <!-- NO <book-search> -->
  <tv-search available="yes"/>
  <movie-search available="yes"/>
</searching>
```

**Lesson**: Use `t=search` for broad compatibility, rely on `cat=` for filtering.

---

### 2. DLTYPES is a Silent Killer
If `dltypes` is missing or doesn't contain `E`, LazyLibrarian will silently skip the provider for ebook searches. There is no error message, no log entry — it just returns 0 results.

**Detection**: Enable debug logging and check for "searching provider X" messages. If a configured provider isn't mentioned, check `dltypes`.

---

### 3. NFS Permissions from Synology are a Recurring Issue
This is the third time we've hit this:
- First: Pi-hole persistent data (chattr +i fix)
- Second: Jellyfin media scanning (UID 1000 conflict)
- Third: SABnzbd + Calibre ebook directories (UID 1029)

**Root Cause**: Synology NFS defaults to `root_squash` and creates new directories as `root:root`.

**Future Work**: Need to investigate Synology NFS export options to prevent this. Possibly:
- Disable `root_squash` (security risk?)
- Use `all_squash` with explicit `anonuid=1029` mapping
- Create a systemd service on Synology to auto-fix permissions

---

### 4. configparser Rewrites Entire Files
Python's `configparser.write()` doesn't preserve:
- Comments
- Section order
- Runtime-added settings
- Whitespace formatting

**Implication**: Apps that manage their own config files (like LazyLibrarian) are dangerous to edit with scripts. Manual `sed` or direct kubectl exec edits are safer.

---

### 5. LazyLibrarian Overwrites Config on Shutdown
Even after manually editing `config.ini`, a graceful pod restart (`kubectl delete pod`) triggers LazyLibrarian to save its in-memory config back to disk, overwriting changes.

**Workaround**: Force-kill with `--grace-period=0` to prevent cleanup handlers from running.

**Long-term**: Should store config in a ConfigMap and mount read-only, or use LazyLibrarian's API to make changes.

---

### 6. Epub Metadata is Wildly Inconsistent
Different NZB uploaders embed different metadata in the same epub:
- "Arthur C. Clarke" vs "Arthur Charles Clarke"
- "Harry Potter and the Philosopher's Stone" vs "Harry Potter 1"
- Different ISBNs for different editions

**Solution**: `--automerge overwrite` uses fuzzy matching and picks the "best" metadata. Essential for preventing duplicates.

---

## Lessons Learned

1. **Always check Newznab caps XML** before assuming `t=book` works — it's not universal.

2. **`dltypes` is required** — empty means the provider is silently ignored for ebook searches.

3. **NFS permissions are a recurring problem** — need a systemic fix for Synology exports.

4. **configparser is dangerous with self-managing apps** — it rewrites entire files and loses runtime settings.

5. **LazyLibrarian overwrites config on shutdown** — use `--force --grace-period=0` to preserve manual edits.

6. **Epub metadata varies wildly** — automerge is essential to prevent duplicate Calibre entries.

7. **Silent failures are the worst** — enable debug logging early and tail all relevant logs simultaneously.

---

## Files Modified

- `.../media/lazylibrarian/config/config.ini` (manual edit in pod)
- `clusters/pi-k3s/media/lazylibrarian/helmrelease.yaml` (added universal-calibre mod)
- `clusters/pi-k3s/media/calibre-web/helmrelease.yaml` (added universal-calibre mod)
- NAS: `/volume1/cluster/media/downloads/complete/usenet/books/` (permissions)
- NAS: `/volume1/cluster/media/books/` (permissions)

---

## Next Steps

- [ ] Investigate Synology NFS export options to prevent root ownership of new directories
- [ ] Consider mounting LazyLibrarian config from ConfigMap (read-only)
- [ ] Document the `DLTYPES` and `booksearch` requirements in media-services skill
- [ ] Test automerge behavior with intentionally mismatched metadata
- [ ] Monitor for duplicate entries over the next week

---

## Relevant Commits

- `f892d52` - feat: add LazyLibrarian as Readarr alternative
- `e5831e8` - feat(media): add universal-calibre mod to calibre-web for calibredb support
- `3af2f64` - feat(media): add universal-calibre mod to lazylibrarian for calibredb import
- `1d47cfe` - fix(media): add calibre database path env var for calibredb
- `d0ffc46` - docs: add session recap for ebook stack deployment

---

**Session End**: 2026-02-05 (evening)
**Success Rate**: 100% (5/5 test books successfully processed)
**Status**: Pipeline fully operational and ready for production use.
