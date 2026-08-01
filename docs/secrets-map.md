# Secrets map — what exists, what it's for, and when NOT to mint a new one

> Read this **before adding any credential to a new or existing service.** It exists because an agent
> (me) invented a `ghcr-pull` token in 2026-08 when `ghcr-read-token` already did the job — the exact
> mistake this map prevents.

## The one rule

**Reuse before mint.** Shared *infrastructure* identities (pull images, send alerts, reach the NAS)
are one-per-role, not one-per-service. A new service references the existing item; it does **not**
create a parallel token. Mint a new secret only for a genuinely **per-workload** cred (this service's
own DB password, its own scoped LiteLLM key). When unsure: `grep -r "remoteRef" clusters/` or check
the tables below.

## How secrets work here

- Source of truth: **1Password**, vault `pi-cluster`. Nothing secret is committed — only `op://` paths.
- Delivery: **External Secrets Operator** → `ClusterSecretStore` named `onepassword`. Each service has
  an `ExternalSecret` mapping `remoteRef.key: <item>/<field>` → a k8s Secret in its namespace.
- Path shape: `op://pi-cluster/<item>/<field>` ⇄ `remoteRef: { key: <item>/<field> }`.

## Shared identities — REUSE, do not mint a parallel one

| Role | 1Password item | Materializes as | Used by |
|---|---|---|---|
| **Pull private GHCR images** | `ghcr-read-token/token` | `ghcr-pull-secret` (per-ns `dockerconfigjson`) + Flux `ghcr-credentials` | Flux image-automation (all `ghcr.io/mtgibbs/*`) + any private-image workload (`private-exit-node`; now new-horizons). **New private service:** copy `external-secret-ghcr.yaml` into its ns + `imagePullSecrets: [ghcr-pull-secret]`. Zero new creds. |
| **Push alerts** | `ntfy/family-password`, `discord-alerts/webhook-url`, `alertmanager/discord-alerts-webhook-url`, `healthchecks/watchdog-ping-url` | per-consumer Secret/env | ntfy family channel, Alertmanager→Discord, external watchdog. Reuse the topic/webhook — don't stand up a new alert identity per service. |
| **Reach the NAS (QNAP)** | `nas/uid`, `nas/gid`, `mcp-homelab/nas-private-key` | env / ssh key | backup jobs, media, anything mounting/rsync'ing the NAS. |
| **Cloudflare (DNS/tunnel)** | `cloudflare/api-token` (DNS-only), `cloudflare-tunnel/tunnel-token` | — | cert-manager DNS01, the tunnel. ⚠️ `cloudflare` token is **DNS-only** — not R2/Email/Workers. |
| **GitHub (as the automation)** | `mtgibbs-github/token`, `github-mirror-token/token`, the **review-hub GitHub App** | — | mirror backups, Renovate, PR review. Prefer the App for repo actions; one identity across repos. |

## Per-workload by design — mint one per service (NOT sprawl, just scope)

| Kind | Examples | Why separate |
|---|---|---|
| **LiteLLM virtual key** | `local-llm-mcp/litellm-key`, `mealie/litellm-key`, `review-hub/litellm-key`, `new-horizons/litellm-key` | Deliberate: per-consumer **cost attribution**, independent **rotation/revocation**, and **model scoping**. This is what virtual keys are for — not a violation of "reuse." |
| **App DB / app secrets** | `n8n/*`, `matrix/*`, `immich/*`, `mealie/db-password`, `grafana/password`, `pihole/password` | Genuinely private to that app. |
| **Service accounts / API tokens for that app** | `mtgibbs-spotify/*`, `opensubtitles/*`, `newshosting/*`, `protonvpn-credentials/*` | Third-party creds owned by one service. |

## Handling tiers (who/what may touch a cred)

1. **Safe, read-only** — pull tokens, LiteLLM keys, endpoints. Fine for automation; the *right* way to
   expose these to the harness is a **homelab-MCP diagnostic** (e.g. "verify this pull works"), **not** a
   raw keystore. See `[[reference_harness_claude_capabilities]]`.
2. **Cluster-acting** — `mcp-homelab/*` (restart/exec), kubeconfig. Behind the MCP's own auth; not on the
   harness hot path.
3. **Crown jewel** — anything that can destroy data or move money; stays **biometric / laptop-only**,
   never relocated into a container. (`backup-ops` SKILL, the op Touch-ID creds.)

**Image + PII note:** an image that bakes in PII (e.g. new-horizons' `profile/` = résumé) stays a
**private** GHCR package (pulled via `ghcr-read-token`). Only PII-free images may be public.

## Checklist — adding secrets to a service

1. **Pull a private image?** → reuse `ghcr-read-token` → `ghcr-pull-secret` (table above). Don't mint.
2. **Send alerts?** → reuse the ntfy topic / Discord webhook. Don't mint an alert identity.
3. **Call the local LLM?** → mint **one** scoped `op://pi-cluster/<service>/litellm-key` (per-workload,
   on purpose).
4. **App's own DB/API secret?** → mint `op://pi-cluster/<service>/<field>`, one `ExternalSecret`.
5. Never commit a value; only the `op://` path. Grep `clusters/` for the role before creating anything.
