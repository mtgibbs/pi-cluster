# Spec: Homepage Retro-Theme Refit ("NOSTROMO Terminal")

> **REASONS Canvas** — sections tagged with their dimension letter.

- **Status:** Planned v0.2 (OQs resolved 2026-06-11 via v1.4.5 source-tag audit)
- **Owner:** Matt
- **Constitution:** `specs/constitution.md` (+ `/CLAUDE.md` Core Mandates)
- **Predecessor:** `specs/homepage-refresh/spec.md` (widget data refresh, 2026-05; explicitly scoped OUT "theme overhaul" — this is that pass)
- **Touches:** `clusters/pi-k3s/homepage/configmap.yaml` ·
  `clusters/pi-k3s/external-services/{synology.yaml (DELETE), kustomization.yaml}` ·
  `clusters/pi-k3s/uptime-kuma/autokuma-monitors.yaml` (+ AutoKuma revision-bump per its SKILL gotcha)

---

## 1. Why · [R]

The homepage works (live widgets shipped in the predecessor spec) but looks like a default
dark dashboard and wastes vertical space: **11 full-width row groups**, including a 1-item
`Automation` band, a 2-item `Logs` band, and four label-only Cluster node tiles duplicating
the header's kubernetes widget. Also: the "Synology NAS" tile has been a **dead link**
(backend 502) since the QNAP cutover. Goal: a **1970s sci-fi terminal identity**
(Alien/Nostromo base, 2001/HAL status colors, restrained Blade Runner accents) + a
consolidated deck layout where live widgets get the space and link-only tiles get dense
treatment.

## 2. Outcomes (Definition of Done) · [R]

1. The page renders the green-phosphor terminal theme (tokens in §7) at `https://home.lab.mtgibbs.dev`.
2. Groups consolidated 11 → 6 decks (§13 table); no band renders fewer than 3 tiles.
3. Zero data regression: every live widget from the current page survives with identical type/url/key.
4. All Synology remnants are gone: tile → **QNAP NAS** (`https://qnap.lab.mtgibbs.dev`, already-wired ingress), dead `nas.lab` ingress deleted, Kuma monitor repointed.
5. The widget capability matrix (what each widget CAN show vs what we show) is recorded in §13b.

## 3. Entities · [E]

Config keys inside `ConfigMap/homepage-config` (namespace `homepage`):

- `settings.yaml` — `title, theme, color, headerStyle, statusStyle, iconStyle, hideVersion, useEqualHeights, fullWidth, layout.<GROUP>.{style,columns,icon}`
- `services.yaml` — list of `<GROUP>: [ <Tile>: {icon, href, description, siteMonitor?, widget?} ]`
- `custom.css` — **new key**; initContainer (`deployment.yaml:24-36`) copies every ConfigMap key to `/app/config/`, where Homepage v1.4.5 natively loads it (served at `/api/config/custom.css`, read from disk per request).
- `external-services/synology.yaml` — dead `Endpoints/Service/Ingress` triple → **deleted**.
- `uptime-kuma/autokuma-monitors.yaml` — `synology.json` entity (autokuma id `synology`) → repointed in place.

## 4. Approach · [A]

CSS-first theming: `settings.yaml` carries only what it natively does well (layout, status
style); ALL visual identity lives in `custom.css` keyed off design tokens (§7). Mirror the
ConfigMap-key pattern already used for `docker.yaml`/`kubernetes.yaml` — add `custom.css` as
a sibling key, nothing else moves.

**Rejected:** background *image* (starfield/rain) — needs `/app/public/images` mount +
restart per image, competes with readability, and `background` filters are incompatible with
`cardBlur`. Texture is CSS-only (scanlines + vignette). Also rejected: blending all three
film palettes equally — one base identity (Nostromo green) with the others as accent tiers.
Also rejected: nested subgroups for CARGO BAY (supported in v1.4.5, but flat `row`×6 reads
better and keeps the qwen regroup trivial).

## 5. Scope · [S]

### In scope
- `clusters/pi-k3s/homepage/configmap.yaml` — `settings.yaml`, `services.yaml`, new `custom.css` key.
- `clusters/pi-k3s/external-services/synology.yaml` — **delete file**; remove its line from
  `external-services/kustomization.yaml`.
- `clusters/pi-k3s/uptime-kuma/autokuma-monitors.yaml` — `synology.json`: name → `QNAP NAS`,
  url → `https://qnap.lab.mtgibbs.dev/` (same file key = same autokuma id = in-place update,
  no delete/recreate flap). Bump the `mtgibbs.dev/monitors-revision` pod-template annotation
  (AutoKuma reads monitors from an initContainer-populated emptyDir — see monitoring-ops SKILL).

### Out of scope
- `homepage/{deployment,external-secret,ingress,rbac,service}.yaml` — **no changes.**
- `external-services/qnap.yaml` — already correct (Endpoints `192.168.1.61:8080`, host
  `qnap.lab.mtgibbs.dev`, TLS) — do not touch.
- No new ExternalSecrets / 1Password items → Lidarr, Prowlarr, Jellyseerr, qBittorrent stay
  **link-only** (their `HOMEPAGE_VAR_*` keys are not synced; verified 2026-06-11).
- No Homepage version bump (stays `v1.4.5`).
- No changes to any monitored service; `bookmarks.yaml` content unchanged (CSS may restyle).

## 6. Prior decisions / facts · [S]

1. **Config delivery:** initContainer copies `/configmap/*` → `/config/` — a new ConfigMap key
   is automatically a file in `/app/config/`. Homepage re-reads `custom.css` per request and
   auto-reloads on config-hash change, **but** our file only changes on pod start (initContainer
   copy) → ConfigMap edits still need `/deploy` + `restart_deployment homepage`.
2. **Synced secrets** (complete list — anything else means new plumbing, out of scope):
   PIHOLE, PIHOLE_SECONDARY, JELLYFIN, IMMICH, UNIFI_USER/PASS, TAILSCALE_API_KEY/DEVICE_ID,
   SONARR, RADARR, SABNZBD, BAZARR, AI_CONTROLPANEL_TOKEN.
3. **Header info widgets** (search, kubernetes w/ per-node CPU+mem, openmeteo, datetime)
   already show node stats → the four `Cluster` tiles are **dropped** (the `pi-k3s` tile's
   customapi mapped `status` → renders the literal string "success" — noise).
4. **Unbound tile** has no href and no widget — pure label, **dropped**.
5. **NAS reality (probed 2026-06-11):** Synology backend (`192.168.1.60:5000`) dead —
   `nas.lab` → 502 via `curl_ingress`. **`qnap.lab.mtgibbs.dev` already fully wired**
   (`external-services/qnap.yaml`: Endpoints `.61:8080` + ingress + LE TLS; UI answers 200
   in 78ms). So: delete the synology triple, point tile + Kuma monitor at `qnap.lab`.
   Residual: the orphaned `synology-tls` cert Secret may linger after ingress deletion —
   harmless; clean up manually if noticed.
6. **Fonts** are client-fetched via Google Fonts `@import` (LAN clients have internet;
   page itself stays self-hosted). Fallback stacks mandatory (§7).
7. **Contrast warning (predecessor §11 lesson):** the existing Loki `customapi` maps
   *top-level* fields; the Prometheus `customapi` pattern needs `data.result.0.value.1`.
   Don't "fix" either while regrouping — **move widget blocks verbatim.**
8. **v1.4.5 audit facts that bound the design** (full matrix §13b):
   - `prometheusmetric` and block-display `customapi` **silently render only the first 4**
     metrics/mappings (`slice(0,4)`). Beelink card has exactly 4 — at the cap, add nothing.
   - Service `fields` have **no global 4-cap** in v1.4.5 — extra fields squeeze the row.
     Keep ≤4 per tile anyway (taste).
   - `layout` group syntax: `style: row` + `columns:` (grid supports up to 8), per-group
     `icon:`. Nested subgroups exist (`subgroup` class) — not used here.
   - `statusStyle: dot` = small colored dot instead of response-ms text; per-service override
     possible. We use `dot` globally.
   - `headerStyle` ∈ `underlined|boxed|clean|boxedWidgets` — we use `clean` (CSS draws its own
     header treatment).
   - `iconStyle: theme` tints `mdi-*` icons to the theme color (default is a gradient) —
     coherent with monochrome phosphor.
   - Stable DOM hooks for custom.css (v1.4.5 source-verified): `.service-card`,
     `.service-title`, `.service-name`, `.service-description`, `.service-icon`,
     `.service-block`, `.services-group`, `.service-group-name` (h2), `.service-group-icon`,
     `.site-monitor-status`, `.ping-status`, `.k8s-status`, `.docker-status-<state>`,
     `#information-widgets`, `.widget-container`, `.information-widget-<type>`, `.bookmark-*`.
     Tailwind utility classes are NOT stable — never target them. Per-tile `id:` in YAML
     renders as a DOM id if ever needed.
   - Group names must be unique across `services.yaml` AND `bookmarks.yaml` (collision
     silently hides a group). Bookmarks groups: `Developer`, `AI`, `Network` — none collide
     with the §13 deck names. ~~`AI`~~ — the old services group `AI` collided risk-free
     before; new deck names are all distinct anyway.

## 7. Norms · [N]

### Design tokens — the literal values (copy exactly)

```css
:root {
  --crt-bg: #04100f;            /* near-black, teal-tinted */
  --crt-surface: rgba(8, 26, 24, 0.82);    /* card / icon-badge surface */
  --crt-border: #18403a;        /* card/section/badge borders */
  --phosphor: #54bcab;          /* muted teal — headings, values, status-up */
  --phosphor-body: #93cabf;     /* body text */
  --phosphor-dim: #4a8278;      /* descriptions, secondary */
  --amber: #d9a020;             /* warnings/degraded ONLY (muted gold) */
  --error-orange: #c2521e;      /* down/error ONLY — darkened orange (teal's complement) */
  --accent: #6fe7d3;            /* Blade Runner accent — hover states ONLY (bright teal) */
  --glow-teal: 0 0 8px rgba(84, 188, 171, 0.40);
  --glow-error: 0 0 10px rgba(194, 82, 30, 0.50);
  --pane-glow: inset 0 0 10px rgba(84, 188, 171, 0.12);  /* icon-badge inner glass */
  --scanline: rgba(0, 0, 0, 0.14);     /* CRT texture */
  --vignette: rgba(0, 0, 0, 0.5);
}
```

- **Color values (hex/rgba) live ONLY in `:root`** — every rule references `var(--token)`.
- **Fonts:** group headers + page title `"Michroma", "Eurostile", sans-serif` (the 2001/Alien
  title face); everything else `"Share Tech Mono", ui-monospace, monospace`.
- **Color semantics:** muted teal = healthy/info. Amber (gold) = warning/degraded. Darkened
  orange = down/error (teal's complement). Bright teal = interactive hover only. Never
  decorative orange/amber.
- **Icons — "through the terminal pane":** every service icon is snapped into a uniform
  **badge** (`.service-icon` → `var(--crt-surface)` bg, `var(--crt-border)` border, rounded,
  `var(--pane-glow)` inner glass). Raster `.png` logos are **monochromed toward teal** with a
  `filter` chain (grayscale→sepia→hue-rotate) so nothing renders in its native brand color;
  `mdi-*` icons inherit teal natively via `color: teal` + `iconStyle: theme`. On card hover
  the pane "lights up" (border → `var(--accent)`, icon filter brightens). No icon shall pop in
  full color.
- **Texture:** scanlines via `repeating-linear-gradient` overlay + subtle radial vignette,
  `pointer-events: none`. Group headers get `text-shadow: var(--glow-teal)`, uppercase,
  `letter-spacing: 0.2em`.
- **Motion: NONE.** No `@keyframes`, no `animation:` (no CRT flicker — distracting). Hover
  `transition` ≤ 150ms allowed.
- **Selectors:** only the §6.8 stable hooks (kebab-case semantic classes, ids) — never
  Tailwind utility classes. **One sanctioned exception:** state-bearing color utilities
  (`[class*="bg-rose"]` etc.) scoped INSIDE a stable status wrapper
  (`.site-monitor-status`, `.ping-status`, `.k8s-status`) — the dot's color class is the
  only state signal homepage exposes. Confirm against live DOM during visual iteration.
- **Icons:** keep each tile's existing icon; deck `icon:` entries in layout use distinct mdi
  icons (§13 table) — never the same icon twice (predecessor `mdi-memory`×3 failure).
- **Tile descriptions:** ≤ 5 words, sentence case, no emoji. Deck names UPPERCASE.
- `custom.css` ≤ 20KB, structured: tokens → fonts → base → texture → header → cards →
  status → bookmarks → hover.

## 8. Safeguards · [S]

1. **No inline secrets** — only `{{HOMEPAGE_VAR_*}}` placeholders in the ConfigMap (gate: grep).
2. **Zero widget regression** — these `type:` counts must hold in the new `services.yaml`:
   `pihole`×2, `unifi`×1, `tailscale`×1, `uptimekuma`×1, `prometheus`×1, `jellyfin`×1,
   `immich`×1, `sonarr`×1, `radarr`×1, `bazarr`×1, `sabnzbd`×1, `prometheusmetric`×1,
   `customapi`×2 (AI Mode, Loki — the dropped pi-k3s tile's customapi is the only removal).
3. **Files touched** = exactly the four in §5 + this spec dir. Nothing else.
4. **Progressive enhancement** — the page must remain fully usable if `custom.css` fails to
   load (pure restyling; never hide content with CSS).
5. **AutoKuma:** repoint `synology.json` **in place** (same key/id). Never rename the file
   key (rename = delete+create; `ON_DELETE=keep` would orphan the old monitor) and never
   touch `ON_DELETE`.
6. **`HOMEPAGE_ALLOWED_HOSTS` and probes untouched** (no deployment edits at all).

## 9. Task breakdown · [O]

- **T1 (Claude — taste):** `custom.css` + `settings.yaml` theme/layout keys (§13 settings block).
- **T2 (qwen one-shot):** regenerate `services.yaml` per the §13 deck table — pure mechanical
  move-verbatim regroup. Runs after T1 (group names must already exist in `settings.yaml`).
- **T3 (Claude):** Synology teardown: delete `synology.yaml`, edit `kustomization.yaml`,
  repoint `autokuma-monitors.yaml` + revision bump.
- **T4:** `verify.sh` STATIC green → `/deploy` → `restart_deployment homepage` → LIVE checks
  + human visual review.

## 10. Acceptance criteria (EARS) · [O]

1. **Ubiquitous** — `services.yaml` shall define exactly these groups, in order:
   `COMMAND, COMMS, AI CORE, REC DECK, ACQUISITION, CARGO BAY`.
2. **Ubiquitous** — `settings.yaml` `layout:` keys shall exactly equal the `services.yaml` group set.
3. **Ubiquitous** — every tile shall sit in the deck assigned by the §13 table; CARGO BAY
   tiles shall have no `widget:` block.
4. **Ubiquitous** — the §8.2 widget-type counts shall hold exactly.
5. **Ubiquitous** — every group shall contain ≥ 3 tiles.
6. **Ubiquitous** — `custom.css` shall open with the §7 `:root` token block verbatim; no hex
   color shall appear outside it.
7. **Ubiquitous** — `custom.css` shall `@import` Michroma and Share Tech Mono and declare the
   §7 fallback stacks.
8. **Unwanted** — if `custom.css` contains `@keyframes` or `animation:`, the gate shall fail.
9. **State-driven** — while a service is down, its status indicator shall render
   `var(--error-orange)` + `var(--glow-error)` (CSS rule marked `/* STATUS:DOWN */`); warnings
   shall use `var(--amber)` (`/* STATUS:WARN */`).
9b. **Ubiquitous** — `custom.css` shall style `.service-icon` as a badge (`var(--pane-glow)`)
   and apply a monochroming `filter:` to `.service-icon img` (rule marked `/* ICON:PANE */`).
10. **Event-driven** — when `kubectl kustomize` builds `homepage`, `external-services`, and
    `uptime-kuma`, all shall succeed.
11. **Ubiquitous** — the ConfigMap shall contain no secret values (placeholders only).
12. **Ubiquitous** — `synology.yaml` shall not exist; `external-services/kustomization.yaml`
    shall not reference it; no config shall reference `nas.lab.mtgibbs.dev`
    (homepage + autokuma reference `qnap.lab.mtgibbs.dev` instead).
13. **Event-driven** — when `https://qnap.lab.mtgibbs.dev` is curled post-deploy, it shall
    return non-502 (LIVE tier).

## 11. Verification — `verify.sh`

STATIC (offline, gates every iteration): ruby-YAML parse + extract embedded docs;
`kubectl kustomize` builds; criteria 1–9, 11, 12 via ruby/grep. LIVE (post-deploy,
human/MCP): homepage pod healthy after restart, `curl_ingress` home.lab → 200 and
qnap.lab → non-502, Kuma "QNAP NAS" monitor green, visual review of the rendered page
(taste boundary — see `specs/design-principles.md`).

## 11b. Loop execution

Only **T2** goes to qwen: one-shot generation, fresh context, input = §13 table + current
`services.yaml` + the §6.7 contrast warning + §8.2 counts. Gated on `verify.sh`. Predecessor
§11 lesson: one-shot is its reliable mode; no agentic autonomy.

## 12. Open questions

- **OQ1** — ~~nested groups?~~ **RESOLVED**: supported in v1.4.5, but rejected for CARGO BAY
  (flat `row`×6 — see §4).
- **OQ2** — ~~stable DOM selectors?~~ **RESOLVED**: §6.8 list, source-verified at tag v1.4.5.
- **OQ3** — ~~Synology vs QNAP~~ **RESOLVED 2026-06-11**: Synology dead (502); `qnap.lab`
  already wired → teardown + repoint (§5, §6.5).

---

## 13. Plan — the literal contracts

### settings.yaml (T1 — full intended content of the theme-relevant keys)

```yaml
title: USCSS PI-K3S
description: Raspberry Pi Kubernetes Cluster
theme: dark
color: teal
headerStyle: clean
statusStyle: dot
iconStyle: theme
hideVersion: true
useEqualHeights: true
fullWidth: true
layout:
  COMMAND:      { style: row, columns: 4, icon: mdi-monitor-dashboard }
  COMMS:        { style: row, columns: 4, icon: mdi-antenna }
  AI CORE:      { style: row, columns: 5, icon: mdi-brain }
  REC DECK:     { style: row, columns: 3, icon: mdi-popcorn }
  ACQUISITION:  { style: row, columns: 4, icon: mdi-download-network }
  CARGO BAY:    { style: row, columns: 6, icon: mdi-package-variant-closed }
```

### Deck assignment table (T2 — the regroup contract; tiles moved VERBATIM unless noted)

| Deck (exact key) | Tiles (exact current names) |
|---|---|
| `COMMAND` | Grafana · Uptime Kuma · Prometheus · Loki |
| `COMMS` | Pi-hole (pi-k3s) · Pi-hole (pi5-worker-1) · Unifi Controller · Tailscale |
| `AI CORE` | Beelink GTR9 Pro · AI Mode · Dewey (kids) · Adults Chat · LiteLLM API |
| `REC DECK` | Jellyfin · Immich · Jellyseerr |
| `ACQUISITION` | Sonarr · Radarr · Bazarr · SABnzbd |
| `CARGO BAY` | Calibre-Web · LazyLibrarian · Kiwix · **QNAP NAS** ① · Lidarr · qBittorrent · Prowlarr · n8n · Log Drain · Personal Site (Cluster) · Personal Site (Heroku) · Cloudflare |

① QNAP NAS replaces "Synology NAS": `icon: qnap.png`, `href: https://qnap.lab.mtgibbs.dev`,
`description: Storage`, `siteMonitor: https://qnap.lab.mtgibbs.dev`.

**Dropped tiles** (rationale §6.3/§6.4): `pi-k3s`, `pi5-worker-1`, `pi5-worker-2`,
`pi3-worker-2`, `Unbound`.

### Synology teardown (T3)

1. `git rm clusters/pi-k3s/external-services/synology.yaml`; delete the `- synology.yaml`
   line from `external-services/kustomization.yaml`.
2. `autokuma-monitors.yaml` → `synology.json` key: `"name": "QNAP NAS"`,
   `"url": "https://qnap.lab.mtgibbs.dev/"` — nothing else changes in the entity.
3. Bump `mtgibbs.dev/monitors-revision` annotation (uptime-kuma deployment pod template).

## 13b. Widget capability matrix (v1.4.5, source-tag audit 2026-06-11)

What each of OUR widgets CAN show vs what we configure. Decision column is binding.

| Widget | Available fields/options | We show | Decision |
|---|---|---|---|
| pihole (×2, v6) | `queries, blocked, blocked_percent, gravity`; default `queries, blocked, gravity` (blocked merges %) | all 4 explicit | **Drop `blocked_percent`** → 3 fields; `blocked` already merges the % inline. Less cramp. |
| unifi | `uptime, wan, lan, lan_users, lan_devices, wlan, wlan_users, wlan_devices` | `wlan_users, lan_devices, wan` | Keep. |
| tailscale | `address, last_seen, expires` | default (all 3) | Keep default. |
| uptimekuma | `up, down, uptime, incident` (needs status-page `slug`) | default (all) | Keep; `incident` auto-appears during incidents. |
| prometheus | `targets_up, targets_down, targets_total` | all 3 | Keep. |
| jellyfin | blocks `movies, series, episodes, songs` (needs `enableBlocks`); `enableNowPlaying` (default on), `enableMediaControl` (default on), `showEpisodeNumber`, `enableUser` | enableBlocks + nowPlaying | Keep; add `showEpisodeNumber: true` (nice for glance). |
| immich (v2) | `users, photos, videos, storage`; admin key required | `photos, videos, storage` | Keep. |
| sonarr | `wanted, queued, series`; `enableQueue` detail rows | default | Keep; **no** `enableQueue` (clutter). |
| radarr | `wanted, missing, queued, movies` | default (all 4) | Keep. |
| bazarr | `missingEpisodes, missingMovies` | default | Keep. |
| sabnzbd | `rate, queue, timeleft` | default | Keep. |
| prometheusmetric (Beelink) | metrics list; **silent `slice(0,4)`** | VRAM/GPU/Temp/RAM = exactly 4 | Keep — at the cap, add nothing. |
| customapi (AI Mode, Loki) | mappings; **block display `slice(0,4)`**; formats incl. remap/scale/suffix | 1–2 mappings | Keep verbatim (§6.7). |

Header info widgets (kubernetes/openmeteo/datetime/search): unchanged; CSS restyles them.

## 14. Tuning log

**Round 1 (2026-06-11)** — `qwen3-coder` via `oc run`, headless one-shot, **pure text
generator** (no tools — per the coding-agent-ops gotcha; markers on stdout, orchestrator did
file I/O + splice). Input: §13 deck table + §13b edit list + §6.7 contrast warning + current
`services.yaml` inline. Result: **clean pass, zero misses** — 6 decks in order, exact tile
counts (4/4/5/3/4/12), all three edits (pihole fields, jellyfin episode numbers, QNAP tile
block) applied exactly, Loki/AI-Mode customapi moved verbatim, drops honored. `verify.sh`
green on first splice.

> Confirms the predecessor's meta-lesson at higher spec maturity: a literal deck table +
> explicit edit list + named contrast warning = nothing left to guess. The tools-off text
> path also avoided the malformed-tool-call stall entirely.

## Two-way sync rule

Logic change → spec first, then config. Refactor → config, then sync fact back here.
Hotfix → post-mortem into §14.
