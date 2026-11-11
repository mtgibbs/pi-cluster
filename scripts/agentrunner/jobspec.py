"""Render the agent Job exactly per CONTRACT.md §4."""
import json

UID = 10001
CONTAINER = "agent"
TTL_AFTER_FINISHED = 3600
SERVICE_ACCOUNT = "agent-run"
PART_OF = "agent-sandbox"
# Applied only when the manifest omits `resources` — a namespace ResourceQuota on cpu/memory
# rejects pods that declare none.
DEFAULT_RESOURCES = {"requests": {"cpu": "100m", "memory": "128Mi"},
                     "limits": {"cpu": "1", "memory": "512Mi"}}


def job_name(run_id):
    return f"run-{run_id}"


def labels(agent, run_id):
    return {"app.kubernetes.io/part-of": PART_OF, "agent": agent, "run-id": run_id}


def render_job(run_id, manifest, event, timeout_s, namespace, litellm_base_url, node_hostnames=()):
    agent = manifest["name"]
    lbl = labels(agent, run_id)
    env = [
        {"name": "AGENT_MANIFEST", "value": json.dumps(manifest, separators=(",", ":"))},
        {"name": "AGENT_EVENT", "value": json.dumps(event, separators=(",", ":"))},
        {"name": "AGENT_RUN_ID", "value": run_id},
        {"name": "LITELLM_BASE_URL", "value": litellm_base_url},
        {"name": "HOME", "value": "/work/home"},
        {"name": "TMPDIR", "value": "/work/tmp"},
    ]
    container = {
        "name": CONTAINER,
        "image": manifest["image"],
        "imagePullPolicy": "IfNotPresent",
        # No command/args: the image's entrypoint runs the agent.
        "env": env,
        "envFrom": [{"secretRef": {"name": manifest["secret"]}}],
        "resources": manifest.get("resources") or DEFAULT_RESOURCES,
        "securityContext": {
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": True,
            "runAsNonRoot": True,
            "capabilities": {"drop": ["ALL"]},
        },
        "volumeMounts": [{"name": "work", "mountPath": "/work"}],
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
        "volumes": [{"name": "work", "emptyDir": {"sizeLimit": "1Gi"}}],
    }
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
