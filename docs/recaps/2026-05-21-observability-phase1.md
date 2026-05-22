# Session Recap — 2026-05-21 (Observability Phase 1)

This is the third arc of 2026-05-21. The other two are `docs/recaps/2026-05-21-q8-coder-agent-comparison.md` (model benchmarking) and `docs/recaps/2026-05-21-backup-recovery-and-mirror-hardening.md` (three weeks of silent backup failure, now fixed and hardened). This arc is the direct response to that recovery: making today's silent failures impossible to miss again.

The monitoring stack was already in place — kube-prometheus-stack feeds Grafana and Alertmanager, Alertmanager routes to Discord, Uptime Kuma + AutoKuma handle HTTP probes, Homepage provides the dashboard. Phase 1 extended that existing infrastructure; no new components were introduced.

---

## What Shipped

### 1. Backup Freshness Alerts (PrometheusRule `backup-jobs-alerts`)

`clusters/pi-k3s/backup-jobs/prometheusrule.yaml` — commit `38461b3`

Three alert rules, routed to Discord via the existing Alertmanager:

- **`BackupCronJobStale`** — fires when `kube_cronjob_status_last_successful_time` for any job in the `backup-jobs` namespace is more than 8 days old. Eight days covers exactly one missed weekly Sunday run — the precise failure mode from this morning, where all six jobs had been silent for three weeks.
- **`BackupJobFailed`** — fires on an active failed job. Catches failures that do update the metric.
- **`BackupCronJobMetricMissing`** — fires if `kube_state_metrics` stops reporting the success-time metric entirely, so we don't go blind if the visibility layer itself drops out.

**Expected behavior after deploy:** all three CronJobs' `lastSuccessfulTime` still reflects the April scheduled run — the manual test runs earlier today do not update that timestamp. `BackupCronJobStale` will fire within about an hour. It will self-clear after Sunday's scheduled run completes. That firing is the intended end-to-end validation of the alert path, not a false alarm.

---

### 2. AutoKuma Uptime Probes for AI Surfaces

`clusters/pi-k3s/uptime-kuma/autokuma-monitors.yaml` — commit `38461b3`

Three new HTTP probes added to the existing AutoKuma configuration:

| Monitor | Target | Endpoint |
|---|---|---|
| `ai.lab` | LiteLLM | `/health/liveliness` |
| `chat.lab` | Open WebUI | `/health` |
| `dewey.lab` | Dewey (Open WebUI) | `/health` |

The AI stack (Ollama + LiteLLM + Open WebUI + Dewey) was brought up on 2026-05-20 with no uptime visibility. These probes close that gap — if any of the three public surfaces goes dark, Uptime Kuma surfaces it immediately.

---

## Commits

| Hash | Subject |
|---|---|
| `38461b3` | feat(observability): backup-freshness alerts + AI-surface uptime probes |

---

## What's Next — Phase 2 (Beelink Load Visibility)

The Beelink (AMD Strix Halo) runs blind: no node metrics, no GPU/VRAM visibility, no LiteLLM request-rate data in Prometheus. Phase 2 adds:

- `node_exporter` + `cAdvisor` on the Beelink, scraped by cluster Prometheus via `additionalScrapeConfigs`
- A GPU/VRAM textfile collector reading `/sys/class/drm/card0/device` (`gpu_busy_percent`, `mem_info_vram_used`, `mem_info_vram_total`) and hwmon temps — no ROCm dependency; `rocm-smi` OOMs on Strix Halo
- LiteLLM `/metrics` scrape
- Grafana dashboards for load, VRAM pressure, and request throughput
- Saturation alerts (VRAM/mem/CPU/GPU-temp thresholds)
