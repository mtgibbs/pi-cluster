"""Render the agent Job exactly per CONTRACT.md §4."""
import copy
import json
import re

import agentspec

UID = 10001
CONTAINER = "agent"
TTL_AFTER_FINISHED = 3600
SERVICE_ACCOUNT = "agent-run"
PART_OF = "agent-sandbox"
# Applied only when the manifest omits `resources` — a namespace ResourceQuota on cpu/memory
# rejects pods that declare none.
DEFAULT_RESOURCES = {"requests": {"cpu": "100m", "memory": "128Mi"},
                     "limits": {"cpu": "1", "memory": "512Mi"}}

# Repo checkout (manifest `checkout:`, CONTRACT §4a). An init container — same image, its own
# entrypoint — fetches the Flux source-controller artifact into the `repo` emptyDir; the agent
# container mounts that volume READ-ONLY. Only the init container ever writes it.
CHECKOUT_CONTAINER = "checkout"
CHECKOUT_MOUNT = "/repo"
CHECKOUT_TREE = CHECKOUT_MOUNT + "/tree"      # AGENT_REPO_DIR: what the file tools are confined to
CHECKOUT_INFO = CHECKOUT_MOUNT + "/checkout.json"
CHECKOUT_VOLUME_LIMIT = "256Mi"
CHECKOUT_COMMAND = ["python", "/app/checkout.py"]
DEFAULT_CHECKOUT_BASE_URL = "http://source-controller.flux-system.svc.cluster.local."
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# A Flux artifact revision: "main@sha1:<sha>" (source-controller v1), "<branch>/<sha>" (pre-v1), or a bare sha.
ARTIFACT_REVISION_RE = re.compile(r"(?:^|[@:/])([0-9a-f]{40})$")


def job_name(run_id):
    return f"run-{run_id}"


def labels(agent, run_id):
    return {"app.kubernetes.io/part-of": PART_OF, "agent": agent, "run-id": run_id}


def effective_manifest(manifest, event):
    """The manifest as the agent sees it: model.allow resolved for this event's type
    (model.by_event_type), by_event_type removed. The runtime only ever reads model.allow."""
    eff = copy.deepcopy(manifest)
    eff["model"] = {"allow": agentspec.models_for(manifest, (event or {}).get("type"))}
    return eff


def event_revision(event):
    """event.data.revision when it is exactly 40 lowercase hex characters, else None."""
    rev = ((event or {}).get("data") or {}).get("revision")
    return rev if isinstance(rev, str) and SHA_RE.match(rev) else None


def artifact_sha(gitrepository):
    """The commit sha of the artifact a Flux GitRepository object currently serves
    (.status.artifact.revision), or None. source-controller names that artifact `<sha>.tar.gz`."""
    if not isinstance(gitrepository, dict):
        return None
    art = (gitrepository.get("status") or {}).get("artifact") or {}
    rev = art.get("revision") if isinstance(art, dict) else None
    m = ARTIFACT_REVISION_RE.search(rev) if isinstance(rev, str) else None
    return m.group(1) if m else None


def checkout_urls(manifest, event, base_url, current_sha=None):
    """(primary, fallback) artifact URLs. Flux source-controller serves a GitRepository's artifact at
    /gitrepository/<ns>/<name>/<commit sha>.tar.gz — and ONLY by sha: there is no latest.tar.gz (the
    v1 API dropped that symlink; source-controller ≥ v1.0 deletes it) and old artifacts are
    garbage-collected soon after a newer one is stored. `current_sha` is the revision the runner read from
    the GitRepository's .status.artifact just before rendering (None if it could not).

    - The event names a revision (event.data.revision, 40 hex): primary is exactly that artifact, fallback
      the current one when it differs (the event's may already be garbage-collected).
    - It does not (manual / scheduled runs): primary is the current artifact, no fallback.
    Returns ("", "") when there is nothing to fetch; the caller refuses the run rather than launch a
    checkout that cannot succeed. Nothing else from the event is ever put in a URL."""
    ns, name = manifest["checkout"]["source"].split("/", 1)
    root = f"{base_url.rstrip('/')}/gitrepository/{ns}/{name}/"
    cur = current_sha if isinstance(current_sha, str) and SHA_RE.match(current_sha) else None
    rev = event_revision(event)
    if rev:
        return root + f"{rev}.tar.gz", (root + f"{cur}.tar.gz" if cur and cur != rev else "")
    if cur:
        return root + f"{cur}.tar.gz", ""
    return "", ""


def render_job(run_id, manifest, event, timeout_s, namespace, litellm_base_url, node_hostnames=(),
               checkout_base_url=DEFAULT_CHECKOUT_BASE_URL, checkout_sha=None):
    """The Job for one run. `checkout_sha`: the artifact revision source-controller currently serves for
    the manifest's checkout.source (see checkout_urls); unused without `checkout:`."""
    agent = manifest["name"]
    lbl = labels(agent, run_id)
    eff = effective_manifest(manifest, event)
    env = [
        {"name": "AGENT_MANIFEST", "value": json.dumps(eff, separators=(",", ":"))},
        {"name": "AGENT_EVENT", "value": json.dumps(event, separators=(",", ":"))},
        {"name": "AGENT_RUN_ID", "value": run_id},
        {"name": "LITELLM_BASE_URL", "value": litellm_base_url},
        {"name": "HOME", "value": "/work/home"},
        {"name": "TMPDIR", "value": "/work/tmp"},
    ]
    security = {
        "allowPrivilegeEscalation": False,
        "readOnlyRootFilesystem": True,
        "runAsNonRoot": True,
        "capabilities": {"drop": ["ALL"]},
    }
    resources = manifest.get("resources") or DEFAULT_RESOURCES
    mounts = [{"name": "work", "mountPath": "/work"}]
    volumes = [{"name": "work", "emptyDir": {"sizeLimit": "1Gi"}}]
    init_containers = []
    if manifest.get("checkout"):
        primary, fallback = checkout_urls(manifest, event, checkout_base_url, checkout_sha)
        if not primary:
            raise ValueError("render_job: no checkout artifact to fetch (resolve it first)")
        env.append({"name": "AGENT_REPO_DIR", "value": CHECKOUT_TREE})
        env.append({"name": "AGENT_CHECKOUT_INFO", "value": CHECKOUT_INFO})
        volumes.append({"name": "repo", "emptyDir": {"sizeLimit": CHECKOUT_VOLUME_LIMIT}})
        mounts.append({"name": "repo", "mountPath": CHECKOUT_MOUNT, "readOnly": True})
        init_containers.append({
            "name": CHECKOUT_CONTAINER,
            "image": manifest["image"],
            "imagePullPolicy": "IfNotPresent",
            "command": list(CHECKOUT_COMMAND),
            # No envFrom: the checkout step holds no credential at all (the artifact server is
            # unauthenticated in-cluster HTTP).
            "env": [
                {"name": "CHECKOUT_URL", "value": primary},
                {"name": "CHECKOUT_FALLBACK_URL", "value": fallback},
                {"name": "CHECKOUT_DEST", "value": CHECKOUT_TREE},
                {"name": "CHECKOUT_INFO", "value": CHECKOUT_INFO},
                {"name": "CHECKOUT_INCLUDE",
                 "value": json.dumps(manifest["checkout"].get("include") or [])},
                {"name": "HOME", "value": "/work/home"},
                {"name": "TMPDIR", "value": "/work/tmp"},
            ],
            "resources": resources,
            "securityContext": dict(security, capabilities={"drop": ["ALL"]}),
            "volumeMounts": [{"name": "work", "mountPath": "/work"},
                             {"name": "repo", "mountPath": CHECKOUT_MOUNT}],
        })
    container = {
        "name": CONTAINER,
        "image": manifest["image"],
        "imagePullPolicy": "IfNotPresent",
        # No command/args: the image's entrypoint runs the agent.
        "env": env,
        "envFrom": [{"secretRef": {"name": manifest["secret"]}}],
        "resources": resources,
        "securityContext": security,
        "volumeMounts": mounts,
    }
    pod_spec = {
        "restartPolicy": "Never",
        "serviceAccountName": SERVICE_ACCOUNT,
        "automountServiceAccountToken": False,
        "enableServiceLinks": False,
        "securityContext": {
            "runAsNonRoot": True,
            "runAsUser": UID,
            "runAsGroup": UID,
            "fsGroup": UID,
            "seccompProfile": {"type": "RuntimeDefault"},
        },
        "containers": [container],
        "volumes": volumes,
    }
    if init_containers:
        pod_spec["initContainers"] = init_containers
    hosts = [h for h in node_hostnames if h]
    if hosts:
        pod_spec["affinity"] = {"nodeAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": {
            "nodeSelectorTerms": [{"matchExpressions": [
                {"key": "kubernetes.io/hostname", "operator": "In", "values": hosts}]}]}}}
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": job_name(run_id), "namespace": namespace, "labels": dict(lbl)},
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": int(timeout_s),
            "ttlSecondsAfterFinished": TTL_AFTER_FINISHED,
            "template": {"metadata": {"labels": dict(lbl)}, "spec": pod_spec},
        },
    }
