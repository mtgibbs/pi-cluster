# Game Preservation & ROM Homestead — Build Plan

**Status:** PLANNING (started 2026-07-01) · **Owner:** Matt · **Orchestrator:** Claude
**Goal:** Preserve the physical game collection (carts + discs) as durable digital copies on the
homestead, cataloged and playable on any device the family already owns — resilient to any single
system (or the whole cluster) failing.

> This doc is the durable source of truth for the initiative. It is written to survive a context
> reboot: a fresh Claude session should read this top-to-bottom before doing any work.

---

## 0. Legal Boundary (READ FIRST — non-negotiable)

The durable, defensible artifact is **a copy we make from media we physically own.**

- ✅ **Dump our own cartridges** (dumper hardware) → ROM files we made.
- ✅ **Rip our own discs** (PC drive / console homebrew) → ISO/RVZ we made.
- ✅ **Freely-distributable content**: homebrew, public-domain titles, and legally-free ROMs.
- ❌ **Do NOT** build or wire up any automated "download ROMs from the internet" pipeline, and do
  not point at ROM-distribution / warez sources. Owning the cart does **not** legalize downloading
  a stranger's copy — the legal footing is *who made the copy*.

Everything downstream of ingest (catalog, storage, backup, play) is 100% legitimate regardless and
is the bulk of the value. Build all of it freely.

---

## 1. Architecture — Two Halves

```
                 INGEST (make our own copies)                 HOMESTEAD BASE (catalog + serve)              PLAY (existing hardware)
  ┌───────────────────────────────────────────┐     ┌──────────────────────────────────┐     ┌──────────────────────────────┐
  │  Cart dumper  ──►  ROM + save files        │     │  RomM (K3s)                      │     │  Steam Decks  (EmuDeck)      │
  │  Disc ripper  ──►  ISO / RVZ files         │ ──► │   - catalog + box art (scrape)   │ ──► │  Laptops      (RomM browser) │
  │  Homebrew DL  ──►  freely-distributable    │     │   - browser play (EmulatorJS)    │     │  TV box (opt) (Batocera)     │
  └───────────────────────────────────────────┘     │   - save-file management         │     └──────────────────────────────┘
                        │                            └──────────────────────────────────┘                       ▲
                        └────────────► QNAP NFS library (storage.lab.mtgibbs.dev) ◄──── restic backup ──────────┘
```

The **ROM/ISO files on the QNAP are the durable artifact.** Every frontend is disposable and
interchangeable — dump once, play anywhere, forever.

---

## 2. The Homestead Base — `RomM` on K3s (build first)

RomM (https://github.com/rommapp/romm) is "Jellyfin for ROMs": catalog, metadata/box-art scraping,
built-in browser play (EmulatorJS), and save-file management. It deploys as a normal GitOps service.

**Components (verify exact deps against current RomM docs at build time — project moves fast):**
- `romm` app container (`rommapp/romm`).
- **MariaDB** database (required).
- **Valkey/Redis** cache (needed for scans/background tasks in recent versions — confirm).
- Metadata API credentials (see below).

**Integration with existing stack:**
- **Storage:** ROM library on QNAP NFS (`storage.lab.mtgibbs.dev`) — same pattern as media PVs.
  Folder layout follows RomM's per-platform convention: `library/roms/<platform-slug>/`.
- **Secrets:** metadata provider key(s) → 1Password `pi-cluster` vault → ExternalSecret.
  RomM supports several providers — **ScreenScraper** (free screenscraper.fr account, retro-focused,
  **no Twitch**) is the low-friction default; **SteamGridDB** (free API key) adds cover art;
  **MobyGames** (API key) is an option. **IGDB** is the richest metadata source but requires a Twitch
  dev app (IGDB is Twitch/Amazon-owned, so its API uses Twitch OAuth — ~5-min setup, no streaming
  involved). Confirm the exact current provider list against RomM docs at build. → **Human gate:**
  register the chosen provider account(s) and mint key(s) — ScreenScraper alone is enough to start.
- **Backups:** ROM + saves folder folds into the existing restic CronJob strategy — this is the
  "won't lose them" guarantee. Add the library path to backup scope.
- **Ingress + TLS:** internal ingress via cert-manager, same as other services.
- **Remote:** Tailscale if we ever want it off-LAN (optional).
- **GitOps:** new service under `clusters/pi-k3s/romm/`, scaffolded with the `add-service` skill.

**Follow-up:** once RomM is live, spin an ops skill (`.claude/skills/rom-ops/` or fold into
media-services) capturing folder-slug conventions, scan/rescan flow, and save-sync notes.

---

## 3. Ingest — Making Our Own Copies

We own all of it, across **NES/SNES/N64**, **GB/GBC/GBA/DS**, **Sega (Genesis/etc.)**, and
**discs (PS1/PS2/GC/Wii)**. There is no legit "download it all" button — dumping/ripping is genuine
hands-on time. Decision: **buy prebuilt/plug-and-play** hardware (no soldering).

**Cart dumpers (prebuilt options to price — Task 2):**

| System(s) | Recommended prebuilt path | Notes |
| :--- | :--- | :--- |
| NES / SNES / N64 / Genesis | **Open Source Cartridge Reader (OSCR), pre-assembled** | Best single-device coverage; also backs up cart saves. Sold pre-built by retro shops. |
| GB / GBC / GBA | **GBxCart RW / GBFlash (insideGadgets)** | Dead-simple USB; dumps ROM + battery saves. |
| DS game cards | **Homebrewed DS/3DS + GodMode9** (not a USB dumper) | Odd one out — different workflow; flag as its own mini-task. |

**Disc ripping (our own discs — more finicky, per-system tools):**

| System | Tool / path | Output |
| :--- | :--- | :--- |
| GameCube / Wii | **CleanRip** (Wii homebrew) or **Dolphin** + compatible PC drive | `.rvz` (compressed) / `.iso` |
| PS1 | PC optical drive + redump-style dumper | `.bin/.cue` |
| PS2 | PC optical drive + ImgBurn | `.iso` |

**Freely-distributable layer (bonus, fully legal):** homebrew + public-domain titles the kids can
enjoy immediately while the dumping backlog is worked through.

**Storage sizing:** carts are tiny (KB–MB); discs dominate (PS1 ~700MB, PS2 ~4GB, GC ~1.5GB,
Wii ~4.7GB each). Realistic family collection is tens–low-hundreds of GB. QNAP has ample room —
not a capacity concern.

---

## 4. Play Surfaces — Use What We Already Own

Play is nearly free given existing hardware:

- **Steam Decks → EmuDeck.** Best-in-class retro setup (RetroArch + standalone emulators +
  EmulationStation-DE). Point it at the NAS library / synced ROMs. → **Human gate:** enable Desktop
  mode / install EmuDeck on each Deck.
- **Laptops → RomM browser play** (EmulatorJS). Zero install, works on the LAN.
- **TV / couch (optional "more toys") → Batocera** on a cheap mini-PC. Survives a *full cluster
  outage* since it reads ROM files directly.

> RomM is the **catalog + browser + save hub**; the Decks/Batocera read the *same files* RomM
> manages off the NAS. Optionally explore the RomM sync plugin for the Deck later.

---

## 5. Execution Plan & Ownership

Legend — **H**=Human gate · **C**=Claude orchestrates/reviews · **Q**=qwen on Beelink (drafts code)
· **CO**=cluster-ops agent (deploy/verify/git).

| # | Task | Owner | Notes |
| :--- | :--- | :--- | :--- |
| 1 | Scaffold RomM GitOps service (Kustomization, app, MariaDB, cache, PVC, Svc, Ingress, ExternalSecret) | Q drafts → C reviews → CO deploys | Use `add-service` skill for conventions. Verify RomM's current dep list first. |
| 2 | Price prebuilt dumpers + disc-rip kit; produce a buy list | C research → **H** buys | OSCR pre-assembled + GBxCart RW; PC drive for discs. |
| 3 | Register metadata provider → creds in 1Password | **H** → C wires ExternalSecret | **ScreenScraper (free acct, no Twitch) = default.** SteamGridDB key for art. IGDB optional (Twitch dev app). |
| 4 | Define NAS library folder structure (RomM platform slugs) | C spec → Q writes organizer script | `library/roms/<slug>/`; include a rename/organize helper. |
| 5 | Add ROM library path to restic backup scope | C → CO | The "won't lose them" guarantee. |
| 6 | First dumps (a few carts) → verify RomM scan + browser play end-to-end | **H** dumps → C verifies | Prove the pipeline on a small batch before bulk. |
| 7 | EmuDeck on Steam Deck(s), pointed at library | **H** | Play surface #1. |
| 8 | (Optional) Batocera TV box | **H** buys → C guides | Full-outage-proof couch play. |
| 9 | Bulk dump/rip backlog (ongoing) | **H** | The long tail; no shortcut. |
| 10 | Write `rom-ops` skill once live | C/recap-architect | Fold conventions into repo knowledge. |

**qwen (Beelink) offload targets:** manifest boilerplate drafts (Task 1), the ROM-organizer /
No-Intro-style rename script (Task 4), and any glue scripts. Claude orchestrates and reviews;
cluster-ops deploys; humans handle purchases + physical dumping.

---

## 6. Open Decisions

- **RomM dependency set** — confirm MariaDB-only vs MariaDB+Valkey against current docs at build.
- **Auth** — RomM's built-in auth vs front with Authelia (Beelink Authelia is Phase-1 pending).
- **Deck ↔ library** — browser-play only, NFS-mount the share, or a sync tool? Decide at Task 7.
- **DS dumping** — worth the homebrew-3DS workflow now, or defer? (Task backlog.)
- **Skill home** — new `rom-ops` skill vs extend `media-services`.

---

## 7. Post-Reboot Kickoff (START HERE after restart)

Since we're running **Tasks 1 + 2 in parallel**:

1. **Track A (build):** kick off Task 1 — draft the RomM GitOps manifests (hand boilerplate to
   qwen), reviewing against the `add-service` skill + current RomM docs. Blocked only by Task 3
   (IGDB creds) for *scraping*, not for standing the service up.
2. **Track B (hardware):** run Task 2 — research current prebuilt dumper + disc-rip options and
   pricing, produce a buy list for Matt to order.
3. Flag Task 3 (metadata provider signup) to Matt — **ScreenScraper is a free account with zero
   Twitch friction** and is enough to start; IGDB (Twitch dev app) is an optional richer source later.
