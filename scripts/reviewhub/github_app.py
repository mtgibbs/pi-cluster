"""GitHub App auth — mint a short-lived installation access token.

ONE App = one identity, installed on all repos (current and future). From its
private key we mint a per-repo, 1-hour installation token ON DEMAND. No per-repo
PATs, no per-repo secrets — credentials scale with bot-roles, not repos.

The installation id comes from each webhook payload, so we don't even store it.
Needs PyJWT[crypto].
"""
import json
import time
import urllib.request

import jwt  # PyJWT

API = "https://api.github.com"


def app_jwt(app_id, private_key_pem):
    """A 10-minute RS256 JWT identifying the App (iss = app id)."""
    now = int(time.time())
    return jwt.encode(
        {"iat": now - 60, "exp": now + 600, "iss": str(app_id)},
        private_key_pem, algorithm="RS256",
    )


def installation_token(app_id, installation_id, private_key_pem):
    """Exchange the App JWT for a 1-hour token scoped to one installation."""
    token_jwt = app_jwt(app_id, private_key_pem)
    req = urllib.request.Request(
        f"{API}/app/installations/{installation_id}/access_tokens", method="POST",
        headers={"Authorization": f"Bearer {token_jwt}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())["token"]
