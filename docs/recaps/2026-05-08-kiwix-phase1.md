# Session Recap — 2026-05-07/08

Kiwix Phase 1: offline reference platform deployed to Pi K3s cluster. A family homework/reference resource — Wikipedia, Gutenberg, Wiktionary, and friends — running locally, no internet required for lookups. Phase 2 (MCP server + LLM inference + Open WebUI chat surface) is planned but explicitly not started here.

---

## What Was Completed

- New `kiwix` namespace, GitOps-managed via Flux
- kiwix-serve pod running `ghcr.io/kiwix/kiwix-tools:latest` on arm64
- QNAP NFS share `/cluster/kiwix/zim` mounted as 250Gi PV at `/data`
- Ingress at `https://kiwix.lab.mtgibbs.dev` with Let's Encrypt cert
- Homepage tile added under Media section
- AutoKuma HTTP monitor configured
- Seed Job (`kiwix-seed-job.yaml`) written and applied manually; kept outside `kustomization.yaml` so Flux ignores it
- 7 ZIMs downloaded and `library.xml` rebuilt; pod confirmed healthy

---

## ZIM Library (Final Inventory)

| Title | Size |
|---|---|
| Project Gutenberg Library | 206 GB |
| Wikipedia full English | 48 GB |
| Wikisource | 11 GB |
| Wiktionary English | 8.2 GB |
| Wikibooks | 3.3 GB |
| Wikipedia Simple English | 922 MB |
| Wikiquote | 309 MB |
| **Total** | **~278 GB** |

---

## Commits

| Hash | Subject |
|---|---|
| `5a13828` | feat(kiwix): phase 1 — offline reference platform (Wikipedia + Wiktionary) |
| `629a59a` | fix(kiwix): use short docopt flags for kiwix-serve |
| `e333025` | feat(kiwix): expand library with full Wikipedia + Wikimedia + Gutenberg |
| `3109298` | fix(kiwix): revert PV capacity bump, document the constraint |
| `2950bb2` | fix(kiwix): stall-aware curl flags in seed Job |

---

## Key Decisions

**Cluster-native, not QNAP-native**
Early in the session there was drift toward running `kiwix-manage` directly on the QNAP. Corrected: QNAP is storage only. Everything compute runs on the Pi cluster, same as the Jellyfin pattern. The seed Job mounts the NFS share RW via a Kubernetes Job and writes ZIMs there; kiwix-serve mounts the same share RO.

**`library.xml` manifest over positional ZIM args**
kiwix-serve can serve ZIM files directly as positional args, but that requires re-deploying whenever the library changes. The `library.xml` approach — built once via `kiwix-manage add` — decouples library contents from the Deployment spec. The extra `kiwix-manage` step in the seed Job is the cost. Chosen from day one; user explicitly declined the "start with positional args as a smoke test" offer to avoid a rollback.

**Node affinity — exclude pi3-worker-2, soft-avoid master**
Hard exclude `pi3-worker-2`: the node has 1 GiB RAM and kiwix's 1Gi memory limit alone could OOM it under query bursts. Soft prefer the pi5-worker-* nodes over `pi-k3s` master to keep the DNS-critical node uncontended. No hard pin to a single worker — user intentionally balances workloads across `pi5-worker-1` and `pi5-worker-2` based on what else is running.

**`runAsUser: 1001` in the seed Job**
The seed Job runs as uid 1001 (`cluster-backup`), matching QNAP NFS ownership on `/share/cluster/kiwix`. No root-squash workarounds needed; writes go through cleanly. kiwix-serve reads the same volume as the default container user.

**One-time seed Job kept outside kustomization**
`kiwix-seed-job.yaml` lives in `clusters/pi-k3s/kiwix/` but is NOT listed in `kustomization.yaml`. Flux will never reconcile it. Apply manually with `kubectl apply -f` when seeding new ZIMs, then delete the completed Job. Keeps the GitOps-managed state clean while preserving the manifest for future use.

---

## Gotchas

**kiwix-serve docopt is strict and cascade-fails**
The binary uses a docopt parser that rejects the entire args list if any flag doesn't match exactly — it doesn't report just the bad flag; it reports every argument as "Unexpected argument." The original manifest used `--blockExternal` (camelCase). The correct flag is `--blockexternal` (lowercase, one word) per the binary's help output. Rather than risk another case mismatch, switched to short-flag form: `-p 8080 -b -l /data/library.xml`. When debugging kiwix-serve startup failures, check the full args list against `kiwix-serve --help` output, not just the flag you think is wrong.

**curl with no stall detection hangs forever**
The first Gutenberg seed attempt stalled silently at 4.6 GB and hung for 60+ minutes. `curl -fL --retry 3` with no timeout flags leaves a dead-but-not-closed TCP connection open indefinitely. Fixed by adding: `--max-time 14400 --speed-time 120 --speed-limit 524288 --connect-timeout 30 --retry 10 --retry-delay 60 --retry-all-errors`. Any seed Job downloading large files needs stall detection; do not rely on `--retry` alone.

**`-C -` (resume) saved hours on the Gutenberg download**
Gutenberg's full 206 GB took 3 pod attempts under the same Job (backoffLimit 2 before correction). With `-C -` (resume from partial), each retry continued from where the previous pod stopped. Without it, three failed attempts at ~200 GB each would have wasted roughly 600 GB of re-download. The `.part` file persists on the NFS volume between pod restarts, so resume works as long as the volume stays mounted.

**PVC capacity bump rejected by k8s**
Attempted to bump PV/PVC from 250Gi to 500Gi. k8s refused: "only dynamically provisioned PVC can be resized and the storageclass must support resize." The `nfs-kiwix` StorageClass is manually provisioned and does not support resize. NFS doesn't enforce capacity at the filesystem level anyway — the 250Gi declaration is purely metadata. Reverted; added a comment in `nfs-pv.yaml` explaining the constraint so no one wastes time trying again.

**`kubectl rollout restart` doesn't survive Flux reconcile**
After the library rebuild, `kubectl rollout restart` was used to pick up the new `library.xml`. The restart annotation (`kubectl.kubernetes.io/restartedAt`) isn't in git, so on the next 10-minute Flux reconcile the annotation is stripped and the Deployment rolls back to the original ReplicaSet hash. Functional impact: zero, because both old and new pods load `library.xml` from the same NFS share. Operational note: if a definitively-new pod is needed that survives reconcile, edit the Deployment in git (e.g., bump an annotation or env var) instead of `rollout restart`.

**ZIM size estimates were significantly off**
Original plan estimates:
- Wiktionary: ~1 GB. Actual: 8.2 GB. The `_all_nopic` variant indexes definitions for words from every language (in English), not just English words.
- Project Gutenberg: ~70 GB. Actual: 206 GB.
- Khan Academy: ~30 GB. Actual: 168 GB (all-videos bundle, 2023-03 vintage only, no topic subsets). Khan Academy was skipped — the format (video-heavy) and age made it the wrong fit for homework reference use.

Plan against actual kiwix.library.zimit.frisch.com sizes before designing Jobs and PV declarations.

**Front-page search filters library titles, not content**
kiwix-serve's landing page search box filters book titles and descriptions — it is not a full-text search. Entering "banana" returns nothing if no ZIM has "banana" in its title. Full-text search happens after clicking into a specific ZIM. The `--searchLimit N` flag enables cross-ZIM full-text search but was not enabled (Phase 2 will handle this better via MCP). Worth knowing before assuming search is broken.

---

## Files

- `clusters/pi-k3s/kiwix/` — all manifests
- `clusters/pi-k3s/kiwix/kustomization.yaml` — does NOT include `kiwix-seed-job.yaml`
- `clusters/pi-k3s/kiwix/kiwix-seed-job.yaml` — seed Job, apply manually
- `clusters/pi-k3s/kiwix/deployment.yaml` — node affinity, resource limits, short-flag args

---

## Phase 2 (Not Started)

The planned next phase is an AI layer on top of this library:

- MCP server that exposes kiwix ZIM content as tools
- LLM inference via Beelink (Ollama + LiteLLM, see `docs/beelink-ai-stack.md`)
- Open WebUI as a kid-friendly chat surface pointed at the kiwix MCP + LiteLLM

Phase 1 was deliberately scoped to "Kiwix working standalone" before any AI layer. Family hasn't been briefed yet — intentional, wanted infrastructure stable first.

---

## Next Steps

- [ ] Brief family on kiwix.lab.mtgibbs.dev
- [ ] Beelink Phase 2: Tailscale + ROCm + LiteLLM/Ollama Compose stack (see `docs/beelink-ai-stack.md`)
- [ ] Kiwix Phase 2: MCP server + Open WebUI chat surface (dependent on Beelink being live)
- [ ] Consider adding `--searchLimit` to kiwix-serve once Phase 2 UX is designed
