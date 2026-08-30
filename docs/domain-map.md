# Domain map — what runs where, needs what, and deploys after what

> The **service lens** on the cluster: for each service (a directory under
> `clusters/pi-k3s/`), what it **runs** (workloads + images), what it **needs**
> (creds, storage), how it's **reached** (ingress), who it **talks to** (in-cluster
> calls), and what must **deploy first** (Flux `dependsOn`). The credential lens is
> [`secrets-map.md`](./secrets-map.md); this map cross-links to it for cred detail.

## How to use this

- **Onboarding a change to service X?** Find its card: its images (🔒priv = a private
  `ghcr.io/mtgibbs` image that needs `ghcr-pull-secret`), the creds it consumes, its PVCs,
  its ingress host, and the services it calls.
- **"What deploys before X?"** → the deploy-order DAG. An arrow A → B means A reconciles first.
  Getting this wrong is the usual cause of a first-boot `ExternalSecret not found` / CRD-missing error.
- **Blast radius of a shared dependency** (e.g. `external-secrets-config`, `ingress`) → follow its
  outgoing arrows in the DAG; everything downstream waits on it.
- **Credentials** → each card lists cred *names*; walk `secrets-map.md` / the `secrets-graph` skill
  for the full item → ExternalSecret → consumer detail and the reuse-before-mint rule.

## Keeping it true (no drift)

Generated from the manifests, like `secrets-map.md`:

```bash
node scripts/gen-domain-map.mjs clusters/pi-k3s --inject docs/domain-map.md
```

Deterministic bytes; CI/pre-merge check = run it, then `git diff --exit-code docs/domain-map.md`.
Modes: `--deps` (DAG mermaid), `--json` (machine graph), default = per-service node index.
Regex-per-document manifest walk — no YAML-parser dependency. What a pod-spec walk can't see
(HelmRelease-managed workloads like cert-manager/monitoring show empty of local workloads; the
Flux ordering still renders) is expected — those services deploy via a `HelmRelease`, not a
Deployment manifest in the dir.

<!-- BEGIN GENERATED:domain-map -->
<!-- Regenerate: node scripts/gen-domain-map.mjs clusters/pi-k3s --inject docs/domain-map.md -->
<!-- Do not hand-edit between these markers; edits are overwritten. -->

_40 services · 70 workloads · 41 Flux Kustomizations · 8 services on a private image. Auto-derived from `clusters/pi-k3s/**`._

## Deploy-order DAG (Flux `dependsOn`)

_What must reconcile before what. An arrow A → B means A deploys before B._

```mermaid
graph LR
  k4urrac["atlas"]
  kkuvy6m["ingress"]
  kkuvy6m --> k4urrac
  k19g0j44["cert-manager-config"]
  k19g0j44 --> k4urrac
  kwoyrdm["backup-jobs"]
  k1unc8vb["external-secrets-config"]
  k1unc8vb --> kwoyrdm
  kfd8pog["pihole"]
  kfd8pog --> kwoyrdm
  kzp0jgv["monitoring"]
  kzp0jgv --> kwoyrdm
  k9ewesc["uptime-kuma"]
  k9ewesc --> kwoyrdm
  kwdw79["calendar"]
  k1unc8vb --> kwdw79
  k1b1zvd7["cert-manager"]
  k1b1zvd7 --> k19g0j44
  k1unc8vb --> k19g0j44
  k19brzrp["cloudflare-tunnel"]
  k1unc8vb --> k19brzrp
  kc9q0cb["coredns-custom"]
  k38fyg["external-secrets"]
  k38fyg --> k1unc8vb
  k9y7g1l["external-services"]
  kkuvy6m --> k9y7g1l
  k19g0j44 --> k9y7g1l
  k1xirz5w["family-board"]
  k1unc8vb --> k1xirz5w
  kkuvy6m --> k1xirz5w
  k19g0j44 --> k1xirz5w
  kd9c6dn["flux-notifications"]
  k1unc8vb --> kd9c6dn
  ka3ayi4["flux-system"]
  k6vrex["harness"]
  k1unc8vb --> k6vrex
  kkuvy6m --> k6vrex
  k19g0j44 --> k6vrex
  kzud5vu["harness-fleet"]
  k1unc8vb --> kzud5vu
  k1uuov05["homepage"]
  kkuvy6m --> k1uuov05
  k19g0j44 --> k1uuov05
  kc47lkc["immich"]
  k1unc8vb --> kc47lkc
  kkuvy6m --> kc47lkc
  k19g0j44 --> kc47lkc
  k1ce1t9w["jellyfin"]
  k1unc8vb --> k1ce1t9w
  kkuvy6m --> k1ce1t9w
  k19g0j44 --> k1ce1t9w
  k502wpt["kiwix"]
  kkuvy6m --> k502wpt
  k19g0j44 --> k502wpt
  k14qwwry["kiwix-mcp"]
  k1unc8vb --> k14qwwry
  kkuvy6m --> k14qwwry
  k19g0j44 --> k14qwwry
  k502wpt --> k14qwwry
  kafk4a9["local-llm-mcp"]
  k1unc8vb --> kafk4a9
  kkuvy6m --> kafk4a9
  k19g0j44 --> kafk4a9
  k114pw4y["log-aggregation"]
  k19brzrp --> k114pw4y
  kzp0jgv --> k114pw4y
  kdtx7rc["matrix"]
  k1unc8vb --> kdtx7rc
  kkuvy6m --> kdtx7rc
  k19g0j44 --> kdtx7rc
  kwjjkc4["mcp-homelab"]
  k1unc8vb --> kwjjkc4
  kkuvy6m --> kwjjkc4
  k19g0j44 --> kwjjkc4
  kdvs4x2["mealie"]
  k1unc8vb --> kdvs4x2
  kkuvy6m --> kdvs4x2
  k19g0j44 --> kdvs4x2
  k513jul["media"]
  k1unc8vb --> k513jul
  kkuvy6m --> k513jul
  k19g0j44 --> k513jul
  k52qv9g["model-watch"]
  k1unc8vb --> k52qv9g
  k1unc8vb --> kzp0jgv
  kkuvy6m --> kzp0jgv
  k19g0j44 --> kzp0jgv
  kbau5m9["mtgibbs-site"]
  kkuvy6m --> kbau5m9
  k19g0j44 --> kbau5m9
  k6rwd["n8n"]
  k1unc8vb --> k6rwd
  kkuvy6m --> k6rwd
  k19g0j44 --> k6rwd
  kwdw79 --> k6rwd
  k7t7fws["new-horizons"]
  k1unc8vb --> k7t7fws
  k5v99c["ntfy"]
  k1unc8vb --> k5v99c
  k1unc8vb --> kfd8pog
  kkuvy6m --> kfd8pog
  k19g0j44 --> kfd8pog
  kkwvqlc["private-exit-node"]
  k1unc8vb --> kkwvqlc
  k1uve1zr["renovate"]
  k1unc8vb --> k1uve1zr
  k18pua87["review-hub"]
  k1unc8vb --> k18pua87
  k5xpno["romm"]
  k1unc8vb --> k5xpno
  kkuvy6m --> k5xpno
  k19g0j44 --> k5xpno
  k1bbtmmr["tailscale"]
  k1unc8vb --> k1bbtmmr
  k1nts3uk["tailscale-config"]
  k1bbtmmr --> k1nts3uk
  kfd8pog --> k1nts3uk
  k1unc8vb --> k9ewesc
  kkuvy6m --> k9ewesc
  k19g0j44 --> k9ewesc
```

## Services

_Per service: what it runs (🔒priv = private image), needs (creds → `secrets-map.md`, storage), how it's reached (ingress), and who it talks to (calls)._

_Images are listed **without tags** on purpose — this map is topology, and the deployed version is a property of the cluster, not of this repo. Read the live tag with `get_flux_status` / `describe_resource`. (Tags here made every bot image bump a map change, and image-automation pushes bypass the PR gate that regenerates it, so unrelated PRs inherited a red `drift`.)_

### atlas  ·  Flux: `atlas` (after: `ingress`, `cert-manager-config`)
- **Deployment/atlas** — `nginx`
  - ingress: `atlas.lab.mtgibbs.dev`

### backup-jobs  ·  Flux: `backup-jobs` (after: `external-secrets-config`, `pihole`, `monitoring`, `uptime-kuma`)
- **CronJob/git-mirror-backup** — `instrumentisto/rsync-ssh`
- **CronJob/k3s-datastore-backup** — `instrumentisto/rsync-ssh`
- **CronJob/mariadb-backup** — `instrumentisto/rsync-ssh`
- **CronJob/media-backup** — `instrumentisto/rsync-ssh`
- **CronJob/postgres-backup** — `instrumentisto/rsync-ssh`
- **CronJob/pvc-backup** — `instrumentisto/rsync-ssh`
- **CronJob/restore-test** — `instrumentisto/rsync-ssh`
- **CronJob/unifi-backup** — `alpine`
- **CronJob/worker2-backup** — `instrumentisto/rsync-ssh`
  - creds: `immich-db-password`, `matrix-db-password`, `mealie-db-password`, `n8n-db-password`, `romm-db-password`, `unifi-credentials`  _(→ secrets-map.md)_
  - storage: `restore-canary`
  - calls: → `immich`, → `matrix`, → `mealie`, → `n8n`, → `romm`

### calendar  ·  Flux: `calendar` (after: `external-secrets-config`)
- **Deployment/calendar** — `nginx`
  - storage: `calendar-data`

### cert-manager  ·  Flux: `cert-manager`

### cert-manager-config  ·  Flux: `cert-manager-config` (after: `cert-manager`, `external-secrets-config`)

### cloudflare-tunnel  ·  Flux: `cloudflare-tunnel` (after: `external-secrets-config`)
- **Deployment/cloudflared** — `alpine`, `cloudflare/cloudflared`
  - creds: `cloudflare-tunnel`  _(→ secrets-map.md)_
  - calls: → `calendar`, → `log-aggregation`, → `mtgibbs-site`, → `n8n`, → `ntfy`, → `review-hub`

### coredns-custom  ·  Flux: `coredns-custom`
- **DaemonSet/pi-k3s-hosts-overrides** — `alpine`

### external-secrets  ·  Flux: `external-secrets`

### external-secrets-config  ·  Flux: `external-secrets-config` (after: `external-secrets`)

### external-services  ·  Flux: `external-services` (after: `ingress`, `cert-manager-config`)
  - ingress: `qnap.lab.mtgibbs.dev`, `unifi.lab.mtgibbs.dev`

### family-board  ·  Flux: `family-board` (after: `external-secrets-config`, `ingress`, `cert-manager-config`)
- **Deployment/family-board** — `nginx`
  - creds: `family-board-feed`  _(→ secrets-map.md)_
  - ingress: `board.lab.mtgibbs.dev`

### flux-notifications  ·  Flux: `flux-notifications` (after: `external-secrets-config`)

### harness  ·  Flux: `harness` (after: `external-secrets-config`, `ingress`, `cert-manager-config`)
- **Deployment/harness-coordinator** — `ghcr.io/mtgibbs/harness-coordinator` 🔒priv
  - creds: `ghcr-pull-secret`, `harness-coordinator`  _(→ secrets-map.md)_
  - storage: `harness-coordinator-state`
  - ⚠️ private image → needs `ghcr-pull-secret` (reuse `ghcr-read-token`)
  - ingress: `harness.lab.mtgibbs.dev`

### harness-fleet  ·  Flux: `harness-fleet` (after: `external-secrets-config`)
  - calls: → `harness`

### homepage  ·  Flux: `homepage` (after: `ingress`, `cert-manager-config`)
- **Deployment/homepage** — `busybox`, `ghcr.io/gethomepage/homepage`
  - creds: `homepage-ai-controlpanel`, `homepage-immich`, `homepage-jellyfin`, `homepage-pihole`, `homepage-pihole-secondary`, `homepage-servarr`, `homepage-tailscale`, `homepage-unifi`  _(→ secrets-map.md)_
  - ingress: `home.lab.mtgibbs.dev`
  - calls: → `immich`, → `jellyfin`, → `log-aggregation`, → `media`, → `monitoring`, → `pihole`, → `uptime-kuma`

### immich  ·  Flux: `immich` (after: `external-secrets-config`, `ingress`, `cert-manager-config`)
- **Deployment/immich-postgresql** — `ghcr.io/immich-app/postgres`
  - creds: `immich-secret`  _(→ secrets-map.md)_
  - storage: `immich-postgresql-data`

### ingress  ·  Flux: `ingress`

### jellyfin  ·  Flux: `jellyfin` (after: `external-secrets-config`, `ingress`, `cert-manager-config`)
- **Deployment/jellyfin** — `jellyfin/jellyfin`
  - storage: `jellyfin-config`, `jellyfin-video`
  - ingress: `jellyfin.lab.mtgibbs.dev`

### kiwix  ·  Flux: `kiwix` (after: `ingress`, `cert-manager-config`)
- **Deployment/kiwix** — `ghcr.io/kiwix/kiwix-tools`
- **Job/kiwix-seed** — `curlimages/curl`, `ghcr.io/kiwix/kiwix-tools`
  - storage: `kiwix-zim`
  - ingress: `kiwix.lab.mtgibbs.dev`

### kiwix-mcp  ·  Flux: `kiwix-mcp` (after: `external-secrets-config`, `ingress`, `cert-manager-config`, `kiwix`)
- **Deployment/kiwix-mcp** — `ghcr.io/mtgibbs/kiwix-mcp` 🔒priv
  - creds: `kiwix-mcp-secrets`  _(→ secrets-map.md)_
  - ⚠️ private image → needs `ghcr-pull-secret` (reuse `ghcr-read-token`)
  - ingress: `kiwix-mcp.lab.mtgibbs.dev`
  - calls: → `kiwix`

### local-llm-mcp  ·  Flux: `local-llm-mcp` (after: `external-secrets-config`, `ingress`, `cert-manager-config`)
- **Deployment/local-llm-mcp** — `ghcr.io/mtgibbs/local-llm-mcp` 🔒priv
  - creds: `local-llm-mcp-secrets`  _(→ secrets-map.md)_
  - ⚠️ private image → needs `ghcr-pull-secret` (reuse `ghcr-read-token`)
  - ingress: `local-llm-mcp.lab.mtgibbs.dev`

### log-aggregation  ·  Flux: `log-aggregation` (after: `cloudflare-tunnel`, `monitoring`)
- **Deployment/vector** — `timberio/vector`
  - creds: `vector-ntfy`  _(→ secrets-map.md)_
  - calls: → `ntfy`

### matrix  ·  Flux: `matrix` (after: `external-secrets-config`, `ingress`, `cert-manager-config`)
- **Deployment/element-web** — `vectorim/element-web`
- **Deployment/matrix-postgresql** — `postgres`
- **Deployment/synapse** — `matrixdotorg/synapse`
  - creds: `matrix-secret`  _(→ secrets-map.md)_
  - storage: `matrix-postgresql-data`, `synapse-data`
  - ingress: `element.lab.mtgibbs.dev`, `matrix.lab.mtgibbs.dev`

### mcp-homelab  ·  Flux: `mcp-homelab` (after: `external-secrets-config`, `ingress`, `cert-manager-config`)
- **DaemonSet/mcp-debug-agent** — `nicolaka/netshoot`
- **Deployment/mcp-homelab** — `ghcr.io/mtgibbs/pi-cluster-mcp` 🔒priv
  - creds: `mcp-homelab-secrets`  _(→ secrets-map.md)_
  - ⚠️ private image → needs `ghcr-pull-secret` (reuse `ghcr-read-token`)
  - ingress: `mcp.lab.mtgibbs.dev`

### mealie  ·  Flux: `mealie` (after: `external-secrets-config`, `ingress`, `cert-manager-config`)
- **Deployment/mealie** — `ghcr.io/mealie-recipes/mealie`
- **Deployment/mealie-postgresql** — `postgres`
- **Job/mealie-ai-provider-bootstrap-v3** — `python`
  - creds: `mealie-ai-secret`, `mealie-secret`  _(→ secrets-map.md)_
  - storage: `mealie-data`, `mealie-postgresql-data`
  - ingress: `recipes.lab.mtgibbs.dev`

### media  ·  Flux: `media` (after: `external-secrets-config`, `ingress`, `cert-manager-config`)
- **CronJob/import-resolver** — `alpine`
- **CronJob/orphan-sweep** — `alpine`
- **Deployment/bazarr** — `linuxserver/bazarr`
- **Deployment/calibre-web** — `lscr.io/linuxserver/calibre-web`
- **Deployment/flaresolverr** — `ghcr.io/flaresolverr/flaresolverr`
- **Deployment/jellyseerr** — `fallenbagel/jellyseerr`
- **Deployment/lazylibrarian** — `lscr.io/linuxserver/lazylibrarian`
- **Deployment/lidarr** — `linuxserver/lidarr`
- **Deployment/prowlarr** — `linuxserver/prowlarr`
- **Deployment/qbittorrent** — `qmcgaw/gluetun`, `linuxserver/qbittorrent`
- **Deployment/radarr** — `linuxserver/radarr`
- **Deployment/readarr** — `linuxserver/readarr`
- **Deployment/sabnzbd** — `linuxserver/sabnzbd`
- **Deployment/sonarr** — `linuxserver/sonarr`
  - creds: `protonvpn-credentials`, `qbittorrent-credentials`, `servarr-api-keys`  _(→ secrets-map.md)_
  - storage: `bazarr-config`, `calibre-web-config`, `jellyseerr-config`, `lazylibrarian-config`, `lidarr-config`, `media-books`, `media-downloads`, `media-library`, `media-music`, `prowlarr-config`, `qbittorrent-config`, `radarr-config`, `readarr-config`, `sabnzbd-config`, `sonarr-config`
  - ingress: `bazarr.lab.mtgibbs.dev`, `calibre.lab.mtgibbs.dev`, `lazylibrarian.lab.mtgibbs.dev`, `lidarr.lab.mtgibbs.dev`, `prowlarr.lab.mtgibbs.dev`, `qbit.lab.mtgibbs.dev`, `radarr.lab.mtgibbs.dev`, `readarr.lab.mtgibbs.dev`, `requests.lab.mtgibbs.dev`, `sabnzbd.lab.mtgibbs.dev`, `sonarr.lab.mtgibbs.dev`

### model-watch  ·  Flux: `model-watch` (after: `external-secrets-config`)
- **CronJob/model-watch** — `python`
  - creds: `model-watch-secret`  _(→ secrets-map.md)_
  - calls: → `ntfy`

### monitoring  ·  Flux: `monitoring` (after: `external-secrets-config`, `ingress`, `cert-manager-config`)
  - ingress: `grafana.lab.mtgibbs.dev`
  - calls: → `log-aggregation`

### mtgibbs-site  ·  Flux: `mtgibbs-site` (after: `ingress`, `cert-manager-config`)
- **Deployment/mtgibbs-site** — `ghcr.io/mtgibbs/mtgibbs.xyz` 🔒priv
  - creds: `mtgibbs-github`, `mtgibbs-spotify`, `mtgibbs-tracking`  _(→ secrets-map.md)_
  - ⚠️ private image → needs `ghcr-pull-secret` (reuse `ghcr-read-token`)
  - ingress: `site.lab.mtgibbs.dev`

### n8n  ·  Flux: `n8n` (after: `external-secrets-config`, `ingress`, `cert-manager-config`, `calendar`)
- **Deployment/n8n** — `n8nio/n8n`
- **Deployment/n8n-postgresql** — `postgres`
- **Deployment/n8n-valkey** — `valkey/valkey`
- **Deployment/n8n-webhook** — `n8nio/n8n`
- **Deployment/n8n-worker** — `n8nio/n8n`
  - creds: `n8n-secret`  _(→ secrets-map.md)_
  - storage: `n8n-calendar`, `n8n-data`, `n8n-postgresql-data`, `n8n-valkey-data`
  - ingress: `n8n.lab.mtgibbs.dev`

### new-horizons  ·  Flux: `new-horizons` (after: `external-secrets-config`)
- **Deployment/new-horizons** — `ghcr.io/mtgibbs/new-horizons` 🔒priv
  - creds: `ghcr-pull-secret`, `new-horizons-secrets`  _(→ secrets-map.md)_
  - storage: `new-horizons-data`
  - ⚠️ private image → needs `ghcr-pull-secret` (reuse `ghcr-read-token`)

### ntfy  ·  Flux: `ntfy` (after: `external-secrets-config`)
- **Deployment/ntfy** — `binwiederhier/ntfy`
  - creds: `ntfy-secret`  _(→ secrets-map.md)_
  - storage: `ntfy-data`

### pihole  ·  Flux: `pihole` (after: `external-secrets-config`, `ingress`, `cert-manager-config`)
- **CronJob/pihole-brainrot-allow** — `alpine`
- **CronJob/pihole-brainrot-block** — `alpine`
- **Deployment/pihole** — `pihole/pihole`
- **Deployment/pihole-exporter** — `ekofr/pihole-exporter`
- **Deployment/pihole-exporter-secondary** — `ekofr/pihole-exporter`
- **Deployment/pihole-secondary** — `pihole/pihole`
- **Deployment/unbound** — `madnuttah/unbound`
- **Deployment/unbound-secondary** — `madnuttah/unbound`
- **Job/pihole-brainrot-setup-adgroups-2** — `alpine`
  - creds: `pihole-secret`  _(→ secrets-map.md)_
  - storage: `pihole-dnsmasq`, `pihole-dnsmasq-secondary`, `pihole-etc`, `pihole-etc-secondary`
  - ingress: `pihole.lab.mtgibbs.dev`

### private-exit-node  ·  Flux: `private-exit-node` (after: `external-secrets-config`)
- **Deployment/exit-node-gateway** — `ghcr.io/mtgibbs/private-exit-node` 🔒priv
  - creds: `exit-node-secrets`, `ghcr-pull-secret`  _(→ secrets-map.md)_
  - ⚠️ private image → needs `ghcr-pull-secret` (reuse `ghcr-read-token`)

### renovate  ·  Flux: `renovate` (after: `external-secrets-config`)
- **CronJob/renovate** — `renovate/renovate`
  - creds: `renovate-secrets`  _(→ secrets-map.md)_

### review-hub  ·  Flux: `review-hub` (after: `external-secrets-config`)
- **Deployment/review-hub** — `ghcr.io/mtgibbs/review-hub` 🔒priv
  - creds: `review-hub-secrets`  _(→ secrets-map.md)_
  - ⚠️ private image → needs `ghcr-pull-secret` (reuse `ghcr-read-token`)

### romm  ·  Flux: `romm` (after: `external-secrets-config`, `ingress`, `cert-manager-config`)
- **Deployment/romm** — `rommapp/romm`
- **Deployment/romm-mariadb** — `mariadb`
  - creds: `romm-secret`  _(→ secrets-map.md)_
  - storage: `romm-config`, `romm-games`, `romm-mariadb-data`, `romm-redis-data`
  - ingress: `romm.lab.mtgibbs.dev`

### tailscale  ·  Flux: `tailscale` (after: `external-secrets-config`)

### tailscale-config  ·  Flux: `tailscale-config` (after: `tailscale`, `pihole`)

### uptime-kuma  ·  Flux: `uptime-kuma` (after: `external-secrets-config`, `ingress`, `cert-manager-config`)
- **Deployment/autokuma** — `alpine`, `ghcr.io/bigboot/autokuma`
- **Deployment/uptime-kuma** — `louislam/uptime-kuma`
  - creds: `uptime-kuma-secret`  _(→ secrets-map.md)_
  - storage: `autokuma-data`, `uptime-kuma-data`
  - ingress: `status.lab.mtgibbs.dev`
  - calls: → `log-aggregation`, → `monitoring`, → `pihole`, → `review-hub`, → `tailscale`

<!-- END GENERATED:domain-map -->
