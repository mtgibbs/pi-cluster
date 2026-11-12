"""Read-only file tools over the repo checkout (manifest `checkout:`, CONTRACT §4a/§6).

The checkout is a directory the init container filled and the agent container mounts read-only.
These tools are the ONLY way the model sees it, and they are confined to that directory:

- a path is relative, '/'-separated, with no '..' component, no NUL, no backslash;
- every component is lstat()ed and a symlink anywhere on the way is refused (the checkout step
  never writes symlinks; this is the second line, in case one ever appears);
- the resolved path must still be inside the root (os.path.commonpath on realpaths);
- directory walks never follow symlinks and skip them;
- reads, listings and searches are size- and count-capped, and binary files are refused.

Search is a literal substring match, never a regex: a model-supplied pattern cannot backtrack
for minutes. Stdlib only.
"""
import os
import posixpath
import stat

READ_MAX_BYTES = 64 * 1024          # one read_file reply
READ_MAX_LINES = 800
FILE_MAX_BYTES = 2 * 1024 * 1024    # files larger than this are not read or searched
LIST_MAX_ENTRIES = 500
LIST_MAX_DEPTH = 6
SEARCH_MAX_MATCHES = 100
SEARCH_MAX_FILES = 20000
SEARCH_LINE_CHARS = 300
QUERY_MIN, QUERY_MAX = 2, 200
PATH_MAX = 512

NAMES = ("list_files", "read_file", "search")
PREFIX = "repo__"


class RepoPathError(ValueError):
    pass


def tool_definitions():
    """OpenAI function tools, named repo__<tool>."""
    path = {"type": "string", "description": "path relative to the repository root, '/'-separated; "
                                             "'' or '.' is the root"}
    return [
        {"type": "function", "function": {
            "name": PREFIX + "list_files",
            "description": "List files and directories in the read-only repository checkout. Directories end "
                           f"with '/'. At most {LIST_MAX_ENTRIES} entries.",
            "parameters": {"type": "object", "properties": {
                "path": path,
                "max_depth": {"type": "integer", "minimum": 1, "maximum": LIST_MAX_DEPTH,
                              "description": "how many directory levels to descend (default 2)"}},
                "additionalProperties": False}}},
        {"type": "function", "function": {
            "name": PREFIX + "read_file",
            "description": "Read a text file from the read-only repository checkout, with line numbers. "
                           f"At most {READ_MAX_LINES} lines / {READ_MAX_BYTES // 1024} KiB per call; use "
                           "start_line to page.",
            "parameters": {"type": "object", "properties": {
                "path": path,
                "start_line": {"type": "integer", "minimum": 1},
                "max_lines": {"type": "integer", "minimum": 1, "maximum": READ_MAX_LINES}},
                "required": ["path"], "additionalProperties": False}}},
        {"type": "function", "function": {
            "name": PREFIX + "search",
            "description": "Find lines containing a literal string (not a regex) in the read-only repository "
                           f"checkout. Returns path:line: text, at most {SEARCH_MAX_MATCHES} matches.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string", "minLength": QUERY_MIN, "maxLength": QUERY_MAX},
                "path": {"type": "string", "description": "only search under this directory or file"},
                "case_sensitive": {"type": "boolean"}},
                "required": ["query"], "additionalProperties": False}}},
    ]


class RepoTools:
    def __init__(self, root):
        real = os.path.realpath(root)
        if not os.path.isdir(real):
            raise RepoPathError("repository checkout directory does not exist")
        self.root = real

    # -- confinement -----------------------------------------------------------------------------
    def resolve(self, rel):
        """Absolute path of `rel` inside the root, or RepoPathError. Never follows a symlink."""
        if rel is None:
            rel = ""
        if not isinstance(rel, str):
            raise RepoPathError("path must be a string")
        if len(rel) > PATH_MAX or "\x00" in rel or "\\" in rel:
            raise RepoPathError("path is not allowed")
        if rel.startswith("/"):
            raise RepoPathError("path must be relative to the repository root")
        parts = [p for p in rel.split("/") if p not in ("", ".")]
        if any(p == ".." for p in parts):
            raise RepoPathError("'..' is not allowed in a path")
        cur = self.root
        for p in parts:
            cur = os.path.join(cur, p)
            try:
                st = os.lstat(cur)
            except FileNotFoundError:
                raise RepoPathError(f"no such file or directory: {posixpath.join(*parts)}") from None
            except OSError:
                raise RepoPathError("path is not accessible") from None
            if stat.S_ISLNK(st.st_mode):
                raise RepoPathError("symbolic links are not followed")
        real = os.path.realpath(cur)
        if os.path.commonpath([real, self.root]) != self.root:
            raise RepoPathError("path escapes the repository root")
        return real

    def _rel(self, abspath):
        return os.path.relpath(abspath, self.root).replace(os.sep, "/")

    # -- tools -----------------------------------------------------------------------------------
    def call(self, name, args):
        """(text, ok). Never raises for bad input; the model gets the error as text."""
        args = args if isinstance(args, dict) else {}
        try:
            if name == "list_files":
                return self.list_files(args.get("path", ""), args.get("max_depth", 2)), True
            if name == "read_file":
                return self.read_file(args.get("path"), args.get("start_line", 1),
                                      args.get("max_lines", READ_MAX_LINES)), True
            if name == "search":
                return self.search(args.get("query"), args.get("path", ""),
                                   bool(args.get("case_sensitive", False))), True
        except RepoPathError as e:
            return f"ERROR: {e}", False
        return f"ERROR: unknown repo tool {name!r}", False

    def list_files(self, rel, max_depth=2):
        base = self.resolve(rel)
        if not os.path.isdir(base):
            raise RepoPathError("not a directory (use read_file for files)")
        depth = max_depth if isinstance(max_depth, int) and not isinstance(max_depth, bool) else 2
        depth = max(1, min(LIST_MAX_DEPTH, depth))
        out, truncated = [], False
        stack = [(base, 1)]
        while stack:
            d, lvl = stack.pop()
            try:
                entries = sorted(os.scandir(d), key=lambda e: e.name)
            except OSError:
                continue
            subdirs = []
            for e in entries:
                if e.is_symlink():
                    continue
                if len(out) >= LIST_MAX_ENTRIES:
                    truncated = True
                    break
                if e.is_dir(follow_symlinks=False):
                    out.append(self._rel(e.path) + "/")
                    if lvl < depth:
                        subdirs.append((e.path, lvl + 1))
                elif e.is_file(follow_symlinks=False):
                    out.append(self._rel(e.path))
            if truncated:
                break
            stack.extend(reversed(subdirs))
        text = "\n".join(sorted(out)) or "(empty directory)"
        if truncated:
            text += f"\n[repo: listing truncated at {LIST_MAX_ENTRIES} entries; list a subdirectory]"
        return text

    def _read_text(self, abspath):
        st = os.lstat(abspath)
        if not stat.S_ISREG(st.st_mode):
            raise RepoPathError("not a regular file")
        if st.st_size > FILE_MAX_BYTES:
            raise RepoPathError(f"file is larger than {FILE_MAX_BYTES} bytes")
        with open(abspath, "rb") as f:
            raw = f.read(FILE_MAX_BYTES + 1)
        if b"\x00" in raw[:8192]:
            raise RepoPathError("binary file")
        return raw.decode("utf-8", errors="replace")

    def read_file(self, rel, start_line=1, max_lines=READ_MAX_LINES):
        if not isinstance(rel, str) or rel.strip() in ("", "."):
            raise RepoPathError("path is required")
        p = self.resolve(rel)
        if os.path.isdir(p):
            raise RepoPathError("is a directory (use list_files)")
        text = self._read_text(p)
        lines = text.splitlines()
        start = start_line if isinstance(start_line, int) and not isinstance(start_line, bool) else 1
        start = max(1, start)
        n = max_lines if isinstance(max_lines, int) and not isinstance(max_lines, bool) else READ_MAX_LINES
        n = max(1, min(READ_MAX_LINES, n))
        chunk, size, last = [], 0, start - 1
        for i in range(start - 1, min(len(lines), start - 1 + n)):
            row = f"{i + 1:>5}  {lines[i]}"
            size += len(row.encode("utf-8")) + 1
            if size > READ_MAX_BYTES:
                break
            chunk.append(row)
            last = i + 1
        head = f"{self._rel(p)} (lines {start}-{last} of {len(lines)})"
        if last < len(lines):
            head += f"; more: start_line={last + 1}"
        return head + "\n" + "\n".join(chunk)

    def search(self, query, rel="", case_sensitive=False):
        if not (isinstance(query, str) and QUERY_MIN <= len(query) <= QUERY_MAX) or "\n" in query:
            raise RepoPathError(f"query must be a single-line string of {QUERY_MIN}..{QUERY_MAX} chars")
        base = self.resolve(rel)
        needle = query if case_sensitive else query.lower()
        files = [base] if os.path.isfile(base) else None
        matches, scanned = [], 0
        if files is None:
            files = []
            for d, dirs, names in os.walk(base, followlinks=False):
                dirs[:] = sorted(x for x in dirs if not os.path.islink(os.path.join(d, x)))
                for nm in sorted(names):
                    files.append(os.path.join(d, nm))
                    if len(files) >= SEARCH_MAX_FILES:
                        break
                if len(files) >= SEARCH_MAX_FILES:
                    break
        for fp in files:
            if os.path.islink(fp):
                continue
            try:
                text = self._read_text(fp)
            except (RepoPathError, OSError):
                continue
            scanned += 1
            for no, line in enumerate(text.splitlines(), 1):
                hay = line if case_sensitive else line.lower()
                if needle in hay:
                    matches.append(f"{self._rel(fp)}:{no}: {line.strip()[:SEARCH_LINE_CHARS]}")
                    if len(matches) >= SEARCH_MAX_MATCHES:
                        return "\n".join(matches) + f"\n[repo: stopped at {SEARCH_MAX_MATCHES} matches; narrow the path]"
        return "\n".join(matches) if matches else f"no matches ({scanned} files searched)"
