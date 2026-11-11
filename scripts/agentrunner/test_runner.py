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


class FakeKube:
    def __init__(self):
        self.jobs = {}
        self.created = []
        self.deleted = []
        self.create_error = None
        self.logs = {}       # run_id -> log text
        self.no_pods = set()
        self.get_calls = 0

    def create_job(self, job):
        if self.create_error:
            raise self.create_error
        self.created.append(job)
        self.jobs[job["metadata"]["name"]] = copy.deepcopy(job)
        return job

    def get_job(self, name):
        self.get_calls += 1
        return self.jobs.get(name)

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
