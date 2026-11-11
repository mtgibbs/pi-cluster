"""Shared plumbing: JSON-line logging with secret redaction, and a proxy-free HTTP opener.

Stdlib only. Nothing here ever logs a header value, a key, or the environment.
"""
import json
import sys
import time
import urllib.request

# The Job has no network except the model gateway and the listed MCP URLs; an inherited
# HTTP(S)_PROXY would silently route around that, so env proxies are ignored on purpose.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class Redactor:
    """Replaces every known secret value with a placeholder. Defence in depth: the code never
    logs a secret on purpose, but an upstream error body could echo one back at us."""

    PLACEHOLDER = "[REDACTED]"

    def __init__(self):
        self._secrets = []

    def add(self, value):
        if value and len(value) >= 4 and value not in self._secrets:
            self._secrets.append(value)
            self._secrets.sort(key=len, reverse=True)

    def __call__(self, text):
        if not isinstance(text, str):
            return text
        for s in self._secrets:
            if s in text:
                text = text.replace(s, self.PLACEHOLDER)
        return text

    def deep(self, obj):
        if isinstance(obj, str):
            return self(obj)
        if isinstance(obj, dict):
            return {self.deep(k): self.deep(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.deep(v) for v in obj]
        return obj


REDACT = Redactor()


def log(event, **fields):
    """One JSON object per stdout line. Callers pass sizes, names and durations — never payloads."""
    rec = {"ts": round(time.time(), 3), "event": event}
    rec.update(fields)
    line = REDACT(json.dumps(REDACT.deep(rec), ensure_ascii=False, default=str))
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def short_error(exc, limit=300):
    """A one-line, length-capped, redacted description of an exception."""
    text = f"{type(exc).__name__}: {exc}"
    body = getattr(exc, "agent_body", None)
    if body:
        text += f" — {body}"
    text = " ".join(text.split())
    return REDACT(text[:limit])
