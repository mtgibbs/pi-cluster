# Spec: Immich Resume (un-park)

- **Status:** Planned (no open questions)
- **Owner:** Matt
- **Constitution:** `specs/constitution.md` (+ `/CLAUDE.md` Core Mandates)
- **Touches:** `clusters/pi-k3s/immich/helmrelease.yaml`, `clusters/pi-k3s/immich/postgresql.yaml`

---

## 1. Why · [R — Requirements]

Immich was **intentionally parked** on 2026-06-17 (commit `53e5b34`) to stop wasting Pi 5
resources while unused — it is **not broken**. We want it back. All data was retained on PVCs
(`immich-library` photo library + `immich-postgresql-data`). This change is the documented
resume — the exact reversal of the park commit — **not** a repair and **not** an upgrade.

## 2. Outcomes (Definition of Done) · [R — Requirements]

1. Git declares Immich ON again: server + valkey enabled, postgres `replicas: 1`.
2. The change is the **minimal** reversal of `53e5b34` — nothing else in the immich dir moves.
3. Machine learning stays **disabled** (a Pi 5 can't run it — non-negotiable).
4. No stale `PARKED 2026-06-17` comments survive (a live service must not carry a parked lie).
5. `verify.sh` (static gate) exits 0. LIVE cluster health is verified post-merge (§11 LIVE tier).

## 3. Entities · [E — Entities]

Config keys only (no data model). Literal keys + target values:

- `helmrelease.yaml` → `spec.values.server.enabled: true` (currently `false`)
- `helmrelease.yaml` → `spec.values.valkey.enabled: true` (currently `false`)
- `helmrelease.yaml` → `spec.values.machine-learning.enabled: false` (UNCHANGED — must stay `false`)
- `postgresql.yaml`  → Deployment `immich-postgresql` `spec.replicas: 1` (currently `0`)

## 4. Approach · [A — Approach]

Reverse the three flips made by the park commit `53e5b34`, and delete the `PARKED 2026-06-17`
comment blocks it introduced. No version change — resume on the pinned chart `0.10.3` / server
image `v2.4.1` exactly as parked (Decision A, lowest-risk). No new pattern: this is literally
`git show 53e5b34` reversed by hand. Considered and rejected — bundling an Immich upgrade or
NFS mount-option tuning into this change (kept out; see §5).

## 5. Scope · [S — Structure: boundary]

### In scope
- `clusters/pi-k3s/immich/helmrelease.yaml` — `server.enabled` + `valkey.enabled` → `true`; drop their PARKED comments.
- `clusters/pi-k3s/immich/postgresql.yaml` — `replicas: 0 → 1`; drop its PARKED comment.

### Out of scope (do NOT touch)
- `machine-learning.enabled` — leave `false`.
- NFS mount options on `nfs-pv.yaml` (resilience tuning is a separate follow-up spec).
- Immich / chart version bump (resume on the pinned version; an upgrade is a later spec).
- `external-secret.yaml`, `library-pvc.yaml`, `nfs-pv.yaml`, `servicemonitor.yaml`,
  `prometheusrule.yaml`, `namespace.yaml`, `kustomization.yaml` — unchanged.
- Any other namespace / service.

## 6. Prior decisions / facts the implementer must know · [S — Structure: system fit & deps]

- The park commit is `53e5b34` ("chore(immich): park Immich…"). Its diff IS the work, reversed.
- Resume recipe (from that commit's own message): `server.enabled true` + `valkey.enabled true`
  + postgres `replicas 1`.
- PVCs are retained (`kustomize.toolkit.fluxcd.io/prune: disabled` on `immich-library-nfs` and
  `immich-postgresql-data`) — photo library + DB survive the park. **No data restore needed.**
- Secrets come via ExternalSecret `immich-secret` (1Password `immich/db-password`,
  `immich/secret-key`) → `secretKeyRef`. **Do NOT inline any secret.**
- ML is disabled on purpose: high CPU on Pi 5, ML jobs retry-loop. **Never enable it here.**
- Resuming the server re-creates the `immich.lab.mtgibbs.dev` ingress + `immich-tls`
  (cert-manager / Let's Encrypt) automatically — no manual ingress work.
- Exact reversals (literal — the comment lines above each value are what gets deleted):

```yaml
# helmrelease.yaml — server block:
    server:
      enabled: true        # was: 3 PARKED comment lines + `enabled: false`

# helmrelease.yaml — valkey block:
    valkey:
      enabled: true        # was: 1 PARKED comment line + `enabled: false`

# postgresql.yaml — Deployment spec:
spec:
  replicas: 1              # was: 2 PARKED comment lines + `replicas: 0`
```

## 7. Norms · [N — Norms]

- Match the file's existing YAML style (2-space indent, no trailing whitespace).
- When you flip a value, **REMOVE** the `PARKED 2026-06-17` comment block above it — don't leave
  a comment that contradicts the live state. Don't add new explanatory comments.
- Keep the diff surgical: exactly 3 value flips + the comment deletions. No reflow, no reorder.

## 8. Safeguards · [S — Safeguards]

- `machine-learning.enabled` MUST remain `false` (verify asserts it).
- Secrets stay via `secretKeyRef` / ExternalSecret — never inline a password or token.
- Touch only the two in-scope files. No deletions of PVCs or other resources.
- Static gate only — this loop NEVER touches the cluster (Flux applies on merge).

## 9. Task breakdown · [O — Operations]

This change is atomic (the gate is all-or-nothing), so it is ONE task:

- **T1:** Reverse park commit `53e5b34` — enable server + valkey, postgres replicas 1, drop PARKED comments.

## 10. Acceptance criteria (EARS) · [O — Operations made testable]

- The system shall set `server.enabled: true` in `helmrelease.yaml`.
- The system shall set `valkey.enabled: true` in `helmrelease.yaml`.
- The system shall keep `machine-learning.enabled: false` in `helmrelease.yaml`.
- The system shall set the `immich-postgresql` Deployment `replicas: 1` in `postgresql.yaml`.
- If a `PARKED 2026-06-17` comment exists in either file, then the system shall remove it.
- The system shall keep secrets referenced via `secretKeyRef` (no inline secret).
- Both manifests shall remain valid YAML.

## 11. Verification — SHIP A `verify.sh`

See `specs/immich-resume/verify.sh`. **STATIC tier** (gates each loop iteration): YAML validity +
the block-scoped flag / replica / comment / secret assertions above.

**LIVE tier** (post-merge, Claude/MCP + Flux — NOT gated here):
1. `immich-postgresql` Ready (`pg_isready`), then `immich-valkey` Ready.
2. `immich-server` Ready; `/data` NFS mount present; reads `/cluster/photos`.
3. `immich-tls` re-issued; `https://immich.lab.mtgibbs.dev` 200 + login works.
4. Metrics scrape resumes (`:8081`/`:8082`); immich PrometheusRule not firing.
5. Photo library + DB intact (counts match pre-park).

## 11b. Loop execution (handing to qwen)

Run from a throwaway branch in a git worktree:

```bash
scripts/ralph-qwen.sh specs/immich-resume
```

One task, fresh context, watchdog-timed, gated on `verify.sh`. Output is a reviewed diff; Flux
applies on merge — never direct-to-cluster.

## 12. Open questions

None. Decision A (resume on pinned version) locked; NFS-resilience tuning and any Immich upgrade
are explicitly deferred to separate specs (§5).
