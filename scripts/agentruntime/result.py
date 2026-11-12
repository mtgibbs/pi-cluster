"""The Result contract (CONTRACT.md §5): schema offered to the model, validation of what it
submits, and the last-line gate that makes whatever we emit conform before it leaves the pod."""
import base64
import json
import re

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

# `plan` outputs (CONTRACT §5a) — mirrors scripts/agentrunner/results.py; the runner re-checks all of it.
PLAN_SECTIONS = ("found", "evidence", "likely_cause", "proposed_change", "risk", "verify", "rollback")
PLAN_SEVERITIES = ("critical", "high", "medium", "low", "info")
PLAN_RULE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
PLAN_RESOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,62}/[A-Z][A-Za-z0-9]{0,62}/[A-Za-z0-9][A-Za-z0-9._:-]{0,252}$")
PLAN_SECTION_BYTES = 4 * 1024
PLAN_EVIDENCE_BYTES = 8 * 1024
PLAN_SECTION_HELP = {
    "found": "what was found, in plain words",
    "evidence": "file paths with line excerpts and/or tool results that show it",
    "likely_cause": "why it is this way (label inference as inference)",
    "proposed_change": "the manifest/file change to make, or exactly 'No change needed.' with the reason",
    "risk": "what could break if the change is made, and the risk of leaving it",
    "verify": "how a human checks the fix worked (a deny you have never seen deny proves nothing)",
    "rollback": "how to undo the change",
}


def _plan_item_schema():
    return {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["plan"]},
            "title": {"type": "string", "maxLength": TITLE_MAX_CHARS,
                      "description": "one line naming the finding"},
            "severity": {"type": "string", "enum": list(PLAN_SEVERITIES)},
            "fingerprint": {
                "type": "object",
                "description": "Stable identity of the finding: the same problem on the same resource must get "
                               "the same rule and resource on every run.",
                "properties": {
                    "rule": {"type": "string", "pattern": PLAN_RULE_RE.pattern,
                             "description": "short stable lowercase slug, e.g. networkpolicy-no-default-deny"},
                    "resource": {"type": "string", "pattern": PLAN_RESOURCE_RE.pattern,
                                 "description": "<namespace or 'cluster'>/<Kind>/<name>, e.g. "
                                                "agents/NetworkPolicy/agent-base-egress"},
                },
                "required": ["rule", "resource"],
                "additionalProperties": False,
            },
            "plan": {
                "type": "object",
                "properties": {k: {"type": "string", "description": v} for k, v in PLAN_SECTION_HELP.items()},
                "required": list(PLAN_SECTIONS),
                "additionalProperties": False,
            },
        },
        "required": ["kind", "title", "severity", "fingerprint", "plan"],
        "additionalProperties": False,
    }


def submit_result_tool(allowed_kinds):
    """OpenAI function-tool definition whose parameters are the Result schema."""
    body_kinds = [k for k in allowed_kinds if k != "plan"]
    schemas = []
    if body_kinds:
        schemas.append({
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": body_kinds},
                "title": {"type": "string", "maxLength": TITLE_MAX_CHARS},
                "body": {"type": "string", "description": "markdown, at most 32 KiB"},
            },
            "required": ["kind", "title", "body"],
            "additionalProperties": False,
        })
    if "plan" in allowed_kinds:
        schemas.append(_plan_item_schema())
    item = schemas[0] if len(schemas) == 1 else ({"anyOf": schemas} if schemas else {"type": "object"})
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
            continue
        if o["kind"] == "plan":
            problems.extend(f"outputs[{i}].{p}" for p in plan_problems(o))
            continue
        for f in ("title", "body"):
            if not isinstance(o.get(f), str):
                problems.append(f"outputs[{i}].{f} must be a string")
    return problems


def plan_problems(o):
    """Shape problems with a plan output that truncation cannot fix (oversize sections are truncated
    by finalize(), so they are not problems)."""
    problems = []
    extra = set(o) - {"kind", "title", "severity", "fingerprint", "plan"}
    if extra:
        problems.append(f"unknown keys {sorted(extra)}")
    title = o.get("title")
    if not (isinstance(title, str) and title.strip()):
        problems.append("title must be a non-empty string")
    if o.get("severity") not in PLAN_SEVERITIES:
        problems.append(f"severity must be one of {list(PLAN_SEVERITIES)}")
    fp = o.get("fingerprint")
    if not isinstance(fp, dict) or set(fp) != {"rule", "resource"}:
        problems.append("fingerprint must be an object with exactly rule and resource")
    else:
        if not (isinstance(fp["rule"], str) and PLAN_RULE_RE.match(fp["rule"])):
            problems.append("fingerprint.rule must be a lowercase slug of 3..64 chars ([a-z0-9-])")
        if not (isinstance(fp["resource"], str) and PLAN_RESOURCE_RE.match(fp["resource"])):
            problems.append("fingerprint.resource must look like <namespace|cluster>/<Kind>/<name>")
    plan = o.get("plan")
    if not isinstance(plan, dict):
        problems.append(f"plan must be an object with {list(PLAN_SECTIONS)}")
    else:
        extra = set(plan) - set(PLAN_SECTIONS)
        if extra:
            problems.append(f"plan has unknown sections {sorted(extra)}")
        for k in PLAN_SECTIONS:
            if not (isinstance(plan.get(k), str) and plan.get(k).strip()):
                problems.append(f"plan.{k} must be a non-empty string")
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
        if o["kind"] == "plan":
            p = _finalize_plan(o)
            if p is None:
                notes.append("dropped a plan output that does not match the plan shape")
                continue
            outputs.append(p)
            continue
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


def _finalize_plan(o):
    """A contract-valid plan output (redacted, truncated, title made one line), or None when the
    structure is wrong in a way truncation cannot repair — the runner would reject the whole Result."""
    if plan_problems(o):
        return None
    title = " ".join(REDACT(o["title"]).split())
    plan = {}
    for k in PLAN_SECTIONS:
        cap = PLAN_EVIDENCE_BYTES if k == "evidence" else PLAN_SECTION_BYTES
        plan[k] = _trunc_bytes(REDACT(o["plan"][k]), cap)
    fp = {"rule": o["fingerprint"]["rule"], "resource": o["fingerprint"]["resource"]}
    if REDACT(fp["rule"]) != fp["rule"] or REDACT(fp["resource"]) != fp["resource"]:
        return None
    # Plain cut, not _trunc_chars: its note has newlines and a plan title must stay one line.
    return {"kind": "plan", "title": title[:TITLE_MAX_CHARS] or "(untitled)",
            "severity": o["severity"], "fingerprint": fp, "plan": plan}


def _encoded_size(outcome, summary, outputs):
    return len(json.dumps({"outcome": outcome, "summary": summary, "outputs": outputs},
                          ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 512


def failed(reason):
    return {"outcome": "failed", "summary": reason, "outputs": []}


def marker_line(result):
    payload = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return MARKER + base64.b64encode(payload).decode("ascii")
