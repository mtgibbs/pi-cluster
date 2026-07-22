# Spec: health probes for the media stack

## 1. Why · [R]

Fourteen Deployments run with no `livenessProbe` and no `readinessProbe`. Two consequences,
both live today:

- **A hung app stays hung.** Kubernetes only restarts a container that *exits*. An app whose
  process is alive but wedged — a common servarr failure — is never restarted, and the only
  cure is somebody noticing and deleting the pod by hand.
- **Ingress routes to pods that are not ready.** Without a readiness gate, a pod joins its
  Service the moment the container starts, so every rollout serves errors for the seconds or
  minutes the app spends booting.

Resource limits are already at 100% coverage in this repo. Probes are the remaining gap.

## 2. Outcomes (Definition of Done) · [R]

- Every in-scope Deployment has both a `readinessProbe` and a `livenessProbe`.
- Probes use an endpoint that was **verified against the running service**, or a TCP check —
  never a guessed HTTP path.
- No healthy pod is restarted by the change: liveness is deliberately slow to fire.
- The two non-HTTP workloads are left alone.

## 3. Entities · [E]

| Entity | Meaning |
|---|---|
| in-scope Deployment | one of the 14 manifests in §6's table |
| httpGet tier | apps with a verified unauthenticated health endpoint |
| tcpSocket tier | apps with no such endpoint — the probe proves the port is listening |
| excluded | workloads with no `containerPort` at all |

## 4. Approach · [A]

**Two tiers, and the tier is decided by evidence, not by app family.**

Where a real health endpoint was verified against the live service, use `httpGet`. Where it was
not, use `tcpSocket` — which proves the process is accepting connections and nothing more, but
is *honest about proving only that*.

The alternative — guessing a plausible path per app — is how you get a **false-green probe**:
one that returns 200 forever while the app is broken. That is not hypothetical here; see the
bazarr note in §6.

## 5. Scope · [S]

### In scope
The 14 files in §6's table, under `clusters/pi-k3s/`. Each edit adds two probe blocks to an
existing container spec. Nothing else changes.

### Out of scope
- `uptime-kuma/autokuma-deployment.yaml` and `private-exit-node/deployment.yaml` — **neither
  declares a `containerPort`**. AutoKuma is a controller and the exit node is Tailscale; there
  is no port to probe and inventing one would be worse than leaving them bare.
- Any change to images, resources, volumes, replicas, or Service/Ingress objects.
- Deployments that already have probes.

## 6. Prior decisions / facts the implementer must know · [S]

**Every endpoint below was verified against the running service on 2026-07-22 via
`curl_ingress` from inside the cluster. Do not substitute a different path.**

### httpGet tier — verified 200, real endpoint

| file | containerPort | path |
|---|---|---|
| `media/sonarr.yaml` | 8989 | `/ping` |
| `media/radarr.yaml` | 7878 | `/ping` |
| `media/lidarr.yaml` | 8686 | `/ping` |
| `media/readarr.yaml` | 8787 | `/ping` |
| `media/prowlarr.yaml` | 9696 | `/ping` |
| `media/sabnzbd.yaml` | 8080 | `/api?mode=version` |

The five servarr apps return **200 with a 20-byte body**, and an unknown path returns 302 — so
`/ping` is a real route, not a catch-all. sabnzbd's version endpoint needs no API key.

### tcpSocket tier — no verified endpoint

| file | containerPort |
|---|---|
| `media/bazarr.yaml` | 6767 |
| `media/calibre-web.yaml` | 8083 |
| `media/qbittorrent.yaml` | 8080 |
| `media/lazylibrarian.yaml` | 5299 |
| `media/jellyseerr.yaml` | 5055 |
| `media/flaresolverr.yaml` | 8191 |
| `pihole/pihole-exporter.yaml` | 9617 |
| `pihole/pihole-secondary-exporter.yaml` | 9617 |

**Why bazarr is here rather than in the httpGet tier, and why it matters:** `bazarr/ping`
returns 200 — and so does `bazarr/definitely-not-a-real-path-xyz`, with a byte-identical
1897-byte body. It is the single-page-app catch-all. An `httpGet` probe there would report
healthy for as long as the web server serves static files, **including while the backend is
dead** — a probe that cannot distinguish working from broken is worse than no probe, because it
converts an outage into a green light.

`jellyseerr/api/v1/status` was the obvious guess and returns **404**. That is exactly why this
table is verified rather than inferred.

## 7. Norms · [N]

- Raw manifests, matching each file's existing indentation and key order. No Helm, no kustomize
  patches.
- Insert the probes inside the existing container entry, adjacent to `ports:`. Change nothing
  else in the file — not image tags, not resources, not comments.
- `port:` in each probe is the **numeric containerPort from the table**, never a name.

## 8. Safeguards · [S]

1. **Liveness must not kill a healthy pod.** `initialDelaySeconds: 120` and
   `failureThreshold: 6` with `periodSeconds: 30` — roughly three minutes of sustained failure
   before a restart. These apps are slow starters on a Pi; an aggressive liveness probe would
   turn a slow boot into a crashloop, which is strictly worse than the status quo.
2. **Never invent an HTTP path.** Only the six paths in §6 may appear. Anything else must be
   `tcpSocket`.
3. **The two excluded files must remain untouched.**
4. **No field outside `readinessProbe`/`livenessProbe` may change** in any file.

## 9. Task breakdown · [O]

See `tasks.txt` — four tasks, grouped so each is a small, uniform batch.

## 10. Acceptance criteria (EARS) · [O]

1. **Where** a file is listed in §6, it **shall** contain both a `readinessProbe` and a
   `livenessProbe` in its container spec.
2. **Where** a file is in the httpGet tier, its probes **shall** use `httpGet` with exactly the
   path and port from the table.
3. **Where** a file is in the tcpSocket tier, its probes **shall** use `tcpSocket` with the port
   from the table.
4. **Where** any probe declares a port, that port **shall** equal a `containerPort` declared in
   the same container.
5. **While** a `livenessProbe` exists, `initialDelaySeconds` **shall** be at least 60 and
   `failureThreshold` at least 3.
6. **Where** a file is excluded by §5, it **shall not** gain any probe.
7. **Where** any in-scope file is edited, no key outside the two probe blocks **shall** differ
   from `main`.
8. **Where** an HTTP path appears in any probe, it **shall** be one of the six in §6.

## 11. Verification (the harness)

`./specs/media-health-probes/verify.sh` — STATIC, offline, presence-gated. It parses each
manifest as YAML and asserts the criteria structurally; it does **not** reach the cluster.

LIVE tier — human, after merge and reconcile:
- `kubectl get pods -n media` shows all pods `READY 1/1` and **restart counts unchanged**.
- Watch for ten minutes: no new restarts. A liveness misconfiguration shows up as a
  slow crashloop, not an immediate one.

## 12. Open questions

- bazarr, calibre-web, qbittorrent and jellyseerr would all benefit from a real HTTP health
  endpoint if one exists behind auth or on an admin path. Worth a follow-up pass, but a
  `tcpSocket` probe today is strictly better than none and strictly honest.
