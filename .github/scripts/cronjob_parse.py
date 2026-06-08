"""Shared CronJob extraction helpers.

Used by both the deterministic lint (`triggerable_lint.py`) and the LLM judge
harness (`scripts/triggerable-judge.py`) so they parse manifests identically.
Pure parsing — no policy, no severities. Keep judgement out of here.
"""

TRIGGERABLE_LABEL = "homelab.mcp/triggerable"


def job_spec_of(doc):
    """The jobTemplate.spec of a CronJob doc (the Job spec), or {}."""
    return (doc.get("spec", {}) or {}).get("jobTemplate", {}).get("spec", {}) or {}


def _containers(job_spec):
    pod = (job_spec or {}).get("template", {}).get("spec", {}) or {}
    return pod, (pod.get("initContainers") or []) + (pod.get("containers") or [])


def script_text(job_spec):
    """All command/args strings across init + main containers, newline-joined."""
    parts = []
    _, containers = _containers(job_spec)
    for c in containers:
        for key in ("command", "args"):
            v = c.get(key)
            if isinstance(v, list):
                parts.extend(str(x) for x in v)
            elif isinstance(v, str):
                parts.append(v)
    return "\n".join(parts)


def writable_shared_volumes(job_spec):
    """Names of NFS/PVC volumes mounted writable somewhere in the pod.

    Shared, persistent storage written by a job is where overlapping/repeated
    runs corrupt each other — so this is the set a concurrency check cares about.
    """
    pod, containers = _containers(job_spec)
    writable = {}  # volume name -> mounted writable anywhere
    for c in containers:
        for m in c.get("volumeMounts") or []:
            name = m.get("name")
            writable[name] = writable.get(name, False) or (not m.get("readOnly", False))
    out = []
    for v in pod.get("volumes") or []:
        if ("nfs" in v or "persistentVolumeClaim" in v) and writable.get(v.get("name"), False):
            out.append(v.get("name"))
    return out


def cronjobs_from_text(text):
    """Yield CronJob docs from a (possibly multi-doc) YAML string.

    Used when the manifest comes from an API fetch (no checkout) rather than a
    file on disk. Malformed YAML yields nothing rather than raising.
    """
    import yaml
    try:
        docs = list(yaml.safe_load_all(text))
    except yaml.YAMLError:
        return
    for doc in docs:
        if isinstance(doc, dict) and doc.get("kind") == "CronJob":
            yield doc


def iter_cronjobs(path):
    """Yield CronJob docs from a (possibly multi-doc) YAML file."""
    with open(path) as f:
        yield from cronjobs_from_text(f.read())
