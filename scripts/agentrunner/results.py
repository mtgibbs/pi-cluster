"""Agent Result extraction + validation (CONTRACT.md §5).

The result is DATA. It is decoded, shape-checked and passed on to the callback; nothing in it is
ever executed, interpolated into a command, or used to choose what the runner does next.
"""
import base64
import binascii
import json
import re

MARKER = "::agent-result::"
OUTCOMES = {"done", "nothing_to_do", "needs_human", "failed"}
RESULT_KEYS = {"outcome", "summary", "outputs"}
OUTPUT_KEYS = {"kind", "title", "body"}          # every kind except `plan`
# `plan` (CONTRACT §5a): a structured finding. n8n files it as an issue from these fields alone,
# so every field is shape-checked here and nothing free-form beyond the sections is accepted.
PLAN_KEYS = {"kind", "title", "severity", "fingerprint", "plan"}
PLAN_FP_KEYS = {"rule", "resource"}
PLAN_SECTIONS = ("found", "evidence", "likely_cause", "proposed_change", "risk", "verify", "rollback")
PLAN_SEVERITIES = ("critical", "high", "medium", "low", "info")
PLAN_RULE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
# <namespace | "cluster">/<Kind>/<name>, e.g. agents/NetworkPolicy/agent-base-egress
PLAN_RESOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,62}/[A-Z][A-Za-z0-9]{0,62}/[A-Za-z0-9][A-Za-z0-9._:-]{0,252}$")
PLAN_TITLE_CHARS = 200
PLAN_SECTION_BYTES = 4 * 1024
PLAN_EVIDENCE_BYTES = 8 * 1024
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
        if not isinstance(o, dict):
            return f"outputs[{i}] must be an object"
        if o.get("kind") not in allowed:
            return f"outputs[{i}].kind not allowed by the manifest"
        err = validate_plan(o) if o["kind"] == "plan" else _validate_body_output(o)
        if err:
            return f"outputs[{i}]: {err}"
    return None


def _validate_body_output(o):
    if set(o) != OUTPUT_KEYS:
        return "must have exactly kind/title/body"
    if not all(isinstance(o[k], str) for k in OUTPUT_KEYS):
        return "fields must be strings"
    if len(o["title"]) > MAX_TITLE_CHARS:
        return "title too long"
    if len(o["body"].encode("utf-8")) > MAX_BODY_BYTES:
        return f"body exceeds {MAX_BODY_BYTES} bytes"
    return None


def validate_plan(o):
    """Error string for a `plan` output, or None. Exact keys, enums, slug/resource patterns, sizes."""
    if set(o) != PLAN_KEYS:
        return f"plan must have exactly {sorted(PLAN_KEYS)}"
    title = o["title"]
    if not (isinstance(title, str) and title.strip()) or len(title) > PLAN_TITLE_CHARS:
        return f"plan title must be 1..{PLAN_TITLE_CHARS} chars"
    if any(ord(c) < 32 for c in title):
        return "plan title must be one line"
    if o["severity"] not in PLAN_SEVERITIES:
        return f"plan severity must be one of {list(PLAN_SEVERITIES)}"
    fp = o["fingerprint"]
    if not isinstance(fp, dict) or set(fp) != PLAN_FP_KEYS:
        return "plan fingerprint must have exactly rule/resource"
    if not (isinstance(fp["rule"], str) and PLAN_RULE_RE.match(fp["rule"])):
        return "plan fingerprint.rule must be a lowercase slug (3..64 chars)"
    if not (isinstance(fp["resource"], str) and PLAN_RESOURCE_RE.match(fp["resource"])):
        return "plan fingerprint.resource must be <namespace|cluster>/<Kind>/<name>"
    plan = o["plan"]
    if not isinstance(plan, dict) or set(plan) != set(PLAN_SECTIONS):
        return f"plan.plan must have exactly {list(PLAN_SECTIONS)}"
    for k in PLAN_SECTIONS:
        v = plan[k]
        if not (isinstance(v, str) and v.strip()):
            return f"plan.{k} must be a non-empty string"
        cap = PLAN_EVIDENCE_BYTES if k == "evidence" else PLAN_SECTION_BYTES
        if len(v.encode("utf-8")) > cap:
            return f"plan.{k} exceeds {cap} bytes"
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
