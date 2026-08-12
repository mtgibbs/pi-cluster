#!/usr/bin/env python3
"""
Fixture server for specs/model-watch — a stand-in HuggingFace Hub.

Mirrors the real route shapes so the implementation needs no test-only code path:
  GET /api/models?...                     -> the sweep list (safetensors is null, as HF really returns)
  GET /api/models/{org}/{name}            -> per-model detail (safetensors.total, config, cardData)
  GET /{org}/{name}/raw/main/README.md    -> the model card

Every requested path is appended to $REQ_LOG, so verify.sh can assert on BEHAVIOUR —
e.g. that model cards were actually fetched — rather than grepping for code that
looks like it fetches them. (Run 2 shipped a card fetcher that always threw; it
grepped fine and was dead code.)

Usage: PORT=8765 REQ_LOG=/tmp/req.log python3 fixture_server.py
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
REQ_LOG = os.environ.get("REQ_LOG", "/tmp/model-watch-requests.log")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):        # keep verify output clean
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        with open(REQ_LOG, "a") as f:
            f.write(path + "\n")

        if path == "/api/models":
            body = open(os.path.join(FIX, "api", "models.json"), "rb").read()
            return self._send(200, body, "application/json")

        if path.startswith("/api/models/"):
            slug = path[len("/api/models/"):].strip("/").replace("/", "__")
            fp = os.path.join(FIX, "api", "models", slug + ".json")
            if os.path.exists(fp):
                return self._send(200, open(fp, "rb").read(), "application/json")
            return self._send(404, b'{"error":"not found"}', "application/json")

        if path.endswith("/raw/main/README.md"):
            slug = path[1:-len("/raw/main/README.md")].replace("/", "__")
            fp = os.path.join(FIX, "raw", slug + ".md")
            if os.path.exists(fp):
                return self._send(200, open(fp, "rb").read(), "text/plain")
            return self._send(404, b"not found", "text/plain")

        return self._send(404, b"not found", "text/plain")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8765"))
    open(REQ_LOG, "w").close()
    srv = HTTPServer(("127.0.0.1", port), Handler)
    sys.stderr.write(f"fixture server on 127.0.0.1:{port}\n")
    sys.stderr.flush()
    srv.serve_forever()
