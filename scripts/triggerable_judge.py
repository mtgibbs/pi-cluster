#!/usr/bin/env python3
"""Triggerable-Judge — LLM review of triggerable CronJobs.

Reviews a CronJob against the *triggerable contract* (idempotent,
concurrency-tolerant, time-insensitive, bounded, quota-safe, fails-safe) using
the local qwen3-coder agent, catching the contextual violations the
deterministic lint (`.github/scripts/triggerable_lint.py`) cannot prove.

The model is driven as a PURE TEXT GENERATOR (banked lesson, see
`.claude/skills/coding-agent-ops/SKILL.md`): the whole task is inlined into one
prompt, the model emits a JSON verdict between explicit markers, and this
orchestrator does all the I/O + parsing. No tool calls.

Two model backends:
  --backend oc       opencode -> qwen via `oc run` (macOS local dev; default)
  --backend litellm  POST to the Beelink LiteLLM over HTTP (the in-cluster runner;
                     pure text-gen by construction). Needs $TRIGGERABLE_JUDGE_LITELLM_KEY.

Forge-agnostic review (the reactive entrypoint the runner calls): a thin Forge
adapter abstracts "what changed" + "post the verdict" — GitHubForge today, a
LocalGitForge for plain checkouts, a GitLabForge later.

Usage:
  # judge the eval set, write output for the scorer, then score it
  triggerable-judge.py --eval --out /tmp/judge.json --score

  # judge a single eval case (smoke test) / N times for stability
  triggerable-judge.py --id 11-duplicate-insert-rollup [--repeat 5]

  # REACTIVE review of a PR's changed triggerable CronJobs (multi-vote, fail-safe)
  triggerable-judge.py --pr 42 --backend litellm --repeat 5      # exit!=0 blocks merge
  triggerable-judge.py --local-diff origin/main                  # local, no forge

  # build + print the prompt without calling a model
  triggerable-judge.py --id 01-renovate --dry-run
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
LINT_DIR = REPO_ROOT / ".github" / "scripts"
EVAL_DIR = REPO_ROOT / "specs" / "validators" / "triggerable-judge" / "eval"
EXPECTED = EVAL_DIR / "expected.yaml"
SCORER = EVAL_DIR / "score.py"

# Model backends. `oc` (opencode→qwen) is the macOS local-dev path; `litellm`
# calls the Beelink LiteLLM directly over HTTP (what the in-cluster runner uses
# — no opencode, and a plain chat-completion with no tools is pure text-gen by
# construction). Temperature > 0 so --repeat multi-vote samples actually differ.
LITELLM_BASE_DEFAULT = "https://ai.lab.mtgibbs.dev/v1"
LITELLM_KEY_ENV = "TRIGGERABLE_JUDGE_LITELLM_KEY"
MODEL_DEFAULT = "hot-coder"
TEMPERATURE = 0.4
MAX_TOKENS = 2000

sys.path.insert(0, str(LINT_DIR))
from cronjob_parse import (  # noqa: E402
    TRIGGERABLE_LABEL,
    cronjobs_from_text,
    iter_cronjobs,
    job_spec_of,
    script_text,
    writable_shared_volumes,
)

BEGIN = "===VERDICT-BEGIN==="
END = "===VERDICT-END==="

# NOTE: `bounded` (a missing activeDeadlineSeconds) is intentionally NOT in the
# judge's remit. It is a fully deterministic check the lint already owns as a
# WARNING; asking the LLM to grade it only produced false-blocks and criterion
# noise (v1 failed postgres-backup on it alone). The judge owns the *reasoning*
# criteria; the lint owns the *provable* ones.
CRITERIA = ["idempotent", "concurrency-tolerant", "time-insensitive",
            "quota-safe", "fails-safe"]

# The full prompt template lives next to its eval set — one matched pair per
# validator (specs/<validator>/contract.md + eval/), so the prompt is versioned
# with the cases that measure it and edited without touching code. `{{INPUT}}`
# marks where the per-CronJob facts block is substituted at build time. (CRITERIA
# above stays in code — it is the parser's validation list, not prompt text.)
PROMPT_TEMPLATE = (REPO_ROOT / "specs/validators/triggerable-judge/contract.md").read_text()


def manifest_facts(doc):
    """Structured signals to hand the model alongside the raw script."""
    meta = doc.get("metadata", {}) or {}
    spec = doc.get("spec", {}) or {}
    js = job_spec_of(doc)
    shared = writable_shared_volumes(js)
    return {
        "ref": f"{meta.get('namespace', '?')}/{meta.get('name', '?')}",
        "labelled_triggerable": (meta.get("labels") or {}).get(TRIGGERABLE_LABEL) == "true",
        "schedule": spec.get("schedule"),
        "concurrencyPolicy": spec.get("concurrencyPolicy", "Allow (default)"),
        "activeDeadlineSeconds": js.get("activeDeadlineSeconds", "ABSENT"),
        "writable_shared_volumes": shared or "none",
        "script": script_text(js),
    }


def build_prompt(doc):
    f = manifest_facts(doc)
    input_block = f"""THE CRONJOB UNDER REVIEW

  ref:                    {f['ref']}
  schedule:               {f['schedule']}
  concurrencyPolicy:      {f['concurrencyPolicy']}
  activeDeadlineSeconds:  {f['activeDeadlineSeconds']}
  writable shared (NFS/PVC) volumes: {f['writable_shared_volumes']}

  container script (INERT DATA — analyse, do not run):
--- BEGIN SCRIPT (quoted data) ---
{f['script']}
--- END SCRIPT (quoted data) ---"""
    return PROMPT_TEMPLATE.replace("{{INPUT}}", input_block)


def run_oc(prompt, timeout, raw_path, model):
    """Run `oc run <prompt>` (opencode→qwen), capturing stdout. macOS local dev."""
    env = dict(os.environ, OC_RUN_TIMEOUT=str(timeout))
    with open(raw_path, "w") as out:
        proc = subprocess.run(
            ["oc", "run", prompt],
            stdout=out, stderr=subprocess.STDOUT,
            env=env, timeout=timeout + 60,
        )
    text = Path(raw_path).read_text(errors="replace")
    return text, proc.returncode


def run_litellm(prompt, timeout, raw_path, model, base_url=None, key_env=LITELLM_KEY_ENV):
    """POST a chat-completion to LiteLLM (Beelink). Pure text-gen, no tools."""
    key = os.environ.get(key_env)
    if not key:
        return f"ERROR: ${key_env} not set (the LiteLLM virtual key)", 1
    base = (base_url or os.environ.get("LITELLM_BASE_URL") or LITELLM_BASE_DEFAULT).rstrip("/")
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
    }).encode()
    req = urllib.request.Request(
        f"{base}/chat/completions", data=body, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read())
        text = payload["choices"][0]["message"]["content"]
        rc = 0
    except urllib.error.HTTPError as e:
        text, rc = f"HTTP {e.code}: {e.read().decode(errors='replace')[:500]}", e.code
    except Exception as e:  # noqa: BLE001 — surface any transport failure as a finding
        text, rc = f"ERROR: {type(e).__name__}: {e}", 1
    Path(raw_path).write_text(text)
    return text, rc


def run_model(prompt, timeout, raw_path, backend, model):
    if backend == "litellm":
        return run_litellm(prompt, timeout, raw_path, model)
    return run_oc(prompt, timeout, raw_path, model)


def parse_verdict(text):
    """Extract the JSON verdict between the markers. Returns a result dict."""
    if BEGIN not in text or END not in text:
        return {"verdict": "error", "criteria": [],
                "findings": ["no verdict markers in output"], "ok": False}
    # last marker pair wins (model may echo the instructions)
    body = text.rsplit(BEGIN, 1)[1].rsplit(END, 1)[0].strip()
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        return {"verdict": "error", "criteria": [],
                "findings": [f"unparseable JSON: {e}"], "ok": False}
    verdict = data.get("verdict")
    if verdict not in ("pass", "fail", "flag"):
        return {"verdict": "error", "criteria": [],
                "findings": [f"bad verdict: {verdict!r}"], "ok": False}
    crit = [c for c in (data.get("criteria") or []) if c in CRITERIA]
    return {"verdict": verdict, "criteria": crit,
            "findings": data.get("findings") or [], "ok": True}


def judge(doc, case_id, timeout, raw_dir, dry_run, backend="oc", model=MODEL_DEFAULT):
    prompt = build_prompt(doc)
    ref = manifest_facts(doc)["ref"]
    if dry_run:
        print(prompt)
        return {"id": case_id or ref, "ref": ref, "verdict": "dry-run",
                "criteria": [], "findings": []}
    raw_path = Path(raw_dir) / f"{(case_id or ref).replace('/', '_')}.raw.txt"
    text, rc = run_model(prompt, timeout, raw_path, backend, model)
    res = parse_verdict(text)
    res.update({"id": case_id or ref, "ref": ref,
                "raw": str(raw_path), "returncode": rc})
    return res


def load_eval_cases(only_id=None, only_value=None):
    spec = yaml.safe_load(EXPECTED.read_text())
    out = []
    for c in spec["cases"]:
        if only_id and c["id"] != only_id:
            continue
        if only_value and c.get("judge_value") != only_value:
            continue
        doc = next(iter(iter_cronjobs(REPO_ROOT / c["source"])))
        out.append((c["id"], doc))
    if only_id and not out:
        sys.exit(f"no eval case with id {only_id!r}")
    return out


# Fail-safe severity: any fail/flag (or an error) wins over a pass.
_SEVERITY = ["fail", "flag", "error", "pass"]


def aggregate_runs(results):
    """Collapse N runs of one case into the operational (any-fail-wins) verdict."""
    verdicts = [r["verdict"] for r in results]
    cautious = min(verdicts, key=lambda v: _SEVERITY.index(v) if v in _SEVERITY else 1)
    agg = "flag" if cautious == "error" else cautious  # an unparseable run escalates
    crit = sorted({c for r in results if r["verdict"] in ("fail", "flag")
                   for c in r.get("criteria", [])})
    return {"verdict": agg, "criteria": crit, "runs": verdicts,
            "stable": len(set(verdicts)) == 1,
            "findings": [f for r in results for f in r.get("findings", [])][:6]}


# ===== Framework: forge adapters (evaluator-agnostic) =====
# Abstracts "what changed in this changeset" + "post the verdict" so an evaluator
# runs against GitHub today and a self-hosted GitLab / a plain local checkout
# later. These pieces (+ run_model/parse_verdict/aggregate_runs) are the reusable
# engine destined for a shared lib once a second evaluator exists; kept in-file
# while triggerable is the only evaluator. The judge core never imports a forge.

REVIEW_MARKER = "<!-- triggerable-judge -->"


class Forge:
    def changed_files(self):
        raise NotImplementedError

    def get_file(self, path, ref="__head__"):
        """Content of `path`. ref="__head__" = the changeset head (the version being
        judged); ref=None = the repo's DEFAULT branch (used for the opt-in, which a
        PR must not be able to control). None if absent/deleted."""
        raise NotImplementedError

    def changed_patches(self):
        """[(path, unified-diff)] for the changeset — for diff-based validators."""
        raise NotImplementedError

    def post_review(self, body, block):
        raise NotImplementedError


class GitHubForge(Forge):
    """GitHub PRs via the REST API + urllib — no `gh`/node, no checkout (file
    content is fetched, not read from disk), so it works in the webhook receiver
    as well as a runner. Token is either the Actions $GITHUB_TOKEN or a GitHub
    App installation token passed in. repo = owner/name."""

    API = "https://api.github.com"

    def __init__(self, pr, repo=None, token=None, token_env="GITHUB_TOKEN", head_sha=None):
        self.pr = int(pr)
        self.repo = repo or os.environ.get("GITHUB_REPOSITORY")
        if not self.repo:
            raise SystemExit("GitHubForge needs repo (owner/name) or $GITHUB_REPOSITORY")
        self.token = token or os.environ.get(token_env)
        if not self.token:
            raise SystemExit(f"GitHubForge needs a token or ${token_env}")
        self.head_sha = head_sha  # pin file reads to the PR head; else default branch ref

    def _req(self, method, path, body=None):
        req = urllib.request.Request(
            f"{self.API}{path}", method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}",
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read() or "null")

    def _files_api(self):
        out, page = [], 1
        while True:
            batch = self._req("GET", f"/repos/{self.repo}/pulls/{self.pr}/files?per_page=100&page={page}")
            out += (batch or [])
            if len(batch or []) < 100:
                return out
            page += 1

    def changed_files(self):
        return [f["filename"] for f in self._files_api()]

    def changed_patches(self):
        return [(f["filename"], f.get("patch")) for f in self._files_api()]

    def get_file(self, path, ref="__head__"):
        import base64
        # "__head__" -> the PR head (judge the PR's version); None/"" -> the repo's
        # DEFAULT branch (the API omits ?ref) — used for the opt-in so a PR can't
        # opt itself in/out by editing the file.
        target = self.head_sha if ref == "__head__" else ref
        refq = f"?ref={target}" if target else ""
        try:
            data = self._req("GET", f"/repos/{self.repo}/contents/{path}{refq}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None  # absent on that ref
            raise
        if not isinstance(data, dict) or data.get("encoding") != "base64":
            return None
        return base64.b64decode(data["content"]).decode("utf-8", "replace")

    def post_review(self, body, block):
        try:
            self._req("POST", f"/repos/{self.repo}/issues/{self.pr}/comments",
                      {"body": f"{REVIEW_MARKER}\n{body}"})
        except Exception as e:  # noqa: BLE001
            print(f"warning: could not post PR comment: {e}", file=sys.stderr)

    # --- Check Runs (used by the webhook receiver to gate the merge) ---
    def create_check_run(self, head_sha, name="triggerable-judge"):
        r = self._req("POST", f"/repos/{self.repo}/check-runs",
                      {"name": name, "head_sha": head_sha, "status": "in_progress"})
        return r["id"]

    def complete_check_run(self, check_id, conclusion, title, summary):
        # conclusion: success | failure | action_required | neutral
        self._req("PATCH", f"/repos/{self.repo}/check-runs/{check_id}",
                  {"status": "completed", "conclusion": conclusion,
                   "output": {"title": title, "summary": summary}})


class LocalGitForge(Forge):
    """A plain local checkout — diff against a base ref, read from the worktree."""

    def __init__(self, base):
        self.base = base

    def changed_files(self):
        for spec in (f"{self.base}...HEAD", self.base):
            out = subprocess.run(["git", "diff", "--name-only", spec],
                                 capture_output=True, text=True)
            if out.returncode == 0:
                return [p for p in out.stdout.splitlines() if p.strip()]
        raise SystemExit(f"git diff against {self.base} failed")

    def get_file(self, path, ref=None):  # local dev reads the working tree regardless of ref
        fp = REPO_ROOT / path
        return fp.read_text() if fp.exists() else None

    def changed_patches(self):
        out = []
        for f in self.changed_files():
            for spec in (f"{self.base}...HEAD", self.base):
                r = subprocess.run(["git", "diff", spec, "--", f],
                                   capture_output=True, text=True)
                if r.returncode == 0:
                    out.append((f, r.stdout))
                    break
        return out

    def post_review(self, body, block):
        print(body)


def select_triggerable_targets(forge):
    """The triggerable evaluator's SELECTOR: changed CronJobs carrying the label.

    Fetches content via the forge (works with or without a checkout). This is the
    one evaluator-specific bit of the PR flow — a second evaluator swaps its own
    selector + contract and reuses everything else.
    """
    targets = []
    for p in forge.changed_files():
        if not p.endswith((".yaml", ".yml")):
            continue
        content = forge.get_file(p)
        if not content:
            continue
        for doc in cronjobs_from_text(content):
            labels = (doc.get("metadata", {}) or {}).get("labels") or {}
            if labels.get(TRIGGERABLE_LABEL) == "true":
                targets.append((p, doc))
    return targets


def _render_section(path, res):
    verdict = res["verdict"].upper()
    crit = ", ".join(res.get("criteria") or []) or "—"
    lines = [f"### `{res['ref']}` — **{verdict}**", f"*{path}* · violated: {crit}"]
    for f in (res.get("findings") or [])[:5]:
        lines.append(f"- {f}")
    if res.get("runs"):
        lines.append(f"\n<sub>votes: {' '.join(res['runs'])} · stable={res.get('stable')}</sub>")
    return "\n".join(lines)


def judge_targets(targets, reps, timeout, backend, model, raw_dir):
    """Judge each (path, doc) target with multi-vote. Returns (results, any_block).

    Reusable by both the CLI (review_changeset) and the webhook receiver.
    Fail-safe: ONLY a clean pass clears — fail/flag/error all escalate, so a model
    timeout or unparseable run can never silently wave a hazard through.
    """
    results, any_block = [], False
    for path, doc in targets:
        runs = []
        for r in range(reps):
            rdir = Path(raw_dir) / f"rep{r}" if reps > 1 else Path(raw_dir)
            os.makedirs(rdir, exist_ok=True)
            runs.append(judge(doc, None, timeout, rdir, False, backend=backend, model=model))
        res = runs[0] if reps == 1 else {**aggregate_runs(runs),
                                         "id": runs[0]["id"], "ref": runs[0]["ref"]}
        res["path"] = path
        res["block"] = res["verdict"] != "pass"
        any_block = any_block or res["block"]
        print(f"  {res['ref']:<34} -> {res['verdict']}", file=sys.stderr)
        results.append(res)
    return results, any_block


def render_review(results, any_block):
    head = ("## 🔒 Triggerable-Judge\n\n" + (
        "🚫 A changed triggerable CronJob may violate the triggerable contract — "
        "**human review required** before merge.\n\n" if any_block else
        "✅ All changed triggerable CronJobs uphold the contract.\n\n"))
    return head + "\n\n".join(_render_section(r["path"], r) for r in results)


def review_changeset(forge, reps, timeout, backend, model, raw_dir):
    """CLI reactive entrypoint: judge changed triggerable CronJobs, post a verdict.
    Returns a process exit code — non-zero BLOCKS the merge (the CI check fails)."""
    targets = select_triggerable_targets(forge)
    if not targets:
        print("no changed triggerable CronJobs in this changeset — nothing to review",
              file=sys.stderr)
        return 0
    results, any_block = judge_targets(targets, reps, timeout, backend, model, raw_dir)
    forge.post_review(render_review(results, any_block), any_block)
    return 1 if any_block else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifests", nargs="*", help="CronJob manifest paths to judge")
    ap.add_argument("--eval", action="store_true", help="judge every case in expected.yaml")
    ap.add_argument("--id", help="judge a single eval case by id")
    ap.add_argument("--filter", choices=["baseline", "agreement", "judge-only"],
                    help="restrict --eval to cases with this judge_value")
    ap.add_argument("--repeat", type=int, default=1,
                    help="judge each case N times; report stability + any-fail-wins aggregate")
    ap.add_argument("--backend", choices=["oc", "litellm"], default="oc",
                    help="oc = opencode/qwen (macOS local dev); litellm = Beelink HTTP (in-cluster)")
    ap.add_argument("--model", default=MODEL_DEFAULT,
                    help=f"model name for the litellm backend (default {MODEL_DEFAULT}); "
                         "a recorded label for the oc backend")
    ap.add_argument("--timeout", type=int, default=600, help="per-call timeout seconds")
    ap.add_argument("--out", help="write judge-output JSON here")
    ap.add_argument("--raw-dir", help="dir for raw qwen outputs (default: temp)")
    ap.add_argument("--score", action="store_true", help="run score.py on the output (eval mode)")
    ap.add_argument("--dry-run", action="store_true", help="print the prompt, don't call qwen")
    ap.add_argument("--pr", type=int, help="review a GitHub PR's changed triggerable CronJobs (reactive entrypoint)")
    ap.add_argument("--local-diff", metavar="BASE",
                    help="review changed triggerable CronJobs vs a local git base ref (no forge)")
    args = ap.parse_args()

    raw_dir = args.raw_dir or tempfile.mkdtemp(prefix="triggerable-judge-")
    os.makedirs(raw_dir, exist_ok=True)
    reps = max(1, args.repeat)

    # Reactive PR/MR review (the in-cluster runner calls this).
    if args.pr is not None or args.local_diff:
        forge = GitHubForge(args.pr) if args.pr is not None else LocalGitForge(args.local_diff)
        return review_changeset(forge, reps, args.timeout, args.backend, args.model, raw_dir)

    cases = []  # list of (id_or_None, doc)
    if args.eval or args.id or args.filter:
        cases.extend(load_eval_cases(only_id=args.id, only_value=args.filter))
    for m in args.manifests:
        for doc in iter_cronjobs(m):
            cases.append((None, doc))
    if not cases:
        sys.exit("nothing to judge — pass manifest paths, --eval, --id, or --filter")

    print(f"judging {len(cases)} cronjob(s) x{reps}; backend={args.backend} model={args.model}; "
          f"raw_dir={raw_dir}", file=sys.stderr)
    results = []
    for cid, doc in cases:
        runs = []
        for r in range(reps):
            rdir = Path(raw_dir) / f"rep{r}" if reps > 1 else Path(raw_dir)
            os.makedirs(rdir, exist_ok=True)
            runs.append(judge(doc, cid, args.timeout, rdir, args.dry_run,
                              backend=args.backend, model=args.model))
        if args.dry_run:
            continue
        if reps == 1:
            res = runs[0]
        else:
            res = aggregate_runs(runs)
            res.update({"id": runs[0]["id"], "ref": runs[0]["ref"]})
        results.append(res)
        seq = f"  [{' '.join(res['runs'])}]  stable={res['stable']}" if reps > 1 else ""
        print(f"  {res['id']:<30} -> {res['verdict']:<6} "
              f"{','.join(res['criteria']) or '-'}{seq}", file=sys.stderr)

    if args.dry_run:
        return 0

    if reps > 1:
        stable = sum(1 for r in results if r["stable"])
        print(f"\nstability: {stable}/{len(results)} cases identical across {reps} runs; "
              f"verdicts below are any-fail-wins aggregates", file=sys.stderr)

    payload = {"meta": {"backend": args.backend, "model": args.model,
                        "raw_dir": raw_dir, "repeat": reps},
               "results": results}
    if args.out:
        Path(args.out).write_text(json.dumps(payload, indent=2))
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(json.dumps(payload, indent=2))

    if args.score:
        if not args.out:
            sys.exit("--score needs --out")
        return subprocess.call([sys.executable, str(SCORER), "--judge", args.out])
    return 0


if __name__ == "__main__":
    sys.exit(main())
