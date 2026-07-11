# Spec: document codesheet injection in scripts/README.md

## 1. Goal

`scripts/README.md` documents `oc` and `harness` but says nothing about the
codesheet injection added to `oc run` and `ralph-qwen.sh`, and `ralph-qwen.sh`
has no section at all. Add that documentation. Documentation-only change:
exactly ONE file may be modified — `scripts/README.md`.

## 7. Acceptance criteria (verify.sh checks these — the gate is deterministic)

- AC1: `scripts/README.md` contains a heading (## or ###) whose text mentions
  codesheet injection.
- AC2: the new text names the generator script `scripts/gen-codesheet.mjs`.
- AC3: the new text documents the `OC_SHEET=off` opt-out.
- AC4: the new text documents the `OC_SHEET_GEN` override.
- AC5: the new text documents `RALPH_SHEET` (ralph's own opt-out).
- AC6: `ralph-qwen.sh` is mentioned (its sheet is generated once per loop).
- AC7: the layer-selection idea is stated: symbol graph for code repos, edge
  index for manifest repos (the words "symbol" and "edge index" must appear).
- AC8: the evidence is cited by path:
  `docs/research/codemap-serena-token-efficiency.md`.
- AC9: existing content is preserved — the `op://work-vault/opencode/key`
  example and the `cp scripts/oc ~/.local/bin/oc` bootstrap line still exist.
- AC10: no file other than `scripts/README.md` is modified or created.

## 10. Reference (facts to document — use these, do not invent)

Write a `### Codesheet injection` subsection inside the existing
"## `oc` — opencode launcher" section, plus a short new
"## `ralph-qwen.sh` — bounded SDD loop" section after the `oc` section.
Facts:

- Every headless `oc run` prepends a navigation codesheet to the prompt:
  a repo map plus the reference sheet the repo's shape calls for.
- Layer selection is automatic, from the repo's contents: symbol graph for
  code repos, edge index for manifest repos, both (domain-disjoint) for mixed
  repos.
- Generator: `scripts/gen-codesheet.mjs`. Resolution order: `$OC_SHEET_GEN`
  env var, then `<target repo>/scripts/gen-codesheet.mjs`, then the canonical
  pi-cluster checkout. If none is found, `oc run` works unchanged (silent
  passthrough).
- Opt-out: `OC_SHEET=off oc run "..."`.
- Interactive `oc` (TUI) sessions are not injected.
- `ralph-qwen.sh <spec-dir>` runs the bounded SDD loop (one task per fresh
  session, deterministic verify.sh gate, retry with failure feedback). It
  generates the codesheet ONCE per loop so the identical bytes ride the
  prefix cache across every task and retry, and sets `OC_SHEET=off` on its
  own `oc` calls so the sheet is never injected twice. Opt-out:
  `RALPH_SHEET=off`.
- Measured basis (cite the path): 20-56% less context at equal-or-better
  accuracy across 783 trials — `docs/research/codemap-serena-token-efficiency.md`.
