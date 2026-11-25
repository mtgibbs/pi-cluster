#!/usr/bin/env bash
# submit.sh — start one factory run from an idea, and print the run URL.
#
#   FABRO_URL=... FABRO_DEV_TOKEN=... factory/submit.sh [--profile <name>] [--spec <name>] [--issue <n>] [--create-only] "<idea text>"
#
# --profile picks a row of factory/models.toml (which model writes, builds and judges);
# the default is all-local.
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
spec="" issue="" create_only=0 profile="${FACTORY_PROFILE:-all-local}"
while [ $# -gt 0 ]; do
  case "$1" in
    --profile) profile="$2"; shift 2 ;;
    --spec) spec="$2"; shift 2 ;;
    --issue) issue="$2"; shift 2 ;;
    --create-only) create_only=1; shift ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    --) shift; break ;;
    -*) echo "unknown flag $1" >&2; exit 2 ;;
    *) break ;;
  esac
done
idea="${1:-}"
[ -n "$idea" ] || { echo "usage: submit.sh [--spec name] [--issue n] \"<idea text>\"" >&2; exit 2; }
: "${FABRO_URL:?set FABRO_URL}" "${FABRO_DEV_TOKEN:?set FABRO_DEV_TOKEN}"
if [ -z "$spec" ]; then   # kebab slug of the idea's first words
  spec=$(printf %s "$idea" | tr 'A-Z' 'a-z' | tr -cs 'a-z0-9' '-' | sed 's/^-//' | cut -d- -f1-5 | sed 's/-$//')
fi

IDEA="$idea" PROFILE="$profile" SPEC="$spec" ISSUE="$issue" HERE="$HERE" REPO="$REPO" CREATE_ONLY="$create_only" python3 - <<'PY'
import base64, hashlib, json, os, pathlib, sys, tomllib, urllib.error, urllib.request
here = pathlib.Path(os.environ["HERE"])
wf = pathlib.Path(os.environ.get("FACTORY_WORKFLOW_DIR") or here / "mcp")   # override only for test/loop-control.py
url = os.environ["FABRO_URL"].rstrip("/"); api = url + "/api/v1"
tok = os.environ["FABRO_DEV_TOKEN"]

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
code_sha = hashlib.sha256(steps).hexdigest() + hashlib.sha256(classify).hexdigest()
files = {}
for p in sorted(wf.rglob("*")):
    if p.is_file() and not p.name.startswith("."):
        files[str(p.relative_to(wf))] = p.read_text()
cfg = tomllib.loads((here / "models.toml").read_text())
pname = os.environ["PROFILE"]
prof = cfg["profiles"].get(pname) or sys.exit(f"no profile {pname!r} in models.toml; have: {', '.join(cfg['profiles'])}")
ROLES = ["writer", "spec_judge", "builder", "conf_judge"]
for r in ROLES:
    if prof.get(r) not in cfg["models"]:
        sys.exit(f"profile {pname}: role {r} names model {prof.get(r)!r}, which models.toml does not define")
profile_line = pname + " " + " ".join(f"{r}={prof[r]}" for r in ROLES)
toml = files["workflow.toml"]
if any(l.strip().startswith("[run.inputs") for l in toml.splitlines()):
    sys.exit("workflow.toml must not define [run.inputs]; submit.sh owns it")
files["workflow.toml"] = toml.rstrip() + "\n\n# --- appended by factory/submit.sh ---\n[run.inputs]\n" + "".join(
    f'{k} = "{v}"\n' for k, v in [("steps_b64", base64.b64encode(steps).decode()),
                                   ("classify_b64", base64.b64encode(classify).decode()),
                                   ("code_sha", code_sha), ("profile", profile_line)]
                                  + [("m_" + r, prof[r]) for r in ROLES])
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
