#!/usr/bin/env python3
"""steps.py — the factory's deterministic stages, run inside the Fabro sandbox.

Every stage that decides anything without a model lives here (plus classify.sh). The
workflow never runs a copy from the target repo: submit.sh base64-packs this file and
classify.sh into the workflow version's [run.inputs], and each command node re-writes them
to /tmp/factory before use, so nothing an agent stage edits can change what judges it.

State. Fabro gives a command node exactly one context key on stdin, so the run's evidence
is one JSON object in context key `fx`, threaded through every deterministic node
(stdin_source="fx" in, `{"context_updates": {"fx": ...}}` out). Flat `fx_*` keys are
emitted alongside it for edge conditions. Judge verdicts come from Fabro's recorded
`response.<judge>` (stdin_source) — never from a file the run can edit.

Every stage prints human-readable output, then exactly one routing JSON object as its LAST
line, and exits 0. Exit 0 matters: Fabro only applies a command's context_updates on exit 0.
A crash (non-zero exit, or no JSON) leaves the stage `failed`; every edge out of a stage
here is conditioned on `outcome=succeeded`, so a crash always falls through to the hold
path, never forward.

Usage (inside the sandbox, cwd = repo root):
  steps.py setup <spec-name> [issue]      (no stdin)
  steps.py spec_check                     stdin: fx
  steps.py capture spec|conf              stdin: response.<judge>
  steps.py raised spec|conf               stdin: fx   (counts the raise, writes feedback, picks revise|hold)
  steps.py note spec|build                stdin: human.gate.text (a human's typed note)
  steps.py merge <key> <value>            stdin: fx
  steps.py lock                           stdin: fx
  steps.py gates                          stdin: fx
  steps.py classify                       stdin: fx
  steps.py open_pr                        stdin: fx
  steps.py wait_checks                    stdin: fx
  steps.py verdict                        stdin: fx
"""
import hashlib, json, os, re, subprocess, sys, time, urllib.error, urllib.parse, urllib.request

W = "/tmp/factory"
REQUIRED_CHECKS = ["build", "lint", "test", "typecheck", "review-hub"]
REVIEW_HUB_APP = "empty-gibbs"           # GitHub App slug that posts review-hub's checks
REPORT_MARKER = "<!-- review-hub:report -->"
VERDICT_MARKER = "<!-- factory:verdict -->"
MAX_GATE_FIX_ROUNDS = 3                  # design table row 5
MAX_CI_FIX_ROUNDS = 3                    # design table row 10
MAX_SPEC_CHECK_RETRIES = 2               # failed deterministic spec checks sent back to ideate
MAX_REVISE_ROUNDS = 2                    # judge raises sent back to the writer/builder before a human sees it
FEEDBACK = {"spec": "spec-feedback.md", "conf": "build-feedback.md"}
CHECK_WAIT_SECONDS = int(os.environ.get("FACTORY_CHECK_WAIT", "2700"))  # 45 min
UNANIMOUS = 5                            # rule 5: would-merge needs 5/5 clear per validator


# ---------------------------------------------------------------- plumbing
def log(*a):
    print(*a, flush=True)


def emit(fx=None, **flat):
    upd = dict(flat)
    if fx is not None:
        upd["fx"] = fx
    print(json.dumps({"context_updates": upd}, sort_keys=True))
    sys.exit(0)


def read_stdin_json():
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    try:
        v = json.loads(raw)
    except json.JSONDecodeError:
        log(f"stdin is not JSON ({raw[:80]!r}); refusing to guess state")
        sys.exit(3)
    if isinstance(v, str):          # a context value stored as a JSON string
        v = json.loads(v)
    return v


def sh(cmd, check=False, timeout=900, env=None, input=None):
    p = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True,
                       timeout=timeout, env=env, input=input)
    if check and p.returncode != 0:
        raise RuntimeError(f"{cmd!r} exited {p.returncode}: {p.stderr[-2000:]}")
    return p


def git(*args, **kw):
    return sh(["git", *args], **kw).stdout.strip()


def tail(text, n=60):
    lines = (text or "").rstrip().splitlines()
    return "\n".join(lines[-n:])


def base_rev():
    """The commit the run branched from. Deterministic and recomputable by any stage."""
    if sh(["git", "rev-parse", "--verify", "-q", "origin/main"]).returncode != 0:
        raise RuntimeError("origin/main is missing in the sandbox clone")
    return git("merge-base", "HEAD", "origin/main", check=True)


def _scratch_index():
    """A throwaway index holding the whole working tree (tracked + untracked, minus ignored),
    so diffs and tree hashes see uncommitted agent work without touching the real index."""
    os.makedirs(W, exist_ok=True)
    idx = f"{W}/index"
    if os.path.exists(idx):
        os.remove(idx)
    env = dict(os.environ, GIT_INDEX_FILE=idx)
    sh(["git", "read-tree", "HEAD"], env=env, check=True)
    sh(["git", "add", "-A", "."], env=env, check=True)
    return env


def worktree_tree():
    env = _scratch_index()
    return sh(["git", "write-tree"], env=env, check=True).stdout.strip()


def worktree_diff(base, context=5):
    env = _scratch_index()
    return sh(["git", "diff", "--cached", "--no-renames", "--no-ext-diff", f"-U{context}", base],
              env=env, check=True).stdout


def changed_paths(base):
    env = _scratch_index()
    out = sh(["git", "diff", "--cached", "--no-renames", "--name-only", base], env=env, check=True).stdout
    return [p for p in out.splitlines() if p]


def short_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def spec_dir(fx):
    return f"specs/{fx['spec']}"


def spec_files(fx):
    d = spec_dir(fx)
    return [f"{d}/spec.md", f"{d}/tasks.txt", f"{d}/verify.sh"]


def spec_id(fx):
    h = hashlib.sha256()
    for f in spec_files(fx):
        h.update(f.encode() + b"\0")
        with open(f, "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()[:12]


def spec_name_from_tree():
    """capture runs on response stdin, so it cannot read fx; recover the spec name from the
    one specs/<name>/ the run added (setup refuses a name that already exists on base)."""
    names = {p.split("/")[1] for p in changed_paths(base_rev())
             if p.startswith("specs/") and p.count("/") >= 2 and not p.startswith("specs/validators/")}
    if len(names) != 1:
        raise RuntimeError(f"expected exactly one new specs/<name>/, found {sorted(names)}")
    return names.pop()


# ---------------------------------------------------------------- GitHub
def gh(method, path, body=None, raw=False, ok=(200, 201, 204)):
    url = path if path.startswith("http") else "https://api.github.com" + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "fabro-factory",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            text = r.read().decode(errors="replace")
            if r.status not in ok:
                raise RuntimeError(f"{method} {path}: HTTP {r.status}")
            return text if raw else (json.loads(text) if text.strip() else None)
    except urllib.error.HTTPError as e:
        if e.code in ok:
            return None
        raise RuntimeError(f"{method} {path}: HTTP {e.code} {e.read().decode(errors='replace')[:300]}")


def repo_slug():
    url = git("remote", "get-url", "origin")
    m = re.search(r"github\.com[:/]+([^/]+/[^/.]+?)(?:\.git)?/?$", url)
    if not m:
        raise RuntimeError(f"cannot parse GitHub slug from origin {url!r}")
    return m.group(1)


# ---------------------------------------------------------------- stages
def st_setup(spec, issue=""):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,48}", spec or ""):
        raise RuntimeError(f"spec name {spec!r} must be kebab-case, 2-49 chars")
    run_id = ""
    m = re.search(r"^Fabro-Run:\s*(\S+)", git("log", "-1", "--format=%B"), re.M)
    if m:
        run_id = m.group(1)
    base = base_rev()
    if sh(["git", "cat-file", "-e", f"{base}:specs/{spec}"]).returncode == 0:
        raise RuntimeError(f"specs/{spec} already exists on main — pick another name")
    log(f"repo={repo_slug()} base={base} run={run_id} spec={spec}")
    p = sh("npm ci --no-audit --no-fund", timeout=1200)
    log(tail(p.stdout + p.stderr, 15))
    if p.returncode != 0:
        raise RuntimeError("npm ci failed on the base tree — the factory cannot gate this repo")
    suffix = (run_id[-6:] or short_hash(spec + base)[:6]).lower()
    fx = {"v": 1, "spec": spec, "issue": issue, "run_id": run_id, "repo": repo_slug(),
          "base": base, "branch": f"factory/{spec}-{suffix}", "gate_fails": 0, "gate_runs": 0,
          "ci_red_rounds": 0, "notes": [],
          # "<profile name> writer=<model> spec_judge=<model> builder=<model> conf_judge=<model>"
          "profile": os.environ.get("FACTORY_PROFILE", "")}
    log(f"model profile: {fx['profile'] or '(none recorded)'}")
    emit(fx, fx_spec=spec)


def st_spec_check(fx):
    """Deterministic checks on the drafted spec, before any model judges it."""
    problems = []
    for f in spec_files(fx):
        if not os.path.isfile(f):
            problems.append(f"missing {f}")
    stray = [p for p in changed_paths(fx["base"]) if not p.startswith(spec_dir(fx) + "/")]
    if stray:
        problems.append("ideate may only write under " + spec_dir(fx) + "/ but changed: " + ", ".join(stray[:10]))
    red = None
    if not problems:
        # Red-before-green: on the unimplemented tree the gate MUST fail. A verify.sh that
        # passes before the change exists cannot tell a right implementation from none.
        p = sh(["bash", f"{spec_dir(fx)}/verify.sh"], env=dict(os.environ, STRICT="1"), timeout=600)
        red = p.returncode != 0
        log("verify.sh on the unimplemented tree (STRICT=1) exited", p.returncode)
        log(tail(p.stdout + p.stderr, 25))
        if not red:
            problems.append("verify.sh PASSES before anything is implemented — it cannot fail, so it proves nothing. "
                            "Add assertions on what the change creates (new tests, new exports, new behaviour).")
    result = "pass" if not problems else "fail"
    fx["spec_check"] = {"result": result, "problems": problems, "red_before_green": red}
    if problems:
        fx["spec_check_fails"] = fx.get("spec_check_fails", 0) + 1
        log(f"SPEC CHECK FAILED (failure {fx['spec_check_fails']}; {MAX_SPEC_CHECK_RETRIES} retries allowed):\n- " + "\n- ".join(problems))
    else:
        sid = spec_id(fx)
        fx["spec_id_checked"] = sid
        os.makedirs(W, exist_ok=True)
        packet = f"SPEC-ID: {sid}\n\n" + "".join(f"===== {f} =====\n{open(f).read()}\n" for f in spec_files(fx))
        with open(f"{W}/spec-review.md", "w") as out:
            out.write(packet)
        log(f"spec check passed; review packet {W}/spec-review.md (SPEC-ID {sid})")
        # The packet is echoed so factory/harvest.py can pair each judge verdict with exactly
        # what the judge was shown, from the run log alone.
        log(f"-----BEGIN SPEC PACKET {sid}-----\n{packet}\n-----END SPEC PACKET {sid}-----")
    write_feedback(fx, "spec")
    emit(fx, fx_spec_check=result, fx_spec_check_fails=fx.get("spec_check_fails", 0))


def parse_verdict(text):
    """Strict: the last non-blank, non-fence line must be a JSON object with
    factory_verdict in {pass, raise} and an `id`. Anything else is no verdict."""
    lines = [l.strip() for l in (text or "").splitlines() if l.strip() and not l.strip().startswith("```")]
    if not lines:
        return None, "empty response"
    try:
        obj = json.loads(lines[-1])
    except json.JSONDecodeError:
        return None, f"last line is not JSON: {lines[-1][:120]!r}"
    if not isinstance(obj, dict) or obj.get("factory_verdict") not in ("pass", "raise"):
        return None, f"no factory_verdict pass|raise in {lines[-1][:120]!r}"
    if not isinstance(obj.get("id"), str):
        return None, "verdict has no id (judge did not prove it read the packet)"
    return obj, ""


def st_capture(kind):
    text = sys.stdin.read()
    obj, why = parse_verdict(text)
    verdict, reasons = "none", []
    if obj:
        if kind == "spec":
            expect = spec_id({"spec": spec_name_from_tree()})
        else:
            expect = short_hash(worktree_diff(base_rev()))
        if obj["id"] != expect:
            why = f"verdict id {obj['id']!r} != packet id {expect!r} — judge did not read the current packet, or the tree changed under it"
        else:
            verdict = obj["factory_verdict"]
            reasons = [str(r)[:400] for r in (obj.get("reasons") or [])][:8]
    log(f"{kind} judge verdict: {verdict}" + (f" ({why})" if why else ""))
    for r in reasons:
        log(" -", r)
    with open(f"{W}/{kind}-verdict.json", "w") as fh:   # read only by `raised`, the very next stage
        json.dump({"verdict": verdict, "id": obj["id"] if obj else "", "reasons": reasons}, fh)
    emit(None, **{f"fx_{kind}_verdict": verdict, f"fx_{kind}_reasons": json.dumps(reasons or ([why] if why else []))})


def write_feedback(fx, kind):
    """Render what the writer (spec) or builder (conf) must fix into a file its prompt tells it
    to read. Rebuilt from fx every time, so it only ever holds what deterministic stages
    recorded. It is advice to the author, never a verdict: nothing routes on it."""
    out = [f"# Feedback to address ({kind}) — fix every item, then stop\n"]
    sc = fx.get("spec_check") or {}
    if kind == "spec" and sc.get("result") == "fail":
        out.append("## The deterministic spec check FAILED\n" + "".join(f"- {p}\n" for p in sc.get("problems", [])))
    rounds = [e for e in fx.get("judge_log", []) if e["judge"] == kind and e["verdict"] == "raise"]
    for e in reversed(rounds):
        latest = " (LATEST — these are what the judge will re-check)" if e is rounds[-1] else " (earlier round, for context)"
        out.append(f"## {kind} judge objections, round {e['round']}{latest}\n" + "".join(f"- {r}\n" for r in e["reasons"]))
    with open(f"{W}/{FEEDBACK[kind]}", "w") as fh:
        fh.write("\n".join(out))


def st_raised(fx, kind):
    """A judge raised. Count it in fx (the engine's own visit counter is not usable in edge
    conditions), log the objections, and choose: back to the author, or hold for a human.
    Runs straight after `capture` with no agent stage in between, so the reasons file it
    reads is the one capture just wrote."""
    reasons, pid = [], ""
    try:
        v = json.load(open(f"{W}/{kind}-verdict.json"))
        if v.get("verdict") == "raise":
            reasons, pid = [str(r) for r in v.get("reasons", [])], str(v.get("id", ""))
    except (OSError, ValueError):
        pass
    n = fx.get(f"{kind}_raises", 0) + 1
    fx[f"{kind}_raises"] = n
    fx[f"{kind}_judge"] = "raise"
    fx.setdefault("judge_log", []).append({"judge": kind, "round": n, "verdict": "raise", "packet": pid, "reasons": reasons})
    nxt = "revise" if n <= MAX_REVISE_ROUNDS and reasons else "hold"
    write_feedback(fx, kind)
    log(f"{kind} judge raised (raise {n}; {MAX_REVISE_ROUNDS} revise rounds allowed) -> {nxt}")
    for r in reasons:
        log(" -", r)
    emit(fx, **{f"fx_{kind}_next": nxt, f"fx_{kind}_raises": n})


def st_note(where):
    """A human typed a note at a gate. It arrives on stdin (never through a shell), is saved
    for the next agent stage to read, and is echoed so the run log keeps it."""
    text = sys.stdin.read().strip()
    if not text:
        log("empty human note — nothing to revise against")
        sys.exit(1)
    with open(f"{W}/human-note.md", "a") as fh:
        fh.write(f"## Human note at the {where} gate ({time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})\n{text}\n\n")
    log(f"human note ({where}):\n{text}")
    emit(None, **{f"fx_human_note_{where}": text[:2000]})


def st_merge(fx, key, value):
    fx[key] = value
    if key.endswith("_judge"):            # keep passes and no-verdicts in the same log as raises
        kind = key[: -len("_judge")]
        pid = fx.get("spec_id_checked", "") if kind == "spec" else fx.get("diff_id", "")
        fx.setdefault("judge_log", []).append({"judge": kind, "round": fx.get(f"{kind}_raises", 0) + 1,
                                               "verdict": value, "packet": pid, "reasons": []})
    log(f"fx.{key} = {value}")
    emit(fx)


def st_lock(fx):
    """Freeze the spec at the human gate: the approved verify.sh is written into git's object
    store, and later stages compare against that blob id."""
    vs = f"{spec_dir(fx)}/verify.sh"
    blob = git("hash-object", "-w", vs, check=True)
    fx["verify_blob"] = blob
    fx["spec_id"] = spec_id(fx)
    log(f"LOCKED {vs} as blob {blob}; spec id {fx['spec_id']}")
    log(f"spec judge: {fx.get('spec_judge')}   deterministic spec check: {fx.get('spec_check', {}).get('result')}")
    for e in [e for e in fx.get("judge_log", []) if e["judge"] == "spec"]:
        log(f"  spec judge round {e['round']}: {e['verdict']}" + "".join(f"\n    - {r}" for r in e["reasons"]))
    for f in spec_files(fx):
        log(f"\n===== {f} =====\n" + open(f).read())
    emit(fx)


def verify_tampered(fx):
    vs = f"{spec_dir(fx)}/verify.sh"
    if not fx.get("verify_blob"):
        return "no locked verify.sh blob (spec was never locked)"
    if not os.path.isfile(vs):
        return f"{vs} was deleted after approval"
    cur = git("hash-object", vs, check=True)
    return "" if cur == fx["verify_blob"] else f"{vs} is blob {cur[:10]}, approved blob {fx['verify_blob'][:10]}"


def st_gates(fx):
    fx["gate_runs"] = fx.get("gate_runs", 0) + 1
    results, first_fail = [], None
    tamper = verify_tampered(fx)
    if tamper:
        results.append({"gate": "spec-lock", "ok": False, "tail": tamper + " — restore the approved verify.sh; do not edit it"})
        first_fail = results[-1]
    else:
        steps = [("npm ci", "npm ci --no-audit --no-fund"), ("lint", "npm run lint"),
                 ("typecheck", "npm run typecheck"), ("test", "npm test"), ("build", "npm run build"),
                 ("verify.sh", f"STRICT=1 bash {spec_dir(fx)}/verify.sh")]
        for name, cmd in steps:
            try:
                p = sh(cmd, timeout=1200)
                ok, out = p.returncode == 0, p.stdout + p.stderr
            except subprocess.TimeoutExpired:
                ok, out = False, f"{cmd} timed out"
            results.append({"gate": name, "ok": ok, "tail": tail(out, 80 if not ok else 3)})
            log(f"[{'PASS' if ok else 'FAIL'}] {name}")
            if not ok:
                first_fail = results[-1]
                break
    passed = first_fail is None
    fx["gates"] = {"result": "pass" if passed else "fail", "run": fx["gate_runs"],
                   "steps": [{"gate": r["gate"], "ok": r["ok"]} for r in results]}
    if passed:
        diff = worktree_diff(fx["base"])
        did = short_hash(diff)
        fx["gated_tree"], fx["diff_id"] = worktree_tree(), did
        with open(f"{W}/review.diff", "w") as out:
            out.write(f"DIFF-ID: {did}\nSPEC: {spec_dir(fx)}/spec.md\nBASE: {fx['base']}\n\n{diff}")
        log(f"all gates green; review packet {W}/review.diff (DIFF-ID {did}, {len(diff)} bytes)")
    else:
        fx["gate_fails"] = fx.get("gate_fails", 0) + 1
        log(f"\nGATE FAILED: {first_fail['gate']} (failure {fx['gate_fails']} of {MAX_GATE_FIX_ROUNDS} fix rounds)\n"
            f"----- last output -----\n{first_fail['tail']}")
    emit(fx, fx_gates=fx["gates"]["result"], fx_gate_fails=fx["gate_fails"])


def st_classify(fx):
    reasons = []
    tamper = verify_tampered(fx)
    tree = worktree_tree()
    if fx.get("gated_tree") and tree != fx["gated_tree"]:
        fx["post_gate_edit"] = True
        reasons.append("tree changed after the gates passed (a later stage edited files)")
    elif not fx.get("gated_tree"):
        reasons.append("gates never passed on this tree")
    full = sh(f"git diff --cached --no-renames --no-ext-diff -U1000000 {fx['base']}",
              env=_scratch_index(), check=True).stdout
    args = ["bash", f"{W}/classify.sh"] + (["--tampered", tamper] if tamper else [])
    p = sh(args, input=full, timeout=120)
    log(p.stdout + p.stderr)
    m = re.match(r"class=([ABC])\n", p.stdout)
    if p.returncode != 0 or not m:
        cls = "C"
        reasons.append(f"classify.sh exited {p.returncode} with no class — treated as C")
    else:
        cls = m.group(1)
    fx["class"] = cls
    fx["class_reasons"] = [l[8:] for l in p.stdout.splitlines() if l.startswith("reason: ")][:30]
    fx["tamper"] = tamper
    fx["classify_notes"] = reasons
    emit(fx, fx_class=cls)


def ensure_labels(slug, cls):
    want = {"factory": ("5319e7", "Opened by the Fabro factory"),
            f"factory:class-{cls.lower()}": ({"A": "0e8a16", "B": "fbca04", "C": "b60205"}[cls],
                                             f"Factory risk class {cls} (factory/README.md)")}
    for name, (color, desc) in want.items():
        try:
            gh("GET", f"/repos/{slug}/labels/{urllib.parse.quote(name, safe='')}")
        except RuntimeError as e:
            if "HTTP 404" not in str(e):
                raise
            gh("POST", f"/repos/{slug}/labels", {"name": name, "color": color, "description": desc})
            log(f"created label {name}")
    return list(want)


def st_open_pr(fx):
    slug, branch = fx["repo"], fx["branch"]
    if branch in ("main", "master") or not branch.startswith("factory/"):
        raise RuntimeError(f"refusing to push to {branch!r}")
    if git("status", "--porcelain"):
        sh(["git", "add", "-A"], check=True)
        sh(["git", "commit", "-q", "-m", "factory: stage remaining changes", "--no-verify"], check=True)
    head = git("rev-parse", "HEAD")
    p = sh(["git", "push", "--force", "origin", f"HEAD:refs/heads/{branch}"], timeout=300)
    log(tail(p.stdout + p.stderr, 10))
    if p.returncode != 0:
        raise RuntimeError("git push failed")
    owner = slug.split("/")[0]
    prs = gh("GET", f"/repos/{slug}/pulls?state=open&head={owner}:{branch}")
    title_line = next((l for l in open(f"{spec_dir(fx)}/spec.md") if l.startswith("# ")), f"# {fx['spec']}")
    title = "factory: " + re.sub(r"^#\s*(Spec:\s*)?", "", title_line).strip()
    body = (f"Opened by the Fabro factory (Stage 0, shadow mode — **a human merges or closes this; the factory never merges**).\n\n"
            f"- Spec: `{spec_dir(fx)}/spec.md` (approved at the human gate; `verify.sh` locked as blob `{fx.get('verify_blob','?')[:12]}`)\n"
            f"- Fabro run: `{fx.get('run_id')}`\n- Risk class: **{fx['class']}** (computed by `factory/classify.sh`)\n"
            + (f"- Refs #{fx['issue']}\n" if fx.get("issue") else "")
            + "\nThe factory's verdict is posted as a comment once CI and review-hub report.")
    if prs:
        pr = prs[0]
        log(f"PR #{pr['number']} already open; pushed new head {head[:10]}")
    else:
        pr = gh("POST", f"/repos/{slug}/pulls", {"title": title[:200], "head": branch, "base": "main",
                                                   "body": body, "draft": False})
        log(f"opened PR #{pr['number']} {pr['html_url']}")
    labels = ensure_labels(slug, fx["class"])
    cur = [l["name"] for l in gh("GET", f"/repos/{slug}/issues/{pr['number']}/labels")]
    for stale in [l for l in cur if l.startswith("factory:class-") and l not in labels]:
        gh("DELETE", f"/repos/{slug}/issues/{pr['number']}/labels/{urllib.parse.quote(stale, safe='')}")
    gh("POST", f"/repos/{slug}/issues/{pr['number']}/labels", {"labels": labels})
    fx["pr"] = {"number": pr["number"], "url": pr["html_url"], "head": head}
    emit(fx, fx_pr=pr["html_url"])


def parse_report(body):
    """review-hub report card → {validator: {"icon","text","clear","total"}}."""
    rows = {}
    for line in body.splitlines():
        m = re.match(r"^\|\s*(\S+)\s*\|\s*\[([^\]]+)\]\([^)]*\)\s*\|\s*([^|]*)\|", line)
        if not m:
            continue
        text = m.group(3).strip()
        c = re.search(r"(\d+)/(\d+) clear", text)
        rows[m.group(2)] = {"icon": m.group(1), "text": text,
                            "clear": int(c.group(1)) if c else None, "total": int(c.group(2)) if c else None}
    return rows


def actions_log_tail(slug, job_id):
    try:
        return tail(gh("GET", f"/repos/{slug}/actions/jobs/{job_id}/logs", raw=True), 60)
    except RuntimeError as e:
        return f"(log unavailable: {e})"


def st_wait_checks(fx):
    slug, head = fx["repo"], fx["pr"]["head"]
    deadline = time.time() + CHECK_WAIT_SECONDS
    runs = {}
    while True:
        data = gh("GET", f"/repos/{slug}/commits/{head}/check-runs?per_page=100")
        runs = {}
        for r in data.get("check_runs", []):    # keep the newest run per name
            if r["name"] not in runs or r["id"] > runs[r["name"]]["id"]:
                runs[r["name"]] = r
        missing = [n for n in REQUIRED_CHECKS if n not in runs]
        pending = [n for n in REQUIRED_CHECKS if n in runs and runs[n]["status"] != "completed"]
        log(time.strftime("%H:%M:%S"), "missing:", missing or "-", "pending:", pending or "-")
        if not missing and not pending:
            break
        if time.time() > deadline:
            fx["ci"] = {"result": "timeout", "head": head, "missing": missing, "pending": pending}
            log("checks did not all report before the deadline — that is a hold, not a pass")
            emit(fx, fx_ci="timeout")
        time.sleep(30)
    concl = {n: runs[n]["conclusion"] for n in REQUIRED_CHECKS}
    validators = {n: {"conclusion": r["conclusion"], "title": (r.get("output") or {}).get("title")}
                  for n, r in runs.items() if (r.get("app") or {}).get("slug") == REVIEW_HUB_APP and n != "review-hub"}
    started = runs["review-hub"].get("started_at") or ""
    report, comment_url = {}, None
    for c in gh("GET", f"/repos/{slug}/issues/{fx['pr']['number']}/comments?per_page=100"):
        if c["body"].startswith(REPORT_MARKER) and c["updated_at"] >= started:
            report, comment_url = parse_report(c["body"]), c["html_url"]
    red = [n for n, v in concl.items() if v != "success"]
    result = "green" if not red else "red"
    fx["ci"] = {"result": result, "head": head, "required": concl, "validators": validators,
                "report": report, "report_url": comment_url}
    log(f"required checks: {concl}")
    for n, v in sorted(validators.items()):
        row = report.get(n, {})
        log(f"  {n}: {v['conclusion']} — {row.get('text', 'no report row')}")
    if red:
        fx["ci_red_rounds"] = fx.get("ci_red_rounds", 0) + 1
        log(f"\nCI RED (round {fx['ci_red_rounds']} of {MAX_CI_FIX_ROUNDS}). What failed:")
        for n in red:
            r = runs[n]
            out = r.get("output") or {}
            log(f"\n### {n}: {r['conclusion']} — {out.get('title') or ''}\n{(out.get('summary') or '')[:2500]}")
            if (r.get("app") or {}).get("slug") == "github-actions":
                log(actions_log_tail(slug, r["id"]))
        for n, v in validators.items():
            if v["conclusion"] != "success" and n not in red:
                log(f"\n### review-hub validator {n}: {v['conclusion']} — {v['title']}")
    emit(fx, fx_ci=result, fx_ci_red_rounds=fx.get("ci_red_rounds", 0))


def decide(fx):
    """would merge only if every check positively passed. Missing evidence is a hold."""
    hold = []
    sc = (fx.get("spec_check") or {}).get("result")
    if sc != "pass":
        hold.append(f"deterministic spec check: {sc or 'missing'}")
    if fx.get("spec_judge") != "pass":
        hold.append(f"spec judge: {fx.get('spec_judge') or 'missing'}")
    g = (fx.get("gates") or {}).get("result")
    if g != "pass":
        hold.append(f"deterministic gates: {g or 'missing'}")
    if fx.get("conf_judge") != "pass":
        hold.append(f"conformance judge: {fx.get('conf_judge') or 'missing'}")
    if fx.get("tamper"):
        hold.append("spec gate tampered: " + fx["tamper"])
    for n in fx.get("classify_notes") or []:
        hold.append(n)
    cls = fx.get("class")
    if cls not in ("A", "B", "C"):
        hold.append("no risk class")
    elif cls == "C":
        hold.append("class C — never auto-merged (human only)")
    ci = fx.get("ci") or {}
    if ci.get("result") != "green":
        hold.append(f"CI/review-hub: {ci.get('result') or 'missing'}")
    if ci.get("head") and fx.get("pr", {}).get("head") and ci["head"] != fx["pr"]["head"]:
        hold.append("checks are for an older head")
    report = ci.get("report") or {}
    if ci.get("result") == "green":
        if not report:
            hold.append("review-hub report card missing or older than the review-hub check — votes unknown")
        if not ci.get("validators"):
            hold.append("no review-hub validator checks found")
        for n, v in sorted((ci.get("validators") or {}).items()):
            row = report.get(n)
            if v["conclusion"] == "neutral":
                continue                                    # validator not applicable to this diff
            if v["conclusion"] != "success":
                hold.append(f"review-hub {n}: {v['conclusion']}")
            elif not row or row["clear"] is None:
                hold.append(f"review-hub {n}: vote count not published")
            elif not (row["clear"] == row["total"] == UNANIMOUS):
                hold.append(f"review-hub {n}: {row['clear']}/{row['total']} clear — factory needs {UNANIMOUS}/{UNANIMOUS}")
    if fx.get("override"):
        hold.append("human overrode a judge at escalation (logged): " + fx["override"])
    if fx.get("abandoned"):
        hold.append("abandoned at escalation: " + fx["abandoned"])
    return ("would merge" if not hold else "hold"), hold


def st_verdict(fx):
    verdict, reasons = decide(fx)
    ci = fx.get("ci") or {}
    votes = "\n".join(f"| {n} | {v['conclusion']} | {(ci.get('report') or {}).get(n, {}).get('text', '—')} |"
                      for n, v in sorted((ci.get("validators") or {}).items())) or "| — | — | — |"
    record = {"verdict": verdict, "class": fx.get("class"), "reasons": reasons, "run_id": fx.get("run_id"),
              "spec": fx.get("spec"), "head": (fx.get("pr") or {}).get("head"),
              "spec_judge": fx.get("spec_judge"), "conf_judge": fx.get("conf_judge"),
              "gate_runs": fx.get("gate_runs"), "gate_fails": fx.get("gate_fails"),
              "ci_red_rounds": fx.get("ci_red_rounds"), "required": ci.get("required"),
              "override": fx.get("override"), "factory_stage": 0, "profile": fx.get("profile")}
    head = "✅ **would merge**" if verdict == "would merge" else "⏸️ **hold**"
    body = "\n".join([
        VERDICT_MARKER, f"## Factory verdict: {head} · class {fx.get('class', '?')}", "",
        "Stage 0 (shadow mode): the factory never merges. This is what it *would* do; a human decides.", "",
        ("**Hold because:**\n" + "\n".join(f"- {r}" for r in reasons)) if reasons else
        "Every deterministic gate passed, both factory judges passed, and every applicable review-hub validator was 5/5 clear.",
        "", "| review-hub validator | check | report card |", "|--|--|--|", votes, "",
        f"Class reasons: " + ("; ".join(fx.get("class_reasons") or []) or "—"),
        f"<sub>run `{fx.get('run_id')}` · gates {fx.get('gate_runs')} run(s), {fx.get('gate_fails')} failed · "
        f"CI red rounds {fx.get('ci_red_rounds')} · spec judge {fx.get('spec_judge')} · conformance judge {fx.get('conf_judge')}</sub>",
        "", f"<!-- factory:record {json.dumps(record, sort_keys=True)} -->"])
    log(body)
    pr = fx.get("pr")
    if pr:
        c = gh("POST", f"/repos/{fx['repo']}/issues/{pr['number']}/comments", {"body": body})
        log("posted", c["html_url"])
        fx["verdict"] = {"verdict": verdict, "reasons": reasons, "comment": c["html_url"]}
    else:
        log("no PR to comment on — verdict recorded in run context only")
        fx["verdict"] = {"verdict": verdict, "reasons": reasons}
    emit(fx, fx_verdict=verdict)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    cmd, args = sys.argv[1], sys.argv[2:]
    os.makedirs(W, exist_ok=True)
    try:
        if cmd == "setup":
            st_setup(*args)
        elif cmd == "capture":
            st_capture(args[0])
        elif cmd == "note":
            st_note(args[0])
        else:
            fx = read_stdin_json()
            if not fx.get("spec"):
                log("no factory state on stdin (fx) — refusing to continue")
                sys.exit(3)
            fn = {"spec_check": st_spec_check, "lock": st_lock, "gates": st_gates, "classify": st_classify,
                  "open_pr": st_open_pr, "wait_checks": st_wait_checks, "verdict": st_verdict}.get(cmd)
            if cmd == "merge":
                st_merge(fx, args[0], args[1])
            elif cmd == "raised":
                st_raised(fx, args[0])
            elif fn:
                fn(fx)
            else:
                print(f"unknown stage {cmd}")
                sys.exit(2)
    except SystemExit:
        raise
    except Exception as e:  # a crash is a failed stage, which every edge routes to hold
        log(f"STAGE {cmd} CRASHED: {type(e).__name__}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
