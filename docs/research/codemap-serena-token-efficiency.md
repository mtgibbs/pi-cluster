# Codemap, Serena & the Knowledge Cloud — Token Efficiency for the Local Coding Agent

**Date:** 2026-07-10
**Status:** Research complete — recommendation pending local dogfood test
**Method:** Deep-research workflow (103 agents: 5-angle search fan-out → 15-source fetch → 3-vote adversarial claim verification → synthesis). Claims below carry their verification votes.
**Related:** `local-coding-agent-sdd.md` (the qwen/opencode harness this is meant to serve)

## Question

Can Serena (LSP-backed MCP symbol tools) or "codemap"-style repo maps reduce token
consumption for qwen3-coder 30B/Q8 (32k context, opencode, Beelink)? And can an
Obsidian-style knowledge graph over this repo double as a retrieval index so a
local model fetches nodes instead of reading whole docs?

## TL;DR

**Yes on token savings — but via the passive repo-map pattern, not Serena's rich
toolset.** The two families attack the problem from opposite directions:

- **Serena** replaces file-reading with ~20 LSP symbol tools the model must
  actively drive (`find_symbol`, `replace_symbol_body`, …).
- **Repo-map tools** (Aider's design, RepoMapper, JordanCoin/codemap,
  kcosr/codemap) pre-compute a compact structural map under an explicit token
  budget (~1–2k tokens) that the model uses as a navigation index to request
  only what it needs.

The best available evidence on weak models cuts **against** instruction-heavy
toolsets and **for** fixed-cost passive maps at our context size. And critically:
**no tool in either family publishes a single measured token-savings number** —
every efficiency claim in the space is qualitative. Whatever we adopt, we have to
measure locally.

## Key Findings (verified)

### 1. Serena: real mechanism, unquantified benefit, zero small-model evidence

- MCP server wrapping LSP backends; symbol-granularity retrieval and editing
  across 40+ languages; opencode integration is trivial (remote SSE server in
  `opencode.jsonc`). Per-project memory store included. *(3-0)*
- Its token-efficiency claim is one qualitative README sentence; no measurements
  anywhere. *(3-0)*
- No first-party statement about minimum model capability. All cited experience
  is frontier models (Claude Opus 4.6, GPT 5.4). Qwen3-Coder CLI and opencode
  appear only as generic client listings. *(2-1)*
- Ops gotchas: must configure ignores (node_modules = 80k+ files pollutes the
  index); `--project-from-cwd` breaks in Docker.

### 2. The weak-model evidence favors simpler tooling (strongest data in the space)

From Aider's docs + leaderboard + quantization benchmark *(3-0, 2-1, 3-0)*:

- **~25k tokens**: above this, most models get distracted and follow their system
  prompt less reliably. Directly binding for our 32k `OLLAMA_CONTEXT_LENGTH` —
  we have almost no headroom for tool-schema bloat. (Practitioner heuristic, not
  a controlled study; independently corroborated by Chroma's 2025 "Context Rot".)
- **Weaker models disobey instruction-heavy formats**: Qwen2.5-Coder-32B hit
  71.6% correct-edit-format vs 98–99% for frontier models on Aider's leaderboard.
- **Quantization matters, but mostly at Q4**: Qwen2.5-Coder-32B scored 71.4%
  (BF16) vs 53.4% (q4_K_M); degradation at Q8 is near-negligible. This
  independently corroborates our own Q8-beats-30B-for-agentic-ops finding
  (2026-05-21 recap) — **prefer the Q8 variant for any tool-heavy work**, and
  check what quant the 30B default pull actually is.
- Aider's own mitigation for weak models is *simpler* interfaces (whole-file
  edits, architect mode splitting propose/apply) — not richer toolsets.

Caveat: this is indirect evidence (edit-format compliance ≠ MCP symbol-tool use),
and the "just barely capable" language is early-2025 vintage — 2026-era 30B coders
are better than it suggests. Nobody has published a 30B-model-drives-Serena test.

### 3. The "codemap" landscape (two distinct projects share the name!)

| Tool | Mechanism | MCP? | Notes |
| :--- | :--- | :--- | :--- |
| **Aider repo map** (canonical design) | tree-sitter AST → PageRank over file-dependency graph → token-budgeted map (default 1k) | n/a (built into aider) | The model uses the map to decide which files to request — navigation index, not content dump *(3-0)* |
| **RepoMapper** (pdavis68) | Aider-derived port (NOT clean-room — provenance claim refuted 1-2): tree-sitter + PageRank + binary-search to budget | ✅ stdio, **one tool** (`repo_map(project_root)`) | Simplest possible surface for a weak model; small personal project, not battle-tested *(3-0 mechanics)* |
| **JordanCoin/codemap** | Go CLI, ast-grep dependency-flow analysis, 18 langs | ✅ built-in `codemap mcp` (analysis + handoff + skills tools) | 637★, v4.1.10 (2026-07-02), active; compact handoff stubs designed for low context cost; no benchmarks *(3-0)* |
| **kcosr/codemap** | tree-sitter map incl. **markdown headings/code blocks**; `--budget` auto-degrades detail across 5 levels | ❌ none (verified by full-repo grep) | Only mapper that understands markdown structure — relevant for our docs-heavy repo; prompt-injection integration only; ~40★, last push 2026-01-29 *(3-0)* |

### 4. Knowledge cloud: the pattern is proven, the off-the-shelf tool isn't headless

- **cyanheads/obsidian-mcp-server** (v3.2.9) demonstrates exactly the retrieval
  pattern we want: `obsidian_get_note` returns a **document-map** (catalog of
  headings/blocks/frontmatter) or a **single section** — fetch the map, then just
  the relevant node. BM25-ranked search included. *(3-0)*
- But it is **not headless**: it proxies Obsidian's Local REST API plugin and
  needs a running Obsidian instance. Over a bare GitOps repo it only works if the
  repo is opened as a vault on an always-on machine. Alternatives noted by
  verifiers: filesystem-direct markdown MCPs (e.g. Piotr1215/mcp-obsidian), and
  Obsidian's official CLI (v1.12.0, Feb 2026) may enable headless paths soon.
- **Local grounding**: this repo has 156 markdown docs + 248 manifests but only
  **9 explicit md→md links**. An Obsidian-style graph of *existing* links would
  be nearly empty — the value is in **extracting implicit edges** (prose mentions
  of recaps/docs, doc↔manifest references, manifest↔manifest namespace/name
  relations) into an index. That's a build, not an install.

## Recommendation (synthesis — medium confidence, needs local measurement)

1. **Don't lead with Serena** for qwen. Its ~20-tool schema surface eats scarce
   context before work starts, weak-model evidence argues against
   instruction-heavy tooling, and its value is concentrated in symbol-level
   editing of polyglot *code* — this repo is dominated by YAML and markdown where
   LSP adds little. Revisit for the TypeScript/Python corners (family-board,
   pi-cluster-mcp) where symbols actually exist.
2. **Adopt the passive repo-map pattern**: a 1–2k-token budgeted map injected
   into the qwen session (or exposed as a single MCP tool via RepoMapper /
   JordanCoin/codemap). Fixed, predictable cost; no tool-use skill required to
   benefit.
3. **Dogfood test to settle it** (nothing published answers this): same SDD task
   run three ways — baseline vs. repo-map vs. Serena — measuring total tokens and
   task success. Also measure opencode's per-MCP-server schema overhead at 32k.
4. **Knowledge cloud = build the index over the repo directly** (headless),
   rather than adopting the Obsidian-runtime dependency. kcosr/codemap's markdown
   structure mapping could be the doc layer; manifest edges need custom
   extraction. The document-map → section retrieval pattern from
   obsidian-mcp-server is the interface to imitate.

## First Local Measurements (2026-07-10, token-bench v1)

`scripts/token-bench/` ran the 8-question repo-navigation bench, 3 reps × 2 arms,
qwen3-coder via `hot-coder` (48 trials, `results/results.jsonl`):

| | pass | in (med) | cache-read (med) | out (med) | ctx=in+cache (mean) | dur (med) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **A baseline** | 24/24 | 2,129 | 42,527 | 149 | 47,128 | 18s |
| **B repo-map** | 25/25 | 1,502 | 32,946 | 80 | 41,775 | 16s |

Takeaways:
1. **No accuracy gap on single-hop questions** — qwen with grep alone went 24/24.
   The model was never the bottleneck at this difficulty; harder multi-hop
   questions (or edit tasks) are needed to differentiate quality.
2. **The map pays for itself**: arm B carries a ~2k-token map yet still lands
   ~30% lower fresh-input, ~23% lower cumulative cache traffic (fewer tool
   round-trips), and ~46% lower output. Modest, real, not transformative.
3. **Prefix caching makes a static map nearly free after first use** (identical
   map prefix cache-hits across runs — q2/B repeats cost 4 input tokens total).
   Operationally this favors injecting one *stable* map over dynamic context.
4. A cold-cache smoke trial showed a 4× input gap (18.6k vs 4.4k) — cache state
   dominates single-trial comparisons; only aggregate reps are meaningful.
5. Ops gotcha: opencode (a Bun binary) leaks a ~5.4MB `.so` into `/tmp` per
   headless run — 48 trials filled the harness container's 256M tmpfs. The
   bench now sweeps the litter per-trial; long-lived harness containers should
   watch for it generally.

### Multi-hop round (same day, `questions-multihop.jsonl` m1-m8)

8 chain-traversal questions (secret chains, Flux dependsOn, image-automation,
backup-target triage) — answer literal and question keywords verified to live in
different files; `grade[]` requires all regexes so endpoint guessing fails:

| | pass | in (med) | cache (med) | out (med) | ctx (mean) | dur (med) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| A single-hop | 24/24 | 2,129 | 42,527 | 149 | 47,128 | 18s |
| B single-hop | 25/25 | 1,502 | 32,946 | 80 | 41,775 | 16s |
| **A multi-hop** | **25/25** | 3,063 | 43,376 | 252 | 54,938 | 24s |
| **B multi-hop** | **24/24**\* | 2,933 | 49,666 | 206 | 54,046 | 24s |

\* recorded 23/24; the one FAIL was a **grader false-negative** (model answered
"item `pihole`, field `api-key`" correctly; the v1 grade demanded the slash
literal). Grade fixed to a proximity regex; lesson: grade on *content proximity*,
never on answer formatting.

Takeaways:
1. **No accuracy gap, even multi-hop — a valuable negative result.** qwen3-coder
   went effectively 49/49 on chain traversal with or without the map. The
   2025-era "weak models flail at navigation" lore does not apply to read-side
   work on a repo this size. Multi-hop cost shows up as tokens (ctx 55k vs 47k
   single-hop, +40% output, +33% wall), not as errors.
2. **The map's token savings evaporate at multi-hop** (ctx 54.0k vs 54.9k — a
   wash). Expected in hindsight: the map encodes *structure* (which files exist,
   what kinds they hold), but chains are *references* (secretName → ExternalSecret
   → 1P item), which the map doesn't carry. Each hop still costs search-read
   round trips.
3. **This is the measurable case for the knowledge-cloud indexer**: an edge
   index (secretName refs, dependsOn, $imagepolicy annotations, doc mentions)
   is exactly what would shortcut hops. Concrete target for that build: beat
   arm A's ~55k mean ctx on the m-set while holding 100% pass.

### Knowledge-cloud edge index round (same day, `gen-edges.mjs`, arm G)

Built the edge index (695 edges: secretName, 1P remoteRef, PVC claims, svc
calls, Flux dependsOn, $imagepolicy, NFS, backup lists, doc mentions; `--json`
emits the full graph for the future viz). Three variants on the m-set:

| multi-hop arm | pass | ctx (mean) | dur (med) |
| :--- | :--- | :--- | :--- |
| A baseline | 25/25 | 54,938 | 24s |
| B repo-map | 26/27\* | 53,977 | 24s |
| G v1: edges by filename | 22/25 | 49,606 | 25s |
| **G v2: + (Kind/name) per doc** | **23/24** | **38,614** | 48s |
| G v2i: v2 + "verify before answering" instruction | 23/24 | 50,142 | 53s |

Verdict — **the edge index works, and the data fix was the lever, not the
instruction**:
1. **v2 hit the target minus one question**: −30% ctx vs baseline at 23/24.
   Cache traffic median halved (23k vs 43k) — genuinely fewer round trips.
2. **v1's failure mode is the field note that matters**: with edges labeled
   only by filename, the model answered m4 with the *filename* off the sheet
   (`backup-cronjob`) instead of the resource's metadata name (`pvc-backup`),
   and even cited the index's invented vocabulary ("the `backs_up` annotation")
   as if it were repo content — the index became an authority to cite, not a
   pointer to verify. Worse, the injected instruction *told it to* ("follow
   chains directly instead of opening each link"). m4 by variant: v1 0/3,
   v2 2/3, v2i 2/3.
3. **The "verify literals in the source" instruction (v2i) bought nothing and
   cost everything**: same 23/24, m4 still 2/3, and ctx gave back the entire
   v2 saving (+30%) to verification reads. For this executor, putting correct
   identities IN the data beats telling the model to double-check — consistent
   with the SDD lesson that the fixture carries the rigor, not the model.
4. Residual m4 miss both v2 variants: filename still sometimes outranks the
   `(Kind/name)` label. Future tweak: lead lines with the resource identity,
   file path second.
5. Wall time roughly doubles under G on multi-hop (24s→48s median) even as
   tokens drop — big uncached index prefills are slow on the Beelink and some
   idle-kill races inflate durations (8 rows needed token backfill from the
   session DB; `backfill-tokens.mjs`). Token counts are the reliable metric;
   wall time on a shared GPU is noisy.

### Generalization round: mtgibbs.xyz (2026-07-10 evening, `questions-site.jsonl`)

Same ladder on an unfamiliar TypeScript/Next.js codebase (55 source files, never
seen by this harness before). Tooling generalized first: repo-map describes TS
exported symbols; edge index extracts the **import graph** (incl. barrel
re-exports) + internal `/api/` fetches, identity = exported symbols. Took THREE
rounds to get valid data — rounds 1-2 (181 trials) quarantined after a
session-directory audit showed opencode roots its project from **$PWD, not
process cwd** (fix + audit now built into run-bench; full gotcha in
`coding-agent-ops/SKILL.md`). Round 3: audit 0/90 wrong-rooted.

| mtgibbs.xyz | pass | ctx (mean) | dur (med) |
| :--- | :--- | :--- | :--- |
| A baseline · single | 12/12 | 41,395 | 15s |
| A baseline · multi | 18/18 | **80,529** | 30s |
| B repo-map · single | 12/12 | 20,513 | 10s |
| B repo-map · multi | 17/18 | 43,642 | 15s |
| **G map+edges · single** | **12/12** | **21,720** | 12s |
| **G map+edges · multi** | **18/18** | **35,650** | 16s |

Findings:
1. **The benefit GROWS with unfamiliarity.** On home turf (pi-cluster) the edge
   index saved 30%; on a codebase the model had never seen it saved **56% on
   multi-hop (80.5k → 35.7k) and 48% on single-hop**, at half the wall time,
   with zero accuracy loss (G 30/30). Baseline stayed accurate but paid ~2×
   pi-cluster's cost per chain — unfamiliarity taxes tokens, and the index
   refunds it.
2. **Import edges cured the barrel-file chain** (ms5: B failed it, G 3/3 — the
   `data/index.ts -> import:project-*.constants` lines ARE the answer). The
   only failure in 90 trials was map-only B on that same question.
3. **Blind-arm resilience (from the quarantined rounds, replicated 2×):** when
   the model couldn't read files at all, G still ranked first and map-only B
   ranked BELOW baseline — an edge index contains answers and degrades
   gracefully; a bare map offers confidence without substance. Corroborates the
   v1 authority-citing failure from the pi-cluster rounds.
4. **Methodology lesson: audit provenance, don't trust green PASSes.** Two
   plausible-looking datasets died on a `session.directory` join. The audit is
   now part of the run command.

### Symbol-graph round: component composition (2026-07-11, arm S, `gen-symbols.mjs`)

The next granularity down: G's edge index knows *file→file* imports; arm S
replaces it with a **symbol-level component graph** — which component renders
which (`Component<-defining/file`), context Provider mounts vs consumers,
custom-hook origins resolved through barrels, props-type `extends` chains,
per-symbol imports, and unexported local symbols. ~2.1k tokens for the whole
site (vs ~1.2k for G's edge index). New question set
(`questions-site-components.jsonl`, c1-c9) targets composition: render fan-in,
fan-out enumeration, provider-vs-consumer, props inheritance, barrel-resolved
hook origin, transitive render chains, local-hook identity. 111 trials, audit
0/111 wrong-rooted.

| mtgibbs.xyz | pass | ctx (mean) | dur (med) |
| :--- | :--- | :--- | :--- |
| A baseline · comp | 25/27 | 45,950 | 19s |
| G map+edges · comp | 26/27 | 28,108 | 13s |
| **S map+symbols · comp** | **27/27** | **26,173** | 14s |
| A baseline · multi (prior round) | 18/18 | 80,529 | 30s |
| G map+edges · multi (prior round) | 18/18 | 35,650 | 16s |
| **S map+symbols · multi** | **18/18** | **25,762** | 12s |
| S map+symbols · single | 12/12 | 24,779 | 12s |

Findings:
1. **The site bench finally produced real accuracy failures, and they're
   composition-shaped.** Baseline failed c1 (fan-in: "which two files render
   SectionTitle?") 1/3 — it grepped, got all 10 matches, and still reported
   the definition file instead of the second renderer. G failed c8 1/3: the
   unexported `useLiveCatalog` hook lives *inside* StarChart.tsx and never
   crosses a file boundary, so a file-level import index is structurally blind
   to it. S carries both answers on the sheet and went 27/27 — plus 30/30 on
   the prior round's s/ms sets (57/57 overall).
2. **Symbol edges beat file edges on the original multi-hop set too: −28% ctx
   vs G (35.7k → 25.8k), −68% vs baseline (80.5k).** In hindsight the ms
   questions were always symbol questions (context consumers, barrel
   constants) — G answered them by opening the files its edges pointed at; S
   answers most hops from the sheet and spends one read verifying. S's median
   cache-read is flat ~17.5k across all tiers — the sheet, the map, and one
   verification read is the whole workload.
3. **The bigger sheet has a real cost on single-hop lookups**: S 24.8k vs G
   21.7k / B 20.5k ctx (+14% vs G). "Where is X?" questions are answered by
   the repo map alone; the extra ~900 tokens of symbol edges ride along
   unused. Same story on fan-out enumeration (c9: baseline's single grep was
   the *cheapest* correct strategy, 28.5k vs S's 35.5k).
4. **Layer selection, not layer stacking, is the emerging design**: map for
   location, symbol graph for code composition, edge index for cross-domain
   references (secrets/PVCs/Flux — things symbols don't cover). Stacking all
   three pays two prefixes everywhere; the right index per question class is
   strictly better. A future "arm GS" (edges for manifests + symbols for code,
   one merged sheet) is the obvious pi-cluster test, where YAML dominates and
   the two indexes don't overlap.

### Serena round: arm C head-to-head (2026-07-11 evening, uv baked into harness image)

Serena v1.5.3 registered per-trial via `OPENCODE_CONFIG` (merges with global
config — identical environment to other arms plus serena), ide-assistant
context, read-only project seed, symbol-tool hint in the prompt. 57 trials +
1 discarded warm-up; audit 0/57 wrong-rooted, zero idle-kills.

| mtgibbs.xyz | pass | ctx (mean) | dur (med) |
| :--- | :--- | :--- | :--- |
| **C serena · comp** | **27/27** | 73,439 | 24s |
| **C serena · multi** | **18/18** | 115,648 | 35s |
| **C serena · single** | **12/12** | 67,941 | 22s |
| S map+symbols · comp | 27/27 | 26,173 | 14s |
| S map+symbols · multi | 18/18 | 25,762 | 12s |
| A baseline · multi | 18/18 | 80,529 | 30s |

Verdict — **both open questions answered, and the recommendation stands**:
1. **qwen3-coder CAN drive serena — the 2025 weak-model lore is refuted on
   accuracy.** 57/57 including every chain question, zero tool-use failures
   in ~250 tool calls. The capability concern that shaped the original
   recommendation is dead; the *cost* concern is not.
2. **Serena costs 2.8–4.5× arm S's context for identical accuracy** — and on
   multi-hop (115.6k vs baseline's 80.5k) it is more expensive than *no
   tooling at all*. Symbol tools replace grep round-trips with symbol
   round-trips, but every request re-carries ~20 tool schemas plus the
   accumulated tool transcript; the sheet arms answer from a one-shot prefix
   the cache makes nearly free. Worst case ms5 (barrel chain): 186k cache /
   119s for one answer arm S delivers at ~36k / 16s.
3. **The schema tax is visible in the floor**: serena's cheapest single-hop
   trials still occupy ~62k cumulative cache vs 17.5k for S — a ~3.5×
   standing overhead before any navigation happens. Wall time ~2× across all
   tiers (tool latency + bigger prefills on the Beelink).
4. Where serena would still win: **symbol-level *editing*** (rename,
   replace_symbol_body) and polyglot repos where a generator like
   gen-symbols.mjs doesn't exist — neither is exercised by a read-side Q&A
   bench. For navigation on our stack, the passive sheet is strictly better:
   same accuracy, ¼ the tokens, ½ the wall time, no python/uv dependency at
   inference time.

### Merged-sheet (GS) null test on pi-cluster (2026-07-11 late)

Arm GS = map + edge index + symbol graph stacked. Running it on pi-cluster
surfaced a structural fact first: **this repo has no symbol graph.** Family
Board is a single-file `index.html` app, the n8n `src/*.js` are standalone
Code-node snippets composed by workflow JSON (zero imports between them), and
the bench scripts are self-contained — pi-cluster's composition lives
entirely in YAML. gen-symbols.mjs correctly emits a ~142-token near-empty
sheet. So the GS round became a null test: does stacking an empty layer hurt?

| m-set, pi-cluster | pass | ctx (med) | ctx (mean) | notes |
| :--- | :--- | :--- | :--- | :--- |
| G v2 (2026-07-10) | 23/24 | 23,189 | 38,614 | |
| **G recheck (same night as GS)** | 23/24 | 47,427 | 43,568 | |
| **GS (same night)** | 23/24 | 48,022 | 61,424 | mean inflated by one 273k outlier |

1. **Null test PASSES**: same-night GS ≈ G (median 48.0k vs 47.4k, identical
   23/24 with the same flaky-m4 residual, 47/48 across both GS sets). The
   empty symbol layer costs its 142 tokens and nothing else — the merged
   sheet is safe to inject unconditionally; layer relevance falls out of the
   data, not config.
2. **Methodology lesson worth the round it cost**: tonight's *G alone* also
   ran ~2× yesterday's median (47.4k vs 23.2k — two round trips where
   yesterday took one, at half the wall time per trip). First read looked
   like "the empty block causes verification reads"; the G recheck proved it
   environmental (hot-coder is aimode-following 30B/Q8, plus Beelink cache
   regime). **Cross-day absolute numbers are invalid; only same-window arm
   pairs count.** The site rounds (A/B/G/S/C) all ran same-window and are
   unaffected.
3. Watch item: one GS trial (m7) thrashed to 273k ctx / 234s before
   answering correctly — sheet arms are not immune to occasional tool loops;
   medians over means for this bench.

## Open Questions

1. ~~Does qwen3-coder Q8 actually drive symbol tools productively?~~
   **ANSWERED 2026-07-11 (arm C): yes on accuracy (57/57), no on economics
   (2.8–4.5× arm S's context, 2× wall).** Untested remainder: symbol-level
   *editing* tools on real SDD tasks.
2. How do repo-map tools handle k8s YAML/Kustomizations? All evaluated mappers
   are code-symbol oriented; none verified on manifest-heavy repos — most of
   this one. (Our own gen-edges covers it; the question is now moot for
   adoption, open only as a market observation.)
3. Can Obsidian's official CLI enable truly headless section-level retrieval?
4. ~~What is opencode's real token overhead per registered MCP server at
   32k?~~ **MEASURED via arm C floor: serena's registration costs ~3.5×
   standing cache occupancy on trivial questions (62k vs 17.5k) — schemas +
   tool transcript ride in every request.**
5. ~~Merged GS sheet on pi-cluster~~ **ANSWERED (null test): GS ≈ G when the
   symbol layer is empty — safe to stack unconditionally.** The positive case
   (a repo with BOTH manifests and real code, e.g. pi-cluster-mcp) remains
   untested; pi-cluster itself turned out to have no symbol graph.

## Refuted During Verification

- "RepoMapper shares no code with Aider" — false; its tree-sitter query files are
  byte-identical to Aider's. Treat it as an Aider-derived port (license/provenance
  awareness).

## Primary Sources

- https://github.com/oraios/serena (v1.5.3, 26.3k★)
- https://aider.chat/docs/repomap.html + /2023/10/22/repomap.html
- https://aider.chat/docs/troubleshooting/edit-errors.html + /2024/11/21/quantization.html + /docs/leaderboards/
- https://github.com/JordanCoin/codemap (v4.1.10)
- https://github.com/kcosr/codemap
- https://github.com/pdavis68/RepoMapper
- https://github.com/cyanheads/obsidian-mcp-server (v3.2.9)
