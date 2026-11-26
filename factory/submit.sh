#!/usr/bin/env bash
# submit.sh — start one factory run from an idea, and print the run URL.
#
#   FABRO_URL=... FABRO_DEV_TOKEN=... factory/submit.sh [--profile <name>] [--panel "<k=v ...>"] [--spec <name>] [--issue <n>] [--create-only] [--dry-run] "<idea text>"
#
# --profile picks a row of factory/models.toml (which model writes, builds and judges, and
# how many votes each judge panel casts); the default is all-local.
# --panel overrides panel settings for this run, e.g. "spec_votes=3 spec_threshold=2 spec_rounds=2"
# (keys: <kind>_votes <kind>_threshold <kind>_rounds for kind in spec_intent spec conf_intent conf).
# The idea text is stamped verbatim into [run.inputs] (idea_b64) and covered by code_sha, so
# the intent panels judge against exactly what was submitted.
# --dry-run resolves and validates the profile and panel, prints the [run.inputs] it would
# stamp (code is shown by size only), and exits without contacting the server.
#
# Uploads factory/mcp/{workflow.fabro,workflow.toml,prompts/*} as a workflow version, with
# factory/steps.py and factory/classify.sh packed into [run.inputs] (so the code that judges
# the run is content-addressed inside the version and never comes from the target repo),
# creates a run against mtgibbs/pi-cluster-mcp@main and starts it.
#
# The run blocks at the `approve_spec` human gate. auto_approve is always sent as false.
# Reads FABRO_URL and FABRO_DEV_TOKEN from the environment; prints no secret.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO="mtgibbs/pi-cluster-mcp"
spec="" issue="" create_only=0 dry_run=0 panel="" profile="${FACTORY_PROFILE:-all-local}"
while [ $# -gt 0 ]; do
  case "$1" in
    --profile) profile="$2"; shift 2 ;;
    --spec) spec="$2"; shift 2 ;;
    --issue) issue="$2"; shift 2 ;;
    --panel) panel="$2"; shift 2 ;;
    --create-only) create_only=1; shift ;;
    --dry-run) dry_run=1; shift ;;
    -h|--help) sed -n '2,21p' "$0"; exit 0 ;;
    --) shift; break ;;
    -*) echo "unknown flag $1" >&2; exit 2 ;;
    *) break ;;
  esac
done
idea="${1:-}"
[ -n "$idea" ] || { echo "usage: submit.sh [--spec name] [--issue n] \"<idea text>\"" >&2; exit 2; }
[ "$dry_run" = 1 ] || : "${FABRO_URL:?set FABRO_URL}" "${FABRO_DEV_TOKEN:?set FABRO_DEV_TOKEN}"
if [ -z "$spec" ]; then   # kebab slug of the idea's first words
  spec=$(printf %s "$idea" | tr 'A-Z' 'a-z' | tr -cs 'a-z0-9' '-' | sed 's/^-//' | cut -d- -f1-5 | sed 's/-$//')
fi

IDEA="$idea" PROFILE="$profile" PANEL="$panel" SPEC="$spec" ISSUE="$issue" HERE="$HERE" REPO="$REPO" CREATE_ONLY="$create_only" DRY_RUN="$dry_run" python3 - <<'PY'
import base64, hashlib, importlib.util, json, os, pathlib, re, sys, tomllib, urllib.error, urllib.request
sys.dont_write_bytecode = True   # importing steps.py below must not drop a __pycache__ in factory/
here = pathlib.Path(os.environ["HERE"])
wf = pathlib.Path(os.environ.get("FACTORY_WORKFLOW_DIR") or here / "mcp")   # override only for test/loop-control.py
dry = os.environ["DRY_RUN"] == "1"
url = os.environ.get("FABRO_URL", "").rstrip("/"); api = url + "/api/v1"
tok = os.environ.get("FABRO_DEV_TOKEN", "")

def call(method, path, body=None):
    req = urllib.request.Request(api + path, method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            t = r.read().decode(); return json.loads(t) if t.strip() else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} -> HTTP {e.code}: {e.read().decode()[:600]}")

steps = (here / "steps.py").read_bytes(); classify = (here / "classify.sh").read_bytes()
# The idea, byte for byte as submitted. setup writes it to /tmp/factory/idea.md and every
# deterministic stage re-checks it with the code: code_sha = sha(steps) + sha(classify) + sha(idea).
idea = os.environ["IDEA"].encode()
code_sha = hashlib.sha256(steps).hexdigest() + hashlib.sha256(classify).hexdigest() + hashlib.sha256(idea).hexdigest()
files = {}
for p in sorted(wf.rglob("*")):
    if p.is_file() and not p.name.startswith("."):
        files[str(p.relative_to(wf))] = p.read_text()
cfg = tomllib.loads((here / "models.toml").read_text())
pname = os.environ["PROFILE"]
prof = cfg["profiles"].get(pname) or sys.exit(f"no profile {pname!r} in models.toml; have: {', '.join(cfg['profiles'])}")
ROLES = ["writer", "spec_intent", "spec_judge", "builder", "conf_intent", "conf_judge"]
for r in ROLES:
    if prof.get(r) not in cfg["models"]:
        sys.exit(f"profile {pname}: role {r} names model {prof.get(r)!r}, which models.toml does not define")
profile_line = pname + " " + " ".join(f"{r}={prof[r]}" for r in ROLES)
# Judge panels: profile votes/thresholds + [loop] round caps, then --panel overrides. Parsed
# and validated by steps.py's own parse_panel, the same code setup runs in the sandbox.
spec_ = importlib.util.spec_from_file_location("factory_steps", here / "steps.py")
steps_mod = importlib.util.module_from_spec(spec_); spec_.loader.exec_module(steps_mod)
loop = cfg.get("loop") or {}
base = {k: v for k, v in {**{k: prof.get(k) for k in steps_mod.PANEL_KEYS}, **loop}.items()
        if k in steps_mod.PANEL_KEYS and v is not None}
try:
    panel = steps_mod.parse_panel(" ".join(f"{k}={v}" for k, v in base.items()) + " " + os.environ["PANEL"])
except ValueError as e:
    sys.exit(f"profile {pname}: bad judge-panel settings: {e}")
graph = (wf / "workflow.fabro").read_text()
def max_visits(node):
    m = re.search(rf"^\s*{node} \[[^\n]*max_visits=(\d+)", graph, re.M)
    return int(m.group(1)) if m else 0
# Every panel's judge, capture and vote nodes: votes x (rounds + 4).
JUDGE_NODE = {"spec_intent": "spec_intent", "spec": "spec_judge", "conf_intent": "conf_intent", "conf": "conf_judge"}
for kind, jnode in JUDGE_NODE.items():
    need = panel[f"{kind}_votes"] * (panel[f"{kind}_rounds"] + 4)
    for node in (jnode, f"{kind}_capture", f"{kind}_vote"):
        cap = max_visits(node)
        if need > cap:
            sys.exit(f"{kind} panel: {panel[f'{kind}_votes']} votes x ({panel[f'{kind}_rounds']} rounds + 4) = {need} "
                     f"visits > {node} max_visits={cap} in workflow.fabro; raise max_visits or lower the panel")
# The authors: each panel's revise rounds come back to the same writer/builder, so their caps add.
author_need = {
    "ideate": 1 + panel["spec_intent_rounds"] + panel["spec_rounds"] + steps_mod.MAX_SPEC_CHECK_RETRIES + 4,
    "implement": 1 + panel["conf_intent_rounds"] + panel["conf_rounds"] + steps_mod.MAX_GATE_FIX_ROUNDS
                 + steps_mod.MAX_CI_FIX_ROUNDS + 4}
for node, follow in (("ideate", "spec_check"), ("implement", "gates")):
    for n in (node, follow):
        if author_need[node] > max_visits(n):
            sys.exit(f"{node}: its revise rounds (+4 human headroom) need {author_need[node]} visits > {n} "
                     f"max_visits={max_visits(n)} in workflow.fabro; raise max_visits or lower the round caps")
toml = files["workflow.toml"]
if any(l.strip().startswith("[run.inputs") for l in toml.splitlines()):
    sys.exit("workflow.toml must not define [run.inputs]; submit.sh owns it")
files["workflow.toml"] = toml.rstrip() + "\n\n# --- appended by factory/submit.sh ---\n[run.inputs]\n" + "".join(
    f'{k} = "{v}"\n' for k, v in [("steps_b64", base64.b64encode(steps).decode()),
                                   ("classify_b64", base64.b64encode(classify).decode()),
                                   ("idea_b64", base64.b64encode(idea).decode()),
                                   ("code_sha", code_sha), ("profile", profile_line)]
                                  + [("m_" + r, prof[r]) for r in ROLES]
                                  + [(k, str(panel[k])) for k in steps_mod.PANEL_KEYS])
if dry:
    print(f"profile {profile_line}")
    print("judge panels: " + steps_mod.panel_line(panel))
    for l in files["workflow.toml"].split("[run.inputs]\n", 1)[1].splitlines():
        k, _, v = l.partition(" = ")
        print(f"  input {k} = " + (f"<{len(v) - 2} chars>" if k.endswith("_b64") else v))
    print("dry run: nothing uploaded, no run created")
    sys.exit(0)
wv = call("POST", "/workflow-versions", {"entrypoint": "workflow.fabro", "files": files, "workflow_dependencies": {}})
spec, issue = os.environ["SPEC"], os.environ["ISSUE"]
title = f"factory: {spec}" + (f" (#{issue})" if issue else "")
run = call("POST", "/runs", {
    "workflow_version_id": wv["workflow_version_id"],
    "target": {"kind": "git", "repo": os.environ["REPO"], "branch": "main"},
    "args": {"model": "hot-coder", "provider": "litellm", "auto_approve": False,
             "inputs": {"spec": spec, "issue": issue}},
    "environment_id": "gated-docker", "title": title[:100], "goal": os.environ["IDEA"]})
rid = run["id"]
if os.environ["CREATE_ONLY"] != "1":
    call("POST", f"/runs/{rid}/start", {})
print(f"profile {profile_line}")
print(f"workflow_version {wv['workflow_version_id']}")
print(f"run {rid} ({'created' if os.environ['CREATE_ONLY'] == '1' else 'started'})")
print(f"{url}/runs/{rid}")
PY
