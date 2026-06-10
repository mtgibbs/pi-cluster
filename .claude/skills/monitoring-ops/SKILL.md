---
name: monitoring-ops
description: Expert knowledge for cluster observability. Use when configuring Prometheus/Grafana, Alertmanager, Uptime Kuma, or the Homepage dashboard.
allowed-tools: Bash, Read, Grep, Glob, Edit, Write
---

# Monitoring Operations

## Stack Overview
- **Core**: `kube-prometheus-stack` (Prometheus, Grafana, Alertmanager)
- **Status Page**: Uptime Kuma (with AutoKuma for GitOps)
- **Dashboard**: Homepage (unified view)

## Prometheus & Alerting

### Configuration
- Managed via Flux HelmRelease in `monitoring` namespace.
- **Alertmanager**: Routes alerts to Discord.
- **Webhook**: Synced from 1Password (`alertmanager/discord-alerts-webhook-url`).

### Active Rules
- **Immich**: Server down, Queue stuck, Slow queries.
- **Kubernetes**: Standard node/pod health checks.

## Uptime Kuma
- **URL**: `https://status.lab.mtgibbs.dev`
- **AutoKuma**: Manages monitors-as-code via `ConfigMap/autokuma-monitors`. **v2.0.0**, matched to Uptime Kuma **v2** (`louislam/uptime-kuma:2`). The plain AutoKuma image tag targets Kuma v2; `uptime-kuma-v1-*` tags exist for v1. AutoKuma `0.7.0` predated Kuma-v2 and was silently broken.
- **Storage**: PVC for Kuma's `sled` DB + AutoKuma's `/data` tracking DB (v1.0.0+ tracks managed entities in a DB, not Kuma labels).
- **Credentials**: Synced from 1Password (`uptime-kuma` item), incl. `discord-webhook-url`.

### AutoKuma v2 gotchas (learned the hard way 2026-06-10 — see recap)
- **Notifications are code too.** A notification is its own entity file, e.g. `discord.json` (file stem = autokuma id `discord`): `{"type":"notification","active":true,"config":{"type":"discord","discordWebhookUrl":"${DISCORD_WEBHOOK_URL}",...}}`. **AutoKuma does NOT honor `isDefault`** — every monitor must opt in explicitly with `"notification_name_list": ["discord"]`.
- **No `__notification_` filename prefix** — it makes AutoKuma 2.0.0 silently skip the file. Use a plain name.
- **`ON_DELETE=keep`, not `delete`.** With `delete`, the v2 migration + notification attach triggered a destructive **delete-then-recreate flap** every sync. `keep` halts it (trade: a ConfigMap-removed monitor won't auto-prune). Don't flip back without understanding the flap.
- **ConfigMap edits need a pod roll.** Monitors live in an emptyDir an initContainer populates (it `envsubst`s `${DISCORD_WEBHOOK_URL}`) at startup — edits don't apply until restart. Bump the `mtgibbs.dev/monitors-revision` pod-template annotation to force it. *(TODO: direct ConfigMap mount + `AUTOKUMA__ENV__` webhook templating → file-watcher auto-reload, no roll.)*
- **HTTP POST probes: body must be valid JSON** (e.g. `"body": "{}"`) — Kuma JSON-validates it before sending, else the monitor false-fails.
- **Major-version migration:** v2 refuses to start while old AutoKuma-labelled monitors exist — start once with `AUTOKUMA__MIGRATE=true` to adopt them, then remove it. A from-scratch rebuild doesn't need it.

## Homepage Dashboard
- **URL**: `https://home.lab.mtgibbs.dev`
- **Config**: GitOps-managed via `ConfigMap`.
- **Live Widgets**:
    - **Pi-hole**: v6 API integration.
    - **Immich/Jellyfin**: API keys via Environment Variables (`HOMEPAGE_VAR_*`).
    - **Kubernetes**: Node stats (requires ServiceAccount with ClusterRole).
- **Secrets**: API keys synced via multiple ExternalSecrets.

## Beelink AI Box Observability (off-cluster, scraped over the LAN)

The Beelink (`192.168.1.70`) is NOT in K3s — it's a Docker Compose host (`beelink-ansible`). Cluster Prometheus scrapes it over the LAN via `additionalScrapeConfigs` in the monitoring HelmRelease.

- **Scrape jobs** (`helmrelease.yaml`): `beelink-node` (:9100, node-exporter + GPU textfile), `beelink-cadvisor` (:8081, per-container), `beelink-litellm` (:9101, custom usage exporter). All labelled `instance=beelink`.
- **Dashboard**: `dashboard-beelink.yaml` ("Beelink AI Load") — VRAM/GPU/host/per-container + 3 LiteLLM usage panels.
- **Alerts**: `prometheusrule-beelink.yaml` — 10 rules (VRAM, GPU thermals, mem, CPU, model-disk, backup freshness). GPU/VRAM series are custom: `beelink_gpu_*` from `gpu-metrics.sh`.

### cAdvisor + Docker 29 containerd image store (GOTCHA)
Docker 29 on the Beelink uses the **containerd snapshotter** image store (`Storage Driver: overlayfs` / `io.containerd.snapshotter.v1`). cAdvisor **< v0.55** can't map containers under it (looks for the legacy `/var/lib/docker/image/overlay2/layerdb/mounts/<id>/mount-id`, fails with "failed to identify the read-write layer ID") → the `:8081` target stays green but emits **zero per-container series**. Fix: cAdvisor **v0.55.1+ with `cgroup: host`** (fixed 2026-05-22). Dashboard container panels use `name!=""` (not `name=~".+"`, which evaluated flaky).

### LiteLLM usage exporter (custom — native /metrics is Enterprise-gated)
LiteLLM's native Prometheus `/metrics` is paywalled (401 on OSS builds). We run our own: `beelink-ansible/files/litellm-exporter.py` (stdlib only, bind-mounted onto `python:alpine`) polls the OSS `/spend/keys` + `/spend/logs` and exposes `litellm_requests_total`, `litellm_tokens_total`, `litellm_request_duration_ms_sum`, `litellm_key_spend_usd` (per `key_alias`). Auth = read-only `proxy_admin_viewer` key at `op://pi-cluster/litellm-spend-exporter/password` (can GET `/spend/*`, 403 on mutations — the `backup_ro` analogue). **Dollar-spend reads ~0** (local Ollama models are unpriced) — tokens + latency are the real signals; use `rate()`. Counters are in-memory (reset on restart; first poll baselines so no restart spike).

## Troubleshooting

### Grafana Access
```bash
# Get admin password
kubectl get secret grafana-admin -n monitoring -o jsonpath="{.data.admin-password}" | base64 -d
```

### Check Alertmanager Status
```bash
kubectl -n monitoring port-forward svc/prometheus-kube-prometheus-alertmanager 9093:9093
# Access at http://localhost:9093
```

### AutoKuma Issues
If monitors are duplicated:
1. Check if `autokuma-pvc` is bound.
2. Verify `strategy: Recreate` is set on the deployment.
