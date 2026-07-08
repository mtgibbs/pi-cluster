# Spec: <Feature Name>

<!--
  Copy this file to specs/<feature>/spec.md and fill it in. Delete the HTML
  comments as you go — they're guidance, not part of the spec.

  The golden rule, learned the hard way (see homepage-refresh §11): the model
  nails anything backed by a concrete pattern, a literal value, or a testable
  rule — and guesses wherever you left intent as prose. SPECIFICITY IS THE LEVER.
-->

> **This template is our REASONS Canvas.** It overlays Martin Fowler's SPDD seven
> dimensions — **R**equirements · **E**ntities · **A**pproach · **S**tructure ·
> **O**perations · **N**orms · **S**afeguards — onto our EARS + `verify.sh` discipline.
> Each section is tagged with its REASONS letter. Sections are ordered
> *constraints-before-work* (best for a literal executor like qwen), not in canvas
> letter-order; all seven dimensions are present. Norms (§7) + Safeguards (§8) are the
> SPDD additions vs our old template — the cross-cutting + non-negotiable layers where
> an executor otherwise guesses badly. Rationale: `docs/research/local-coding-agent-sdd.md` §11.

- **Status:** Draft v0.1   <!-- Draft -> Planned (OQs resolved) -> In progress -> Done; bump version on tuning -->
- **Owner:** <name>
- **Constitution:** `specs/constitution.md` (+ `/CLAUDE.md` Core Mandates)
- **Touches:** <the files/paths this will change>

---

## 1. Why · [R — Requirements]
<!-- The problem, in 2-4 sentences. Stops the agent optimizing the wrong thing. -->

## 2. Outcomes (Definition of Done) · [R — Requirements]
<!-- Done-in-plain-language. The human-alignment layer. Numbered, observable. -->

## 3. Entities · [E — Entities]
<!-- The domain objects this touches and their SHAPE — tables/columns, message/payload
     fields, config keys, CRDs, state machines, relationships. Use literal field names and
     types (e.g. `intake_items(id, due_at TIMESTAMPTZ, student ENUM ronin|rory|both|unknown)`).
     A literal executor invents field names and shapes unless you pin them here.
     If the work is genuinely stateless (pure UI/script with no data model), say so and skip. -->

## 4. Approach · [A — Approach]
<!-- The strategy in 2-5 sentences: HOW we intend to meet §1, and crucially WHICH existing
     pattern this mirrors ("same shape as X in path/to/file"). The high-level plan that the
     §9 task breakdown then makes concrete. Note any approach considered and rejected (so a
     later reader — or a regenerating model — doesn't re-litigate it). Rejected approaches
     often live in past agent sessions, not docs — the lifecycle's ctx prior-art pass
     (`ctx search "<terms>"`) is where to dig them up. -->

## 5. Scope · [S — Structure: boundary]
### In scope
<!-- Exact files/areas. -->
### Out of scope
<!-- What NOT to touch. This list prevents drift as much as the "in" list. Be explicit
     about anything adjacent the model might "helpfully" change. -->

## 6. Prior decisions / facts the implementer must know · [S — Structure: system fit & deps]
<!-- The context dump that prevents hallucination. Include:
     - exact resource names, URLs, ports, namespaces (look them up — don't make the model guess)
     - which EXISTING pattern to copy, and the file it lives in ("like X in path/to/file")
     - OPERATIONAL REALITY the model can't infer from code (e.g. "service X is deployed but unused")
     - upstream/downstream dependencies and how this component fits the system
     - literal values for anything linkable (URLs, UIDs)
     - decisions/attempts from prior agent sessions (`ctx search --file <path>` per touched
       file) — distill the finding into a sentence here; cite the ctx session id so a
       reviewer can pull the full context with `ctx show session <id>` -->

## 7. Norms · [N — Norms]
<!-- Cross-cutting STANDARDS for this task — the stuff a literal executor has no taste for and
     will guess (badly) unless stated. Pull the relevant rules from `specs/design-principles.md`
     and make them concrete here:
       - Naming: file/var/resource conventions to follow.
       - Observability: what to log/emit; existing metric/label conventions to match.
       - Error handling / defensive coding: how failures surface; what's continueOnError.
       - House style / taste: e.g. "distinct icons per metric — do NOT reuse one for three"
         (the literal homepage-refresh failure). Specify, or it recurs.
     Norms are how the work should look; Safeguards (§8) are what it must never violate. -->

## 8. Safeguards · [S — Safeguards]
<!-- NON-NEGOTIABLE boundaries and invariants — distinct from "out of scope" (what to leave
     alone). These are what must ALWAYS hold, stated so a passing §11 gate can't be "confidently
     wrong":
       - Security: no inline secrets; secrets via ExternalSecret only; never echo a secret;
         never execute downloaded/untrusted files.
       - Data invariants: idempotency / dedup key; no destructive writes without X; PK/uniqueness.
       - Performance/resource bounds: limits, timeouts, payload caps.
       - Safety: what a wrong implementation could break, and the guardrail against it.
     Where possible, each safeguard should map to a §11 verify.sh assertion. -->

## 9. Task breakdown · [O — Operations]
<!-- Ordered work units. Mark which can run in parallel. Map to files where possible.
     Obey §7 Norms and §8 Safeguards throughout — they are always-on, not a final step. -->

## 10. Acceptance criteria (EARS) · [O — Operations made testable]
<!-- The testable contract — the HEART of the spec. Use the five EARS patterns:
       Ubiquitous:  The <system> shall <response>.
       Event-driven: When <trigger>, the <system> shall <response>.
       State-driven: While <state>, the <system> shall <response>.
       Unwanted:    If <condition>, then the <system> shall <response>.
       Optional:    Where <feature>, the <system> shall <response>.
     Each one must be checkable by the verification harness in §11. If you can't test it,
     rewrite it until you can. Include the "what if a thing is missing" cases.
     (This is SPDD's "Operations" dimension — but compiled to a deterministic gate, not prose.) -->

## 11. Verification (the harness) — SHIP A `verify.sh`
<!-- §10 acceptance criteria, COMPILED into a runnable, deterministic gate: a `verify.sh`
     in the spec dir that exits 0 only if the work is acceptable. Mandatory for any spec
     handed to an agent loop. Two tiers:
       - STATIC (no deploy): lint, build/dry-run, structural/semantic greps. This is what
         gates each loop iteration — must be deterministic + offline.
       - LIVE (post-deploy): renders-with-data, secrets-synced, health. Human/Flux; NOT
         gated in the loop.
     The LOOP runs verify.sh — the model NEVER self-certifies "done". Write each §10
     criterion (and each §8 safeguard) so it maps to a verify.sh assertion.
     (Hashimoto harness-engineering / TDD-for-agents.) -->

## 11b. Loop execution (handing to a local model)
<!-- Local models (qwen) are faithful literal executors with no stamina/taste/self-check.
     Run via scripts/ralph-qwen.sh: ONE task per iteration, FRESH context each time,
     timeboxed (watchdog), gated on verify.sh, retry-with-feedback, stop-for-human when
     stuck. Decompose §9 into a tasks.txt. Bound scope = small context = reliable. Never
     hand the model the whole repo or whole spec at once. -->

## 12. Open questions
<!-- Honest unknowns. Don't fabricate — flag them, resolve in the Plan phase, then fold
     the answers back in (living document). Number them OQ1, OQ2, ... -->

<!-- ## 13. Plan — implementation reference   (added when OQs are resolved) -->
<!-- ## 14. Tuning log                          (added after an agent eval — what missed and why) -->

## Two-way sync rule (keep spec ⇄ code aligned)
<!-- From SPDD, and our own drift finding (#7): the spec is the source of intent, so —
       - LOGIC change (behavior differs): fix the SPEC first, then regenerate/edit code.
       - REFACTOR (no behavior change): change code, then sync the fact back into the spec.
       - HOTFIX that bypassed the loop: post-mortem it back into the spec + Tuning log (§14).
     A taste/Norms correction made in review (§7) MUST be written back, or the executor
     reproduces the same miss next iteration. "When reality diverges, fix the prompt first." -->

## Worked-example checklist (before you hand this to an agent)
<!-- - [ ] ctx prior-art pass run (feature terms + each touched file); findings folded into §4/§6.
     - [ ] Every linkable target is a LITERAL url/uid, not prose.
     - [ ] §3 Entities pin literal field names/types (or "stateless — n/a").
     - [ ] §4 Approach names the existing pattern being mirrored.
     - [ ] §7 Norms pull the taste/observability rules that apply (don't leave to guess).
     - [ ] §8 Safeguards state the non-negotiables, and each maps to a §11 assertion where possible.
     - [ ] Novel/unfamiliar patterns have a copy-paste example block.
     - [ ] Where an existing-but-different pattern could mislead, the contrast is called out.
     - [ ] Operational facts the model can't infer are stated in §6.
     - [ ] Every §10 criterion is testable by §11. -->
