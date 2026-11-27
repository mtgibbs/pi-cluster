#!/usr/bin/env python3
"""submit.py — start one factory run from an idea. The one implementation behind factory/submit.sh
(the laptop) and factory/intake/ (the in-cluster intake service).

  FABRO_URL=... FABRO_DEV_TOKEN=... factory/submit.py [--target <name>] [--profile <name>] [--panel "<k=v ...>"]
      [--spec <name>] [--issue <n>] [--gate-mode human|auto] [--origin <who>] [--request <key>]
      [--create-only] [--dry-run] "<idea text>"

--target picks factory/targets/<name>.toml: the repo the run acts on, the workflow directory, and the
target's earn-out stage. A target without a file is refused. Default: pi-cluster-mcp.
--profile picks a row of factory/models.toml (which model writes, builds and judges, and how many
votes each judge panel casts); the default is all-local.
--panel overrides panel settings for this run, e.g. "spec_votes=3 spec_threshold=2 spec_rounds=2"
(keys: <kind>_votes <kind>_threshold <kind>_rounds for kind in spec_intent spec conf_intent conf).
--gate-mode human (default) stops the run at approve_spec and the two escalation gates for a person.
auto (the intake's mode) never stops for a person: the spec is approved only when BOTH spec panels
passed, otherwise the run ends with no PR ("spec held"); a run that would escalate holds instead.
The only human gate left is the PR. See docs/design/factory-intake.md.
--origin is who asked ("human", or "agent:<name>"); --request the intake's dedupe key. Both are
stamped into the version and written into the verdict record, for the earn-out ledger.
The idea text is stamped verbatim into [run.inputs] (idea_b64) and covered by code_sha, so the
intent panels judge against exactly what was submitted.
--dry-run resolves and validates everything, prints the [run.inputs] it would stamp (code is shown
by size only), and exits without contacting the server.

Uploads factory/<workflow>/{workflow.fabro,workflow.toml,prompts/*} as a workflow version, with
factory/steps.py and factory/classify.sh packed into [run.inputs] (so the code that judges the run is
content-addressed inside the version and never comes from the target repo), creates a run against
<repo>@main and starts it. auto_approve is always sent as false: it would answer every gate without
the panels' consent. Reads FABRO_URL and FABRO_DEV_TOKEN from the environment; prints no secret.
"""
import argparse, base64, hashlib, importlib.util, json, os, pathlib, re, sys, tomllib, urllib.error, urllib.request

sys.dont_write_bytecode = True   # importing steps.py below must not drop a __pycache__ in factory/
HERE = pathlib.Path(__file__).resolve().parent
ROLES = ["writer", "spec_intent", "spec_judge", "builder", "conf_intent", "conf_judge"]
GATE_MODES = ("human", "auto")
ORIGIN_RE = re.compile(r"^(human|agent:[a-z0-9][a-z0-9-]{0,62})$")
REQUEST_RE = re.compile(r"^[A-Za-z0-9:_.-]{0,128}$")
TARGET_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


class SubmitError(Exception):
    """A refusal: bad target, profile, panel or argument. Nothing was uploaded."""


def load_target(name):
    if not TARGET_RE.fullmatch(name or ""):
        raise SubmitError(f"bad target name {name!r}")
    p = HERE / "targets" / f"{name}.toml"
    if not p.is_file():
        have = ", ".join(sorted(x.stem for x in (HERE / "targets").glob("*.toml"))) or "none"
        raise SubmitError(f"no target {name!r} (factory/targets/{name}.toml); allowed: {have}")
    t = tomllib.loads(p.read_text())
    for k in ("repo", "workflow", "stage"):
        if k not in t:
            raise SubmitError(f"target {name}: missing key {k!r}")
    if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", t["repo"]):
        raise SubmitError(f"target {name}: bad repo {t['repo']!r}")
    if t["repo"] == "mtgibbs/pi-cluster":
        raise SubmitError("pi-cluster is never a factory target while the factory lives in it (rule 1)")
    if not (isinstance(t["stage"], int) and 0 <= t["stage"] <= 3):
        raise SubmitError(f"target {name}: stage must be 0..3")
    t["name"] = name
    return t


def _steps_module():
    spec_ = importlib.util.spec_from_file_location("factory_steps", HERE / "steps.py")
    mod = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(mod)
    return mod


def default_spec(idea):
    """Kebab slug of the idea's first five words (what submit.sh always did)."""
    s = re.sub(r"[^a-z0-9]+", "-", idea.lower()).strip("-")
    return "-".join(s.split("-")[:5]).strip("-")


def prepare(idea, target="pi-cluster-mcp", profile="all-local", panel="", gate_mode="human",
            origin="human", request="", spec="", issue=""):
    """Everything short of contacting Fabro: the files of the workflow version (with [run.inputs]
    appended) and what the run will be created with. Pure; raises SubmitError on any refusal."""
    if not idea.strip():
        raise SubmitError("empty idea")
    if gate_mode not in GATE_MODES:
        raise SubmitError(f"gate mode must be one of {GATE_MODES}, not {gate_mode!r}")
    if not ORIGIN_RE.fullmatch(origin):
        raise SubmitError(f"bad origin {origin!r} (human | agent:<name>)")
    if not REQUEST_RE.fullmatch(request):
        raise SubmitError(f"bad request key {request!r}")
    tgt = load_target(target)
    if origin not in tgt.get("origins", ["human"]) and not (
            origin.startswith("agent:") and "agent:*" in tgt.get("origins", [])):
        raise SubmitError(f"target {target}: origin {origin!r} is not allowed (origins = {tgt.get('origins')})")
    spec = spec or default_spec(idea)
    wf = pathlib.Path(os.environ.get("FACTORY_WORKFLOW_DIR") or HERE / tgt["workflow"])  # override: test/loop-control.py only
    steps = (HERE / "steps.py").read_bytes(); classify = (HERE / "classify.sh").read_bytes()
    # The idea, byte for byte as submitted. setup writes it to /tmp/factory/idea.md and every
    # deterministic stage re-checks it with the code: code_sha = sha(steps) + sha(classify) + sha(idea).
    idea_b = idea.encode()
    code_sha = hashlib.sha256(steps).hexdigest() + hashlib.sha256(classify).hexdigest() + hashlib.sha256(idea_b).hexdigest()
    files = {}
    for p in sorted(wf.rglob("*")):
        if p.is_file() and not p.name.startswith("."):
            files[str(p.relative_to(wf))] = p.read_text()
    cfg = tomllib.loads((HERE / "models.toml").read_text())
    prof = cfg["profiles"].get(profile)
    if not prof:
        raise SubmitError(f"no profile {profile!r} in models.toml; have: {', '.join(cfg['profiles'])}")
    for r in ROLES:
        if prof.get(r) not in cfg["models"]:
            raise SubmitError(f"profile {profile}: role {r} names model {prof.get(r)!r}, which models.toml does not define")
    profile_line = profile + " " + " ".join(f"{r}={prof[r]}" for r in ROLES)
    # Judge panels: profile votes/thresholds + [loop] round caps, then --panel overrides. Parsed
    # and validated by steps.py's own parse_panel, the same code setup runs in the sandbox.
    steps_mod = _steps_module()
    loop = cfg.get("loop") or {}
    base = {k: v for k, v in {**{k: prof.get(k) for k in steps_mod.PANEL_KEYS}, **loop}.items()
            if k in steps_mod.PANEL_KEYS and v is not None}
    try:
        pan = steps_mod.parse_panel(" ".join(f"{k}={v}" for k, v in base.items()) + " " + panel)
    except ValueError as e:
        raise SubmitError(f"profile {profile}: bad judge-panel settings: {e}")
    graph = (wf / "workflow.fabro").read_text()

    def max_visits(node):
        m = re.search(rf"^\s*{node} \[[^\n]*max_visits=(\d+)", graph, re.M)
        return int(m.group(1)) if m else 0
    # Every panel's judge, capture and vote nodes: votes x (rounds + 4).
    judge_node = {"spec_intent": "spec_intent", "spec": "spec_judge", "conf_intent": "conf_intent", "conf": "conf_judge"}
    for kind, jnode in judge_node.items():
        need = pan[f"{kind}_votes"] * (pan[f"{kind}_rounds"] + 4)
        for node in (jnode, f"{kind}_capture", f"{kind}_vote"):
            cap = max_visits(node)
            if need > cap:
                raise SubmitError(f"{kind} panel: {pan[f'{kind}_votes']} votes x ({pan[f'{kind}_rounds']} rounds + 4) = {need} "
                                  f"visits > {node} max_visits={cap} in workflow.fabro; raise max_visits or lower the panel")
    # The authors: each panel's revise rounds come back to the same writer/builder, so their caps add.
    author_need = {
        "ideate": 1 + pan["spec_intent_rounds"] + pan["spec_rounds"] + steps_mod.MAX_SPEC_CHECK_RETRIES + 4,
        "implement": 1 + pan["conf_intent_rounds"] + pan["conf_rounds"] + steps_mod.MAX_GATE_FIX_ROUNDS
                     + steps_mod.MAX_CI_FIX_ROUNDS + 4}
    for node, follow in (("ideate", "spec_check"), ("implement", "gates")):
        for n in (node, follow):
            if author_need[node] > max_visits(n):
                raise SubmitError(f"{node}: its revise rounds (+4 human headroom) need {author_need[node]} visits > {n} "
                                  f"max_visits={max_visits(n)} in workflow.fabro; raise max_visits or lower the round caps")
    toml = files["workflow.toml"]
    if any(l.strip().startswith("[run.inputs") for l in toml.splitlines()):
        raise SubmitError("workflow.toml must not define [run.inputs]; submit.py owns it")
    inputs = ([("steps_b64", base64.b64encode(steps).decode()),
               ("classify_b64", base64.b64encode(classify).decode()),
               ("idea_b64", base64.b64encode(idea_b).decode()),
               ("code_sha", code_sha), ("profile", profile_line)]
              + [("m_" + r, prof[r]) for r in ROLES]
              + [(k, str(pan[k])) for k in steps_mod.PANEL_KEYS]
              + [("gate_mode", gate_mode), ("origin", origin), ("request", request),
                 ("target_stage", str(tgt["stage"]))])
    files["workflow.toml"] = toml.rstrip() + "\n\n# --- appended by factory/submit.py ---\n[run.inputs]\n" + "".join(
        f'{k} = "{v}"\n' for k, v in inputs)
    title = f"factory: {spec}" + (f" (#{issue})" if issue else "")
    run_body = {
        "target": {"kind": "git", "repo": tgt["repo"], "branch": "main"},
        "args": {"model": "hot-coder", "provider": "litellm", "auto_approve": False,
                 "inputs": {"spec": spec, "issue": issue}},
        "environment_id": "gated-docker", "title": title[:100], "goal": idea}
    return {"files": files, "run": run_body, "inputs": inputs, "profile_line": profile_line,
            "panel_line": steps_mod.panel_line(pan), "target": tgt, "spec": spec}


def describe(prep):
    """The dry-run printout: what would be stamped, code shown by size only."""
    out = [f"target {prep['target']['name']} repo={prep['target']['repo']} stage={prep['target']['stage']}",
           f"profile {prep['profile_line']}", "judge panels: " + prep["panel_line"],
           f"run title {prep['run']['title']!r} auto_approve={prep['run']['args']['auto_approve']}"]
    out += [f"  input {k} = " + (f"<{len(v)} chars>" if k.endswith("_b64") else f'"{v}"') for k, v in prep["inputs"]]
    return "\n".join(out)


def _call(url, tok, method, path, body=None):
    req = urllib.request.Request(url.rstrip("/") + "/api/v1" + path, method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            t = r.read().decode(); return json.loads(t) if t.strip() else {}
    except urllib.error.HTTPError as e:
        raise SubmitError(f"{method} {path} -> HTTP {e.code}: {e.read().decode()[:600]}")


def submit(prep, url=None, tok=None, create_only=False):
    """Upload the version, create the run and (unless create_only) start it. Returns
    {"workflow_version_id", "run_id", "url"}."""
    url = (url or os.environ.get("FABRO_URL", "")).rstrip("/")
    tok = tok or os.environ.get("FABRO_DEV_TOKEN", "")
    if not url or not tok:
        raise SubmitError("set FABRO_URL and FABRO_DEV_TOKEN")
    if prep["run"]["args"].get("auto_approve") is not False:
        raise SubmitError("refusing to create a run with auto_approve set")
    wv = _call(url, tok, "POST", "/workflow-versions",
               {"entrypoint": "workflow.fabro", "files": prep["files"], "workflow_dependencies": {}})
    run = _call(url, tok, "POST", "/runs", {"workflow_version_id": wv["workflow_version_id"], **prep["run"]})
    if not create_only:
        _call(url, tok, "POST", f"/runs/{run['id']}/start", {})
    return {"workflow_version_id": wv["workflow_version_id"], "run_id": run["id"], "url": f"{url}/runs/{run['id']}"}


def main(argv=None):
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--target", default=os.environ.get("FACTORY_TARGET", "pi-cluster-mcp"))
    ap.add_argument("--profile", default=os.environ.get("FACTORY_PROFILE", "all-local"))
    ap.add_argument("--panel", default="")
    ap.add_argument("--spec", default="")
    ap.add_argument("--issue", default="")
    ap.add_argument("--gate-mode", default="human")
    ap.add_argument("--origin", default="human")
    ap.add_argument("--request", default="")
    ap.add_argument("--create-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-h", "--help", action="store_true")
    ap.add_argument("idea", nargs="?", default="")
    a = ap.parse_args(argv)
    if a.help:
        print(__doc__)
        return 0
    if not a.idea:
        print('usage: submit.sh [--target name] [--profile name] [--spec name] [--issue n] "<idea text>"', file=sys.stderr)
        return 2
    try:
        prep = prepare(a.idea, target=a.target, profile=a.profile, panel=a.panel, gate_mode=a.gate_mode,
                       origin=a.origin, request=a.request, spec=a.spec, issue=a.issue)
        print(describe(prep) if a.dry_run else f"profile {prep['profile_line']}")
        if a.dry_run:
            print("dry run: nothing uploaded, no run created")
            return 0
        r = submit(prep, create_only=a.create_only)
    except SubmitError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"workflow_version {r['workflow_version_id']}")
    print(f"run {r['run_id']} ({'created' if a.create_only else 'started'})")
    print(r["url"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
