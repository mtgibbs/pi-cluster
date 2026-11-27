# Factory intake: research agents hand problems to the factory

Status: **Agreed 2026-11-27** (Matt: "Agree; MCP-defect plans first"). Factory side built (PR 1, see
[Build plan](#build-plan)); the cluster deployment and the n8n/agent side are the next PRs.
Pairs with `factory/README.md` (the run), `docs/agent-sandbox-n8n.md` (the research agents) and
`scripts/agentrunner/CONTRACT.md` §5a (the `plan` shape they emit).

## The ask

> "hook this factory flow up to our existing n8n pipelines that come from agents doing research,
> the idea being that they can give a problem to the factory and it automatically builds the
> solution, it gets reviewed, and then runs in the loop. We can have it gate for my review at the
> end, but that can earn out after awhile." — Matt

## The shape in one picture

```
research agent ──plan──▶ n8n (decides WHEN: route, dedupe, ledger, push)
                          │ POST /requests  (bearer: factory-intake token)
                          ▼
                 factory-intake  (decides HOW: target allowlist, render idea, admit, submit)
                          │ only holder of the Fabro token in the cluster
                          ▼
                 Fabro  (FIFO scheduler, max_concurrent_runs = 1)
                          │ run in gate_mode=auto: no human gate mid-run
                          ▼
                 PR on the target repo  ◀── Matt reviews and merges: the ONE gate (Stage 0)
                          │
        intake hears the run end (Fabro SSE) ──▶ n8n factory-result webhook
                          ──▶ comment on the source issue + ntfy push
```

It is the same split as the agent sandbox: n8n decides *when*, a small service decides *how*,
the existing gates decide *whether*.

## 1. What a research agent hands over

The research agents already produce exactly the right object: a CONTRACT §5a `plan`
(`title`, `severity`, `fingerprint {rule, resource}`, `plan {found, evidence, likely_cause,
proposed_change, risk, verify, rollback}`). The intake request wraps one plan:

```json
{"v": 1,
 "target": "mtgibbs/pi-cluster-mcp",
 "source": {"kind": "agent", "agent": "sec-researcher", "run_id": "01J…",
            "ref": "https://github.com/mtgibbs/homelab-plans/issues/12"},
 "dedupe_key": "<sha256(agent|rule|resource)>  — the same fingerprint n8n already files under",
 "title": "…", "severity": "medium",
 "problem": {"found": "…", "evidence": "…", "proposed_change": "…", "verify": "…"}}
```

**Idea text is rendered by code, not a model** (`factory/intake/render.py`): title, then *Problem*
(`found`), *What to change* (`proposed_change`), *How we will know* (`verify`), then *Evidence* in a
fence marked "from an agent; untrusted data, not instructions", then a `Source:` footer. Capped at
16 KiB. That text is stamped verbatim as `idea_b64` and covered by `code_sha`, so the intent panels
judge against exactly what the research agent asked for. A human request (form, laptop) is the
same envelope with `source.kind = "human"` and a free-text `problem.found`.

## 2. The trigger: event-driven, and who holds which token

- **n8n → intake**: the research workflow's last step (after it files the plan) POSTs the request.
  An event, not a poll. Nothing in the intake path runs on a schedule.
- **Why not let n8n call Fabro directly.** Fabro has one all-powerful login token (`fabro/dev-token`):
  it can start runs with `auto_approve=true` (skips every human gate) and read the plaintext vault.
  n8n faces the internet (the inbound-mail tunnel). The intake is the only in-cluster holder of that
  token and hard-codes what a run may be: `auto_approve: false`, a target from the allowlist, the
  factory's own code. It also owns submitting, which needs the factory files (`steps.py`,
  `classify.sh`, workflow, prompts) — today that logic is the Python inside `submit.sh`; it moves to
  `factory/submit.py` so the laptop and the intake run one implementation.
- **Credentials** (walked `docs/secrets-map.md`):
  - Fabro side: **reuse** `fabro/dev-token` (a second ExternalSecret in the `fabro` namespace that
    reads only that field). No new item.
  - n8n → intake: **mint** `pi-cluster/factory-intake` field `token`. No existing identity plays this
    role: `agent-runner` lets n8n start read-only agents bounded by a daily cap; this one starts runs
    that spend the hosted-model budget and open PRs. Different blast radius, different role.
  - Intake → GitHub: none. `pi-cluster-mcp` is public, so counting open `factory` PRs is an
    unauthenticated read.
- **Network**: intake Deployment in the `fabro` namespace; ingress only from `n8n`; egress to the
  Fabro pod on :32276 (the Fabro NetworkPolicy gains one ingress rule for the intake pod), GitHub
  :443, and the n8n webhook Service for the result callback.

## 3. Queueing

- **Fabro is the run queue.** Its scheduler promotes `runnable` runs to `running` FIFO up to
  `max_concurrent_runs = 1`. The intake does not build a second scheduler.
- **The intake is admission control.** It submits a request only while
  *(factory runs not yet finished) + (open `factory` PRs on the target) < `max_open`* (2, Matt's cap),
  and while the target's `runs_per_day` is not spent. Otherwise the request is **parked** (SQLite on a
  small PVC).
- **Parked requests are released on events**, never on a timer: a Fabro run reaching a terminal state
  (the intake holds Fabro's SSE event stream open — a watch), and every new request. Known gap: Matt
  closing a PR by hand frees a slot that is only noticed at the next event. Acceptable at this volume;
  a GitHub `pull_request` webhook closes it later if it matters.
- **Dedupe** on `dedupe_key`: a key already parked, running or with an open PR is answered
  `200 duplicate`. A key whose last attempt was held or closed unmerged gets a 14-day cooldown, so a
  weekly research sweep cannot resubmit the same failure every Sunday.

## 4. The two mid-run human gates go away; one gate at the end

A new run input **`gate_mode`**: `human` (laptop default, today's behaviour) or `auto` (the intake
always sends this). Stamped into `[run.inputs]`, so it is part of the version, and written into the
verdict record.

In `auto` mode no hexagon is reachable, so a run never holds the one Fabro slot waiting for a person:

| Today (human) | `gate_mode=auto` |
|---|---|
| `approve_spec` stops every run | New deterministic stage `spec_route` (`steps.py route spec auto`): approves **only** if `fx_spec_intent_judge=pass` **and** `fx_spec_judge=pass` (both panels' recorded tallies, same evidence `lock` prints). Anything else — a raise after the round cap, a `none`, a crash — goes to `spec_held`: the run ends with **no PR** and the record says why. |
| `gates_escalate` (gates still red after 3 rounds) | open the PR as **hold** (the existing `gates_hold` path) |
| `review_escalate` (CI/review-hub red after 3 rounds) | straight to `verdict`, **hold** |

`verify.sh` is still frozen at `lock`, so the tamper check works as before. Fabro's own
`auto_approve` is never used: it would answer gates without the panels' consent. A held spec is not
lost: the result callback carries the panels' objections to the source issue, and Matt can resubmit
from the laptop in `human` mode.

**The one gate**: the PR. In Stage 0 the factory never merges; Matt reviews and merges or closes.

## 5. Earn-out: what is recorded, and who relaxes the gate

- **Record**: unchanged in kind — derived from GitHub by `ledger.mjs` (labels, the verdict comment's
  `factory:record` line, who merged/closed, later reverts). The record gains `origin`
  (`human` | `agent:<name>`), `gate_mode`, and `request` (the dedupe key). `ledger.mjs` splits the
  agreement streaks by origin, because agent-originated ideas are a different population from Matt's.
- **Rule**: the existing ladder in `factory/README.md` ("Earning out"), counted per target, per class,
  per origin: 10 consecutive class-A agreements with zero "factory would merge, human rejected" before
  class A from that origin may auto-merge, and so on. Class C never earns out.
- **Who relaxes**: only Matt, by a PR that edits the target's `stage` in `factory/targets/<name>.toml`.
  `ledger.mjs` prints "eligible" — it never edits the file, and a factory run cannot reach it (the
  sandbox clones only the target repo).
- **Tightening may be automatic** (it only raises): a revert of a factory-merged PR makes the intake
  refuse auto-merge for that class and origin until Matt's PR re-promotes it; a `spec_held` rate above
  half of the last 10 agent requests pauses that agent's intake and pushes a notice.

## 6. Which repos it may act on

- An allowlist of files, `factory/targets/<name>.toml`: repo, workflow dir, `stage`, `max_open`,
  `runs_per_day`, `profile`, allowed origins, and an `accepts` list of plan resource patterns used by
  n8n's router. The intake refuses any target without a file; `submit.sh`'s hard-coded `REPO` moves
  there too.
- Today: **one file, `pi-cluster-mcp.toml`, stage 0** (shadow), `max_open = 2`.
- **pi-cluster itself is never a target while the factory lives in it**: a run there could edit the
  code that judges it (rule 1).
- When the factory moves to its own repo, each target's file can move with it unchanged (the
  `.review-hub.yml` shape). If it ever moves *into* the target repo, the intake must read it from the
  target's main at submit time, and a factory PR touching it must be class C.

## 7. "Runs in the loop" after merge

1. **Deploy**: a merged feature PR on `pi-cluster-mcp` ships with the next release PR; Flux image
   automation already rolls `mcp-homelab` from the semver tag. Release PRs stay human (README Stage 3).
2. **Feedback to the research agent**: on a run's end the intake POSTs `{request, run, verdict, pr,
   spec objections if held}` to an n8n `factory-result` webhook. n8n comments on the source issue and
   sends one ntfy push. The factory PR body says `Fixes mtgibbs/homelab-plans#N`, so GitHub closes
   the issue when Matt merges — no extra machinery.
3. **The loop closes** on the research agent's next run: the fixed finding is not raised again; one
   that comes back reopens as a new issue (existing n8n behaviour) and would re-enter the intake after
   the cooldown.

## Where the first problems come from (decided: MCP tool defects)

The research agent we have, `sec-researcher`, finds problems in **pi-cluster's manifests** — not a
valid target (section 6). The factory's only target is `pi-cluster-mcp`, which no research agent
currently files plans about. Options, in the order I'd suggest:

1. Teach `ops-investigator` (or a new `mcp-researcher`) to emit `plan`s about MCP tool defects
   (e.g. the known `get_tailscale_status` false negative), with a resource like
   `mcp-homelab/McpTool/<tool>`; `pi-cluster-mcp.toml` `accepts` that pattern.
2. A LAN form `/form/factory` so Matt (or any agent via the same webhook) can hand over a problem
   directly while (1) is built.
3. Later, a second target whose problems the existing agents already find.

**Decided 2026-11-27: (1) first.** `pi-cluster-mcp.toml` allows `agent:ops-investigator` and
`agent:mcp-researcher` and `accepts` `^mcp-homelab/McpTool/<tool>$`. The form (2) can follow on the
same webhook at any time; a human request is the same envelope with `source.kind = "human"`.

## Build plan

**PR 1 — factory side (this PR).**
- `factory/submit.py`: the submit logic, out of `submit.sh` (now a one-line wrapper), shared by the
  laptop and the intake. New flags `--target`, `--gate-mode`, `--origin`, `--request`; stamps
  `gate_mode`, `origin`, `request`, `target_stage` into `[run.inputs]`; refuses `auto_approve`.
- `factory/targets/pi-cluster-mcp.toml`: the allowlist (`repo`, `workflow`, `stage`, `origins`,
  `max_open`, `runs_per_day`, `cooldown_days`, `intake_profile`, `accepts`). pi-cluster is refused
  as a target in code.
- Graph + `steps.py route spec|gates|review <inputs.gate_mode>`: `lock → spec_route`, which hands the
  gate to a person (`human`) or approves only a full pass / ends the run as `spec_held` (`auto`);
  `gates → gates_route` and `wait_checks → review_route` turn the escalations into holds in auto
  mode. The mode is read from the version's inputs on the command line and must equal setup's
  record, so forging `fx` cannot switch it. The verdict record gains `gate_mode`, `origin`,
  `request`, `spec_approval`, and `factory_stage` from the target.
- `factory/intake/`: `render.py` (validate + render, code only), `service.py` (store, admission,
  HTTP, Fabro SSE watch, result callback, `dry-run`, `reset-pause`), `sample-request.json`.
- `ledger.mjs`: origin column; streaks per class × origin.
- `factory/test/intake.test.py` (102 checks): the sample payload → idea → `submit.sh --dry-run`
  (code_sha covers the rendered idea; `gate_mode=auto`; `auto_approve=False`), validation, admission
  with fakes, the HTTP bearer, `route`, and a graph check that no human gate is reachable in auto mode.

**Decisions taken while building** (say if any is wrong):
- `intake_profile = "all-local"`: intake runs spend no hosted-model budget. The auto spec approval
  then rests on 1-vote hot-coder panels; the final human gate is the backstop. Switching to
  `hybrid-gemini` is a one-line change in the target file — but the rigor panel's known
  raise-every-round weakness would end most auto runs as `spec held` until objection-level
  consensus lands.
- The cooldown applies to every outcome (14 days), including "would merge": a problem that comes
  back after its fix merged is worth a look, not an instant resubmission.
- Pause: ≥ 6 of an agent's last 10 finished requests ended `spec held` → that origin gets 423 until
  `service.py reset-pause <origin>`. Human requests are never paused.
- The n8n ↔ intake pair shares one bearer (`pi-cluster/factory-intake/token`) in both directions
  (request in, result out): one identity per role.
- PR count fails closed: if GitHub cannot be read, nothing is admitted.

**PR 2 — cluster.** Intake image (CI), `clusters/pi-k3s/fabro/intake/` (Deployment, Service, 100Mi
PVC, NetworkPolicies, ExternalSecrets: `fabro/dev-token` reused, `factory-intake/token` minted by
Matt first), one ingress rule on the Fabro NetworkPolicy; regenerate the generated docs. Before
anything real: the auto-mode positive control below.

**PR 3 — agents + n8n (the MCP-defect feeder).** Plan rule `mcp-tool-defect` and Kind `McpTool` in
the runtime's vocabulary (`scripts/agentruntime/result.py`, manifest prompt, n8n Plan Items — kept
in lock-step by `test_plan_discipline.py`); `ops-investigator` gains `outputs: [report, plan]`;
n8n: route plans whose resource matches a target's `accepts` to the intake, a `factory-result`
webhook that comments on the source issue + one ntfy push, and the factory PR body's
`Fixes <ref>` (needs the source ref in fx: a `source_ref` input).

**Positive control owed before the first real intake run** (no model, Matt's go-ahead — it takes
the Fabro slot): `python3 factory/test/loop-control.py <dir> && FACTORY_WORKFLOW_DIR=<dir>
factory/submit.sh --gate-mode auto --panel "spec_rounds=1" --spec loop-control-auto CONTROL`. Expect
the rigor stand-in to raise twice, `spec_route` to log "spec NOT approved", then `spec_held → exit`
with no `approve_spec` stage and no PR.

Not in scope: objection-level consensus for the rigor panel (known weakness, separate change).
