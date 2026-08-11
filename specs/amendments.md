# Amendments — ratified changes to the constitution

> Version: 1.2.0 · rides with `constitution.md` as Tier-1 context.
>
> The constitution is founding intent. **It does not morph.** Change arrives here:
> proposed from the memory notes (`memory-amend propose`), ratified by a human via
> the PR that adds it, appended — never edited into the original.
>
> Rules for this file:
> - **Append-only.** A superseded amendment gets `Status: Superseded by <heading>`,
>   never deletion — the history is the point.
> - **Semver on the version line above.** New principle = MINOR. Wording fix = PATCH.
>   Removing or redefining one = MAJOR, and should make you pause.
> - Every amendment names its **Source** note, so the trail back to where it was
>   learned survives.
> - Judges cite an amendment by its heading, same as a constitution principle.

## Gates must prove they can fail

Status: Accepted · 2026-08-10 · Source: pi-cluster/reference_loop_library

A `verify.sh` check must be shown to go RED without the change it verifies —
red-before / green-after — not merely green with it. A check that has never
failed proves presence, not correctness; it cannot catch "built nothing."

**Rationale:** false-green is the strongest failure mode of deterministic
gates (the `no_false_green` risk; the specs/export incident scored an empty
deliverable as passing). Proposed in the notes 2026-07-27 from the Loop
Library review; ratified via memory-amend + this PR.

## Durable facts go to the repo, never only to memory

Status: Accepted · 2026-08-10 · Source: pi-cluster/feedback_docs_over_memory

A non-obvious fact about the cluster or a service — API quirk, breaking
default, hour-long recipe — lands in the repo: a skill's `SKILL.md`, `docs/`,
or `ARCHITECTURE.md`. Agent memory holds the user profile, feedback rules,
ephemeral state, and pointers to docs — never the content itself. When in
doubt, write the doc.

**Rationale:** memory is private to one agent — it survives no rebuild, gets
no PR review, and is invisible to sub-agents and humans reading the repo.
Docs travel with the codebase. This principle already decided all six
amendment declines before it was ratified itself.
