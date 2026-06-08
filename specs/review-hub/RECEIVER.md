# review-hub — Reactive PR-Evaluator Receiver (deploy runbook)

The in-cluster webhook receiver that reviews PRs. A single **GitHub App**
(installed on all repos) POSTs `pull_request` webhooks via the **Cloudflare
Tunnel** to this service, which mints a per-repo App token, runs the applicable
evaluators, and posts a **Check Run** + comment. Reactive, multi-repo,
multi-evaluator. See `PLAN.md` for the judge; this is the delivery layer.

```
PR opened/updated
  → GitHub App webhook → https://review-hub.mtgibbs.dev/webhook
  → [Cloudflare Tunnel, path-locked to /webhook] → review-hub Service :8080
  → receiver: verify HMAC → ack 202 → background:
        mint App installation token (from payload's installation id)
        evaluators_for(repo) → judge changed triggerable CronJobs (multi-vote)
        HTTPS → ai.lab.mtgibbs.dev/v1 (qwen)
        post Check Run (failure = merge gate) + comment
```

## Files

- `scripts/triggerable_judge.py` — judge + the triggerable evaluator (importable)
- `scripts/reviewhub/` — `github_app.py`, `evaluators.py` (registry), `receiver.py`, `Dockerfile`, `VERSION`
- `.github/workflows/build-review-hub.yml` — builds + pushes `ghcr.io/mtgibbs/review-hub` (multi-arch)
- `clusters/pi-k3s/review-hub/` — namespace, ExternalSecret, Deployment, Service, image-automation, kustomization
- `clusters/pi-k3s/flux-system/infrastructure.yaml` — Kustomization #29
- `clusters/pi-k3s/cloudflare-tunnel/config.yaml` — the `review-hub.mtgibbs.dev` route

## Identity (DONE)

One GitHub App "review-bot" (app id `3998878`), installed on **all** repos,
verified minting a per-repo installation token that sees all 45 repos. Secrets in
`op://pi-cluster/review-hub` → `{app-id, private-key, webhook-secret, litellm-key}`.
**No per-repo PATs.** A new repo is auto-covered; a new evaluator is a registry entry.

## Deploy sequence

1. **Commit + push** the code + manifests to `main`. The `build-review-hub`
   workflow builds `ghcr.io/mtgibbs/review-hub:0.1.0` and pushes it.

2. **Flip the GHCR package public** (the cluster pulls anonymously), once, after
   the first push:
   ```bash
   gh api -X PATCH /user/packages/container/review-hub -f visibility=public
   ```

3. **DNS** — point `review-hub.mtgibbs.dev` at the Cloudflare Tunnel (a CNAME to
   `<TUNNEL_ID>.cfargotunnel.com`, same as the other `*.mtgibbs.dev` tunnel hosts).
   Claude can add this with the DNS-scoped `cloudflare` token.

4. **Point the App's webhook URL** at `https://review-hub.mtgibbs.dev/webhook`
   (you set a placeholder at creation — update it now).

5. **Flux deploys.** The ExternalSecret syncs the 4 fields; the Deployment pulls
   the image (brief ImagePullBackOff until steps 1–2 land is normal); the Service
   comes up; the Tunnel routes the hostname. Image-automation rolls future
   versions when `VERSION` is bumped.

6. **Make it a merge gate.** In branch protection for `mtgibbs/pi-cluster` `main`,
   add the **`triggerable-judge`** check as required. (Add it on
   `mtgibbs/pi-cluster-mcp` when evaluator #2 lands.)

## Verify

Open a PR on `pi-cluster` that adds/edits a CronJob with
`homelab.mcp/triggerable: "true"`. GitHub delivers the webhook; the `triggerable-judge`
check appears in_progress, then success (clean) or failure (fail/flag), with a
verdict comment. Check delivery under *App → Advanced → Recent Deliveries*, and pod
logs with `kubectl logs -n review-hub deploy/review-hub`.

## Onboarding a repo (opt-in)

A repo signs up by committing **`.review-hub.yml`** at its root — presence is the
sign-up, absence means no review (opt-in, not opt-out). The bot's App is installed
org-wide but only reviews repos that ship this file. The opt-in is read from the
repo's **default branch** (not the PR head) — so the subscription takes effect once
the file is **merged to `main`**, and a PR can't opt itself out (or in) by editing it:

```yaml
# .review-hub.yml
validators:
  - gate-regression      # by name; must be a validator valid for this repo
```

Two-sided handshake in `validators_for(repo, files, opted_in)`: a validator runs iff
(1) the repo opted into it here, (2) the validator is valid for this repo
(`repos` empty = any), and (3) the changed files match its globs. **Onboarding a repo
never touches review-hub code — one commit on the repo's side.**

## Adding a validator (e.g. MCP tool-safety)

1. Add a single-concern validator: a class in `scripts/reviewhub/validators/<name>.py`
   (its `repos`/`globs` routing + `review()`) and its prompt+eval set under
   `specs/validators/<name>/` (`contract.md` + `eval/`). Register it in
   `validators/__init__.py` `REGISTRY`.
2. Repos opt in by adding its name to their `.review-hub.yml`. Bump `VERSION`. Done —
   **no new App, runner, secret, or service.**

## Notes

- **Fail-safe:** only a clean `pass` clears; fail/flag/error (incl. a crashed
  evaluator or a model timeout) all post a `failure` Check Run. A hazard can't slip
  through on an error.
- **No inbound creds:** the only exposed surface is `POST /webhook`, HMAC-verified;
  `/health` is internal (tunnel 404s it).
- **Model:** `hot-coder` by default (env `JUDGE_MODEL`); the key is scoped to the
  coder models so you can switch to `qwen3-coder-30b`/`-next-q8` without re-minting.
- **Orphaned key:** the earlier `triggerable-judge`-alias LiteLLM key is unused
  (superseded by the `review-hub` alias); delete it via LiteLLM `/key/delete` for hygiene.
