# Spec: Remote-Ops Access (deploy + diagnose the lab from off-net over Tailscale)

> **REASONS Canvas** (see `specs/TEMPLATE.md`). Constraints-before-work order.

- **Status:** Phase 1 + Phase 3 DONE (LIVE-verified 2026-06-06). Phase 2 RESCOPED + shipped
  2026-06-06 — route advertisement, NOT an ACL grant (see §4 / OQ3 below).
- **Owner:** Matt
- **Constitution:** `specs/constitution.md` (+ `/CLAUDE.md` Core Mandates)
- **Touches:** `beelink-ansible` repo → `inventory.yml` (Phase 1); Tailscale tailnet ACL policy + MagicDNS (Phase 2); `.claude/skills/tailscale-ops/SKILL.md` (capture the gap + the fix).

---

## 1. Why · [R — Requirements]

When VPN'd in from off-net, we **cannot work the lab** the way we expect. On 2026-06-04 a routine
`ansible-playbook` deploy to the Beelink **failed to connect** because the inventory resolves
`beelink-ai` → `192.168.1.70` (the home LAN IP), which is **not routed over Tailscale** (only `/32`s for
`192.168.1.55/.56` are advertised to the laptop; the full `/24` is not). The deploy only succeeded after a
manual `-e ansible_host=100.123.94.31` (tailnet IP) override. Separately, from off-net **only ICMP + SSH
to tailnet `100.x` IPs work** — every service port (`:443` Caddy, `:6443` k8s API) returns `000`, because
the personal laptop (`autogroup:member`) has no Tailscale ACL grant to the `tag:inference` / cluster
tagged-devices. We want remote deploys to "just work" and a documented path to reach lab services from the
road.

## 2. Outcomes (Definition of Done) · [R — Requirements]

1. A remote `ansible-playbook … -l inference` deploy to the Beelink **connects with no
   `-e ansible_host=` override**, both on-LAN and off-net.
2. The change is in `beelink-ansible` (committed), not a one-off flag.
3. From off-net, `https://ai.lab.mtgibbs.dev/health` (Caddy front door → LiteLLM) is **reachable with a
   virtual key** — the documented way to drive the LLM stack remotely. *(Phase 2.)*
4. The remote-ops gap + the working break-glass path (SSH→tailnet IP→Docker-net) are written into
   `tailscale-ops/SKILL.md` so the next session doesn't rediscover it.

## 3. Entities · [E — Entities]

- **`beelink-ai`** — Beelink GTR9 Pro host. LAN `192.168.1.70`; **tailnet `100.123.94.31`**; Tailscale
  machine name `beelink-ai`, tag **`tag:inference`** (status: `tagged-devices`).
- **`inventory.yml`** (beelink-ansible) — group `inference` → host `beelink-ai`. Today relies on
  `~/.ssh/config` Host alias which pins `HostName 192.168.1.70`. Add per-host `ansible_host`.
- **Tailscale tailnet policy (ACL/grants)** — edited in the admin console (HuJSON). Current grants (per
  `tailscale-ops/SKILL.md`): `tag:k8s-operator ↔ autogroup:member` ip `*`; subnet route `192.168.1.0/24`
  → `tag:k8s-operator`. **No grant** for `autogroup:member → tag:inference`.
- **Tailscale identities seen 2026-06-04:** laptop `matts-macbook-pro` `100.94.106.87` (`autogroup:member`);
  `beelink-ai` `100.123.94.31` (`tag:inference`); `pi-cluster-exit` `100.99.139.43` (exit node);
  `tailscale-operator` `100.125.197.43` (`tag:k8s-operator`).
- **Service ports:** Caddy `:443` (host-published, the only external front door); Ollama `:11434` &
  LiteLLM `:4000` are **Docker-internal by design — do NOT expose them**.

## 4. Approach · [A — Approach]

Two phases, smallest-blast-radius first.

- **Phase 1 (unblocks deploys, zero ACL change):** in `beelink-ansible/inventory.yml`, set
  `ansible_host` for `beelink-ai` to the **tailnet path** so Ansible connects over Tailscale regardless of
  where the control machine sits. Preferred value: the **MagicDNS name** (`beelink-ai.<tailnet>.ts.net`,
  stable across IP changes); acceptable literal fallback: **`100.123.94.31`** (known-good, used in the
  2026-06-04 deploy). Tailscale prefers a direct path on-LAN, so on-prem deploys stay fast.
- **Phase 2 (general service reachability) — RESCOPED 2026-06-06.** The original plan
  (member→`tag:inference` ACL grant + MagicDNS split-DNS) was **wrong** for the goal. Investigation
  (OQ3) showed: (a) DNS already resolves off-net — `*.lab.mtgibbs.dev` → Pi-hole `.55` via its `/32`
  route + Tailscale "Override Local DNS"; (b) `ai/chat/dewey.lab.mtgibbs.dev` all resolve to **`.70`**
  (Caddy), set in `pihole-custom-dns.yaml`; (c) the ACL **already** grants `autogroup:member →
  192.168.1.0/24`. The only gap is that **`.70` isn't advertised as a route** — so with the exit node
  active, `.70` traffic blackholes (PROVEN 2026-06-06: ping/curl to `.70` fail while on the tailnet).
  **Fix:** add `192.168.1.70/32` to the Connector's `advertiseRoutes` (`tailscale-config/connector.yaml`)
  — same mechanism as `.55/.56`, falls inside the existing `192.168.1.0/24` autoApprover so it
  **auto-approves** (no admin-console step, no ACL edit, no split-DNS). Then `https://ai.lab.mtgibbs.dev`
  + a LiteLLM virtual key (and the chat/Dewey UIs) work over the tailnet from anywhere.
- **Rejected:** advertising the full home `/24` to the laptop and addressing services by `192.168.1.x` —
  brittle (couples remote ops to LAN topology) and broader than needed. Tailnet-native addressing is the
  norm here.
- **Rejected:** host-publishing Ollama `:11434` / LiteLLM `:4000` — they are internal by design; the
  front door is Caddy `:443`.

## 5. Scope · [S — Structure: boundary]

### In scope
- `beelink-ansible/inventory.yml` — add `ansible_host` to `beelink-ai` (Phase 1).
- Tailscale tailnet policy — one `autogroup:member → tag:inference` grant (Phase 2).
- MagicDNS / split-DNS config so `*.lab.mtgibbs.dev` resolves off-net (Phase 2).
- `.claude/skills/tailscale-ops/SKILL.md` — document the gap, the grant, and the SSH break-glass path.

### Out of scope
- Any change to Ollama/LiteLLM port bindings (stay Docker-internal).
- Flux/K3s manifests (the Beelink is Ansible-managed, not in the cluster).
- Broadening the home `/24` subnet route to member devices.
- The KV/quantization work (done; separate).

## 6. Prior decisions / facts the implementer must know · [S — Structure: system fit & deps]

- The Beelink stack is **Ansible-managed**, source of truth = **`beelink-ansible`** repo (`playbooks/50-ai-stack.yml`); `/opt/ai-stack/docker-compose.yml` on the box is a *rendered artifact* (hand-edits overwritten on git-pull). `beelink-ansible` has **no git remote** (local-only; land via worktree + `--ff-only`).
- Deploy command (reference, 2026-06-04): `ansible-playbook playbooks/50-ai-stack.yml -l inference` with the 12 secrets passed as `--extra-vars` from 1Password via `op read` (header of `50-ai-stack.yml` lists each `op://` path) + `export QNAP_BACKUP_SSH_KEY="$(op read 'op://pi-cluster/synology_backup/private key')"`. `op read` works directly (sandbox off).
- **Break-glass path that works TODAY** (no fix needed): `ssh mtgibbs@100.123.94.31` → on-box → hit the Docker network: Ollama at `http://172.18.0.5:11434` (container IP via `docker inspect`). This is how the 2026-06-04 measurements ran.
- ACL is edited in the Tailscale **admin console** (HuJSON policy) — not currently GitOps'd. `tailscale-ops/SKILL.md` holds the canonical policy snippet; update it in lockstep.
- MagicDNS FQDN form is `beelink-ai.<tailnet>.ts.net` — **confirm the exact `<tailnet>` domain** (OQ1) before using the name; until then the `100.123.94.31` literal is safe.

## 7. Norms · [N — Norms]

- **Tailnet-native addressing** for cross-site ops (MagicDNS name or `100.x`), never LAN `192.168.1.x`.
- **Least-privilege ACL:** prefer `tag:inference:443` over `*` if quick; `*` is acceptable to mirror the
  existing member↔k8s-operator grant — state which was chosen and why in the commit.
- **No secrets in the inventory or spec** — connection creds stay in `~/.ssh/config` + 1Password.
- **Docs in lockstep:** any ACL edit is mirrored into `tailscale-ops/SKILL.md` the same change (the skill
  is the only record since ACLs aren't GitOps'd).

## 8. Safeguards · [S — Safeguards]

- **Never expose Ollama `:11434` or LiteLLM `:4000`** on the host or tailnet — internal-only invariant.
- **Phase 1 must not break on-LAN deploys** — verify a deploy/ping still connects when home.
- **No secret in `inventory.yml`** (it's committed) — `ansible_host` is a hostname/IP only.
- **ACL change is additive** — do not remove or narrow the existing `tag:k8s-operator ↔ member` grants or
  the `192.168.1.0/24` subnet route (Pi-hole remote DNS depends on it).
- **Pi-hole/DNS stays reachable** after any MagicDNS/split-DNS change (don't strand cluster DNS).

## 9. Task breakdown · [O — Operations]

**Phase 1 — inventory (do first; unblocks remote deploy):**
1. In `beelink-ansible/inventory.yml`, under `hosts: beelink-ai:`, add `ansible_host: 100.123.94.31`
   (or the confirmed MagicDNS FQDN). Keep the `~/.ssh/config` identity/user/1Password-agent comment.
2. Commit in `beelink-ansible` via worktree + `git merge --ff-only` to main (no remote).
3. Verify: from off-net, `ansible -i inventory.yml inference -m ping` succeeds with **no** `-e` override.

**Phase 2 — service reachability (when ready):**
4. Add Tailscale grant `autogroup:member → tag:inference` (≥`:443`) in the admin-console policy; mirror
   into `tailscale-ops/SKILL.md`.
5. Make `*.lab.mtgibbs.dev` resolve off-net (MagicDNS split-DNS → Pi-hole, or confirm the `/24` subnet
   route reaches Pi-hole).
6. Verify: off-net `curl -H 'Authorization: Bearer <vk>' https://ai.lab.mtgibbs.dev/health` → `200`.

**Phase 3 — capture:**
7. Write the gap + break-glass SSH path + the Phase-1/2 fix into `tailscale-ops/SKILL.md`.

## 10. Acceptance criteria (EARS) · [O]

- **Ubiquitous:** The `inference` inventory host shall be addressable over Tailscale without a per-run
  `ansible_host` override.
- **Event-driven:** When `ansible-playbook -l inference` is run from off-net, the play shall reach
  `Gathering Facts: ok` (not `UNREACHABLE`).
- **State-driven:** While on the home LAN, an `inference` deploy/ping shall still connect.
- **Unwanted:** If a config addresses the Beelink by `192.168.1.70` from off-net, then it shall be treated
  as a defect (LAN IP is unrouted over the tailnet).
- **Optional (Phase 2):** Where the member→`tag:inference` grant + MagicDNS are in place, off-net
  `https://ai.lab.mtgibbs.dev/health` shall return `200` with a valid virtual key.
- **Safeguard:** If Ollama `:11434` or LiteLLM `:4000` become reachable off-box, then the change is
  rejected.

## 11. Verification (the harness) — `verify.sh`

`verify.sh` in this dir. STATIC tier (offline, gates the change): assert `beelink-ansible/inventory.yml`
gives `beelink-ai` a tailnet `ansible_host` (not a LAN-only alias) and contains no inline secret. LIVE tier
(commented; human-run from off-net): `ansible -m ping` with no override; the Caddy `:443` health curl.

## 12. Open questions

- **OQ1:** ~~Exact MagicDNS tailnet domain?~~ **RESOLVED 2026-06-06:** suffix `tailf8d786.ts.net` →
  `beelink-ai.tailf8d786.ts.net` (→ `100.123.94.31`). Inventory now uses the MagicDNS name; host key
  confirmed identical to the trusted IP and added to `known_hosts`. LIVE `ansible -m ping` → `pong`.
- **OQ2:** Phase-2 grant scope — `tag:inference:443` (least-priv) vs `*` (mirrors existing member grant)?
- **OQ3:** Does the existing `192.168.1.0/24` subnet-route grant already let the laptop resolve Pi-hole
  off-net (making split-DNS unnecessary), or is MagicDNS split-DNS required for `*.lab.mtgibbs.dev`?
- **OQ4:** Should the tailnet ACL be moved into GitOps (e.g. a policy-as-code repo) so it stops living only
  in the admin console + the skill doc? (Bigger initiative; flag only.)

## Two-way sync rule
Logic change → fix spec first. ACL edits MUST be mirrored into `tailscale-ops/SKILL.md` (only record).
