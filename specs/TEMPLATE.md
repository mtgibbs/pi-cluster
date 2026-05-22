# Spec: <Feature Name>

<!--
  Copy this file to specs/<feature>/spec.md and fill it in. Delete the HTML
  comments as you go — they're guidance, not part of the spec.

  The golden rule, learned the hard way (see homepage-refresh §11): the model
  nails anything backed by a concrete pattern, a literal value, or a testable
  rule — and guesses wherever you left intent as prose. SPECIFICITY IS THE LEVER.
-->

- **Status:** Draft v0.1   <!-- Draft -> Planned (OQs resolved) -> In progress -> Done; bump version on tuning -->
- **Owner:** <name>
- **Constitution:** `specs/constitution.md` (+ `/CLAUDE.md` Core Mandates)
- **Touches:** <the files/paths this will change>

---

## 1. Why
<!-- The problem, in 2-4 sentences. Stops the agent optimizing the wrong thing. -->

## 2. Outcomes
<!-- Done-in-plain-language. The human-alignment layer. Numbered, observable. -->

## 3. Scope
### In scope
<!-- Exact files/areas. -->
### Out of scope
<!-- What NOT to touch. This list prevents drift as much as the "in" list. Be explicit
     about anything adjacent the model might "helpfully" change. -->

## 4. Constraints
<!-- The constitution made concrete for THIS task. GitOps? in-cluster URLs? no inline
     secrets? destructive? Call out house conventions the change must follow. -->

## 5. Prior decisions / facts the implementer must know
<!-- The context dump that prevents hallucination. Include:
     - exact resource names, URLs, ports, namespaces (look them up — don't make the model guess)
     - which EXISTING pattern to copy, and the file it lives in ("like X in path/to/file")
     - OPERATIONAL REALITY the model can't infer from code (e.g. "service X is deployed but unused")
     - literal values for anything linkable (URLs, UIDs) -->

## 6. Task breakdown
<!-- Ordered work units. Mark which can run in parallel. Map to files where possible. -->

## 7. Acceptance criteria (EARS)
<!-- The testable contract — the HEART of the spec. Use the five EARS patterns:
       Ubiquitous:  The <system> shall <response>.
       Event-driven: When <trigger>, the <system> shall <response>.
       State-driven: While <state>, the <system> shall <response>.
       Unwanted:    If <condition>, then the <system> shall <response>.
       Optional:    Where <feature>, the <system> shall <response>.
     Each one must be checkable by the verification harness in §8. If you can't test it,
     rewrite it until you can. Include the "what if a thing is missing" cases. -->

## 8. Verification (the harness)
<!-- How §7 is proven. Concrete commands: lint, build/dry-run, the MCP/CLI checks,
     the post-apply spot-checks. This is what the agent self-checks against and what
     the reviewer runs. (Mitchell Hashimoto's "harness engineering".) -->

## 9. Open questions
<!-- Honest unknowns. Don't fabricate — flag them, resolve in the Plan phase, then fold
     the answers back in (living document). Number them OQ1, OQ2, ... -->

<!-- ## 10. Plan — implementation reference   (added when OQs are resolved) -->
<!-- ## 11. Tuning log                          (added after an agent eval — what missed and why) -->

## Worked-example checklist (before you hand this to an agent)
<!-- - [ ] Every linkable target is a LITERAL url/uid, not prose.
     - [ ] Novel/unfamiliar patterns have a copy-paste example block.
     - [ ] Where an existing-but-different pattern could mislead, the contrast is called out.
     - [ ] Operational facts the model can't infer are stated in §5.
     - [ ] Every §7 criterion is testable by §8. -->
