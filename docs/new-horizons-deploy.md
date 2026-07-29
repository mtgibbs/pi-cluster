# Deploying new-horizons into the Pi cluster

The job-search agent (`mtgibbs/new-horizons`) is a **CLI (`nh`) over one SQLite lead store** — not a
web server. "Deploying" it means giving that store a **durable, backed-up home** and a way to run
`nh` in-cluster, then layering a read surface and ingestion on top. Phased so each step is a small,
reviewable PR; nothing auto-applies to the running cluster until you merge.

## Architecture

```
new-horizons repo (the app)          pi-cluster (this repo — the deploy layer)
  scripts/nh  (stdlib-only CLI) ──►   ghcr.io/mtgibbs/new-horizons image
  profile/    (résumé + profile)         │
                                         ▼
                          Deployment "new-horizons" (runner: sleep infinity)
                            ├─ PVC new-horizons-data (local-path, backed up)  →  /data/new-horizons.db
                            ├─ NH_LLM_* → Beelink LiteLLM (score / fetch-jd distill)
                            └─ exec:  nh list · nh stats · nh fetch-jd --all · nh score --all
```

## Phase 1 — durable store + runner  ✅ (this PR)

`clusters/pi-k3s/new-horizons/`: namespace, PVC (`local-path`, `prune:disabled`, 1Gi), ExternalSecret
(`new-horizons/litellm-key`), Deployment (stdlib `nh` image, store PVC, `NH_LLM_*` wired to the
Beelink like review-hub, `sleep infinity` runner), kustomization. Plus the Flux Kustomization (#33)
and the PVC added to the `pvc-backup` allowlist (`new-horizons_new-horizons-data`).

**You track by exec:** `kubectl exec -n new-horizons deploy/new-horizons -- nh list` /
`nh stats` / `nh show <id>` / `nh dossier <id>` / `nh advance <id> <stage>`.

### Human-gated prerequisites (before it goes green)
1. **Mint a scoped LiteLLM virtual key** for new-horizons (coder models on the Beelink), store it at
   `op://pi-cluster/new-horizons/litellm-key`. Same pattern as `review-hub/litellm-key`.
2. **Build + publish the image:** `ghcr.io/mtgibbs/new-horizons:0.1.0` (Dockerfile + CI live in the
   app repo), then flip the GHCR package **public** (`gh api PATCH /user/packages/container/new-horizons -f visibility=public`).
3. **Seed the store** (optional): `kubectl cp` your existing `new-horizons.db`, or start empty and let
   ingestion fill it.

## Phase 2 — the tracking surface (Grafana)  ✅ drafted (this PR)

The runner now **serves Prometheus metrics** instead of `sleep infinity`: the Deployment runs
`nh serve-metrics` (needs the `metrics` spec — new-horizons PR #16 — built into the image), exposing
`/metrics` (+ `/healthz`) with the `nh_*` gauges. A **Service** + **ServiceMonitor** (`release:
kube-prometheus`) get it scraped, and `monitoring/dashboard-new-horizons.yaml` provisions a
**Grafana "Job Search" dashboard** (label `grafana_dashboard: "1"`): total/applied stats, the
stage funnel, fit-score distribution, and the **résumé-version applied-vs-positive** table (which
angle gets replies). You still `kubectl exec … -- nh list/stats/fetch-jd/score` on the same pod.

Prereq beyond Phase 1: the image must include `nh serve-metrics` (i.e. new-horizons PR #16 merged
before the `:0.1.0` build).

## Phase 3 — reactive flow  ◐ push drafted; ingestion blocked on sample .eml

The chain: `job-alert email → nh add → nh fetch-jd → nh score → nh alert → ntfy + Matrix`.

**Drafted (this PR) — the push bridge.** An `alerter` **sidecar** in the new-horizons pod (shares
the store PVC — no RWO conflict, reuses the `nh` image) loops `nh alert --json` (new-horizons spec
`alert`, PR #17) and pushes new 8+/10 leads to **ntfy** + **Matrix** via `urllib`. Idempotent
(`nh alert`'s state file on `/data`), best-effort, at-most-once. `clusters/pi-k3s/new-horizons/`:
`alerter/alerter.py` (ConfigMap-generated), the sidecar in `deployment.yaml`, and
`external-secret-push.yaml` (ntfy/Matrix tokens — **separate** ExternalSecret so an unprovisioned
token can't break the required `litellm-key`). Push code smoke-tested against a local receiver
(correct ntfy POST + Matrix `m.text` PUT).

**Prereqs for the pings (all optional — unset ⇒ that backend stays quiet):**
- ntfy: the topic `new-horizons` (set `NTFY_TOKEN` only if it's protected → `op://pi-cluster/new-horizons/ntfy-token`).
- Matrix: a bot access token → `op://pi-cluster/new-horizons/matrix-token`, and set `MATRIX_ROOM_ID`
  in the Deployment to the job-search room.

**Still blocked — the reactive ingestion.** The `email → {company,role,url}` parse node (n8n) needs
Matt's sample job-alert `.eml`s; the `add → fetch-jd → score → alert` tail is ready. Until then the
sidecar's 15-min idempotent poll is the bridge (fires only on genuinely-new qualifiers, not a loop).
Wiring the n8n flow to call `nh alert` inline (so pings are instant) is the last step once the
`.eml`s land.

## Notes
- **Backups:** the whole store is one SQLite file, so the `pvc-backup` rsync covers it fully; restore
  via the standard `restore-job.template.yaml`.
- **Single writer:** Deployment uses `strategy: Recreate` — never two pods on the one RWO PVC.
- **No ingress in phase 1** (nothing serves HTTP yet); added in phase 2 only if the web-UI route is chosen.
