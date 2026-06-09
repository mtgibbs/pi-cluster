#!/usr/bin/env python3
"""review-hub webhook receiver — reactive PR evaluation across all repos.

GitHub App POSTs pull_request webhooks here. We verify the HMAC, ack fast, and
in a background thread: mint a per-repo App token, run the applicable validators,
and post a Check Run (the merge gate) + a comment. No checkout — manifests are
fetched via the API. No inbound creds beyond the App; the installation id comes
from the webhook payload.

Env:
  GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY (PEM), GITHUB_WEBHOOK_SECRET   (required)
  TRIGGERABLE_JUDGE_LITELLM_KEY                                        (model auth)
  JUDGE_REPEAT=5  JUDGE_TIMEOUT=240  JUDGE_MODEL=hot-coder  PORT=8080  (tunables)
  LOG_LEVEL=INFO
"""
import hashlib
import hmac
import json
import logging
import os
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import yaml  # noqa: E402

import github_app  # noqa: E402
import triggerable_judge as tj  # noqa: E402
import validators  # noqa: E402
import reporting  # noqa: E402

logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
    stream=sys.stdout,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("review-hub")

OPTIN_FILE = ".review-hub.yml"

APP_ID = os.environ.get("GITHUB_APP_ID")
PRIVATE_KEY = os.environ.get("GITHUB_APP_PRIVATE_KEY")
WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "").encode()
REPS = int(os.environ.get("JUDGE_REPEAT", "5"))
TIMEOUT = int(os.environ.get("JUDGE_TIMEOUT", "240"))
MODEL = os.environ.get("JUDGE_MODEL", "hot-coder")
PORT = int(os.environ.get("PORT", "8080"))
CONCURRENCY = int(os.environ.get("VALIDATOR_CONCURRENCY", "4"))  # validators run in parallel
_VFILE = Path(__file__).resolve().parent / "VERSION"
VERSION = _VFILE.read_text().strip() if _VFILE.exists() else "?"
PR_ACTIONS = {"opened", "synchronize", "reopened"}


def verify_signature(sig, body):
    if not WEBHOOK_SECRET or not sig or not sig.startswith("sha256="):
        return False
    digest = hmac.new(WEBHOOK_SECRET, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest("sha256=" + digest, sig)


def read_optin(forge):
    """The validators a repo opted into, from .review-hub.yml on its DEFAULT branch.
    Read from the default branch (ref=None), NOT the PR head, so a PR can't opt
    itself out (delete the file to skip review) or in — only the merged-to-main
    subscription counts. Empty = the repo hasn't signed up, so we review nothing."""
    raw = forge.get_file(OPTIN_FILE, ref=None)
    if not raw:
        return set()
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as e:
        log.warning("%s is not valid YAML: %s", OPTIN_FILE, e)
        return set()
    return set(data.get("validators") or [])


def _run_one(forge, v, head_sha, tag):
    """One validator, end to end, in its OWN thread: own Check Run (independent in the
    pipeline view), own judging. Returns a normalized summary for the report card.
    Never raises — a crash becomes a blocking check, never a silent pass."""
    check_id = None
    t0 = time.monotonic()
    concern = getattr(v, "concern", "")
    try:
        check_id = forge.create_check_run(head_sha, name=v.name)
        raw = tempfile.mkdtemp(prefix=f"{v.name}-")
        results, any_block, body = v.review(forge, REPS, TIMEOUT, MODEL, raw)
        s = reporting.summarize(v.name, concern, results, any_block, body)
        conclusion = {"neutral": "neutral", "pass": "success", "block": "failure"}[s["state"]]
        forge.complete_check_run(check_id, conclusion,
                                 reporting.check_title(s), reporting.check_summary(s)[:60000])
        log.info("%s: %s — %s [%.0fs]", tag, v.name, s["state"].upper(), time.monotonic() - t0)
        return s
    except Exception as e:  # noqa: BLE001 — fail-safe: a crash blocks, never silently passes
        log.exception("%s: %s — crashed: %s", tag, v.name, e)
        s = reporting.error_summary(v.name, concern, e)
        if check_id is not None:
            try:
                forge.complete_check_run(check_id, "failure", reporting.check_title(s),
                                         reporting.check_summary(s)[:60000])
            except Exception:  # noqa: BLE001
                pass
        return s


def handle_pull_request(payload):
    """Background worker: token → roster → a Check Run each (in PARALLEL) → ONE report
    card. Each validator's check stays independent (the merge gate + pipeline view);
    the consolidated comment is the human-readable roster. Never raises."""
    repo = payload["repository"]["full_name"]
    pr = payload["number"]
    head_sha = payload["pull_request"]["head"]["sha"]
    install_id = payload["installation"]["id"]
    tag = f"{repo}#{pr}"

    try:
        token = github_app.installation_token(APP_ID, install_id, PRIVATE_KEY)
    except Exception as e:  # noqa: BLE001
        log.error("%s: token mint failed: %s", tag, e)
        return

    forge = tj.GitHubForge(pr, repo=repo, token=token, head_sha=head_sha)
    try:
        opted_in = read_optin(forge)
        changed = forge.changed_files()  # warms the shared file-list cache for all validators
    except Exception as e:  # noqa: BLE001
        log.error("%s: could not read PR: %s", tag, e)
        return

    if not opted_in:
        log.info("%s: no %s — repo not opted in, skipping", tag, OPTIN_FILE)
        return
    roster = validators.validators_for(repo, changed, opted_in)
    log.info("%s: opted into %s · %d changed file(s) · running %s (concurrency=%d)",
             tag, sorted(opted_in), len(changed), [v.name for v in roster] or "nothing", CONCURRENCY)
    if not roster:
        return

    # Fan out: validators run concurrently, each completing its own Check Run as it
    # finishes. The file list is already cached (warmed above), so no per-validator
    # re-fetch and no write races on the forge.
    with ThreadPoolExecutor(max_workers=min(CONCURRENCY, len(roster))) as ex:
        summaries = list(ex.map(lambda v: _run_one(forge, v, head_sha, tag), roster))

    # Barrier passed — post the ONE consolidated report card (edits in place).
    try:
        forge.upsert_comment(reporting.render_report(summaries, changed, VERSION),
                             reporting.REPORT_MARKER)
    except Exception as e:  # noqa: BLE001 — the checks are the gate; the comment is a courtesy
        log.warning("%s: could not post report card: %s", tag, e)
    blocked = [s["name"] for s in summaries if s["state"] in ("block", "error")]
    log.info("%s: done — %d/%d need review %s", tag, len(blocked), len(summaries), blocked or "")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, msg="ok"):
        body = msg.encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(200, "ok") if self.path == "/health" else self._send(404, "not found")

    def do_POST(self):
        if self.path != "/webhook":
            return self._send(404, "not found")
        body = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
        delivery = self.headers.get("X-GitHub-Delivery", "?")
        if not verify_signature(self.headers.get("X-Hub-Signature-256"), body):
            log.warning("rejected webhook: bad signature (delivery=%s)", delivery)
            return self._send(401, "bad signature")
        try:
            payload = json.loads(body or "{}")
        except json.JSONDecodeError:
            log.warning("rejected webhook: bad json (delivery=%s)", delivery)
            return self._send(400, "bad json")
        event = self.headers.get("X-GitHub-Event")
        action = payload.get("action")
        repo = (payload.get("repository") or {}).get("full_name", "?")
        if event == "pull_request" and action in PR_ACTIONS:
            log.info("→ %s/%s %s#%s — accepted, dispatching", event, action, repo,
                     payload.get("number"))
            threading.Thread(target=handle_pull_request, args=(payload,), daemon=True).start()
        else:
            log.info("· %s/%s %s — ignored", event, action, repo)
        self._send(202, "accepted")

    def log_message(self, *args):
        pass  # access logging is handled by our own structured lines


def main():
    missing = [n for n, v in (("GITHUB_APP_ID", APP_ID),
                              ("GITHUB_APP_PRIVATE_KEY", PRIVATE_KEY),
                              ("GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)) if not v]
    if missing:
        sys.exit(f"missing required env: {', '.join(missing)}")
    log.info("review-hub receiver listening on :%d · validators=%s · reps=%d model=%s",
             PORT, [v.name for v in validators.REGISTRY], REPS, MODEL)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
