# Agent sandbox — contracts (slice 1; burst handling in runner 0.2.0; plans, repo checkout and per-event models in runner 0.3.0 / runtime 0.2.0)

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
  by_event_type:                    # optional (runner 0.3.0): event.type -> its own list, used INSTEAD of allow
    security.sweep: [claude-sonnet, claude-haiku]   # the personal-data rule applies to every list
secret: agent-media-investigator    # k8s Secret in ns `agents`, envFrom'd into the Job. Holds AGENT_LITELLM_KEY
                                    # and any connector keys. The runner never reads it.
connectors:
  mcp:
    - name: homelab
      url: http://mcp-homelab.mcp-homelab.svc.cluster.local:3000/mcp
      header: X-API-Key
      key_env: MCP_HOMELAB_READONLY_KEY     # env var name inside the Job (from `secret`)
      tools: [get_media_status, get_cluster_health]   # allowlist; nothing else is offered to the model
checkout:                           # optional (runner 0.3.0, runtime 0.2.0): read-only repo copy, §4a
  source: flux-system/flux-system   # <namespace>/<name> of a Flux GitRepository; the HOST is the runner's
  include: [clusters/]              # optional: path prefixes to unpack (default: everything)
outputs: [report]                   # result output kinds this agent may return (report | plan, §5a)
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
  - 202 `{"run_id": "…", "status": "launched"}` when a slot is free, or 202
    `{"run_id": "…", "status": "queued", "position": N}` when `RUNNER_MAX_CONCURRENT` agent Jobs already
    exist (or others are already waiting). Either way the callback below arrives exactly as for a launch.
  - 200 with the existing run if (`event.id`, `agent`) was seen (queued, launched or finished);
    401 bad token; 404 unknown agent; 422 invalid manifest/event/callback; 503 when `RUNNER_PAUSED=true`.
  - 429 with one of three bodies: `{"error": "daily cap of N runs reached"}`, `{"error": "cluster quota
    exceeded"}`, or `{"error": "queue_full", "detail": "…"}` (the queue already holds `RUNNER_MAX_QUEUE`).
- `GET /runs/<run_id>` → the ledger record; `status` is `queued` (with `position`, 1 = next to start),
  `launched`, `launch_failed` or `finished`. `GET /healthz` → 200.
- On Job end — or when a queued run ends without ever getting a Job — the runner POSTs to `callback`:
  `{"run_id", "agent", "event_id", "started", "finished", "exit_reason", "result": <Result>}`.
  `started` is when the Job was created (`null` if it never was). `exit_reason`: `completed` | `deadline` |
  `job_failed` | `no_result` | `invalid_result` | `queue_expired` (queued longer than
  `RUNNER_MAX_QUEUE_WAIT`; `result.outcome` is `failed`, no outputs). Retries 3×.

Runner env: `RUNNER_API_TOKEN`, `RUNNER_NAMESPACE` (agents), `RUNNER_MANIFEST_DIR` (/etc/agents),
`RUNNER_LEDGER_PATH`, `RUNNER_CALLBACK_PREFIXES`, `RUNNER_LOCAL_MODELS` (comma list), `RUNNER_PAUSED`,
`RUNNER_LITELLM_BASE_URL` (passed to Jobs as `LITELLM_BASE_URL`), `RUNNER_NODE_HOSTNAMES` (comma list for
required node affinity on `kubernetes.io/hostname`), `RUNNER_MAX_CONCURRENT` (default 2),
`RUNNER_MAX_QUEUE` (default 8), `RUNNER_MAX_QUEUE_WAIT` (default `45m`, `Ns`/`Nm`/`Nh`),
`RUNNER_CHECKOUT_BASE_URL` (default `http://source-controller.flux-system.svc.cluster.local.`, §4a).

## 4. The Job the runner renders (ns `agents`)

- name `run-<run_id>`; labels `app.kubernetes.io/part-of: agent-sandbox`, `agent: <name>`, `run-id: <run_id>`
  (on Job and pod: NetworkPolicies select on `agent`).
- `backoffLimit: 0`, `activeDeadlineSeconds` from the manifest, `ttlSecondsAfterFinished: 3600`,
  `restartPolicy: Never`, `serviceAccountName: agent-run`, `automountServiceAccountToken: false`.
- Pod security `restricted`: runAsNonRoot, uid/gid 10001, seccomp RuntimeDefault; container
  `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, `capabilities.drop: [ALL]`.
- One `emptyDir` (sizeLimit 1Gi) at `/work`; env `HOME=/work/home`, `TMPDIR=/work/tmp`.
- env: `AGENT_MANIFEST` (manifest as JSON), `AGENT_EVENT` (event as JSON), `AGENT_RUN_ID`, `LITELLM_BASE_URL`;
  `envFrom` the manifest's `secret`. `AGENT_MANIFEST` carries the **effective** model list: `model` is
  `{"allow": <by_event_type[event.type] or allow>}`, so the runtime never sees `by_event_type`.
- No `command`/`args`: the image's entrypoint runs the agent.
- With `checkout:` — see §4a.

## 4a. Repo checkout (manifest `checkout:`)

An agent that reads a repository gets it **without internet egress**: Flux's source-controller already holds the
repo as an artifact (a `.tar.gz` of the tree at one revision) and serves it over in-cluster HTTP.

- The Job gets an **init container** `checkout`: the manifest's `image`, `command: ["python", "/app/checkout.py"]`,
  the same restricted securityContext and resources, **no `envFrom`** (it needs no credential), mounts `work` and a
  second `emptyDir` `repo` (sizeLimit 256Mi) at `/repo`. Env: `CHECKOUT_URL`, `CHECKOUT_FALLBACK_URL`,
  `CHECKOUT_DEST=/repo/tree`, `CHECKOUT_INFO=/repo/checkout.json`, `CHECKOUT_INCLUDE` (JSON list), `HOME`, `TMPDIR`.
- The agent container mounts `repo` at `/repo` **read-only** and gets `AGENT_REPO_DIR=/repo/tree`,
  `AGENT_CHECKOUT_INFO=/repo/checkout.json`.
- URLs: `<RUNNER_CHECKOUT_BASE_URL>/gitrepository/<ns>/<name>/<file>`. `<file>` is `<sha>.tar.gz` when
  `event.data.revision` is exactly 40 lowercase hex characters (then `CHECKOUT_FALLBACK_URL` is `latest.tar.gz`, used
  on a 404 because source-controller garbage-collects old artifacts), else `latest.tar.gz` with no fallback. No other
  event field reaches the URL, and the manifest cannot choose the host.
- `checkout.py` downloads (≤ 32 MiB), then unpacks **by hand**: regular files and directories only (symlinks, hard
  links, devices skipped), member names that are absolute or contain `..`, NUL or `\` skipped, ≤ 10,000 files,
  ≤ 128 MiB unpacked, ≤ 8 MiB per file, `include` prefixes applied. It **always exits 0** and writes
  `checkout.json` `{"ok": true|false, "requested", "served", "sha256", "files", …, "error"}`.
- **Retry (runtime ≥ 0.2.1):** connection-level failures (refused, reset, timeout, DNS) are retried with backoff
  (0.5 s doubling, capped at 8 s) inside one `CHECKOUT_RETRY_BUDGET` (default 45 s) shared by the sha fetch and the
  fallback — a new pod's first connection can be refused while kube-router is still programming its rules. A clean
  404 on the sha is never retried; it goes straight to `latest.tar.gz`. Each attempt logs `"event":
  "checkout_attempt"` (`kind` sha|latest, `attempt`, `outcome`, `error` class). On give-up the error reads `could not
  fetch the <sha|latest> artifact: <ErrorClass> after <n> attempts` — no URL or host. `CHECKOUT_TIMEOUT` (default
  15 s) is per socket operation.
- The runtime reads `checkout.json`: `ok: false` (or a missing file) is a `failed` Result, "repository checkout
  failed: …". Otherwise it offers the model `repo__list_files`, `repo__read_file`, `repo__search` (§6) and tells it
  which artifact it got (and, when `served != requested`, that it is reading a newer revision).
- Network: the pod needs egress to source-controller :9090 and source-controller needs a matching ingress allow;
  both are NetworkPolicies naming the agent (`clusters/pi-k3s/agents/networkpolicies.yaml` 3b and 5).

## 5. Result (agent → runner)

The agent's **last stdout line** is `::agent-result::<base64 of the Result JSON>`.

```json
{"outcome": "done|nothing_to_do|needs_human|failed", "summary": "<= 2048 chars",
 "outputs": [{"kind": "report", "title": "…", "body": "markdown, <= 32 KiB"}]}
```
The runner reads it from the pod log, and rejects it (`invalid_result`, outcome forced to `failed`) if the JSON is
malformed, `outcome` is unknown, any `outputs[].kind` is not in the manifest's `outputs`, or any output does not
match its kind's exact shape (`report` and other prose kinds: exactly `kind/title/body`; `plan`: §5a). No marker
line → `no_result`. The runner treats the result as data and never executes anything in it.

### 5a. `plan` outputs (runner 0.3.0)

A structured finding. It carries **no** issue URL: the agent holds no GitHub credential, and n8n files plans
(`docs/agent-sandbox-n8n.md`, "sec-researcher").

```json
{"kind": "plan", "title": "one line, <= 200 chars", "severity": "critical|high|medium|low|info",
 "fingerprint": {"rule": "netpol-broad-egress", "resource": "agents/NetworkPolicy/agent-base-egress"},
 "plan": {"found": "…", "evidence": "…", "likely_cause": "…", "proposed_change": "… or 'No change needed.'",
          "risk": "…", "verify": "…", "rollback": "…"}}
```
- Exact keys at every level; every section a non-empty string; `evidence` ≤ 8 KiB, every other section ≤ 4 KiB
  (UTF-8); `title` one line.
- `fingerprint.rule`: `^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$`. `fingerprint.resource`:
  `<namespace | cluster>/<Kind>/<name>`, `^[a-z0-9][a-z0-9.-]{0,62}/[A-Z][A-Za-z0-9]{0,62}/[A-Za-z0-9][A-Za-z0-9._:-]{0,252}$`.
- n8n's identity for a finding is `sha256("<agent>|<rule>|<resource>")`.
- The runtime offers this schema to the model, bounces a malformed plan back to it, and at emit truncates oversize
  sections and drops a plan it cannot repair (saying so in the summary), so the runner should never have to reject.

## 6. Agent runtime (image `agent-runtime`)

Stdlib-only Python. Reads `AGENT_MANIFEST` / `AGENT_EVENT`; talks to LiteLLM's OpenAI-compatible
`$LITELLM_BASE_URL/chat/completions` with `Authorization: Bearer $AGENT_LITELLM_KEY`; connects to each MCP server
(streamable HTTP, JSON-RPC) and offers the model **only** the allowlisted tools, named `<connector>__<tool>`, plus
a built-in `submit_result` tool whose arguments are the Result, plus — only with `checkout:` (§4a) — three local,
read-only file tools over `AGENT_REPO_DIR`: `repo__list_files`, `repo__read_file` (≤ 800 lines / 64 KiB per call),
`repo__search` (literal substring, never a regex; ≤ 100 matches). Paths are relative with no `..`, no NUL/backslash;
every component is `lstat`ed and any symlink is refused; the resolved path must stay under the root; walks never
follow links; files over 2 MiB and binary files are refused. The loop ends when `submit_result` is called, at
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

## 7a. Settled while building burst handling (runner 0.2.0, 2026-11-11)

- **The gate counts the runner's own unfinished runs** (Job created, callback not yet sent), not pods.
  It is conservative: a slot frees when the runner has seen the Job end and delivered the callback.
  `agents` ResourceQuota `pods` must stay `RUNNER_MAX_CONCURRENT + 1` (the runner's own pod).
- **Strict FIFO.** A POST takes a free slot directly only when nobody is queued; otherwise it queues
  behind them. A slot freed by a finishing run starts the queue head at once; a 5 s dispatcher tick also
  expires stale runs and retries a deferred start.
- **The deadline starts at Job creation.** `started` (ledger and callback) is the Job-create time;
  `accepted` is the POST time. `activeDeadlineSeconds` and the runner's own `timeout + 300 s` safety net
  both count from creation. Queue wait counts from `accepted`, across restarts.
- **The daily cap counts at accept**: a queued run counts, a `queue_full` refusal does not, and a
  `queue_expired` run still counts. Dedupe on (`event.id`, `agent`) covers queued runs too.
- **The manifest is re-read when a queued run starts**, not frozen at accept. If it no longer loads,
  that run ends `job_failed` (summary says why) with the normal callback.
- **Starting a queued run:** a quota refusal or an API transport error leaves it at the head, retried on
  the next tick (bounded by the queue wait); any other Kubernetes error ends that run `job_failed`.
- **`RUNNER_PAUSED` also stops queued runs from starting**; they stay queued and expire normally.
- **Restarts.** Since 0.1.0 the runner re-adopts launched runs from the ledger (keeps watching their
  Jobs, sends their callbacks). Queued runs survive the same way: the ledger records them (identifiers
  only, as ever), and the event of each queued run is kept in a spool file next to the ledger
  (`<ledger dir>/queue/<run_id>.json`, mode 0600, on the PVC) until its Job is created or it ends,
  then deleted. On start the queue is rebuilt in accept order; orphan spool files are deleted; a
  queued run whose spool file is missing ends `job_failed` ("the queued event was lost").
  The callback URL, and with it n8n's Wait, outlives the restart, so the result still arrives.
