# Spec: Homepage Dashboard Refresh

- **Status:** Planned v0.3 (tuned after a Round-1 qwen3-coder eval — see §11)
- **Owner:** Matt
- **Constitution:** `/CLAUDE.md` Core Mandates (GitOps via Flux, secrets via 1Password/ESO, MCP-first, public-by-default, agent work PR-gated)
- **Surface:** `https://home.lab.mtgibbs.dev` — Homepage (gethomepage)
- **Touches:** `clusters/pi-k3s/homepage/{configmap,external-secret,deployment}.yaml`

---

## 1. Why (problem / context)

The Homepage is the lab's landing page, but it has drifted behind what we actually run:

- The **arr / download stack** is listed but only as `siteMonitor` (up/down dots) — no
  at-a-glance status: no queue depth, no health warnings, no download speed.
- The **AI / chat surfaces** (`dewey.lab`, `chat.lab`, `ai.lab`) are **absent entirely**.
- The **Beelink emits no telemetry** to the homepage, even though Horizon 2 (2026-05-22)
  put its full metric set into Prometheus. The Pi cluster has glanceable node stats; the
  Beelink — our most active box — has nothing.

A good landing page is **one-click links + glanceable health for everything we run.**

## 2. Outcomes (definition of done, in plain language)

1. Every running service is reachable from the homepage in one click.
2. The arr stack shows **live status** (queue, warnings, speed) without opening each app.
3. A dedicated **AI section** surfaces the chat/inference services with a health indicator.
4. **Beelink telemetry** (GPU/VRAM/host) is visible on the homepage, the way the Pi cluster's is.

## 3. Scope

### In scope
- `homepage/configmap.yaml` — `services.yaml`, `settings.yaml` (layout), `widgets.yaml`, `bookmarks.yaml`.
- `homepage/external-secret.yaml` — new ExternalSecrets for arr API keys.
- `homepage/deployment.yaml` — env wiring for the new secret keys.

### Out of scope
- No changes to the underlying services (Sonarr, etc.) — widgets are **read-only**.
- No Homepage version bump or theme overhaul.
- No SSO/Authelia in front of the homepage (tracked separately).
- No **new** 1Password items unless a required key is genuinely missing (prefer reuse).

## 4. Constraints (constitution applied here)

- **GitOps only** — every change is in the Flux-managed YAML and reconciled by Flux. No edits in the Homepage UI.
- **Secrets via ExternalSecret → 1Password** (`pi-cluster` vault). Never inline a key. The referenced 1Password field paths **must already exist**.
- **Widgets use in-cluster service URLs** (`*.svc.cluster.local`), not public ingress — avoids a LAN round-trip and ingress auth.
- **Beelink telemetry reuses the existing `customapi`→Prometheus pattern** (see the `Cluster → pi-k3s` block in `services.yaml`) against metrics already scraped.
- **No secret values in the rendered page** — aliases, counts, and rates only.

## 5. Prior decisions / facts the implementer must know

- Beelink metrics in Prometheus (from H2): `beelink_gpu_busy_percent`,
  `beelink_gpu_vram_used_bytes`, `beelink_gpu_vram_total_bytes`, `beelink_gpu_temp_celsius`,
  and `node_*` / `container_*` with `instance="beelink"`. Jobs: `beelink-node`,
  `beelink-cadvisor`, `beelink-litellm`.
- Prometheus in-cluster URL (already used on the page):
  `http://kube-prometheus-kube-prome-prometheus.monitoring.svc.cluster.local:9090`.
- Homepage `customapi` widget can hit `/api/v1/query?query=<promql>` and map fields — the
  existing `Cluster → pi-k3s` entry already does this for `node_uname_info`.
- Homepage has **native widget types** for: `sonarr`, `radarr`, `lidarr`, `bazarr`,
  `prowlarr`, `sabnzbd`, `qbittorrent`, `jellyseerr`, `prometheus`, `customapi`.
- The arr API keys are likely already in the `pi-cluster` 1Password vault (the
  `mcp-homelab` / servarr-ops tooling uses them) — **reuse those paths**.
- AI surfaces & health endpoints (verified during the H2 Kuma work):
  `ai.lab.mtgibbs.dev/health/liveliness`, `chat.lab.mtgibbs.dev/health`, `dewey.lab.mtgibbs.dev/health`.
- **Active-use reality (a widget is only worth it if the service is actually used):**
  **qBittorrent is deployed but NOT in active use** — we run usenet via SABnzbd, not
  torrents. A qBittorrent widget would render "inactive" and add noise. Treat it like
  Jellyseerr: a `siteMonitor` link, no widget. (This is operational knowledge the model
  cannot infer from the manifests — it must be stated here.)

## 6. Task breakdown

- **T1 — Arr at-a-glance status.** Convert Sonarr, Radarr, Lidarr, Bazarr, Prowlarr,
  SABnzbd, qBittorrent, Jellyseerr from `siteMonitor` → typed widgets. Add an ExternalSecret
  per API key and wire the env vars in `deployment.yaml`.
- **T2 — AI / chat section (new group).** Dewey, Adults Chat, LiteLLM API; a `customapi`
  health/up indicator on `ai.lab`. Optionally list the MCP servers.
- **T3 — Beelink telemetry (new group).** VRAM-used %, GPU-busy %, GPU temp via
  `customapi`→Prometheus; host RAM/CPU. Mirror the `Cluster` block's pattern.
- **T4 — Layout + bookmarks.** Add `Beelink` and `AI` groups to `settings.yaml` (style/columns);
  bookmark the Grafana "Beelink AI Load" dashboard.

## 7. Acceptance criteria (EARS)

1. **Ubiquitous** — The homepage shall present these groups: DNS, Cluster, Beelink, Network, Monitoring, AI, Media, Downloads, Logs, Automation, Web.
2. **Event-driven** — When a Sonarr / Radarr / Lidarr API is reachable, the corresponding widget shall display its queue count and health/warning count.
3. **Event-driven** — When SABnzbd is reachable, its widget shall display the current download rate and queue size.
4. **State-driven** — While the Beelink is being scraped by Prometheus, the Beelink panel shall display VRAM-used %, GPU-busy %, and GPU temperature.
5. **Ubiquitous** — The AI group shall present Dewey (`dewey.lab`), Adults Chat (`chat.lab`), and LiteLLM API (`ai.lab`), each with a health/up indicator.
6. **Unwanted behavior** — If an API key required by a widget is missing from 1Password, then that widget's change shall be omitted (no inline secret, no broken ExternalSecret) and called out in the PR.
7. **Ubiquitous** — The rendered homepage shall expose no secret values (only aliases, counts, rates).
8. **Event-driven** — When `kustomize build clusters/pi-k3s/homepage` is run, it shall complete with no errors.

## 8. Verification (the harness)

- `verify.sh`: `yamllint` the changed files; `kustomize build clusters/pi-k3s/homepage` succeeds; grep the rendered output for accidental secret leakage (no `sk-`, no raw keys).
- After Flux apply: Homepage pod healthy; new `homepage-*` ExternalSecrets show `SecretSynced` (`get_secrets_status`); spot-check 3 widgets render — Sonarr queue, Beelink VRAM, `ai.lab` up — via the live page or `curl_ingress`.
- Review the diff against §7 acceptance criteria before merge.

## 9. Open questions — RESOLVED 2026-05-22

- **OQ1 ✅** — All arr services are in the `media` namespace; URLs/ports confirmed from manifests (see §10 table).
- **OQ2 ✅** — All arr API-key items exist in 1Password **except Jellyseerr** (verified via `op item list --vault pi-cluster`). Bazarr uses the documented exception path. Jellyseerr has no key → its widget is **omitted** (criterion #6); see §10.
- **OQ3 ✅** — Use `customapi`→Prometheus (the native `prometheus` widget only summarizes targets up/down). One Prometheus instant query returns one value, so it's **one `customapi` tile per metric**, grouped under "Beelink" — mirrors the existing `Cluster → pi-k3s` block. Exact queries in §10.
- **OQ4 ✅** — **Omit MCP servers** from the human landing page (non-browsable API endpoints). May add as a Developer bookmark later. Not in scope for this pass.

---

## 10. Plan — implementation reference (v0.2)

### Arr services (all namespace `media`)

| Service | In-cluster URL | Widget type | Auth — 1Password path | Status |
|---|---|---|---|---|
| Sonarr | `http://sonarr.media.svc.cluster.local:8989` | `sonarr` | `op://pi-cluster/sonarr.lab.mtgibbs.dev/api-key` | ✅ exists (live ESO) |
| Radarr | `http://radarr.media.svc.cluster.local:7878` | `radarr` | `op://pi-cluster/radarr.lab.mtgibbs.dev/api-key` | ✅ exists (live ESO) |
| Lidarr | `http://lidarr.media.svc.cluster.local:8686` | `lidarr` | `op://pi-cluster/lidarr.lab.mtgibbs.dev/api-key` | ✅ item exists |
| Bazarr | `http://bazarr.media.svc.cluster.local:6767` | `bazarr` | `op://pi-cluster/mcp-homelab/bazarr-api-key` | ✅ exists (**exception** — not a `*.lab` item) |
| Prowlarr | `http://prowlarr.media.svc.cluster.local:9696` | `prowlarr` | `op://pi-cluster/prowlarr.lab.mtgibbs.dev/api-key` | ✅ item exists |
| SABnzbd | `http://sabnzbd.media.svc.cluster.local:8080` | `sabnzbd` | `op://pi-cluster/sabnzbd.lab.mtgibbs.dev/api-key` | ✅ exists (len 32) |
| qBittorrent | `http://qbittorrent.media.svc.cluster.local:8080` | — | — | ⚠️ **deployed but not in active use** → keep as `siteMonitor` link, **omit widget** (it would just render "inactive"). We run usenet/SAB, not torrents. |
| Jellyseerr | `http://jellyseerr.media.svc.cluster.local:5055` | `jellyseerr` | — | ❌ **no key in vault → keep as `siteMonitor` link, omit widget** (follow-up: provision key) |

> Field name is `api-key` (confirmed for Sonarr/Radarr via the live `media/servarr-api-keys.yaml` ESO; assumed by convention for the rest — a wrong field name surfaces as an ESO sync failure, caught in verify).

### Beelink telemetry — group "Beelink", `customapi` → Prometheus

- Base: `http://kube-prometheus-kube-prome-prometheus.monitoring.svc.cluster.local:9090/api/v1/query?query=<promql>`
- **⚠️ TWO gotchas:**
  1. **The value is NESTED.** Prometheus returns `{"data":{"result":[{"value":[<ts>,"0.61"]}]}}`,
     so the mapping field path **MUST be `data.result.0.value.1`** — NOT `value`. (Different
     from the existing Loki `customapi`, which maps top-level fields — don't copy that style.)
  2. **`format: percent` expects a 0–1 FRACTION.** Homepage uses `Intl.NumberFormat` style
     `percent`, which multiplies by 100. So return the raw ratio — do **NOT** pre-multiply by
     100, or it renders "6100%". `0.61` → "61%". (Verified against Homepage's formatter.)

| Tile | promql (raw fraction for percent — no ×100) | format |
|---|---|---|
| VRAM Used % | `beelink_gpu_vram_used_bytes / beelink_gpu_vram_total_bytes` | percent |
| GPU Busy % | `beelink_gpu_busy_percent / 100` | percent |
| GPU Temp °C | `round(beelink_gpu_temp_celsius)` | number |
| Host RAM % | `1 - node_memory_MemAvailable_bytes{instance="beelink"} / node_memory_MemTotal_bytes{instance="beelink"}` | percent |

**Worked example — copy this shape exactly for each tile (note the `field` path):**

```yaml
- Beelink VRAM Used %:
    icon: mdi-memory
    description: iGPU VRAM in use
    widget:
      type: customapi
      url: http://kube-prometheus-kube-prome-prometheus.monitoring.svc.cluster.local:9090/api/v1/query?query=beelink_gpu_vram_used_bytes%20/%20beelink_gpu_vram_total_bytes
      mappings:
        - field: data.result.0.value.1   # <-- nested; NOT "value"
          label: VRAM %
          format: percent                 # <-- value is a 0-1 fraction (Homepage ×100)
```

Plus a link tile → Grafana **"Beelink AI Load"** dashboard. **Use this literal href**
(do NOT guess the dashboard UID): `https://grafana.lab.mtgibbs.dev/d/beelink-ai-load`.

### AI group

| Entry | href | health |
|---|---|---|
| Dewey (kids) | `https://dewey.lab.mtgibbs.dev` | `siteMonitor` → `/health` |
| Adults Chat | `https://chat.lab.mtgibbs.dev` | `siteMonitor` → `/health` |
| LiteLLM API | `https://ai.lab.mtgibbs.dev` | `customapi` → `/health/liveliness` (or `siteMonitor`) |

### Files to change (maps to tasks)

- **T1** — `configmap.yaml` (arr widgets), `external-secret.yaml` (+6 ESO: sonarr/radarr/lidarr/prowlarr/sabnzbd/bazarr `HOMEPAGE_VAR_*_API_KEY`; qbit user/pass), `deployment.yaml` (env wiring).
- **T2** — `configmap.yaml` AI group.
- **T3** — `configmap.yaml` Beelink group.
- **T4** — `configmap.yaml` `settings.yaml` layout + `bookmarks.yaml`.

### Residual follow-up (out of this pass)
- Provision a Jellyseerr API key in 1Password (`requests.lab.mtgibbs.dev/api-key` or similar) to upgrade it from link → widget.
- Decide qBittorrent's fate (retire, or actually configure it) — until then it stays a link.

---

## 11. Tuning log (the eval → tune loop)

**Round 1 (2026-05-22)** — handed v0.2 to `qwen3-coder-30b`, zero-shot, controlled
generation of `configmap.yaml`. Result: ~7/9 acceptance criteria clean, valid YAML,
all arr URLs/ports/widget types/key vars correct, **Jellyseerr correctly omitted** (AC#6
honored). Two misses, both traced to *spec gaps, not model error*:

1. **Beelink `customapi` used `field: value`** instead of the nested `data.result.0.value.1`.
   Root cause: the model copied the existing **Loki** `customapi` style (top-level fields)
   over the spec's path. → Fix: §10 now has a **worked example** + an explicit **contrast
   with Loki**. *(Lesson: existing code beats prose; show, don't tell.)*
2. **Invented a Grafana dashboard URL** (guessed the UID). → Fix: §10 now gives the
   **literal href**. *(Lesson: never leave a linkable target as prose.)*
3. **Built a qBittorrent widget** for a service we don't actually use → would show
   "inactive". Caught by the human (operational knowledge not in the manifests). → Fix:
   §5 + §10 now record qBittorrent as link-only. *(Lesson: the spec must carry
   real-world/active-use facts the model can't infer.)*

> Meta-lesson for the SDD practice: the model nailed everything backed by a concrete
> pattern or a testable rule (EARS criteria, the §10 URL table), and only missed where
> the spec described *intent* without a literal example or fact. **Specificity is the lever.**

**Round 2 (2026-05-23)** — handed the tuned v0.3 to qwen3-coder **agentically** via opencode
(it edits files itself, in a worktree). Findings:

- **Tuned lessons held under agentic execution:** nested field path ✓, literal Grafana URL ✓,
  Jellyseerr + qBittorrent link-only ✓, correct arr URLs/ports/keys ✓.
- **It executed a *spec bug* faithfully:** §10 said `round(100 * …)` + `format: percent`, but
  Homepage's percent formatter ×100 (expects 0–1) → would render "6100%". The model had no
  judgment to catch our error — **it amplifies spec mistakes.** Fixed §10 to raw fractions.
- **No taste on the unspecified:** reused `mdi-memory` for 3 of 4 tiles (icons weren't specified).
- **No self-verification + a 2h stall:** it never ran §8 verify, left the AI group in the layout
  with no services, then hung on one streaming request (no timeout). GPU/model were healthy —
  the gap was an un-timed-out agentic loop. → added a watchdog to the `oc` launcher.

> Round-2 meta-lesson: for the local model, **one-shot generation is reliable; open-ended
> agentic autonomy is not** (it stalls, doesn't self-check, brings no taste). Externalize
> verification to the harness, bound the scope per iteration, timebox every run, and keep
> specs *correct* — the model won't save you from your own bugs.
