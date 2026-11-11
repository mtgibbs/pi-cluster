# Agent sandbox — n8n hands an event to a short-lived, least-privilege agent

**Status:** Draft design, revision 3. Not built. Nothing here is deployed.
**Date:** 2026-11-11
**Asks of Matt:** the [open questions](#11-open-questions-for-matt) at the end.

## 0. The goal

Today, when Matt sees a problem, he opens a Claude session and has it investigate. This design automates that
operator flow:

- n8n is the workflow and state engine. It receives an event (an alert, an email, a line Matt typed) and hands it to
  the right agent.
- Each agent runs in a throwaway sandbox holding only the connectors, MCPs and credentials its job needs.
- **Inside the sandbox, the agent can orchestrate whatever it wants.** Outside it, the agent can do only what its
  manifest allows.
- The outcome is not always a system change. One agent opens a plan for a cluster fix; another puts an appointment on
  the family calendar.

The security aim is that a rogue or hijacked agent cannot break something or act outside its responsibility, because it
never held the means to.

## 1. What exists

| Piece | What it is | What it lacks for this goal |
|---|---|---|
| **n8n** (`clusters/pi-k3s/n8n/`) | Queue mode, Postgres, eight workflows. The email pipeline already makes inline model calls for kid and appointment mail. | It cannot start an agent. Workflow JSON is not applied by Flux. |
| **jig fleet dispatcher** (`clusters/pi-k3s/harness-fleet/`) | The one identity in the cluster that may create Jobs. It launches a build-loop worker for a spec. | It only knows "build this spec". It cannot be handed an event, and nothing calls it. |
| **jig** (`mtgibbs/jig`) | A method for code changes: a spec plus gates, with mutation-tested gates. | It is a way of *doing* a change, not a way of *running* agents. |
| **review-hub** (`clusters/pi-k3s/review-hub/`) | PR judges, as GitHub checks, with short-lived GitHub App tokens. | Nothing. It keeps doing this job. |
| **CI gates** (`.github/workflows/`) | The drift gate and lints. | pi-cluster `main` has no required checks yet. |
| **Sandboxing** | The fleet namespace has quota and limits. | No app namespace has a NetworkPolicy or enforced pod security. |

Prior decisions this design keeps:
- PR to publish, always. The human checkpoint is the point.
- Reactive, not scheduled.
- Credentials scale by role; nothing standing where a short-lived token will do.
- No AI-facing tool holds standing access to a real inbox.
- Everything as code.

## 2. Separation of concerns

Four parts. Each knows nothing about the others' insides.

| Part | Its one job | Knows nothing about |
|---|---|---|
| **n8n** | *When.* Receive events, drop duplicates, decide which agent runs, wait, act on the result, ask Matt | How an agent runs or what it does inside |
| **Runner** (new, small) | *How.* Turn "agent X, event Y" into a sandboxed Job with that agent's credentials, and return its result | Why it was asked; what the agent does; specs, gates, GitHub workflow |
| **Agent** (an image + a manifest) | *What.* Do the work, using whatever it likes inside the sandbox | Who triggered it or what happens next |
| **Gates** (CI, review-hub, Matt) | *Whether.* Judge a proposed change | Who or what wrote it |

```
 Alertmanager ─┐
 Flux ─────────┤                 ┌──────────── runner ────────────┐
 Uptime Kuma ──┼─▶ n8n workflow ─┤ POST /runs {agent, event,      │──▶ Job (sandbox)
 inbound mail ─┤     │    ▲      │             callback}          │      │ agent does its work
 Matt (a line) ┘     │    │      └────────────────────────────────┘      │
                     │    └──────────── result (validated JSON) ◀────────┘
                     ▼
        n8n acts on the result: notify · ask Matt · write the calendar · run the next agent
```

Three contracts hold it together. Anything that honours them can be swapped.

1. **Event** — what n8n hands over.
2. **Agent manifest** — what an agent is and may touch.
3. **Result** — what comes back.

### 2.1 Event

```jsonc
{
  "id": "01JD…",                       // unique
  "type": "media.hang",                // a name, used by n8n to pick the workflow
  "source": "matt|alertmanager|flux|kuma|inbound-mail",
  "subject": "jellyfin:apple-tv",      // what it is about
  "dedupe_key": "…",                   // set by the source's adapter; n8n drops repeats
  "trust": "internal|external",        // external = may hold text an attacker wrote (email, PR text)
  "data": { /* small, ≤ 64 KiB. Refs where possible; inline text where that is the task (an email body) */ }
}
```

- Dedupe is one table in n8n's Postgres with a unique key. Alertmanager re-sends a firing alert every 1–4 hours, so
  this matters from the first day.
- **Matt can send an event by hand.** A form in n8n (and later an ntfy or Matrix line) takes "investigate: jellyfin
  hung on the Apple TV" and produces the same event an alert would. This is the "come over here and make Claude run"
  path, minus the session.

### 2.2 Agent manifest

One YAML file per agent, in Git, at `agents/<name>.yaml`. It is the whole answer to "what can this agent touch?". The
runner refuses to launch an agent whose manifest does not validate.

```yaml
kind: Agent
name: media-investigator
purpose: "Find out why a media client hung. Report; change nothing."
image: ghcr.io/mtgibbs/agent-runtime-claude:0.1.0
model:
  key: agent-media-investigator        # its own LiteLLM key, with a daily budget
  allow: [hot-coder, claude-haiku]     # local first; the small hosted model as fallback (5.4)
data_class: system                     # system | personal (see 3.3)
connectors:                            # everything it can reach. Nothing else is routable.
  mcp:
    - server: homelab-readonly
      tools: [get_pod_logs, get_events, list_pods, get_jellyfin_sessions]
  http:
    - loki-read
  github: []                           # no repo access
outputs: [report]                      # the kinds of result it may return (2.3)
limits:
  timeout: 15m
  runs_per_day: 10
```

- The manifest says what the agent **may** do. It does not say **when** it runs. That is an n8n workflow's business,
  which is what keeps the two composable: the same agent can be used from an alert, from Matt's form, or as a step in a
  longer workflow.
- An agent that wants jig's spec-and-gate loop, sub-agents, or its own scratch tooling ships that in its image. The
  runner does not care.

### 2.3 Result

The agent's last act is to write one JSON result. The runner validates it against the manifest's `outputs` and passes
it to n8n. A missing or invalid result is a failure, never a silent success.

```jsonc
{
  "outcome": "done|nothing_to_do|needs_human|failed",
  "summary": "≤ 2 KiB, plain words",
  "outputs": [
    {"kind": "report", "title": "…", "body_ref": "…"},
    {"kind": "calendar_event", "calendar": "family", "title": "Dentist — Rory", "start": "…", "end": "…"},
    {"kind": "plan", "issue_url": "…"},
    {"kind": "pull_request", "url": "…"}
  ]
}
```

## 3. Outcomes — who performs the side effect

This is the rule that keeps an agent inside its responsibility. There are two ways an outcome reaches the world, and
the agent only ever performs the first.

| | The agent does it | n8n does it |
|---|---|---|
| **What** | Writes a *proposal* somewhere a human gate already stands: a plan issue, a draft PR | Applies a *structured result* to a system: a calendar entry, a database row, a notification |
| **Credential** | A token minted for that run, scoped to that one repo and that one permission | n8n's own credential. **The agent never holds it.** |
| **Check before it is live** | The plan needs Matt's approval; the PR needs the checks and Matt's merge | n8n validates the result against a schema, then applies it, or asks Matt first (per workflow) |

So a calendar assistant never holds calendar access. It returns `calendar_event` items, and the n8n workflow, which is
deterministic and reviewed, writes them. A hijacked assistant can at worst propose a wrong appointment.

### 3.1 Matt's two examples

**1. The kid-and-appointment emails.** Yes: it is the same contained loop, and its outcome is data, not a system
change. It already works this way. The inbound-mail workflow makes one model call and n8n writes the row.
- It does not need a container today, because it is a single model call with no tools. Think of it as an *inline
  agent*: the same event-in, result-out contract, run inside n8n.
- It would move into a sandbox only when it needs tools or several steps, for example "read the PDF, check the family
  calendar for conflicts, propose a time". The workflow around it would not change.

**2. "We noticed the Jellyfin client hang, launch an investigation."** Yes: it is just another container with a
different manifest. `media-investigator` above gets the Jellyfin and log connectors and nothing else. `ops-investigator`
gets Flux and cluster-read tools. Neither can reach what the other can.

### 3.2 The agents this starts with

| Agent | Triggered by | Connectors | Outputs |
|---|---|---|---|
| `sec-researcher` | A merge touching access-control manifests; a weekly sweep; Matt | Repo read, cluster-read MCP | `plan` |
| `ops-investigator` | Alertmanager, Flux failures, Uptime Kuma; Matt | Cluster-read MCP, Loki | `plan` or `report` |
| `media-investigator` | Matt; media alerts | Jellyfin and media read tools, Loki | `report` |
| `ops-fixer` | A plan Matt approved, and nothing else | One repo, branch and PR only | `pull_request` |
| `family-assistant` | Matt; the mail workflow, when a message needs more than one step | None beyond the model | `calendar_event`, `note` |

Adding an agent is one manifest, and one n8n workflow or one more branch in an existing one.

### 3.3 Personal data stays local

An agent with `data_class: personal` (family mail, calendars, school data) may only use models served on the Beelink.
The runner enforces this: it refuses a `personal` manifest whose `model.allow` names a hosted model. System agents may
use Claude. This is the email rule applied to agents, for privacy. (Decided 2026-11-11.)

## 4. n8n as the workflow and state engine

A flow is an ordinary n8n workflow. The only new building block is a **Run agent** step:

1. `POST` to the runner with `{agent, event, callback: <this execution's resume URL>}`.
2. Wait. n8n's wait-for-webhook holds the execution, for minutes or days, with a timeout.
3. The runner calls back with the result. The workflow carries on.

Everything else is what n8n already does well: branch on the result, notify, wait for Matt, call the next agent.

```
alert-investigate:   webhook → dedupe → Run agent(ops-investigator) → notify Matt with the plan link
plan-approved:       webhook(issue labelled by Matt) → Run agent(ops-fixer) → notify Matt with the PR link
mail-appointment:    inbound mail → inline model call → [needs more?] → Run agent(family-assistant)
                       → validate calendar_event → ask Matt (ntfy button) → write the calendar
investigate-by-hand: form → Run agent(<chosen>) → send Matt the report
```

**State lives where a person can see it.** For system work, the plan issue and the PR are the state. For everything
else, the n8n execution is. n8n adds one table for dedupe and one for the run ledger (5.5), and no chain-tracking
machinery.

**Where n8n stops being the right tool:**
- If routing ever needs judgment (an LLM choosing the agent), that belongs in reviewable code. Today routing is "this
  event type starts this workflow".
- If events ever need replay or several independent consumers, that is a real queue (NATS JetStream is small enough for
  a Pi). The event contract does not depend on n8n, so only the transport would change.
- The workflows that run agents must be in Git and applied automatically. Today n8n workflows are imported by hand, so
  a small sync Job is a prerequisite.

## 5. The runner and the sandbox

### 5.1 The runner

A small service, about the size of the existing dispatcher (validate, map, launch, record). It is lifted out of jig so
it knows nothing about specs or gates; jig's build loop becomes one of its clients.

- `POST /runs {agent, event, callback}` → loads `agents/<agent>.yaml` (mounted from Git by Flux) → renders the Job →
  watches it → validates the result → calls back.
- It is the only identity that can create Jobs, and only in the `agents` namespace.
- It accepts calls only from n8n (network policy plus a bearer token).
- It holds the GitHub App key, to mint per-run tokens. That makes it the component to protect: it has no ingress from
  outside the cluster, no LLM inside it, and no logic beyond the table above.
- A kill switch: one setting makes it refuse every launch.

### 5.2 The sandbox

One Job per run, in an `agents` namespace.

| Control | Setting |
|---|---|
| Kubernetes access | None. No service-account token is mounted. Cluster reads go through a read-only MCP. |
| Pod | Non-root, read-only root filesystem, all capabilities dropped, default seccomp, pod security `restricted` enforced on the namespace |
| Workspace | An `emptyDir` with a size limit. Gone when the Job is. |
| Lifetime | The manifest's timeout as a hard deadline. No automatic retries. Cleaned up an hour after finishing. |
| Network | Default deny. Allowed: DNS, the model gateway, and exactly the manifest's connectors. Agents that need the internet (GitHub) get public `443` with every private address range blocked, so **no agent can reach the LAN**. |
| Capacity | A namespace quota of 2 concurrent Jobs. The runner answers "busy"; n8n retries. |
| Placement | The Pi 5 workers. Never the Pi 3 or the master. An agent needs roughly 0.5–1 GiB, so no dedicated node is needed. |

### 5.3 Credentials

| Credential | How the agent gets it | Scope |
|---|---|---|
| Model | A per-agent LiteLLM key, delivered by ExternalSecrets, with a model allowlist and a **daily budget** (5.4) | That agent's models and spend |
| GitHub | Minted per run by the runner from one GitHub App, narrowed to the manifest | One repo, one permission (issues *or* branch-and-PR), one hour |
| MCP | A per-role read-only key | Read tools only, enforced by the server |
| Anything personal (calendar, mail) | **Never.** n8n applies those results. | — |

The Anthropic key lives only in LiteLLM. Agents see capped LiteLLM keys, so Claude spend has one revocation point and
shows up in the existing spend metrics.

### 5.4 Spend and models

The Claude plan gives about **$200 of API spend a month**. Three limits protect it, all enforced by LiteLLM, none by
the agent:

| Limit | Value (start) | What it is for |
|---|---|---|
| Monthly, all agents | **$180** | The one that protects the plan. $20 of headroom. |
| Daily, all agents | **$15** | A spike limiter. A daily cap alone would allow $450 a month, so it is not the main control. One bad day (an alert storm) costs at most about 8% of the month. |
| Daily, per agent | Set in each manifest; they sum to no more than $15 | One noisy agent cannot starve the others |

When a limit is hit, the model gateway refuses the call, the run ends as `failed` with that reason, and Matt is told.
Agents whose manifest allows `hot-coder` keep working, since local models cost nothing.

**Small models by default.** Each agent's key lists the models it may call, so this is enforced, not advised.

| Agent type | Model |
|---|---|
| Investigators, the family assistant | `hot-coder` on the Beelink, falling back to Haiku |
| Researchers | Haiku; Sonnet for the weekly sweep |
| Fixer | Sonnet |
| Any agent | Never Opus |

What a run actually costs is not known yet. The run ledger records spend per run, so a week of slice 1 gives real
numbers to retune these against.

### 5.5 Seeing what happened

- **Logs:** agents log JSON lines with `run_id` and `agent`; the existing pipeline carries them to Loki.
- **Run ledger:** one table. `run_id, agent, event_id, started, finished, outcome, model, spend, output links`. The
  runner writes it.
- **Alerts:** failure rate, spend near a budget, the kill switch being on. Each has a test that proves it can fire.

### 5.6 When things fail

| Failure | What happens |
|---|---|
| The same event arrives twice | Dropped by the dedupe key |
| The runner is down or busy | n8n retries with backoff, then tells Matt. The event is kept. |
| The manifest is invalid | The runner refuses. No degraded run. |
| The Job passes its deadline | Killed. The result is `failed`, with the reason. |
| The agent exits without a valid result | `failed` |
| A spend limit is hit (5.4) | The model gateway refuses; the result is `failed`. Matt is told. Local-model agents keep running. |
| The Beelink is in family mode and the agent needs the work model | The run is parked and replayed on the mode flip, as inbound mail is today |

## 6. The safety rules

These hold for every agent, and each is enforced by something other than the agent's good behaviour.

1. **An agent only reaches what its manifest lists.** Network policy and token scope enforce it.
2. **No agent can reach the LAN or the Kubernetes API.**
3. **An agent proposes; it never applies.** System changes are draft PRs that Matt merges. Personal-system writes are
   done by n8n from a validated result.
4. **Only a human starts a writer.** `ops-fixer` runs only from a plan Matt approved. The approval check looks at *who*
   added the label, because a read-only agent can label issues too.
5. **No agent calls another agent.** Every hand-off goes back through n8n, so every edge is visible in a workflow.
   With rule 4, an agent loop cannot form.
6. **An agent cannot change its own sandbox.** `agents/**` and `.github/**` are off limits to agent PRs, checked in CI,
   and owned by Matt in CODEOWNERS.
7. **Spend and time are capped**, per agent, per day and per month, by the model gateway and the Job deadline.
8. **Text from outside is data.** Mail bodies, PR text and log lines are fenced as data in the prompt. This is a
   mitigation only; rules 1–7 are what bound a hijacked agent.

## 7. System work: plans, fixes and gates

The path for anything that changes the cluster or a repo:

```
event → investigator or researcher (read-only) → plan issue → Matt approves → ops-fixer → draft PR
      → CI + review-hub checks → Matt merges → Flux
```

- **Plans are issues in a private repo.** pi-cluster is public. A security finding posted before it is fixed says where
  the hole is, and investigation plans quote raw logs. All plans start private (decided 2026-11-11); whether ordinary
  ops plans can move to public issues is revisited once there are real ones to look at.
- A plan has a fixed shape: what was found and the evidence; likely cause; proposed change, or "no change needed";
  risk; how to verify; how to roll back.
- **Research findings carry a fingerprint** (`agent | rule | resource`), so a re-run updates the open issue instead of
  opening a second, and a finding closed as accepted risk stays closed. A run opens at most 5 new issues.
- **The gates do not change.** The drift gate stays in Actions and review-hub's judges stay in review-hub. They react to
  the PR, whoever wrote it. They do not go through n8n or the runner.
- pi-cluster `main` gets required checks and a required review by Matt before any fixer exists.

## 8. Where jig and review-hub fit

- **jig** is a tool an agent may carry. A fixer whose changes deserve a spec and gates can run the jig loop inside its
  sandbox; that is a choice of image. jig's own fleet dispatch becomes a client of the runner.
- **review-hub** is a gate, unchanged. It gains one small duty in the fix path: forwarding "Matt labelled this plan" to
  n8n, since it already receives GitHub's webhooks.

## 9. Build order

Each slice adds one capability. Nothing that can write to a repo runs until the read-only slices have a track record.

| Slice | Builds | Proves |
|---|---|---|
| **1. The sandbox, driven by hand** | The runner, the `agents` namespace and its policies, the Claude runtime image, the *Run agent* step, the form trigger, the run ledger, and one read-only agent, `media-investigator`, returning a `report` | n8n can hand an event to a sandboxed agent and get a result back. This alone replaces "open a session and ask". |
| **2. Events in** | The Alertmanager, Flux and Uptime Kuma emitters to n8n (one manifest each; Discord unchanged), dedupe | Investigations start on their own |
| **3. Plans** | The private plans repo, the GitHub App, `sec-researcher`, finding fingerprints and an eval set of seeded faults | Agents find and write up their own work |
| **4. Fixes** | Required checks on `main`, the approval path, `ops-fixer` | The full path to a merge Matt makes |
| **5. Personal** | `family-assistant`, n8n-applied `calendar_event`, the local-model rule | The same sandbox serving a non-system outcome |

Slice 1 needs no GitHub App, no plans repo and no changes to alerting. Its human-only steps are the Anthropic key in
LiteLLM and one agent key.

## 10. What this deliberately does not do

- No agent merges, ever.
- No agent holds a write credential for the cluster, a calendar or an inbox.
- No LLM decides which agent runs.
- No scheduled polling. The one exception is a weekly research sweep, named here so it does not grow.
- No second job launcher. The build-loop fleet and the agents share one runner.

## 11. Open questions for Matt

Decided 2026-11-11:
- Spend limits and small-model defaults (5.4).
- Agents run on the Pi 5 workers (5.2).
- Personal-data agents use Beelink models only (3.3).
- All plans start in one private repo (7).
- `media-investigator` is the first agent (9).

Still open, and not blocking until slice 5:
1. **Calendar writes.** Should n8n apply a proposed calendar entry on its own, or ask first? If it asks, the options
   are:
   - an ntfy notification with **Add** and **Skip** buttons. The button calls n8n, which today is reachable only at
     home or over Tailscale;
   - a "proposed" card on the Family Board, confirmed with the existing ack tap, which Julia could also use.
