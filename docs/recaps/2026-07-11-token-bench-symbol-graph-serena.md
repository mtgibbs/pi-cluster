# Recap — Symbol graph, serena, and the merged-sheet null test close the token-bench campaign (2026-07-11)

Direct continuation of yesterday's token-efficiency research (`docs/recaps/2026-07-10-token-efficiency-research-and-knowledge-cloud.md`).
Yesterday closed with a validated file-level edge index (arm G, -30% ctx) and two open questions:
can qwen3-coder actually drive serena, and does a symbol-level index beat a file-level one? Today
answered both, ran the merged-sheet (map + edges + symbols) case to a null result on pi-cluster and a
positive result on pi-cluster-mcp, and closed the campaign at 783 audited trials with production
guidance for the qwen harness.

---

## 1. Arm S: symbol-level component graph — the only perfect arm on the site

`gen-symbols.mjs` replaces G's file→file import edges with a **symbol-level component graph**:
component render fan-in/out, context Provider-vs-consumer, custom-hook origins resolved through
barrels, props-type `extends` chains, and unexported local symbols — ~2.1k tokens for the whole site
vs G's ~1.2k edge index. A new composition question set (`questions-site-components.jsonl`, c1-c9,
111 trials) finally produced real accuracy failures, and they were composition-shaped: baseline
grepped `SectionTitle`'s renderer and reported the wrong file (1/3 on fan-in), G went blind on a hook
that lives inside another component and never crosses a file boundary (1/3). Arm S carried both
answers on the sheet and went **27/27**, plus 30/30 on the prior multi-hop/single-hop sets —
**57/57 overall, the only arm on the site to pass every trial.**

Symbol edges also beat file edges on the original multi-hop set: **-28% context vs G (35.7k → 25.8k
median), -68% vs baseline (80.5k)** — the multi-hop questions turn out to have always been symbol
questions (context consumers, barrel constants); S answers most hops straight from the sheet and
spends one verification read where G had to open every file its edges pointed at. The one place S
loses is single-hop lookups (+14% vs G) — "where is X?" is answered by the map alone, and the extra
symbol tokens ride along unused. Emerging design: **layer selection, not layer stacking** — map for
location, symbols for code composition, edges for cross-domain references (secrets/PVCs/Flux) that
symbols don't cover.

Commit: `717c920`.

## 2. Serena refutes 2025 weak-model lore on accuracy, loses decisively on economics

Matt baked `uv` into the harness image mid-session, unblocking the arm that had been parked since
yesterday. Serena v1.5.3 registered per-trial via `OPENCODE_CONFIG` (merges with the global config —
same environment as every other arm, plus serena; this merge behavior was itself an open question
going in). 57 trials + 1 discarded warm-up, 0/57 wrong-rooted, zero idle-kills.

**Verdict: qwen3-coder CAN drive serena — 57/57 including every chain question, zero tool-use
failures across ~250 tool calls. The 2025-era "weak models get lost with LSP tools" lore is dead on
accuracy.** But it costs **2.8-4.5× arm S's context for identical accuracy**, and on multi-hop
(115.6k vs baseline's 80.5k) it's more expensive than *no tooling at all* — schemas for ~20 tools plus
the accumulated tool transcript ride in every request, so symbol round-trips replace grep round-trips
without ever getting cheap. The floor makes the tax visible: serena's cheapest single-hop trials still
sit at ~62k cumulative cache vs 17.5k for S — a ~3.5× standing overhead before any navigation even
starts. Worst case (ms5, a barrel chain): 186k cache / 119s for an answer arm S delivers at ~36k/16s.

Where serena would still plausibly win: symbol-level *editing* (rename, `replace_symbol_body`) and
polyglot repos with no `gen-symbols.mjs`-style generator — neither is exercised by a read-side Q&A
bench, so that stays open. For navigation on our stack: same accuracy, a quarter the tokens, half the
wall time, no python/uv dependency at inference time.

Commits: `79129eb` (wiring + `serena-prep.md`, image-bake ask, `OPENCODE_CONFIG` merge discovery),
`2c558f3` (results).

## 3. Two methodology saves

**Cross-day cost drift.** Running the merged-sheet (GS) test on pi-cluster, a same-night *G alone*
recheck came in at ~2× yesterday's median (47.4k vs 23.2k) at half the wall time per trip — the
"empty symbol layer causes verification reads" read looked plausible until the recheck proved it
environmental (hot-coder is aimode-following 30B/Q8, plus Beelink cache regime drift). **Lesson:
cross-day absolute numbers are invalid; only same-window arm-pair comparisons count.** The site
rounds (A/B/G/S/C) all ran same-window and are unaffected — this only invalidated a same-vs-different-day
G comparison on pi-cluster, caught before it became a false finding.

**GS-overlap fabrication.** Stacking two sheets that describe the *same relations in different
vocabularies* (G's file-level import edges + S's symbol edges) made the model fabricate hybrid index
lines: GS-overlap answered ms3 with `phosphor-tuner -> hooks:useGPU`, a line that exists in *neither*
sheet, 0/3, pure sheet-reading with zero verification reads. Fix: `gen-edges --no-code-imports`, now
automatic for arm GS, makes the two layers domain-disjoint. The disjoint merged sheet went 24/24 on
the cross-domain x-set. **Rule: one vocabulary per relation; stack only across domains.**

Commit: `bb70fc2`.

## 4. pi-cluster has no symbol graph — the GS run became a null test, and passed

Running arm GS (map + edges + symbols stacked) on pi-cluster surfaced a structural fact first:
**this repo has no symbol graph.** Family Board is a single-file `index.html` app, the n8n `src/*.js`
files are standalone Code-node snippets composed by workflow JSON with zero imports between them, and
the bench scripts are self-contained — pi-cluster's composition lives entirely in YAML. `gen-symbols.mjs`
correctly emits a ~142-token near-empty sheet, so the GS round became a test of whether stacking an
empty layer hurts. It doesn't: same-night GS (23/24, med 48.0k) tracked the same-night G recheck
(23/24, med 47.4k) almost exactly, with the same flaky-m4 residual and 47/48 across both sets — **the
empty layer costs its 142 tokens and nothing else. The merged sheet is safe to inject unconditionally;
layer relevance falls out of the data, not config.** One GS trial (m7) did thrash to 273k ctx / 234s
before answering correctly — sheet arms aren't immune to occasional tool loops, hence medians over
means for this bench.

Commit: `fbe81f7`.

## 5. Positive GS case: pi-cluster-mcp, and the completion rounds that closed the matrix

To get the merged-sheet case pi-cluster couldn't provide, the session cloned `pi-cluster-mcp` fresh
(37 TS files + k8s manifests — actual code *and* actual YAML) and built a new cross-domain question
set (`x-set`, 8 grep-verified chains: yaml→code env-var plumbing, code→yaml secret refs, RBAC verb →
code guard, a dynamic-import chain). Extractor fixes landed alongside it (TS NodeNext `.js`→`.ts`
resolution, dynamic `await import()` edges). **All four arms went 24/24** — G -22%, S -21%, GS-disjoint
-19% vs baseline's 56.8k median. At 37 files the three sheet types converge; the merged sheet's value
is a bet on repo size, not a necessity here — *safe*, not yet *necessary*.

Commit: `378dda4`.

The overnight completion batch (351 trials) closed every remaining matrix cell: site gaps (B on the
comp set, GS re-run, S re-run as a same-window anchor), serena on pi-cluster, and the pi-cluster-mcp
x-set above. Serena on pi-cluster (a manifest repo) went **48/48** — competent via its pattern-search
tools, but at 84-91k median ctx vs the same-night G recheck's 47.4k (~1.9×). **Across the whole
campaign serena finished 105/105 lifetime, with the worst economics on every tier it ran** (1.9× on
manifests, 2.8-4.5× on code). Bare map (B) confirmed as the weakest sheet arm — it repeatedly falls
into the barrel-origin trap (reports a re-export file as the implementation). Accuracy has saturated
across 783 total audited trials (0 wrong-rooted); the only failures left are the three predicted trap
classes — barrel origin, local symbol, sheet fabrication. At this repo scale, **arm choice is now a
cost/safety decision, not an accuracy one.**

Commit: `9bdb122`.

## 6. Production guidance (now in the research doc)

Campaign verdict, written into `docs/research/codemap-serena-token-efficiency.md`: **inject map +
the domain-appropriate sheet into qwen sessions** — symbols for code repos, edges for manifest repos,
both (kept disjoint) for mixed repos. **One vocabulary per relation.** Do not register serena for
navigation; revisit only if a symbol-level *editing* bench gets built. The doc's status line now
reflects measurement-complete + guidance-issued instead of "pending local dogfood test."

## 7. Open threads

- Symbol-level *editing* tools (serena's rename/`replace_symbol_body`) on real SDD tasks — untested,
  the last open cell in the serena story.
- Wiring the winning sheet(s) into `ralph-qwen.sh` for real SDD runs, now that the arm choice is
  settled — noted in yesterday's recap as pending, still pending.
- Obsidian-style viz of the `--json` edge/symbol graph output — parked, unblocked by nothing new
  today.

No cluster topology changed. `scripts/token-bench/` and its results files are dev tooling for the
local coding-agent workflow and were left untouched by this recap; durable detail lives in
`docs/research/codemap-serena-token-efficiency.md` and will feed `docs/research/local-coding-agent-sdd.md`
once the sheet wiring lands.

---

## Commits

| Repo | Ref | Subject |
| :--- | :--- | :--- |
| pi-cluster | `717c920` | feat(token-bench): arm S symbol/component graph — 57/57, -28% ctx vs edge index on multi-hop |
| pi-cluster | `79129eb` | feat(token-bench): wire arm C (serena) — runs the moment uv lands in the harness image |
| pi-cluster | `2c558f3` | feat(token-bench): serena round — 57/57 but 2.8-4.5x the context of the symbol sheet |
| pi-cluster | `fbe81f7` | feat(token-bench): GS merged-sheet null test — GS ≈ G, empty symbol layer is free |
| pi-cluster | `378dda4` | feat(token-bench): x-set (pi-cluster-mcp cross-domain questions) + extractor fixes |
| pi-cluster | `bb70fc2` | fix(token-bench): GS layers must be domain-disjoint — overlap made the model fabricate sheet lines |
| pi-cluster | `9bdb122` | feat(token-bench): completion rounds — full matrix closed, 351 trials, overlap hazard confirmed |

**Continued:** production wiring and the first ralph run under sheet injection — `docs/recaps/2026-07-12-codesheet-production-wiring.md`.
