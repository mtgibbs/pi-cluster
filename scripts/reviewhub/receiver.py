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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import yaml  # noqa: E402

import github_app  # noqa: E402
import triggerable_judge as tj  # noqa: E402
import validators  # noqa: E402

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


def handle_pull_request(payload):
    """Background worker: token → roster of validators → a Check Run each. Never raises."""
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
        changed = forge.changed_files()
    except Exception as e:  # noqa: BLE001
        log.error("%s: could not read PR: %s", tag, e)
        return

    if not opted_in:
        log.info("%s: no %s — repo not opted in, skipping", tag, OPTIN_FILE)
        return
    roster = validators.validators_for(repo, changed, opted_in)
    log.info("%s: opted into %s · %d changed file(s) · running %s",
             tag, sorted(opted_in), len(changed), [v.name for v in roster] or "nothing")
    if not roster:
        return

    for v in roster:
        check_id = None
        t0 = time.monotonic()
        try:
            check_id = forge.create_check_run(head_sha, name=v.name)
            log.info("%s: %s — check created, judging (reps=%d)…", tag, v.name, REPS)
            raw = tempfile.mkdtemp(prefix=f"{v.name}-")
            results, any_block, body = v.review(forge, REPS, TIMEOUT, MODEL, raw)
            dt = time.monotonic() - t0
            if body is None:
                forge.complete_check_run(check_id, "neutral",
                                         "No applicable changes", "Nothing to review.")
                log.info("%s: %s — neutral, no applicable targets [%.0fs]", tag, v.name, dt)
                continue
            forge.post_review(body, any_block)
            forge.complete_check_run(
                check_id,
                "failure" if any_block else "success",
                "Human review required" if any_block else "All clear",
                body[:60000])
            verdicts = ", ".join(f"{r.get('ref') or r.get('path')}={r['verdict']}" for r in results)
            log.info("%s: %s — %s [%.0fs]  %s", tag, v.name,
                     "BLOCK" if any_block else "PASS", dt, verdicts)
        except Exception as e:  # noqa: BLE001 — fail-safe: a crash blocks, never silently passes
            log.exception("%s: %s — crashed, posting a blocking check: %s", tag, v.name, e)
            if check_id is not None:
                try:
                    forge.complete_check_run(check_id, "failure", "Validator error",
                                             f"The validator crashed — a human must review.\n\n```\n{e}\n```")
                except Exception:  # noqa: BLE001
                    pass


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
