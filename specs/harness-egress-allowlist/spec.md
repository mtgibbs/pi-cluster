# Spec: Harness Egress Allowlist (default-deny outbound for the coding-harness containers)

> **REASONS Canvas** (see `specs/TEMPLATE.md`). Constraints-before-work order.

- **Status:** Draft v0.3 — **OQ1, OQ2 and OQ5 all CLOSED 2026-08-18.** OQ1's answer changed the
  design (see §4); OQ2 is settled on **squid**, measured on the box rather than argued (see §12).
  **No open blockers — this is ready to hand to a loop.** OQ3 and OQ4 are answered *by* running
  phase 1, not before it.
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

- **Harness containers** — `coding-harness-qwen` (`mem_limit: 4g`, `cpus: 2.0`),
  `coding-harness-claude` (`4g`/`2.0`), `coding-harness-claude-2` (`2g`/`1.0`),
  `coding-harness-codex` (`2g`/`1.0`). Non-root uid 1000, `cap_drop: [ALL]`, read-only rootfs, no
  Docker socket. Caps are **not** uniform — verified against `beelink-ansible` `origin/main`.
- **`ai-internal`** (existing) — the single shared bridge network. `driver: bridge`, **no subnet
  declared, no `internal: true`**. **18 services sit on it**: the four harness containers plus
  `litellm`, `ollama`, `llama-server`, `postgres`, `caddy`, `open-webui`, `open-webui-dewey`,
  `pipelines`, `pipelines-ops`, `cadvisor`, `gpu-metrics`, `litellm-exporter`, `beelink-backup`,
  `harness-console`. This is the fact that shapes the whole design (§4).
- **`harness-net`** (NEW — must be created, not renamed) — a dedicated bridge network for the four
  harness containers + `harness-egress` + `litellm`, with an **explicit fixed subnet** so
  `DOCKER-USER` has something stable to match. Container IPs are not stable; the subnet is.
- **`harness-egress`** (new) — the forward-proxy container: **squid**, caching disabled, no TLS
  interception (OQ2, closed). Config is two files: `squid.conf` (the mechanism) and
  `allowlist.conf` (the policy — one host-pattern per line, `#` comments, fed to squid as a
  `dstdomain` ACL file). Keeping policy in its own file is what lets T4 rewrite the allowlist
  without touching proxy mechanics, and what makes the diff reviewable.
- **Allowlist entry** — `(pattern, port, why)`. `pattern` is a hostname or `*.suffix`; entries
  without a recorded `why` are not allowed (see §7).
- **Env contract** — `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` in each harness container, pointing
  at `harness-egress`. `NO_PROXY` must cover in-Docker-network names so container→container traffic
  (e.g. `litellm`) does not detour through the proxy.

## 4. Approach · [A — Approach]

**Belt and braces, in that order.** The *braces* are an HTTP(S) forward proxy with a hostname
allowlist, selected by `HTTP_PROXY`/`HTTPS_PROXY`. The *belt* is a host firewall rule in the
`DOCKER-USER` chain: default-deny for the harness subnet, permitting only the proxy, DNS, and named
LAN destinations. The proxy alone is **not** a boundary — `HTTP_PROXY` is advisory and any process
can ignore it. The firewall rule is what makes it real; the proxy is what makes it *legible* (a
named allowlist you can read and audit).

**The network move is the load-bearing step (OQ1's answer, and it changed this design).** All 18
Beelink services share one bridge network, `ai-internal`, with no subnet declared. A `DOCKER-USER`
rule matching that subnet would therefore confine **ollama, litellm, postgres, caddy and everything
else** — precisely what §5 puts out of scope, and a fast route to an outage. So the four harness
containers move **off** `ai-internal` and onto a new dedicated `harness-net` with an explicit fixed
subnet, joined by `harness-egress`. `litellm` is attached to **both** networks so that
`http://litellm:4000` keeps resolving by name from the harness side; every other service stays
exactly where it is. Confining a subnet is only safe once that subnet contains only what we mean to
confine.

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
- `beelink-ansible`: the harness compose block in `playbooks/50-ai-stack.yml` (new `harness-net`
  network + proxy env + moving the four harness services onto it + attaching `litellm` to it), a new
  `harness-egress` service + its allowlist config under `files/`, host `DOCKER-USER` rules.
- `pi-cluster`: the `Known gap` paragraph in `.claude/skills/coding-agent-ops/SKILL.md`.

### Out of scope
- **The Pi K3s cluster.** Nothing here touches `clusters/`. Cluster egress is a separate question.
- **The UDM firewall.** The YouTube/short-form blackout rules are a different system with a
  different owner (`unifi-ops/SKILL.md`); do not extend them to cover this.
- **The Beelink's other 14 services** — ollama, llama-server, LiteLLM, Open WebUI (×2), Postgres,
  Caddy, pipelines (×2), cadvisor, gpu-metrics, litellm-exporter, beelink-backup, harness-console.
  Only the four harness containers are confined. Do not "helpfully" widen it — and note that leaving
  them on `ai-internal` while the harness moves to `harness-net` is exactly what keeps them out.
  `litellm` is the sole exception: it joins `harness-net` *in addition to* `ai-internal`, and is not
  itself confined.
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
- **The host firewall is `ufw`, and the playbook already drives it** — `50-ai-stack.yml` shells out
  to `ufw allow from 192.168.1.0/24 to any port 9100` and `ufw allow from 172.16.0.0/12 to any port
  9110`, with `changed_when: "'Rule added' in …stdout"` for idempotency. **Follow that pattern for
  anything host-level.** But note the gotcha the playbook itself records: *"cAdvisor :8081 is
  published via Docker so its iptables bypass ufw"* — Docker installs its own rules ahead of ufw, so
  **ufw cannot govern container forwarding**. Container egress must go in `DOCKER-USER`. Both
  mechanisms are in play; do not assume one covers the other. (OQ5, closed.)
- **`beelink-ansible`'s working tree on the laptop mirror is STALE** — it was 40 commits behind
  `origin/main` on a feature branch when this spec was written, and the stale tree showed only two
  harness containers. **Read `git show origin/main:playbooks/50-ai-stack.yml`, not the checkout.**
- **RAM is the binding constraint on that box**: the OS sees ~30.5 GiB after the ~96 GB iGPU UMA
  carve (measured 2026-08-18, `docs/adr/009-sbx-sandboxes.md`). The proxy must be small — a
  few hundred MiB, not a JVM. This is a hard design input, not a preference.
- **`harness run … --repo beelink-ansible`** already exists (`specs/harness-multi-repo`), so a ralph
  loop can execute against the ansible repo. That is the intended execution path for this spec.
- **Git identity** is a fine-grained PAT (`op://pi-cluster/coding-harness-github-pat/token`).
  `github.com` reachability is not optional — losing it strands every loop's output.
- **Compose prefixes network names — the live network is `ai-stack_ai-internal`, not `ai-internal`.**
  Verified on the box 2026-08-18: `docker network ls` shows `ai-stack_ai-internal`; `docker network
  inspect ai-internal` returns *"network not found"*. `ai-internal` is only the key inside the compose
  YAML. So `harness-net` will materialise as **`ai-stack_harness-net`**, and any command or rule that
  names a network — inspection, a `DOCKER-USER` comment, a runbook line — must use the prefixed form
  or it will silently look at nothing.
- **`ai-internal` is auto-assigned `172.18.0.0/16`** (gateway `172.18.0.1`) — a /16, because no subnet
  is declared and Docker allocates from its default pool. Two consequences for T2/T6: `harness-net`'s
  fixed subnet must be chosen so it cannot collide with that pool, and the existing ufw rule
  `ufw allow from 172.16.0.0/12 to any port 9110` (§6 above) **already spans both networks** — it is
  not harness-specific and must not be mistaken for one.
- **Live membership confirms the §3 count**: 17 containers were attached at inspection time — the four
  harness containers, `litellm`, `ollama`, `llama-server`, `postgres`, `caddy`, `open-webui`,
  `open-webui-dewey`, `pipelines`, `pipelines-ops`, `cadvisor`, `gpu-metrics`, `litellm-exporter`,
  `harness-console`. The 18th, `beelink-backup`, is a nightly one-shot and is simply not running
  between runs. Safeguard 8's "confine only what `harness-net` contains" should be checked against
  the *running* set, which is why this number moves.
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

1. **No credential ever appears in the proxy config or the firewall rules.** Not the PAT, not a
   LiteLLM key, not an OAuth token. The proxy does not authenticate; it filters by hostname.
2. **No TLS interception.** No MITM CA is generated, installed, or mounted into any container.
3. **The four harness containers keep their existing confinement** — `cap_drop: [ALL]`,
   `no-new-privileges`, read-only rootfs, non-root, no Docker socket. Adding egress control must not
   relax any of them, and must not grant `NET_ADMIN` to a harness container.
4. **The proxy container does not get the Docker socket.** It is a network appliance, not an orchestrator.
5. **Phase 1 is log-only.** No enforcement ships in the same change as the observation tooling.
6. **`litellm` and the in-Docker-network hostnames stay reachable** — container-to-container traffic
   is not proxied and not denied.
7. **Locking yourself out is the failure mode to design against.** The `DOCKER-USER` rules apply to
   the `harness-net` subnet ONLY, never to `ai-internal`, never to the host's own egress, never to
   SSH/Tailscale. A wrong rule here costs remote access to the box.
8. **Confine only what `harness-net` contains.** Before any enforcement lands, `harness-net` must
   hold exactly the four harness containers, `harness-egress`, and `litellm`. If another service is
   ever added to it, the blast radius of every rule in §9 T6 silently grows. This is the safeguard
   that OQ1 turned out to require.

## 9. Task breakdown · [O — Operations]

**Phase 1 — observe (ships first, alone)**
- **T1.** Add a `harness-egress` compose service (**squid**, `ubuntu/squid`, `cache deny all` /
  `cache_mem 0`) + a `files/harness-egress/` config directory holding `squid.conf` and
  `allowlist.conf`. Log-only: `http_access allow all`, but log every destination as
  `ALLOW <host>:<port>` via `logformat` + `access_log`. Log to a file under a `proxy`-owned
  `/var/log/squid/` and `tail -F` it to stdout from the entrypoint — squid cannot write `/dev/stdout`
  directly after dropping privileges (OQ2).
- **T2.** Declare `harness-net` with an explicit fixed subnet. **Move** the four harness services
  from `ai-internal` onto it, put `harness-egress` on it, and add `harness-net` to `litellm`'s
  network list so it sits on both. Leave the other 14 services on `ai-internal` untouched. Then set
  `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` in each harness container; `NO_PROXY` must include `litellm`.
  No firewall rules yet.
- **T3.** Wire both into `playbooks/50-ai-stack.yml`. Deploy. **Smoke-test the network move before
  anything else** — a loop that cannot reach `litellm` is a broken harness, not a quiet one:
  `docker exec coding-harness-claude curl -sS -m5 -o /dev/null -w '%{http_code}\n' http://litellm:4000/health`.
  Then run normal loops for a week.
- **T4.** Distil the observed destination set into `allowlist.conf`, one `why` comment per entry.

**Phase 2 — enforce (separate change, after T4)**
- **T5.** Flip the proxy from log-only to allowlist-enforcing.
- **T6.** Add the `DOCKER-USER` default-deny for the **`harness-net` subnet only** (never
  `ai-internal`): permit → proxy, DNS, and the named LAN destinations; reject everything else. Use
  `DOCKER-USER`, not a `ufw` rule — Docker's own rules run ahead of ufw and ufw does not govern
  container forwarding (§6).
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
- **AC4 (Ubiquitous).** The `harness-net` network shall declare an explicit fixed subnet.
- **AC4b (Ubiquitous).** `harness-net` shall be a network distinct from `ai-internal`, and `litellm`
  shall be attached to it — otherwise the harness loses `http://litellm:4000` by name.
- **AC5 (State-driven).** While in phase 1, the proxy config shall be log-only — no entry is denied.
- **AC6 (Ubiquitous).** Every allowlist entry shall be preceded by a `#` comment giving its reason.
- **AC7 (Unwanted).** If an allowlist pattern is broader than one wildcard label, the gate shall fail.
- **AC8 (Unwanted).** If any credential literal appears in the proxy config or firewall rules, the
  gate shall fail.
- **AC9 (Unwanted).** If any harness service gains `NET_ADMIN`, `privileged`, or a Docker socket
  mount, the gate shall fail.
- **AC10 (Unwanted).** If the proxy service mounts the Docker socket, the gate shall fail.
- **AC11 (Event-driven).** When phase 2 lands, the `DOCKER-USER` rules shall scope to a source
  subnet and shall not reference the SSH/Tailscale paths.
- **AC13 (Unwanted).** If a firewall rule references `ai-internal`, the gate shall fail — confining
  that subnet would confine all 18 services (Safeguard 8).
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

`tasks.txt` covers **T1–T3 only**, and nothing in it is provisional any more: T2 is grounded in the
real topology (OQ1 closed) and T1 names a specific proxy (OQ2 closed). T4 is not a loop task at all —
it needs a week of real traffic to distil.

## 12. Open questions

- **OQ1. CLOSED 2026-08-18.** One shared bridge network, `ai-internal`, `driver: bridge`, **no
  subnet declared**, **18 services on it** including all four harness containers and `litellm`.
  Confirmed against `beelink-ansible` `origin/main` (the laptop mirror's working tree was 40 commits
  stale and showed only two harness containers — see §6). **This answer changed the design**: a
  subnet rule on `ai-internal` would confine the entire stack, so the harness moves to a dedicated
  `harness-net` (§4, §9 T2, Safeguard 8, AC4b, AC13).
- **OQ2. CLOSED 2026-08-18 — `squid`,** caching disabled. Decided by measuring all three on the
  Beelink itself, not by argument.

  **RAM does not discriminate.** The premise that squid is "heavier than this box wants" is wrong at
  this scale: measured idle RSS was **23–25 MiB** (`ubuntu/squid`, `cache deny all`, `cache_mem 0`),
  against a stated ceiling of a few hundred MiB. tinyproxy came in at **1.9 MiB**. Both are noise on
  a 30.5 GiB host — squid is ~0.7% of the RAM free at the time of measurement. A 21 MiB difference is
  not a reason to accept a worse allowlist.

  **Legibility discriminates, and it is the criterion that matters** — §4 is explicit that the proxy
  is not the boundary (the `DOCKER-USER` rule is); the proxy exists to make the policy *auditable*.
  Squid is the only candidate that produces both required artifacts natively, with no code:

  - **The allowlist format §7 asks for.** `acl allowed_hosts dstdomain "/etc/squid/allowlist.conf"`
    reads one host per line with `#` comments — the spec's format, verbatim, no translation layer.
    `.github.com` means "that domain and its subdomains", which is exactly the one-label wildcard
    §7 permits.
  - **The log format §7 asks for.** Two `logformat` lines plus ACL-selected `access_log` emit
    literally `ALLOW <host>:<port>` / `DENY <host>:<port>`. Verified end-to-end through a real
    client:

    ```
    ALLOW github.com:443       # curl -x proxy https://github.com   -> 200
    DENY example.com:443       # curl -x proxy https://example.com  -> 000, fails fast
    ```

  **Why not the other two:**

  - **tinyproxy** — smallest, but its filter file is **POSIX regex, not globs**. `*.githubusercontent.com`
    is not a valid pattern there; you would write `\.githubusercontent\.com$`. That contradicts §7's
    stated syntax and **AC7**, which gates on wildcard-label breadth. Its log format is also fixed
    (`Connect ... Proxying refused on filtered domain`), so `ALLOW`/`DENY` would need post-processing.
    Saving 21 MiB by making the audit surface less readable inverts the point of the component.
  - **A hand-rolled Go/Python `CONNECT` filter** — would match the norms perfectly, but adds an image
    we build and maintain, plus correctness risk in proxy semantics (CONNECT tunnelling, absolute-form
    plain-HTTP `HTTP_PROXY` requests that npm and pip actually use, timeouts, concurrency). ADR-009
    already books "the egress proxy is work we now own" as a Negative; this is the option that
    maximises it, in exchange for nothing squid does not already give us. Reconsider only if squid's
    config surface becomes the problem.

  **One implementation wart, found while measuring — T1 must handle it.** Squid drops privileges to
  the `proxy` user and then **cannot open `/dev/stdout`** (`FATAL: Cannot open '/dev/stdout' for
  writing`), so the §7 norm of "`docker logs harness-egress` is the triage tool" is not free. Log to
  a file under a `proxy`-owned `/var/log/squid/` and stream it to stdout from the entrypoint
  (`squid -N … & exec tail -F /var/log/squid/egress.log`). Verified working in that shape. Also:
  **do not use the alpine `squid` package** — it dies at startup with
  `initgroups: unable to set groups for User root`. `ubuntu/squid` works.
- **OQ3.** Does anything in the harness ignore `HTTP_PROXY`? Go binaries honour it; some Node tooling
  needs `npm config set proxy` separately. Enumerate during T3 rather than assuming.
- **OQ4.** What hosts do Claude Code's telemetry/auth and codex's ChatGPT device-auth actually need?
  This is exactly what phase 1 exists to answer — do not guess it into the allowlist.
- **OQ5. CLOSED 2026-08-18.** The host runs **`ufw`**, already driven from `50-ai-stack.yml` via
  `ansible.builtin.command: ufw allow …` with `changed_when` idempotency — follow that pattern for
  host-level rules. But ufw does **not** govern container forwarding (the playbook itself records
  that Docker's iptables bypass ufw for published ports), so container egress goes in `DOCKER-USER`.
  Both mechanisms are in play; neither covers the other.

## Two-way sync rule

Phase 1's observed destination set (T4) **must** be written back into §9's candidate allowlist with
its `why` comments before phase 2 starts. If enforcement is tuned by editing the deployed config
directly, fix this spec first — otherwise the next rebuild silently reverts the fix.
