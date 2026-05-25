# Recap — n8n Email Ingestion Pipeline (2026-05-25)

Built a general inbound-email ingestion pipeline end-to-end (school = use case #1).
Full reference + runbook: **[`docs/n8n-email-pipeline.md`](../n8n-email-pipeline.md)**.

## What shipped
- **Migrated** the existing single-pod SQLite n8n → **queue mode** (main + worker + webhook
  + Valkey/AOF + Postgres) for durable execution. Commits `71bc1ab` (Postgres/secrets),
  `a11a678` (queue mode), `c2f362e` (drop S3 binary mode — Enterprise-only, was crash-looping).
- **Cloudflare edge** (manual/out-of-band): R2 bucket + 48h lifecycle + S3 token; Email
  Routing enabled; `intake@mtgibbs.dev` → Email Worker; tunnel `n8n-hook.mtgibbs.dev`
  path-restricted to the inbound-mail path; n8n UI pulled off the public tunnel (LAN-only).
- **Email Worker** `mtgibbs-mail-worker` (`edge/email-worker/`, wrangler): parse → offload
  attachments to R2 → POST refs-only JSON → n8n. Commit `05ccccb`.
- **Verified end-to-end** with real emails (attachments land in R2 intact; jobs run on workers).
- **Corpus** (~10 real specimens) characterized: HTML-body newsletters dominate; text PDFs;
  a `.docx`; Peachjar image flyers (deferred vision branch).
- **Schema** designed/confirmed (typed records, deadline-centric).
- **Extraction live in n8n** (commit `c86b049`): Webhook → Build Request → LiteLLM
  (`qwen3-30b-instruct` on Beelink) → Parse Records. Execution #11 produced 7 clean records.
- **1Password reorg:** runtime secrets in `n8n`, ops tokens in new `n8n-automation`.

## Why a runbook
Big realization: the in-cluster half is GitOps, but the **Cloudflare edge, secrets, Worker,
and n8n workflow/credentials are NOT Flux-managed** — manual to reconstruct. `docs/n8n-email-pipeline.md`
captures the human steps, the two "publish" restart dances (cloudflared + webhook tier don't
hot-reload), the Flux cascade, and the gotchas.

## Remaining
Storage (`intake_items` table) → PDF/docx branch → Peachjar vision → site-pointer detect →
dashboard. Storage is the next high-value step.
