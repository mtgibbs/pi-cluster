#!/usr/bin/env python3
"""review-hub webhook receiver — reactive PR evaluation across all repos.

GitHub App POSTs pull_request webhooks here. We verify the HMAC, ack fast, and
in a background thread: mint a per-repo App token, run the applicable evaluators,
and post a Check Run (the merge gate) + a comment. No checkout — manifests are
fetched via the API. No inbound creds beyond the App; the installation id comes
from the webhook payload.

Env:
  GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY (PEM), GITHUB_WEBHOOK_SECRET   (required)
  TRIGGERABLE_JUDGE_LITELLM_KEY                                        (model auth)
  JUDGE_REPEAT=5  JUDGE_TIMEOUT=240  JUDGE_MODEL=hot-coder  PORT=8080  (tunables)
"""
import hashlib
import hmac
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import yaml  # noqa: E402

import github_app  # noqa: E402
import triggerable_judge as tj  # noqa: E402
import validators  # noqa: E402

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
    """The validators a repo opted into, from its .review-hub.yml. Empty = the
    repo hasn't signed up, so we review nothing (opt-in, not opt-out)."""
    raw = forge.get_file(OPTIN_FILE)
    if not raw:
        return set()
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        return set()
    return set(data.get("validators") or [])


def handle_pull_request(payload):
    """Background worker: token → roster of validators → a Check Run each. Never raises."""
    repo = payload["repository"]["full_name"]
    pr = payload["number"]
    head_sha = payload["pull_request"]["head"]["sha"]
    install_id = payload["installation"]["id"]
    try:
        token = github_app.installation_token(APP_ID, install_id, PRIVATE_KEY)
    except Exception as e:  # noqa: BLE001
        print(f"token mint failed for {repo}#{pr}: {e}", file=sys.stderr)
        return

    forge = tj.GitHubForge(pr, repo=repo, token=token, head_sha=head_sha)
    try:
        opted_in = read_optin(forge)
        changed = forge.changed_files()
    except Exception as e:  # noqa: BLE001
        print(f"could not read {repo}#{pr}: {e}", file=sys.stderr)
        return
    if not opted_in:
        print(f"{repo}#{pr}: no {OPTIN_FILE} — repo not opted in, skipping", file=sys.stderr)
        return
    roster = validators.validators_for(repo, changed, opted_in)
    if not roster:
        print(f"{repo}#{pr}: opted into {sorted(opted_in)} but none apply to these changes",
              file=sys.stderr)
        return

    for v in roster:
        check_id = None
        try:
            check_id = forge.create_check_run(head_sha, name=v.name)
            raw = tempfile.mkdtemp(prefix=f"{v.name}-")
            results, any_block, body = v.review(forge, REPS, TIMEOUT, MODEL, raw)
            if body is None:
                forge.complete_check_run(check_id, "neutral",
                                         "No applicable changes", "Nothing to review.")
                continue
            forge.post_review(body, any_block)
            forge.complete_check_run(
                check_id,
                "failure" if any_block else "success",
                "Human review required" if any_block else "All clear",
                body[:60000])
            print(f"{repo}#{pr} {v.name}: {'BLOCK' if any_block else 'pass'}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001 — fail-safe: a crash blocks, never silently passes
            print(f"{v.name} errored on {repo}#{pr}: {e}", file=sys.stderr)
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
        if not verify_signature(self.headers.get("X-Hub-Signature-256"), body):
            return self._send(401, "bad signature")
        try:
            payload = json.loads(body or "{}")
        except json.JSONDecodeError:
            return self._send(400, "bad json")
        if (self.headers.get("X-GitHub-Event") == "pull_request"
                and payload.get("action") in PR_ACTIONS):
            threading.Thread(target=handle_pull_request, args=(payload,), daemon=True).start()
        self._send(202, "accepted")

    def log_message(self, *args):
        pass  # quiet; we log our own lines


def main():
    missing = [n for n, v in (("GITHUB_APP_ID", APP_ID),
                              ("GITHUB_APP_PRIVATE_KEY", PRIVATE_KEY),
                              ("GITHUB_WEBHOOK_SECRET", WEBHOOK_SECRET)) if not v]
    if missing:
        sys.exit(f"missing required env: {', '.join(missing)}")
    print(f"review-hub receiver listening on :{PORT}", file=sys.stderr)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
