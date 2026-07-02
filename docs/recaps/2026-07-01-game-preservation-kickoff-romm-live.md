# Recap — Game Preservation / ROM Homestead kickoff, RomM deployed and live (2026-07-01)

New initiative, first session. This extends the household's digital-homesteading posture
(self-hosted, vendor-independent, resilient-to-the-cluster-going-away) to the family's physically-owned
game collection: dump/rip the carts and discs already sitting in boxes, catalog them somewhere durable,
and play them on hardware already in the house. The living plan is `docs/game-preservation.md` — written
to survive a context reset, a fresh session should read it top-to-bottom before touching this initiative
again.

Two tracks ran in parallel this session. Track A (build RomM) shipped, crash-looped once, got fixed, and
was verified live end-to-end. Track B (dumper hardware) produced a priced buy list ready to act on. A
third track (Archival Sources — legitimate third-party acquisition) got scoped but not started.

---

## 1. The legal line — locked before any manifest was written

The user asked directly about r/ROMs-style megathreads early in the session, and the answer needed to be
unambiguous before any infrastructure got built:

- **In scope:** copies made from media the family physically owns (own cart dumps, own disc rips), plus
  a curated **Archival Sources** track — Internet Archive selective-by-title ingest (Console Living Room,
  homebrew/PD collections), freely-distributable homebrew/public-domain titles, and a GOG buy list for
  out-of-print-but-still-purchasable titles.
- **Out of scope, hard line:** any warez/Usenet/piracy-index pipeline. The r/ROMs megathread and full-set
  mirrors (e.g. Myrient) were explicitly asked about and explicitly rejected — indiscriminate copies of
  mostly-in-print commercial games is piracy, not archival, regardless of what hardware is owned. This is
  not a "download it all" project.
- **Provenance requirement:** every copy — dumped or archivally sourced — gets hash-verified against the
  **No-Intro** (carts) and **Redump** (discs) DAT databases via RomVault/clrmamepro. This was the user's
  core ask ("I can't verify each file" from a bulk mirror), and DAT verification is the direct answer:
  per-file, known-good-or-flagged provenance, which a bulk mirror can never give you.

This reasoning lives in `docs/game-preservation.md` §0 and §3B and should not need re-litigating in future
sessions — it's the boundary, not an open decision.

---

## 2. Metadata plan

- **Hasheous** — keyless, gives day-one scraping with zero provider signup. This is why RomM could be
  deployed and verified working before Task 3 (provider registration) was even started.
- **ScreenScraper** — free account, no Twitch OAuth — the default enrichment provider once registered.
- **IGDB** — richest metadata source but requires a Twitch dev app (Twitch/Amazon-owned); optional,
  deferred, not blocking anything.

---

## 3. `docs/game-preservation.md` — the build plan

Authored and iterated across the session as facts got verified against upstream docs. Two doc-only
commits landed directly on main early in the session to establish the plan before any code was written:

- `b5ef3cf` — initial build plan: architecture (ingest → RomM catalog → play surfaces), the legal
  boundary, RomM component list, the 14-task execution table with owner tags (Human / Claude / qwen /
  cluster-ops).
- `a988621` — added the Archival Sources track (§3B above) plus the DAT-verification requirement.

The plan's architecture in short:

```
   INGEST (own-made + archival)          HOMESTEAD BASE (K3s)              PLAY (existing hardware)
  ┌─────────────────────────────┐   ┌──────────────────────────┐   ┌───────────────────────────┐
  │ Cart dumper → ROM + saves   │   │ RomM                     │   │ Steam Decks (EmuDeck)     │
  │ Disc ripper → ISO/RVZ       │──▶│  catalog + box-art scrape │──▶│ Laptops (RomM browser)    │
  │ Archival DL → IA/homebrew/PD│   │  browser play (EmulatorJS)│   │ TV box, optional (Batocera)│
  └─────────────────────────────┘   └──────────────────────────┘   └───────────────────────────┘
                 │                        ▲  QNAP NFS library (storage.lab.mtgibbs.dev)  ▲
                 └────────────────────────┴──────────── restic/backup ────────────────────┘
```

The ROM/ISO files on the QNAP are the durable artifact; every frontend (RomM, EmuDeck, Batocera) is
disposable and reads the same underlying files.

---

## 4. `docs/dumper-hardware.md` — Track B buy list (Task 2, done)

Researched and priced same day. Recommended minimal kit:

| Item | Price | Covers |
| :--- | :--- | :--- |
| **OSCR HW5 Rev5, assembled** (eBay/Tindie) | ~$230 | NES/SNES/N64/Genesis/SMS/GB/GBC/GBA — all native slots, no adapters |
| **LG WH16NS40** optical drive, flashed to 3.02/OmniDrive firmware, + USB 3.0 SATA enclosure | ~$120–175 | PS1/PS2, plus GC/Wii/Xbox raw-read as a bonus of the flash |
| Existing 3DS + GodMode9 (DS cards); existing Wii + CleanRip (GC/Wii) | $0 | DS, GC/Wii fallback |
| **Total** | **~$350–405** | |

Nice-to-haves noted: GBxCart RW ($33, superior save handling via FlashGBX) and GB Operator ($49.99,
ships 7/15, polished UX) — neither required, both cheap adds later. **Retrode 2 was explicitly rejected**
— redundant with the OSCR, worse price-per-system, and can't dump SA-1 SNES games (Super Mario RPG, Kirby
Super Star) that the OSCR handles natively.

---

## 5. RomM deployed — PR #41

`clusters/pi-k3s/romm/` scaffolded: `namespace.yaml`, `deployment.yaml`, `mariadb.yaml`, `pvc.yaml`,
`nfs-pv.yaml`, `service.yaml`, `ingress.yaml`, `external-secret.yaml`, `kustomization.yaml`, wired into
`clusters/pi-k3s/flux-system/infrastructure.yaml`. Stack:

- `rommapp/romm:4.9.2` (arm64) — serves on 8080, `HASHEOUS_API_ENABLED=true` for keyless day-one scraping.
- **MariaDB 11.4** companion Deployment (required dependency).
- **Valkey is embedded in the RomM image** (`/redis-data` volume only) — no separate cache workload
  needed. This resolves an open question from the original plan, which assumed a standalone cache pod.
- Library volumes (`/romm/library`, `/romm/assets`, `/romm/resources`) → QNAP NFS `/cluster/games`
  (subPath mounts); `/romm/config` and MariaDB data → local-path PVCs.
- Secrets from a new 1Password `romm` item (db-password, db-root-password, auth-secret-key) via
  ExternalSecret.
- nginx ingress + `letsencrypt-prod` TLS, same pattern as every other internal service.

**Process note (per the project's coding-agent-ops pattern):** manifest boilerplate was drafted by
qwen3-coder (local coding agent on the Beelink box, headless text-generation mode). Headless qwen is not
trusted as a tool-user — only as a text generator whose output gets extracted, reviewed, and integrated by
Claude before it lands. That review-and-integrate step is what happened here before the PR opened.

PR #41 merged as `4ee2faa`, shipping the manifests, `docs/dumper-hardware.md`, and the plan-doc updates
with verified RomM 4.9.2 facts in one squash commit.

---

## 6. The bug — `ROMM_PORT` env-var collision crashed nginx

First rollout crash-looped. Root cause: naming the Kubernetes Service `romm` triggered the legacy
service-links feature, which injects `ROMM_PORT=tcp://<ip>:8080` into the pod's environment. RomM's own
container entrypoint reads any `*_PORT` variable matching its app name as an override for its nginx
listen-port, and misread the Kubernetes-supplied URL as a literal listen directive:

```
invalid host in "tcp://<ip>:8080" of the "listen" directive
```

nginx failed to start, pod crash-looped. Fix: `enableServiceLinks: false` on the pod spec, which stops
kubelet from injecting the legacy `<SVCNAME>_*` env vars at all. Committed directly to main as `4e5a9f4`
— correctly treated as an ops one-liner (a running-cluster hotfix), not code that needed to go back
through the qwen/PR pipeline.

---

## 7. Verified end-to-end after the fix

Not just an internal pod healthcheck — the full real path was proven:

- Pod `Ready 1/1`; MariaDB companion healthy.
- Flux Kustomization `romm` — `Applied` at the latest commit.
- `letsencrypt-prod` certificate — `Ready`.
- `curl_ingress` (MCP tool, exercises the actual ingress path — DNS wildcard → nginx ingress → TLS → pod,
  not a shortcut) against `https://romm.lab.mtgibbs.dev/api/heartbeat` → **200** in ~143ms.

`docs/game-preservation.md` was updated in `5fa1076` to mark Task 1 **LIVE 2026-07-01** and record the
`enableServiceLinks` fix and the resolved Valkey-is-embedded question.

---

## 8. Post-deploy cluster health check — a scare that wasn't one

Due diligence after the new deploy, and a direct application of the project's Diagnostic Discipline
mandate (check every layer; a green light on one tool doesn't prove the layers behind it are healthy —
and the inverse holds too, a scary first snapshot doesn't prove an outage until you check the layer
behind it).

- `get_cluster_health`: 103 total pods, **zero** problem pods, all 4 nodes `Ready`.
- `get_flux_status` (first poll): a large fan-out of Kustomizations reporting `dependency not ready` —
  looked like nearly every service in the `flux-system` namespace was degraded. Alarming at a glance.
- Investigated directly with `kubectl describe kustomization` rather than trusting the first snapshot:
  this was a transient artifact of triggering a full `flux-system` source-level reconcile, which requeues
  the entire dependency graph and cascades through it one 10-minute-interval tick at a time — not a real
  outage.
- Spot-checked `external-secrets-config` and `cert-manager-config` directly: both `Healthy`/`Succeeded`
  at the current git commit, seconds old, actively converging.
- A second `get_flux_status` poll a minute later showed the ready-wave visibly propagating through the
  dependency chain.
- All 46 ExternalSecrets across the cluster reported `synced`, zero failures.

**Conclusion:** nothing broken. RomM is the only new addition to the cluster this session and it's fully
green.

---

## 9. State at close

| Component | State | Notes |
| :--- | :--- | :--- |
| `docs/game-preservation.md` | **BUILDING** (living plan) | Track A live; Track B done; Track C scoped, not started |
| RomM (`romm.lab.mtgibbs.dev`) | **LIVE, verified** | 4.9.2, MariaDB 11.4, embedded Valkey, Hasheous scraping active |
| `enableServiceLinks: false` fix | Committed (`4e5a9f4`) | Prevents future `<SVCNAME>_PORT` collisions on any service literally named after its own app |
| `docs/dumper-hardware.md` | **Done** | Buy list ready; ordering is a human step |
| Archival Sources track | Scoped, not started | IA ingest, homebrew/PD pack, GOG buy list all unscheduled |
| Cluster overall | **Healthy** | 103 pods / 0 problem pods / 4 nodes Ready / 46 ExternalSecrets synced |

---

## 10. Open items

- [ ] **Task 3 — register ScreenScraper account.** Optional, not blocking; Hasheous already scrapes.
- [ ] **Task 4 — NAS folder-structure spec + organizer script.** `library/roms/<platform-slug>/`
  convention; qwen drafts the rename/organize helper.
- [ ] **Task 5 — backup wiring, with a gotcha.** The cluster's backup CronJobs are per-node
  rsync-over-SSH jobs, not restic — RomM's PVCs live on a specific Pi 5 worker, so a node-independent
  `mariadb-dump` CronJob needs to be added post-deploy (plus a decision on QNAP-side snapshot/2nd-copy
  for `/share/cluster/games`).
- [ ] **Task 6 — first real dump → RomM scan → browser-play smoke test.** Blocked on the dumper hardware
  actually arriving (Track B buy list above).
- [ ] **Homepage dashboard tile + AutoKuma uptime monitor for RomM.** Deliberately skipped this session
  to keep PR #41 reviewable; small follow-up.
- [ ] **Steam Deck / EmuDeck setup.** Human task, once library has real content.
- [ ] **Whole Archival Sources track.** Internet Archive ingest tooling, DAT-verification tooling
  (RomVault/clrmamepro wiring), and the GOG buy list are all scoped in `docs/game-preservation.md` §3B
  but none has started.

---

## Commits

| Hash | Subject |
| :--- | :--- |
| `b5ef3cf` | docs(game-preservation): plan ROM homestead (dump own carts+discs, RomM on K3s) |
| `a988621` | docs(game-preservation): add Archival Sources track + per-file verification |
| `4ee2faa` | feat(romm): RomM ROM library service (game-preservation Track A) (#41) |
| `4e5a9f4` | fix(romm): disable service links (ROMM_PORT env collision crashed nginx) |
| `5fa1076` | docs(game-preservation): mark RomM live, verified end-to-end |
