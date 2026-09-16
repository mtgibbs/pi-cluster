"""mitmdump addon — capture the Canvas mobile-OAuth API token off the iOS app login.

Fulton disabled manual access-token creation, so the only way to mint a Canvas API
token is the iOS app's OAuth flow. Run this under mitmdump while the Canvas Parent app
logs in (via Account → QR for Mobile Login), and it writes the resulting API token to a
capture dir OUTSIDE this repo. Full runbook: docs/canvas-ingestion.md § "Rotating the
token (mobile OAuth capture)".

    mitmdump --listen-host 0.0.0.0 --listen-port 8080 -s scripts/canvas/grab_token.py

Outputs (in $CANVAS_CAPTURE_DIR, default <tempdir>/canvas-capture):
  - api_token.txt        the API access_token — USE THIS ONE (~70 chars)
  - oauth_response.json  the full /login/oauth2/token response (has refresh_token, user)
  - hosts_seen.txt       every host that traversed the proxy (diagnostic)

Prefer api_token.txt. A plain `Authorization: Bearer` header captured off a later request
can be a different, sso-scoped JWT that 401s against the API — so once the OAuth exchange
is seen, its access_token wins and later Bearers never overwrite it.

The capture dir holds live secrets: keep it off the repo, and shred it once the token is
in 1Password + the n8n `canvas-api` credential.
"""
import json, os, pathlib, tempfile

CAP = pathlib.Path(os.environ.get("CANVAS_CAPTURE_DIR", pathlib.Path(tempfile.gettempdir()) / "canvas-capture"))
CAP.mkdir(parents=True, exist_ok=True)
API   = CAP / "api_token.txt"
OAUTH = CAP / "oauth_response.json"
HOSTS = CAP / "hosts_seen.txt"

_hosts = set()
_have_oauth_token = False   # once the authoritative OAuth token lands, don't let a stray Bearer clobber it


def _redact(t):
    return f"{t[:6]}…{t[-4:]} (len {len(t)})" if t else "(empty)"


def _note_host(h):
    if h not in _hosts:
        _hosts.add(h)
        HOSTS.write_text("\n".join(sorted(_hosts)) + "\n")


def response(flow):
    # The authoritative source: the OAuth exchange itself returns {"access_token": ...}.
    global _have_oauth_token
    if "oauth2/token" in flow.request.path:
        try:
            data = json.loads(flow.response.get_text())
        except Exception:
            return
        if "access_token" in data:
            OAUTH.write_text(json.dumps(data, indent=2))
            API.write_text(data["access_token"])
            _have_oauth_token = True
            print(f"[grab] access_token from {flow.request.pretty_host} oauth -> {_redact(data['access_token'])} -> {API}")


def request(flow):
    # Fallback only — a Bearer seen on an API request, used ONLY if the OAuth exchange
    # was never captured (e.g. the app reused a cached token and never re-exchanged).
    _note_host(flow.request.pretty_host)
    if _have_oauth_token:
        return
    auth = flow.request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        tok = auth.split(" ", 1)[1].strip()
        canvasy = any(c in flow.request.pretty_host for c in ("instructure.com", "canvaslms.com"))
        if tok and canvasy:
            API.write_text(tok)
            print(f"[grab] fallback Bearer on {flow.request.pretty_host}{flow.request.path[:30]} -> {_redact(tok)} "
                  f"(verify against /users/self/observees — may be sso-scoped)")
