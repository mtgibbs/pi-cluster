"""agent-runner tests — no network (one loopback-only server smoke test). Run:
    python3 -m pytest scripts/agentrunner -q
"""
import base64
import copy
import json
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agentspec  # noqa: E402
import jobspec  # noqa: E402
import results  # noqa: E402
import runner as rmod  # noqa: E402
from kubeapi import KubeError  # noqa: E402
from ledger import Ledger  # noqa: E402

TOKEN = "s3cret-token"
CB = "http://n8n.n8n.svc.cluster.local:5678/webhook/"
NOW = datetime(2026, 11, 11, 12, 0, 0, tzinfo=timezone.utc)
SENTINEL = "PRIVATE-EVENT-DATA-7f3a"

MANIFEST = {
    "kind": "Agent",
    "name": "media-investigator",
    "purpose": "investigate media hangs",
    "image": "ghcr.io/mtgibbs/agent-runtime:0.1.0",
    "data_class": "system",
    "model": {"allow": ["hot-coder", "claude-haiku"]},
    "secret": "agent-media-investigator",
    "connectors": {"mcp": [{
        "name": "homelab",
        "url": "http://mcp-homelab.mcp-homelab.svc.cluster.local:3000/mcp",
        "header": "X-API-Key",
        "key_env": "MCP_HOMELAB_READONLY_KEY",
        "tools": ["get_media_status", "get_cluster_health"],
    }]},
    "outputs": ["report"],
    "prompt": "Investigate.\n",
    "limits": {"timeout": "15m", "runs_per_day": 3, "max_steps": 30},
}


def event(eid="01JD0001", **over):
    ev = {"id": eid, "type": "media.hang", "source": "matt", "subject": "jellyfin:apple-tv",
          "dedupe_key": "k", "trust": "internal", "data": {"ask": SENTINEL}}
    ev.update(over)
    return ev


def encode_result(res):
    return results.MARKER + base64.b64encode(json.dumps(res).encode()).decode()


GOOD = {"outcome": "done", "summary": "found it",
        "outputs": [{"kind": "report", "title": "Hang", "body": "# details"}]}


CUR_SHA = "89abcdef0123456789abcdef0123456789abcdef"   # what source-controller serves "now"


class FakeKube:
    def __init__(self):
        self.jobs = {}
        self.created = []
        self.deleted = []
        self.create_error = None
        self.logs = {}       # run_id -> log text
        self.no_pods = set()
        self.get_calls = 0
        # Flux GitRepository read by the runner for `checkout:` manifests (status.artifact.revision).
        self.gitrepo_revision = "main@sha1:" + CUR_SHA
        self.gitrepo_error = None
        self.gitrepo_calls = []

    def create_job(self, job):
        if self.create_error:
            raise self.create_error
        self.created.append(job)
        self.jobs[job["metadata"]["name"]] = copy.deepcopy(job)
        return job

    def get_job(self, name):
        self.get_calls += 1
        return self.jobs.get(name)

    def get_gitrepository(self, namespace, name):
        self.gitrepo_calls.append((namespace, name))
        if self.gitrepo_error:
            raise self.gitrepo_error
        art = {"revision": self.gitrepo_revision} if self.gitrepo_revision else None
        return {"kind": "GitRepository", "status": {"artifact": art} if art else {}}

    def delete_job(self, name):
        self.deleted.append(name)
        self.jobs.pop(name, None)

    def set_condition(self, run_id, ctype, reason=None):
        self.jobs[f"run-{run_id}"]["status"] = {"conditions": [
            {"type": ctype, "status": "True", "reason": reason,
             "lastTransitionTime": "2026-11-11T12:05:00Z"}]}

    def list_pods(self, selector):
        rid = selector.split("=", 1)[1]
        if rid in self.no_pods or rid not in self.logs:
            return []
        return [{"metadata": {"name": f"run-{rid}-abcde", "creationTimestamp": "x"}}]

    def pod_log(self, pod, container=None, tail_lines=None, limit_bytes=None):
        assert container == "agent"
        return self.logs[pod.removeprefix("run-").rsplit("-", 1)[0]]


class Clock:
    def __init__(self, t=NOW):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def env(tmp_path):
    mdir = tmp_path / "agents"
    mdir.mkdir()
    (mdir / "media-investigator.yaml").write_text(yaml.safe_dump(MANIFEST))
    cfg = rmod.Config(token=TOKEN, manifest_dir=str(mdir),
                      ledger_path=str(tmp_path / "data" / "ledger.jsonl"),
                      callback_prefixes=[CB], local_models=["hot-coder"],
                      litellm_base_url="http://litellm.ai.svc:4000",
                      node_hostnames=["pi5-worker-1", "pi5-worker-2"])
    kube = FakeKube()
    posts = []
    post_codes = []

    def post(url, payload):
        posts.append((url, payload))
        code = post_codes.pop(0) if post_codes else 200
        if isinstance(code, Exception):
            raise code
        return code

    sleeps = []
    clock = Clock()
    r = rmod.Runner(cfg, kube, Ledger(cfg.ledger_path), post=post, now=clock,
                    sleep=sleeps.append, spawn_watchers=False)

    class E:
        pass
    e = E()
    e.runner, e.cfg, e.kube, e.posts, e.post_codes, e.sleeps, e.clock, e.mdir = (
        r, cfg, kube, posts, post_codes, sleeps, clock, mdir)
    return e


def call(e, method, path, body=None, token=TOKEN, raw=None):
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
    return e.runner.handle(method, path, headers, data)


def submit(e, agent="media-investigator", ev=None, callback=CB + "abc"):
    return call(e, "POST", "/runs", {"agent": agent, "event": ev or event(), "callback": callback})


def write_manifest(e, doc, name=None):
    (e.mdir / f"{name or doc['name']}.yaml").write_text(yaml.safe_dump(doc))


# ------------------------------------------------------------------ manifest validation

def valid(doc=None, stem="media-investigator", local=("hot-coder",)):
    return agentspec.validate_manifest(doc or copy.deepcopy(MANIFEST), stem, list(local))


def test_valid_manifest_parses_timeout():
    assert valid() == 900


def test_unknown_top_level_key_rejected():
    d = copy.deepcopy(MANIFEST)
    d["sidecar"] = True
    with pytest.raises(agentspec.ManifestError, match="unknown top-level"):
        valid(d)


def test_name_must_equal_file_name():
    with pytest.raises(agentspec.ManifestError, match="does not equal the file name"):
        valid(stem="other-agent")


def test_bad_name_charset_rejected():
    d = copy.deepcopy(MANIFEST)
    d["name"] = "Media_Investigator"
    with pytest.raises(agentspec.ManifestError, match=r"\[a-z0-9-\]"):
        valid(d, stem="Media_Investigator")


def test_personal_data_class_rejects_non_local_model():
    d = copy.deepcopy(MANIFEST)
    d["data_class"] = "personal"
    with pytest.raises(agentspec.ManifestError, match="claude-haiku"):
        valid(d)
    d["model"]["allow"] = ["hot-coder"]
    assert valid(d) == 900


def test_missing_required_key_rejected():
    d = copy.deepcopy(MANIFEST)
    del d["secret"]
    with pytest.raises(agentspec.ManifestError, match="missing keys"):
        valid(d)


def test_unknown_connector_key_rejected():
    d = copy.deepcopy(MANIFEST)
    d["connectors"]["mcp"][0]["tool"] = ["delete_everything"]
    with pytest.raises(agentspec.ManifestError, match="unknown keys"):
        valid(d)


def test_bad_timeout_rejected():
    d = copy.deepcopy(MANIFEST)
    d["limits"]["timeout"] = "forever"
    with pytest.raises(agentspec.ManifestError, match="timeout"):
        valid(d)


def test_duration_parsing():
    assert agentspec.parse_duration("30s") == 30
    assert agentspec.parse_duration("2h") == 7200
    assert agentspec.parse_duration(45) == 45
    for bad in ("0m", "10d", True, "", "25h"):
        with pytest.raises(ValueError):
            agentspec.parse_duration(bad)


def test_manifest_reread_per_request(env):
    assert submit(env, ev=event("a"))[0] == 202
    d = copy.deepcopy(MANIFEST)
    d["bogus"] = 1
    write_manifest(env, d)
    assert submit(env, ev=event("b"))[0] == 422


# ------------------------------------------------------------------ event validation

@pytest.mark.parametrize("mutate", [
    lambda ev: ev.pop("trust"),
    lambda ev: ev.update(trust="maybe"),
    lambda ev: ev.update(data="not-an-object"),
    lambda ev: ev.update(id=""),
    lambda ev: ev.pop("subject"),
])
def test_invalid_event_rejected(env, mutate):
    ev = event()
    mutate(ev)
    assert submit(env, ev=ev)[0] == 422
    assert env.kube.created == []


def test_oversize_event_rejected(env):
    ev = event(data={"ask": "x" * (64 * 1024)})
    status, body = submit(env, ev=ev)
    assert status == 422 and "exceeds" in body["error"]


# ------------------------------------------------------------------ HTTP statuses

def test_healthz_needs_no_token(env):
    assert call(env, "GET", "/healthz", token=None)[0] == 200


@pytest.mark.parametrize("tok", [None, "wrong", ""])
def test_bad_token_401(env, tok):
    assert call(env, "POST", "/runs", {"agent": "x"}, token=tok)[0] == 401
    assert call(env, "GET", "/runs/abc", token=tok)[0] == 401


def test_token_comparison_is_constant_time(env, monkeypatch):
    seen = []
    real = rmod.hmac.compare_digest
    monkeypatch.setattr(rmod.hmac, "compare_digest", lambda a, b: seen.append(1) or real(a, b))
    call(env, "GET", "/runs/abc")
    assert seen


def test_launch_202(env):
    status, body = submit(env)
    assert status == 202 and body["status"] == "launched"
    assert len(env.kube.created) == 1
    assert env.kube.created[0]["metadata"]["name"] == f"run-{body['run_id']}"


def test_unknown_agent_404(env):
    assert submit(env, agent="no-such-agent")[0] == 404
    assert submit(env, agent="../etc/passwd")[0] == 404


def test_agent_name_cannot_escape_manifest_dir(env):
    # A valid-looking manifest just outside the manifest dir must not be reachable by name.
    d = copy.deepcopy(MANIFEST)
    d["name"] = "escape"
    (env.mdir.parent / "escape.yaml").write_text(yaml.safe_dump(d))
    assert submit(env, agent="../escape")[0] == 404
    assert env.kube.created == []


def test_invalid_manifest_422(env):
    d = copy.deepcopy(MANIFEST)
    d["name"] = "something-else"
    write_manifest(env, d, name="media-investigator")
    status, body = submit(env)
    assert status == 422 and "file name" in body["error"]
    assert env.kube.created == []


def test_callback_prefix_rejected_422(env):
    for cb in ("http://evil.example/webhook/abc", "ftp://n8n", None, 7):
        assert submit(env, callback=cb)[0] == 422
    assert env.kube.created == []


def test_bad_json_body_422(env):
    assert call(env, "POST", "/runs", raw=b"{not json")[0] == 422
    assert call(env, "POST", "/runs", raw=b"[]")[0] == 422


def test_oversize_body_422(env):
    # The HTTP layer passes body=None when Content-Length exceeds the cap.
    status, body = env.runner.handle("POST", "/runs", {"Authorization": f"Bearer {TOKEN}"}, None)
    assert status == 422 and "too large" in body["error"]


def test_idempotent_replay_200(env):
    s1, b1 = submit(env)
    s2, b2 = submit(env)
    assert (s1, s2) == (202, 200)
    assert b2["run_id"] == b1["run_id"] and b2["status"] == "launched"
    assert len(env.kube.created) == 1
    # Same event id, different agent -> a distinct run.
    d = copy.deepcopy(MANIFEST)
    d["name"] = "other-agent"
    write_manifest(env, d)
    assert submit(env, agent="other-agent")[0] == 202


def test_idempotency_survives_restart(env):
    s1, b1 = submit(env)
    r2 = rmod.Runner(env.cfg, env.kube, Ledger(env.cfg.ledger_path), post=lambda u, p: 200,
                     now=env.clock, sleep=lambda s: None, spawn_watchers=False)
    s2, b2 = r2.handle("POST", "/runs", {"Authorization": f"Bearer {TOKEN}"},
                       json.dumps({"agent": "media-investigator", "event": event(),
                                   "callback": CB + "abc"}).encode())
    assert s2 == 200 and b2["run_id"] == b1["run_id"]


def test_daily_cap_429(env):
    for i in range(3):
        assert submit(env, ev=event(f"e{i}"))[0] == 202
    status, body = submit(env, ev=event("e3"))
    assert status == 429 and "daily cap" in body["error"]
    env.clock.t = NOW + timedelta(days=1)  # new UTC day resets the count
    assert submit(env, ev=event("e4"))[0] == 202


def test_paused_503(env):
    env.cfg.paused = True
    assert submit(env)[0] == 503
    assert env.kube.created == []


def test_paused_from_env():
    assert rmod.Config.from_env({"RUNNER_PAUSED": "true"}).paused
    assert not rmod.Config.from_env({"RUNNER_PAUSED": "false"}).paused


def test_quota_exceeded_429_and_retry_allowed(env):
    env.kube.create_error = KubeError(403, 'jobs.batch "run-x" is forbidden: exceeded quota: agents')
    status, _ = submit(env)
    assert status == 429
    env.kube.create_error = None
    assert submit(env)[0] == 202  # a failed launch does not claim the idempotency key


def test_other_kube_error_502(env):
    env.kube.create_error = KubeError(403, "forbidden: RBAC")
    assert submit(env)[0] == 502


def test_get_run_record_and_404(env):
    _, b = submit(env)
    status, rec = call(env, "GET", f"/runs/{b['run_id']}")
    assert status == 200 and rec["agent"] == "media-investigator" and rec["status"] == "launched"
    assert call(env, "GET", "/runs/doesnotexist")[0] == 404
    assert call(env, "GET", "/runs/../../x")[0] == 404


def test_ledger_never_holds_event_data_or_token(env):
    _, b = submit(env)
    env.kube.logs[b["run_id"]] = encode_result(GOOD)
    env.kube.set_condition(b["run_id"], "Complete")
    env.runner.poll_once(b["run_id"])
    text = Path(env.cfg.ledger_path).read_text()
    assert SENTINEL not in text and TOKEN not in text and "# details" not in text


def test_logs_never_hold_event_data(env, capsys):
    submit(env)
    out = capsys.readouterr().out
    assert SENTINEL not in out and TOKEN not in out
    assert all(json.loads(line) for line in out.strip().splitlines())


# ------------------------------------------------------------------ Job rendering (§4)

def rendered(env, hosts=("pi5-worker-1",)):
    return jobspec.render_job("abc123", copy.deepcopy(MANIFEST), event(), 900, "agents",
                              "http://litellm:4000", list(hosts))


def test_job_matches_contract(env):
    job = rendered(env)
    lbl = {"app.kubernetes.io/part-of": "agent-sandbox", "agent": "media-investigator",
           "run-id": "abc123"}
    assert job["apiVersion"] == "batch/v1" and job["kind"] == "Job"
    assert job["metadata"]["name"] == "run-abc123"
    assert job["metadata"]["namespace"] == "agents"
    assert job["metadata"]["labels"] == lbl
    spec = job["spec"]
    assert spec["backoffLimit"] == 0
    assert spec["activeDeadlineSeconds"] == 900
    assert spec["ttlSecondsAfterFinished"] == 3600
    assert spec["template"]["metadata"]["labels"] == lbl
    pod = spec["template"]["spec"]
    assert pod["restartPolicy"] == "Never"
    assert pod["serviceAccountName"] == "agent-run"
    assert pod["automountServiceAccountToken"] is False
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert pod["securityContext"]["runAsUser"] == 10001
    assert pod["securityContext"]["runAsGroup"] == 10001
    assert pod["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}
    assert pod["volumes"] == [{"name": "work", "emptyDir": {"sizeLimit": "1Gi"}}]
    assert pod["affinity"]["nodeAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"] == {
        "nodeSelectorTerms": [{"matchExpressions": [
            {"key": "kubernetes.io/hostname", "operator": "In", "values": ["pi5-worker-1"]}]}]}
    [c] = pod["containers"]
    assert "command" not in c and "args" not in c
    assert c["image"] == MANIFEST["image"]
    sc = c["securityContext"]
    assert sc["allowPrivilegeEscalation"] is False
    assert sc["readOnlyRootFilesystem"] is True
    assert sc["capabilities"] == {"drop": ["ALL"]}
    assert c["volumeMounts"] == [{"name": "work", "mountPath": "/work"}]
    env_ = {x["name"]: x["value"] for x in c["env"]}
    assert set(env_) == {"AGENT_MANIFEST", "AGENT_EVENT", "AGENT_RUN_ID", "LITELLM_BASE_URL",
                         "HOME", "TMPDIR"}
    assert json.loads(env_["AGENT_MANIFEST"]) == MANIFEST
    assert json.loads(env_["AGENT_EVENT"]) == event()
    assert env_["AGENT_RUN_ID"] == "abc123"
    assert env_["LITELLM_BASE_URL"] == "http://litellm:4000"
    assert env_["HOME"] == "/work/home" and env_["TMPDIR"] == "/work/tmp"
    assert c["envFrom"] == [{"secretRef": {"name": "agent-media-investigator"}}]
    assert "valueFrom" not in json.dumps(c["env"])  # the runner never resolves secret values


def test_job_without_node_hostnames_has_no_affinity(env):
    assert "affinity" not in rendered(env, hosts=())["spec"]["template"]["spec"]


def test_job_resources_from_manifest_or_default(env):
    c = rendered(env)["spec"]["template"]["spec"]["containers"][0]
    assert c["resources"] == jobspec.DEFAULT_RESOURCES
    m = copy.deepcopy(MANIFEST)
    m["resources"] = {"requests": {"cpu": "200m"}, "limits": {"memory": "512Mi"}}
    c = jobspec.render_job("r", m, event(), 60, "agents", "u")["spec"]["template"]["spec"]
    assert c["containers"][0]["resources"] == m["resources"]


def test_launched_job_uses_manifest_timeout(env):
    submit(env)
    assert env.kube.created[0]["spec"]["activeDeadlineSeconds"] == 900


# ------------------------------------------------------------------ result parsing (§5)

def parse(log, kinds=("report",)):
    return results.parse_result(log, list(kinds))


def test_result_good():
    status, res, _ = parse("starting\nthinking\n" + encode_result(GOOD) + "\n\n")
    assert status == results.OK and res == GOOD


def test_result_missing_marker():
    assert parse("just some logs\n")[0] == results.NO_RESULT
    assert parse("")[0] == results.NO_RESULT


def test_result_marker_not_last_line_is_no_result():
    assert parse(encode_result(GOOD) + "\ntrailing junk\n")[0] == results.NO_RESULT


def test_result_marker_must_start_the_line():
    assert parse("model said: " + encode_result(GOOD))[0] == results.NO_RESULT


def test_result_malformed_base64():
    status, _, why = parse(results.MARKER + "!!!not base64!!!")
    assert status == results.INVALID and "base64" in why
    # Junk spliced into otherwise-valid base64 must be rejected, not silently skipped.
    enc = encode_result(GOOD)
    cut = len(results.MARKER) + 8
    status, _, why = parse(enc[:cut] + "!*" + enc[cut:])
    assert status == results.INVALID and "base64" in why


def test_result_malformed_json():
    line = results.MARKER + base64.b64encode(b"{nope").decode()
    status, _, why = parse(line)
    assert status == results.INVALID and "JSON" in why


def test_result_unknown_outcome():
    status, _, why = parse(encode_result({**GOOD, "outcome": "rm -rf"}))
    assert status == results.INVALID and "outcome" in why


def test_result_output_kind_not_in_manifest():
    bad = {**GOOD, "outputs": [{"kind": "pull_request", "title": "t", "body": "b"}]}
    status, _, why = parse(encode_result(bad))
    assert status == results.INVALID and "kind" in why


def test_result_oversize_summary_and_body_and_line():
    assert parse(encode_result({**GOOD, "summary": "x" * 2049}))[0] == results.INVALID
    big = {**GOOD, "outputs": [{"kind": "report", "title": "t", "body": "x" * (32 * 1024 + 1)}]}
    assert parse(encode_result(big))[0] == results.INVALID
    huge = results.MARKER + "A" * (results.MAX_MARKER_LINE + 10)
    status, _, why = parse(huge)
    assert status == results.INVALID and "oversize" in why


def test_result_not_an_object_or_unknown_key():
    assert parse(encode_result(["done"]))[0] == results.INVALID
    assert parse(encode_result({**GOOD, "exec": "x"}))[0] == results.INVALID


# ------------------------------------------------------------------ watch -> finalize -> callback

def launch(env):
    _, b = submit(env)
    return b["run_id"]


def test_completed_with_good_result(env):
    rid = launch(env)
    assert env.runner.poll_once(rid) is False  # still running
    env.kube.logs[rid] = "log\n" + encode_result(GOOD)
    env.kube.set_condition(rid, "Complete")
    assert env.runner.poll_once(rid) is True
    [(url, p)] = env.posts
    assert url == CB + "abc"
    assert set(p) == {"run_id", "agent", "event_id", "started", "finished", "exit_reason", "result"}
    assert p["exit_reason"] == "completed" and p["result"] == GOOD
    assert p["event_id"] == "01JD0001" and p["started"] == "2026-11-11T12:00:00Z"
    rec = env.runner.ledger.get(rid)
    assert rec["status"] == "finished" and rec["callback_delivered"] is True
    assert env.runner.poll_once(rid) is True and len(env.posts) == 1  # no double callback


def test_completed_without_marker_is_no_result(env):
    rid = launch(env)
    env.kube.logs[rid] = "crashed quietly\n"
    env.kube.set_condition(rid, "Complete")
    env.runner.poll_once(rid)
    p = env.posts[0][1]
    assert p["exit_reason"] == "no_result" and p["result"]["outcome"] == "failed"


def test_completed_with_invalid_result_forces_failed(env):
    rid = launch(env)
    env.kube.logs[rid] = encode_result({**GOOD, "outcome": "pwned"})
    env.kube.set_condition(rid, "Complete")
    env.runner.poll_once(rid)
    p = env.posts[0][1]
    assert p["exit_reason"] == "invalid_result"
    assert p["result"]["outcome"] == "failed" and p["result"]["outputs"] == []


def test_deadline_exceeded_maps_to_deadline(env):
    rid = launch(env)
    env.kube.set_condition(rid, "Failed", reason="DeadlineExceeded")
    env.runner.poll_once(rid)
    p = env.posts[0][1]
    assert p["exit_reason"] == "deadline" and p["result"]["outcome"] == "failed"


def test_job_failed(env):
    rid = launch(env)
    env.kube.set_condition(rid, "Failed", reason="BackoffLimitExceeded")
    env.runner.poll_once(rid)
    assert env.posts[0][1]["exit_reason"] == "job_failed"


def test_job_vanished_is_job_failed(env):
    rid = launch(env)
    env.kube.jobs.clear()
    assert env.runner.poll_once(rid) is True
    assert env.posts[0][1]["exit_reason"] == "job_failed"


def test_runner_side_deadline_safety_net(env):
    rid = launch(env)
    env.clock.t = NOW + timedelta(seconds=900 + rmod.DEADLINE_GRACE_S - 1)
    assert env.runner.poll_once(rid) is False
    env.clock.t = NOW + timedelta(seconds=900 + rmod.DEADLINE_GRACE_S + 1)
    assert env.runner.poll_once(rid) is True
    assert env.kube.deleted == [f"run-{rid}"]
    assert env.posts[0][1]["exit_reason"] == "deadline"


def test_callback_retries_then_succeeds(env):
    rid = launch(env)
    env.post_codes.extend([500, ConnectionError("down"), 204])
    env.kube.logs[rid] = encode_result(GOOD)
    env.kube.set_condition(rid, "Complete")
    env.runner.poll_once(rid)
    assert len(env.posts) == 3
    assert env.sleeps == [2, 5]
    rec = env.runner.ledger.get(rid)
    assert rec["callback_delivered"] is True and rec["callback_attempts"] == 3


def test_callback_gives_up_after_three_retries(env):
    rid = launch(env)
    env.post_codes.extend([500, 500, 500, 500, 500])
    env.kube.set_condition(rid, "Complete")
    env.runner.poll_once(rid)
    assert len(env.posts) == 4  # 1 attempt + 3 retries
    rec = env.runner.ledger.get(rid)
    assert rec["callback_delivered"] is False and rec["status"] == "finished"


def test_callback_rechecked_against_prefixes_at_delivery(env):
    rid = launch(env)
    env.cfg.callback_prefixes = ["http://somewhere-else/"]
    env.kube.set_condition(rid, "Complete")
    env.runner.poll_once(rid)
    assert env.posts == []


def test_readopt_unfinished_runs_after_restart(env):
    rid = launch(env)
    r2 = rmod.Runner(env.cfg, env.kube, Ledger(env.cfg.ledger_path),
                     post=lambda u, p: env.posts.append((u, p)) or 200,
                     now=env.clock, sleep=lambda s: None, spawn_watchers=False)
    assert r2.readopt() == [rid]
    env.kube.logs[rid] = encode_result(GOOD)
    env.kube.set_condition(rid, "Complete")
    assert r2.poll_once(rid) is True
    assert env.posts[0][1]["exit_reason"] == "completed"
    r3 = rmod.Runner(env.cfg, env.kube, Ledger(env.cfg.ledger_path), spawn_watchers=False)
    assert r3.readopt() == []


def test_ledger_tolerates_torn_line(env):
    rid = launch(env)
    with open(env.cfg.ledger_path, "a") as f:
        f.write('{"op":"launch","run_id":"tor')
    assert Ledger(env.cfg.ledger_path).get(rid)["status"] == "launched"


def test_watch_thread_polls_until_done(env):
    env.runner.spawn_watchers = True
    done = threading.Event()
    env.runner.sleep = lambda s: done.wait(0.01)
    rid = launch(env)
    env.kube.logs[rid] = encode_result(GOOD)
    env.kube.set_condition(rid, "Complete")
    for _ in range(200):
        if env.posts:
            break
        done.wait(0.01)
    assert env.posts and env.posts[0][1]["exit_reason"] == "completed"


# ------------------------------------------------------------------ concurrency gate + FIFO queue

def ids(env):
    return [j["metadata"]["labels"]["run-id"] for j in env.kube.created]


def finish(env, rid, runner=None):
    env.kube.logs[rid] = encode_result(GOOD)
    env.kube.set_condition(rid, "Complete")
    assert (runner or env.runner).poll_once(rid) is True


def burst(env, n):
    out = []
    for i in range(n):
        status, body = submit(env, ev=event(f"burst{i}"))
        assert status == 202, body
        out.append(body)
    return out


@pytest.fixture
def qenv(env):
    """The burst scenario: generous daily cap, default gate (2 concurrent, 8 queued, 45m wait)."""
    d = copy.deepcopy(MANIFEST)
    d["limits"]["runs_per_day"] = 50
    write_manifest(env, d)
    assert (env.cfg.max_concurrent, env.cfg.max_queue, env.cfg.max_queue_wait_s) == (2, 8, 2700)
    return env


def test_gate_defaults_from_env():
    cfg = rmod.Config.from_env({})
    assert (cfg.max_concurrent, cfg.max_queue, cfg.max_queue_wait_s) == (2, 8, 2700)
    cfg = rmod.Config.from_env({"RUNNER_MAX_CONCURRENT": "3", "RUNNER_MAX_QUEUE": "0",
                                "RUNNER_MAX_QUEUE_WAIT": "10m"})
    assert (cfg.max_concurrent, cfg.max_queue, cfg.max_queue_wait_s) == (3, 0, 600)


def test_burst_creates_only_max_concurrent_jobs(qenv):
    bodies = burst(qenv, qenv.cfg.max_concurrent + 3)
    assert len(qenv.kube.created) == 2
    assert [b["status"] for b in bodies] == ["launched"] * 2 + ["queued"] * 3
    assert [b.get("position") for b in bodies[2:]] == [1, 2, 3]
    queued = bodies[2]["run_id"]
    status, rec = call(qenv, "GET", f"/runs/{queued}")
    assert status == 200 and rec["status"] == "queued" and rec["position"] == 1
    assert "started" not in rec and rec["accepted"] == "2026-11-11T12:00:00Z"
    # No Job object at all for a queued run: nothing for the Job controller's deadline to count.
    assert f"run-{queued}" not in qenv.kube.jobs


def test_freed_slot_starts_next_in_fifo_order(qenv):
    bodies = burst(qenv, 5)
    rids = [b["run_id"] for b in bodies]
    finish(qenv, rids[1])                 # second-launched finishes first
    assert ids(qenv) == rids[:3]          # head of the queue (3rd accepted) starts, not a later one
    finish(qenv, rids[0])
    assert ids(qenv) == rids[:4]
    finish(qenv, rids[2])
    assert ids(qenv) == rids
    assert call(qenv, "GET", f"/runs/{rids[4]}")[1]["status"] == "launched"
    # A queued run's Job gets its event from the spool, intact.
    env_ = {x["name"]: x["value"] for x in qenv.kube.created[4]["spec"]["template"]["spec"]
            ["containers"][0]["env"]}
    assert json.loads(env_["AGENT_EVENT"]) == event("burst4")
    assert list((Path(qenv.cfg.ledger_path).parent / "queue").iterdir()) == []


def test_new_submit_waits_behind_queue_even_if_slot_free(qenv):
    bodies = burst(qenv, 3)
    qenv.kube.jobs[f"run-{bodies[0]['run_id']}"]["status"] = {"conditions": [
        {"type": "Complete", "status": "True", "lastTransitionTime": "2026-11-11T12:05:00Z"}]}
    # Slot is free in Kubernetes but the runner has not polled yet; the queue head goes first.
    finish(qenv, bodies[0]["run_id"])
    s, b = submit(qenv, ev=event("late"))
    assert s == 202 and b["status"] == "queued"
    assert ids(qenv) == [bodies[0]["run_id"], bodies[1]["run_id"], bodies[2]["run_id"]]


def test_queue_full_429_distinct_from_daily_cap(qenv):
    burst(qenv, 2 + 8)
    status, body = submit(qenv, ev=event("overflow"))
    assert status == 429 and body["error"] == "queue_full"
    assert len(qenv.kube.created) == 2
    # Refused: not recorded, does not claim the idempotency key, does not count toward the cap.
    assert qenv.runner.ledger.find("media-investigator", "overflow") is None
    assert qenv.runner.ledger.count_on_day("media-investigator", "2026-11-11") == 10
    # The daily-cap body is unchanged.
    d = copy.deepcopy(MANIFEST)
    d["limits"]["runs_per_day"] = 10
    write_manifest(qenv, d)
    status, body = submit(qenv, ev=event("capped"))
    assert status == 429 and body["error"] == "daily cap of 10 runs reached"


def test_max_queue_zero_refuses_beyond_concurrency(qenv):
    qenv.cfg.max_queue = 0
    burst(qenv, 2)
    status, body = submit(qenv, ev=event("x"))
    assert (status, body["error"]) == (429, "queue_full")


def test_queue_expired_sends_callback(qenv):
    bodies = burst(qenv, 4)
    qenv.clock.t = NOW + timedelta(minutes=45)
    assert qenv.runner.expire_queued() == []          # not yet: strictly more than the wait
    qenv.clock.t = NOW + timedelta(minutes=45, seconds=1)
    expired = qenv.runner.expire_queued()
    assert expired == [bodies[2]["run_id"], bodies[3]["run_id"]]
    assert len(qenv.posts) == 2
    url, p = qenv.posts[0]
    assert url == CB + "abc"
    assert set(p) == {"run_id", "agent", "event_id", "started", "finished", "exit_reason", "result"}
    assert p["exit_reason"] == "queue_expired" and p["started"] is None
    assert p["event_id"] == "burst2" and p["result"]["outcome"] == "failed"
    assert p["result"]["outputs"] == [] and "45 minutes" in p["result"]["summary"]
    rec = qenv.runner.ledger.get(bodies[2]["run_id"])
    assert rec["status"] == "finished" and rec["exit_reason"] == "queue_expired"
    assert rec["callback_delivered"] is True
    # Expired runs never start, even when slots free up afterwards.
    finish(qenv, bodies[0]["run_id"])
    assert len(qenv.kube.created) == 2
    # The dedupe key is still held: a replay returns the finished record, not a new run.
    s, b = submit(qenv, ev=event("burst2"))
    assert s == 200 and b["exit_reason"] == "queue_expired"


def test_timeout_counts_from_job_creation_not_accept(qenv):
    bodies = burst(qenv, 3)
    queued = bodies[2]["run_id"]
    qenv.clock.t = NOW + timedelta(minutes=30)       # waited 30 minutes for a slot
    finish(qenv, bodies[0]["run_id"])
    assert ids(qenv)[-1] == queued
    rec = qenv.runner.ledger.get(queued)
    assert rec["started"] == "2026-11-11T12:30:00Z" and rec["accepted"] == "2026-11-11T12:00:00Z"
    assert qenv.kube.created[-1]["spec"]["activeDeadlineSeconds"] == 900
    # Accept + timeout + grace has passed, but Job creation + timeout + grace has not: still running.
    qenv.clock.t = NOW + timedelta(minutes=30, seconds=900 + rmod.DEADLINE_GRACE_S - 1)
    assert qenv.runner.poll_once(queued) is False
    assert qenv.kube.deleted == []
    qenv.clock.t = NOW + timedelta(minutes=30, seconds=900 + rmod.DEADLINE_GRACE_S + 1)
    assert qenv.runner.poll_once(queued) is True
    assert qenv.kube.deleted == [f"run-{queued}"]
    assert qenv.posts[-1][1]["started"] == "2026-11-11T12:30:00Z"


def test_daily_cap_counts_queued_runs_at_accept(env):
    # MANIFEST cap is 3: 2 launch, 1 queues, the 4th is the daily cap even though only 2 ran.
    burst(env, 3)
    status, body = submit(env, ev=event("over"))
    assert status == 429 and "daily cap" in body["error"]


def test_queued_run_replay_returns_queued_record(qenv):
    bodies = burst(qenv, 3)
    s, b = submit(qenv, ev=event("burst2"))
    assert s == 200 and b["run_id"] == bodies[2]["run_id"] and b["status"] == "queued"
    assert len(qenv.runner.queue) == 1


def test_quota_refusal_on_dequeue_keeps_run_at_head(qenv):
    bodies = burst(qenv, 4)
    qenv.kube.create_error = KubeError(403, "exceeded quota: agents")
    finish(qenv, bodies[0]["run_id"])
    assert len(qenv.kube.created) == 2
    assert list(qenv.runner.queue) == [bodies[2]["run_id"], bodies[3]["run_id"]]
    rec = qenv.runner.ledger.get(bodies[2]["run_id"])
    assert rec["status"] == "queued" and rec.get("started") is None
    qenv.kube.create_error = None
    qenv.runner.tick()
    assert ids(qenv)[-1] == bodies[2]["run_id"]


def test_other_kube_error_on_dequeue_fails_that_run_with_callback(qenv):
    bodies = burst(qenv, 3)
    qenv.kube.create_error = KubeError(403, "forbidden: RBAC")
    finish(qenv, bodies[0]["run_id"])
    p = qenv.posts[-1][1]
    assert p["run_id"] == bodies[2]["run_id"] and p["exit_reason"] == "job_failed"
    assert "kubernetes API error 403" in p["result"]["summary"]
    assert list(qenv.runner.queue) == []


def test_manifest_removed_while_queued_fails_run(qenv):
    bodies = burst(qenv, 3)
    (qenv.mdir / "media-investigator.yaml").unlink()
    finish(qenv, bodies[0]["run_id"])
    p = qenv.posts[-1][1]
    assert p["run_id"] == bodies[2]["run_id"] and p["exit_reason"] == "job_failed"


def test_paused_runner_does_not_start_queued_runs(qenv):
    bodies = burst(qenv, 3)
    qenv.cfg.paused = True
    finish(qenv, bodies[0]["run_id"])
    assert len(qenv.kube.created) == 2
    qenv.clock.t = NOW + timedelta(minutes=46)
    assert qenv.runner.expire_queued() == [bodies[2]["run_id"]]


def test_queue_survives_restart_in_fifo_order(qenv):
    bodies = burst(qenv, 5)
    rids = [b["run_id"] for b in bodies]
    # The ledger stays identifiers-only even with runs queued; the event is in the spool.
    assert SENTINEL not in Path(qenv.cfg.ledger_path).read_text()
    r2 = rmod.Runner(qenv.cfg, qenv.kube, Ledger(qenv.cfg.ledger_path),
                     post=lambda u, p: qenv.posts.append((u, p)) or 200,
                     now=qenv.clock, sleep=lambda s: None, spawn_watchers=False)
    assert r2.readopt() == rids[:2]
    assert list(r2.queue) == rids[2:]
    assert call(qenv, "GET", f"/runs/{rids[3]}")[1]["status"] == "queued"
    finish(qenv, rids[0], runner=r2)
    assert ids(qenv) == rids[:3]
    env_ = {x["name"]: x["value"] for x in qenv.kube.created[2]["spec"]["template"]["spec"]
            ["containers"][0]["env"]}
    assert json.loads(env_["AGENT_EVENT"]) == event("burst2")
    # Queue wait is measured from the ORIGINAL accept, across the restart.
    qenv.clock.t = NOW + timedelta(minutes=46)
    assert r2.expire_queued() == rids[3:]


def test_restart_prunes_orphan_spool_and_fails_lost_event(qenv):
    bodies = burst(qenv, 3)
    spool = Path(qenv.cfg.ledger_path).parent / "queue"
    (spool / "orphan123.json").write_text("{}")
    (spool / f"{bodies[2]['run_id']}.json").unlink()   # event lost (e.g. volume restored)
    r2 = rmod.Runner(qenv.cfg, qenv.kube, Ledger(qenv.cfg.ledger_path),
                     post=lambda u, p: qenv.posts.append((u, p)) or 200,
                     now=qenv.clock, sleep=lambda s: None, spawn_watchers=False)
    r2.readopt()
    assert not (spool / "orphan123.json").exists()
    finish(qenv, bodies[0]["run_id"], runner=r2)
    p = qenv.posts[-1][1]
    assert p["run_id"] == bodies[2]["run_id"] and p["exit_reason"] == "job_failed"
    assert "lost" in p["result"]["summary"]


def test_concurrent_submits_never_exceed_the_gate(qenv):
    """Many POSTs from parallel threads (as ThreadingHTTPServer delivers them) must still create exactly max_concurrent Jobs."""
    real_create = qenv.kube.create_job
    gate = threading.Event()

    def slow_create(job):            # widen the race window inside the critical section
        gate.wait(0.002)
        return real_create(job)
    qenv.kube.create_job = slow_create
    results_ = []
    lock = threading.Lock()

    def one(i):
        r = submit(qenv, ev=event(f"t{i}"))
        with lock:
            results_.append(r)
    threads = [threading.Thread(target=one, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    statuses = sorted((s, b.get("status") or b.get("error")) for s, b in results_)
    assert len(qenv.kube.created) == 2
    assert statuses.count((202, "launched")) == 2
    assert statuses.count((202, "queued")) == 8
    assert statuses.count((429, "queue_full")) == 2
    assert len(qenv.runner.queue) == 8


def test_dispatcher_thread_expires_queued_runs(qenv):
    done = threading.Event()
    qenv.runner.sleep = lambda s: done.wait(0.01)
    bodies = burst(qenv, 3)
    stop = qenv.runner.start_dispatcher()
    try:
        qenv.clock.t = NOW + timedelta(minutes=46)
        for _ in range(300):
            if qenv.posts:
                break
            done.wait(0.01)
    finally:
        stop.set()
    assert [(p["run_id"], p["exit_reason"]) for _, p in qenv.posts] == [
        (bodies[2]["run_id"], "queue_expired")]


# ------------------------------------------------------------------ process / server

def test_refuses_to_start_without_token(monkeypatch):
    monkeypatch.setenv("RUNNER_API_TOKEN", "  ")
    with pytest.raises(SystemExit, match="RUNNER_API_TOKEN"):
        rmod.main()


def test_http_server_loopback(env):
    srv = rmod.make_server(env.runner, host="127.0.0.1", port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/healthz", timeout=5) as r:
            assert r.status == 200
        req = urllib.request.Request(base + "/runs", data=b"{}", method="POST")
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req, timeout=5)
        assert ei.value.code == 401
        body = json.dumps({"agent": "media-investigator", "event": event(),
                           "callback": CB + "x"}).encode()
        req = urllib.request.Request(base + "/runs", data=body, method="POST",
                                     headers={"Authorization": f"Bearer {TOKEN}"})
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 202
        req = urllib.request.Request(base + "/runs", data=b"x" * (rmod.MAX_REQUEST_BYTES + 1),
                                     method="POST", headers={"Authorization": f"Bearer {TOKEN}"})
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req, timeout=5)
        assert ei.value.code == 422
    finally:
        srv.shutdown()


def test_callback_prefix_without_trailing_slash_is_dropped():
    import runner as RN
    cfg = RN.Config.from_env({"RUNNER_API_TOKEN": "t",
                              "RUNNER_CALLBACK_PREFIXES": "http://n8n.n8n.svc,http://ok.svc:5678/"})
    assert cfg.callback_prefixes == ["http://ok.svc:5678/"]


# ------------------------------------------------------------------ slice 3: plan results, checkout, models per event

SEC = {
    "kind": "Agent", "name": "sec-researcher", "purpose": "review access control",
    "image": "ghcr.io/mtgibbs/agent-runtime:0.2.0", "data_class": "system",
    "model": {"allow": ["claude-haiku"], "by_event_type": {"security.sweep": ["claude-sonnet", "claude-haiku"]}},
    "secret": "agent-sec-researcher",
    "checkout": {"source": "flux-system/flux-system", "include": ["clusters/", "docs/secrets-map.md"]},
    "outputs": ["plan"], "prompt": "Review.\n",
    "limits": {"timeout": "20m", "runs_per_day": 6, "max_steps": 40},
}
SHA = "0123456789abcdef0123456789abcdef01234567"


def plan_item(**over):
    p = {"kind": "plan", "title": "agents namespace allows X", "severity": "medium",
         "fingerprint": {"rule": "networkpolicy-broad-egress", "resource": "agents/NetworkPolicy/agent-base-egress"},
         "plan": {"found": "f", "evidence": "clusters/pi-k3s/agents/networkpolicies.yaml:40", "likely_cause": "c",
                  "proposed_change": "No change needed.", "risk": "r", "verify": "v", "rollback": "rb"}}
    p.update(over)
    return p


def plan_res(*items):
    return {"outcome": "needs_human", "summary": "1 finding", "outputs": list(items)}


def test_plan_result_valid():
    st, res, why = parse(encode_result(plan_res(plan_item(), plan_item(severity="info"))), kinds=("plan",))
    assert st == results.OK and why is None and len(res["outputs"]) == 2


@pytest.mark.parametrize("mut, frag", [
    (lambda p: p.pop("severity"), "exactly"),
    (lambda p: p.update(severity="urgent"), "severity"),
    (lambda p: p.update(body="x"), "exactly"),
    (lambda p: p.update(issue_url="https://github.com/x/y/issues/1"), "exactly"),
    (lambda p: p["fingerprint"].update(rule="Bad Rule!"), "rule"),
    (lambda p: p["fingerprint"].update(rule="ab"), "rule"),
    (lambda p: p["fingerprint"].update(resource="networkpolicy foo"), "resource"),
    (lambda p: p["fingerprint"].update(resource="agents/networkpolicy/foo"), "resource"),
    (lambda p: p["fingerprint"].update(extra="x"), "fingerprint"),
    (lambda p: p["plan"].pop("rollback"), "plan.plan"),
    (lambda p: p["plan"].update(notes="x"), "plan.plan"),
    (lambda p: p["plan"].update(risk="   "), "plan.risk"),
    (lambda p: p["plan"].update(risk=7), "plan.risk"),
    (lambda p: p["plan"].update(risk="x" * (4 * 1024 + 1)), "plan.risk exceeds"),
    (lambda p: p["plan"].update(evidence="é" * (4 * 1024 + 1)), "plan.evidence exceeds"),
    (lambda p: p.update(title="x" * 201), "title"),
    (lambda p: p.update(title="two\nlines"), "one line"),
    (lambda p: p.update(title=""), "title"),
])
def test_plan_result_invalid_is_rejected(mut, frag):
    p = plan_item()
    mut(p)
    st, res, why = parse(encode_result(plan_res(p)), kinds=("plan",))
    assert st == results.INVALID and res is None and frag in why, why


def test_plan_sizes_at_the_limit_pass():
    p = plan_item(title="t" * 200)
    p["plan"]["evidence"] = "e" * (8 * 1024)
    p["plan"]["risk"] = "r" * (4 * 1024)
    assert parse(encode_result(plan_res(p)), kinds=("plan",))[0] == results.OK


def test_plan_kind_must_be_allowed_and_report_shape_still_enforced():
    assert parse(encode_result(plan_res(plan_item())), kinds=("report",))[0] == results.INVALID
    bad = {"outcome": "done", "summary": "s", "outputs": [{"kind": "report", "title": "t"}]}
    assert parse(encode_result(bad), kinds=("report", "plan"))[0] == results.INVALID


def test_invalid_plan_result_forces_failed_callback(env):
    write_manifest(env, SEC)
    _, b = submit(env, agent="sec-researcher", ev=event(type="security.manual"))
    rid = b["run_id"]
    bad = plan_item()
    bad["fingerprint"]["resource"] = "../../etc"
    env.kube.logs[rid] = encode_result(plan_res(bad))
    env.kube.set_condition(rid, "Complete")
    assert env.runner.poll_once(rid) is True
    [(_, p)] = env.posts
    assert p["exit_reason"] == "invalid_result" and p["result"]["outcome"] == "failed"
    assert p["result"]["outputs"] == []


def test_sec_manifest_valid():
    assert valid(copy.deepcopy(SEC), stem="sec-researcher") == 1200


@pytest.mark.parametrize("mut, frag", [
    (lambda m: m.update(checkout="flux-system/flux-system"), "checkout must be a mapping"),
    (lambda m: m["checkout"].update(url="http://evil/x.tar.gz"), "checkout must be a mapping"),
    (lambda m: m["checkout"].pop("source"), "checkout must be a mapping"),
    (lambda m: m["checkout"].update(source="http://evil"), "checkout.source"),
    (lambda m: m["checkout"].update(source="flux-system"), "checkout.source"),
    (lambda m: m["checkout"].update(include=["../secrets"]), "checkout.include"),
    (lambda m: m["checkout"].update(include=["/etc"]), "checkout.include"),
    (lambda m: m["checkout"].update(include=["clusters/../.."]), "checkout.include"),
    (lambda m: m["checkout"].update(include=[]), "checkout.include"),
    (lambda m: m["model"].update(by_event_type={"security.sweep": []}), "by_event_type[security.sweep]"),
    (lambda m: m["model"].update(by_event_type={"Bad Type": ["x"]}), "not an event type"),
    (lambda m: m["model"].update(by_event_type=["x"]), "by_event_type must be"),
    (lambda m: m["model"].update(fallback=["x"]), "model must be a mapping"),
])
def test_sec_manifest_invalid(mut, frag):
    m = copy.deepcopy(SEC)
    mut(m)
    with pytest.raises(agentspec.ManifestError, match=frag.replace("[", r"\[").replace("]", r"\]")):
        valid(m, stem="sec-researcher")


def test_personal_rule_covers_by_event_type_models():
    m = copy.deepcopy(MANIFEST)
    m["data_class"] = "personal"
    m["model"] = {"allow": ["hot-coder"], "by_event_type": {"x.y": ["claude-sonnet"]}}
    with pytest.raises(agentspec.ManifestError, match="claude-sonnet"):
        valid(m)


def _sec_job(ev, base=jobspec.DEFAULT_CHECKOUT_BASE_URL, current=CUR_SHA):
    return jobspec.render_job("abc123", copy.deepcopy(SEC), ev, 1200, "agents", "http://litellm:4000",
                              ["pi5-worker-1"], checkout_base_url=base, checkout_sha=current)


def _ienv(job):
    return {x["name"]: x["value"] for x in job["spec"]["template"]["spec"]["initContainers"][0]["env"]}


def test_model_selected_per_event_type():
    def models(ev_type):
        c = _sec_job(event(type=ev_type))["spec"]["template"]["spec"]["containers"][0]
        man = json.loads({x["name"]: x["value"] for x in c["env"]}["AGENT_MANIFEST"])
        assert set(man["model"]) == {"allow"}   # the runtime only ever sees the resolved list
        return man["model"]["allow"]
    assert models("security.sweep") == ["claude-sonnet", "claude-haiku"]
    assert models("security.flux_revision") == ["claude-haiku"]
    assert models("security.manual") == ["claude-haiku"]


def test_checkout_renders_init_container_and_readonly_mount():
    pod = _sec_job(event(type="security.flux_revision", data={"revision": SHA}))["spec"]["template"]["spec"]
    [init] = pod["initContainers"]
    [agent] = pod["containers"]
    assert init["name"] == "checkout" and init["image"] == SEC["image"]
    assert init["command"] == ["python", "/app/checkout.py"]
    assert "envFrom" not in init                      # the checkout step holds no credential
    ienv = {x["name"]: x["value"] for x in init["env"]}
    base = "http://source-controller.flux-system.svc.cluster.local./gitrepository/flux-system/flux-system/"
    assert ienv["CHECKOUT_URL"] == base + SHA + ".tar.gz"
    assert ienv["CHECKOUT_FALLBACK_URL"] == base + CUR_SHA + ".tar.gz"   # the current artifact, never latest.tar.gz
    assert ienv["CHECKOUT_DEST"] == "/repo/tree" and ienv["CHECKOUT_INFO"] == "/repo/checkout.json"
    assert json.loads(ienv["CHECKOUT_INCLUDE"]) == ["clusters/", "docs/secrets-map.md"]
    isc = init["securityContext"]
    assert isc["readOnlyRootFilesystem"] is True and isc["allowPrivilegeEscalation"] is False
    assert isc["runAsNonRoot"] is True and isc["capabilities"] == {"drop": ["ALL"]}
    assert {"name": "repo", "mountPath": "/repo"} in init["volumeMounts"]
    # the agent container sees the checkout read-only, and only the init container writes it
    assert {"name": "repo", "mountPath": "/repo", "readOnly": True} in agent["volumeMounts"]
    aenv = {x["name"]: x["value"] for x in agent["env"]}
    assert aenv["AGENT_REPO_DIR"] == "/repo/tree" and aenv["AGENT_CHECKOUT_INFO"] == "/repo/checkout.json"
    assert {"name": "repo", "emptyDir": {"sizeLimit": "256Mi"}} in pod["volumes"]


@pytest.mark.parametrize("rev", [None, "", "main", SHA.upper(), SHA[:39], SHA + "0",
                                 "../../../helmrepository/x/y/latest", "abc?x=1"])
def test_checkout_url_only_takes_a_well_formed_sha_from_the_event(rev):
    data = {} if rev is None else {"revision": rev}
    ienv = _ienv(_sec_job(event(type="security.manual", data=data)))
    assert ienv["CHECKOUT_URL"] == ("http://source-controller.flux-system.svc.cluster.local./gitrepository/"
                                    f"flux-system/flux-system/{CUR_SHA}.tar.gz")
    assert ienv["CHECKOUT_FALLBACK_URL"] == ""


def test_checkout_never_asks_for_latest_tar_gz():
    """source-controller ≥ v1.0 serves no latest.tar.gz (2026-11-13: a manual run 404'd on it)."""
    for ev in (event(type="security.manual"), event(type="security.flux_revision", data={"revision": SHA})):
        for cur in (CUR_SHA, None):
            if cur is None and "revision" not in ev["data"]:
                continue
            assert "latest" not in json.dumps(_ienv(_sec_job(ev, current=cur)))


def test_checkout_event_sha_equal_to_current_has_no_fallback():
    ienv = _ienv(_sec_job(event(type="security.flux_revision", data={"revision": CUR_SHA})))
    assert ienv["CHECKOUT_URL"].endswith(f"/{CUR_SHA}.tar.gz") and ienv["CHECKOUT_FALLBACK_URL"] == ""


def test_checkout_event_sha_without_current_has_no_fallback():
    ienv = _ienv(_sec_job(event(type="security.flux_revision", data={"revision": SHA}), current=None))
    assert ienv["CHECKOUT_URL"].endswith(f"/{SHA}.tar.gz") and ienv["CHECKOUT_FALLBACK_URL"] == ""


@pytest.mark.parametrize("cur", [None, "", "main", CUR_SHA.upper(), "../x"])
def test_render_refuses_a_checkout_with_nothing_to_fetch(cur):
    with pytest.raises(ValueError, match="no checkout artifact"):
        _sec_job(event(type="security.manual"), current=cur)


@pytest.mark.parametrize("obj,want", [
    ({"status": {"artifact": {"revision": f"main@sha1:{CUR_SHA}"}}}, CUR_SHA),
    ({"status": {"artifact": {"revision": f"main/{CUR_SHA}"}}}, CUR_SHA),        # pre-v1 form
    ({"status": {"artifact": {"revision": CUR_SHA}}}, CUR_SHA),
    ({"status": {"artifact": {"revision": f"main@sha1:{CUR_SHA}x"}}}, None),
    ({"status": {"artifact": {"revision": f"main@sha1:{CUR_SHA.upper()}"}}}, None),
    ({"status": {"artifact": {"revision": "main@sha256:" + "a" * 64}}}, None),
    ({"status": {"artifact": {}}}, None), ({"status": {}}, None), ({}, None), (None, None), ([], None),
    ({"status": {"artifact": "x"}}, None),
])
def test_artifact_sha_parses_gitrepository_status(obj, want):
    assert jobspec.artifact_sha(obj) == want


def test_checkout_host_comes_from_runner_config_not_manifest():
    ienv = _ienv(_sec_job(event(), base="http://sc.test:9090/"))
    assert ienv["CHECKOUT_URL"] == f"http://sc.test:9090/gitrepository/flux-system/flux-system/{CUR_SHA}.tar.gz"
    assert rmod.Config.from_env({"RUNNER_CHECKOUT_BASE_URL": "http://sc.test:9090"}).checkout_base_url == \
        "http://sc.test:9090"
    assert rmod.Config.from_env({}).checkout_base_url == jobspec.DEFAULT_CHECKOUT_BASE_URL


def test_manifest_without_checkout_renders_no_init_container(env):
    pod = rendered(env)["spec"]["template"]["spec"]
    assert "initContainers" not in pod
    assert all(v["name"] != "repo" for v in pod["volumes"])


def test_runner_launch_passes_checkout_base(env):
    env.cfg.checkout_base_url = "http://sc.test:9090"
    write_manifest(env, SEC)
    submit(env, agent="sec-researcher", ev=event(type="security.sweep"))
    init = env.kube.created[0]["spec"]["template"]["spec"]["initContainers"][0]
    assert {x["name"]: x["value"] for x in init["env"]}["CHECKOUT_URL"].startswith("http://sc.test:9090/")


def test_runner_resolves_current_artifact_for_a_run_without_revision(env, capsys):
    write_manifest(env, SEC)
    s, b = submit(env, agent="sec-researcher", ev=event(type="security.manual", data={"ask": "x"}))
    assert s == 202 and b["status"] == "launched"
    assert env.kube.gitrepo_calls == [("flux-system", "flux-system")]   # the manifest's checkout.source
    ienv = _ienv(env.kube.created[0])
    assert ienv["CHECKOUT_URL"].endswith(f"/gitrepository/flux-system/flux-system/{CUR_SHA}.tar.gz")
    assert ienv["CHECKOUT_FALLBACK_URL"] == ""
    assert '"event":"checkout_resolved"' in capsys.readouterr().out


def test_runner_flux_run_falls_back_to_current_artifact(env):
    write_manifest(env, SEC)
    submit(env, agent="sec-researcher", ev=event(type="security.flux_revision", data={"revision": SHA}))
    ienv = _ienv(env.kube.created[0])
    assert ienv["CHECKOUT_URL"].endswith(f"/{SHA}.tar.gz")
    assert ienv["CHECKOUT_FALLBACK_URL"].endswith(f"/{CUR_SHA}.tar.gz")


@pytest.mark.parametrize("err", [KubeError(403, "forbidden"), KubeError(404, "not found"), OSError("down")])
def test_runner_flux_run_still_launches_when_gitrepository_unreadable(env, err):
    env.kube.gitrepo_error = err
    write_manifest(env, SEC)
    s, _ = submit(env, agent="sec-researcher", ev=event(type="security.flux_revision", data={"revision": SHA}))
    assert s == 202
    ienv = _ienv(env.kube.created[0])
    assert ienv["CHECKOUT_URL"].endswith(f"/{SHA}.tar.gz") and ienv["CHECKOUT_FALLBACK_URL"] == ""


@pytest.mark.parametrize("err,detail", [(KubeError(403, "forbidden"), "kubernetes API error 403"),
                                        (OSError("down"), "kubernetes API unreachable (OSError)"),
                                        (None, "GitRepository has no stored artifact")])
def test_runner_refuses_a_run_with_nothing_to_check_out(env, err, detail):
    env.kube.gitrepo_error = err
    if err is None:
        env.kube.gitrepo_revision = None
    write_manifest(env, SEC)
    s, b = submit(env, agent="sec-researcher", ev=event(type="security.manual"))
    assert s == 502 and env.kube.created == []
    assert b["error"].startswith("no repository revision to check out") and detail in b["error"]
    assert "flux-system/flux-system" in b["error"]
    # refused before the ledger: no run record, the daily cap is not spent, a retry is not a replay
    assert Ledger(env.cfg.ledger_path).count_on_day("sec-researcher", "2026-11-11") == 0
    env.kube.gitrepo_error, env.kube.gitrepo_revision = None, "main@sha1:" + CUR_SHA
    assert submit(env, agent="sec-researcher", ev=event(type="security.manual"))[0] == 202


def test_manifest_without_checkout_never_reads_gitrepository(env):
    submit(env)
    assert env.kube.created and env.kube.gitrepo_calls == []


def _sec_queue(env):
    d = copy.deepcopy(SEC)
    d["limits"]["runs_per_day"] = 50
    write_manifest(env, d)
    out = [submit(env, agent="sec-researcher", ev=event(f"q{i}", type="security.manual"))[1] for i in range(3)]
    assert [b["status"] for b in out] == ["launched", "launched", "queued"]
    return out


def test_queued_run_resolves_checkout_when_it_starts(env):
    bodies = _sec_queue(env)
    later = "fedcba9876543210fedcba9876543210fedcba98"
    env.kube.gitrepo_revision = "main@sha1:" + later         # Flux moved on while it waited
    finish(env, bodies[0]["run_id"])
    assert ids(env) == [bodies[0]["run_id"], bodies[1]["run_id"], bodies[2]["run_id"]]
    assert _ienv(env.kube.created[2])["CHECKOUT_URL"].endswith(f"/{later}.tar.gz")


def test_queued_run_stays_queued_on_api_transport_failure(env):
    bodies = _sec_queue(env)
    env.kube.gitrepo_error = OSError("blip")
    finish(env, bodies[0]["run_id"])
    assert len(env.kube.created) == 2 and list(env.runner.queue) == [bodies[2]["run_id"]]
    env.kube.gitrepo_error = None
    env.runner.pump()
    assert len(env.kube.created) == 3 and list(env.runner.queue) == []


def test_queued_run_fails_when_gitrepository_is_forbidden(env):
    bodies = _sec_queue(env)
    env.kube.gitrepo_error = KubeError(403, "forbidden")
    finish(env, bodies[0]["run_id"])
    p = env.posts[-1][1]
    assert p["run_id"] == bodies[2]["run_id"] and p["exit_reason"] == "job_failed"
    assert "no repository revision to check out" in p["result"]["summary"]
    assert len(env.kube.created) == 2 and list(env.runner.queue) == []


def test_repo_manifest_sec_researcher_is_valid():
    """The manifest in Git loads under the runner's own validator (as the runner would load it)."""
    mdir = Path(__file__).resolve().parents[2] / "clusters/pi-k3s/agents/manifests"
    doc, timeout = agentspec.load_manifest(str(mdir), "sec-researcher", ["hot-coder"])
    assert doc["outputs"] == ["plan"] and doc["data_class"] == "system"
    assert doc["checkout"]["source"] == "flux-system/flux-system"
    allm = {m for lst in [doc["model"]["allow"], *doc["model"].get("by_event_type", {}).values()] for m in lst}
    assert not any("opus" in m for m in allm)
    assert "connectors" in doc and doc["connectors"]["mcp"][0]["key_env"] == "MCP_HOMELAB_READONLY_KEY"


def test_kubeapi_get_gitrepository_path(tmp_path, monkeypatch):
    import kubeapi
    (tmp_path / "token").write_text("t")
    monkeypatch.setattr(kubeapi.ssl, "create_default_context", lambda cafile=None: None)
    kc = kubeapi.KubeClient("agents", sa_dir=str(tmp_path))
    seen = []
    monkeypatch.setattr(kc, "_request", lambda method, path, **kw: seen.append((method, path)) or {})
    kc.get_gitrepository("flux-system", "flux-system")
    kc.get_gitrepository("a/b", "../c")
    assert seen == [("GET", "/apis/source.toolkit.fluxcd.io/v1/namespaces/flux-system/gitrepositories/flux-system"),
                    ("GET", "/apis/source.toolkit.fluxcd.io/v1/namespaces/a%2Fb/gitrepositories/..%2Fc")]
