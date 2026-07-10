# Recap — Token-efficiency research and the knowledge-cloud edge index (2026-07-10)

One thread all day, run from inside `coding-harness-claude`: does qwen3-coder (32k ctx, opencode,
Beelink) actually need a token-saving layer over plain repo reads, and if so, which one? Started as a
deep-research literature pass on Serena (LSP-backed MCP) and codemap-style repo-map tools, then
pivoted to building and running an actual measurement harness once the research turned up no
published numbers to trust. Ended with a validated winner and a genuine surprise about where qwen's
actual weak spot is.

---

## 1. Research: Serena vs. repo-map, and the absence of evidence

Ran a 103-agent deep-research pass on Serena (`oraios/serena`) and codemap-style repo-map tools as
token savers for qwen3-coder, with adversarial verification of every claim before it was allowed into
the report. The headline finding was negative: **no tool in this space publishes measured token
savings** — not Serena, not the codemap forks, not the LSP-MCP alternatives. Serena in particular has
zero small-model evidence; its own docs and issues are silent on anything below frontier-model scale.
The best weak-model evidence available anywhere was indirect — Aider's docs and leaderboard, which
put a distraction threshold around 25k tokens of injected context and show quantization hurting
accuracy at Q4, not Q8 (qwen3-coder here runs Q8).

Verdict: given the evidence gap, the sane move was the low-surface option — a passive, generated
repo-map — over adopting Serena's ~20-tool live-LSP surface for a single local model with no data
showing it helps. Full report: `docs/research/codemap-serena-token-efficiency.md`.

## 2. Building the measurement harness

Since nobody else had numbers, the session built its own: `scripts/token-bench/` runs a
repo-navigation Q&A bench through headless `opencode run` invocations, one trial per question per
arm, metered by reading opencode's own SQLite session DB (tokens in/out/cache per session) — no
LiteLLM admin access needed, and it turned out LiteLLM's `/spend/logs` doesn't even see local-model
usage (see gotchas below).

- **8 single-hop questions** — grep-verified answers, one lookup each.
- **8 multi-hop chain-traversal questions** added later (`questions-multihop.jsonl`) — deliberately
  constructed so the literal answer and the question's own keywords live in *different* files, and
  graded with array-of-regex `grade[]` requirements (all must match) so a lucky endpoint guess can't
  pass. Each question documents its intended hop path.
- `gen-repomap.mjs` — a budgeted structural map: per-file detail degrades as the map grows, and
  collapsed directories still surface distinctive filenames instead of just a count.

## 3. Results, round 1: repo-map helps single-hop, vanishes on chains

~200 trials landed in `scripts/token-bench/results/results.jsonl` across the session.

- **Single-hop:** baseline 24/24 at 47.1k mean context; repo-map arm 25/25 at 41.8k (**-11%**).
- **Multi-hop:** baseline 25/25 at 54.9k; repo-map 26/27 at 54.0k — the saving essentially disappears.
  A structural map tells you *where things are*, not how they *reference* each other, so it doesn't
  help chase a chain. (The one "fail" was a grader false-negative — it was checking content
  proximity, not exact formatting, and got it wrong, not qwen.)

**Headline negative result:** qwen scored an effective 49/49 on navigation including the
chain-traversal set. Read-navigation accuracy is not qwen's weak spot — the 2025-era "weak local
models get lost in big repos" lore the research pass surfaced doesn't hold here. Multi-hop questions
cost tokens (+17% context), not correctness.

## 4. Knowledge-cloud edge index — the actual winner

Since the gap was reference-following, not structure, `gen-edges.mjs` (arm G) extracts 695 explicit
reference edges straight out of the repo: `secretName` → ExternalSecret, 1Password `remoteRef`, PVC
claims, Service calls, Flux `dependsOn`, `$imagepolicy` markers, NFS mounts, backup CronJob PVC
lists, Tailscale routes, and doc mentions. A `--json` mode emits the full graph for a future
Obsidian-style viz on the site.

Three iterations to get it right:

- **v1 (filename-labeled edges)** — 22/25 at 49.6k, and a new failure class showed up: the model
  started citing the index *as if it were repo content*, answering with the index's filename label
  (`backup-cronjob`) instead of the actual resource name (`pvc-backup`), and quoting index vocabulary
  like "backs_up annotation" as though it appeared in the source. Partly caused by an injected
  instruction telling it to follow chains directly instead of opening each linked file.
- **v2 (per-doc Kind/name labels)** — 23/24 at **38.6k mean context, -30% vs. baseline**, with cache
  traffic roughly halved. The winner.
- **v2i (v2 + an added "verify literals in source" instruction)** — 23/24 at 50.1k. The instruction
  bought no accuracy and handed the entire token saving back.

**Lesson from v1→v2→v2i:** put correct identities *in the data*, don't instruct the model to
double-check them — the fixture should carry the rigor, not a prompt appended on top of a sloppy one.

m4 pass rate by variant: baseline A 3/3, repo-map B 3/3, edge-index G-v1 0/3, G-v2 2/3, G-v2i 2/3 —
v2's residual miss is the same identity-labeling issue v1 had, just less of it.

## 5. Harness gotchas worth remembering

- **opencode/Bun leaks ~5.4MB of `.so` files into `/tmp` per headless run.** 48 trials filled the
  harness container's 256M tmpfs mid-run. The bench now sweeps `/tmp` between trials; flagged for the
  next image bake to just give `/tmp` more room.
- **`opencode run` reliably hangs after printing its answer** (remote MCP connections staying open).
  The bench uses an idle-kill watchdog and records time-to-last-output rather than waiting for exit.
- **Idle-kill can race opencode's async token flush**, producing zero-token rows. The meter now waits
  for the flush and `backfill-tokens.mjs` repairs any gaps afterward straight from the session DB by
  `session_id`.
- **LiteLLM virtual keys can't read `/spend/logs`, and local-model spend records as $0 anyway** —
  opencode's own session DB is the only trustworthy meter for this setup, not LiteLLM admin.

## 6. Open threads

- v2's edge lines should lead with resource identity to close the last of the m4 misses.
- Wire the v2 edge-index injection into `ralph-qwen.sh` for real SDD runs — a stable map should be
  near-free once opencode's prefix cache kicks in.
- Turn the `--json` graph output into an Obsidian-style viz for the site.
- Serena arm is parked pending a `uv`/Python bake into the harness image — much lower priority now
  that baseline navigation is already 49/49.

No cluster topology changed today; `scripts/token-bench/` is dev tooling for the local coding-agent
workflow, so `ARCHITECTURE.md` and the cluster skill docs are unaffected. `docs/research/` gained one
report; the `coding-agent-ops` project memory already tracks the local-agent initiative and will pick
up the edge-index wiring as its own entry once it lands in `ralph-qwen.sh`.

---

## Commits

| Repo | Ref | Subject |
| :--- | :--- | :--- |
| pi-cluster | `9849c2a` | docs(research) + feat(token-bench): codemap/serena report + repo-map analytics harness |
| pi-cluster | `b73bcc5` | token-bench: first 48-trial collection + Bun-litter sweep + measured results |
| pi-cluster | `b6f949f` | token-bench: multi-hop question set (m1-m8) + array grades + tier split |
| pi-cluster | `22dae6f` | token-bench: multi-hop results (49/49 effective) + grader fix + findings |
| pi-cluster | `08ec914` | token-bench: knowledge-cloud edge index (gen-edges.mjs) + arm G |
| pi-cluster | `8c002fe` | token-bench: edge index v2 — per-doc Kind/name attribution + run tags |
| pi-cluster | `2befdb6` | token-bench: v2/v2i results — edge index validated, data fix beat instruction fix |
