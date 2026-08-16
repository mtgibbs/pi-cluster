# Recap — model onboarding, what a gate is worth, and 44 hours of silence (2026-08-11 → 16)

Started as a research question about one inference engine. Ended with a repeatable
onboarding process, a measured answer to "how good is the local coding loop", and a
cluster-wide incident that had been running for nearly two days before anyone noticed.

Seven PRs across two repos. One theme connects almost all of it, so it goes first:

> **A check that cannot fail certifies nothing — and reads as coverage while it does so.**

It shows up three times below, in places that have nothing to do with each other. This is a
close cousin of the theme in [`2026-08-03`](2026-08-03-pihole-newhorizons-drift.md) ("a
signal that cannot fail stops being read"); the difference is that *those* signals were
ignored, and these ones were **trusted**.

---

## 1. Colibrì — a real trick, wrong hardware (#153)

Colibrì runs GLM-5.2 (744B) on 25 GB of RAM by keeping the int4 dense trunk resident and
streaming **21,504 experts** off NVMe — ~11 GB of expert reads *per token*. The claim is
true, and it is also the entire cost model: capacity comes from disk, latency is paid in
disk reads.

**Verdict: not now.** What makes that confident rather than hand-wavy is
[issue #124](https://github.com/JustVugg/colibri/issues/124) — someone benchmarked a
**Ryzen AI Max+ 395 with 128 GB unified**, our exact silicon. Tuned, CPU-only, best
sustained **1.10 tok/s**. Three blockers, two of them untunable:

- **Drive class.** Two SSDs on identical silicon: DRAM-less Kingston **0.55 tok/s**, SK
  hynix P41 **0.81–1.24**. The binding constraint is *random-read latency at low queue
  depth*, not bandwidth. Our Crucial P310 is Phison E27T, DRAM-less/HMB, 232-layer QLC —
  the slower half. Projects to **~0.5 tok/s**, ≈15 min for a 500-token answer.
- **RAM.** Auto-pin wants 37–47 GB of page cache. The #124 tester had all 128 GB free
  (iGPU unused); we carve ~96 GB as VRAM and work-mode Q8 holds ~85 GB.
- **Thermals.** SSD controller 56 °C → 84 °C mid-run in a conventional desktop. The GTR9
  Pro is SFF.

Full analysis + four falsifiable revisit triggers:
`docs/research/colibri-moe-disk-streaming.md`. The idea worth stealing regardless is
**persisted compressed KV across sessions** (~182 KB/token to disk, zero re-prefill on
resume) — it targets the "compute redo" copy that `kv-sizing-and-sessions.md` already flags
as our remaining one.

## 2. The onboarding runway (#153, #157)

`docs/model-eval-2026-05.md` was a good one-off; every candidate since restarted from zero.
`docs/model-onboarding.md` generalises it: intake gates, the VRAM/KV math to run *before*
downloading, a stand-up decision tree, and a **decision log backfilled with every verdict
since May** — the part that stops the next evaluation starting at zero.

`model-watch` (#157) is §0 of that runbook made real: a monthly CronJob that answers the
question leaderboards can't. Not *"what's the best open model"* — nothing in that tier has
fit this box since mid-2026 — but **"what's the best model that fits ~96 GB."** HF API
supplies every number (params, MoE sparsity, licence, Q4 fit are **computed**, so the
digest can't invent a model); only gate-clearing candidates get their README read by the
Beelink for what metadata can't express.

Two filters found by *running* it, not by reasoning: derivative repos must be dropped via
HF's `base_model:` relation tag **but a vendor's own instruct-tune of its own base is a
real release**; and MoE config keys aren't standardised — checking only the Qwen spelling
reported a 35B-A3B model as "dense 7.3B".

**Worth acting on:** `Qwen3-Next-80B-A3B-Instruct` was selected in May and never deployed
— ~59 tok/s measured on this box class, non-thinking Instruct, Apache-2.0, needs only a
second llama.cpp-vulkan server. Highest value per unit of effort currently on the shelf.
New and fitting: `inclusionAI/Ling-3.0-flash` (MoE 127.5B, 8/512 active, ~71 GB Q4).

## 3. The loop is exactly as good as its gate (#155, #158, #161)

Three ralph runs on `specs/model-watch`, one variable each — full write-up in research log
§17.

| Run | Gate | Facts pinned | Result |
|---|---|---|---|
| 1 | monolithic, 2 verdicts | no | STOP on T1. Best attempt **17/19** |
| 2 | staged (`pend`/`STRICT`) | yes | **All 4 tasks passed, STRICT passed** — 6 real defects shipped |
| 3 | staged + behavioural fixtures | yes | refused 3× → STOP |

**Run 2 is the one to remember.** It reported `VERIFY: PASS` while producing `ssl.CERT_NONE`
on a request carrying an API key, ntfy auth that would 401 silently forever, an MoE parser
reading `512 total / 10 active` as `10 / None`, and a card fetcher that always returned
`None`. *Every one of those greps fine.* Run 3 — same model, same spec — was refused three
times by a gate that actually executes the code against recorded fixtures with known
answers.

Three findings shipped into `specs/TEMPLATE.md`:

- **The three-verdict contract already existed** (`pend` + `STRICT`) and the template never
  documented it, so a spec written from the template alone gets a two-verdict gate where
  task 1 is gated on task 4's work. Presence-gate on the **artifact**, not the task number.
- **Task lines anchor harder than the spec does.** Same everything: *"write model-watch.py
  — the sweep, the gate logic, the DRY_RUN output contract"* → 17/19. *"implement the whole
  model-watch feature"* → the model built what the **name** suggested (a filesystem poller
  watching `/models`) → 7/19.
- **Verify in both directions.** Testing the hardened gate against known-good code caught a
  false negative in the gate *and* a genuine contract break in the human-written reference
  implementation that review had missed.

Also learned the unglamorous way: `model-watch` was ~30% pattern-stamping and ~70%
discovering undocumented API behaviour. qwen scored 17/19 on the former and zero on the
latter. **The fair-comparison spec and the effective spec are different documents** —
withholding the API facts to keep an experiment clean is the same thing as writing a bad
spec, since §6a exists precisely to pin literal facts.

## 4. The ESO incident — 44.5 hours, found by accident (#159, #160)

`ClusterSecretStore/onepassword` died **2026-08-11 ~20:30 UTC**. The `onepasswordSDK`
provider runs the 1Password SDK as an Extism/WASM plugin; `init_client()` trapped with
`out of bounds memory access`. **53 of 56 ExternalSecrets** stopped refreshing.

It was invisible by construction: failing ExternalSecrets keep their last-synced value, so
every materialised Secret stayed intact, every workload kept running, every dashboard
stayed green. The pod reported `Running 1/1` with **0 restarts** — a liveness probe would
not have fired, because the *process* was healthy; its embedded runtime wasn't. Rotation
was dead and no new secret could be created, and it surfaced only because an unrelated docs
merge triggered a Flux re-reconcile someone happened to look at.

**The real defect was that ESO had no metrics scraped at all** — not a missing alert rule,
no telemetry. The chart's `serviceMonitor` was never enabled, so `:8080` existed and was
never read. Any rule written against ESO metrics would have matched nothing and reported
healthy. *That is worse than having no rule.*

Fixed in #159: `serviceMonitor.enabled`, three alerts (store-level primary — one cause, 53
echoes), and a **512Mi memory limit as deliberate self-healing** — `resources: {}` is why
this ran 44 hours instead of 4 minutes.

Merging #159 also *ended* the outage: adding `resources:` mutates the Deployment pod
template, so Flux ran a Helm upgrade, the controller rolled, and a fresh process meant a
fresh WASM host. Last error 17:02:22, first `reconciled secret` 17:02:29.

**Two corrections worth preserving**, both mine, both mid-incident:

1. *"A restart probably won't help — ESO has been retrying continuously."* Backwards.
   Retrying **inside the process** never resets WASM host memory. The persistence was
   evidence *for* a restart.
2. *"A rolling restart won't discriminate WASM-exhaustion from a malformed token."* It did.
   The token was never touched and works fine in a fresh process; a malformed value would
   have failed identically. Credential exonerated.

Incident doc: `docs/incidents/2026-08-11-eso-onepassword-wasm.md`.

## 5. Harness gaps this exposed

- **`restart_deployment`'s whitelist was applications-only**, so the agent could root-cause
  the incident and not act on it. `pi-cluster-mcp#53` adds the ESO controller only —
  webhook excluded (restarting it can block every admission request) and the Flux
  controllers excluded (they're how every change reaches the cluster; that deserves its own
  decision, not a drive-by). All four denials asserted in tests.
- **`reconcile_flux` accepts only `kustomization` and `helmrelease`, not `gitrepository`**,
  so the documented *reconcile-source-first* order isn't expressible through the MCP.
  Reconciling a Kustomization before the source has fetched the new commit is a no-op.
- **opencode built an absolute path** (`Read /specs/model-watch/spec.md`) and was
  auto-rejected as an external directory, so that attempt wrote nothing — and then
  **passed**, because an empty tree satisfies every `pend`. `ralph-qwen.sh` now treats a
  no-op attempt as a failure.

---

## Where things stand

| Item | State |
|---|---|
| Colibrì | Rejected with revisit triggers. No cluster footprint |
| `docs/model-onboarding.md` | Live on main, decision log backfilled |
| `model-watch` CronJob | **PR open** — needs the `model-watch/litellm-key` 1Password item |
| SDD template + fixture harness | Live on main |
| ESO store | Healthy. 0 restarts, ~3 days uptime as of 2026-08-16 |
| ESO alerting | Live — metric names still want confirming against Prometheus now that scraping exists |
| `pi-cluster-mcp#53` | **PR open** |

**Watch item:** if the WASM host leaks on a schedule, the 512Mi limit converts a 44-hour
silent outage into a periodic self-healing restart. Good trade — but a recurring OOM-restart
would confirm a real leak worth reporting upstream rather than absorbing. Controller uptime
is the number.
