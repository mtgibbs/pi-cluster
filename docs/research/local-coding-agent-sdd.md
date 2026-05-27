# Research: Local Coding Agent + Spec-Driven Development

> **Living research log.** Captures what we learned standing up qwen3-coder as an executing
> coding agent under Claude orchestration, using spec-driven development (SDD). Started
> 2026-05-23. This exists so the findings survive context compaction — reference it while
> deciding the open questions in §10.

## 1. Why this exists (TL;DR)

Build a **Claude-independent local coding capability** for the homelab — qwen3-coder on the
Beelink, driven via a provider-agnostic harness, orchestrated by Claude. Motivations:
**digital homesteading** (own the tools, privacy, no vendor lock-in), **resilience** (works if
we lose Claude), and **cost/ToS** (see §3 — automated agent loops on the Claude subscription
are now capped/metered/ToS-restricted, local is free + clean).

**State:** harness wired + proven; SDD practice built + battle-tested on one real feature
(homepage refresh, shipped); the agentic loop has known failure modes (§5–§7) and open
operational decisions (§10). The *model* is not the weak link — the *fixture around it* is the work.

## 2. Architecture

- **Harness:** `opencode` 1.15.6 (Homebrew). Chosen over goose (provider-agnostic, both
  headless) and Claude Code (Claude-only — can't run qwen) for: project-scoped `opencode.json`,
  `AGENTS.md` auto-load, Plan/Build modes, momentum. goose is the fallback brain-swapper.
- **Brain:** `qwen3-coder-30b` on the Beelink, reached via LiteLLM `https://ai.lab.mtgibbs.dev/v1`
  with a scoped virtual key (`op://pi-cluster/opencode-coder`).
- **Launcher:** `scripts/oc` (→ `~/.local/bin/oc`) — pulls the key from 1Password at startup
  (one biometric), puts it only in opencode's process env, adds a **watchdog timeout** on
  `oc run` (`OC_RUN_TIMEOUT`, default 600s). Interactive TUI untimed.
- **Division of labor:** **Claude (this session) orchestrates** — writes specs, builds verify
  harnesses, reviews diffs. **opencode+qwen executes** — reads/edits files, runs commands.
  opencode is *only* ever pointed at qwen, never Claude (see §3).
- **Config:** `opencode.json` pins `instructions: ["AGENTS.md"]` (lean, qwen-sized context —
  NOT the full `CLAUDE.md`). Verified: qwen's context shows only AGENTS.md, no CLAUDE.md bleed.

## 3. Economics (why local, not Claude-via-opencode)

Anthropic's 2026 billing changes make automated Claude agent loops expensive/restricted:

- `ANTHROPIC_API_KEY` set ⇒ metered pay-per-token (separate from the subscription), even in Claude Code.
- **Apr 4 2026:** subscription coverage for third-party tools (opencode etc.) killed, then reinstated "with a catch."
- **Jun 15 2026:** subscription splits — a first-party pool (interactive chat + Claude Code) vs
  a capped **Agent SDK credit** pool ($20 Pro / $100 Max-5x / $200 Max-20x) covering
  third-party agents **and `claude -p`**.
- ToS **prohibits** subscription use for scripted/automated/CI work → automation must use API.

**Conclusion:** interactive Claude Code = subscription cockpit (keep). Automated/looped coding
= **free local qwen** (no metering, no cap, ToS-clean). **Never run Claude through opencode**
(metered + capped + ToS-risky). Sources: Claude help center, VentureBeat (subscription reinstatement),
the Jun-15 split coverage.

## 4. The SDD practice (artifacts)

The spec is the executable artifact; code is regenerable output. Layered, all in `specs/`:

| Layer | Artifact | Role |
|---|---|---|
| Constitution | `specs/constitution.md` | non-negotiables + house architecture (Tier-1 context, generic) |
| Design/taste | `specs/design-principles.md` | house style — the taste layer (see §6 taste gap) |
| Template | `specs/TEMPLATE.md` | required spec skeleton (outcomes, scope, EARS criteria, verify, loop notes) |
| Spec | `specs/<feature>/spec.md` | per-feature: §7 EARS acceptance criteria, §10 plan, §11 tuning log |
| Gate | `specs/<feature>/verify.sh` | §7 compiled to a **deterministic** static gate (exit 0 = acceptable) |
| Loop | `scripts/ralph-qwen.sh` | one-task-per-iteration, fresh context, watchdog, verify-gate, retry-with-feedback |

**Context budget (key principle):** Tier-1 context is **sized to the model**. qwen (~32k window)
gets the lean `AGENTS.md`; Claude gets full `CLAUDE.md` + on-demand `ARCHITECTURE.md`. You can't
ship `ARCHITECTURE.md` (~2,500 lines) to a local model. Curation is the skill.

**Canon referenced:** Sean Grove (OpenAI) "spec is the artifact"; Geoffrey Huntley (Ralph loop);
Harper Reed (spec→plan→execute); Alistair Mavin (EARS); GitHub Spec Kit; Mitchell Hashimoto
(harness engineering: build the validation the agent self-checks against).

## 5. The two evals — generation quality ≠ agentic stamina

**Round 1 — controlled generation** (Claude calls qwen via LiteLLM, one-shot, produces the file):
clean, complete, **85s**, ~7/9 acceptance criteria first try. Two misses — Beelink customapi
field path + an invented Grafana URL — **both spec gaps, not model error**. Tuning the spec
(worked example + literal URL) → re-run fixed both. **Specificity is the lever.**

**Round 2 — agentic** (opencode+qwen edits files itself, in a worktree): tool calls were
**faithful and correct** (the tuned lessons held), but the session **stalled for ~2 hours** on
one streaming request and never finished T2. GPU/model/streaming all verified **healthy**
(qwen replied 0.2s non-stream, 0.1s streamed) — the hang was an **un-timed-out agentic session**,
not hardware.

> **Core finding:** the local model's *generation* is strong; its *agentic stamina, judgment,
> and self-checking* are weak. SDD leans on the first; the harness must compensate for the second.
> One-shot controlled generation is reliable; open-ended agentic autonomy is not (yet).

## 6. What qwen asks for (request anatomy) — captured from opencode's DB

Per turn, opencode sends qwen: **system prompt** (opencode instructions + our `AGENTS.md`) +
**the ~10-tool JSON schema** (`bash, read, write, edit, glob, grep, list, webfetch, todowrite,
task, skill`) + **the entire conversation so far** + `stream=true`. The preamble + tool schema
are **re-sent in full every turn** — fixed overhead; history is the part that grows.

From the homepage run's opencode SQLite DB (`~/.local/share/opencode/opencode.db`):
- qwen made **13 tool calls** — all sensible (`read` spec → `glob`+`read` neighbors → 4× `edit`
  configmap). Faithful exploration + targeted edits.
- **Context grew 9k → 26k tokens**, then opencode **auto-compacted** (`{"type":"compaction",
  "auto":true,"overflow":false}`) — proactively summarized history (the 26k→5k drop). Compaction
  is **lossy** (summarizes earlier turns) → quality-drift risk on long runs + an extra LLM call.
  **This validates `ralph-qwen.sh`'s fresh-context-per-task:** lossless by design, sidesteps compaction.
- **The hang is visible in the DB:** 20 `step-start`s, 19 `step-finish`es — one **orphaned step**
  = the streaming request that never returned. opencode's `step-start`/`step-finish` events are a
  natural **heartbeat** for a smarter watchdog (a step with no finish in N min = stalled).
- **Not in the DB:** the verbatim system prompt + tool JSON (assembled at request time). Capturing
  the literal preamble needs a one-shot logging proxy between opencode and LiteLLM (open todo, §10).

## 7. Model behavior characterization

qwen3-coder-30b as an executor = a **fast, faithful, literal stamper**:
- ✅ Nails anything **explicitly specified** (URLs, ports, keys, the tuned lessons, EARS rules).
- ✅ **Reuses existing patterns** (pattern-matches the codebase) — *but* sometimes copies the
  *wrong* nearby example (it copied the Loki `customapi` style over the spec's field path).
- ❌ **No taste** on the unspecified (reused `mdi-memory` ×3 for distinct metrics).
- ❌ **No self-verification** (never ran §8; left the AI group half-built, then hung).
- ❌ **Amplifies spec bugs** — executed our wrong `round(100*)` percent example verbatim ("6100%").
- ❌ **No stamina** — open-ended sessions stall; needs bounded scope + a watchdog.

> Mental model: **qwen is the stamper; `verify.sh` is the inspector; `ralph-qwen.sh` is the
> conveyor belt + jig; the human is QC on the line.** You don't make the stamper wise — you build
> a fixture precise enough that faithful-but-mindless stamping yields correct parts.

## 8. Process gaps surfaced (the survey)

| # | Gap | How it bit | Status |
|---|---|---|---|
| 1 | Spec correctness | percent ×100 → "6100%"; model executed the bug faithfully | ✅ banked: tested examples |
| 2 | Taste | 4 fat cards passed every check, looked dumb | ✅ banked: `design-principles.md` |
| 3 | Verification granularity | prowlarr — verified *item*, not *field* | ✅ banked: verify the exact thing |
| 4 | Agentic stamina | 2h silent hang | ✅ fixed: `oc` watchdog |
| 5 | Self-verification | qwen never self-checks | ✅ banked: `verify.sh` external/mandatory |
| 6 | **op friction** | blocked read/run/**ssh** ×6+ AND degraded rigor (caused #3) | ✅ **resolved 2026-05-23** — local device→tool creds (see below) |
| 7 | Spec/verify/config drift | design change forced 3 hand-edits, no link between them | ⚠️ unaddressed |
| 8 | Blind loops | only found the 2h hang when the user asked | ⚠️ partial — heartbeat idea (§6) not built |
| 9 | Skipped formal PR | merged to main on live review, vs the PR-gated principle | ⚠️ deviation noted |

**Through-line A — op friction is a *compounding* tax, not an annoyance.** It blocked `op read`,
`oc run`, and `ssh` (the 1Password SSH agent), AND when per-field reads flaked I downgraded to
item-level checks — **which is the root cause of the prowlarr gap (#3).** It's the keystone: every
other gap got banked; this one keeps generating new ones.

**Through-line B — static verification has a ceiling.** `verify.sh` can't see taste (#2), can't
guarantee live behavior, and a passing gate on a *wrong spec* (#1) is confidently wrong. The
human/visual review is irreplaceable; the discipline is to *shrink what it must catch*.

## 9. Concrete result (the dogfood)

**Homepage refresh** — first real feature built this way, **shipped to main + live**: arr status
widgets (sonarr/radarr/sabnzbd/bazarr, keys synced; lidarr/prowlarr link-only — no `api-key`
field in vault), **Beelink telemetry as one `prometheusmetric` perf card** (after a taste fix
from 4 ugly cards), new AI group, all 11 groups. qwen produced ~90% agentically; Claude finished
T2 + fixed the percent/encoding bugs in review. Relevant commits on `main` through `59366c1`.

## 10. Open decisions (PENDING — the user is deciding)

1. **op friction (#6, keystone): ✅ RESOLVED 2026-05-23.** Decision: the laptop↔Beelink-qwen
   link is a **device-to-tool** connection on a trusted machine (not a cluster credential), so
   its *working* creds live **locally** while **canonical copies stay in 1Password** for
   re-bootstrap. Implemented: (a) `oc` reads the LiteLLM/qwen key from the **macOS Keychain**
   (service `opencode-qwen`), 1Password fallback — no biometric on the agent hot path; (b) a
   private SSH key on disk (`~/.ssh/beelink-ai`, 0600) with `IdentityAgent none` for that host,
   bypassing the 1Password SSH agent. Crown-jewel / cluster-acting creds stay biometric.
   **Consequence to remember:** this enables *supervised* friction-free runs; truly unattended
   loops still need a persistent cred (these creds ARE persistent-but-local now, so unattended
   is technically possible — but gate it behind the loop's maturity + PR review, not just auth).
2. **Heartbeat watchdog:** upgrade `ralph-qwen.sh` / `oc` from a flat timeout to monitoring
   opencode's `step-start`/`step-finish` events (stall = a start with no finish in N min).
3. **Live preamble capture:** stand up a logging proxy to see the verbatim system prompt + tool
   JSON qwen receives (measure the fixed per-turn overhead; confirm AGENTS.md lands intact).
4. **PR-gate formalization (#9):** decide deliberately whether agent work goes through a real
   GitHub PR vs live-review-then-merge.
5. **Drift mitigation (#7):** how spec / `verify.sh` / live config stay in sync.
6. **Next qwen project:** a fresh, small, safe spec to shake down the *hardened* loop end-to-end
   (the decommission-carl-pi-ollama backlog spec is a candidate but destructive — maybe not first).

## 11. Key files

- `specs/README.md`, `specs/TEMPLATE.md`, `specs/constitution.md`, `specs/design-principles.md`
- `scripts/oc` (launcher + watchdog), `scripts/ralph-qwen.sh` (the loop)
- `specs/homepage-refresh/{spec.md, verify.sh}` (first worked example — note §11 tuning log)
- `opencode.json`, `AGENTS.md` (the qwen harness config + lean entry file)
- Memory: `project_local_coding_agent`, `user_digital_homesteading`, `feedback_agent_safety_pr_gated`

## 12. Context budget & the preamble (measured 2026-05-23/24)

An `oc` session opens with **~31% of qwen's 32k window already consumed** by the fixed
**preamble** that opencode re-sends EVERY turn. Captured via a one-shot logging proxy:

| Chunk | ~tokens |
|---|---|
| opencode system prompt (+ AGENTS.md + env) | ~3,988 |
| 9 tool schemas | ~5,924 |
| **Total preamble** | **~10,043 (≈31% of 32k)** |

Per-tool: `bash` 1,460 · `skill` 1,053 · `task` 917 · `todowrite` 682 · `edit` 498 ·
`read` 442 · `grep` 311 · `glob` 291 · `write` 262. **Tools are ~60% of the preamble; the
biggest *unused* ones — `skill`, `task`, `todowrite` (~2,650 tok combined) — are a free ~8%
reclaim.** (Note: `permission: deny` still *sends* the schema; you must **disable** the tool
to shrink the window.)

**The tension ("it'll die"):** preamble ~10k + elaborate spec (6–15k) + files (4–10k) +
accumulating history → overflows 32k → lossy auto-compaction → drift → stall. Elaborate specs
*will* kill a single long session. Two responses:

- **Path A — decompose harder (orchestrator iterates).** Claude atomizes the spec; each
  fresh-context iteration = preamble + ONE small task + ONE file ≈ 15–20k. Robust, fast.
  **KEY insight:** focused context is *quality-optimal*, not just a VRAM workaround —
  long-context attention degrades ("lost in the middle"), so a tight window reasons BETTER
  than a bloated one. This is the **default, regardless of limits.** Cost: more decomposition
  work for the orchestrator, more iterations, qwen never sees the whole picture (risk on
  cross-cutting changes).
- **Path B — more context (hold spec + code together).** The model supports far more than our
  32k cap (we capped it to protect the iGPU KV cache — documented gotcha). So it's a VRAM +
  latency question: `aimode work` (sole-tenant) frees VRAM; the catch is **prefill latency** on
  the bandwidth-bound iGPU. **Now measured (2026-05-24, see below)** — the three Path-B
  questions are answered.

### Measured: qwen3-coder:30b prefill/quality, 32k vs 64k (2026-05-24)

Probed sole-tenant via Ollama `/api/generate` (timing fields), 30B reloaded at `num_ctx=65536`
(31.9 GB VRAM — fits the 96 GB carveout fine; **Q8 at 64k would risk >96 GB, so NOT done**):

| Prompt tokens | Prefill tok/s | Wall |
|---|---|---|
| 403 | 778 | 0.5s |
| 5,734 | 635 | 9s |
| 15,615 | 331 | 47s |
| 28,615 | 194 | 148s |
| **57,991** | **99** | **583s (~9.7 min)** |

- **(a) Prefix caching: YES, dramatic.** Identical prompt, 2nd call: `4.15s → 0.02s` — the
  unchanged prefix is reused for ~free (flash-attention on, `keep_alive=-1`).
- **(b) Prefill latency: brutal & super-linear.** ~8× collapse (778→99 tok/s); a near-full 58k
  context = **~10 min** to prefill before the first token. A cache *miss* = that stall.
- **(c) Quality at depth: HELD.** A needle (`port 8443` / `svc-dewey-prober-x9`) at ~50% of a
  49k context was retrieved **exactly**. No lost-in-the-middle failure on retrieval. Big context
  is **not** quality-disqualified.

**Synthesis — DECIDED:** tier it. (1) Trimmed unused tools (`skill`/`task`/`todowrite`) — done.
(2) **Path A (decompose) is the default** — small fresh contexts are cheap to prefill *and* need
no cache to survive eviction; immune to both failure modes on the shared box; quality-optimal.
(3) **Path B is a deliberate escape hatch**, viable ONLY under `aimode work` sole-tenancy (protects
the cache slot) **and** a stable prefix — for the ~10% genuinely cross-cutting specs. Proven
usable (quality holds), but expensive on first prefill and fragile to eviction.
**"Loop with power" now has two flavors** (opencode follows `hot-coder`): **Q8 @ 32k** (smarter,
must decompose — the recommended power default) vs **30B @ 64k** (weaker judgment, holds a big
spec — niche, for "read whole spec + one file" one-shots, NOT iterative loops). Note: a 30B@64k
mode would also need opencode's `limit.context` raised to 64k (it caps at 32k today) — deliberately
NOT built, since the data says it's niche.

## 13. RESOLVED + current state (2026-05-24)

The context-budget question (§12) is **settled** — Path A is the default, Path B is a
sole-tenant escape hatch (full reasoning + measured data in §12).

**Shipped this session:**
- **Tools trimmed** — `opencode.json` `"tools": {skill,task,todowrite: false}`. (Reclaim
  unverified — opencode docs don't say if `false` strips the schema or just denies; confirm
  with a capture before banking the exact floor.)
- **opencode → `hot-coder`** — `opencode.json` model is now `beelink/hot-coder`, so `oc`/ralph
  **follow `aimode`**: 30B in family, Q8 in work. Toggle finally reaches the loop. (30B kept as
  `qwen3-coder-30b` pinned fallback. Both 32k.)
- **`aimode` bugs fixed** (`beelink-ansible/files/aimode.sh`, deployed): `warm()` used
  `docker exec ollama curl` but **the ollama image has no curl** → warm-ups were a silent
  no-op for the life of the toggle. Now uses `docker exec open-webui curl` (proven path). And
  the warm-set pointed at stale models (gemma3/qwen3.5) — corrected to Dewey's REAL pair
  (`qwen3-30b-instruct` + `qwen3-4b-instruct`, per `dewey-pipeline.py` defaults; verified via
  LiteLLM `/model/info` + container env, no `DEWEY_MODEL` override).

**Open follow-ups (not blocking):**
1. **Deploy-time warmup drift** — `50-ai-stack.yml` still pre-warms `gemma3:27b`, not Dewey's
   pair. Same bug class as aimode. Left as-is pending: is gemma3 still a real WebUI surface, or
   fully superseded by the Dewey pipeline? Decide, then align the warmup.
2. **Homepage `aimode` toggle** — surface `aimode status` + a flip button on the dashboard. Good
   bounded qwen dogfood (the "next qwen project").
3. **Verify the tool-trim reclaim** — re-run the preamble capture to confirm `false` actually
   strips schemas.
4. **`aimode bigctx` deliberately NOT built** — 30B@64k is niche per the benchmark; revisit only
   if a real cross-cutting spec needs it (would also require opencode `limit.context` → 64k).

## 14. External: SPDD (Martin Fowler) — what we adopt / reject (2026-05-27)

Source: Fowler, *Structured Prompt-Driven Development* — https://martinfowler.com/articles/structured-prompt-driven/
Independent of us, it formalizes most of our practice; it sharpens three open decisions and
hands us one concrete artifact. Their thesis: **prompts are first-class, version-controlled
delivery artifacts** — "the real question isn't 'How do we generate more code?' It's how do
we make AI-generated changes governable, reviewable, and reusable." That is our §4 premise.

### Confirms us
- **Spec-is-the-artifact, code is regenerable** — our Sean Grove framing, their core claim.
- **Model-agnostic spec / swappable executor** — they treat it as a *caution* ("prompt drift
  from ad hoc model swaps"); we made it a **hard law** (§3 economics: qwen-only executor, never
  Claude-through-opencode). The intent stays locked in the spec; the executor varies. We're ahead.
- **Functional-validation-first** (`/spdd-api-test`) ≈ our deterministic `verify.sh` gate (and
  ours is stronger — static, offline, loop-gating, not a human-run script).
- **"Context black holes"** (unclear domain tanks even strong models) = our §7 — and it bites our
  weaker local models *harder*, reinforcing "the fixture, not the model, is the work."

### Adopted
- **REASONS Canvas → `specs/TEMPLATE.md` (done).** Overlaid R-E-A-S-O-N-S on our template and
  added the dimensions we lacked: **Entities (E)**, **Approach (A)**, **Norms (N)**,
  **Safeguards (S)**. N+S are the cross-cutting + non-negotiable layers — exactly the
  "unspecified" space where qwen guessed badly (reused `mdi-memory` ×3; executed the wrong
  percent example). Now there's a home to pin taste rules and invariants, each Safeguard mapping
  to a `verify.sh` assertion where possible.
- **Two-way sync rule → `specs/TEMPLATE.md` (done).** "When reality diverges, fix the prompt
  first." Logic change → spec→regen; refactor → code→spec; hotfix → post-mortem back into spec +
  Tuning log. A Norms/taste fix made in review MUST be written back or it recurs. This is our
  drift-mitigation protocol (informs §10.5 / #7).

### Informs (but does NOT resolve — these are still the user's per §10)
- **§10.4 PR-gate / deviation #9.** Their sharpest warning is **"single-shot review
  compression"** — one late gate makes humans skim/defer/approve-by-default. Implication for us:
  the answer isn't "PR vs live-review," it's **two small gates** — (1) an **intent gate before
  execution** (Claude approves the spec/canvas pre-loop — cheap, automatable, keeps the Ralph
  loop's autonomy) plus (2) a **diff gate before merge** (human). Distributing the gate is the
  fix; it does not require adopting their human-heaviness.
- **§10.5 drift (#7).** The two-way sync rule above is the concrete protocol.

### Rejected / tension
- SPDD is **human-in-each-of-6-steps** (heavy, distributed pairing). Our Ralph loop targets
  **unattended** iteration with gates only at spec-in / PR-out. We borrow their **gate placement**
  (intent gate before code) but hold that early gate with **Claude, not a human** — autonomy
  preserved, rubber-stamp risk removed. We do not adopt their per-step human checkpoints.
- Their `openspdd` CLI (`/spdd-*` slash commands) is a tooling layer we don't need — our
  `ralph-qwen.sh` + `verify.sh` + Claude-orchestration already cover generation, validation,
  and the loop.
