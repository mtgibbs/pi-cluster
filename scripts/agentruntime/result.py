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
    "evidence": "file path:line with the quoted lines, and/or the live tool name + field/value that shows it "
                "(required: a plan without one is dropped)",
    "likely_cause": "why it is this way (label inference as inference)",
    "proposed_change": "the manifest/file change to make, or exactly 'No change needed.' with the reason",
    "risk": "what could break if the change is made, and the risk of leaving it",
    "verify": "how a human checks the fix worked (a deny you have never seen deny proves nothing)",
    "rollback": "how to undo the change",
}


# -- plan discipline (runtime >= 0.3.0, CONTRACT §5b) ---------------------------------------------
# The fingerprint (rule + resource) is n8n's identity for a finding, so `rule` comes from this CLOSED
# vocabulary and each rule names the Kind(s) its resource may be. Every rule name ever filed stays here
# (homelab-plans issues carry them): renaming or removing one orphans the open issue it fingerprints.
# The manifest prompt and n8n's Plan Items node list the same names (test_repo_checkout.py checks).
RBAC_KINDS = ("Role", "ClusterRole", "RoleBinding", "ClusterRoleBinding")
WORKLOAD_KINDS = ("Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob", "Pod", "HelmRelease")
PLAN_RULES = {  # rule -> (what it means, Kinds its resource may be; None = any Kind)
    "rbac-wildcard": ("a Role/ClusterRole grants * verbs, resources or apiGroups", RBAC_KINDS),
    "rbac-secrets-read": ("get/list/watch on secrets beyond what the workload needs", RBAC_KINDS),
    "rbac-escalation-verbs": ("escalate, bind or impersonate verbs", RBAC_KINDS),
    "rbac-cluster-admin": ("a binding to cluster-admin or an equivalent", RBAC_KINDS),
    "rbac-broad-subject": ("a binding to a broad subject (all SAs of a namespace, system:authenticated, ...)",
                           RBAC_KINDS),
    "rbac-workload-create": ("create/patch of pods, jobs or workloads (they can mount any Secret in the namespace)",
                             RBAC_KINDS),
    "rbac-pod-exec": ("pods/exec, pods/attach or pods/portforward", RBAC_KINDS),
    "sa-token-automount": ("an API token is mounted into a workload that never calls the API",
                           ("ServiceAccount",) + WORKLOAD_KINDS),
    "sa-shared": ("one ServiceAccount (or `default`) used by unrelated workloads", ("ServiceAccount",) + WORKLOAD_KINDS),
    "netpol-no-default-deny": ("a namespace without a default-deny policy (resource: cluster/Namespace/<ns>)",
                               ("Namespace",)),
    "netpol-broad-egress": ("an egress rule broader than its stated purpose", ("NetworkPolicy",)),
    "netpol-broad-ingress": ("an ingress rule broader than its stated purpose", ("NetworkPolicy",)),
    "netpol-lan-egress": ("egress to the home LAN that the workload does not need", ("NetworkPolicy",)),
    "netpol-api-egress": ("egress to the Kubernetes API that the workload does not need", ("NetworkPolicy",)),
    "pod-privileged": ("privileged: true", WORKLOAD_KINDS),
    "pod-host-namespace": ("hostNetwork, hostPID or hostIPC", WORKLOAD_KINDS),
    "pod-hostpath": ("a hostPath volume", WORKLOAD_KINDS),
    "pod-host-port": ("a hostPort", WORKLOAD_KINDS),
    "pod-runs-as-root": ("runs as uid 0 or without runAsNonRoot", WORKLOAD_KINDS),
    "pod-privilege-escalation": ("allowPrivilegeEscalation not false", WORKLOAD_KINDS),
    "pod-added-capabilities": ("capabilities added, or ALL not dropped", WORKLOAD_KINDS),
    "pod-writable-rootfs": ("readOnlyRootFilesystem not true", WORKLOAD_KINDS),
    "pod-no-seccomp": ("no seccomp profile", WORKLOAD_KINDS),
    "psa-not-enforced": ("a namespace without a Pod Security enforce label (resource: cluster/Namespace/<ns>)",
                         ("Namespace",)),
    "image-mutable-tag": ("an image by :latest or no tag (whoever pushes the tag runs code); NOT version lag",
                          WORKLOAD_KINDS),
    "secret-inline-value": ("a secret value committed to Git (cite the path, never the value)", None),
    "secret-tier-too-high": ("an ExternalSecret pulls a more powerful credential than the workload needs", None),
    "secret-shared-across-roles": ("one credential used by several roles/workloads", None),
    "ingress-public-no-auth": ("reachable from outside the LAN without auth", None),
    "ingress-no-tls": ("exposed without TLS", None),
    "ingress-unexpected-exposure": ("exposed further than its purpose needs", None),
    "service-lan-exposure": ("a LoadBalancer/NodePort Service exposing something to the LAN that need not be",
                             ("Service", "HelmRelease")),
}
CLUSTER_SCOPED_KINDS = ("ClusterRole", "ClusterRoleBinding", "Namespace", "ClusterSecretStore",
                        "ClusterExternalSecret", "ClusterIssuer", "PersistentVolume", "StorageClass",
                        "CustomResourceDefinition", "PriorityClass", "IngressClass", "Node",
                        "ValidatingWebhookConfiguration", "MutatingWebhookConfiguration")
NAMESPACED_KINDS = ("Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "Job", "CronJob", "Pod", "Service",
                    "Ingress", "IngressRoute", "Middleware", "NetworkPolicy", "Role", "RoleBinding",
                    "ServiceAccount", "Secret", "ConfigMap", "ExternalSecret", "SecretStore", "HelmRelease",
                    "Kustomization", "GitRepository", "HelmRepository", "OCIRepository", "PersistentVolumeClaim",
                    "ResourceQuota", "LimitRange", "PodDisruptionBudget", "Certificate")
_KIND_SPELLING = {k.lower(): k for k in CLUSTER_SCOPED_KINDS + NAMESPACED_KINDS}
# Evidence must point at something checkable: a file path WITH a line number, or a live tool result.
_FILE_LINE_RE = re.compile(
    r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.(?:ya?ml|md|json|js|py|sh|conf|toml|txt)"
    r"(?::\s*L?\d+|#L\d+|,?\s*\(?\s*(?:lines?|L|l\.)\s*\d+)", re.I)
# A title that labels itself inference is not a finding (it belongs in the summary as an open question).
_INFERENCE_RE = re.compile(r"\b(inference|inferred|speculative|speculation|unverified|hypothetical)\b", re.I)
_NUM = r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_SEV_COUNT_RE = re.compile(_NUM + r"\s+(critical|high|medium|low|info(?:rmational)?)\b", re.I)
_FINDING_COUNT_RE = re.compile(_NUM + r"\s+(?:[a-z-]+\s+)?(?:findings?|issues?|problems?)\b", re.I)


def _n(word):
    return int(word) if word.isdigit() else _WORDS[word.lower()]


def summary_claims(summary):
    """What a summary says about findings: ({severity: count}, largest 'N findings' count). Zeros are no claim."""
    sev = {}
    for m in re.finditer(r"\b" + _SEV_COUNT_RE.pattern, summary or "", re.I):
        n, s = _n(m.group(1)), m.group(2).lower()
        s = "info" if s.startswith("info") else s
        if n:
            sev[s] = sev.get(s, 0) + n
    total = max([_n(m.group(1)) for m in re.finditer(r"\b" + _FINDING_COUNT_RE.pattern, summary or "", re.I)]
                or [0])
    return sev, total


def plan_semantic_problems(o, tool_names=()):
    """Problems with one shape-valid plan that make it unfit to file: an unknown rule, a resource whose Kind
    the rule does not allow or whose scope is wrong, evidence that cites neither a file:line nor a live tool
    result, or a title that calls itself inference."""
    problems = []
    rule, resource = o["fingerprint"]["rule"], o["fingerprint"]["resource"]
    ns, kind, _ = resource.split("/", 2)
    if rule not in PLAN_RULES:
        problems.append(f"fingerprint.rule {rule!r} is not in the rule vocabulary (see the submit_result schema); "
                        "if no rule fits, it is not a finding for this agent")
    canon = _KIND_SPELLING.get(kind.lower())
    if canon and canon != kind:
        problems.append(f"fingerprint.resource Kind must be spelled {canon!r}")
    kind = canon or kind
    if kind in CLUSTER_SCOPED_KINDS and ns != "cluster":
        problems.append(f"fingerprint.resource: {kind} is cluster-scoped, write cluster/{kind}/<name>")
    if kind in NAMESPACED_KINDS and ns == "cluster":
        problems.append(f"fingerprint.resource: {kind} is namespaced, write <namespace>/{kind}/<name>")
    allowed = (PLAN_RULES.get(rule) or (None, None))[1]
    if allowed and kind not in allowed:
        problems.append(f"fingerprint.rule {rule} applies to {'/'.join(allowed)}, not {kind}: name the object "
                        "the fix changes, or pick the rule that matches it")
    ev = o["plan"]["evidence"]
    if not (_FILE_LINE_RE.search(ev) or any(t and t in ev for t in tool_names)):
        problems.append("plan.evidence must cite a file path with a line number (path:line) or the live tool "
                        "result that shows it (tool name + field); inference alone belongs in the summary as "
                        "an open question, not in a plan")
    if _INFERENCE_RE.search(o["title"]):
        problems.append("title says the finding is inference: a plan needs concrete evidence; drop it and "
                        "ask the open question in the summary instead")
    return problems


def _plans_only(allowed_kinds):
    return set(allowed_kinds) == {"plan"}


def review_submission(args, allowed_kinds, tool_names=()):
    """Discipline problems with a shape-valid submission from a plan agent ([] = fine). These get ONE
    corrective re-prompt; enforce_discipline() then settles whatever is still wrong, deterministically."""
    if "plan" not in allowed_kinds:
        return []
    problems = []
    plans = [o for o in args.get("outputs") or [] if o.get("kind") == "plan"]
    for i, o in enumerate(args.get("outputs") or []):
        if o.get("kind") == "plan":
            problems.extend(f"outputs[{i}]: {p}" for p in plan_semantic_problems(o, tool_names))
    if not _plans_only(allowed_kinds) or args.get("outcome") == "failed":
        return problems
    sev, total = summary_claims(args.get("summary"))
    have = {}
    for o in plans:
        have[o["severity"]] = have.get(o["severity"], 0) + 1
    if not plans and (sev or total):
        problems.append("the summary reports findings but outputs has no plan: every finding must be a plan "
                        "output (with evidence), and the summary may only count the plans you return")
    elif plans and (any(have.get(s, 0) != n for s, n in sev.items()) or total > len(plans)):
        problems.append(f"the summary's finding counts do not match the {len(plans)} plan(s) returned "
                        f"({', '.join(f'{v} {k}' for k, v in have.items())}): every finding must be a plan")
    if not plans and args.get("outcome") == "needs_human" and "?" not in (args.get("summary") or ""):
        problems.append("outcome needs_human with no plan must ask Matt a stated question in the summary; "
                        "otherwise use nothing_to_do (findings go in plans, never only in the summary)")
    return problems


def enforce_discipline(args, allowed_kinds, tool_names=()):
    """Deterministic settlement after the one corrective re-prompt: drop plans that are still unfit to file,
    derive the outcome from the plans that remain, and say in the summary what was dropped or inconsistent.
    Returns (args, notes)."""
    if "plan" not in allowed_kinds:
        return args, []
    notes, kept, dropped = [], [], []
    for o in args.get("outputs") or []:
        if o.get("kind") == "plan" and plan_semantic_problems(o, tool_names):
            dropped.append(f"{o['fingerprint']['rule']} {o['fingerprint']['resource']}")
        else:
            kept.append(o)
    if dropped:
        notes.append(f"dropped {len(dropped)} plan(s) that failed the plan rules (vocabulary, resource Kind, "
                     f"evidence citation): {'; '.join(dropped)[:400]}")
    args = dict(args, outputs=kept)
    if not _plans_only(allowed_kinds) or args.get("outcome") == "failed":
        return args, notes
    sev, total = summary_claims(args.get("summary"))
    plans = [o for o in kept if o.get("kind") == "plan"]
    if (sev or total) and (not plans or total > len(plans) or any(
            sum(1 for o in plans if o["severity"] == s) != n for s, n in sev.items())):
        notes.append(f"the summary counts findings that are not among the {len(plans)} plan(s) returned; "
                     "only the plans are filed")
    if plans:
        outcome = "needs_human" if any(o["severity"] != "info" for o in plans) else "done"
    elif dropped or notes:
        outcome = "needs_human"   # something was found but nothing will be filed: a person must look
    elif args.get("outcome") == "needs_human" and "?" in (args.get("summary") or ""):
        outcome = "needs_human"   # a stated question for Matt
    else:
        outcome = "nothing_to_do"
    args["outcome"] = outcome
    return args, notes


def _rule_help():
    return "; ".join(f"{r} = {d}" for r, (d, _) in PLAN_RULES.items())


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
                    "rule": {"type": "string", "enum": list(PLAN_RULES),
                             "description": "exactly one of the listed rules (a closed vocabulary; if none "
                                            "fits, it is not a finding): " + _rule_help()},
                    "resource": {"type": "string", "pattern": PLAN_RESOURCE_RE.pattern,
                                 "description": "the ONE object the fix changes: <namespace>/<Kind>/<name>, Kind "
                                                "in its Kubernetes spelling, e.g. agents/NetworkPolicy/agent-base-"
                                                "egress; cluster-scoped objects and namespace-wide gaps use "
                                                "cluster/<Kind>/<name>, e.g. cluster/Namespace/media"},
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
