# Spec: Agent Bus — Phase 0 (Matrix Synapse + Element on K3s)

- **Status:** Draft v0.1 (awaiting Matt's glance, then OQ resolution → hand to ralph-qwen)
- **Owner:** laptop-Claude (orchestrator); executor = qwen via `scripts/ralph-qwen.sh`
- **Constitution:** `specs/constitution.md` (+ `/CLAUDE.md` Core Mandates)
- **Approved plan:** `~/.claude/plans/we-can-review-it-fizzy-pancake.md` (rev 3)
- **Touches:** new `clusters/pi-k3s/matrix/*`; `clusters/pi-k3s/flux-system/infrastructure.yaml`;
  (optional) `clusters/pi-k3s/pihole/pihole-custom-dns.yaml`; `ARCHITECTURE.md` Decision #13.

---

## 1. Why · [R]
The homelab agents + humans have shared durable state (the memory vault) but no shared **live
channel**. Phase 0 stands up the private, self-hosted chat backend — a Matrix homeserver
(Synapse) + web client (Element) — that Phase 1's `agent-bus` CLI and Phase 2's qwen listener
will build on. This spec is Phase 0 ONLY: a running, private homeserver with logins working.

## 2. Outcomes (Definition of Done) · [R]
1. `https://matrix.lab.mtgibbs.dev/_matrix/client/versions` returns JSON over LAN TLS.
2. A human logs into Element at `https://element.lab.mtgibbs.dev` against our homeserver.
3. Federation is OFF (no inbound 8448, no outbound whitelist) and open registration is OFF.
4. All secrets come from 1Password via ExternalSecret — none inline in git.
5. Everything runs on `pi5-worker-2` within declared memory limits; Flux reconciles clean.

## 3. Entities · [E]
- **Namespace:** `matrix`.
- **ExternalSecret `matrix-secret`** (ClusterSecretStore `onepassword`) → renders:
  - `POSTGRES_PASSWORD` (scalar, for the postgres container)
  - `homeserver-secrets.yaml` (a Synapse config fragment: `database.args.password`,
    `registration_shared_secret`, `macaroon_secret_key`, `form_secret` — secrets inline here
    only, kept OUT of the ConfigMap). Pulls 1Password item `matrix` fields:
    `db-password`, `registration-shared-secret`, `macaroon-secret`, `form-secret`.
- **Postgres** `matrix-postgresql` (DB `synapse`, user `synapse`) — mirror
  `clusters/pi-k3s/mealie/postgresql.yaml` almost verbatim (rename mealie→synapse, pin to
  worker-2).
- **PVCs (local-path, `prune: disabled`):** `matrix-postgresql-data` (5Gi),
  `synapse-data` (5Gi — signing key + media_store).
- **ConfigMaps:** `synapse-config` (non-secret `homeserver.yaml` base + `log.config`),
  `element-config` (`config.json`).

## 4. Approach · [A]
Mirror the **`mealie`** stack (app + dedicated Postgres + ESO + ingress) for everything EXCEPT
Synapse's own config, which has no in-repo precedent and is authored verbatim in §6. Synapse
reads a **base `homeserver.yaml`** (ConfigMap, non-secret) that `include`s a **secrets fragment**
mounted from the ESO Secret — chosen because Synapse has **no `*_path` secret directives**
(verified against the config manual) and we refuse to inline secrets. Rejected: hand-rolling
`_path` secrets (unsupported); a Synapse Helm chart (adds a chart dependency; repo convention is
raw manifests per n8n — HelmRelease is reserved for genuinely complex charts like immich).

## 5. Scope · [S]
### In scope
- `clusters/pi-k3s/matrix/`: `namespace.yaml`, `external-secret.yaml`, `pvc.yaml`,
  `postgresql.yaml`, `synapse-config.yaml` (ConfigMap), `synapse.yaml` (Deployment+Service),
  `element.yaml` (ConfigMap+Deployment+Service), `ingress.yaml`, `kustomization.yaml`.
- Register a Flux Kustomization `matrix` in `flux-system/infrastructure.yaml`.
- `verify.sh` (this dir) — the static gate.
### Out of scope (orchestrator / human / later — NOT qwen's job)
- Minting the 1Password `matrix` item + secrets (**laptop-Claude, `op`**).
- `flux reconcile`, deploy, Synapse user/room bootstrap (**laptop-Claude / cluster-ops**).
- Backup CronJob (fast-follow; mirrors `backup-jobs/postgres-backup-cronjob.yaml`).
- The `agent-bus` CLI + qwen listener (**Phase 1 / 2, separate specs**).
- DNS edit — the wildcard `*.lab → 192.168.1.55` already resolves both hosts; only add
  documentation entries if trivial. **Do NOT touch `chat.lab` (it is Beelink Open WebUI).**

## 6. Prior decisions / facts the implementer must know · [S]
- **Hostnames:** Synapse = `matrix.lab.mtgibbs.dev`; Element = `element.lab.mtgibbs.dev`.
  `chat.lab` is ALREADY USED (Beelink). `server_name: matrix.lab.mtgibbs.dev` is **immutable
  after first start** — never change it.
- **Placement:** every workload gets `nodeSelector: { kubernetes.io/hostname: pi5-worker-2 }`.
- **Resource caps (hard):** synapse `requests 512Mi/250m`, `limits 1Gi/1000m`;
  postgres `256Mi/512Mi` (as mealie); element `16Mi/64Mi`.
- **ESO pattern:** copy `clusters/pi-k3s/mealie/external-secret.yaml` shape — `secretStoreRef
  { name: onepassword, kind: ClusterSecretStore }`, `template.engineVersion: v2`,
  `data[].remoteRef.key`. 1Password item key is `matrix/<field>`.
- **Ingress pattern:** copy `clusters/pi-k3s/mealie/ingress.yaml` — annotations
  `cert-manager.io/cluster-issuer: letsencrypt-prod`, `ssl-redirect: "true"`,
  `proxy-body-size: "0"` (media uploads), `ingressClassName: nginx`, tls secret
  `<app>-tls`. Synapse backend port **8008**; Element port **80**.
- **Flux registration:** add a `Kustomization` to `flux-system/infrastructure.yaml` exactly like
  the `mealie` block (`path: ./clusters/pi-k3s/matrix`, `dependsOn: external-secrets-config,
  ingress, cert-manager-config`, `sourceRef flux-system`, interval/prune as neighbors).
- **Images (pin exact tags — OQ2 to confirm latest stable; Renovate manages after):**
  `matrixdotorg/synapse:v1.156.0`, `vectorim/element-web:v1.12.23`, `postgres:16-alpine`
  (confirmed latest stable 2026-07-16: Synapse release v1.156.0, Element v1.12.23 — OQ2 closed).
- **Synapse config — AUTHORED HERE (novel; do not improvise).**
  `synapse-config` ConfigMap `homeserver.yaml` (base, non-secret):
  ```yaml
  server_name: "matrix.lab.mtgibbs.dev"
  public_baseurl: "https://matrix.lab.mtgibbs.dev/"
  pid_file: /data/homeserver.pid
  signing_key_path: /data/homeserver.signing.key
  media_store_path: /data/media_store
  report_stats: false
  enable_registration: false
  enable_registration_without_verification: false
  federation_domain_whitelist: []          # outbound federation OFF
  trusted_key_servers: []
  suppress_key_server_warning: true
  log_config: "/synapse/config/log.config"
  listeners:
    - port: 8008                            # client only — no 8448 => inbound federation OFF
      tls: false
      type: http
      x_forwarded: true
      bind_addresses: ['0.0.0.0']
      resources:
        - names: [client]
          compress: false
  database:
    name: psycopg2
    args: { user: synapse, database: synapse, host: matrix-postgresql, cp_min: 5, cp_max: 10 }
  # secrets (db password, registration_shared_secret, macaroon_secret_key, form_secret)
  # are supplied by a SECOND config file from the ESO secret — see synapse.yaml command.
  ```
  ESO `matrix-secret` renders `homeserver-secrets.yaml`:
  ```yaml
  database: { args: { password: "{{ .dbpassword }}" } }
  registration_shared_secret: "{{ .regsecret }}"
  macaroon_secret_key: "{{ .macaroon }}"
  form_secret: "{{ .formsecret }}"
  ```
  Synapse **merges multiple `--config-path` files** (later files override) — the Deployment
  runs both. Deployment shape:
  ```yaml
  initContainers:               # generate the signing key onto the PVC if missing (idempotent)
    - name: generate-keys
      image: matrixdotorg/synapse:v1.156.0
      command: ["python","-m","synapse.app.homeserver"]
      args: ["--config-path","/synapse/config/homeserver.yaml",
             "--config-path","/synapse/secrets/homeserver-secrets.yaml","--generate-keys"]
      volumeMounts: [config→/synapse/config (ro), secrets→/synapse/secrets (ro), data→/data]
  containers:
    - name: synapse
      image: matrixdotorg/synapse:v1.156.0
      command: ["python","-m","synapse.app.homeserver"]
      args: ["--config-path","/synapse/config/homeserver.yaml",
             "--config-path","/synapse/secrets/homeserver-secrets.yaml"]
      ports: [8008]
      readinessProbe/livenessProbe: httpGet /health :8008
      # volumes: config (ConfigMap), secrets (Secret matrix-secret, items homeserver-secrets.yaml
      #          + log.config from ConfigMap), data (PVC synapse-data)
  ```
- **Element `config.json`** (ConfigMap, mounted `/app/config.json`), served by the
  `vectorim/element-web` image (nginx built in):
  ```json
  { "default_server_config": { "m.homeserver": {
      "base_url": "https://matrix.lab.mtgibbs.dev", "server_name": "matrix.lab.mtgibbs.dev" } },
    "disable_guests": true, "disable_3pid_login": true }
  ```

## 7. Norms · [N]
- Filenames/labels/service names mirror `mealie`'s (`app: <name>`, ClusterIP services named
  after their workload). Postgres = `matrix-postgresql` (Synapse expects host `matrix-postgresql`).
- One YAML doc per concern; `kustomization.yaml` lists files in dependency order (ns → eso →
  pvc → configmaps → postgres → synapse → element → ingress), same style as mealie.
- PVCs carry `kustomize.toolkit.fluxcd.io/prune: disabled` (data protection — as mealie/immich).

## 8. Safeguards · [S]
- **No inline secrets.** Every credential flows through `matrix-secret` (ESO). `git grep` for a
  literal password/secret in `clusters/pi-k3s/matrix/` must find none (verify.sh asserts).
- **Private by construction:** no federation listener (8448), `federation_domain_whitelist: []`,
  `enable_registration: false`. verify.sh asserts all three.
- **Resource bounds:** every container has memory limits (verify.sh asserts) — worker-2 is
  already 152% limit-overcommitted; an unbounded pod is unacceptable.
- **`server_name` immutable:** must be exactly `matrix.lab.mtgibbs.dev` (verify.sh asserts).
- **Data locality:** PVCs `storageClassName: local-path` + node-pinned (no cross-node move).

## 9. Task breakdown · [O]
1. `namespace.yaml` + `kustomization.yaml` skeleton.
2. `external-secret.yaml` (mirror mealie; add the `homeserver-secrets.yaml` template).
3. `pvc.yaml` (two PVCs).
4. `postgresql.yaml` (mirror mealie, rename to synapse/matrix-postgresql).
5. `synapse-config.yaml` ConfigMap (paste §6 `homeserver.yaml` + a standard `log.config`).
6. `synapse.yaml` Deployment+Service (paste §6 init/main container shape).
7. `element.yaml` ConfigMap+Deployment+Service (§6 config.json).
8. `ingress.yaml` (two hosts: matrix.lab→synapse:8008, element.lab→element:80).
9. Register Flux Kustomization `matrix` in `infrastructure.yaml`.
10. Update `ARCHITECTURE.md` Decision #13 workload list (Matrix stack → pi5-worker-2).
(1–8 are the qwen loop; 9–10 too. Each task = one file, verify.sh after each.)

## 10. Acceptance criteria (EARS) · [O]
- The `matrix` kustomization shall include all nine manifests in dependency order.
- The system shall define `server_name` as exactly `matrix.lab.mtgibbs.dev`.
- If any manifest contains a literal secret value, then verify.sh shall fail.
- While federation is disabled, the config shall set `federation_domain_whitelist: []` and expose
  no `8448` listener.
- The system shall set `enable_registration: false`.
- Every container shall declare a memory limit and `nodeSelector` pi5-worker-2.
- The ingress shall route `matrix.lab`→synapse:8008 and `element.lab`→element:80, and shall NOT
  reference `chat.lab`.
- Where Flux registers the app, `infrastructure.yaml` shall contain a `matrix` Kustomization with
  `path: ./clusters/pi-k3s/matrix` and `dependsOn` external-secrets-config, ingress,
  cert-manager-config.

## 11. Verification — see `verify.sh` (static gate; runs every loop iteration)
LIVE tier (post-merge, laptop-Claude — NOT loop-gated): mint the `matrix` 1Password item; Flux
applies clean; pods Running within limits on worker-2; `/_matrix/client/versions` 200; Element
login; `register_new_matrix_user` (shared secret) creates `@matt` + the 4 agent bots; delete the
synapse pod → history survives (PVC).

## 11b. Loop execution
`scripts/ralph-qwen.sh specs/agent-bus` on a worktree/branch; decompose §9 into `tasks.txt`;
fresh context per task; gated on `verify.sh`; stop-for-human on the Synapse tasks if the config
merge is fighting it (that's the novel bit — escalate rather than thrash).

## 12. Open questions
- **OQ1 (live-verify, mine):** confirm Synapse honors two merged `--config-path` files with the
  default image entrypoint (vs. needing `SYNAPSE_CONFIG_PATH`). If not, fall back to the ESO
  rendering the FULL `homeserver.yaml` as one secret file. Resolve at first deploy, not in loop.
- **OQ2 (mine, pre-loop):** confirm latest STABLE image tags for synapse + element-web; pin them.
- **OQ3:** two rooms `#agents` + `#tasks` created at bootstrap (Phase 0 live step) — confirm names.
