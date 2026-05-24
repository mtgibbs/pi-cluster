# Spec: AI control panel (`ai-controlpanel`) — aimode module + homepage status

- **Status:** ✅ Done v1.0 — shipped + verified live 2026-05-24
- **Owner:** Matt (orchestrated by Claude; bounded pieces executed by qwen)
- **Constitution:** `specs/constitution.md` (+ `/CLAUDE.md` Core Mandates)
- **Touches:**
  - `beelink-ansible/files/ai-controlpanel.py` *(new — qwen task A)*
  - `clusters/pi-k3s/homepage/configmap.yaml` *(edit — qwen task B)*
  - Cross-cutting glue *(Claude): `beelink-ansible/files/ai-controlpanel.service`, deploy task in*
    `beelink-ansible/playbooks/50-ai-stack.yml`, *a Caddy route, the token secret, and the*
    `controlpanel.lab.mtgibbs.dev` *DNS record in* `clusters/pi-k3s/pihole/pihole-custom-dns.yaml`.

---

## 1. Why

`aimode {work|family}` flips the Beelink between the family stack (Dewey + 30B coder) and the
sole-tenant Q8 power coder — but it's SSH-only, with no at-a-glance state. We want a small
**AI control panel** for the stack, reachable from the homepage: it surfaces the **live mode** and
lets you **flip it** without a terminal. **aimode is the first module** — the panel is built to grow
(future: warm/evict a model, restart a service, show loaded VRAM) without a rename or rebuild.

## 2. Outcomes

1. The homepage shows the **live mode** (`FAMILY` or `WORK`), auto-refreshing.
2. From the homepage you can reach the **control panel** (`controlpanel.lab.mtgibbs.dev`), whose
   first section is **AI Mode** with two flip buttons.
3. A flip from the panel actually runs `aimode work|family` on the Beelink and reflects the new mode
   within one refresh.
4. A casual/kid click cannot flip the mode (the flip is **token-gated**); *reading* the mode is open.
5. Nothing about existing family/work behavior, Dewey, or the LiteLLM `hot-coder` alias changes.
6. The service + page are **structured for more modules** — routes are namespaced per control.

## 3. Scope

### In scope
- A small **`ai-controlpanel`** HTTP service on the Beelink host: a control-panel page (`/`), an
  **aimode module** (status + token-gated flip), built so other modules slot in later.
- A **homepage status card** (reads the mode) and a **bookmark** to the control panel.
- The glue to deploy + route + name + secure it.

### Out of scope
- **Do NOT modify `aimode.sh`** — correct and just-fixed (2026-05-24). The panel *calls* it.
- **Do NOT build other modules yet** (models/restarts/VRAM). Only leave room for them (namespaced
  routes, a sectioned page). aimode is the only live module in v0.2.
- **Do NOT touch** Dewey, the LiteLLM model list, the `hot-coder` alias, or any Ollama config.
- **Do NOT add auth infra** (Authelia is Phase 1, not deployed) — token-in-link only.
- **Do NOT change** any other homepage group/widget. Add one card + one bookmark, nothing else.

## 4. Constraints

- **GitOps for the homepage half:** `clusters/pi-k3s/homepage/configmap.yaml` is Flux-managed —
  edit the file; don't touch the live cluster. The Beelink half is **ansible** (not k8s).
- **No inline secrets.** The flip token comes from **1Password** (`op://pi-cluster/ai-controlpanel/token`),
  injected at deploy by ansible (Beelink) and via the homepage ExternalSecret (k8s). Never hardcode.
- **In-stack URLs / house conventions:** per-service subdomain under `*.lab.mtgibbs.dev`, fronted by
  Caddy on the Beelink (like `ai.lab`, `dewey.lab`, `chat.lab`).
- **Reversible, not destructive** — but flipping *disrupts* Dewey, hence the token gate.

## 5. Prior decisions / facts the implementer must know

- **Mode source of truth:** `/opt/ai-stack/.aimode_state` contains exactly `family` or `work`
  (written by `aimode`). Prefer reading the state file (cheap, no docker) over `aimode status`.
- **The flip command:** `sudo aimode work` / `sudo aimode family`. The service runs the flip via
  this CLI; it does **not** re-implement it.
- **Sibling service for STYLE:** `beelink-ansible/files/litellm-exporter.py` — a small stdlib Python
  service on the Beelink. **Copy its style** (stdlib `http.server`, no framework). KEY difference:
  the exporter is a *container*; `ai-controlpanel` must run as a **host systemd service** because it
  shells out to `sudo aimode` — a container cannot.
- **Caddy** on the Beelink terminates TLS for `*.lab.mtgibbs.dev` and reverse-proxies to backends.
  `controlpanel.lab.mtgibbs.dev` is the same pattern as the existing `ai.lab` block.
- **Homepage widget patterns already in this repo** (copy, don't invent): the `customapi` card near
  the `Beelink` group in `clusters/pi-k3s/homepage/configmap.yaml`; Homepage substitutes secrets via
  `{{HOMEPAGE_VAR_*}}` from env (wired through the `homepage` ExternalSecret).
- **Routes (namespaced — this is the extensibility hook):**
  - `GET /` → the control-panel HTML page; first section **"AI Mode"** showing current mode + two
    buttons.
  - `GET /aimode` → `200` JSON `{"mode": "<family|work>"}` (open; the homepage card reads this).
  - `POST /aimode/flip/family` · `POST /aimode/flip/work` → token-gated; runs the flip.
- **Port:** env **`AI_CONTROLPANEL_PORT`, default `9110`**, bind `0.0.0.0` (Caddy container reaches
  the host). `9101` is taken by `litellm-exporter`.
- **Token:** env **`AI_CONTROLPANEL_TOKEN`** (systemd injects it from a file ansible writes out of
  1Password). Validate on flip; reject otherwise. Homepage bookmark carries it as
  `{{HOMEPAGE_VAR_AI_CONTROLPANEL_TOKEN}}`.

## 6. Task breakdown

- **A — `ai-controlpanel.py`** *(qwen, bounded, single file)* — the service (§7 A-criteria).
- **B — homepage card + bookmark** *(qwen, bounded, YAML edit)* — status card + panel link
  (§7 B-criteria).
- **C — glue** *(Claude, cross-cutting)* — systemd unit + tight sudoers, ansible deploy, Caddy route,
  token in 1Password + both injection paths, `controlpanel.lab` DNS. (Not handed to qwen.)

A and B are independent → parallel loops. C lands after A.

## 7. Acceptance criteria (EARS)

**Service (`ai-controlpanel.py`) — Task A:**

- A1 (Ubiquitous): The service shall listen on `0.0.0.0` at the port from env
  `AI_CONTROLPANEL_PORT` (default `9110`).
- A2 (Event): When it receives `GET /aimode`, the service shall respond `200` with JSON
  `{"mode": "<family|work>"}` read from `/opt/ai-stack/.aimode_state` (whitespace-stripped).
- A3 (Event): When it receives `GET /`, the service shall respond `200` with an HTML page containing
  an **"AI Mode"** section that shows the current mode and has two buttons ("Family"/"Work") that
  POST the flip.
- A4 (Event): When it receives `POST /aimode/flip/family` or `POST /aimode/flip/work` **with a valid
  token**, the service shall run the corresponding `sudo aimode {family|work}` and respond `200` with
  the new mode.
- A5 (Unwanted): If a `POST /aimode/flip/*` arrives **without a valid token** (env
  `AI_CONTROLPANEL_TOKEN`), then the service shall respond `403` and shall **not** run `aimode`.
- A6 (Unwanted): If the flip target is neither `family` nor `work`, then the service shall respond
  `400` and run nothing.
- A7 (Ubiquitous): The service shall contain **no hardcoded token or secret** — the token comes only
  from `AI_CONTROLPANEL_TOKEN`.
- A8 (Optional/extensibility): Where a new module is added later, the routing shall let it mount under
  its own path prefix without altering the aimode routes (i.e., dispatch on path prefix, not a flat
  if-chain hardcoded to aimode only).

**Homepage — Task B:**

- B1 (Ubiquitous): The homepage config shall include exactly **one** `customapi` card whose `url` is
  `https://controlpanel.lab.mtgibbs.dev/aimode` and which displays the `mode` field.
- B2 (Ubiquitous): The homepage config shall include **one** bookmark/link to
  `https://controlpanel.lab.mtgibbs.dev/` carrying the token via
  `{{HOMEPAGE_VAR_AI_CONTROLPANEL_TOKEN}}` (never a literal token).
- B3 (Unwanted): If the change would alter any other group, widget, or service entry, then it is out
  of bounds — only the one card + one bookmark may be added.
- B4 (Ubiquitous): The edited `configmap.yaml` shall remain valid YAML and its embedded documents
  well-formed.

## 8. Verification (the harness) — `verify.sh`

`specs/aimode-toggle/verify.sh` (STATIC, offline, deterministic; exit 0 = acceptable) asserts:

- **A (service):** `python3 -m py_compile ai-controlpanel.py` passes; greps confirm handlers for
  `/aimode`, `/`, `/aimode/flip/`; a `403` branch on missing/invalid token; reads
  `AI_CONTROLPANEL_TOKEN` from env; reads `/opt/ai-stack/.aimode_state`; binds `AI_CONTROLPANEL_PORT`
  / `9110`; **no** hardcoded token (no literal secret assignment); prefix-based dispatch present (A8).
- **B (homepage):** `configmap.yaml` valid YAML; exactly one new `customapi` `url:
  https://controlpanel.lab.mtgibbs.dev/aimode`; one bookmark to
  `https://controlpanel.lab.mtgibbs.dev/` with `{{HOMEPAGE_VAR_AI_CONTROLPANEL_TOKEN}}` and **no**
  literal token; diff-bounded (only the one card + one bookmark added).
- Overridable input paths (`API`, `CM`) like the homepage-refresh `verify.sh`, so each piece gates
  independently in its loop.

**LIVE (post-deploy, human/Flux — NOT loop-gated):** `curl https://controlpanel.lab.mtgibbs.dev/aimode`
returns the real mode; the card renders it; a tokened flip switches mode within a refresh; a tokenless
flip is rejected `403`.

## 8b. Loop execution

Two independent bounded loops via `scripts/ralph-qwen.sh`, **fresh context each**:

- `tasks.txt` (A): one task — "implement `ai-controlpanel.py` per spec §7 A1–A8"; gate on
  `verify.sh` A-assertions.
- `tasks.txt` (B): one task — "add the homepage card + bookmark per spec §7 B1–B4"; gate on
  `verify.sh` B-assertions.

Hand qwen **only** the relevant file + this spec's §5/§7 — never the whole repo. Claude reviews each
diff (correctness + the out-of-scope guardrails) before the glue (Task C) and the PR.

## 9. Open questions

- **OQ1 — Caddy → host service reach.** Caddy is a container; `ai-controlpanel` is on the host.
  Resolve (host-gateway IP / `extra_hosts: host.docker.internal` / bind to the bridge). *(Claude,
  Task C; does not block qwen.)*
- **OQ2 — sudo for the service.** Service user gets `NOPASSWD` for `/usr/local/bin/aimode` only
  (tight sudoers), or run the unit as root. Least-privilege that works. *(Claude, Task C.)*
- **OQ3 — token exposure / rotation. RESOLVED (accepted interim).** The flip token is carried in
  the homepage card + bookmark URL → it renders into the homepage DOM and lands in Caddy logs.
  Accepted because the gated action is *reversible + LAN-only* (worst case: someone toggles AI mode).
  **Not** a pattern for sensitive actions. Tracked in the roadmap's "interim auth ledger"; retire
  when network-wide SSO fronts `controlpanel.lab` (then drop the token entirely). SSO itself is
  deliberately deferred — layering auth across Jellyfin/*arr/Pi-hole's native logins is a design
  problem, not a bolt-on.

## Worked-example checklist (before handing to an agent)

- [x] Every linkable target is a LITERAL url (`controlpanel.lab.mtgibbs.dev/aimode`, etc.).
- [x] Novel patterns have a copy-from pointer (`litellm-exporter.py`, the existing `customapi` card).
- [x] The misleading-sibling contrast is called out (exporter is a *container*; this is a *host
      systemd service*).
- [x] Operational facts stated (`.aimode_state` contents, sudo requirement, port `9101` taken).
- [x] Every §7 criterion maps to a §8 `verify.sh` assertion.
