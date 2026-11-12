"""Slice 3 runtime tests: the checkout init step, the read-only repo tools and their confinement, and
`plan` results end to end (agent loop -> marker line -> the RUNNER's own validator). No network beyond
loopback; the fake servers come from test_agent_run.py."""
import base64
import importlib.util
import io
import json
import os
import sys
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import checkout as CO  # noqa: E402
import repo_tools as RT  # noqa: E402
import result as R  # noqa: E402
from test_agent_run import (MCP_KEY, TOOLS, FakeLLM, FakeMCP, call, offered_names, run_agent,  # noqa: E402,F401
                            servers, submit, tool_messages)

# The runner's validator, loaded by path (it is a different image; this pins the two together).
_spec = importlib.util.spec_from_file_location("runner_results", HERE.parent / "agentrunner" / "results.py")
RUNNER = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RUNNER)

SHA = "0123456789abcdef0123456789abcdef01234567"


# -- helpers -------------------------------------------------------------------------------------
def make_tar(members):
    """members: list of (name, kind, payload). kind: file|dir|symlink|hardlink|fifo."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, kind, payload in members:
            ti = tarfile.TarInfo(name)
            if kind == "file":
                data = payload.encode() if isinstance(payload, str) else payload
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data))
                continue
            ti.type = {"dir": tarfile.DIRTYPE, "symlink": tarfile.SYMTYPE, "hardlink": tarfile.LNKTYPE,
                       "fifo": tarfile.FIFOTYPE}[kind]
            if kind in ("symlink", "hardlink"):
                ti.linkname = payload
            tf.addfile(ti)
    return buf.getvalue()


class ArtifactServer:
    """Serves {path: bytes}; anything else is 404. Records the paths requested."""

    def __init__(self, files):
        self.files, self.paths = files, []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                outer.paths.append(self.path)
                body = outer.files.get(self.path)
                self.send_response(200 if body is not None else 404)
                self.send_header("Content-Length", str(len(body or b"")))
                self.end_headers()
                self.wfile.write(body or b"")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def art():
    made = []

    def make(files):
        s = ArtifactServer(files)
        made.append(s)
        return s
    yield make
    for s in made:
        s.close()


def run_checkout(tmp_path, monkeypatch, url, fallback="", include=None):
    dest, info = tmp_path / "repo" / "tree", tmp_path / "repo" / "checkout.json"
    (tmp_path / "repo").mkdir(exist_ok=True)
    (tmp_path / "tmp").mkdir(exist_ok=True)
    for k, v in {"CHECKOUT_URL": url, "CHECKOUT_FALLBACK_URL": fallback, "CHECKOUT_DEST": str(dest),
                 "CHECKOUT_INFO": str(info), "CHECKOUT_INCLUDE": json.dumps(include or []),
                 "TMPDIR": str(tmp_path / "tmp")}.items():
        monkeypatch.setenv(k, v)
    CO.run()
    return dest, json.loads(info.read_text())


REPO = [("clusters/", "dir", None), ("clusters/pi-k3s/", "dir", None),
        ("clusters/pi-k3s/agents/rbac.yaml", "file", "kind: Role\nrules:\n  - verbs: [get]\n"),
        ("clusters/pi-k3s/agents/networkpolicies.yaml", "file", "kind: NetworkPolicy\n# ipBlock 192.168.1.70/32\n"),
        ("docs/secrets-map.md", "file", "graph\n"), ("README.md", "file", "hello\n")]


# -- checkout ------------------------------------------------------------------------------------
def test_checkout_fetches_exact_revision_and_unpacks(tmp_path, monkeypatch, art):
    srv = art({f"/gitrepository/flux-system/flux-system/{SHA}.tar.gz": make_tar(REPO)})
    root = f"{srv.base}/gitrepository/flux-system/flux-system/"
    dest, info = run_checkout(tmp_path, monkeypatch, root + f"{SHA}.tar.gz", root + "latest.tar.gz")
    assert info["ok"] is True and info["served"] == f"{SHA}.tar.gz" and info["requested"] == f"{SHA}.tar.gz"
    assert info["files"] == 4 and len(info["sha256"]) == 64
    assert (dest / "clusters/pi-k3s/agents/rbac.yaml").read_text().startswith("kind: Role")
    assert srv.paths == [f"/gitrepository/flux-system/flux-system/{SHA}.tar.gz"]


def test_checkout_falls_back_to_latest_and_says_so(tmp_path, monkeypatch, art):
    srv = art({"/g/latest.tar.gz": make_tar(REPO)})
    _, info = run_checkout(tmp_path, monkeypatch, f"{srv.base}/g/{SHA}.tar.gz", f"{srv.base}/g/latest.tar.gz")
    assert info["ok"] and info["requested"] == f"{SHA}.tar.gz" and info["served"] == "latest.tar.gz"


def test_checkout_include_filters(tmp_path, monkeypatch, art):
    srv = art({"/a.tar.gz": make_tar(REPO)})
    dest, info = run_checkout(tmp_path, monkeypatch, srv.base + "/a.tar.gz",
                              include=["clusters/", "docs/secrets-map.md"])
    assert info["ok"] and info["files"] == 3 and info["skipped_excluded"] == 1
    assert not (dest / "README.md").exists() and (dest / "docs/secrets-map.md").exists()


def test_checkout_skips_links_traversal_and_devices(tmp_path, monkeypatch, art):
    outside = tmp_path / "outside.txt"
    evil = make_tar(REPO + [
        ("../outside.txt", "file", "pwned"), ("/abs.txt", "file", "pwned"),
        ("clusters/../../outside.txt", "file", "pwned"),
        ("clusters/link", "symlink", "/etc/passwd"), ("clusters/up", "symlink", "../../.."),
        ("clusters/hard", "hardlink", "clusters/pi-k3s/agents/rbac.yaml"),
        ("clusters/fifo", "fifo", None), ("clusters/x\\y", "file", "bs")])
    srv = art({"/a.tar.gz": evil})
    dest, info = run_checkout(tmp_path, monkeypatch, srv.base + "/a.tar.gz")
    assert info["ok"] and info["files"] == 4
    assert info["skipped_links"] == 3 and info["skipped_unsafe"] == 4 and info["skipped_other"] == 1
    assert not outside.exists() and not (tmp_path / "abs.txt").exists()
    for p in dest.rglob("*"):
        assert not p.is_symlink()


def test_checkout_caps(tmp_path, monkeypatch, art):
    srv = art({"/a.tar.gz": make_tar([(f"f{i}", "file", "x") for i in range(5)]),
               "/big.tar.gz": make_tar([("big", "file", "y" * 5000)])})
    monkeypatch.setattr(CO, "MAX_FILES", 3)
    _, info = run_checkout(tmp_path, monkeypatch, srv.base + "/a.tar.gz")
    assert info["ok"] is False and "more than 3 files" in info["error"]
    monkeypatch.setattr(CO, "MAX_FILES", 100)
    monkeypatch.setattr(CO, "MAX_DOWNLOAD", 50)     # the gzip is ~100 bytes
    (tmp_path / "b").mkdir()
    _, info = run_checkout(tmp_path / "b", monkeypatch, srv.base + "/big.tar.gz")
    assert info["ok"] is False and "larger than 50 bytes" in info["error"]
    monkeypatch.setattr(CO, "MAX_DOWNLOAD", 10_000)
    monkeypatch.setattr(CO, "MAX_EXTRACT", 4000)      # a small download that unpacks big (a "bomb")
    (tmp_path / "c").mkdir()
    _, info = run_checkout(tmp_path / "c", monkeypatch, srv.base + "/big.tar.gz")
    assert info["ok"] is False and "unpacks to more than 4000 bytes" in info["error"]


def test_checkout_failures_never_crash(tmp_path, monkeypatch, art):
    srv = art({"/junk.tar.gz": b"not a tarball"})
    _, info = run_checkout(tmp_path, monkeypatch, srv.base + "/missing.tar.gz")
    assert info["ok"] is False and "404" in info["error"]
    (tmp_path / "b").mkdir()
    _, info = run_checkout(tmp_path / "b", monkeypatch, srv.base + "/junk.tar.gz")
    assert info["ok"] is False and "gzip tar" in info["error"]
    (tmp_path / "c").mkdir()
    _, info = run_checkout(tmp_path / "c", monkeypatch, "file:///etc/passwd")
    assert info["ok"] is False and "http" in info["error"]


# -- repo tools: confinement ---------------------------------------------------------------------
@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "tree"
    (root / "clusters/pi-k3s/agents").mkdir(parents=True)
    (root / "clusters/pi-k3s/agents/rbac.yaml").write_text("kind: Role\nrules:\n  - verbs: ['*']\n")
    (root / "clusters/pi-k3s/agents/blob.bin").write_bytes(b"\x00\x01binary")
    (root / "secret-outside.txt").write_text("x")
    (tmp_path / "outside.txt").write_text("OUTSIDE-SECRET")
    (tmp_path / "outdir").mkdir()
    (tmp_path / "outdir" / "o.yaml").write_text("OUTSIDE-SECRET\n")
    os.symlink(tmp_path / "outside.txt", root / "clusters/link.txt")
    os.symlink(tmp_path / "outdir", root / "clusters/linkdir")
    return RT.RepoTools(str(root)), tmp_path


@pytest.mark.parametrize("path", ["../outside.txt", "/etc/passwd", "clusters/../../outside.txt",
                                  "clusters/link.txt", "clusters/linkdir/o.yaml", "clusters/linkdir",
                                  "a\x00b", "clusters\\pi-k3s", "x" * 600, 5, ["a"]])
def test_repo_tools_refuse_escape(repo, path):
    tools, _ = repo
    for name, args in (("read_file", {"path": path}), ("list_files", {"path": path}),
                       ("search", {"query": "OUTSIDE", "path": path})):
        text, ok = tools.call(name, args)
        assert ok is False and text.startswith("ERROR:"), (name, path, text)
        assert "OUTSIDE-SECRET" not in text


def test_repo_tools_refuse_symlinks_even_inside_the_root(repo):
    """The lstat guard on its own: a link that stays inside the root is still refused (the checkout never
    writes links, so one appearing is a bug or an attack). The realpath/commonpath check is the second line
    for links that leave the root; test_repo_tools_refuse_escape covers that pair."""
    tools, _ = repo
    os.symlink(os.path.join(tools.root, "clusters/pi-k3s"), os.path.join(tools.root, "alias"))
    for name, args in (("read_file", {"path": "alias/agents/rbac.yaml"}), ("list_files", {"path": "alias"})):
        text, ok = tools.call(name, args)
        assert ok is False and "symbolic links" in text, text


def test_repo_tools_walks_skip_symlinks(repo):
    tools, _ = repo
    listing, ok = tools.call("list_files", {"path": "", "max_depth": 6})
    assert ok and "clusters/pi-k3s/agents/rbac.yaml" in listing
    assert "link" not in listing
    found, ok = tools.call("search", {"query": "OUTSIDE-SECRET"})
    assert ok and found.startswith("no matches")


def test_repo_tools_read_search_and_caps(repo, monkeypatch):
    tools, _ = repo
    text, ok = tools.call("read_file", {"path": "clusters/pi-k3s/agents/rbac.yaml"})
    assert ok and "    3  " in text and "(lines 1-3 of 3)" in text
    text, ok = tools.call("read_file", {"path": "clusters/pi-k3s/agents/blob.bin"})
    assert not ok and "binary" in text
    text, ok = tools.call("search", {"query": "VERBS"})
    assert ok and text.startswith("clusters/pi-k3s/agents/rbac.yaml:3:")
    assert tools.call("search", {"query": "VERBS", "case_sensitive": True})[0].startswith("no matches")
    assert tools.call("search", {"query": "(a+)+$"})[1] is True  # literal, not a regex
    assert tools.call("search", {"query": "x"})[1] is False       # too short
    monkeypatch.setattr(RT, "READ_MAX_LINES", 2)
    text, _ = tools.call("read_file", {"path": "clusters/pi-k3s/agents/rbac.yaml"})
    assert "more: start_line=3" in text
    monkeypatch.setattr(RT, "FILE_MAX_BYTES", 4)
    assert "larger than" in tools.call("read_file", {"path": "clusters/pi-k3s/agents/rbac.yaml"})[0]


# -- the agent loop with a checkout --------------------------------------------------------------
def plan(**over):
    p = {"kind": "plan", "title": "Role grants * verbs", "severity": "high",
         "fingerprint": {"rule": "rbac-wildcard", "resource": "agents/Role/agent-runner"},
         "plan": {"found": "wildcard verbs", "evidence": "clusters/pi-k3s/agents/rbac.yaml:3  - verbs: ['*']",
                  "likely_cause": "copy-paste", "proposed_change": "list the verbs", "risk": "low",
                  "verify": "kubectl auth can-i", "rollback": "revert the PR"}}
    p.update(over)
    return p


def sec_manifest(mcp_url):
    return {"kind": "Agent", "name": "sec-researcher", "purpose": "review access control",
            "image": "x", "data_class": "system", "model": {"allow": ["claude-haiku"]},
            "secret": "agent-sec-researcher", "checkout": {"source": "flux-system/flux-system"},
            "connectors": {"mcp": [{"name": "homelab", "url": mcp_url, "header": "X-API-Key",
                                    "key_env": "MCP_HOMELAB_READONLY_KEY", "tools": ["get_cluster_health"]}]},
            "outputs": ["plan"], "prompt": "Review.", "limits": {"timeout": "20m", "runs_per_day": 6, "max_steps": 10}}


SEC_EVENT = {"id": "01JDSEC", "type": "security.flux_revision", "source": "flux", "subject": "rev:0123456",
             "trust": "internal", "data": {"revision": SHA, "changed_paths": ["clusters/pi-k3s/agents/rbac.yaml"]}}


def checkout_env(repo, ok=True, served=f"{SHA}.tar.gz"):
    tools, tmp = repo
    info = tmp / "checkout.json"
    info.write_text(json.dumps({"ok": ok, "requested": f"{SHA}.tar.gz", "served": served, "files": 3}
                               if ok else {"ok": False, "error": "artifact not found (HTTP 404)"}))
    return {"AGENT_REPO_DIR": tools.root, "AGENT_CHECKOUT_INFO": str(info)}


def runner_accepts(res):
    line = R.marker_line(res)
    st, _, why = RUNNER.parse_result(line, ["plan"])
    return st == RUNNER.OK, why


def test_agent_reads_repo_and_submits_plan(servers, repo):
    mcp = servers(FakeMCP, TOOLS)
    llm = servers(FakeLLM, [call("repo__read_file", {"path": "clusters/pi-k3s/agents/rbac.yaml"}),
                            call("repo__read_file", {"path": "../outside.txt"}),
                            submit(outcome="needs_human", summary="1 high", outputs=[plan()])])
    res, logs, _ = run_agent(sec_manifest(mcp.url), llm, event=SEC_EVENT, extra_env=checkout_env(repo))
    assert res["outcome"] == "needs_human" and res["outputs"] == [plan()]
    assert runner_accepts(res) == (True, None)
    assert offered_names(llm.requests[0]) == ["homelab__get_cluster_health", "repo__list_files",
                                              "repo__read_file", "repo__search", "submit_result"]
    msgs = tool_messages(llm.requests[2])
    assert "verbs: ['*']" in msgs[0]["content"] and msgs[1]["content"].startswith("ERROR:")
    assert "OUTSIDE-SECRET" not in json.dumps(llm.requests[2]["json"])
    user = llm.requests[0]["json"]["messages"][1]["content"]
    assert "read-only copy of the repository" in user and "DATA" in user and "no longer serves" not in user
    sub = next(t for t in llm.requests[0]["json"]["tools"] if t["function"]["name"] == "submit_result")
    item = sub["function"]["parameters"]["properties"]["outputs"]["items"]
    assert item["properties"]["kind"]["enum"] == ["plan"] and "fingerprint" in item["required"]
    assert not any(m.get("method") == "tools/call" for m in mcp.calls)  # repo tools never go to the MCP


def test_revision_fallback_is_told_to_the_model(servers, repo):
    mcp = servers(FakeMCP, TOOLS)
    llm = servers(FakeLLM, [submit(outcome="nothing_to_do", summary="none", outputs=[])])
    run_agent(sec_manifest(mcp.url), llm, event=SEC_EVENT, extra_env=checkout_env(repo, served="latest.tar.gz"))
    assert "no longer serves" in llm.requests[0]["json"]["messages"][1]["content"]


def test_failed_checkout_is_a_failed_run(servers, repo):
    mcp = servers(FakeMCP, TOOLS)
    llm = servers(FakeLLM, [submit(outputs=[plan()])])
    res, _, _ = run_agent(sec_manifest(mcp.url), llm, event=SEC_EVENT, extra_env=checkout_env(repo, ok=False))
    assert res["outcome"] == "failed" and "repository checkout failed" in res["summary"] and "404" in res["summary"]
    assert llm.requests == []
    res, _, _ = run_agent(sec_manifest(mcp.url), llm, event=SEC_EVENT, drop=("AGENT_REPO_DIR",),
                          extra_env={"AGENT_CHECKOUT_INFO": "/nonexistent"})
    assert res["outcome"] == "failed" and "AGENT_REPO_DIR" in res["summary"]


def test_bad_plan_is_bounced_to_the_model_then_fixed(servers, repo):
    mcp = servers(FakeMCP, TOOLS)
    bad = plan(fingerprint={"rule": "RBAC Wildcard", "resource": "agent-runner"})
    llm = servers(FakeLLM, [submit(outputs=[bad]), submit(outcome="needs_human", outputs=[plan()])])
    res, logs, _ = run_agent(sec_manifest(mcp.url), llm, event=SEC_EVENT, extra_env=checkout_env(repo))
    assert res["outputs"] == [plan()] and runner_accepts(res)[0]
    err = tool_messages(llm.requests[1])[-1]["content"]
    assert "fingerprint.rule" in err and "fingerprint.resource" in err
    assert any(r["event"] == "submit_rejected" for r in logs)


def test_finalize_makes_any_plan_runner_valid():
    """The last gate: truncation + redaction keep plans valid; structurally bad plans are dropped, so the
    runner never has to reject a Result the runtime emitted."""
    huge = plan(title="t" * 500 + "\nsecond line")
    huge["plan"] = {k: "é" * 9000 for k in R.PLAN_SECTIONS}
    broken = plan(severity="urgent")
    extra = dict(plan(), body="x")
    out = R.finalize({"outcome": "needs_human", "summary": "s", "outputs": [huge, broken, extra, plan()]}, ["plan"])
    assert len(out["outputs"]) == 2 and "dropped a plan output" in out["summary"]
    assert "\n" not in out["outputs"][0]["title"] and len(out["outputs"][0]["title"]) <= 200
    assert runner_accepts(out) == (True, None)
    for p in out["outputs"]:
        assert RUNNER.validate_plan(p) is None


def test_runtime_and_runner_plan_rules_agree():
    for name in ("PLAN_SECTIONS", "PLAN_SEVERITIES", "PLAN_SECTION_BYTES", "PLAN_EVIDENCE_BYTES"):
        assert getattr(R, name) == getattr(RUNNER, name), name
    assert R.PLAN_RULE_RE.pattern == RUNNER.PLAN_RULE_RE.pattern
    assert R.PLAN_RESOURCE_RE.pattern == RUNNER.PLAN_RESOURCE_RE.pattern
    assert R.TITLE_MAX_CHARS == RUNNER.PLAN_TITLE_CHARS
