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
   `op://pi-cluster/new-horizons/litellm-key`. Per-service on purpose — cost attribution + access
   scope differ per consumer (same rationale as `review-hub/litellm-key`).
2. **Build the image (keep it PRIVATE):** `ghcr.io/mtgibbs/new-horizons:0.1.0` (Dockerfile + CI in the
   app repo). It bakes in `profile/` (PII), so do **not** flip it public — it's pulled via the shared
   `ghcr-pull` secret (`external-secret-ghcr.yaml`).
3. **The shared GHCR pull identity** (one-time, cluster-wide — reused by every future private image):
   a read-only GitHub token at `op://pi-cluster/ghcr-pull/{username,token}`. New private service adds
   the same `external-secret-ghcr.yaml` to its namespace + `imagePullSecrets: [ghcr-pull]` — zero new
   identities.
4. **Seed the store** (optional): `kubectl cp` your existing `new-horizons.db`, or start empty and let
   ingestion fill it.

## Phase 2 — the tracking surface (Grafana)  ⬜ next PR

`nh stats --json` → a small exporter (CronJob writing a Prometheus textfile, or a sidecar) →
a **Grafana "Job Search" dashboard**: stage funnel, fit-score distribution, and the
résumé-version↔outcome panel (which tailoring angle gets replies). Reuses the existing
kube-prometheus-grafana stack. *(Alternative if you'd rather: a thin read-only web page + ingress.)*

## Phase 3 — reactive flow  ⬜ later

n8n job-alert email → `nh add` → `nh fetch-jd` → `nh score` → **ntfy + Matrix** ping on new 8+/10
leads ("3 new high-fit leads, dossiers ready"). This is the PLAN's original `intake` email path
(needs sample `.eml`s) plus the alert wiring.

## Notes
- **Backups:** the whole store is one SQLite file, so the `pvc-backup` rsync covers it fully; restore
  via the standard `restore-job.template.yaml`.
- **Single writer:** Deployment uses `strategy: Recreate` — never two pods on the one RWO PVC.
- **No ingress in phase 1** (nothing serves HTTP yet); added in phase 2 only if the web-UI route is chosen.
