"""The Result contract (CONTRACT.md §5): schema offered to the model, validation of what it
submits, and the last-line gate that makes whatever we emit conform before it leaves the pod."""
import base64
import json

from common import REDACT

OUTCOMES = ("done", "nothing_to_do", "needs_human", "failed")
MARKER = "::agent-result::"
SUMMARY_MAX_CHARS = 2048
BODY_MAX_BYTES = 32 * 1024
RESULT_MAX_BYTES = 240 * 1024  # runner limit is 256 KiB decoded; leave headroom
# Not in the contract; bounds the marker line so a runaway model cannot emit a multi-MB log line.
TITLE_MAX_CHARS = 200
OUTPUTS_MAX = 20
TRUNC_NOTE = "\n\n[agent-runtime: truncated to fit the result size limit]"


def submit_result_tool(allowed_kinds):
    """OpenAI function-tool definition whose parameters are the Result schema."""
    item = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(allowed_kinds)},
            "title": {"type": "string", "maxLength": TITLE_MAX_CHARS},
            "body": {"type": "string", "description": "markdown, at most 32 KiB"},
        },
        "required": ["kind", "title", "body"],
        "additionalProperties": False,
    }
    outputs = {"type": "array", "items": item, "maxItems": OUTPUTS_MAX if allowed_kinds else 0}
    return {
        "type": "function",
        "function": {
            "name": "submit_result",
            "description": "Finish the run. Call exactly once, when the investigation is complete "
                           "(or cannot proceed). This is the only way to deliver your answer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "outcome": {"type": "string", "enum": list(OUTCOMES)},
                    "summary": {"type": "string", "maxLength": SUMMARY_MAX_CHARS},
                    "outputs": outputs,
                },
                "required": ["outcome", "summary", "outputs"],
                "additionalProperties": False,
            },
        },
    }


def validate_submission(args, allowed_kinds):
    """Problems with a submit_result call, as human-readable strings ([] = acceptable).
    Oversize fields are not problems: finalize() truncates them."""
    if not isinstance(args, dict):
        return ["arguments must be a JSON object"]
    problems = []
    if args.get("outcome") not in OUTCOMES:
        problems.append(f"outcome must be one of {list(OUTCOMES)}")
    if not isinstance(args.get("summary"), str) or not args.get("summary").strip():
        problems.append("summary must be a non-empty string")
    outputs = args.get("outputs", [])
    if not isinstance(outputs, list):
        problems.append("outputs must be an array")
        outputs = []
    for i, o in enumerate(outputs):
        if not isinstance(o, dict):
            problems.append(f"outputs[{i}] must be an object")
            continue
        if o.get("kind") not in allowed_kinds:
            problems.append(f"outputs[{i}].kind {o.get('kind')!r} is not allowed; "
                            f"allowed kinds: {list(allowed_kinds)}")
        for f in ("title", "body"):
            if not isinstance(o.get(f), str):
                problems.append(f"outputs[{i}].{f} must be a string")
    return problems


def _trunc_chars(text, limit):
    if len(text) <= limit:
        return text
    keep = max(0, limit - len(TRUNC_NOTE))
    return text[:keep] + TRUNC_NOTE[: limit - keep]


def _trunc_bytes(text, limit):
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    note = TRUNC_NOTE.encode("utf-8")
    head = raw[: max(0, limit - len(note))].decode("utf-8", errors="ignore")
    return head + TRUNC_NOTE


def finalize(result, allowed_kinds):
    """The last gate before emit. Always returns a contract-valid Result: an unknown outcome
    becomes `failed`, outputs whose kind is not in the manifest are dropped (and said so in the
    summary), oversize fields are truncated with a visible note, secrets are redacted."""
    if not isinstance(result, dict):
        result = {"outcome": "failed", "summary": "agent produced a non-object result", "outputs": []}
    notes = []
    outcome = result.get("outcome")
    if outcome not in OUTCOMES:
        notes.append(f"unknown outcome {str(outcome)[:40]!r} forced to failed")
        outcome = "failed"
    summary = result.get("summary")
    summary = summary if isinstance(summary, str) and summary.strip() else "(no summary)"
    outputs = []
    raw_outputs = result.get("outputs")
    for o in raw_outputs if isinstance(raw_outputs, list) else []:
        if not isinstance(o, dict) or o.get("kind") not in allowed_kinds:
            kind = o.get("kind") if isinstance(o, dict) else type(o).__name__
            notes.append(f"dropped output with disallowed kind {str(kind)[:40]!r}")
            continue
        if len(outputs) >= OUTPUTS_MAX:
            notes.append(f"dropped outputs beyond {OUTPUTS_MAX}")
            break
        title = o.get("title") if isinstance(o.get("title"), str) else ""
        body = o.get("body") if isinstance(o.get("body"), str) else ""
        outputs.append({
            "kind": o["kind"],
            "title": _trunc_chars(REDACT(title), TITLE_MAX_CHARS),
            "body": _trunc_bytes(REDACT(body), BODY_MAX_BYTES),
        })
    # The runner rejects a decoded Result over 256 KiB (scripts/agentrunner/results.py). Stay under it.
    dropped = 0
    while outputs and _encoded_size(outcome, summary, outputs) > RESULT_MAX_BYTES:
        outputs.pop()
        dropped += 1
    if dropped:
        notes.append(f"dropped {dropped} output(s) to keep the result under {RESULT_MAX_BYTES} bytes")
    if notes:
        summary = f"{summary} [agent-runtime: {'; '.join(notes)}]"
    return {"outcome": outcome, "summary": _trunc_chars(REDACT(summary), SUMMARY_MAX_CHARS),
            "outputs": outputs}


def _encoded_size(outcome, summary, outputs):
    return len(json.dumps({"outcome": outcome, "summary": summary, "outputs": outputs},
                          ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 512


def failed(reason):
    return {"outcome": "failed", "summary": reason, "outputs": []}


def marker_line(result):
    payload = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return MARKER + base64.b64encode(payload).decode("ascii")
