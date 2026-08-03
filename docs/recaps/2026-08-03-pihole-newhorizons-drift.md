# Recap — the Pi-hole saga closes, new-horizons ships, and the drift treadmill dies (2026-08-02 → 03)

The harness-side arc of the same overnight session covered in
[`2026-08-03-judge-loop-and-incident.md`](2026-08-03-judge-loop-and-incident.md), which recounts
the laptop side (judge loop, `gate-score`, and the incident from its end). This one covers the
other half: **14 PRs across three repos**, ending with a months-old misdiagnosis closed, a new
service live, and a recurring CI tax removed at the source.

One theme runs through nearly all of it, so it is stated up front rather than saved for the end:

> **A signal that cannot fail stops being read — and then it cannot do its job when something
> real breaks.**

That single failure mode appears below in five unrelated places. It was not looked for; it kept
turning up.

---

## 1. The Pi-hole saga — a misdiagnosis two layers deep

**PRs:** pi-cluster-mcp #46 → 0.1.25, #49 → 0.1.26 · pi-cluster #125

The `get_dns_status` stats had been failing for months, and the repo's own diagnostic table said
why: *"the `PIHOLE_API_TOKEN` no longer matches Pi-hole's app password — re-mint it."* That row
was wrong, and it had been sending readers to rotate a perfectly good credential.

- **#44/#46 (0.1.25)** — the real cause was two defects masking each other: `stats/summary` was
  fetched with `requiresAuth = false` (true in v5, not v6), *and* `authenticate()` swallowed
  failures and silently degraded to an unauthenticated request. So a **valid** password produced
  a byte-identical `401`.
- **0.1.25 then exposed a `429`.** Verifying the fix in production rather than trusting the
  release surfaced the next layer. Pi-hole's own log settled it in one call:
  `WARNING: API: Rate-limiting login attempts` — **twice, at the same second, from a single tool
  call**. Nothing dedup'd *in-flight* logins, so `Promise.all` fan-out had every branch miss the
  not-yet-populated session cache and fire its own `POST /api/auth`. On failure the session
  stayed null, so the next call bursted again and re-armed the limiter: a **self-sustaining
  lockout**, which is why it read as permanent rather than transient.
- **#49 (0.1.26)** — single-flight the login, back off on 429 honouring `Retry-After`, and report
  throttling *as* throttling. The old message blamed the password, which is the #44 misdirection
  aimed at a new cause.
- **Second, unrelated defect in the same tool:** `healthy` was `every(p => p.ready)` over every
  pod named `*pihole*`, including completed `brainrot` CronJob pods that sit in `Succeeded` with
  `Ready=False` **forever**. Six leftovers pinned the flag false permanently. Now excluded by
  `ownerReferences`; a *failed* Job pod still surfaces.
- **#125** corrected both rows in `cluster-diagnostics/SKILL.md` and kept the full `#17 → #44 →
  #48/#49` trail in `mcp-homelab-setup.md` — because the reusable lesson is the misdiagnoses, not
  the verdict.

**Verified live on a cold call** (fresh pod, empty session cache — the exact condition that used
to fail): `healthy: true`, 395,581 queries, 17.67% blocked, no `statsError`.

> **Lesson.** An error message that names a cause is not evidence of that cause. Both
> misdiagnoses came from believing the string instead of checking the server side.

---

## 2. new-horizons: live in-cluster

**PRs:** pi-cluster #126, #127, #128 (+ laptop's #129, #130) · new-horizons #21

The deploy stack had been parked (#105–#107 closed "pending go-live"). Rebuilt as one coordinated
PR off current `main`, and rebuilding it is what caught the problems:

- **Two real bugs in the parked stack.** Phase 3 branched off phase 2 *before* the GHCR wiring
  existed and silently lost it — no `external-secret-ghcr.yaml`, no `imagePullSecrets`. As parked,
  it would have been `ImagePullBackOff`. It *looked* complete because phase 3 was the tip and the
  tip built. **Build the union, don't take the tip's tree.**
- **A stale instruction to publish PII.** "Flip the GHCR package public" had propagated into
  **four** files. The image `COPY`s `profile/` — résumé and accomplishments. Packages default to
  private, so the default was safe; the hazard was a copy-pasteable command to undo that sitting
  in the files someone opens first. Corrected in all four.
- **#127 — nothing ever ran `nh init`.** The alerter came up logging
  `sqlite3.OperationalError: no such table: leads` every cycle. The runbook offered "start empty"
  as a supported path, but no manifest created the schema — "empty" meant *no schema*. And
  `serve-metrics` would have failed its probes the same way once the credential landed, which
  would have read as *"the key didn't fix it"* and sent someone back to chase the credential.
- **#128 — the only failing ExternalSecret in the cluster.** The Phase-3 push tokens were
  deliberately unprovisioned, but an ExternalSecret aimed at absent fields does not wait quietly;
  it sits red forever. Removed until the credential was real — then laptop-claude landed #129/#130
  with a **dedicated `@new-horizons` Matrix bot** (one identity per role, not a borrowed token)
  and restored it properly. Good sequencing between two agents: remove the red, restore when true.

**Closed a long-open question:** this was the first workload to actually exercise
`ghcr-read-token`'s `read:packages` scope — every other private image is scaled to 0. **It works.**

**Final state:** pod 2/2, 0 restarts, `/healthz` 200, Prometheus scraping `/metrics` every 60s,
PVC in the backup allowlist, image private, alerts wired to `#jobs`.

---

## 3. Killing the drift treadmill at the source

**PR:** pi-cluster #131

`drift` kept failing on PRs that had nothing to do with the map. Root cause: the map derived
`repo:TAG`, so **every image bump was a map change** — and Flux's `ImageUpdateAutomation` pushes
those straight to `main` with a deploy key, which *structurally* bypasses the PR gate that
regenerates the map. `main` carried a stale map and the next unrelated PR inherited a red gate.
That tax was paid twice in one day (#125, #126) and would have recurred after every bot bump.

Two options existed: teach the bot to regenerate, or stop deriving the churning field. **Matt
chose the second**, and it is the better trade — a version number is not topology; it is a
property of the *cluster*, and stale the moment it is written.

Proof, rather than assertion: bumped `mcp-homelab` to a fake `:9.9.9`, regenerated, and the map
came out **byte-identical**. 8/8 tag-stripping edge cases (registry ports preserved, digests
stripped), private-image detection unaffected.

> **Consequence worth remembering:** a red `drift` is now much more likely to be *your* change.
> The old reflex — "just regenerate, it's the bot again" — is now wrong.

---

## 4. `nh export` / `nh import` — and what building it revealed

**PRs:** new-horizons #22, #24, #25, #26 (issue #23)

"Seed the 25 leads" could not be done from the harness (no data, no `kubectl exec`) — but
attempting it surfaced that the documented method was **unsafe**, and then that a whole capability
was missing.

- **#22** — the runbook said `kubectl cp` onto the live `/data/new-horizons.db`, a non-atomic
  write over a file two readers hold continuously. A read landing mid-copy gets
  `database disk image is malformed`. Replaced with copy-beside-then-`mv` (atomic rename).
- **#23** — `nh list --json` emitted 5 of 13 columns and dropped `url`, part of the dedupe key.
  It *looked* like an export and could not round-trip a lead. That is why seeding had to be a file
  copy at all.
- **#24/#25** — spec-first, then the supervised qwen loop. **Four defect classes escaped a gate
  that had been validated two ways before handoff** (reference implementation 15/15, mutation
  testing 5/5). Each was caught by reading the diff above a green result:

  | class | what escaped | why the gate was blind |
  |---|---|---|
  | fail-open ordering | built nothing, littered `temp_head`/`temp_tail`, returned **PASS** | presence gate exited 0 *before* the scope check |
  | assertion theatre | `--dry-run` always `(0 new, 0 updated)` | asserted the *string* "dry-run" appeared |
  | symmetric round-trip blindness | two trailing newlines | round-trip compares equal when both sides are wrong |
  | fixture coincidence | ids `[1,3]` → `[1,2]` | fixture seeded ids 1,2 — autoincrement reproduces them |

  The loop escalated correctly, exhausting 4 attempts on the last one and stopping with *"needs a
  human"*; the final fix needed judgment it did not have.
- **#26** — with a lossless export, seeding stopped needing a file copy at all:
  `nh export | kubectl exec -i … -- nh import -`. That does not mitigate the earlier hazards, it
  **removes** them — no live-file write, no schema replacement, idempotent, reviewable.

> **The behavioural finding, handed to the judge-loop work:** the loop fixes precisely what is
> **gated** and regresses what is merely **described**. And *a fixture that cannot fail is worse
> than no fixture* — it purchases false confidence and survives review because the line is green.

---

## 5. The recurring pattern

Five independent instances, none of them looked for:

| where | the signal that could not fail |
|---|---|
| `get_dns_status` | `healthy` pinned false by completed CronJob pods |
| Pi-hole stats | `401` blamed on a credential for months; then `429` blamed on it again |
| new-horizons | an ExternalSecret red forever by design |
| `gate-score.sh` (laptop side) | discarded the verifier's exit status; ties permitted check deletion |
| `specs/export` gate | `pend` returned PASS for "built nothing" |

Each one trains its readers to ignore it, and then hides the real failure behind it. The
countermeasure that emerged — **red-before-green** — is cheap and mechanical: every new assertion
was run against a known-bad build first and required to *fail*, naming the observed wrong value,
before a PASS was trusted.

---

## 6. Artifacts left behind

- **Judge calibration corpus** — `calib/gap1-nothing-built`, `calib/gap23-newline-dryrun`,
  `calib/gap4-id-renumber`, `calib/fixed` in new-horizons. Four seeded defects at commits where
  **the gate was green and the code was wrong**, ground truth re-measured per tag. A spec the
  judge did not build, *with an answer key*, so its first external run measures recall rather than
  plausibility. Predictions were written down in advance.
- **Gate-gap taxonomy** — `specs/judge-loop/evidence/2026-08-03-harness-gate-gap-evidence.md`.
- **Incident** — see §2 of the laptop recap and `docs/incidents/`; root cause fixed in #133.

## 7. Open

- **Seed the 25 leads.** Method ready and now a single pipe; needs the laptop. *Still not done.*
- **Run the judge calibration.** Laptop-side — `codex` is not on PATH in the harness container.
- **Phase F** (reactive n8n ingestion) — blocked on real job-alert `.eml` samples.
- **Sweep the remaining gates** — `specs/alert|intake|metrics|dossier` share the pend-before-scope
  shape that produced defect class 1; it already caused the identical STOP on `intake` and `alert`.
  Agreed with laptop-claude: one PR per shape-fix.
