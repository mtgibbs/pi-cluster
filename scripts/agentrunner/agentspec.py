"""Agent manifest + event validation (CONTRACT.md §1, §2).

A manifest that fails validation is never launched. Validation is strict: unknown keys are an
error at the top level (per contract) AND inside model/limits/connectors/resources, because a
typo in an allowlist-shaped field (e.g. `tool:` for `tools:`) must fail loudly, not widen access.
"""
import json
import re
from pathlib import Path

import yaml

NAME_RE = re.compile(r"^[a-z0-9-]+$")
K8S_NAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MODEL_RE = re.compile(r"^[A-Za-z0-9._:/-]+$")
DURATION_RE = re.compile(r"^(\d+)([smh])$")
TOOL_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
EVENT_TYPE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
# checkout.source names a Flux source object as <namespace>/<name>. The runner, not the manifest,
# decides the host it is fetched from (RUNNER_CHECKOUT_BASE_URL), so a manifest cannot point an
# init container at an arbitrary URL.
CHECKOUT_SOURCE_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?/[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
INCLUDE_RE = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*/?$")
CHECKOUT_KEYS = {"source", "include"}
MAX_INCLUDE = 20

TOP_KEYS = {"kind", "name", "purpose", "image", "data_class", "model", "secret", "connectors",
            "outputs", "prompt", "limits", "resources", "checkout"}
REQUIRED = {"kind", "name", "purpose", "image", "data_class", "model", "secret", "outputs",
            "prompt", "limits"}
LIMIT_KEYS = {"timeout", "runs_per_day", "max_steps"}
MCP_KEYS = {"name", "url", "header", "key_env", "tools"}
RESOURCE_KEYS = {"cpu", "memory", "ephemeral-storage"}
MAX_MANIFEST_BYTES = 256 * 1024
MAX_TIMEOUT_S = 24 * 3600

MAX_EVENT_BYTES = 64 * 1024
EVENT_FIELDS = {"id": str, "type": str, "source": str, "subject": str, "trust": str, "data": dict}
TRUST = {"internal", "external"}


class AgentNotFound(LookupError):
    pass


class ManifestError(ValueError):
    pass


class EventError(ValueError):
    pass


def parse_duration(v):
    """'15m' / '30s' / '1h' / int seconds -> seconds (int > 0)."""
    if isinstance(v, bool):
        raise ValueError("timeout must be a duration")
    if isinstance(v, int):
        secs = v
    elif isinstance(v, str) and DURATION_RE.match(v.strip()):
        n, unit = DURATION_RE.match(v.strip()).groups()
        secs = int(n) * {"s": 1, "m": 60, "h": 3600}[unit]
    else:
        raise ValueError(f"timeout {v!r} is not a duration like 15m/30s/1h")
    if not 0 < secs <= MAX_TIMEOUT_S:
        raise ValueError(f"timeout must be between 1s and {MAX_TIMEOUT_S}s")
    return secs


def _str(v):
    return isinstance(v, str) and v.strip() != ""


def _pos_int(v):
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def _model_list(v):
    return (isinstance(v, list) and bool(v)
            and all(isinstance(x, str) and MODEL_RE.match(x) for x in v))


def models_for(manifest, event_type):
    """The model list a run of `manifest` uses for an event of `event_type`: the matching
    model.by_event_type entry, else model.allow. Both were validated (incl. the personal rule)."""
    m = manifest["model"]
    return list((m.get("by_event_type") or {}).get(event_type) or m["allow"])


def validate_manifest(doc, file_stem, local_models):
    """Raise ManifestError listing every problem; return the timeout in seconds when valid."""
    errs = []
    if not isinstance(doc, dict):
        raise ManifestError("manifest is not a mapping")
    unknown = set(doc) - TOP_KEYS
    if unknown:
        errs.append(f"unknown top-level keys: {sorted(unknown)}")
    missing = REQUIRED - set(doc)
    if missing:
        errs.append(f"missing keys: {sorted(missing)}")

    if "kind" in doc and doc["kind"] != "Agent":
        errs.append("kind must be 'Agent'")
    name = doc.get("name")
    if "name" in doc:
        if not (isinstance(name, str) and NAME_RE.match(name) and len(name) <= 63):
            errs.append("name must match [a-z0-9-]+ (<= 63 chars)")
        elif name != file_stem:
            errs.append(f"name {name!r} does not equal the file name {file_stem!r}")
    for k in ("purpose", "image", "prompt"):
        if k in doc and not _str(doc[k]):
            errs.append(f"{k} must be a non-empty string")
    if "data_class" in doc and doc["data_class"] not in ("system", "personal"):
        errs.append("data_class must be 'system' or 'personal'")
    if "secret" in doc and not (isinstance(doc["secret"], str) and K8S_NAME_RE.match(doc["secret"])):
        errs.append("secret must be a Kubernetes object name")

    # model
    model_lists = []   # every model list the manifest can select (allow + each by_event_type entry)
    if "model" in doc:
        m = doc["model"]
        if not isinstance(m, dict) or "allow" not in m or set(m) - {"allow", "by_event_type"}:
            errs.append("model must be a mapping with key allow (and optionally by_event_type)")
        else:
            allow = m["allow"]
            if _model_list(allow):
                model_lists.append(allow)
            else:
                errs.append("model.allow must be a non-empty list of model names")
            if "by_event_type" in m:
                bet = m["by_event_type"]
                if not (isinstance(bet, dict) and bet):
                    errs.append("model.by_event_type must be a non-empty mapping of event type -> models")
                else:
                    for et, lst in bet.items():
                        if not (isinstance(et, str) and EVENT_TYPE_RE.match(et)):
                            errs.append(f"model.by_event_type key {et!r} is not an event type")
                        elif not _model_list(lst):
                            errs.append(f"model.by_event_type[{et}] must be a non-empty list of model names")
                        else:
                            model_lists.append(lst)
    if doc.get("data_class") == "personal" and model_lists:
        local = set(local_models)
        nonlocal_models = sorted({x for lst in model_lists for x in lst if x not in local})
        if nonlocal_models:
            errs.append(f"data_class personal requires local models only; not in "
                        f"RUNNER_LOCAL_MODELS: {nonlocal_models}")

    # outputs
    if "outputs" in doc:
        o = doc["outputs"]
        if not (isinstance(o, list) and o and all(_str(x) for x in o) and len(set(o)) == len(o)):
            errs.append("outputs must be a non-empty list of unique strings")

    # limits
    if "limits" in doc:
        lim = doc["limits"]
        if not isinstance(lim, dict):
            errs.append("limits must be a mapping")
        else:
            if set(lim) - LIMIT_KEYS:
                errs.append(f"unknown limits keys: {sorted(set(lim) - LIMIT_KEYS)}")
            if LIMIT_KEYS - set(lim):
                errs.append(f"missing limits keys: {sorted(LIMIT_KEYS - set(lim))}")
            if "timeout" in lim:
                try:
                    parse_duration(lim["timeout"])
                except ValueError as e:
                    errs.append(f"limits.{e}")
            for k in ("runs_per_day", "max_steps"):
                if k in lim and not _pos_int(lim[k]):
                    errs.append(f"limits.{k} must be a positive integer")

    # connectors
    if "connectors" in doc:
        c = doc["connectors"]
        if not isinstance(c, dict) or set(c) - {"mcp"}:
            errs.append("connectors must be a mapping with only key: mcp")
        else:
            mcp = c.get("mcp") or []
            if not isinstance(mcp, list):
                errs.append("connectors.mcp must be a list")
                mcp = []
            seen = set()
            for i, ent in enumerate(mcp):
                where = f"connectors.mcp[{i}]"
                if not isinstance(ent, dict):
                    errs.append(f"{where} must be a mapping")
                    continue
                if set(ent) - MCP_KEYS:
                    errs.append(f"{where}: unknown keys {sorted(set(ent) - MCP_KEYS)}")
                if not (isinstance(ent.get("name"), str) and NAME_RE.match(ent["name"])):
                    errs.append(f"{where}.name must match [a-z0-9-]+")
                elif ent["name"] in seen:
                    errs.append(f"{where}.name {ent['name']!r} is duplicated")
                else:
                    seen.add(ent["name"])
                url = ent.get("url")
                if not (isinstance(url, str) and url.startswith(("http://", "https://"))):
                    errs.append(f"{where}.url must be an http(s) URL")
                if ("header" in ent) != ("key_env" in ent):
                    errs.append(f"{where}: header and key_env go together")
                if "header" in ent and not _str(ent["header"]):
                    errs.append(f"{where}.header must be a non-empty string")
                if "key_env" in ent and not (isinstance(ent["key_env"], str)
                                             and ENV_RE.match(ent["key_env"])):
                    errs.append(f"{where}.key_env must be an env var name")
                tools = ent.get("tools")
                if not (isinstance(tools, list) and tools
                        and all(isinstance(t, str) and TOOL_RE.match(t) for t in tools)):
                    errs.append(f"{where}.tools must be a non-empty list of tool names")

    # checkout (optional): a read-only copy of a Flux source artifact (CONTRACT §2, §4)
    if "checkout" in doc:
        co = doc["checkout"]
        if not isinstance(co, dict) or set(co) - CHECKOUT_KEYS or "source" not in co:
            errs.append("checkout must be a mapping with key source (and optionally include)")
        else:
            if not (isinstance(co["source"], str) and CHECKOUT_SOURCE_RE.match(co["source"])):
                errs.append("checkout.source must be <namespace>/<name> of a Flux GitRepository")
            if "include" in co:
                inc = co["include"]
                if not (isinstance(inc, list) and inc and len(inc) <= MAX_INCLUDE and all(
                        isinstance(x, str) and INCLUDE_RE.match(x) and ".." not in x.split("/")
                        for x in inc)):
                    errs.append(f"checkout.include must be 1..{MAX_INCLUDE} relative path prefixes "
                                "(no leading '/', no '..')")

    # resources (optional)
    if "resources" in doc:
        r = doc["resources"]
        if not isinstance(r, dict) or set(r) - {"requests", "limits"}:
            errs.append("resources must be a mapping of requests/limits")
        else:
            for k, v in r.items():
                if not isinstance(v, dict) or set(v) - RESOURCE_KEYS or not all(
                        isinstance(q, (str, int, float)) and not isinstance(q, bool)
                        for q in v.values()):
                    errs.append(f"resources.{k} must map {sorted(RESOURCE_KEYS)} to quantities")

    if errs:
        raise ManifestError("; ".join(errs))
    return parse_duration(doc["limits"]["timeout"])


def load_manifest(manifest_dir, agent, local_models):
    """(manifest dict, timeout seconds). Re-read from disk on every call so a ConfigMap update is
    picked up without a restart. AgentNotFound for an unknown/unsafe name; ManifestError if invalid."""
    if not (isinstance(agent, str) and NAME_RE.match(agent) and len(agent) <= 63):
        raise AgentNotFound(agent)
    path = Path(manifest_dir) / f"{agent}.yaml"
    if not path.is_file():
        raise AgentNotFound(agent)
    raw = path.read_bytes()
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ManifestError("manifest file too large")
    try:
        doc = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise ManifestError(f"manifest is not valid YAML: {str(e)[:200]}") from None
    timeout = validate_manifest(doc, agent, local_models)
    # Must be JSON-serialisable to become AGENT_MANIFEST (YAML can yield dates etc.).
    try:
        json.dumps(doc)
    except (TypeError, ValueError):
        raise ManifestError("manifest contains values that are not JSON-representable") from None
    return doc, timeout


def event_size(event):
    return len(json.dumps(event, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def validate_event(ev):
    if not isinstance(ev, dict):
        raise EventError("event must be an object")
    errs = []
    for k, t in EVENT_FIELDS.items():
        if k not in ev:
            errs.append(f"event.{k} is required")
        elif not isinstance(ev[k], t):
            errs.append(f"event.{k} must be a {t.__name__}")
    if isinstance(ev.get("id"), str) and not (0 < len(ev["id"]) <= 256):
        errs.append("event.id must be 1..256 chars")
    if isinstance(ev.get("trust"), str) and ev["trust"] not in TRUST:
        errs.append("event.trust must be 'internal' or 'external'")
    if "dedupe_key" in ev and not isinstance(ev["dedupe_key"], str):
        errs.append("event.dedupe_key must be a string")
    if not errs and event_size(ev) > MAX_EVENT_BYTES:
        errs.append(f"event exceeds {MAX_EVENT_BYTES} bytes")
    if errs:
        raise EventError("; ".join(errs))
