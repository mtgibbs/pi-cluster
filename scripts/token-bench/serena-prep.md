# Arm C (Serena) — image-bake ask + runbook

Everything bench-side is wired (2026-07-11); arm C runs the moment the harness
image has `uv`. Per the container-config rule, the image change happens from
the laptop via `beelink-ansible` — this file is the ask.

## The ask (harness image bake)

Add to the coding-harness container image (both `coding-harness-qwen` and
`coding-harness-claude` use the same base):

```dockerfile
# uv + uvx (static binaries — no system python needed; uv manages its own)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Pre-warm serena so the first bench trial doesn't pay the clone + resolve
# (pin matches run-bench.mjs --serena-ref default; bump both together)
RUN uvx --from git+https://github.com/oraios/serena@v1.5.3 serena --help
```

Notes:
- The pre-warm populates `~/.cache/uv` — make sure it runs as (or is readable
  by) the runtime user, else it re-downloads at trial time.
- Serena's TypeScript support downloads a language server on first project
  activation (runtime, needs network — container has it). First arm C trial
  against a TS repo is therefore slow once per repo; warm-up is a discarded
  `--only c1 --reps 1 --tag warm` run.
- No system python needed: uv provisions its own interpreter for the venv.

## Post-bake verification (in the container)

```sh
uvx --version                                                    # 1. binary present
uvx --from git+https://github.com/oraios/serena@v1.5.3 serena --help   # 2. cached, no download
cd /Users/mtgibbs/dev/pi-cluster/scripts/token-bench
node run-bench.mjs --arm C --root /Users/mtgibbs/dev/mtgibbs.xyz \
  --qfile questions-site-components.jsonl --only c1 --reps 1 --tag warm  # 3. end-to-end (discard: warm-up)
```

Then the real comparison (sequential, no concurrent opencode sessions):

```sh
node run-bench.mjs --arm C --root /Users/mtgibbs/dev/mtgibbs.xyz --qfile questions-site-components.jsonl --reps 3
node run-bench.mjs --arm C --root /Users/mtgibbs/dev/mtgibbs.xyz --qfile questions-site.jsonl --reps 3
node report.mjs
```

## How arm C works (already wired in run-bench.mjs)

- Registers serena for the trial only via `OPENCODE_CONFIG` pointing at a
  generated config with the serena stdio entry. Verified: the env-pointed
  config **merges** with the global one, so provider/model/homelab MCPs are
  inherited — every arm sees the same environment plus/minus its aid.
- Seeds `<ROOT>/.serena/project.yml` if absent (`ignored_paths` covering
  node_modules — the #1 serena ops gotcha — and `read_only: true`; the bench
  is Q&A, symbol-editing tools stay off).
- Prompt gets a tool hint (prefer `find_symbol`/`find_referencing_symbols`
  over whole-file reads) — symmetric with the sheet arms' usage instructions.
- `--serena-ref` overrides the version pin.

## What arm C is supposed to answer (research doc open questions 1 & 4)

1. **Can qwen3-coder actually drive ~20 instruction-heavy symbol tools?**
   Weak-model evidence says no; nobody has published the test. Pass-rate vs
   arm S is the answer.
2. **What does registering serena cost per trial at 32k context?** Its tool
   schemas ride in every request. Compare arm C `tokens_input` on a question
   answered WITHOUT serena tool calls vs arm A's — the delta is the standing
   schema tax. The incumbent to beat: arm S at 57/57, ~26k mean ctx.
