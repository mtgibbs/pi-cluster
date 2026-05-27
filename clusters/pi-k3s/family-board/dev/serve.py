#!/usr/bin/env python3
"""Local preview server for the Family Board — no cluster required.

Serves the static board from the parent dir AND mocks the same-origin board API
so the renderer behaves exactly as it does in production (where nginx proxies
these paths to n8n, injecting the auth token):

  GET  /api/feed              -> dev/feed.sample.json, with `acks` injected per item
  POST /api/ack   {item_id,person}   -> toggles an in-memory ack, returns {seen}
  POST /api/menu  {action,...}        -> in-memory board_menu CRUD (list/add/edit/toggle/delete)

In-memory state resets when you restart the server — it stands in for the n8n
Postgres tables (board_acks / board_menu). Edit dev/feed.sample.json to design
against different data shapes.

    python3 dev/serve.py            # -> http://localhost:8000
    python3 dev/serve.py 9000       # custom port
    FEED=dev/other.json python3 dev/serve.py   # swap the fixture
"""
import http.server
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED = os.environ.get("FEED", os.path.join(ROOT, "dev", "feed.sample.json"))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

# --- in-memory stand-ins for the n8n Postgres tables --------------------------
ACKS = {}            # item_id (int) -> set(person)
MENU = [             # board_menu rows; seeded so the widget looks alive
    {"id": 1, "meal": "Sheet-Pan Chicken Fajitas", "recipe_url": "https://www.paprikarecipes.com/", "eaten": True},
    {"id": 2, "meal": "Spaghetti & Meatballs", "recipe_url": "", "eaten": True},
    {"id": 3, "meal": "Taco Tuesday", "recipe_url": "", "eaten": False},
    {"id": 4, "meal": "Lemon Herb Salmon", "recipe_url": "https://www.paprikarecipes.com/", "eaten": False},
    {"id": 5, "meal": "Breakfast for Dinner", "recipe_url": "", "eaten": False},
]
_next_menu_id = [6]
PEOPLE = {"julia", "matt", "ronin", "rory"}


def _feed_with_acks():
    with open(FEED, "rb") as fh:
        items = json.load(fh)
    for it in items:
        it["acks"] = sorted(ACKS.get(it.get("id"), set()))
    return items


def _toggle_ack(item_id, person):
    s = ACKS.setdefault(item_id, set())
    if person in s:
        s.discard(person)
        seen = False
    else:
        s.add(person)
        seen = True
    if not s:
        ACKS.pop(item_id, None)
    return {"item_id": item_id, "person": person, "seen": seen}


def _menu(action, body):
    global MENU
    if action == "list":
        return MENU
    if action == "add":
        row = {"id": _next_menu_id[0], "meal": body.get("meal", ""),
               "recipe_url": body.get("recipe_url", ""), "eaten": False}
        _next_menu_id[0] += 1
        MENU.append(row)
        return [row]
    rid = body.get("id")
    row = next((m for m in MENU if str(m["id"]) == str(rid)), None)
    if action == "edit" and row:
        if body.get("meal"):
            row["meal"] = body["meal"]
        row["recipe_url"] = body.get("recipe_url", "")
        return [row]
    if action == "toggle" and row:
        row["eaten"] = not row["eaten"]
        return [row]
    if action == "delete" and row:
        MENU = [m for m in MENU if str(m["id"]) != str(rid)]
        return [{"id": rid}]
    return []


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return {}

    def do_GET(self):
        if self.path.split("?")[0] == "/api/feed":
            try:
                return self._json(_feed_with_acks())
            except FileNotFoundError:
                return self.send_error(500, f"fixture not found: {FEED}")
        return super().do_GET()

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/ack":
            b = self._read_body()
            return self._json(_toggle_ack(b.get("item_id"), b.get("person")))
        if path == "/api/menu":
            b = self._read_body()
            return self._json(_menu(b.get("action", "list"), b))
        return self.send_error(404, "not found")


if __name__ == "__main__":
    print(f"Family Board dev server: http://localhost:{PORT}")
    print(f"  serving: {ROOT}")
    print(f"  /api/feed -> {FEED}  (+ in-memory /api/ack, /api/menu)")
    http.server.HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
