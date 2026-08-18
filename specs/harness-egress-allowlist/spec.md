# Spec: Harness Egress Allowlist (default-deny outbound for the coding-harness containers)

> **REASONS Canvas** (see `specs/TEMPLATE.md`). Constraints-before-work order.

- **Status:** Draft v0.1 — OQ1–OQ5 open, must be resolved before handing to a loop
- **Owner:** Matt
- **Constitution:** `specs/constitution.md` (+ `/CLAUDE.md` Core Mandates)
- **Touches:** `beelink-ansible` repo → `playbooks/50-ai-stack.yml`, the coding-harness compose
  template, a new `files/harness-egress/` (proxy config), host nftables. Plus
  `.claude/skills/coding-agent-ops/SKILL.md` in *this* repo (close out the "Known gap" note).

---

## 1. Why · [R — Requirements]

The four `coding-harness-*` containers can reach the open internet like any other Docker container
on the Beelink. `.claude/skills/coding-agent-ops/SKILL.md` has carried this as a **Known gap** since
the harness was built. It is also why the dependency-install policy ("`npm ci` allowed for
`mtgibbs/*` repos with a committed lockfile; ask first for third-party") is a *written rule* rather
than an enforced boundary — nothing stops a postinstall script from exfiltrating or phoning home.
`docs/adr/009-sbx-sandboxes.md` evaluated Docker Sandboxes as the fix, rejected it as a retrofit on
RAM arithmetic, and committed us to building this instead.

## 2. Outcomes (Definition of Done) · [R — Requirements]

1. Outbound traffic from the four harness containers is **default-deny**, permitted only to an
   explicit allowlist.
2. The allowlist is **declarative and ansible-managed** — a from-scratch rebuild reproduces it with
   no manual steps. (This is the whole reason we chose it over sbx; if it drifts to hand-config the
   decision was wrong.)
3. **Nothing the harness does today breaks**: Claude Code / codex / opencode reach their model
   endpoints, `git push` and `gh` work, `npm ci` on `mtgibbs/*` repos works, MCP servers stay
   reachable.
4. Enforcement is preceded by an **observation phase** with real traffic data — we do not guess the
   allowlist and discover the gaps by breaking the harness mid-loop.
5. The `Known gap` paragraph in `coding-agent-ops/SKILL.md` is replaced with the shipped design.

## 3. Entities · [E — Entities]

- **Harness containers** — `coding-harness-qwen`, `coding-harness-claude`, `coding-harness-claude-2`,
  `coding-harness-codex`. Non-root uid 1000, `cap_drop: [ALL]`, read-only rootfs, no Docker socket.
- **`harness-egress`** (new) — the forward-proxy container. Config: an allowlist file, one
  host-pattern per line, `#` comments. Exact syntax depends on OQ2 (proxy choice).
- **`harness-net`** (new or renamed) — the Docker network the harness containers sit on, with a
  **fixed subnet** so nftables can match on it. Container IPs are not stable; the subnet is.
- **Allowlist entry** — `(pattern, port, why)`. `pattern` is a hostname or `*.suffix`; entries
  without a recorded `why` are not allowed (see §7).
- **Env contract** — `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` in each harness container, pointing
  at `harness-egress`. `NO_PROXY` must cover in-Docker-network names so container→container traffic
  (e.g. `litellm`) does not detour through the proxy.

## 4. Approach · [A — Approach]

**Belt and braces, in that order.** The *braces* are an HTTP(S) forward proxy with a hostname
allowlist, selected by `HTTP_PROXY`/`HTTPS_PROXY`. The *belt* is host nftables in the `DOCKER-USER`
chain: default-deny for the harness subnet, permitting only the proxy, DNS, and named LAN
destinations. The proxy alone is **not** a boundary — `HTTP_PROXY` is advisory and any process can
ignore it. The nftables rule is what makes it real; the proxy is what makes it *legible* (a named
allowlist you can read and audit).

Deliberately **not** using TLS interception. Hostname filtering via the `CONNECT` verb is enough to
enforce "which host", we do not need "which URL", and a MITM CA in a container that runs agent code
is a worse artifact than the problem it solves.

**Two phases, and phase 1 is not optional.** Phase 1 deploys the proxy in **log-only mode** — it
permits everything and records every destination. After a week of real ralph loops, the observed set
becomes the allowlist. Phase 2 flips to enforce. Guessing the allowlist and enforcing immediately is
how you discover on a Friday that codex's device-auth flow needs a host nobody listed.

Mirrors the shape of the existing `beelink-backup` sidecar pattern (a small purpose-built container
deployed by `50-ai-stack.yml`, config in `files/`), not a new orchestration concept.

**Rejected:** Docker Sandboxes (`sbx`) — see ADR-009 §Alternatives; rejected on RAM arithmetic,
not preference. **Rejected:** per-container `iptables` inside the containers — `cap_drop: [ALL]`
means they cannot manage their own firewall, and self-managed confinement is not confinement.

## 5. Scope · [S — Structure: boundary]

### In scope
- `beelink-ansible`: the harness compose template (network + proxy env), a new `harness-egress`
  service + its allowlist config under `files/`, host nftables rules, `playbooks/50-ai-stack.yml`.
- `pi-cluster`: the `Known gap` paragraph in `.claude/skills/coding-agent-ops/SKILL.md`.

### Out of scope
- **The Pi K3s cluster.** Nothing here touches `clusters/`. Cluster egress is a separate question.
- **The UDM firewall.** The YouTube/short-form blackout rules are a different system with a
  different owner (`unifi-ops/SKILL.md`); do not extend them to cover this.
- **The Beelink's other containers** — ollama, llama-server, LiteLLM, Open WebUI, Postgres, Caddy.
  Only the four harness containers are confined. Do not "helpfully" widen it.
- **Ingress.** This is outbound only. No port publishing changes, no new exposed ports.
- **The dependency-install policy wording.** Phase 2 makes it enforceable; rewriting the policy is a
  follow-up, not this spec.

## 6. Prior decisions / facts the implementer must know · [S — Structure]

- **Container source** lives in `beelink-ansible/files/coding-harness-{qwen,claude,codex}/`;
  `coding-harness-claude-2` reuses the `coding-harness-claude` image and build context as a second
  compose service with its own volume. Deployed by `beelink-ansible/playbooks/50-ai-stack.yml`.
- **Model access today** is `http://litellm:4000`, model alias `hot-coder` — a **Docker-network
  hostname, not a public URL**. This must keep working, and it must NOT be proxied. It is the single
  most likely thing to break; put `litellm` in `NO_PROXY`.
- **The containers already have no** Docker socket, kubeconfig, 1Password service token, or NAS
  mount. Egress is the last open axis, which is why it is worth closing and also why it is not
  urgent enough to justify breaking the harness.
- **Host is Ubuntu 26.04 Server** (`docs/beelink-ai-stack.md`), x86_64, Docker Compose, not K3s.
- **RAM is the binding constraint on that box**: the OS sees ~30.5 GiB after the ~96 GB iGPU UMA
  carve (measured 2026-08-18, `docs/adr/009-sbx-sandboxes.md`). The proxy must be small — a
  few hundred MiB, not a JVM. This is a hard design input, not a preference.
- **`harness run … --repo beelink-ansible`** already exists (`specs/harness-multi-repo`), so a ralph
  loop can execute against the ansible repo. That is the intended execution path for this spec.
- **Git identity** is a fine-grained PAT (`op://pi-cluster/coding-harness-github-pat/token`).
  `github.com` reachability is not optional — losing it strands every loop's output.
- **MCP endpoints the harness may use** are in-cluster on the Pi, reached over the LAN:
  `mcp.lab.mtgibbs.dev`, `local-llm-mcp.lab.mtgibbs.dev`, `kiwix-mcp.lab.mtgibbs.dev`
  (`docs/local-llm-mcp.md`, `docs/kiwix-mcp.md`). These are LAN destinations, not internet —
  the nftables rule must not silently drop them.

## 7. Norms · [N — Norms]

- **Every allowlist entry carries a `why` comment on the line above it.** An allowlist nobody can
  audit becomes an allow-all in eighteen months. No bare hostnames.
- **No wildcards broader than one label** (`*.githubusercontent.com` yes; `*.com` no; bare `*` never).
- **Naming:** follow the existing `beelink-*` / `coding-harness-*` convention. The proxy is
  `harness-egress`, its config `files/harness-egress/allowlist.conf`.
- **Observability:** the proxy logs every decision as `ALLOW <host>:<port>` / `DENY <host>:<port>`
  to stdout, so `docker logs harness-egress` is the triage tool. A `DENY` must name the host — a
  denial you cannot attribute is unactionable.
- **Fail loudly, not silently.** A blocked connection should surface as a connection error the agent
  reports, not a hang. Prefer TCP reject over drop for the harness subnet so tools fail fast.
- **Idempotent ansible.** Re-running `50-ai-stack.yml` must not duplicate nftables rules — use a
  managed table/chain the playbook owns and replaces wholesale.

## 8. Safeguards · [S — Safeguards]

1. **No credential ever appears in the proxy config or the nftables rules.** Not the PAT, not a
   LiteLLM key, not an OAuth token. The proxy does not authenticate; it filters by hostname.
2. **No TLS interception.** No MITM CA is generated, installed, or mounted into any container.
3. **The four harness containers keep their existing confinement** — `cap_drop: [ALL]`,
   `no-new-privileges`, read-only rootfs, non-root, no Docker socket. Adding egress control must not
   relax any of them, and must not grant `NET_ADMIN` to a harness container.
4. **The proxy container does not get the Docker socket.** It is a network appliance, not an orchestrator.
5. **Phase 1 is log-only.** No enforcement ships in the same change as the observation tooling.
6. **`litellm` and the in-Docker-network hostnames stay reachable** — container-to-container traffic
   is not proxied and not denied.
7. **Locking yourself out is the failure mode to design against.** The nftables rules apply to the
   harness subnet ONLY, never to the host's own egress or to SSH/Tailscale. A wrong rule here costs
   remote access to the box.

## 9. Task breakdown · [O — Operations]

**Phase 1 — observe (ships first, alone)**
- **T1.** Add a `harness-egress` compose service (small proxy image, OQ2) + `files/harness-egress/`
  config directory. Log-only: permit all, log every destination.
- **T2.** Put the harness containers on a network with a **fixed subnet**; set `HTTP_PROXY`/
  `HTTPS_PROXY`/`NO_PROXY` in each. No nftables yet. `NO_PROXY` must include `litellm` and the
  Docker network suffix.
- **T3.** Wire both into `playbooks/50-ai-stack.yml`. Deploy. Run normal loops for a week.
- **T4.** Distil the observed destination set into `allowlist.conf`, one `why` comment per entry.

**Phase 2 — enforce (separate change, after T4)**
- **T5.** Flip the proxy from log-only to allowlist-enforcing.
- **T6.** Add the `DOCKER-USER` nftables default-deny for the harness subnet: permit → proxy, DNS,
  and the named LAN destinations; reject everything else.
- **T7.** Update `coding-agent-ops/SKILL.md` — replace the `Known gap` paragraph with the design.

Candidate starting allowlist (to be **confirmed against T3 data**, not trusted as written):
`ai.lab.mtgibbs.dev`, `api.anthropic.com`, `github.com`, `api.github.com`, `codeload.github.com`,
`objects.githubusercontent.com`, `registry.npmjs.org`, `pypi.org`, `files.pythonhosted.org`,
`mcp.lab.mtgibbs.dev`, `local-llm-mcp.lab.mtgibbs.dev`, `kiwix-mcp.lab.mtgibbs.dev`, plus whatever
codex's ChatGPT auth and Claude Code's telemetry actually require (OQ4).

## 10. Acceptance criteria (EARS) · [O]

- **AC1 (Ubiquitous).** The `harness-egress` service shall be defined in the compose template and
  deployed by `50-ai-stack.yml`.
- **AC2 (Ubiquitous).** Each of the four harness containers shall have `HTTP_PROXY`, `HTTPS_PROXY`
  and `NO_PROXY` set.
- **AC3 (Ubiquitous).** `NO_PROXY` shall include `litellm`, so model traffic is not proxied.
- **AC4 (Ubiquitous).** The harness network shall declare an explicit fixed subnet.
- **AC5 (State-driven).** While in phase 1, the proxy config shall be log-only — no entry is denied.
- **AC6 (Ubiquitous).** Every allowlist entry shall be preceded by a `#` comment giving its reason.
- **AC7 (Unwanted).** If an allowlist pattern is broader than one wildcard label, the gate shall fail.
- **AC8 (Unwanted).** If any credential literal appears in the proxy config or nftables rules, the
  gate shall fail.
- **AC9 (Unwanted).** If any harness service gains `NET_ADMIN`, `privileged`, or a Docker socket
  mount, the gate shall fail.
- **AC10 (Unwanted).** If the proxy service mounts the Docker socket, the gate shall fail.
- **AC11 (Event-driven).** When phase 2 lands, the nftables rules shall scope to the harness subnet
  and shall not reference the host's primary interface or the SSH/Tailscale paths.
- **AC12 (Ubiquitous).** No MITM CA shall be generated, installed, or mounted anywhere.

## 11. Verification (the harness)

`specs/harness-egress-allowlist/verify.sh` — **STATIC tier only**, presence-gated per the ralph
contract (a check for a not-yet-written identifier PENDs, never FAILs; `STRICT=1` on the final pass
turns every pend into a failure).

It runs against a **beelink-ansible checkout**, located via `$ANSIBLE_REPO` (default `.`, so it also
works when the loop runs inside that repo). If the checkout is absent, every check pends — and under
`STRICT=1` that is a failure, so "I could not test this" never reads as "this is fine."

**What it cannot prove, by construction:** that traffic is actually blocked. That is the LIVE tier
and it is a human's call after deploy:

```
docker exec coding-harness-claude curl -sS -m 5 -o /dev/null -w '%{http_code}\n' https://ai.lab.mtgibbs.dev/health   # expect 200
docker exec coding-harness-claude curl -sS -m 5 https://example.com                                                   # expect refused/blocked
docker logs harness-egress | tail -50                                                                                 # expect a DENY naming example.com
docker exec coding-harness-claude git ls-remote https://github.com/mtgibbs/pi-cluster >/dev/null && echo git-ok
```

## 11b. Loop execution

Run against the ansible repo, which is what `specs/harness-multi-repo` built the flag for:

```
harness run qwen specs/harness-egress-allowlist --repo beelink-ansible
```

One task per iteration, fresh context, gated on `verify.sh`. **Phase 1 only** (T1–T4) — phase 2
touches host firewall rules where a wrong rule costs remote access to the Beelink (Safeguard 7), so
T5–T7 are a human-driven change, not a loop.

`tasks.txt` covers **T1–T3 only** and is **provisional**: T1 names the proxy chosen in OQ2 and T2
assumes a network shape that OQ1 has not confirmed. Resolve OQ1 and OQ2, fold the answers back into
§4/§6, then re-read the tasks before starting a loop. T4 is not a loop task at all — it needs a week
of real traffic to distil.

## 12. Open questions

- **OQ1.** What is the current compose network topology on the Beelink? Are the harness containers
  and `litellm` on a shared user-defined network, and does it declare a subnet? Everything in §9
  depends on this and I could not read `beelink-ansible` from the harness container. **Resolve first.**
- **OQ2.** Which proxy? Candidates: `tinyproxy` (tiny, `Allow`/`Filter` by host, minimal deps),
  `squid` (capable, heavier than this box wants), or a ~50-line Go/Python `CONNECT` filter (no
  dependency, but ours to maintain). Decide on RAM footprint and allowlist-syntax legibility.
- **OQ3.** Does anything in the harness ignore `HTTP_PROXY`? Go binaries honour it; some Node tooling
  needs `npm config set proxy` separately. Enumerate during T3 rather than assuming.
- **OQ4.** What hosts do Claude Code's telemetry/auth and codex's ChatGPT device-auth actually need?
  This is exactly what phase 1 exists to answer — do not guess it into the allowlist.
- **OQ5.** nftables or iptables-nft on Ubuntu 26.04, and does the installed Docker version still
  honour the `DOCKER-USER` chain the same way? Verify on the box before writing T6.

## Two-way sync rule

Phase 1's observed destination set (T4) **must** be written back into §9's candidate allowlist with
its `why` comments before phase 2 starts. If enforcement is tuned by editing the deployed config
directly, fix this spec first — otherwise the next rebuild silently reverts the fix.
