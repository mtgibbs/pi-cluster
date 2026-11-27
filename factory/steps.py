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
  steps.py capture <kind>                 stdin: response.<judge>   (parses ONE vote)
  steps.py vote <kind>                    stdin: fx   (records the vote, tallies the round: more|pass|raise|none)
  steps.py raised <kind>                  stdin: fx   (counts the raise, writes feedback, picks revise|hold)
  steps.py passed spec_intent|conf_intent stdin: fx   (intent panel passed: record it, hand on to rigor/conformance)
  steps.py forward spec                   stdin: fx   (human gate [F]: the last-raising spec panel's objections become the note)
  steps.py note spec|build                stdin: human.gate.text (a human's typed note)
  steps.py merge <key> <value>            stdin: fx
  steps.py lock                           stdin: fx
  steps.py gates                          stdin: fx
  steps.py classify                       stdin: fx
  steps.py open_pr                        stdin: fx
  steps.py wait_checks                    stdin: fx
  steps.py verdict                        stdin: fx
  steps.py route spec|gates|review <mode> stdin: fx   (<mode> = inputs.gate_mode: who answers the gate — a person, or code)

<kind> is a judge panel: spec_intent, spec (rigor), conf_intent, conf (conformance). The panel
order is spec_intent -> spec -> (build, gates) -> conf_intent -> conf; see README "Judge panels".

The idea text. setup writes it verbatim to /tmp/factory/idea.md (from inputs.idea_b64), and
inputs.code_sha covers it alongside steps.py and classify.sh, so the sha256 check every
deterministic stage runs first also catches an agent editing the idea the intent panels judge
against.

Gate mode (inputs.gate_mode, docs/design/factory-intake.md). `human`: the run stops at approve_spec,
and at gates_escalate / review_escalate when those loops run out, for a person. `auto` (the intake):
no person mid-run. `route spec auto` approves the spec only when the deterministic spec check AND
both spec panels recorded a pass; anything else ends the run with no PR ("spec held"). `route
gates|review auto` turns an escalation into a hold. A model can only raise: nothing here can turn a
raise, a `none` or a crash into an approval. The mode comes from the version's inputs (on the
command line), and must match what setup recorded, so an agent forging fx cannot change it.
"""
import hashlib, json, os, re, subprocess, sys, time, urllib.error, urllib.parse, urllib.request

# FACTORY_TEST_DIR exists only for factory/test/panel.test.py; the workflow never sets it, and an
# agent stage cannot set a command node's environment.
W = os.environ.get("FACTORY_TEST_DIR") or "/tmp/factory"
REQUIRED_CHECKS = ["build", "lint", "test", "typecheck", "review-hub"]
REVIEW_HUB_APP = "empty-gibbs"           # GitHub App slug that posts review-hub's checks
REPORT_MARKER = "<!-- review-hub:report -->"
VERDICT_MARKER = "<!-- factory:verdict -->"
MAX_GATE_FIX_ROUNDS = 3                  # design table row 5
MAX_CI_FIX_ROUNDS = 3                    # design table row 10
MAX_SPEC_CHECK_RETRIES = 2               # failed deterministic spec checks sent back to ideate
# Judge panels (README "Judge panels"). Votes, thresholds and the revise cap come from
# factory/models.toml via submit.sh -> [run.inputs] -> setup (FACTORY_PANEL) -> fx["panel"].
# These defaults apply only when setup was given nothing.
# Panel kinds, in the order a run meets them. `spec`/`conf` are the rigor and conformance
# panels (their node ids, fx keys and records predate the intent panels and are unchanged).
KINDS = ("spec_intent", "spec", "conf_intent", "conf")
INTENT_KINDS = ("spec_intent", "conf_intent")
PANEL_KEYS = ("spec_votes", "spec_threshold", "conf_votes", "conf_threshold", "spec_rounds", "conf_rounds",
              "spec_intent_votes", "spec_intent_threshold", "spec_intent_rounds",
              "conf_intent_votes", "conf_intent_threshold", "conf_intent_rounds")
DEFAULT_PANEL = {"spec_votes": 1, "spec_threshold": 1, "conf_votes": 1, "conf_threshold": 1,
                 "spec_rounds": 4, "conf_rounds": 4,
                 "spec_intent_votes": 1, "spec_intent_threshold": 1, "spec_intent_rounds": 3,
                 "conf_intent_votes": 1, "conf_intent_threshold": 1, "conf_intent_rounds": 3}
MAX_VOTES = 15
MAX_ROUNDS = 10
FEEDBACK = {"spec": "spec-feedback.md", "conf": "build-feedback.md",
            "spec_intent": "spec-intent-feedback.md", "conf_intent": "change-intent-feedback.md"}
PACKET = {"spec": "spec-review.md", "conf": "review.diff",
          "spec_intent": "spec-intent-review.md", "conf_intent": "change-intent-review.md"}
NAME = {"spec": "spec rigor", "conf": "conformance", "spec_intent": "spec intent", "conf_intent": "change intent"}
# What an intent panel may raise about. A raise reason must carry one of these tags.
INTENT_TAGS = ("missing", "added", "oversized")
_TAG_RE = re.compile(r"^\s*[\[(]?\s*(missing|added|oversized)\s*[\])]?\s*[:\-\u2013\u2014]\s*(\S.*)$", re.I | re.S)
CHECK_WAIT_SECONDS = int(os.environ.get("FACTORY_CHECK_WAIT", "2700"))  # 45 min
UNANIMOUS = 5                            # rule 5: would-merge needs 5/5 clear per validator


# ---------------------------------------------------------------- plumbing
# Fabro finds a stage's routing directive by brace-matching its stdout. One unbalanced "{"
# in echoed model text (a judge quoting `it('x', async () => {`) and it finds no JSON at all:
# the stage is marked failed with "not a routing directive" (run 01M8B66RQXT5T7NYFN4R7YW1KK,
# spec round 3). So no brace other than the directive's own structure ever reaches stdout:
#   * human-readable stdout lines show braces as the look-alikes U+2983 / U+2984;
#   * inside the directive, braces in string values are written as \u007b / \u007d, which
#     any JSON parser decodes back to the exact original text.
import builtins
_SHOW = str.maketrans({"{": "\u2983", "}": "\u2984"})
_MARK = str.maketrans({"{": "\ue000", "}": "\ue001"})


def print(*a, **k):
    if k.get("file") in (None, sys.stdout):
        a = tuple(str(x).translate(_SHOW) for x in a)
    builtins.print(*a, **k)


def _mark(o):
    if isinstance(o, str):
        return o.translate(_MARK)
    if isinstance(o, dict):
        return {_mark(k): _mark(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_mark(v) for v in o]
    return o


def directive(obj):
    """obj as one JSON line whose only literal braces are structural."""
    return json.dumps(_mark(obj), sort_keys=True).replace("\\ue000", "\\u007b").replace("\\ue001", "\\u007d")


def log(*a):
    print(*a, flush=True)


def emit(fx=None, **flat):
    upd = dict(flat)
    if fx is not None:
        upd["fx"] = fx
    builtins.print(directive({"context_updates": upd}))
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


def worktree_diff(base, context=5, exclude=None):
    env = _scratch_index()
    spec = ["--", ".", f":(exclude){exclude}"] if exclude else []
    return sh(["git", "diff", "--cached", "--no-renames", "--no-ext-diff", f"-U{context}", base, *spec],
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


def idea_text():
    """The idea exactly as submitted. setup wrote it from inputs.idea_b64; the script line of
    every deterministic stage has already checked its sha256 (inside inputs.code_sha)."""
    with open(f"{W}/idea.md", "rb") as fh:
        return fh.read().decode("utf-8", errors="replace")


def idea_sha():
    with open(f"{W}/idea.md", "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def intent_id(inner):
    """An intent packet's id: binds the idea to the spec or diff it is compared with, and
    differs from the rigor/conformance packet ids so a voter cannot echo the wrong packet."""
    return short_hash(f"intent:{idea_sha()}:{inner}")


def packet_id(kind, spec=None, base=None):
    """The id a judge of `kind` must echo, recomputed from the tree (and the idea) as it is now."""
    if kind in ("spec", "spec_intent"):
        sid = spec_id({"spec": spec or spec_name_from_tree()})
        return sid if kind == "spec" else intent_id(sid)
    did = short_hash(worktree_diff(base or base_rev()))
    return did if kind == "conf" else intent_id(did)


def file_sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def write_packet(fx, kind, text):
    """Write a judge's review packet and remember its hash; `vote` refuses a round whose packet
    changed under it (a voter editing what the next voter reads)."""
    os.makedirs(W, exist_ok=True)
    with open(f"{W}/{PACKET[kind]}", "w") as out:
        out.write(text)
    fx[f"{kind}_packet_sha"] = file_sha(f"{W}/{PACKET[kind]}")


def idea_block():
    return ("===== THE IDEA (verbatim, exactly as submitted) =====\n" + idea_text().rstrip("\n")
            + "\n===== END OF THE IDEA =====\n")


def tag_reasons(reasons):
    """Intent-panel reasons -> (tagged 'kind: text' strings, their kinds, untagged strings)."""
    tagged, kinds, untagged = [], [], []
    for r in reasons:
        m = _TAG_RE.match(str(r))
        if m:
            k = m.group(1).lower()
            tagged.append(f"{k}: {m.group(2).strip()}")
            kinds.append(k)
        else:
            untagged.append(str(r))
    return tagged, kinds, untagged


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
          "profile": os.environ.get("FACTORY_PROFILE", ""),
          "panel": parse_panel(os.environ.get("FACTORY_PANEL", "")),
          "idea_sha": idea_sha(),
          # Who asked, how, and at what earn-out stage (inputs; written into the verdict record).
          "gate_mode": gate_mode_of(os.environ.get("FACTORY_GATE_MODE", "")),
          "origin": os.environ.get("FACTORY_ORIGIN", "") or "human",
          "request": os.environ.get("FACTORY_REQUEST", ""),
          "target_stage": int(os.environ.get("FACTORY_TARGET_STAGE", "0") or 0)}
    if not idea_text().strip():
        raise RuntimeError(f"{W}/idea.md is empty — the intent panels would have nothing to judge against")
    log(f"model profile: {fx['profile'] or '(none recorded)'}")
    log(f"idea ({len(idea_text())} chars, sha256 {fx['idea_sha'][:12]}) saved verbatim to {W}/idea.md")
    log("judge panels: " + panel_line(fx["panel"]))
    log(f"gate mode {fx['gate_mode']} · origin {fx['origin']}" + (f" · request {fx['request']}" if fx["request"] else ""))
    emit(fx, fx_spec=spec, fx_gate_mode=fx["gate_mode"])


GATE_MODES = ("human", "auto")


def gate_mode_of(mode):
    if mode not in GATE_MODES:
        raise RuntimeError(f"gate mode {mode!r} is not one of {GATE_MODES}")
    return mode


def spec_held_reasons(fx):
    """Why code may not approve this spec in auto mode; empty means approve. The same evidence
    lock prints for a person: the deterministic check and the latest result of BOTH spec panels."""
    why = []
    sc = (fx.get("spec_check") or {}).get("result")
    if sc != "pass":
        why.append(f"deterministic spec check: {sc or 'missing'}")
    for kind, key in (("spec_intent", "spec_intent_judge"), ("spec", "spec_judge")):
        if fx.get(key) != "pass":
            why.append(f"{NAME[kind]} panel: {fx.get(key) or 'did not run on this version'}")
        else:
            t = (fx.get(f"{kind}_tallies") or [None])[-1]
            if not t or t.get("outcome") != "pass":
                why.append(f"{NAME[kind]} panel: recorded pass without a passing round")
    return why


def st_route(fx, where, mode):
    """Who answers this gate. human -> the person's gate (today's behaviour). auto -> code:
    spec: approve only on a full pass, else held (the run ends, no PR); gates/review: hold."""
    if where not in ("spec", "gates", "review"):
        raise RuntimeError(f"unknown gate {where!r}")
    mode = gate_mode_of(mode)
    if fx.get("gate_mode") != mode:
        raise RuntimeError(f"gate mode on the command line ({mode}) differs from setup's ({fx.get('gate_mode')!r})")
    key = f"fx_{where}_route"
    if mode == "human":
        log(f"gate mode human: the {where} gate is a person's")
        emit(fx, **{key: "human"})
    if where != "spec":
        fx[f"{where}_escalated"] = "auto-hold"
        log(f"gate mode auto: no person to escalate to at the {where} gate -> the PR is held")
        emit(fx, **{key: "hold"})
    why = spec_held_reasons(fx)
    if not why:
        fx["spec_approval"] = "auto"
        log("gate mode auto: deterministic spec check and both spec panels passed -> spec approved by code, building")
        emit(fx, **{key: "approve"})
    kind, t = last_raising(fx, "spec")
    objections = format_objections(fx, kind, t, f"{NAME[kind].capitalize()} panel objections, round {t['round']}") if t else ""
    fx["spec_approval"] = "held"
    fx["verdict"] = {"verdict": "spec held", "reasons": why, "objections": objections[:8000]}
    log("gate mode auto: spec NOT approved -> the run ends here, no PR\n" + "\n".join(f"- {w}" for w in why)
        + ("\n" + objections if objections else ""))
    emit(fx, **{key: "held", "fx_verdict": "spec held"})


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
        # A new version of the spec: both spec panels start a fresh round on it, and no verdict
        # about an earlier version stands (decide() reads a missing one as hold).
        for k in ("spec_intent", "spec"):
            fx.pop(f"{k}_open", None)
            fx.pop(f"{k}_judge", None)
        fx["spec_cycle"] = {k: len(fx.get(f"{k}_tallies") or []) for k in ("spec_intent", "spec")}
        iid = intent_id(sid)
        ipacket = (f"INTENT-ID: {iid}\n\n" + idea_block() + "\n"
                   + "".join(f"===== {f} =====\n{open(f).read()}\n" for f in spec_files(fx)[:2]))
        write_packet(fx, "spec_intent", ipacket)
        packet = f"SPEC-ID: {sid}\n\n" + "".join(f"===== {f} =====\n{open(f).read()}\n" for f in spec_files(fx))
        write_packet(fx, "spec", packet)
        log(f"spec check passed; intent packet {W}/{PACKET['spec_intent']} (INTENT-ID {iid}), "
            f"rigor packet {W}/{PACKET['spec']} (SPEC-ID {sid})")
        # The packets are echoed so factory/harvest.py can pair each judge verdict with exactly
        # what the judge was shown, from the run log alone.
        log(f"-----BEGIN SPEC-INTENT PACKET {iid}-----\n{ipacket}\n-----END SPEC-INTENT PACKET {iid}-----")
        log(f"-----BEGIN SPEC PACKET {sid}-----\n{packet}\n-----END SPEC PACKET {sid}-----")
    write_feedback(fx, "spec")
    write_feedback(fx, "spec_intent")
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
    """Parse ONE judge vote. Its result goes to a file that only the very next stage (`vote`)
    reads and then deletes, so no later voter in the round can find it."""
    if kind not in KINDS:
        raise RuntimeError(f"unknown panel kind {kind!r}")
    vfile = f"{W}/{kind}-verdict.json"
    if os.path.exists(vfile):
        os.remove(vfile)
    text = sys.stdin.read()
    obj, why = parse_verdict(text)
    verdict, reasons, kinds = "none", [], []
    if obj:
        expect = packet_id(kind)
        if obj["id"] != expect:
            why = f"verdict id {obj['id']!r} != packet id {expect!r} — judge did not read the current packet, or the tree changed under it"
        else:
            verdict = obj["factory_verdict"]
            reasons = [str(r)[:400] for r in (obj.get("reasons") or [])][:8]
            if kind in INTENT_KINDS and verdict == "raise":
                # An intent panel may only raise about the idea: something missing, something
                # added, or a spec/change out of proportion. Anything else is the rigor or
                # conformance panel's job and is dropped; a raise with nothing left is no verdict.
                reasons, kinds, dropped = tag_reasons(reasons)
                if dropped:
                    log(f"dropped {len(dropped)} untagged reason(s) (not missing:/added:/oversized:): "
                        + " | ".join(d[:120] for d in dropped))
                if not reasons:
                    verdict, why = "none", ("intent raise carried no missing:/added:/oversized: reason — "
                                            "test rigor and code correctness belong to the other panels")
    log(f"{kind} judge verdict: {verdict}" + (f" ({why})" if why else ""))
    for r in reasons:
        log(" -", r)
    rec = {"verdict": verdict, "id": obj["id"] if obj else "", "reasons": reasons, "why": why}
    if kind in INTENT_KINDS:
        rec["kinds"] = kinds
    with open(vfile, "w") as fh:   # read (and deleted) only by `vote`, the very next stage
        json.dump(rec, fh)
    emit(None, **{f"fx_{kind}_verdict": verdict, f"fx_{kind}_reasons": json.dumps(reasons or ([why] if why else []))})


# ---------------------------------------------------------------- judge panels
def parse_panel(text):
    """'spec_votes=5 spec_threshold=3 ...' -> validated dict. Unset keys take DEFAULT_PANEL.
    Raises ValueError on anything malformed (setup then crashes -> abort, never a silent default)."""
    p = dict(DEFAULT_PANEL)
    for tok in (text or "").split():
        k, sep, v = tok.partition("=")
        if not sep or k not in PANEL_KEYS:
            raise ValueError(f"panel setting {tok!r}: expected one of {', '.join(PANEL_KEYS)} as key=<integer>")
        if not re.fullmatch(r"\d{1,3}", v):
            raise ValueError(f"panel setting {tok!r}: value must be a non-negative integer")
        p[k] = int(v)
    validate_panel(p)
    return p


def validate_panel(p):
    for kind in KINDS:
        n, t, r = p[f"{kind}_votes"], p[f"{kind}_threshold"], p[f"{kind}_rounds"]
        if not 1 <= n <= MAX_VOTES:
            raise ValueError(f"{kind}_votes={n}: must be 1..{MAX_VOTES}")
        if not 1 <= t <= n:
            raise ValueError(f"{kind}_threshold={t}: must satisfy 1 <= threshold <= votes ({n})")
        if not 0 <= r <= MAX_ROUNDS:
            raise ValueError(f"{kind}_rounds={r}: must be 0..{MAX_ROUNDS}")
    return p


def panel_line(p):
    return " ".join(f"{k}={p[k]}" for k in PANEL_KEYS)


def fx_panel(fx):
    return validate_panel({**DEFAULT_PANEL, **(fx.get("panel") or {})})


def tally(verdicts, n, threshold):
    """Decide one panel round from the votes cast so far. Deterministic; fails closed.
      raise  when raise-votes >= threshold
      pass   only when actual pass-votes >= n - threshold + 1 (a `none` vote never counts as a pass)
      none   when every vote is in, or the outcome can no longer reach either bar
      more   otherwise (cast another vote)
    Both bars cannot be met at once: threshold + (n - threshold + 1) > n."""
    r, p = verdicts.count("raise"), verdicts.count("pass")
    left = n - len(verdicts)
    need_pass = n - threshold + 1
    if r >= threshold:
        return "raise"
    if p >= need_pass:
        return "pass"
    if left <= 0 or (r + left < threshold and p + left < need_pass):
        return "none"
    return "more"


def round_votes(fx, kind, rnd):
    return [e for e in fx.get("judge_log", []) if e.get("judge") == kind and e.get("round") == rnd]


def format_objections(fx, kind, t, heading):
    """The raising voters' objections of one tallied round, grouped per voter, verbatim.
    No model merges or dedupes them."""
    raisers = [e for e in round_votes(fx, kind, t["round"]) if e.get("verdict") == "raise"]
    cast = f" ({t['cast']} votes cast; voting stops once the outcome is decided)" if t["cast"] < t["n"] else ""
    out = [f"{heading}: {t['raise']} of {t['n']} voters raised{cast}\n"]
    for e in raisers:
        out.append(f"### Voter {e.get('vote', '?')}\n" + ("".join(f"- {r}\n" for r in e.get("reasons") or [])
                                                        or "- (raised with no reasons)\n"))
    return "\n".join(out)


def minority_notes(fx, kind):
    """The last round of a panel PASSED but some voters raised: their objections, kept as
    non-blocking notes. Empty string otherwise."""
    tallies = fx.get(f"{kind}_tallies") or []
    if not tallies or tallies[-1]["outcome"] != "pass" or not tallies[-1]["raise"]:
        return ""
    name = NAME[kind].capitalize()
    return format_objections(fx, kind, tallies[-1],
                             f"## {name} panel passed with minority objections (NON-BLOCKING), round {tallies[-1]['round']}")


def tally_line(t):
    return (f"r{t['round']} {t['outcome']} ({t['raise']} raise / {t['pass']} pass / {t['none']} none"
            f" of {t['cast']} cast; panel {t['n']}, threshold {t['threshold']})")


def write_feedback(fx, kind):
    """Render what the writer (spec) or builder (conf) must fix into a file its prompt tells it
    to read. Rebuilt from fx every time, so it only ever holds what deterministic stages
    recorded. It is advice to the author, never a verdict: nothing routes on it.
    Only DECIDED raise rounds appear here, so a voter never sees another vote of its own round."""
    out = [f"# Feedback to address ({NAME[kind]}) — fix every item, then stop\n"]
    if kind in INTENT_KINDS:
        out.append("The intent panel compares your work with the ORIGINAL idea (/tmp/factory/idea.md), not with "
                   "earlier objections. `missing:` = the idea asks for it and it is not delivered; `added:` = the "
                   "idea did not ask for it — remove it; `oversized:` = cut it down to the size of the ask. "
                   "This feedback outranks the rigor/conformance feedback.\n")
    sc = fx.get("spec_check") or {}
    if kind == "spec" and sc.get("result") == "fail":
        out.append("## The deterministic spec check FAILED\n" + "".join(f"- {p}\n" for p in sc.get("problems", [])))
    raised = [t for t in fx.get(f"{kind}_tallies", []) if t["outcome"] == "raise"]
    for t in reversed(raised):
        if kind in INTENT_KINDS:
            latest = " (LATEST)" if t is raised[-1] else " (earlier round, for context)"
        else:
            latest = " (LATEST — these are what the judges will re-check)" if t is raised[-1] else " (earlier round, for context)"
        out.append(format_objections(fx, kind, t, f"## {kind} judge panel, round {t['round']}{latest}"))
    with open(f"{W}/{FEEDBACK[kind]}", "w") as fh:
        fh.write("\n".join(out))


def st_vote(fx, kind):
    """Record one judge vote (written by `capture` a moment ago), then tally the round.
    Emits fx_<kind>_panel = more (cast another vote) | pass | raise | none. A missing or
    unreadable vote file is a `none` vote: it can only hold, never pass."""
    if kind not in KINDS:
        raise RuntimeError(f"unknown panel kind {kind!r}")
    panel = fx_panel(fx)
    n, thr = panel[f"{kind}_votes"], panel[f"{kind}_threshold"]
    vfile = f"{W}/{kind}-verdict.json"
    try:
        with open(vfile) as fh:
            v = json.load(fh)
    except (OSError, ValueError) as e:
        v = {"verdict": "none", "id": "", "reasons": [], "why": f"no readable vote from capture ({type(e).__name__})"}
    finally:
        if os.path.exists(vfile):
            os.remove(vfile)      # gone before the next voter of this round starts
    # The packet every voter of this round reads must not change under the round. A voter that
    # edited it could steer the next one; that round is decided `none` (hold), never pass.
    tampered = ""
    want = fx.get(f"{kind}_packet_sha")
    if want:
        try:
            got = file_sha(f"{W}/{PACKET[kind]}")
        except OSError:
            got = "missing"
        if got != want:
            tampered = f"review packet {PACKET[kind]} changed during the round ({got[:12]} != {want[:12]})"
            v = {"verdict": "none", "id": str(v.get("id") or ""), "reasons": [], "why": tampered}
    verdict = v.get("verdict") if v.get("verdict") in ("pass", "raise") else "none"
    tallies = fx.setdefault(f"{kind}_tallies", [])
    rnd = len(tallies) + 1
    open_votes = fx.setdefault(f"{kind}_open", [])
    open_votes.append(verdict)
    idx = len(open_votes)
    entry = {"judge": kind, "round": rnd, "vote": idx, "of": n, "verdict": verdict, "packet": str(v.get("id") or ""),
             "reasons": [str(r) for r in v.get("reasons") or []] if verdict != "none" else [],
             "why": str(v.get("why") or "")}
    if kind in INTENT_KINDS:
        entry["kinds"] = [k for k in v.get("kinds") or [] if k in INTENT_TAGS] if verdict == "raise" else []
    fx.setdefault("judge_log", []).append(entry)
    decision = "none" if tampered else tally(open_votes, n, thr)
    log(f"{kind} panel round {rnd}, vote {idx} of up to {n}: {verdict}" + (f" ({v.get('why')})" if v.get("why") else ""))
    if decision != "more":
        t = {"round": rnd, "n": n, "threshold": thr, "cast": len(open_votes), "raise": open_votes.count("raise"),
             "pass": open_votes.count("pass"), "none": open_votes.count("none"), "outcome": decision}
        if tampered:
            t["tamper"] = tampered
        tallies.append(t)
        fx.pop(f"{kind}_open", None)
        log(f"{kind} panel decided: {tally_line(t)}")
    else:
        log(f"{kind} panel: not decided yet ({open_votes.count('raise')} raise, {open_votes.count('pass')} pass, "
            f"{open_votes.count('none')} none) -> another vote on {packet_head(kind)}")
    emit(fx, **{f"fx_{kind}_panel": decision, f"fx_{kind}_vote": f"r{rnd}v{idx}"})


def packet_head(kind):
    """The first line of a panel's packet (its id line), for the run log."""
    try:
        with open(f"{W}/{PACKET[kind]}") as fh:
            return fh.readline().strip() or "(empty packet)"
    except OSError:
        return "(no packet)"


def st_passed(fx, kind):
    """An intent panel passed: record it and hand on to the rigor (spec) or conformance panel.
    The forward edge tests fx_<kind>_judge=pass; anything else is a hold."""
    if kind not in INTENT_KINDS:
        raise RuntimeError(f"`passed` is only for the intent panels, not {kind!r}")
    t = (fx.get(f"{kind}_tallies") or [None])[-1]
    if not t or t["outcome"] != "pass":
        raise RuntimeError(f"{kind} has no passing round to record")
    fx[f"{kind}_judge"] = "pass"
    nxt = "spec" if kind == "spec_intent" else "conf"
    log(f"{NAME[kind]} panel passed ({tally_line(t)}) -> {NAME[nxt]} panel next, on {packet_head(nxt)}")
    emit(fx, **{f"fx_{kind}_judge": "pass"})


def st_raised(fx, kind):
    """A judge panel raised. Count it in fx (the engine's own visit counter is not usable in
    edge conditions), write the raising voters' objections as feedback, and choose: back to
    the author, or hold for a human."""
    cap = fx_panel(fx)[f"{kind}_rounds"]
    tallies = fx.get(f"{kind}_tallies") or []
    last = tallies[-1] if tallies and tallies[-1]["outcome"] == "raise" else None
    reasons = [r for e in (round_votes(fx, kind, last["round"]) if last else []) if e.get("verdict") == "raise"
               for r in e.get("reasons") or []]
    n = fx.get(f"{kind}_raises", 0) + 1
    fx[f"{kind}_raises"] = n
    fx[f"{kind}_judge"] = "raise"
    nxt = "revise" if last and n <= cap and reasons else "hold"
    write_feedback(fx, kind)
    log(f"{kind} judge panel raised (raise {n}; {cap} revise rounds allowed) -> {nxt}")
    if last:
        log(format_objections(fx, kind, last, f"{kind} panel round {last['round']}"))
    emit(fx, **{f"fx_{kind}_next": nxt, f"fx_{kind}_raises": n})


def last_raising(fx, gate):
    """The panel round [F] forwards at a gate: among the gate's panels (spec gate: rigor, then
    intent), the latest round on the CURRENT version of the spec that had any raising voter.
    One spec version gets at most one intent round and, if that passed, one rigor round, so
    rigor-then-intent is newest-first. Without a recorded cycle (older runs) every round counts,
    and only each panel's latest round is considered, as before. Returns (kind, tally) or (None, None)."""
    order = {"spec": ("spec", "spec_intent")}[gate]
    cycle = fx.get(f"{gate}_cycle") or {}
    for kind in order:
        ts = (fx.get(f"{kind}_tallies") or [])[cycle.get(kind, 0):]
        if ts and ts[-1]["raise"]:
            return kind, ts[-1]
    return None, None


def st_forward(fx, gate):
    """Human gate option [F]: the last-raising panel round's objections (intent or rigor),
    verbatim, become the revise note — exactly what a typed note does, without retyping.
    Nothing to forward is fx_<gate>_forwarded=no, which the graph routes back to the gate."""
    kind, t = last_raising(fx, gate)
    if not t:
        latest = "; ".join(f"{NAME[k]} {tally_line(fx[f'{k}_tallies'][-1])}" for k in ("spec_intent", "spec")
                           if fx.get(f"{k}_tallies")) or "none"
        log(f"no open {gate}-gate panel objections to forward (latest rounds: {latest})")
        emit(fx, **{f"fx_{gate}_forwarded": "no"})
    text = format_objections(fx, kind, t, f"{NAME[kind].capitalize()} panel objections forwarded by the human, round {t['round']}")
    with open(f"{W}/human-note.md", "a") as fh:
        fh.write(f"## Human note at the {gate} gate ({time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}): "
                 f"address the judges' open objections below\n{text}\n\n")
    fx.setdefault("forwards", []).append({"kind": kind, "round": t["round"]})
    log(f"forwarded to the writer:\n{text}")
    emit(fx, **{f"fx_{gate}_forwarded": "yes"})


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
    fx[key] = value                       # every judge vote is already in judge_log (st_vote)
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
    log(f"deterministic spec check: {fx.get('spec_check', {}).get('result')}   "
        f"spec intent panel: {fx.get('spec_intent_judge') or 'not run on this version'}   "
        f"spec rigor panel: {fx.get('spec_judge') or 'not run on this version'}")
    for kind in ("spec_intent", "spec"):
        for t in fx.get(f"{kind}_tallies") or []:
            log(f"  {NAME[kind]} panel {tally_line(t)}" + (f" [{t['tamper']}]" if t.get("tamper") else ""))
            for e in round_votes(fx, kind, t["round"]):
                log(f"    vote {e.get('vote')}: {e['verdict']}" + (f" ({e['why']})" if e.get("why") else "")
                    + "".join(f"\n      - {r}" for r in e["reasons"]))
    notes = "\n".join(n for n in (minority_notes(fx, "spec_intent"), minority_notes(fx, "spec")) if n)
    with open(f"{W}/spec-notes.md", "w") as fh:     # the builder's prompt reads it; empty when none
        fh.write(notes)
    if notes:
        log("\n" + notes)
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
        # A new change: both build panels start a fresh round, and no earlier verdict stands.
        for k in ("conf_intent", "conf"):
            fx.pop(f"{k}_open", None)
            fx.pop(f"{k}_judge", None)
        write_packet(fx, "conf", f"DIFF-ID: {did}\nSPEC: {spec_dir(fx)}/spec.md\nBASE: {fx['base']}\n\n{diff}")
        # The change-intent packet: the idea and the code change only (the spec dir is left out —
        # this panel judges the change against what was asked, not against the spec's fine print).
        cid = intent_id(did)
        code = worktree_diff(fx["base"], exclude=spec_dir(fx) + "/")
        cpacket = (f"CHANGE-ID: {cid}\nBASE: {fx['base']}\n\n" + idea_block()
                   + f"\n===== THE CHANGE (unified diff against BASE, {spec_dir(fx)}/ left out) =====\n{code}")
        write_packet(fx, "conf_intent", cpacket)
        log(f"all gates green; change-intent packet {W}/{PACKET['conf_intent']} (CHANGE-ID {cid}), "
            f"conformance packet {W}/review.diff (DIFF-ID {did}, {len(diff)} bytes)")
        log(f"-----BEGIN CHANGE-INTENT PACKET {cid}-----\n{cpacket}\n-----END CHANGE-INTENT PACKET {cid}-----")
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
    if fx.get("spec_intent_judge") != "pass":
        hold.append(f"spec intent panel: {fx.get('spec_intent_judge') or 'missing'}")
    if fx.get("spec_judge") != "pass":
        hold.append(f"spec judge: {fx.get('spec_judge') or 'missing'}")
    g = (fx.get("gates") or {}).get("result")
    if g != "pass":
        hold.append(f"deterministic gates: {g or 'missing'}")
    if fx.get("conf_intent_judge") != "pass":
        hold.append(f"change intent panel: {fx.get('conf_intent_judge') or 'missing'}")
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
              "spec_intent_judge": fx.get("spec_intent_judge"), "conf_intent_judge": fx.get("conf_intent_judge"),
              "gate_runs": fx.get("gate_runs"), "gate_fails": fx.get("gate_fails"),
              "ci_red_rounds": fx.get("ci_red_rounds"), "required": ci.get("required"),
              "override": fx.get("override"), "factory_stage": fx.get("target_stage", 0), "profile": fx.get("profile"),
              "gate_mode": fx.get("gate_mode", "human"), "origin": fx.get("origin", "human"),
              "request": fx.get("request", ""), "spec_approval": fx.get("spec_approval", "human"),
              "panel": fx.get("panel"),
              "panels": {k: fx.get(f"{k}_tallies") or [] for k in KINDS}}
    panels = "\n".join(f"- {name}: " + ("; ".join(tally_line(t) for t in fx.get(f"{k}_tallies") or []) or "no rounds")
                       for k, name in (("spec_intent", "spec intent panel"), ("spec", "spec rigor panel"),
                                       ("conf_intent", "change intent panel"), ("conf", "conformance judge panel")))
    conf_notes = "\n".join(n.replace("## ", "**", 1).replace("\n", "**\n", 1)
                           for n in (minority_notes(fx, "conf_intent"), minority_notes(fx, "conf")) if n)
    head = "✅ **would merge**" if verdict == "would merge" else "⏸️ **hold**"
    body = "\n".join([
        VERDICT_MARKER, f"## Factory verdict: {head} · class {fx.get('class', '?')}", "",
        "Stage 0 (shadow mode): the factory never merges. This is what it *would* do; a human decides.", "",
        ("**Hold because:**\n" + "\n".join(f"- {r}" for r in reasons)) if reasons else
        "Every deterministic gate passed, all four factory judge panels passed, and every applicable review-hub validator was 5/5 clear.",
        "", "**Factory judge panels** (votes per round):", panels, "",
        *([conf_notes, ""] if conf_notes else []),
        "| review-hub validator | check | report card |", "|--|--|--|", votes, "",
        f"Class reasons: " + ("; ".join(fx.get("class_reasons") or []) or "—"),
        f"<sub>run `{fx.get('run_id')}` · gates {fx.get('gate_runs')} run(s), {fx.get('gate_fails')} failed · "
        f"CI red rounds {fx.get('ci_red_rounds')} · spec intent {fx.get('spec_intent_judge')} · spec judge {fx.get('spec_judge')}"
        f" · change intent {fx.get('conf_intent_judge')} · conformance judge {fx.get('conf_judge')}</sub>",
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
            elif cmd == "vote":
                st_vote(fx, args[0])
            elif cmd == "forward":
                st_forward(fx, args[0])
            elif cmd == "passed":
                st_passed(fx, args[0])
            elif cmd == "route":
                st_route(fx, args[0], args[1])
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
