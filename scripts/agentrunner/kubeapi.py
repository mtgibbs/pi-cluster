"""Minimal Kubernetes REST client for the agent runner (stdlib urllib, in-pod SA token + CA).

Deliberately narrow: create/get/delete Jobs, list Pods by label, read a Pod's log — all in one
namespace — plus one read outside it: GET a Flux GitRepository, to learn which artifact source-controller
serves for a manifest's `checkout.source` (RBAC allows exactly that one object, see agents/rbac.yaml).
There is no generic GET, so this client cannot be pointed at Secrets (the runner never reads them; the
agent's Secret is only ever *referenced* by name in the Job's envFrom).
"""
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request

SA_DIR = "/var/run/secrets/kubernetes.io/serviceaccount"


class KubeError(Exception):
    def __init__(self, status, message):
        super().__init__(f"kubernetes API {status}: {message}")
        self.status = status
        self.message = message

    @property
    def quota_exceeded(self):
        # ResourceQuota admission rejects with 403 Forbidden "... exceeded quota: ..."
        return self.status == 403 and "exceeded quota" in self.message


class KubeClient:
    def __init__(self, namespace, sa_dir=SA_DIR, timeout=15):
        host = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
        port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"  # IPv6 service IP
        self.base = f"https://{host}:{port}"
        self.ns = namespace
        self.token_path = os.path.join(sa_dir, "token")
        self.ctx = ssl.create_default_context(cafile=os.path.join(sa_dir, "ca.crt"))
        self.timeout = timeout

    def _request(self, method, path, body=None, query=None, text=False):
        url = self.base + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        # Re-read per call: projected SA tokens are rotated by the kubelet.
        with open(self.token_path) as f:
            token = f.read().strip()
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Accept", "*/*" if text else "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            msg = e.read()[:4096].decode("utf-8", "replace")
            try:
                msg = json.loads(msg).get("message", msg)
            except (ValueError, AttributeError):
                pass
            raise KubeError(e.code, msg) from None
        if text:
            return raw.decode("utf-8", "replace")
        return json.loads(raw or b"{}")

    def _jobs(self, name=None):
        p = f"/apis/batch/v1/namespaces/{urllib.parse.quote(self.ns, safe='')}/jobs"
        return p + (f"/{urllib.parse.quote(name, safe='')}" if name else "")

    def create_job(self, job):
        return self._request("POST", self._jobs(), body=job)

    def get_job(self, name):
        """The Job object, or None if it does not exist."""
        try:
            return self._request("GET", self._jobs(name))
        except KubeError as e:
            if e.status == 404:
                return None
            raise

    def delete_job(self, name):
        try:
            self._request("DELETE", self._jobs(name), body={"propagationPolicy": "Background"})
        except KubeError as e:
            if e.status != 404:
                raise

    def list_pods(self, label_selector):
        ns = urllib.parse.quote(self.ns, safe="")
        out = self._request("GET", f"/api/v1/namespaces/{ns}/pods",
                            query={"labelSelector": label_selector})
        return out.get("items") or []

    def pod_log(self, pod, container=None, tail_lines=None, limit_bytes=None):
        ns = urllib.parse.quote(self.ns, safe="")
        q = {}
        if container:
            q["container"] = container
        if tail_lines is not None:
            q["tailLines"] = str(tail_lines)
        if limit_bytes is not None:
            q["limitBytes"] = str(limit_bytes)
        pod_q = urllib.parse.quote(pod, safe="")
        return self._request("GET", f"/api/v1/namespaces/{ns}/pods/{pod_q}/log",
                             query=q or None, text=True)

    def get_gitrepository(self, namespace, name):
        """A Flux source.toolkit.fluxcd.io/v1 GitRepository (its .status.artifact names the served
        tarball). Raises KubeError (403 when RBAC does not cover it, 404 when absent)."""
        ns = urllib.parse.quote(namespace, safe="")
        n = urllib.parse.quote(name, safe="")
        return self._request("GET", f"/apis/source.toolkit.fluxcd.io/v1/namespaces/{ns}/gitrepositories/{n}")
