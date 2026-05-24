# Session Recap — 2026-05-24 (AI Control Panel + Context Budget + aimode Fixes)

This session had four threads that wound together. The headline result is a live AI control panel — `controlpanel.lab.mtgibbs.dev` — shipped end-to-end as the **first real SDD dogfood run**: two bounded qwen tasks, Claude providing orchestration glue, a full Flux + Ansible deploy, and a verified live service. The other threads are the context-budget benchmark that closed an open question from the previous session, a pair of real bugs in `aimode.sh` that were found and fixed, and a deliberate architectural decision to defer network-wide SSO rather than bolt it on piecemeal.

Related prior recaps: `docs/recaps/2026-05-21-q8-coder-agent-comparison.md` (the model comparison session that validated the two-tier strategy) and `docs/recaps/2026-05-22-dewey-rag-rebuild.md` (which produced the Dewey model pair that aimode now correctly warms).

---

## Chapter 1 — Context Budget: The 32k-vs-64k Benchmark (RESOLVED)

### The open question

Coming out of the previous session, one question remained undecided: when a spec is too large to decompose cleanly into independent tasks (the ~10% genuinely cross-cutting case), is Path B — giving qwen a larger context window — actually viable on the Beelink's hardware? The concern was twofold: (a) does prefix caching actually work in practice, making repeated large-context runs cheap? and (b) how bad is uncached prefill latency at 64k?

The question mattered because it determines what the "escape hatch" option is for hard specs: either you decompose harder (Path A), or you can hand the model more context (Path B). Without measured data, Path B was just a theory.

### What was measured

Probed sole-tenant via Ollama's `/api/generate` timing fields, with `qwen3-coder:30b` reloaded at `num_ctx=65536`. (Q8 at 64k was deliberately not tested — at 85 GB model weights plus 64k KV cache, it would risk exceeding the 96 GB VRAM carveout on the Beelink.)

| Prompt tokens | Prefill tok/s | Wall time |
|---|---|---|
| 403 | 778 | 0.5s |
| 5,734 | 635 | 9s |
| 15,615 | 331 | 47s |
| 28,615 | 194 | 148s |
| **57,991** | **99** | **~583s (~10 min)** |

Three findings, all decisive:

**(a) Prefix caching is real and dramatic.** An identical prompt sent twice: `4.15s → 0.02s` on the second call. The unchanged prefix is served from the KV cache at essentially zero cost (flash attention on, `keep_alive=-1`). If you can hold the prefix stable, large contexts are viable.

**(b) Uncached prefill is brutal and super-linear.** Prefill rate collapses from 778 tok/s at a short prompt to 99 tok/s at 58k tokens — an 8x slowdown. A near-full 58k context costs ~10 minutes of wall time before the first output token. A single cache eviction (model displaced from VRAM by another request) resets this entirely.

**(c) Quality at depth held.** A needle (`port 8443` / `svc-dewey-prober-x9`) placed at ~50% of a 49k context was retrieved exactly. The model did not lose-in-the-middle at that depth. Large context is not quality-disqualified.

### Verdict

Path A (decompose harder) is the default for all specs. Small, fresh contexts are cheap to prefill, survive any eviction event, and are quality-optimal because the model receives only what it needs.

Path B (more context) is a deliberate escape hatch — valid **only** under `aimode work` (sole-tenant, protects the cache slot) with a stable prefix. It applies to the ~10% of genuinely cross-cutting specs where independent decomposition is not achievable. It is expensive on first prefill and one eviction away from a 10-minute penalty.

Two flavors now exist: Q8 @ 32k (smarter model, must decompose — the recommended power default) and 30B @ 64k (weaker judgment but can hold a big spec — niche, for "read whole spec + one file" one-shots, not iterative loops). The 30B@64k mode also requires raising opencode's `limit.context` to 64k, which was deliberately left not built — the data says it's too niche to justify.

### What shipped (commits `b1440c6`, `49e4cf4`)

- The benchmark data and synthesis were written into `docs/research/local-coding-agent-sdd.md` as §12 and §13.
- `opencode.json` model was repointed from the hardcoded `beelink/qwen3-coder-30b` to `beelink/hot-coder`. `oc` and the ralph loop now follow `aimode`: 30B in family mode, Q8 in work mode. The toggle finally reaches the coding loop.
- Unused opencode tools (`skill`, `task`, `todowrite`) were disabled in `opencode.json` to reclaim ~2.6k tokens of preamble space. (Whether `false` strips the schema or merely denies the call — the exact floor — is a follow-up to confirm with a preamble capture.)

---

## Chapter 2 — aimode Bugs Found and Fixed

### Bug 1: `warm()` was a silent no-op

The `warm()` function in `aimode.sh` was implemented as:

```bash
docker exec ollama curl -s http://localhost:11434/api/generate ...
```

The ollama Docker image ships no `curl`. Every warm-up call since the toggle shipped had silently exited with `rc=127` (command not found) and was swallowed by the `|| true`. Dewey was never actually being pre-loaded when switching to family mode — the first request after an `aimode family` flip always hit the full model-load latency.

**Fix (`beelink-ansible` commit `9ebc265`):** switch to `docker exec open-webui curl`, pointing at `http://ollama:11434` over the Docker network. This is the same path used by the deploy-time warmup in `50-ai-stack.yml` — a proven route that has always worked.

### Bug 2: warm-up targeted stale models

Even if the curl had worked, the models being warmed were wrong. `aimode.sh` was warming `gemma3:27b` and `qwen3.5:9b` — the original model set from Phase 0.5 of the Beelink bringup. Dewey's actual models, per `dewey-pipeline.py`'s defaults (verified via LiteLLM `/model/info` with no `DEWEY_MODEL` override in the container env), are `qwen3-30b-instruct` and `qwen3-4b-instruct`.

**Fix (same commit):** corrected the warm-set to `qwen3-30b-instruct` (Dewey's answer model) and `qwen3-4b-instruct` (Dewey's keyword model). With `OLLAMA_MAX_LOADED_MODELS=3`, these two plus the coder fill VRAM exactly.

### aimode flip timings measured

While the bugs were being diagnosed, actual mode-flip timings were measured and committed (`57eac29`):

| Flip | Wall time | Notes |
|---|---|---|
| family → work | ~54s | evict Ollama models → start llama-server → load ~85 GB Q8 |
| work → family | ~9s | repoint LiteLLM + stop llama-server + warm Dewey pair |

Per-model heat-up (page-cache-warm): 30B-class models ~6s, 4B ~2s, Q8 ~50s. True-cold (post-reboot, disk-bound at ~1.7 GB/s): a 25 GB model takes ~15s; the Q8 approaches 60–120s.

The practical implication: in steady-state use, flipping to work mode takes about a minute to reach full power. Dewey is unavailable for the entire duration that work mode is held. These numbers are now in `docs/beelink-ai-stack.md`.

---

## Chapter 3 — The AI Control Panel: The Headline

### Why

`aimode` was SSH-only. There was no at-a-glance view of whether the Beelink was in family mode (Dewey + 30B coder, shared) or work mode (Q8 sole-tenant, Dewey down). The natural place to surface this is the homepage, but adding a flip button from the homepage requires a real HTTP service. The spec was also deliberately designed as the first module of a **general AI control panel** — a structure that can grow (warm/evict a model, show loaded VRAM, restart a service) without a rename or rebuild. Routes are namespaced; future modules slot in under their own prefixes.

### The SDD decomposition

The spec (`specs/aimode-toggle/spec.md`) was written to v0.2, then split into two bounded qwen tasks with matching gates:

- **Task A:** implement `beelink-ansible/files/ai-controlpanel.py` — a stdlib Python host HTTP service. EARS criteria A1–A8 (status endpoint, flip endpoint, token gate, prefix dispatch, no hardcoded secrets). Verified by `specs/aimode-toggle/verify.sh` assertions A.
- **Task B:** add the homepage status card and bookmark in `clusters/pi-k3s/homepage/configmap.yaml`. EARS criteria B1–B4 (one `customapi` card reading `/aimode`, one bookmark carrying the token via `{{HOMEPAGE_VAR_AI_CONTROLPANEL_TOKEN}}`, no other diffs). Verified by verify.sh assertions B.

Claude owned the cross-cutting glue (Task C): the systemd unit, the Ansible deploy tasks, the Caddy reverse-proxy route, the DNS record, and the token ExternalSecret. These pieces all cross boundaries between repos and systems — not appropriate to hand to a bounded qwen task.

### What qwen built

**Task A** (`beelink-ansible` commit `92e51b8`): `ai-controlpanel.py`, 139 lines, stdlib `http.server`. Prefix-dispatch router. `GET /` returns an HTML dashboard with an AI Mode section, current mode display, and two flip buttons. `GET /aimode` returns `{"mode": "..."}` (open, for the homepage card). `POST /aimode/flip/{family,work}` is token-gated; runs `sudo aimode {family|work}` and returns the new mode. `GET /aimode/flip/*` with a missing or wrong token returns 403. Token comes exclusively from `AI_CONTROLPANEL_TOKEN` env. Passed `verify.sh` A assertions.

**Task B** (`pi-cluster` commit `2c55513`): added one `customapi` card to the Beelink group in `configmap.yaml` (polls `https://controlpanel.lab.mtgibbs.dev/aimode`, displays `mode`) and one bookmark to the control panel with the token in the URL via `{{HOMEPAGE_VAR_AI_CONTROLPANEL_TOKEN}}`. Passed verify.sh B assertions after a minor regex correction by Claude (`c47a7df`).

### The glue Claude wired (commits `48ccce7` / `c916956`)

**On the cluster side (`pi-cluster`):**
- `controlpanel.lab.mtgibbs.dev` DNS record added to `clusters/pi-k3s/pihole/pihole-custom-dns.yaml`, pointing at the Beelink (`192.168.1.70`).
- `homepage-ai-controlpanel` ExternalSecret created: reads `op://pi-cluster/ai-controlpanel/token` and surfaces it as `HOMEPAGE_VAR_AI_CONTROLPANEL_TOKEN` in the homepage deployment's `envFrom`.

**On the Beelink side (`beelink-ansible`):**
- `files/ai-controlpanel.service`: systemd unit running `ai-controlpanel.py` as root (simplest least-privilege path — the flip requires `sudo aimode`, and running as root avoids a NOPASSWD sudoers line for a host-level service).
- `playbooks/50-ai-stack.yml` deploy tasks: copies the service file, renders an env file with the token (from `op://pi-cluster/ai-controlpanel/token`), enables and starts the unit.
- Caddy route for `controlpanel.lab.mtgibbs.dev`, reverse-proxying to `host.docker.internal:9110`. Caddy runs in Docker; the control panel is on the host — `extra_hosts: host-gateway` is how Caddy reaches it.

### Integration issues encountered

Three real friction points emerged during the deploy. None were in the spec or in qwen's code; all were orchestration-layer issues:

**1. LiteLLM key ACL blocked `hot-coder`.** When `opencode.json` was repointed to `beelink/hot-coder`, the first actual `oc` invocation failed because the `opencode-coder` LiteLLM virtual key's `model_access` allowlist did not include `hot-coder` — it was scoped to `qwen3-coder:30b` by name. Fix: update the key's allowed models in LiteLLM to include the alias.

**2. Pi-hole needed a restart to pick up the new DNS record.** After committing the `pihole-custom-dns.yaml` change and letting Flux reconcile, DNS resolution for `controlpanel.lab.mtgibbs.dev` was returning the Beelink's `.55` Tailscale address (the `*.lab.mtgibbs.dev` wildcard) rather than the LAN `.70` address from the new custom record. Pi-hole's DNS config had reloaded but not taken effect for the new record. A Pi-hole restart resolved it — the custom record was then read correctly and `.70` served.

**3. ufw blocked Caddy's connection to port 9110.** After deploying the Ansible playbook, the control panel returned 502. The cause: `ai-controlpanel.py` is a host service (not Docker-published), so ufw governs inbound connections to port 9110 — and there was no ufw rule permitting the Docker bridge subnets to reach it. Caddy reaches the host via `host.docker.internal`, which resolves to an address in the Docker bridge range (`172.16.0.0/12`). Added a ufw rule in `beelink-ansible` commit `8cf0970`:

```bash
ufw allow from 172.16.0.0/12 to any port 9110 proto tcp
```

This matches the existing pattern for port 9100 (node_exporter). The service never needed to be LAN-accessible directly — Caddy is the only legitimate caller.

**4. The `op` CLI works fine in tool calls with sandboxing disabled.** A standing assumption — that `op` (1Password CLI) couldn't run non-interactively in Claude's tool calls — turned out to be wrong. The actual constraint was Claude Code's sandbox mode. With `dangerouslyDisableSandbox: true`, `op` reads credentials cleanly in tool calls. The prior workaround (seeding to macOS Keychain and reading from there in the hot path) was a sandbox artifact, not a fundamental op CLI limitation. This is a meaningful correction: it means the op-friction "keystone" that was framed as a major blocker is smaller than believed.

### End state

After the deploy and ufw fix, verified live:

- `https://controlpanel.lab.mtgibbs.dev/aimode` returns `{"mode": "family"}` (or `work`)
- The homepage Beelink group shows an AI Mode status card, auto-refreshing
- A tokened bookmark in the homepage AI Controls section links directly to the control panel
- A flip from the control panel actually runs `aimode` on the Beelink and reflects the new mode within one refresh
- A tokenless flip returns 403

A final polish commit (`37b49bd`) made the AI Mode status card itself clickable — tapping it navigates to the control panel, not just reading the mode.

---

## Chapter 4 — The Dogfood Result: What the SDD Run Validated

The most important output of this session is not the control panel itself — it is what the process of building it revealed.

### The predicted split held exactly

The decomposition hypothesis going into this session was: qwen handles bounded, well-specified coding tasks reliably; Claude handles cross-cutting orchestration. Both sides of that prediction held.

qwen's outputs on both Task A and Task B were correct, in scope, and passed their verify.sh gates on first or second attempt. The code was clean, idiomatic stdlib Python. The homepage YAML was properly structured. qwen did not go out of scope on either task. The spec guard (explicit "DO NOT modify X" scope boundaries + EARS criteria + verify.sh) was sufficient to keep it bounded.

**All the friction was at the orchestrator level:** the LiteLLM key ACL, the Pi-hole restart, the ufw rule, and the sandbox discovery. None of these were in a task file. None were things a bounded code-generation step could have been expected to anticipate. They were integration facts that crossed system boundaries — exactly the layer Claude is positioned to handle.

### The spec was the artifact

The spec (`specs/aimode-toggle/spec.md`) grew from v0.2 to Done v1.0 during the session. The v0.2 spec had already pre-identified the three open questions (OQ1: Caddy→host reach; OQ2: sudo for the service; OQ3: token exposure). All three were resolved in Task C, as planned. OQ1 and OQ2 were engineering problems (the `extra_hosts: host-gateway` pattern and the root-unit decision). OQ3 became a deliberate policy decision (see Chapter 5).

The verify.sh gates caught one issue: a regex in the B-assertions was written for an unparameterized URL and needed to handle the tokenized `?token={{...}}` form after the spec was refined. Claude fixed that (`c47a7df`) before the B-loop ran. This is the verify.sh doing its job — catching a spec ambiguity before handing to qwen, not after.

### What this proves for the local-coding-agent initiative

The local coding agent initiative (documented in `docs/research/local-coding-agent-sdd.md`) now has a real, deployed proof-point. The SDD loop works for this class of problem: a greenfield service with clear API contracts and no cross-cutting entanglement in the parts handed to qwen. The friction budget for one real feature was: spec authoring (~1.5 hrs), three integration issues caught at deploy (~1 hr), and one verify.sh fix (~15 min). Total: roughly half a session. Output: a live service.

---

## Chapter 5 — Auth/SSO Deliberately Deferred

The control panel's flip token is carried in the homepage bookmark URL and rendered into the homepage DOM. It also appears in Caddy access logs. This is a deliberate, documented interim — not an oversight.

The reasoning: the worst-case blast radius for token exposure is that someone on the LAN toggles AI mode. The gated action is reversible (toggle back). The token is not a session credential, not a secret that grants access to sensitive data, and not reused anywhere else. Accepted interim, tracked in the roadmap.

However, the flip token also made visible a larger question: should auth be added to `controlpanel.lab` now? The answer is no — and more importantly, the answer is "not piecemeal." Network-wide SSO requires a holistic plan. Jellyfin has its own user model. The *arr stack has its own logins. Pi-hole has its own admin auth. Bolting forward-auth in front of all of those without breaking their native auth is a design problem. Deploying Authelia just for `controlpanel.lab` would leave the rest of the stack still unprotected and would create a false sense of coverage.

Decision recorded in `docs/roadmap-2026-q2.md`: SSO remains deliberately deferred until there is a plan that covers the whole stack. An "interim auth ledger" was added to track the debt: the controlpanel token-in-URL is the first entry, to be retired when SSO eventually fronts `controlpanel.lab`.

The aimode-toggle spec was marked **Done v1.0** and OQ3 was resolved with the accepted interim documented inline.

---

## Key Lessons

### The SDD split is empirically validated, not just a theory

Going into this session, the "qwen executes bounded tasks, Claude orchestrates" claim was supported by one data point (the homepage refresh). This session adds a second, more complex one: a feature that spans two repos, a host service, a systemd unit, a Caddy route, a DNS record, and a Kubernetes ExternalSecret. The bounded pieces were correct. The cross-cutting pieces required orchestrator judgment. The split held as predicted.

### Integration friction lives at the boundary, not inside bounded tasks

The three real issues (LiteLLM ACL, Pi-hole restart, ufw rule) were all invisible from inside either task's scope. They couldn't have been captured in Task A's spec or Task B's spec because they only exist at the intersection of: (a) LiteLLM's virtual-key model allowlists, (b) Pi-hole's runtime DNS cache, and (c) ufw's treatment of Docker bridge traffic to host services. This is precisely why the orchestrator layer exists. The implication for future SDD runs: the verify.sh gates catch within-task errors; integration errors surface at deploy. Plan for a deploy-verify-debug iteration.

### The op CLI assumption was wrong (and smaller than it looked)

The "op can't run non-interactively" belief was a sandbox artifact. With `dangerouslyDisableSandbox: true`, op reads 1Password items cleanly in Claude tool calls. This does not change the operational hot-path (Keychain seeding is still the right pattern for tools that run frequently on the hot path without supervision), but it removes a category of friction from orchestration work where Claude is already present and the session is supervised.

### The ufw/host-service pattern is now documented

A host service reachable only through Caddy does not need a LAN-wide ufw rule — only the Docker bridge subnets need access. The pattern (`ufw allow from 172.16.0.0/12 to any port <N> proto tcp`) is the same as the existing node_exporter rule for port 9100. Any future host service routed through Caddy should follow the same pattern.

### Measured data closes design debates faster than discussion

The context budget debate (Path A vs Path B) consumed multiple hours of reasoning across two sessions and remained open. Thirty minutes of targeted benchmarking (prefill curve + caching check + needle retrieval) closed it cleanly with numbers. The same pattern held for the aimode timing debate — "how long does a flip take in practice?" was answerable in a few minutes once the question was posed as a measurement rather than an estimate.

---

## Commits

### pi-cluster repo

| Hash | Date | Subject |
|---|---|---|
| `b1440c6` | 2026-05-24 | docs(research): context budget §12 + WHERE-WE-LEFT-OFF §13 (pre-compaction) |
| `49e4cf4` | 2026-05-24 | feat(coding-agent): opencode→hot-coder, trim tools, bank 32k-vs-64k benchmark |
| `57eac29` | 2026-05-24 | docs(beelink): measured aimode flip + per-model heat-up timings |
| `1d9eb68` | 2026-05-24 | spec(ai-controlpanel): AI control panel — aimode module + homepage status |
| `c47a7df` | 2026-05-24 | fix(verify): correct B2 bookmark regex for tokened panel URL |
| `2c55513` | 2026-05-24 | feat(homepage): AI Mode status card + AI Controls bookmark (qwen-generated) |
| `48ccce7` | 2026-05-24 | feat(ai-controlpanel): cluster-side glue (DNS + token ExternalSecret + env) |
| `89b76a2` | 2026-05-24 | merge: ai-controlpanel cluster side (homepage card+bookmark, DNS, token ExternalSecret) |
| `37b49bd` | 2026-05-24 | fix(homepage): make the AI Mode card clickable → control panel |
| `939f457` | 2026-05-24 | docs: defer network-wide SSO deliberately + log ai-controlpanel token as interim |

### beelink-ansible repo

| Hash | Date | Subject |
|---|---|---|
| `9ebc265` | 2026-05-24 | fix(aimode): repair family warm-ups (no-op + stale models) |
| `92e51b8` | 2026-05-24 | feat(ai-controlpanel): aimode module HTTP service (qwen-generated) |
| `c916956` | 2026-05-24 | feat(ai-controlpanel): host service deploy + Caddy route (glue) |
| `8cf0970` | 2026-05-24 | fix(ai-controlpanel): ufw rule for Caddy→host:9110 (502 fix) |
| `f8e3cd4` | 2026-05-24 | merge: ai-controlpanel — host service, Caddy route, ufw rule, aimode warm fix |

---

## Verified End State

| Component | State | Notes |
|---|---|---|
| `controlpanel.lab.mtgibbs.dev` | Live | Returns real mode; flip works; 403 on tokenless attempt |
| `ai-controlpanel.py` | Deployed as systemd unit (root) | Token from env; prefix-dispatch router; extensible |
| `aimode warm()` | Fixed | Uses `docker exec open-webui curl`; warms Dewey's real models |
| `aimode` flip timings | Measured + documented | →work ~54s, →family ~9s; now in `docs/beelink-ai-stack.md` |
| Homepage AI Mode card | Live | Clickable; auto-refreshes; reads `/aimode` |
| Homepage AI Controls bookmark | Live | Tokened URL via `{{HOMEPAGE_VAR_AI_CONTROLPANEL_TOKEN}}` |
| DNS `controlpanel.lab` | Live | `192.168.1.70` (Beelink); Pi-hole restart applied |
| Token ExternalSecret | Synced | `op://pi-cluster/ai-controlpanel/token` → homepage env |
| `opencode.json` model | `beelink/hot-coder` | Follows `aimode`; unused tools disabled |
| Context budget decision | Path A default, Path B escape hatch | Measured data in `docs/research/local-coding-agent-sdd.md` §12/§13 |
| SSO deferral | Deliberate + documented | Interim auth ledger in `docs/roadmap-2026-q2.md` |
| aimode-toggle spec | Done v1.0 | All OQs resolved; OQ3 accepted interim |

---

## What Remains

- [ ] Confirm that disabling unused tools in `opencode.json` (`false`) actually strips the schema from the preamble, not just denies the call — re-run the preamble capture to verify the token floor
- [ ] Align deploy-time warmup in `50-ai-stack.yml` — still pre-warms `gemma3:27b`, not Dewey's real pair (`qwen3-30b-instruct` + `qwen3-4b-instruct`). Depends on deciding whether gemma3 is still a real production surface or fully superseded by the Dewey pipeline
- [ ] Beelink GPU utilization metric in Grafana — the Vulkan wedge is detectable (GPU at 0% under load) but only if the metric is being scraped; the visibility gap is still open
- [ ] Design network-wide SSO holistically before deploying any forward-auth — must cover *arr, Pi-hole, and Jellyfin native auth, not just new services
- [ ] Evaluate `aimode bigctx` (30B@64k) only if a genuinely cross-cutting spec requires it — requires `opencode limit.context → 64k` change; deliberately NOT built yet per benchmark data

---

## Related Documentation

- `docs/research/local-coding-agent-sdd.md` — full SDD research log, §12 context budget benchmark, §13 resolved state
- `docs/beelink-ai-stack.md` — aimode flip timings, per-model heat-up, Vulkan wedge runbook
- `docs/roadmap-2026-q2.md` — SSO track with interim auth ledger
- `specs/aimode-toggle/spec.md` — Done v1.0, OQ3 resolution, full EARS criteria
- `.claude/skills/coding-agent-ops/SKILL.md` — operating runbook for the qwen/opencode agent
- `docs/recaps/2026-05-21-q8-coder-agent-comparison.md` — two-tier model strategy validated by benchmark
- `docs/recaps/2026-05-22-dewey-rag-rebuild.md` — Dewey model pair that aimode now correctly warms
