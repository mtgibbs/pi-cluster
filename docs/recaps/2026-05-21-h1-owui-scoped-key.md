# Session Recap — 2026-05-21 (H1: Adults' OWUI Master Key → Scoped Virtual Key)

This is the fifth arc of 2026-05-21 and the last item in Horizon 1. The other arcs are `docs/recaps/2026-05-21-backup-recovery-and-mirror-hardening.md`, `docs/recaps/2026-05-21-observability-phase1.md`, `docs/recaps/2026-05-21-q8-coder-agent-comparison.md`, and `docs/recaps/2026-05-21-beelink-backup-coverage.md`. This arc was ~30 minutes; it was flagged as a Phase 1 follow-up since the initial AI-stack bring-up.

---

## What & Why

The adults' Open WebUI (`chat.lab.mtgibbs.dev`) was authenticating to LiteLLM with the **master key** — the admin credential that can mint keys, add/remove models, and inspect all usage. That key was correct as a bootstrap shortcut but wrong as a steady-state configuration. Any compromise of the OWUI container or its env would have yielded full LiteLLM admin.

The fix was straightforward: mint a **DB-backed virtual key** scoped to all models with no admin privileges, store it in 1Password, and swap OWUI's env to use it. This was the last remaining H1 item per `docs/roadmap-2026-q2.md`.

---

## What Was Done

### 1. Key minted via LiteLLM `/key/generate`

A POST to `/key/generate` (authenticated with the master key) produced a DB-backed virtual key with:

- Alias: `openwebui-adults`
- Models: all (`*`)
- Admin: false

The key was stored immediately at `op://pi-cluster/openwebui/litellm-key`. The value was never printed to a terminal or logged.

### 2. beelink-ansible commit `63a956f` — `playbooks/50-ai-stack.yml`

Two changes in the playbook:

- Added `OWUI_LITELLM_KEY` to the `.env` template (sourced from `op://pi-cluster/openwebui/litellm-key` at deploy time via `op read`).
- Changed the `open-webui` service's `OPENAI_API_KEYS` first element from `${LITELLM_MASTER_KEY}` to `${OWUI_LITELLM_KEY}`.

The secrets-header comment block at the top of the playbook was also updated to document the key's purpose and the separation of concerns: master key is litellm-internal + ops sidecar only; `owui_litellm_key` is for the adults' surface.

### 3. Deployed via `50-ai-stack.yml` play

Result: `ok=34 changed=3 failed=0`. The `open-webui` container was recreated; Ollama, LiteLLM, and the other services were undisturbed. OWUI came back healthy on the virtual key.

### 4. pi-cluster commit `82d3784`

Marked H1 complete in `docs/roadmap-2026-q2.md` and resolved the three follow-up notes in `docs/beelink-ai-stack.md` that had tracked this item since the initial bring-up.

---

## Verification

Prove-the-server-path checks before declaring done:

| Check | Endpoint | Result |
|---|---|---|
| Model access | `GET /v1/models` with the virtual key | 200 OK — full model list returned |
| Admin denied | `POST /key/generate` with the virtual key | 401 Unauthorized — as expected |
| OWUI health | Container inspect + log tail | Healthy; virtual key in running env |

The 200/401 pair is the definitive proof: the key reaches LiteLLM and can invoke models, but cannot perform any admin operation.

---

## Notable Lesson

The first deploy attempt aborted before writing `.env`. The `QNAP_BACKUP_SSH_KEY` assertion in the playbook — added during the backup-coverage arc earlier today — fired because the `op` CLI session had lapsed between the two back-to-back plays, causing `$(op read ...)` to return an empty string.

The fail-loud guard stopped the play before rendering `.env`, preventing a half-apply where the file would have had an empty key value. Re-running with a warm `op` session succeeded cleanly.

**Pattern confirmed:** assert all secrets are non-empty before writing any file. An empty secret written silently is harder to debug than a play that refuses to continue. See `docs/recaps/2026-05-21-beelink-backup-coverage.md` where this pattern was established.

---

## Commits

| Hash | Repo | Subject |
|---|---|---|
| `63a956f` | beelink-ansible | feat(security): adults' OWUI uses scoped LiteLLM virtual key, not master |
| `82d3784` | pi-cluster | docs: mark H1 complete — adults' OWUI on scoped virtual key |

---

## Outcome

Every UI surface now runs on its own scoped virtual key:

| Surface | Key alias | Admin |
|---|---|---|
| Adults' chat (`chat.lab.mtgibbs.dev`) | `openwebui-adults` | No |
| Kids' Dewey (`dewey.lab.mtgibbs.dev`) | `dewey` | No |
| Ops pipeline (sidecar bearer) | `ops-pipelines` | No |
| LiteLLM-internal + admin ops | master key | Yes |

**Horizon 1 is complete.** H2 (observability) and H3b (ops pipeline) are already done. Next session is H3a Dewey polish.
