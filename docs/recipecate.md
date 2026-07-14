# Recipecate — Recipe Homestead Build Plan

**Status:** PLANNED (research completed 2026-07-12) · **Owner:** Matt · **Orchestrator:** Claude
**Goal:** A self-hosted, forever-durable home for the family's recipes — replacing Paprika 3 —
with the killer feature preserved: paste any recipe URL *or Instagram reel* and the recipe is
captured, structured, and protected on the homestead.

> This doc is the durable source of truth for the initiative. A fresh Claude session should read
> this top-to-bottom before doing any work. Research provenance: deep-research run 2026-07-12
> (104 agents, 25 claims adversarially verified, 24 confirmed / 1 refuted).

---

## 0. The Decision — Adopt Mealie, Don't Rebuild Recipecate From Scratch

The original prototype (`mtgibbs/recipecate-api` + `mtgibbs/recipecate-ui`) was going to be the
base. Research says the "adopt Mealie + Instagram-import sidecar" hybrid **already exists off the
shelf**, and the only part that would justify a from-scratch build (Instagram capture) is the part
that's already covered twice over:

- **URL import is a solved problem.** The `recipe-scrapers` Python library (Mealie's engine)
  parses schema.org/Recipe markup (JSON-LD, Microdata, RDFa) + OpenGraph across **649 supported
  sites** (v15.11.0, actively maintained). A custom build would just re-wrap this library — and
  would have to solve fetching/anti-bot itself, which the library explicitly refuses to do.
- **Instagram publishes NO schema.org/Recipe data** (Mealie maintainer, issue #5857: "cannot be
  scraped"). Instagram capture is LLM-extraction-only, and Mealie now has that natively: an
  OpenAI-compatible AI-provider integration that (a) downloads reels via yt-dlp and transcribes
  them, and (b) falls back to sending page text (incl. the caption) to the LLM for non-audio
  providers. Upstream also merged native social-media video import (PR #6764).
- **A maintained sidecar exists for the share-sheet UX**: `social-to-mealie` (v1.7.1, 2026-07-11)
  — yt-dlp + Whisper + tool/vision LLM → pushes into Mealie via API. Ships an iOS Shortcut and PWA
  share-target. Tested on Instagram, TikTok, Facebook, YouTube Shorts, Pinterest.
- **Paprika migration is first-party** in Mealie (recipes + categories + images + auto-tagging).
- **iOS story exists**: full-featured PWA (free) + native `MealieSwift` App Store client
  ($9.99 lifetime w/ Family Sharing) as an optional nicety.

**What survives from the prototype:** the *design DNA*, not the code. Recipecate's core idea —
normalized ingredients with amounts/units, meal plans as recipe collections, and the shopping list
**derived** by aggregating a plan's ingredients — is exactly Mealie's model (ingredient parser +
meal planner + shopping-list-from-recipes). The name lives on as the initiative. If we ever want a
custom family frontend, Mealie's OpenAPI-documented REST API is the seam — the Angular UI could be
revived against it as a thin client, the same "frontends are disposable" stance as the ROM plan.

**Known caveat (be honest about it):** the landscape leg (Mealie vs Tandoor vs KitchenOwl vs Grocy
head-to-head) did NOT survive verification — the one comparative source was refuted 0-3. The
recommendation rests on Mealie's *positively verified* strengths (import pipeline, Paprika
migration, AI integration, iOS client, API), not on a verified head-to-head. Tandoor is the
fallback if Mealie disappoints hands-on (it also imports `.paprikarecipes` with images).

---

## 1. Architecture

```
        CAPTURE                          HOMESTEAD BASE (K3s)                       CONSUME (family iPhones etc.)
┌──────────────────────────┐    ┌───────────────────────────────────┐    ┌───────────────────────────────┐
│ Recipe site URL ─────────┼──► │ Mealie (recipe-scrapers path)     │    │ PWA (recipes.lab.mtgibbs.dev) │
│ Instagram reel/post ─────┼──► │ Mealie AI import / social-to-     │ ─► │ MealieSwift (optional, paid)  │
│  (iOS share sheet)       │    │  mealie sidecar                   │    │ Family Board (recipe_url)     │
│ Paprika 3 export ────────┼──► │  └─ LLM: Beelink LiteLLM/Ollama   │    └───────────────────────────────┘
│  (.paprikarecipes)       │    │ Postgres (recipe DB)              │
└──────────────────────────┘    └───────────────────────────────────┘
                                        │ nightly
                                        ▼
                     QNAP NFS backups (restic pattern) + schema.org JSON-LD export
```

- **The durable artifact is the recipe data**, exported to open formats (schema.org/Recipe JSON-LD;
  optionally RecipeMD plain-text) — same philosophy as ROMs on the QNAP: the app is disposable.
- **All LLM work runs on the Beelink** (LiteLLM virtual key per client, per existing convention).
  Nothing leaves the homestead for extraction.

## 2. Phase 1 — Deploy Mealie via GitOps

Standard service pattern (`clusters/pi-k3s/mealie/`):

- [x] `mealie` Deployment — `ghcr.io/mealie-recipes/mealie` (arm64 published; 64-bit required —
      fine on Pi 5). Pin the version — **v3.20.1 is current as of 2026-07-12** (repo verified
      active: commits daily, AGPL-3.0, yt-dlp dep bumped 2026-07-09; note `mealie.io` is a stale
      placeholder page — the live fronts are the GitHub repo + docs.mealie.io). Any 3.x image
      satisfies the sidecar's "1.9.0+" note; confirm PR #6764 (native social video import) is in
      the pinned release's changelog at build time. **Deployed 2026-07-13 (PR #49).**
- [x] **Postgres** companion (plain PG, matching the n8n decision) + 1Password item `mealie`
      (db creds, `MEALIE_API_TOKEN` later) via ExternalSecret.
      **Gotcha (PR #50):** Mealie's discrete `POSTGRES_*` path builds its DSN with
      `urllib.parse.quote()` at the default `safe='/'`, so any password containing `/` (i.e. any
      base64-generated one) crashloops the pod with pydantic "invalid port number". Fix: the
      ExternalSecret templates the full `POSTGRES_URL_OVERRIDE` DSN — that code path re-quotes
      the password with `safe=''` and tolerates any password.
- [x] Volumes: app data (`/app/data` — images live here) on local-path PVC; backups to NFS.
- [x] Ingress `recipes.lab.mtgibbs.dev` + cert (existing cert-tls pattern); LAN + Tailscale only.
- [x] Homepage tile + AutoKuma monitor (same as RomM bring-up).
- [ ] Household/user accounts for Matt + Julia (multi-user from day one). Default admin is
      `changeme@example.com` / `MyPassword` — change on first login. Onboarding wizard's AI
      provider + email prompts can be skipped (see Phase 3 — providers are DB records now, and
      SMTP/OIDC are optional env vars).
- [ ] Smoke test: URL-import 3–5 recipes from major sites (schema.org path, no AI needed).

## 3. Phase 2 — Paprika 3 Migration

- [ ] **Human gate (Matt):** export `.paprikarecipes` from Paprika 3 and drop it somewhere
      reachable. Archive the raw export on the QNAP permanently (it's a ZIP of gzipped per-recipe
      JSON — the ur-copy).
- [ ] Import via Mealie's first-party Paprika migration (Data Management → Migrations).
      **Verified to carry:** recipes, categories, images (+ auto-tag by source).
      **NOT migrated (verified absent):** shopping lists, meal plans, ratings, nutrition.
- [ ] Validate counts + spot-check ~10 recipes (images, ingredient parsing quality).
- [ ] Meal plans/shopping lists are ephemeral by nature — rebuild by hand. If the Paprika export
      turns out to contain meal-plan/rating data worth keeping, a small one-off converter against
      the gzipped JSON is a qwen/oc-sized task (open question from research).
- [ ] **Keep Paprika running in parallel** until Phase 4 proves capture parity. No burn-the-boats.

## 4. Phase 3 — AI Import Bring-Up (the Instagram feature)

**How v3 actually wires AI (verified in v3.20.1 source, 2026-07-13):** providers are **per-group
database records**, not env vars — the old `OPENAI_BASE_URL`-style config is gone. Each provider
is `{name, base_url, api_key, model, timeout, request_headers, request_params}`, managed in the
UI (Group Settings → AI Providers) or via REST: CRUD at
`/api/groups/ai-providers/providers`, role assignment at `/api/groups/ai-providers/settings`.
Group settings bind providers to three **role slots**:

| Slot | Used by | Beelink status |
| :--- | :--- | :--- |
| `default` (text) | "Import with AI" URL/text paste; structuring transcripts | ✅ ready — `qwen3-30b-instruct` (or `qwen3.6:35b-a3b`) via LiteLLM `https://ai.lab.mtgibbs.dev/v1` |
| `image` (vision) | Photo-of-recipe import | ❌ gap — no vision model on Beelink yet (qwen-VL-class pull needed) |
| `audio` | Instagram/social video import (the yt-dlp strategy is **only enabled when an audio provider is set**) | ❌ gap — Mealie calls `/v1/audio/transcriptions` (Whisper API) first, then falls back to chat-completion `input_audio`; Beelink serves neither today (needs faster-whisper/speaches behind LiteLLM) |

Plain URL import (recipe-scrapers / schema.org) uses **no AI** and already works.

- [x] **Keep IaC despite DB-resident config:** `ai-provider-bootstrap.yaml` — in-cluster Job
      (python:3.12-alpine, stdlib only) that create-or-updates the `beelink-litellm` provider by
      name and binds the `default` slot, preserving audio/image bindings. Secrets via
      `mealie-ai-secret` ExternalSecret (`mealie/litellm-key` + shared
      `mcp-homelab/mealie-api-token`). Re-run on change: bump the Job name suffix (`-v1` → `-v2`).
- [ ] Mint a LiteLLM virtual key for `mealie` (one identity per client, per convention) →
      1Password `mealie` item, field `litellm-key`. **Human gate — do this BEFORE the bootstrap
      Job lands or its ExternalSecret stalls.**
- [ ] **Text slot first** (works today): bootstrap Job registers LiteLLM
      (`https://ai.lab.mtgibbs.dev/v1`, `qwen3-30b-instruct`) as `default` provider →
      unlocks AI text/URL import and the caption-fallback test.
- [ ] Beelink: pull a vision model (qwen2.5-VL-class) → register as `image` provider.
- [ ] Beelink: stand up Whisper (faster-whisper/speaches) behind LiteLLM → register as `audio`
      provider (hard requirement for the reel-transcription path).
- [ ] Test ladder, cheapest first:
      1. Instagram URL → Mealie import with **caption-fallback** path (page text → LLM; needs
         `default` slot only).
      2. Instagram reel → **video download + transcription** path (yt-dlp + `audio` slot).
      3. A JSON-LD site through the AI path to confirm no regression on normal sites.
- [ ] **Known fragility (verified):** yt-dlp Instagram downloads fail for some users without
      cookies ("empty media response…use --cookies"; suspected EU cookie-prompt trigger). Test
      from our US residential IP first — if we hit the wall, caption-fallback still works, and a
      cookie-refresh strategy is a separate decision (ToS-sensitive; don't automate casually).

**Other onboarding seams (env-var based, both optional, both skippable for now):**
`SMTP_*` (only needed for invite emails / password resets — accounts are hand-created, skip)
and `OIDC_*` (full OIDC support exists; revisit when Authelia lands in Beelink Phase 1).

## 5. Phase 4 — Family Capture UX

- [ ] Decide: **Mealie-native import UI vs `social-to-mealie` sidecar.** Native may be enough now
      that PR #6764 is merged; the sidecar earns its keep with the **iOS Shortcut + PWA
      share-target** (share a reel from the Instagram app → recipe appears in Mealie). If native
      testing in Phase 3 feels clunky from a phone, deploy the sidecar
      (`ghcr.io/gerardpollorebozado/social-to-mealie`, needs `MEALIE_URL`/`MEALIE_API_KEY`).
- [ ] iOS for the family: install the PWA on Julia's + Matt's phones (free, full-featured).
      Optional: MealieSwift native client — $9.99 lifetime with Apple Family Sharing (note: last
      updated ~June 2025, mild maintenance risk; PWA remains the guaranteed path).
- [ ] Family Board integration: menu `recipe_url` entries point at Mealie recipe pages instead of
      Paprika share links (BACKEND-ASKS.md already models this as just-a-URL — zero board changes).

## 6. Phase 5 — Durability & Paprika Retirement

- [ ] Nightly backup CronJob (restic pattern → QNAP `cluster-backup`): Mealie's own backup zip +
      `pg_dump`, same shape as the RomM `mariadb-backup` job.
- [ ] Periodic **open-format export** — schema.org/Recipe JSON-LD (the canonical interchange
      target, per research; ~10K-100K domains serve it) and/or RecipeMD (plain-text Markdown,
      spec v2.4.0, readable with zero software in 2050). Mealie's API can drive this; a small
      CronJob exporting to the NFS backup share makes recipes app-independent forever.
- [ ] After 4–6 weeks of parity: stop entering new recipes in Paprika; keep the app installed
      read-only until the family stops reaching for it.

## 7. Open Questions (carried from research)

1. Does yt-dlp Instagram download work from our IP without cookies? (Phase 3 test decides.)
2. Which Mealie release ships PR #6764, and does it make the sidecar redundant? (Phase 1/4.)
3. Exact `.paprikarecipes` contents — is there meal-plan/rating data worth a one-off converter?
4. Hands-on verdict: does Mealie's ingredient parsing + shopping-list UX actually satisfy the
   family? (Tandoor is the researched fallback; both import `.paprikarecipes`.)

## 8. Prototype Repos

`recipecate-api` (hapi/knex, 2019) and `recipecate-ui` (Angular 17 + Material + transloco, 2024)
stay archived as design reference. The structured-ingredient → derived-shopping-list model they
pioneered is satisfied by Mealie; the Angular UI is revivable against Mealie's OpenAPI surface if
a custom family frontend is ever wanted.
