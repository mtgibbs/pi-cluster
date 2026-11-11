# Agent sandbox — contracts (slice 1)

Design: `docs/design/agent-sandbox.md` (PR #258). Four parts: n8n decides *when*, the **runner** decides *how*,
the **agent runtime** image decides *what*, existing gates decide *whether*. These contracts are what the parts
share. Change them here first.

## 1. Event (n8n → runner → agent)

```json
{"id": "01JD...", "type": "media.hang", "source": "matt", "subject": "jellyfin:apple-tv",
 "dedupe_key": "...", "trust": "internal", "data": {"ask": "free text"}}
```
Required: `id`, `type`, `source`, `subject`, `trust` (`internal`|`external`), `data` (object). Whole event ≤ 64 KiB.

## 2. Agent manifest — `clusters/pi-k3s/agents/manifests/<name>.yaml`

```yaml
kind: Agent
name: media-investigator            # [a-z0-9-]+, must equal the file name
purpose: "one line"
image: ghcr.io/mtgibbs/agent-runtime:0.1.0
data_class: system                  # system | personal. personal => every model must be in RUNNER_LOCAL_MODELS
model:
  allow: [hot-coder, claude-haiku]  # tried in order; next one on API error
secret: agent-media-investigator    # k8s Secret in ns `agents`, envFrom'd into the Job. Holds AGENT_LITELLM_KEY
                                    # and any connector keys. The runner never reads it.
connectors:
  mcp:
    - name: homelab
      url: http://mcp-homelab.mcp-homelab.svc.cluster.local:3000/mcp
      header: X-API-Key
      key_env: MCP_HOMELAB_READONLY_KEY     # env var name inside the Job (from `secret`)
      tools: [get_media_status, get_cluster_health]   # allowlist; nothing else is offered to the model
outputs: [report]                   # result output kinds this agent may return
prompt: |
  multi-line instructions for the agent
limits:
  timeout: 15m                      # -> activeDeadlineSeconds
  runs_per_day: 10
  max_steps: 30                     # model/tool round trips
resources: {requests: {cpu: 200m, memory: 256Mi}, limits: {cpu: "1", memory: 512Mi}}   # optional
```
Unknown top-level keys are an error. A manifest that fails validation is never launched (HTTP 422).

## 3. Runner HTTP API (in-cluster only, port 8080)

All except `/healthz` need `Authorization: Bearer $RUNNER_API_TOKEN`.

- `POST /runs` body `{"agent": "<name>", "event": {…}, "callback": "<url>"}`
  - `callback` must start with one of `RUNNER_CALLBACK_PREFIXES` (comma-separated), else 422.
  - 202 `{"run_id": "…", "status": "launched"}`; 200 with the existing run if (`event.id`, `agent`) was seen;
    401 bad token; 404 unknown agent; 422 invalid manifest/event/callback; 429 daily cap or cluster quota;
    503 when `RUNNER_PAUSED=true`.
- `GET /runs/<run_id>` → the ledger record. `GET /healthz` → 200.
- On Job end the runner POSTs to `callback`:
  `{"run_id", "agent", "event_id", "started", "finished", "exit_reason", "result": <Result>}`.
  `exit_reason`: `completed` | `deadline` | `job_failed` | `no_result` | `invalid_result`. Retries 3×.

Runner env: `RUNNER_API_TOKEN`, `RUNNER_NAMESPACE` (agents), `RUNNER_MANIFEST_DIR` (/etc/agents),
`RUNNER_LEDGER_PATH`, `RUNNER_CALLBACK_PREFIXES`, `RUNNER_LOCAL_MODELS` (comma list), `RUNNER_PAUSED`,
`RUNNER_LITELLM_BASE_URL` (passed to Jobs as `LITELLM_BASE_URL`), `RUNNER_NODE_HOSTNAMES` (comma list for
required node affinity on `kubernetes.io/hostname`).

## 4. The Job the runner renders (ns `agents`)

- name `run-<run_id>`; labels `app.kubernetes.io/part-of: agent-sandbox`, `agent: <name>`, `run-id: <run_id>`
  (on Job and pod: NetworkPolicies select on `agent`).
- `backoffLimit: 0`, `activeDeadlineSeconds` from the manifest, `ttlSecondsAfterFinished: 3600`,
  `restartPolicy: Never`, `serviceAccountName: agent-run`, `automountServiceAccountToken: false`.
- Pod security `restricted`: runAsNonRoot, uid/gid 10001, seccomp RuntimeDefault; container
  `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, `capabilities.drop: [ALL]`.
- One `emptyDir` (sizeLimit 1Gi) at `/work`; env `HOME=/work/home`, `TMPDIR=/work/tmp`.
- env: `AGENT_MANIFEST` (manifest as JSON), `AGENT_EVENT` (event as JSON), `AGENT_RUN_ID`, `LITELLM_BASE_URL`;
  `envFrom` the manifest's `secret`.
- No `command`/`args`: the image's entrypoint runs the agent.

## 5. Result (agent → runner)

The agent's **last stdout line** is `::agent-result::<base64 of the Result JSON>`.

```json
{"outcome": "done|nothing_to_do|needs_human|failed", "summary": "<= 2048 chars",
 "outputs": [{"kind": "report", "title": "…", "body": "markdown, <= 32 KiB"}]}
```
The runner reads it from the pod log, and rejects it (`invalid_result`, outcome forced to `failed`) if the JSON is
malformed, `outcome` is unknown, or any `outputs[].kind` is not in the manifest's `outputs`. No marker line →
`no_result`. The runner treats the result as data and never executes anything in it.

## 6. Agent runtime (image `agent-runtime`)

Stdlib-only Python. Reads `AGENT_MANIFEST` / `AGENT_EVENT`; talks to LiteLLM's OpenAI-compatible
`$LITELLM_BASE_URL/chat/completions` with `Authorization: Bearer $AGENT_LITELLM_KEY`; connects to each MCP server
(streamable HTTP, JSON-RPC) and offers the model **only** the allowlisted tools, named `<connector>__<tool>`, plus
a built-in `submit_result` tool whose arguments are the Result. The loop ends when `submit_result` is called, at
`max_steps`, or on an unrecoverable error (then it emits an `outcome: failed` Result itself). Event content is
passed to the model fenced as data, with `trust` stated.

## 7. Settled while building (2026-11-11)

- **Sizes.** Body ≤ 32 KiB of UTF-8; summary ≤ 2048 characters; at most 20 outputs; the decoded Result ≤ 256 KiB
  (the runtime keeps itself under 240 KiB by dropping trailing outputs and saying so in the summary).
- **The marker must be the last non-empty log line.** The runner reads the whole pod log, not a tail.
- **`limits.timeout`** is `Ns`, `Nm` or `Nh`. The runtime stops itself shortly before it, so a `failed` Result is
  still printed; the runner deletes a Job still running 300 s past it and reports `deadline`.
- **Model fallback is sticky**: once a model errors, later steps stay on the next one.
- **Any connector down at start fails the run.**
- **Callbacks are at-least-once**; the receiver dedupes on `run_id`. The runner sends no credential of its own: with
  n8n's Wait node the callback URL carries a per-execution `signature`, which n8n checks. Callback prefixes must end
  in `/`. The callback URL is kept in the ledger (needed to re-send after a restart) and is never logged.
- **Runner statuses beyond §3:** 502 for a Kubernetes error other than quota; 422 for a malformed or oversize body.
  A replay of a known (`event.id`, `agent`) returns 200 even while paused.
- **The daily cap** counts per UTC day; failed launches do not count.
- **The agent runtime creates `$HOME` and `$TMPDIR`** itself; the volume at `/work` starts empty.
