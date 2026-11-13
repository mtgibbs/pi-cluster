#!/usr/bin/env python3
"""checkout — the init container of an agent Job whose manifest has `checkout:` (CONTRACT §4a).

Fetches a Flux source-controller artifact (a .tar.gz of the Git tree at one revision, always named
`<commit sha>.tar.gz` — source-controller serves no `latest.tar.gz`) over in-cluster HTTP and unpacks it
into CHECKOUT_DEST, which the agent container then mounts READ-ONLY. It holds no
credential: the artifact server is unauthenticated, and only this pod's NetworkPolicy reaches it.

The archive is untrusted input. Extraction is done by hand, never tarfile.extractall:
- only regular files and directories are written; symlinks, hard links, devices and FIFOs are skipped;
- a member name that is absolute, contains '..', NUL or a backslash is skipped;
- the download, the unpacked total, each file and the file count are capped;
- CHECKOUT_INCLUDE (a JSON list of path prefixes) limits what is unpacked.

Connection-level failures (refused, reset, timeout, DNS) are retried with capped exponential backoff
inside one CHECKOUT_RETRY_BUDGET (seconds, default 45) shared by the revision fetch and the fallback:
a brand-new pod's first connection can be refused for a moment while the NetworkPolicy engine
(kube-router, which REJECTs) is still programming rules for it. A clean HTTP 404 on the revision is
never retried — it goes straight to CHECKOUT_FALLBACK_URL (the GitRepository's current artifact, which the
runner resolved when it rendered the Job), if there is one. Every attempt is logged to stdout with
kind "requested" or "fallback".

It ALWAYS exits 0 and writes CHECKOUT_INFO ({"ok": true|false, ...}). The agent runtime reads that file
and, when ok is false, emits a `failed` Result naming the reason — a clearer failure than an init
container crash, which would leave the agent container's log (where the runner looks) empty.
"""
import hashlib
import http.client
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
TIMEOUT = float(os.environ.get("CHECKOUT_TIMEOUT", "15"))   # per socket operation, not per download
RETRY_BUDGET = float(os.environ.get("CHECKOUT_RETRY_BUDGET", "45"))  # seconds; 0 = a single attempt
RETRY_FIRST_DELAY = 0.5
RETRY_MAX_DELAY = 8.0
CHUNK = 64 * 1024

# Injectable for tests: no real sleeping there.
_clock = time.monotonic
_sleep = time.sleep


class CheckoutError(Exception):
    pass


class NotFound(CheckoutError):
    pass


class Transient(CheckoutError):
    """A connection-level failure worth retrying. `cls` is the underlying error class name only —
    never a message, URL or body."""

    def __init__(self, cls):
        super().__init__(f"connection failed: {cls}")
        self.cls = cls


def _error_class(e):
    """The most specific class name: URLError wraps the real cause (ConnectionRefusedError, gaierror,
    timeout…) in .reason, and that is what tells a refusal from a DNS failure."""
    reason = getattr(e, "reason", None)
    if isinstance(e, urllib.error.URLError) and isinstance(reason, BaseException):
        return type(reason).__name__
    return type(e).__name__


def _safe_url(url):
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise CheckoutError("checkout URL must be http(s)")
    return url


def download(url, dest_file):
    """Stream `url` into `dest_file` (≤ MAX_DOWNLOAD bytes). Returns (bytes, sha256 hex).
    Raises NotFound on 404, Transient on a connection-level failure, CheckoutError otherwise."""
    req = urllib.request.Request(_safe_url(url), method="GET")
    h = hashlib.sha256()
    n = 0
    try:
        out = open(dest_file, "wb")    # truncates: a retry never appends to a partial download
    except OSError as e:
        raise CheckoutError(f"could not write the artifact: {type(e).__name__}") from None
    with out:
        try:
            with OPENER.open(req, timeout=TIMEOUT) as resp:
                while True:
                    buf = resp.read(CHUNK)
                    if not buf:
                        break
                    n += len(buf)
                    if n > MAX_DOWNLOAD:
                        raise CheckoutError(f"artifact is larger than {MAX_DOWNLOAD} bytes")
                    h.update(buf)
                    try:
                        out.write(buf)
                    except OSError as e:
                        raise CheckoutError(f"could not write the artifact: {type(e).__name__}") from None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise NotFound("artifact not found (HTTP 404)") from None
            raise CheckoutError(f"artifact server answered HTTP {e.code}") from None
        except CheckoutError:
            raise
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            # Refused / reset / timed out / DNS / dropped mid-stream: nothing came back that says the
            # artifact is absent, so this is retryable. (HTTPError, a URLError subclass, is above.)
            raise Transient(_error_class(e)) from None
    return n, h.hexdigest()


def fetch(url, dest_file, deadline, kind="requested"):
    """download() with bounded retry on Transient errors until `deadline` (a _clock() value). At least
    one attempt is always made. NotFound and every other CheckoutError are raised at once. `kind`
    ("requested" | "fallback") labels logs and errors."""
    attempt = 0
    delay = RETRY_FIRST_DELAY
    while True:
        attempt += 1
        try:
            size, digest = download(url, dest_file)
        except Transient as e:
            remaining = deadline - _clock()
            retry = remaining > 0
            log("checkout_attempt", kind=kind, attempt=attempt, outcome="error", error=e.cls,
                retry_in=round(min(delay, remaining), 2) if retry else None)
            if not retry:
                raise CheckoutError(f"could not fetch the {kind} artifact: {e.cls} after {attempt} "
                                    f"attempt{'s' if attempt != 1 else ''}") from None
            _sleep(min(delay, remaining))
            delay = min(delay * 2, RETRY_MAX_DELAY)
            continue
        except NotFound:
            log("checkout_attempt", kind=kind, attempt=attempt, outcome="not_found")
            raise
        except CheckoutError:
            log("checkout_attempt", kind=kind, attempt=attempt, outcome="failed")
            raise
        log("checkout_attempt", kind=kind, attempt=attempt, outcome="ok", bytes=size)
        return size, digest


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
        deadline = _clock() + max(RETRY_BUDGET, 0.0)
        try:
            size, digest = fetch(url, archive, deadline, "requested")
        except NotFound:
            if not fallback:
                raise CheckoutError(f"artifact {served_name(url)} not found (HTTP 404)") from None
            log("checkout_fallback", requested=served_name(url), fallback=served_name(fallback))
            used = fallback
            try:
                size, digest = fetch(fallback, archive, deadline, "fallback")
            except NotFound:
                raise CheckoutError(f"neither artifact {served_name(url)} nor the fallback "
                                    f"{served_name(fallback)} was found (HTTP 404)") from None
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
