"""Agent Result extraction + validation (CONTRACT.md §5).

The result is DATA. It is decoded, shape-checked and passed on to the callback; nothing in it is
ever executed, interpolated into a command, or used to choose what the runner does next.
"""
import base64
import binascii
import json

MARKER = "::agent-result::"
OUTCOMES = {"done", "nothing_to_do", "needs_human", "failed"}
RESULT_KEYS = {"outcome", "summary", "outputs"}
OUTPUT_KEYS = {"kind", "title", "body"}
MAX_SUMMARY_CHARS = 2048
MAX_BODY_BYTES = 32 * 1024
MAX_TITLE_CHARS = 512
MAX_OUTPUTS = 20
MAX_RESULT_BYTES = 256 * 1024  # decoded JSON
MAX_MARKER_LINE = len(MARKER) + (MAX_RESULT_BYTES * 4 // 3) + 8

OK, NO_RESULT, INVALID = "ok", "no_result", "invalid_result"


def failed_result(summary):
    return {"outcome": "failed", "summary": summary[:MAX_SUMMARY_CHARS], "outputs": []}


def last_line(log_text):
    lines = [ln for ln in (log_text or "").splitlines() if ln.strip()]
    return lines[-1].strip() if lines else ""


def validate_result(res, allowed_kinds):
    """Return an error string, or None when the Result is valid."""
    if not isinstance(res, dict):
        return "result is not a JSON object"
    if set(res) - RESULT_KEYS:
        return f"unknown result keys {sorted(set(res) - RESULT_KEYS)}"
    if res.get("outcome") not in OUTCOMES:
        return "unknown outcome"
    if not isinstance(res.get("summary"), str):
        return "summary must be a string"
    if len(res["summary"]) > MAX_SUMMARY_CHARS:
        return f"summary exceeds {MAX_SUMMARY_CHARS} chars"
    outs = res.get("outputs", [])
    if not isinstance(outs, list):
        return "outputs must be a list"
    if len(outs) > MAX_OUTPUTS:
        return f"more than {MAX_OUTPUTS} outputs"
    allowed = set(allowed_kinds)
    for i, o in enumerate(outs):
        if not isinstance(o, dict) or set(o) != OUTPUT_KEYS:
            return f"outputs[{i}] must have exactly kind/title/body"
        if not all(isinstance(o[k], str) for k in OUTPUT_KEYS):
            return f"outputs[{i}] fields must be strings"
        if o["kind"] not in allowed:
            return f"outputs[{i}].kind not allowed by the manifest"
        if len(o["title"]) > MAX_TITLE_CHARS:
            return f"outputs[{i}].title too long"
        if len(o["body"].encode("utf-8")) > MAX_BODY_BYTES:
            return f"outputs[{i}].body exceeds {MAX_BODY_BYTES} bytes"
    return None


def parse_result(log_text, allowed_kinds):
    """(status, result, reason). status is OK, NO_RESULT or INVALID; result is the validated
    Result dict only when status is OK. `reason` never echoes agent content back."""
    line = last_line(log_text)
    if not line.startswith(MARKER):
        return NO_RESULT, None, "no result marker on the last log line"
    payload = line[len(MARKER):].strip()
    if len(line) > MAX_MARKER_LINE:
        return INVALID, None, "result is oversize"
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        return INVALID, None, "result is not valid base64"
    if len(raw) > MAX_RESULT_BYTES:
        return INVALID, None, "result is oversize"
    try:
        res = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return INVALID, None, "result is not valid JSON"
    err = validate_result(res, allowed_kinds)
    if err:
        return INVALID, None, err
    res.setdefault("outputs", [])
    return OK, res, None
