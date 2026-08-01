# Pattern: deploy-health verification

**When:** just deployed/reconciled a service (or a PR merged) and want to confirm it actually came up —
not just that Flux said "applied". Also the go-to for "service X is 404/500/unreachable after a change".

**Uses the domain map:** `docs/domain-map.md` tells you this service's images, creds, storage, ingress
host, and **what must deploy before it** (Flux `dependsOn`). Check the card first — most first-boot
failures are a dependency that hasn't reconciled yet.

## Layers (each independent — fan out one worker per layer)

| # | Layer | Tool(s) | Healthy verdict | Red flags |
|---|---|---|---|---|
| 1 | Flux reconciled | `get_flux_status` | Kustomization + its `dependsOn` all Ready | stuck reconciling, dependency not Ready, `wait` timeout |
| 2 | Pods up | `get_cluster_health`, `get_pod_logs <svc>` | Running, ready, no restarts | CrashLoop, ImagePullBackOff, Pending (no node/resources) |
| 3 | Secrets synced | `get_secrets_status`, `refresh_secret` if stale | ExternalSecret → k8s Secret present | `SecretSyncedError`, 1Password item/field typo (check `secrets-map.md`) |
| 4 | Ingress + cert | `get_ingress_status`, `get_certificate_status`, `curl_ingress` | endpoint answers, cert valid/not-expiring | 404 (no backend), cert pending/failed (DNS01) |
| 5 | Image pull (private only) | is it `ghcr.io/mtgibbs/*`? | `ghcr-pull-secret` present in ns | ImagePullBackOff → missing/!reused `ghcr-read-token` (see `secrets-map.md`) |
| 6 | Backup (stateful only) | `get_backup_status` | PVC covered by a backup CronJob | new stateful service with no backup wired |

## Discipline for THIS scenario

- **Flux "applied" ≠ healthy.** It means the manifest was accepted, not that the pod is serving. Always
  go past layer 1.
- **Order is usually the bug.** If layer 2 shows Pending/CrashLoop right after deploy, check layer 1's
  `dependsOn` — `external-secrets-config`, `ingress`, `cert-manager-config` gate most services (see the
  deploy-order DAG in `docs/domain-map.md`).
- **ImagePullBackOff on a private image** → almost always the `ghcr-pull-secret`/`ghcr-read-token` reuse,
  not a new credential. `[[secrets-graph]]`.

## Synthesis

First failing layer is usually the root cause and downstream layers are just symptoms (no secret →
CrashLoop → 404). Fix the earliest failing layer, re-check downstream. Hand the actual manifest/secret
change to `cluster-ops`.
