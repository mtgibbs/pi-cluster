# Spec: Decommission CARL + Pi-side Ollama

- **Status:** ✅ Done — executed 2026-05-24 (Claude-driven; destructive + cross-cutting teardown, kept off the qwen loop). CARL + Pi-Ollama pruned via GitOps (commit `12ba63d`); pods confirmed gone, Beelink Ollama untouched.
- **Owner:** Matt
- **Constitution:** `/CLAUDE.md` Core Mandates (GitOps via Flux, secrets via 1Password/ESO, agent work PR-gated). **This is a destructive teardown — see §4.**
- **Touches:** `clusters/pi-k3s/carl/`, `clusters/pi-k3s/ollama/`, `flux-system/infrastructure.yaml`, `homepage/configmap.yaml`, DNS, AutoKuma.

---

## 1. Why

Two services are pure overhead on the Pi cluster and no longer earn their keep:

- **CARL** (`carl.lab.mtgibbs.dev`) — Canvas assignment reminders. A "museum exhibit"; superseded by the planned Canvas-aware Dewey/Signal flows. Not in active use.
- **Pi-side Ollama** (`clusters/pi-k3s/ollama/`) — local inference on the Pi, **fully superseded by the Beelink** (LiteLLM/`ai.lab`). It only still exists because **CARL depends on it** as its LLM backend (`CARL/ollama_url`, `CARL/ollama_model`). With CARL gone, it has zero consumers.

Removing both frees Pi RAM/CPU/storage and resolves the long-deferred "clean up `clusters/pi-k3s/ollama/`" item (its blocker — the CARL dependency — is removed by this same change).

## 2. Outcomes (definition of done)

1. CARL and Pi-Ollama are fully removed from the cluster — no pods, namespaces, ingresses, DNS, image-automation, or homepage entries remain.
2. Nothing else breaks (verified: **only CARL** consumes Pi-Ollama; the **Beelink Ollama is untouched**).
3. The repo has no dangling references to either service.

## 3. Scope

### In scope
- Delete `clusters/pi-k3s/carl/` and `clusters/pi-k3s/ollama/` (whole dirs).
- Remove the `carl` and `ollama` Flux Kustomizations from `flux-system/infrastructure.yaml` (lines ~386, ~406).
- Remove the **CARL** entry from `homepage/configmap.yaml` (Web group).
- Remove DNS records for `carl.lab.*` and any `ollama.lab.*` (Pi-hole custom DNS).
- Remove any AutoKuma monitor + image-automation (ImageRepository/Policy) for CARL.
- Update docs/memory that describe these as live (roadmap, CLAUDE.md service index if listed, `MEMORY.md`).

### Out of scope
- **The Beelink Ollama stack — DO NOT TOUCH.** This decommission is the *Pi-side* `clusters/pi-k3s/ollama/` only.
- Retiring 1Password items (`CARL/*`, any Pi-ollama secret) — optional cleanup, can be a follow-up; leaving them is harmless.

## 4. Constraints (destructive teardown — read carefully)

- **GitOps teardown:** removal is by deleting the YAML + the Flux Kustomization entries; Flux **prunes** the live resources. **Confirm `prune: true`** on these Kustomizations (OQ1) — if not enabled, the spec MUST include an explicit namespace-delete step, or the pods will orphan.
- **Destructive-data check (the real risk per the constitution):** the Pi-Ollama **PVC holds downloaded models — re-pullable, no unique data, safe to delete.** CARL is **stateless** (config via env/ESO, no PVC). Net: no irreplaceable data is lost. Confirm this in the plan phase (OQ2) before deleting any PVC.
- **PR-gated:** the teardown lands as a reviewed PR; a human confirms the diff (especially that only the *Pi* ollama is removed) before merge. No direct-to-cluster deletes.
- **Order matters:** remove CARL (the consumer) and Pi-Ollama together in one change so CARL never points at a dead backend mid-reconcile.

## 5. Prior decisions / facts

- **Dependency confirmed:** `clusters/pi-k3s/carl/external-secret.yaml` injects `OLLAMA_URL` + `OLLAMA_MODEL` (`op://.../CARL/ollama_url`, `.../ollama_model`) → CARL's brain is the Pi-Ollama. Removing CARL removes Ollama's only consumer.
- **Beelink Ollama is the survivor** — all real inference moved there (H0/H0.5, 2026-05-20). The Pi-Ollama is legacy.
- CARL footprint: `clusters/pi-k3s/carl/{deployment,service,ingress,namespace,kustomization,external-secret,image-automation}.yaml`; Flux kustomization `carl`; homepage Web-group entry; DNS `carl.lab.mtgibbs.dev`.
- Pi-Ollama footprint: `clusters/pi-k3s/ollama/{deployment,service,namespace,kustomization,external-secret,pvc}.yaml`; Flux kustomization `ollama`.
- Cross-refs to clean: `homepage/configmap.yaml` (CARL), `flux-system/infrastructure.yaml` (both Kustomizations).

## 6. Task breakdown

- **T1** — Remove the `carl` and `ollama` Flux Kustomizations from `flux-system/infrastructure.yaml` (and any `dependsOn` that reference them).
- **T2** — `git rm -r clusters/pi-k3s/carl/ clusters/pi-k3s/ollama/`.
- **T3** — Remove the CARL entry from `homepage/configmap.yaml`; remove `carl.lab` / `ollama.lab` DNS records; remove the CARL AutoKuma monitor (if any).
- **T4** — Reconcile, verify teardown (§8), and update docs/memory (roadmap "deferred ollama cleanup" → done; drop CARL from any "live services" list).

## 7. Acceptance criteria (EARS)

1. **Event-driven** — When Flux reconciles after merge, the `carl` and `ollama` namespaces shall no longer exist (no pods, services, ingresses).
2. **Ubiquitous** — The homepage shall not list CARL.
3. **Event-driven** — When `carl.lab.mtgibbs.dev` (and `ollama.lab.*` if it existed) is resolved, it shall not return a cluster record.
4. **State-driven** — While the teardown is applied, the **Beelink Ollama / `ai.lab` inference stack shall remain fully operational** (untouched).
5. **Ubiquitous** — The repo shall contain no remaining references to `clusters/pi-k3s/carl` or `clusters/pi-k3s/ollama` (grep-clean).
6. **Unwanted behavior** — If `prune: true` is not set on the removed Kustomizations, then the change shall include an explicit namespace deletion so no resources orphan.

## 8. Verification (the harness)

- `get_cluster_health` / `get_flux_status`: no `carl` or `ollama` (Pi) pods/namespaces; no Kustomization errors.
- Homepage renders without CARL; `diagnose_dns` shows `carl.lab` no longer resolving to the cluster.
- `grep -rni 'carl\|pi-k3s/ollama' clusters/` returns nothing (except this spec).
- Confirm `ai.lab.mtgibbs.dev/health/liveliness` still 200 (Beelink untouched).

## 9. Open questions (resolve in the Plan phase)

- **OQ1** — Is `prune: true` set on the `carl` and `ollama` Flux Kustomizations? (Determines whether removal auto-deletes or needs explicit namespace deletion — drives criterion #6.)
- **OQ2** — Confirm the Pi-Ollama PVC holds only re-pullable models (no unique data) and CARL is truly stateless, before any delete.
- **OQ3** — Where are the `carl.lab` (and any `ollama.lab`) DNS records — `pihole-custom-dns.yaml`? Is there a CARL AutoKuma monitor to remove?
- **OQ4** — Retire the `CARL/*` and Pi-ollama 1Password items, or leave them? (Harmless to leave; tidy to remove.)
