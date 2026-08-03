# Incident: agent-bus message interpolation leaked six live credentials (2026-08-02)

- **Date:** 2026-08-02, ~23:15 EDT exposure → 2026-08-03 ~00:30 EDT fully remediated
- **Severity:** High exposure class (live credentials in a chat room), low realized blast radius
  (private lab room; 5/6 credentials unusable off-LAN; no evidence of misuse)
- **Status:** ✅ **Resolved same night** — all six credentials rotated **and revoke-verified**;
  root cause fixed in #133; consumers redeployed and confirmed green.
- **Detected via:** laptop-Claude reading the message during normal bus traffic; the sending
  agent independently noticed its message was malformed and self-redacted.

---

## 1. TL;DR

`coding-harness-claude` posted a long status message to the Matrix `#tasks` room. The
`agent-bus post` CLI took the message body as a **shell-interpolated argv string**, and the body
contained a `$(export)`-shaped fragment — so the shell expanded it mid-sentence and pasted the
container's **entire environment** (`declare -x` dump) into the room, including six live
credentials. The body was never data; it was code.

Every credential was rotated the same night, in blast-radius order, with the **old value verified
dead** (401) before the item was called closed. The CLI defect was fixed the same night (#133):
`agent-bus post --file` / stdin — the body never touches a shell argument.

## 2. What leaked, and real exposure

| Credential | What it grants | Off-LAN usable? |
|---|---|---|
| `HARNESS_GITHUB_PAT` | git push/pull as the harness role on mtgibbs repos | **YES — the only one** |
| `MCP_HOMELAB_KEY` | homelab MCP: cluster reads + bounded mutations | no (LAN/Tailscale) |
| `HARNESS_LITELLM_KEY` | LiteLLM spend on the `opencode-coder` virtual key | no (LAN) |
| `MATRIX_TOKEN` (harness-claude) | post/read as the agent on the lab bus | no (LAN) |
| `LOCAL_LLM_MCP_KEY` | local-llm MCP server | no (LAN) |
| `KIWIX_MCP_KEY` | kiwix MCP server | no (LAN) |

**Audience of the leak:** the private `#tasks` room (lab agents + Matt) plus anything that synced
before redaction — the laptop-Claude session transcript at minimum. The sender redacted the event
server-side; zero live room events carried secrets afterward (verified by API query). Rotation
proceeded anyway: redaction does not un-sync a value, and transcripts persist.

## 3. Timeline (EDT)

- **~23:15** — harness posts the message; interpolation dumps the env into `#tasks`.
- **~23:5x** — laptop-Claude reads the room during unrelated work, identifies six live values,
  flags the incident. Independently, the harness notices its message is malformed (the dump also
  *truncated* the intended content) and **redacts its own event**.
- **~23:58** — redaction verified: 0 live events in the room contain secret material.
- **23:59–00:15** — rotation, in order (see §4). Matt handles the GitHub PAT (UI-only op);
  laptop-Claude executes the rest end-to-end.
- **~00:12** — `deploy-ai-stack.sh` rerun re-renders the Beelink `.env` from 1Password and
  recreates the containers.
- **~00:20** — harness returns on its new token and confirms all three paths green (bus write,
  MCP with new keys, git push with new PAT). Incident closed.
- **Same night** — root-cause fix merged (pi-cluster#133): `agent-bus post --file` / stdin path,
  plus an outbound secrets guard.

## 4. Response — rotate in blast-radius order, verify the OLD value fails

The bar for "done" on each item was **the old credential observably failing**, not the new one
working. A rotation that leaves the old value live has accomplished nothing.

1. **GitHub PAT** (first — the only off-LAN credential): revoked + reissued by Matt in the GitHub
   UI. Old PAT → `401` against `api.github.com`. The push PAT deliberately lacks `workflow`
   scope; that gap survives the rotation.
2. **MCP keys ×3** (homelab / local-llm / kiwix): new values minted (structure-matched), written
   to their existing 1Password items — no new items minted — ExternalSecrets force-synced,
   deployments rolled. Old keys → `401`, new → `200`, on all three `/mcp` endpoints.
3. **LiteLLM key**: `/key/delete` old + `/key/generate` with the same alias and model scope
   (`opencode-coder`: qwen3-coder-30b, hot-coder). Old → `401`, new → `200` on `/v1/models`.
4. **Matrix token** (last — cuts the harness off the bus until rebuild): fresh device login,
   old device explicitly logged out (a new Synapse login does NOT invalidate old sessions).
   Old token → `401` on `whoami`.
5. **Consumer redeploy**: `deploy-ai-stack.sh` (reads every secret fresh from 1Password) rebuilt
   the Beelink stack; harness verified bus/MCP/git green on the new set.

## 5. Root cause and the fix

**Root cause:** `agent-bus post <room> "<body>"` passed the body through shell interpolation.
Message bodies routinely contain logs, diffs, tracebacks and command output — exactly the content
most likely to contain `$(...)`/backtick shapes. The defect was structural, not a typo.

**Fix (#133, merged same night):** `agent-bus post <room> --file PATH` (or stdin) — the body is
read as data and never touches a shell argument. Header docs now instruct: *use `--file`/stdin
for anything containing logs, diffs, tracebacks or command output.* An outbound secrets guard
also scans bodies before posting.

**Follow-up on the guard (harness, in progress):** the first guard matched bare substrings
(e.g. `declare -x `), which false-positives on *prose about* an incident — and a guard that
blocks incident write-ups trains agents to reflexively override it. It is being tightened to
match actual assignments (`declare -x NAME=`) instead of mentions.

## 6. Lessons

1. **Message bodies are data, not code.** Any CLI that forwards user/agent text into a shell
   argv is a leak waiting for its first traceback. (#133)
2. **Revoke-and-verify is the deliverable.** Each rotation closed only when the old value
   returned 401. New-key-works proves nothing about exposure.
3. **Rotate in blast-radius order.** The one off-LAN credential (GitHub PAT) went first; the
   bus token went last because rotating it silences the victim agent mid-incident.
4. **Per-role credentials kept this small.** One identity per system meant six rotations, zero
   cascading re-issuance — the `credentials-scale-by-role` policy paying out under fire.
5. **A guard that cries wolf gets overridden.** Secret-detection must match dumps, not mentions
   of dumps, or its override flag becomes routine (§5 follow-up).
6. **Ops trap, recorded:** zsh does not word-split unquoted variables — a `for pair in ...; set
   -- $pair` rotation loop silently no-ops. The ExternalSecret `refreshTime` check caught it;
   verify sync timestamps, not command exit codes, when forcing ESO refreshes.
7. **Transcripts outlive redactions.** The laptop session transcript holds a pre-redaction copy;
   inert once rotation verified, but it is why redaction alone never closes a leak.

## 7. Verification record

- Room sweep post-redaction: 0 events containing secret fragments (Matrix `/messages` API).
- Old values: PAT 401 · homelab 401 · local-llm 401 · kiwix 401 · LiteLLM 401 · Matrix 401.
- New values: homelab 200 · local-llm 200 · kiwix 200 · LiteLLM 200 · Matrix 200 · PAT confirmed
  by harness `git push --dry-run`.
- Harness post-rebuild: bus write ✅ · MCP `get_cluster_health` 4/4 nodes ✅ · git ✅.
