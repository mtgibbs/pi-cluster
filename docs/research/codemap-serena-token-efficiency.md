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

## Open Questions

1. Does qwen3-coder Q8 actually drive symbol tools productively? (Dogfood test.)
2. How do repo-map tools handle k8s YAML/Kustomizations? All evaluated mappers
   are code-symbol oriented; none verified on manifest-heavy repos — most of
   this one.
3. Can Obsidian's official CLI enable truly headless section-level retrieval?
4. What is opencode's real token overhead per registered MCP server at 32k —
   Serena's ~20 schemas vs RepoMapper's one?

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
