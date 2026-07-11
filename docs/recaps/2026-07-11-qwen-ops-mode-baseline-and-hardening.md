# Recap — qwen ops-debugging baseline, AGENTS.md hardening, and ops mode (2026-07-11)

Local coding agent initiative: qwen3-coder has been a *coding* executor since it stood up, but Matt
declared local-model **ops debugging** — "check on X and make sure it's in Jellyfin" style questions
— a requirement for the self-sustaining homestead lab, not out-of-scope. This session banked a
failure baseline, hardened the prompt layer against it, and shipped a dedicated opencode ops agent.

## 1. Baseline: unscaffolded qwen as an ops debugger

Matt ran a stale laptop opencode session (hot-coder, `ses_0c336c21effespTcakl1Q50t7Y`) and asked it
to check on a download of "seeking persophone" and confirm it imported into Jellyfin. Ground truth
via mcp-homelab: no such download exists anywhere (Radarr/SABnzbd queue+history all empty of it —
it's a Sarah M. Eden novel, not a film). The correct answer was two read-only MCP calls.

qwen instead: searched the *laptop* filesystem for cluster media, hand-rolled a JSON-RPC curl against
the MCP endpoint with an invented method (`jellyfin/scan-media`), curled in-cluster DNS names from
the laptop and treated silent/empty `curl -s` output as progress, extracted and printed the Jellyfin
API key from the k8s secret, and closed with a hallucinated 3-option tool menu. Full taxonomy in
`docs/research/local-coding-agent-sdd.md` §16. The exposed key was deliberately **not rotated**
(Matt's call — LAN-only service).

Commit: `21698d2`.

## 2. AGENTS.md hardened against the failure modes

Added non-negotiables straight from the §16 taxonomy: "this machine is not the homelab" (world-model
fix), "you have exactly the tools in your tool list — no improvised HTTP/JSON-RPC, no self-served
credentials, no `kubectl`, missing tool = stop and say so", "silence is failure" (empty
`curl -s`/`2>/dev/null` output means failed until proven otherwise), and the never-print-secrets rule
extended to secrets *at rest* (`kubectl get secret`, `base64 -d`, `/var/secrets`). Prompt layer
only — opencode's actual permission enforcement is machine-local, addressed next.

Commit: `eeea0a1` (`AGENTS.md`).

## 3. Ops mode — a dedicated opencode agent, not more prose

The real fix: `.opencode/agents/ops.md`, a repo-tracked opencode primary agent distinct from the
coding executor — its own world-model prompt, a curated 23-tool `mcp-homelab` subset, four bounded
mutations (`homelab_restart_deployment`, `homelab_reconcile_flux`, `homelab_fix_jellyfin_metadata`,
`homelab_retry_sabnzbd_download`) gated to `ask`, `edit: deny`, and `kubectl */op *: deny`.

`scripts/oc` grows an `ops` subcommand: loads `MCP_HOMELAB_KEY` (Keychain service `mcp-homelab`
first, else `op://pi-cluster/mcp-homelab/api-key` with Touch ID), then execs `opencode --agent ops`.
Plain `oc` never prompts for the ops key.

`.claude/skills/coding-agent-ops/SKILL.md` gained a full "Ops mode" runbook section: machine-local
`opencode.json` wiring (including deleting an invalid `mcpServers` key that caused
`ConfigInvalidError` on opencode 1.17.x), the smoke test (`oc ops` → ask cluster health → confirm it
calls `homelab_get_cluster_health` instead of shelling out), and the eval — rerun the §16 baseline
prompt verbatim in `oc ops` and log the after-result back into research log §16. Ops quality noted as
meaningfully better on the Q8 (`aimode work`) tier — prefer it for nontrivial debugging.

Commit: `4d27eea` (`.opencode/agents/ops.md`, `scripts/oc`, SKILL.md).

## 4. Handoff state / open decisions

The laptop agent is applying the machine-local steps now: merging `opencode.json`, `cp scripts/oc
~/.local/bin/`, running the smoke test, and rerunning the §16 baseline prompt as the after-measurement.

- **Open: MCP key tier.** 1Password-only (Touch ID per ops session — respects the crown-jewel rule,
  since the key is cluster-acting) vs. seeding the Keychain for convenience. Not yet decided.
- **Container follow-up (not done):** `coding-harness-qwen` gets `ops.md` via the repo but needs
  `MCP_HOMELAB_KEY` in its env (beelink-ansible, laptop-side change) before `oc ops` works there.
- Noted for day-to-day use: `opencode export <session-id>` is the clean way to hand a qwen transcript
  to Claude for review — added to the SKILL.md.

No cluster topology changed. All three commits are docs/prompt/tooling for the local-agent
initiative; durable detail lives in `docs/research/local-coding-agent-sdd.md` §16 and
`.claude/skills/coding-agent-ops/SKILL.md` — this recap is a pointer, not a duplicate.

---

## Commits

| Repo | Ref | Subject |
| :--- | :--- | :--- |
| pi-cluster | `21698d2` | docs(coding-agent): bank unscaffolded-qwen ops-debugging baseline (§16) |
| pi-cluster | `eeea0a1` | feat(coding-agent): harden AGENTS.md against the ops-baseline failure modes |
| pi-cluster | `4d27eea` | feat(coding-agent): ops mode — local-model homelab diagnostician (oc ops) |
