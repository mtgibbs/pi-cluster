"""Minimal MCP client over streamable HTTP (JSON-RPC 2.0), stdlib only.

initialize -> notifications/initialized -> tools/list -> tools/call. A POST response may be a plain
JSON body or an SSE stream (`data:` lines); both are handled. An `Mcp-Session-Id` returned by the
server is echoed on every later request.
"""
import json
import time
import urllib.error
import urllib.request

from common import OPENER

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "agent-runtime", "version": "0.1.0"}


class MCPError(Exception):
    pass


class MCPClient:
    def __init__(self, name, url, auth_header=None, auth_value=None, timeout=60):
        self.name = name
        self.url = url
        self.timeout = timeout
        self._auth = (auth_header, auth_value) if auth_header and auth_value else None
        self.session_id = None
        self.protocol_version = None
        self._next_id = 0

    # -- transport ---------------------------------------------------------------------------
    def _headers(self):
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self._auth:
            h[self._auth[0]] = self._auth[1]
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        if self.protocol_version:
            h["MCP-Protocol-Version"] = self.protocol_version
        return h

    def _post(self, message, timeout):
        req = urllib.request.Request(self.url, data=json.dumps(message).encode("utf-8"),
                                     headers=self._headers(), method="POST")
        try:
            return OPENER.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            err = MCPError(f"{self.name}: HTTP {e.code} from MCP server")
            try:
                err.agent_body = e.read(300).decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass
            raise err from None
        except (urllib.error.URLError, OSError) as e:
            reason = getattr(e, "reason", e)
            raise MCPError(f"{self.name}: cannot reach MCP server ({reason})") from None

    def notify(self, method, params=None):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        with self._post(msg, self.timeout) as resp:
            resp.read(65536)

    def request(self, method, params=None, timeout=None):
        timeout = timeout or self.timeout
        self._next_id += 1
        rid = self._next_id
        msg = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
        deadline = time.monotonic() + timeout
        with self._post(msg, timeout) as resp:
            sid = resp.headers.get("Mcp-Session-Id")
            if sid and not self.session_id:
                self.session_id = sid
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype == "text/event-stream":
                reply = self._read_sse(resp, rid, deadline)
            else:
                body = resp.read()
                try:
                    reply = json.loads(body)
                except ValueError:
                    raise MCPError(f"{self.name}: {method} returned non-JSON "
                                   f"(content-type {ctype or 'none'})") from None
                if isinstance(reply, list):  # a JSON-RPC batch; pick ours
                    reply = next((m for m in reply if isinstance(m, dict) and m.get("id") == rid), None)
        if not isinstance(reply, dict) or reply.get("id") != rid:
            raise MCPError(f"{self.name}: {method}: no JSON-RPC response with id {rid}")
        if "error" in reply:
            e = reply["error"] if isinstance(reply["error"], dict) else {"message": str(reply["error"])}
            raise MCPError(f"{self.name}: {method}: JSON-RPC error {e.get('code')}: "
                           f"{str(e.get('message'))[:200]}")
        return reply.get("result") or {}

    def _read_sse(self, resp, rid, deadline):
        """Read SSE events until the JSON-RPC response with our id arrives. Server notifications
        and requests on the stream are skipped."""
        data_lines = []
        while True:
            if time.monotonic() > deadline:
                raise MCPError(f"{self.name}: timed out waiting on the SSE stream")
            line = resp.readline()
            if not line:  # stream closed; flush a final unterminated event
                msg = self._sse_event(data_lines)
                if isinstance(msg, dict) and msg.get("id") == rid and ("result" in msg or "error" in msg):
                    return msg
                raise MCPError(f"{self.name}: SSE stream ended without a response")
            line = line.decode("utf-8", errors="replace").rstrip("\r\n")
            if line == "":
                msg = self._sse_event(data_lines)
                data_lines = []
                if isinstance(msg, dict) and msg.get("id") == rid and ("result" in msg or "error" in msg):
                    return msg
            elif line.startswith("data:"):
                data_lines.append(line[5:][1:] if line[5:6] == " " else line[5:])
            # event:, id:, retry:, and ':' comments are ignored

    @staticmethod
    def _sse_event(data_lines):
        if not data_lines:
            return None
        try:
            return json.loads("\n".join(data_lines))
        except ValueError:
            return None

    # -- protocol ----------------------------------------------------------------------------
    def initialize(self):
        res = self.request("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                          "clientInfo": CLIENT_INFO})
        self.protocol_version = res.get("protocolVersion") or PROTOCOL_VERSION
        self.notify("notifications/initialized")
        return res

    def list_tools(self):
        tools, cursor = [], None
        for _ in range(50):  # pagination bound
            res = self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(t for t in res.get("tools") or [] if isinstance(t, dict))
            cursor = res.get("nextCursor")
            if not cursor:
                break
        return tools

    def call_tool(self, tool, arguments, timeout=None):
        return self.request("tools/call", {"name": tool, "arguments": arguments}, timeout=timeout)


def render_tool_result(res):
    """Flatten a tools/call result into text for the model."""
    parts = []
    for c in res.get("content") or []:
        if not isinstance(c, dict):
            continue
        if c.get("type") == "text":
            parts.append(str(c.get("text", "")))
        elif c.get("type") == "resource" and isinstance(c.get("resource"), dict) \
                and "text" in c["resource"]:
            parts.append(str(c["resource"]["text"]))
        else:
            parts.append(f"[{c.get('type', 'unknown')} content omitted]")
    if not parts and res.get("structuredContent") is not None:
        parts.append(json.dumps(res["structuredContent"], ensure_ascii=False))
    text = "\n".join(parts) if parts else "(empty tool result)"
    if res.get("isError"):
        text = "TOOL ERROR: " + text
    return text
