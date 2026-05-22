# Session Recap — 2026-05-22 (Horizon 2: Observability Complete)

This recap covers the completion of Horizon 2. The arc started with "what are our next horizon items?" — the user picked observability ("observability is king") — and ended with a fully live per-key LiteLLM usage dashboard and a suppressed silent-failure class in cAdvisor. The twist: H2 was ~70% already committed from the previous session (`86c5132`, `0ff937a`). The session's actual work was a live verification that exposed two real gaps hiding behind green checkmarks.

Context: H2's Phase 1 scaffolding (backup-freshness alerts, AutoKuma probes) is in `docs/recaps/2026-05-21-observability-phase1.md`. Phase 2 (Beelink node/GPU/container scraping, 10 alerts, dashboard) shipped at the end of 2026-05-21. This session is Phase 3: close the gaps that verification exposed.

---

## The Diagnostic Discipline Moment

Before writing a line of new code, a live Prometheus query was run against the already-committed configuration. The dashboard had been committed; the scrape config was live; the cAdvisor target showed `up=1`. By every green-light heuristic, this should have been done.

It wasn't. The Container CPU and Memory panels were silently empty. This is exactly the failure mode the project's "Prove the server path first" mandate exists to catch: a cached success (green Prometheus target) masking a broken backend (zero per-container series emitted). The rest of the session followed from that one query.

---

## Chapter 1 — cAdvisor: Green Target, Dead Data

### The problem

`beelink-cadvisor` on port `:8081` was `up=1` in Prometheus. No scrape errors. But every per-container `container_*` series was absent — the dashboard's Container CPU/Memory panels were silently blank.

On-box diagnosis: cAdvisor **v0.49.1** (2024 release) does not understand Docker 29's **containerd image store** (`Storage Driver: overlayfs` / `io.containerd.snapshotter.v1`). It expected the legacy graphdriver layout at `/var/lib/docker/image/overlay2/layerdb/mounts/<id>/mount-id`, which does not exist in Docker 29's containerd-backed store. Every container produced:

```
failed to identify the read-write layer ID
```

cAdvisor discovered the containers and reported the scrape as successful — it just emitted no data for any of them. The Prometheus target turned green while the underlying metrics were all null.

### Fix

Proven on-box with throwaway containers **before committing**: bumping to **v0.55.1** (which supports the containerd snapshotter store) plus adding `cgroupns: host` (required for cgroup v2 sibling-scope visibility) resolved it entirely. No per-container errors in logs; all container series present immediately.

Applied surgically: only the cAdvisor sidecar was recreated (Ollama, LiteLLM, OWUI, all other services undisturbed). Verified: 11 per-container series now ingesting (Ollama at 3.0 GiB VRAM, CPU rate live, no layer errors).

The dashboard was hardened at the same time: the Container CPU and Memory panel matchers were tightened from `name=~".+"` to `name!=""` — the regex variant evaluated flaky against freshly-arriving series; the negative-match form is stable.

### Commits

| Repo | Hash | Subject |
|---|---|---|
| beelink-ansible (local only) | `d91cc56` | fix(observability): cAdvisor v0.55.1 + cgroup:host for Docker 29 containerd store |
| pi-cluster | `1dd7131` | fix(monitoring): robust container-panel matcher + H2 status |

### The durable lesson

Captured in `.claude/skills/monitoring-ops/SKILL.md`:

> **cAdvisor on Docker 29+ (containerd image store):** v0.49.x emits zero per-container series and silently succeeds at the scrape level. Require v0.55.1+ and `cgroupns: host`. The scrape target will be green regardless — always verify that per-container series actually exist.

---

## Chapter 2 — LiteLLM Usage: Native Metrics Paywalled, Custom Exporter Built

### The problem

The last remaining H2 item was per-key LiteLLM token spend visibility. Live probe: `GET /metrics` returned **401** on OSS LiteLLM 1.85.1. Current docs confirmed: native Prometheus metrics are now an **Enterprise feature** (~$250/mo). This was not knowable from prior sessions.

The free path: the `/spend` REST API remains open-source. Empirically mapped what it exposes:

- `/spend/keys` — per-key cumulative spend + aliases
- `/spend/logs` — per-request token counts, duration, and the `api_key` → alias mapping

**Key finding on dollar-spend:** local Ollama models have no price data in LiteLLM's pricing table, so `spend_usd` is always ~0. **Token throughput and request latency are the real signals for a homelab LiteLLM instance.** Dollar-spend panels are a distraction.

### The exporter

Built `beelink-ansible/files/litellm-exporter.py` — stdlib-only Python, bind-mounted onto `python:3.12-alpine`. No third-party image to vet; same pattern as `gpu-metrics.sh`. It:

- Polls `/spend/keys` + `/spend/logs` on a configurable interval
- Deduplicates by `request_id` (crash-restart safe — no artificial rate spikes on restart)
- First poll only baselines the request log (no spike on container start)
- Exposes as Prometheus counters: `litellm_requests_total`, `litellm_tokens_total`, `litellm_request_duration_ms_sum`, `litellm_key_spend_usd` — all labeled by `key_alias` and `model`

Publishes on `:9101`.

### Least-privilege auth

The exporter authenticates with a **`proxy_admin_viewer` role** LiteLLM key — the `backup_ro` analogue for LiteLLM. Empirically validated before storing: `GET /spend/keys` and `GET /spend/logs` return 200; `POST /key/generate` and `POST /user/new` return 403. The key can read spend data and nothing else.

Stored at `op://pi-cluster/litellm-spend-exporter/password`. The value was created on the box and captured via stdin — never printed to a terminal.

This least-privilege design was also where the **op-unlock friction** surfaced: the 1Password CLI session lapsed mid-session at exactly the moment the viewer key needed to be stored. This is the precise motivation for H1.5 (make the Beelink GitOps-ready with a box-local 1Password service account). The friction was resolved manually this session; H1.5 is what eliminates it permanently.

### Cluster side

Three panels added to the "Beelink AI Load" dashboard:

| Panel | Metric | Why |
|---|---|---|
| Tokens/sec by key + model | `rate(litellm_tokens_total[5m])` | See which surface and model are driving load |
| Requests/sec by key | `rate(litellm_requests_total[5m])` | Identify bursty callers |
| Avg request latency by model | `rate(duration_ms_sum) / rate(requests_total)` | Catch model-level slowdowns |

The `beelink-litellm` scrape job (`:9101`) was added to the monitoring HelmRelease `additionalScrapeConfigs`.

End-to-end verification: fired a test inference request, confirmed `litellm_requests_total`, `litellm_tokens_total`, and `litellm_request_duration_ms_sum` all incremented. Flux reconciled; confirmed `up{job="beelink-litellm"}=1` and `litellm_*` series live in cluster Prometheus.

### Commits

| Repo | Hash | Subject |
|---|---|---|
| beelink-ansible (local only) | `a62e75b` | feat(observability): custom LiteLLM usage exporter sidecar |
| pi-cluster | `12e79e9` | feat(monitoring): scrape Beelink LiteLLM exporter + usage panels |
| pi-cluster | `4c506c1` | docs: mark H2 complete + Beelink observability runbook |

The durable lesson is captured in `.claude/skills/monitoring-ops/SKILL.md`:

> **LiteLLM native `/metrics` (OSS 1.85.1+):** returns 401 — this is now an Enterprise feature. Use the `/spend` API (open-source) + a custom exporter. Dollar-spend is always ~0 for local models; instrument tokens + latency instead.

---

## Verified End State

| Signal | Source | Status |
|---|---|---|
| Node metrics (CPU, RAM, disk) | `beelink-node` :9100 / node-exporter | Live |
| GPU/VRAM metrics | `beelink-node` :9100 / gpu-metrics textfile | Live |
| Per-container CPU/mem | `beelink-cadvisor` :8081 / cAdvisor v0.55.1 | Live (fixed this session) |
| LiteLLM request/token/latency | `beelink-litellm` :9101 / custom exporter | Live (added this session) |
| 10 Prometheus alerts | `prometheusrule-beelink.yaml` | Active, routing to Discord |
| AutoKuma probes | `ai.lab`, `chat.lab`, `dewey.lab` | Live |
| Grafana dashboard | "Beelink AI Load" — 11 panels | Live at `grafana.lab.mtgibbs.dev` |

H2 is complete per `docs/roadmap-2026-q2.md`.

---

## Commits Summary

### pi-cluster (pushed to main)

All H2 scaffolding from 2026-05-21:

| Hash | Subject |
|---|---|
| `38461b3` | feat(observability): backup-freshness alerts + AI-surface uptime probes |
| `86c5132` | feat(observability): scrape Beelink + GPU/stress alerts + load dashboard |
| `0ff937a` | feat(monitoring): add BeelinkBackupStale freshness alert |

This session (2026-05-22):

| Hash | Subject |
|---|---|
| `1dd7131` | fix(monitoring): robust container-panel matcher + H2 status |
| `12e79e9` | feat(monitoring): scrape Beelink LiteLLM exporter + usage panels |
| `4c506c1` | docs: mark H2 complete + Beelink observability runbook |

### beelink-ansible (local-only — no remote)

| Hash | Subject |
|---|---|
| `d91cc56` | fix(observability): cAdvisor v0.55.1 + cgroup:host for Docker 29 containerd store |
| `a62e75b` | feat(observability): custom LiteLLM usage exporter sidecar |

---

## Key Lessons

### Committed ≠ working. Verify live.

The biggest H2 gaps were not found in code review. They were found by querying a running Prometheus instance after everything was green. "Config committed, target up" is a necessary condition, not a sufficient one. The per-container series check took 30 seconds; the cAdvisor version problem would have sat unnoticed indefinitely.

### Green scrape targets don't mean data is flowing

cAdvisor can report `up=1` while emitting zero data — it scrapes successfully even when its internal container-discovery fails. When debugging missing dashboard panels, verify that the underlying series (`container_cpu_usage_seconds_total`, etc.) actually exist with `count by (name)(container_cpu_usage_seconds_total)` before looking anywhere else.

### Check current docs before assuming API stability

LiteLLM's `/metrics` was open in prior versions. It is paywalled now. A five-minute check of current docs before writing the scrape job would have reached the custom-exporter design immediately rather than after hitting the 401. For third-party service APIs that are changing (LiteLLM is a fast-moving OSS project), current docs beat prior knowledge.

### Least-privilege applies to exporters too

The spend exporter has `proxy_admin_viewer` role — it can read spend data and nothing else. This took one extra step (mint a scoped key via the `/key/generate` API, empirically verify the 200/403 boundary) and means a compromised exporter container cannot generate new keys, delete users, or modify the LiteLLM configuration. Same design as `backup_ro` for NAS access.

---

## What's Next

Per `docs/roadmap-2026-q2.md`:

- **H1.5 — Make the Beelink GitOps-ready.** The op-unlock friction this session surfaced is exactly what H1.5 is designed to eliminate. Box-local 1Password service account + publish beelink-ansible to GitHub + ansible-pull reconciler. The gate on letting an agent safely operate the Beelink without holding secrets.
- **H3 — Dewey + pipeline polish.** H3a (Dewey RAG rebuild) shipped in the parallel session today (`docs/recaps/2026-05-22-dewey-rag-rebuild.md`). H3b items remain.

---

## Related Documentation

- `.claude/skills/monitoring-ops/SKILL.md` — Beelink off-cluster scrape runbook (cAdvisor containerd gotcha + custom LiteLLM exporter design)
- `docs/roadmap-2026-q2.md` — H2 marked complete
- `docs/recaps/2026-05-21-observability-phase1.md` — H2 Phase 1: backup alerts + AutoKuma probes
- `clusters/pi-k3s/monitoring/prometheusrule-beelink.yaml` — 10 alert rules
- `clusters/pi-k3s/monitoring/dashboard-beelink.yaml` — 11-panel Grafana dashboard
- `beelink-ansible/files/litellm-exporter.py` — custom LiteLLM spend exporter
