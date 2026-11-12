#!/usr/bin/env python3
"""checkout — the init container of an agent Job whose manifest has `checkout:` (CONTRACT §4a).

Fetches a Flux source-controller artifact (a .tar.gz of the Git tree at one revision) over in-cluster
HTTP and unpacks it into CHECKOUT_DEST, which the agent container then mounts READ-ONLY. It holds no
credential: the artifact server is unauthenticated, and only this pod's NetworkPolicy reaches it.

The archive is untrusted input. Extraction is done by hand, never tarfile.extractall:
- only regular files and directories are written; symlinks, hard links, devices and FIFOs are skipped;
- a member name that is absolute, contains '..', NUL or a backslash is skipped;
- the download, the unpacked total, each file and the file count are capped;
- CHECKOUT_INCLUDE (a JSON list of path prefixes) limits what is unpacked.

It ALWAYS exits 0 and writes CHECKOUT_INFO ({"ok": true|false, ...}). The agent runtime reads that file
and, when ok is false, emits a `failed` Result naming the reason — a clearer failure than an init
container crash, which would leave the agent container's log (where the runner looks) empty.
"""
import hashlib
import json
import os
import posixpath
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request

sys.dont_write_bytecode = True

from common import OPENER, log  # noqa: E402

MAX_DOWNLOAD = int(os.environ.get("CHECKOUT_MAX_BYTES", str(32 * 1024 * 1024)))
MAX_EXTRACT = int(os.environ.get("CHECKOUT_MAX_EXTRACT_BYTES", str(128 * 1024 * 1024)))
MAX_FILES = int(os.environ.get("CHECKOUT_MAX_FILES", "10000"))
MAX_FILE = int(os.environ.get("CHECKOUT_MAX_FILE_BYTES", str(8 * 1024 * 1024)))
TIMEOUT = float(os.environ.get("CHECKOUT_TIMEOUT", "60"))
CHUNK = 64 * 1024


class CheckoutError(Exception):
    pass


class NotFound(CheckoutError):
    pass


def _safe_url(url):
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise CheckoutError("checkout URL must be http(s)")
    return url


def download(url, dest_file):
    """Stream `url` into `dest_file` (≤ MAX_DOWNLOAD bytes). Returns (bytes, sha256 hex)."""
    req = urllib.request.Request(_safe_url(url), method="GET")
    h = hashlib.sha256()
    n = 0
    try:
        with OPENER.open(req, timeout=TIMEOUT) as resp, open(dest_file, "wb") as out:
            while True:
                buf = resp.read(CHUNK)
                if not buf:
                    break
                n += len(buf)
                if n > MAX_DOWNLOAD:
                    raise CheckoutError(f"artifact is larger than {MAX_DOWNLOAD} bytes")
                h.update(buf)
                out.write(buf)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise NotFound("artifact not found (HTTP 404)") from None
        raise CheckoutError(f"artifact server answered HTTP {e.code}") from None
    except (urllib.error.URLError, OSError) as e:
        if isinstance(e, CheckoutError):
            raise
        raise CheckoutError(f"could not fetch the artifact: {type(e).__name__}") from None
    return n, h.hexdigest()


def member_path(name):
    """Normalised relative path of a tar member, or None when it must be skipped."""
    if not isinstance(name, str) or "\x00" in name or "\\" in name or name.startswith("/"):
        return None
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    return "/".join(parts)


def included(rel, prefixes):
    if not prefixes:
        return True
    for p in prefixes:
        p = p.rstrip("/")
        if rel == p or rel.startswith(p + "/"):
            return True
    return False


def _inside(path, root):
    return os.path.commonpath([os.path.realpath(path), root]) == root


def extract(archive, dest, prefixes):
    """Unpack `archive` into `dest`. Returns counts. Raises CheckoutError on a cap."""
    stats = {"files": 0, "bytes": 0, "skipped_links": 0, "skipped_unsafe": 0, "skipped_other": 0,
             "skipped_excluded": 0}
    real_dest = os.path.realpath(dest)
    try:
        tf = tarfile.open(archive, mode="r:gz")
    except (tarfile.TarError, OSError, EOFError):
        raise CheckoutError("artifact is not a gzip tar archive") from None
    with tf:
        try:
            for m in tf:
                rel = member_path(m.name)
                if rel is None:
                    stats["skipped_unsafe"] += 1
                    continue
                if m.issym() or m.islnk():
                    stats["skipped_links"] += 1
                    continue
                if not (m.isfile() or m.isdir()):
                    stats["skipped_other"] += 1
                    continue
                if not included(rel, prefixes):
                    stats["skipped_excluded"] += 1
                    continue
                target = os.path.join(real_dest, *rel.split("/"))
                if m.isdir():
                    os.makedirs(target, mode=0o755, exist_ok=True)
                    if not _inside(target, real_dest):
                        raise CheckoutError("a directory resolved outside the checkout")
                    continue
                if m.size > MAX_FILE:
                    stats["skipped_other"] += 1
                    continue
                if stats["files"] + 1 > MAX_FILES:
                    raise CheckoutError(f"artifact has more than {MAX_FILES} files")
                if stats["bytes"] + m.size > MAX_EXTRACT:
                    raise CheckoutError(f"artifact unpacks to more than {MAX_EXTRACT} bytes")
                parent = os.path.dirname(target)
                os.makedirs(parent, mode=0o755, exist_ok=True)
                # Belt and braces: we never create a symlink, so the parent can only resolve outside
                # dest through a bug — refuse rather than write there.
                if not _inside(parent, real_dest):
                    raise CheckoutError("a file resolved outside the checkout")
                if os.path.lexists(target):
                    stats["skipped_unsafe"] += 1   # duplicate member name: first one wins
                    continue
                src = tf.extractfile(m)
                if src is None:
                    stats["skipped_other"] += 1
                    continue
                written = 0
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o444)
                with os.fdopen(fd, "wb") as out:
                    while True:
                        buf = src.read(CHUNK)
                        if not buf:
                            break
                        written += len(buf)
                        if written > MAX_FILE:
                            raise CheckoutError("an archive member is larger than its header says")
                        out.write(buf)
                stats["files"] += 1
                stats["bytes"] += written
        except (tarfile.TarError, EOFError, OSError) as e:
            if isinstance(e, CheckoutError):
                raise
            raise CheckoutError(f"archive could not be read: {type(e).__name__}") from None
    return stats


def served_name(url):
    return posixpath.basename(urllib.parse.urlparse(url).path)


def run():
    url = os.environ.get("CHECKOUT_URL", "")
    fallback = os.environ.get("CHECKOUT_FALLBACK_URL", "")
    dest = os.environ.get("CHECKOUT_DEST", "")
    info_path = os.environ.get("CHECKOUT_INFO", "")
    try:
        prefixes = json.loads(os.environ.get("CHECKOUT_INCLUDE") or "[]")
        if not (isinstance(prefixes, list) and all(isinstance(p, str) for p in prefixes)):
            raise ValueError
    except ValueError:
        prefixes = None
    info = {"ok": False, "requested": served_name(url) if url else None, "served": None}
    t0 = time.monotonic()
    try:
        if not (url and dest and info_path):
            raise CheckoutError("CHECKOUT_URL, CHECKOUT_DEST and CHECKOUT_INFO are required")
        if prefixes is None:
            raise CheckoutError("CHECKOUT_INCLUDE is not a JSON list of strings")
        os.makedirs(dest, mode=0o755, exist_ok=True)
        if os.listdir(dest):
            raise CheckoutError("checkout destination is not empty")
        tmpdir = os.environ.get("TMPDIR") or "/tmp"
        os.makedirs(tmpdir, exist_ok=True)
        archive = os.path.join(tmpdir, "artifact.tar.gz")
        used = url
        try:
            size, digest = download(url, archive)
        except NotFound:
            if not fallback:
                raise
            log("checkout_fallback", requested=served_name(url), fallback=served_name(fallback))
            used = fallback
            size, digest = download(fallback, archive)
        stats = extract(archive, dest, prefixes)
        try:
            os.unlink(archive)
        except OSError:
            pass
        info.update(ok=True, served=served_name(used), sha256=digest, archive_bytes=size,
                    include=prefixes, **stats)
    except CheckoutError as e:
        info["error"] = str(e)[:300]
    except Exception as e:  # noqa: BLE001 — never crash: the agent reports the failure instead
        info["error"] = f"internal error: {type(e).__name__}"
    info["ms"] = int((time.monotonic() - t0) * 1000)
    log("checkout", **{k: v for k, v in info.items() if k != "include"})
    if info_path:
        try:
            with open(info_path, "w") as f:
                json.dump(info, f)
        except OSError:
            pass
    return info


def main():
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
