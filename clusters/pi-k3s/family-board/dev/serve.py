#!/usr/bin/env python3
"""Local preview server for the Family Board — no cluster required.

Serves the static board from the parent dir AND mocks the same-origin
`/api/feed` endpoint with dev/feed.sample.json, so the renderer behaves
exactly as it does in production (where nginx proxies /api/feed -> n8n).

    python3 dev/serve.py            # -> http://localhost:8000
    python3 dev/serve.py 9000       # custom port
    FEED=dev/other.json python3 dev/serve.py   # swap the fixture

Edit dev/feed.sample.json to design against different data shapes.
"""
import http.server
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED = os.environ.get("FEED", os.path.join(ROOT, "dev", "feed.sample.json"))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/feed":
            try:
                with open(FEED, "rb") as fh:
                    body = fh.read()
            except FileNotFoundError:
                self.send_error(500, f"fixture not found: {FEED}")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


if __name__ == "__main__":
    print(f"Family Board dev server: http://localhost:{PORT}")
    print(f"  serving: {ROOT}")
    print(f"  /api/feed -> {FEED}")
    http.server.HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
