# Spec: UniFi under OpenTofu — pilot (DNS-lockdown firewall objects)

> **REASONS Canvas** (see `mtgibbs/jig:specs/TEMPLATE.md`). Constraints-before-work order.

- **Status:** DRAFT 2026-11-19. Phase 0 is a go/no-go probe. Nothing after it starts until Phase 0 passes.
- **Owner:** Matt
- **Constitution:** `specs/constitution.md` (+ `/CLAUDE.md`)
- **Origin:** `docs/research/spacelift-eval.md` (PR #277). That eval found Spacelift's free tier can't reach the LAN. Its recommended pilot was "UniFi under OpenTofu, executed in-lab".
- **Touches:** new `infra/unifi/` (OpenTofu code); new `clusters/pi-k3s/tofu-controller/` and `clusters/pi-k3s/iac-unifi/` (Flux); `flux-system/infrastructure.yaml`; `flux-notifications/`; `.claude/skills/unifi-ops/SKILL.md`; regenerated `docs/secrets-map.md` and `docs/domain-map.md`.

---

## 1. Why · [R]

The UDM Pro Max is the one load-bearing system in the lab that isn't code. The YouTube/short-form blackout depends on it: the DNS lockdown firewall, the DoH block, the IPv6 RDNSS pair and remote syslog all live **on the box**. Their only record is a hand-maintained table in `unifi-ops/SKILL.md`. A from-scratch rebuild does not "just work" (see `feedback_everything_as_code`).

**That record has already rotted.** A read-only inventory on 2026-11-19 (unifi MCP) shows the following:

- The site is now on the **zone-based firewall**. `list_firewall_rule` returns `[]`. The lockdown lives in `firewall_zone_policy` objects.
- **Every object ID is now a UUID.** The site ID, network ID and group IDs all changed (e.g. `fw-dns-infra` is now `3deaee48-af4b-4a49-9ea8-6ff4c086f142`, not `6a42d234…`). That points to a controller migration to Network 10/11.
- The migration **fanned each legacy rule out ×4**, one per destination zone. That makes 5 rule intents × 4 copies = **20 zone policies**.
- The SKILL.md table ("legacy firewall — this site is not zone-based"), its Mongo-style IDs and its **break-glass `curl` commands** (`/rest/firewallrule/<old-id>`) are therefore all stale. The break-glass path would fail during the exact incident it exists for.

Turning live config into code is how this stops happening.

## 2. Outcomes (Definition of Done) · [R]

1. The DNS-lockdown objects (4 firewall groups + 20 zone policies) are declared in `infra/unifi/` and **adopted by import**. The first apply changes **nothing** on the UDM.
2. An in-cluster executor (tofu-controller) reconciles them. Every apply is gated by a **merged PR**: the plan approval is itself a git commit.
3. A hand edit to a managed object in the UniFi UI (or via the MCP) is **detected as drift within one interval** and alerted through the existing ntfy/Discord path. It is **never auto-reverted**.
4. The "infra always resolves" invariant (`fw-dns-infra` ⊇ `192.168.1.48/28` + `.70`, and an ALLOW precedes every BLOCK) is **enforced in code**, so `tofu plan` fails if it's violated.
5. `unifi-ops/SKILL.md` describes the **real** (zone-based) state. Its object table points at the code instead of duplicating it, and the break-glass path works.

## 3. Entities · [E] (live, read 2026-11-19)

- **Controller:** UDM Pro Max `192.168.1.1`, site `default` (`site_id 09971510-a913-4e8c-a174-dda60fa77d00`). Devices: UDMPROMAX, U6 LR, U7IW, US16P150. *Network application version: not exposed by the MCP; see Phase 0.*
- **Networks:** `Default` (LAN `192.168.1.0/24`, id `c89699d7-…`, zone Internal), `Internet 1`/`Internet 2` (WAN, zone External). No VLANs.
- **Zones:** Internal `bc4a5c4d-…`, External `c1168cec-…`, Gateway `cd608486-…`, Vpn `6bfba301-…`, Hotspot `a9882c6d-…`, Dmz `0d60e1b0-…`.
- **Firewall groups (pilot scope):**

  | name | type | id | members |
  |---|---|---|---|
  | `fw-dns-infra` | address | `3deaee48-af4b-4a49-9ea8-6ff4c086f142` | `192.168.1.48/28`, `192.168.1.70` |
  | `fw-dns-ports` | port | `e796b77d-61d8-40e1-9b65-8657e388b772` | 53, 853 |
  | `fw-doh-endpoints` | address | `0eb3a16c-09a7-4f53-bed9-83e23049d9f7` | 17 DoH resolver IPs |
  | `fw-doh-ports` | port | `2aaf6145-d92f-46c0-a915-73dfaa2810bf` | 443 |

- **Zone policies (pilot scope).** Source zone is always Internal. Each intent exists ×4, one per destination zone: **Internal, External, Hotspot, Vpn** (Gateway and Dmz are not covered). All four copies share the same `index`: 10000 ALLOW → 10001 BLOCK → 10002 ALLOW → 10003 BLOCK → 10004 BLOCK v6. ALLOWs match `source.ip_group_id = fw-dns-infra`.

  | intent | action | v | sample id |
  |---|---|---|---|
  | Allow DNS-infra resolvers out (Unbound+bootstrap) | ALLOW | 4 | `1c13af90-…` |
  | Block public DNS bypass (force Pi-hole) [LOG] | BLOCK | 4 | `24d34789-…` (idx 10001, dst Internal) |
  | Allow DNS-infra to DoH endpoints (invariant exemption) | ALLOW | 4 | `08283c78-…` |
  | Block DoH endpoints on :443 (force Pi-hole) [LOG] | BLOCK | 4 | `3f9095ea-…` |
  | Block public DNS bypass IPv6 (force Pi-hole) [LOG] | BLOCK | 6 | `dbbc152d-…` |

  The remaining ~60 policies are `predefined` zone defaults ("Allow Return Traffic", "Block All Traffic", …). They are **out of scope**. Never import or manage them.
- **Out-of-pilot but recorded** (the next phases): `Default` network DHCP DNS `.55/.56`, `dhcpdv6_dns_1/2` = `fe80::cef4:1f47:81cf:14d7` / `fe80::61bf:9c92:249a:8cc1`, `ipv6_interface_type pd`, RA valid 86400. `rsyslogd` → `192.168.1.55:30514`, `log_all_contents`. One WLAN `pwny-wireless-AP` (wpapsk). No port forwards, static routes, DNS records or port profiles.
- **Provider:** `ubiquiti-community/unifi`. Latest is v0.65.0 (2026-11-01), with frequent releases, API-key auth (`api_key`, `allow_insecure`), and resources `unifi_firewall_group`, `unifi_firewall_zone` (data source too) and `unifi_firewall_policy`. Import is by `<id>` or `<site>:<id>`. v0.60.0 broke the attribute layout (nested `ipv6 = {…}`), so pin exactly. `filipowm/unifi` (v1.1.0, July, no release since) is the fallback.
- **Executor:** `flux-iac/tofu-controller`, v0.17.0 (2026-11-16, active). It publishes linux/arm64 images, uses the `infra.contrib.fluxcd.io/v1alpha2` API (v1alpha1 was removed in 0.17), defaults to a Kubernetes-Secret state backend (`tfstate-default-<name>`), has drift detection on by default, and offers manual mode (`approvePlan` blank → plan is held → set `approvePlan: plan-main-<sha8>` to apply).

## 4. Approach · [A]

**Executor: tofu-controller in-cluster.** It's pull-based and Flux-native, the runner pod already sits on the LAN next to the UDM, and it opens no new inbound path.

- **Rejected: GitHub Actions self-hosted runner.** `mtgibbs/pi-cluster` is **PUBLIC**. A self-hosted runner on a public repo executes fork-PR workflow code on a LAN host that holds a firewall-admin key. That's the worst blast radius in the lab. A private side-repo would fix it, but at the cost of splitting the source of truth.
- **Rejected: Spacelift/Atlantis/Terrakube.** See the eval: a SaaS control plane or another inbound service, for nothing tofu-controller lacks.
- **Rejected: laptop-only `tofu apply`.** It would be code without a reconciler. Drift goes unseen and the checkpoint is honour-system.

**The human checkpoint is the PR, twice:**

1. A PR changes `infra/unifi/*.tf` → review → merge.
2. tofu-controller plans and **holds** (manual mode). It posts "plan pending" to ntfy with the plan id.
3. Matt reads the plan (laptop: `tfctl show plan` or the plan Secret). Then a **second, one-line PR** sets `approvePlan: plan-main-<sha8>` → merge → apply.

This is deliberately two PRs. The first reviews *intent*, the second approves the *computed effect*. The approval can't be rubber-stamped by the same merge, and no one (human or agent) applies from a shell.

**Adopt, don't create.** All 24 objects come in through OpenTofu `import {}` blocks keyed by the live IDs in §3. The acceptance bar for the first apply is `24 to import, 0 to add, 0 to change, 0 to destroy`. Anything else means the code is wrong, not the UDM.

**Model the fan-out, don't hand-copy it.** Each intent is one resource with `for_each` over the destination zones it covers today. That's ~5 blocks for 20 policies, and the ×4 copy becomes a property you can read in the code.

**Phased, smallest blast radius first:**

| Phase | What | Mutates UDM? |
|---|---|---|
| 0 | Probe: version, provider pin, import-plan dry run, fix stale SKILL.md | No |
| 1 | `infra/unifi/` code + invariant checks + verify gate | No |
| 2 | tofu-controller + credential + Terraform CR (manual mode) + alerts | No |
| 3 | Adopt: first plan (imports only) → approve PR → apply | No-op apply |
| 4 | Drift positive control | One harmless UI edit, reverted |
| later | rsyslogd, Default network DNS/IPv6, WLAN | Separate specs |

## 5. Scope · [S]

**In:** the 4 groups and 20 non-predefined zone policies in §3. The tofu-controller install. One ExternalSecret. One Terraform CR. One Flux alert. SKILL.md correction. Regenerated docs.

**Out (each is its own later spec):**
- `Default` network. Provider issues #718 (Default LAN never converges on Network 11) and #723 (first update of an imported Default LAN fails) make it unsafe today, and it carries DHCP for the whole house.
- WLAN (passphrase lands in state unless `passphrase_wo` is used).
- `unifi_setting` (rsyslogd/mgmt). The mgmt writes regenerate `x_api_token`.
- Predefined zone policies.
- Branch planner (tech preview, and needs a PR-write token).
- Cloudflare DNS and GitHub settings (the next IaC candidates from the eval).

## 6. Prior decisions / facts the implementer must know · [S]

- **The invariant that prevents the 2026-06-29 deadlock:** CoreDNS forwards to `1.1.1.1/8.8.8.8` and pi-k3s bootstraps on public DNS. If the cluster loses public DNS, Flux can't pull the fix. **tofu-controller is itself an in-cluster consumer of that path.** A bad apply that drops infra DNS strands the very reconciler that would revert it. Break-glass must therefore never depend on the cluster (§8).
- ALLOW policies must have a lower index than their BLOCK siblings, and must exist first.
- The UDM's **API key is bound to an admin account.** Network-admin rights are required: a login-only account authenticates but 403s on `/proxy/network`.
- The existing `unifi` 1Password item is marked **SHARED** in `docs/secrets-map.md` (backup CronJob, Homepage, and its `api-key` field feeds the AI-facing unifi MCP). **Decision: mint a new identity for tofu, not a reuse.** It's a write-capable automation actor and needs its own UDM audit-log attribution and blast radius, so rotating the MCP key must not break IaC and vice versa. This is the "genuinely per-workload" exception in the secrets-graph rule. Matt can overrule it (OQ2).
- Generated docs: adding an ExternalSecret changes `docs/secrets-map.md`, and a new Flux Kustomization changes `docs/domain-map.md`. Re-run both generators. CI rejects hand edits.
- The container has no `kubectl`, `tfctl` or `op`. Reading the plan and creating the UniFi admin and API key are **Matt's laptop/UI steps** (§9). The coding harness only writes code and PRs.
- Plan visibility without the branch planner means the plan is only readable in-cluster. That's acceptable for the pilot (one person, low change rate). Revisit with the branch planner later, reusing an existing GitHub bot identity with PR-write (`feedback_credentials_scale_by_role`).

## 7. Norms · [N]

- **Pin everything:** the provider exactly (`= 0.65.0`, or whatever Phase 0 proves), OpenTofu, and the tofu-controller chart and images.
- **Code is the record.** SKILL.md links to `infra/unifi/` for object definitions and keeps only runbook prose, break-glass and gotchas.
- **Names stay byte-identical** to the live objects, so imports match and the Loki/syslog `[LOG]` searches keep working.
- **Agents may author `infra/unifi/` PRs** (agent queue, harness). Only the merged `approvePlan` PR applies. No agent holds the tofu UniFi key. It lives only in the runner pod's Secret.
- **Managed objects become read-only by convention** for the unifi MCP and UI. Changes go through a PR. The MCP stays for reads and unmanaged objects.

## 8. Safeguards · [S]

- **Never auto-apply.** `approvePlan` stays blank or explicit in git. `auto` is rejected by the verify gate.
- **Never auto-revert drift.** Drift produces a held plan plus an alert. A human decides whether the code or the box is right.
- **Reject any plan that destroys or replaces** an ALLOW policy or `fw-dns-infra`, or that adds a BLOCK without its ALLOW sibling. This is enforced by `check`/`precondition` blocks in code and by the human on the approve PR.
- **Invariant in code:** a `precondition` asserts `fw-dns-infra` contains `192.168.1.48/28` and `192.168.1.70`, and that each BLOCK intent's ALLOW sibling has a lower index across the same zone set.
- **Don't import predefined policies.** Importing then dropping one from code would plan a destroy of a zone default.
- **Break-glass is off-cluster:** the UDM UI, or a corrected API-key `curl` from the laptop, recorded in SKILL.md in Phase 0. After a break-glass edit, the next plan shows it as drift. Reconcile it via PR. Don't approve a revert blindly.
- **State hygiene:** the pilot resources hold no secrets, and the provider credential is never in state. The state Secret is reconstructible by re-import, which is why the K8s backend is acceptable (OQ3).
- Runner pods are scheduled on Pi 5 nodes only, never `pi3-worker-2` (1 GB).

## 9. Task breakdown · [O]

**Phase 0 — probe (laptop, read-only; GO/NO-GO):**
1. Record the Network application version: `GET https://192.168.1.1/proxy/network/api/s/default/stat/sysinfo` with the existing API key, or Settings → System in the UI.
2. Cross-check against provider issues #715 (import-by-UUID fails on Network 11), #716 (zone/NAT duplication after upgrade) and #717/#718. If #715 bites, try `<site>:<id>` and the `name=` form. Names are ×4 duplicates, so `name=` is ambiguous for policies. If import can't address UUIDs, the result is **NO-GO**: file or track upstream and stop. Never fall back to create-then-delete.
3. Write `infra/unifi/` minimally (provider + the 4 groups) and run `tofu plan` with `import {}` blocks. A plan with imports is **read-only**. Expected: `4 to import, 0 add/change/destroy`. Then extend it to one policy intent (×4).
4. Fix `unifi-ops/SKILL.md` now, independent of the IaC outcome: replace the legacy table with the zone-based reality and UUIDs, and rewrite the break-glass `curl` for zone policies (the endpoint differs from `/rest/firewallrule`, so confirm it during the probe).

**Phase 1 — code (harness, PR):**
5. `infra/unifi/`: `versions.tf` (pins), `provider.tf` (`api_url`, `allow_insecure = true`, key from env `UNIFI_API_KEY`), `groups.tf`, `policies.tf` (5 intents, `for_each` over destination zones), `imports.tf`, `invariants.tf` (`check`/`precondition`).
6. `specs/unifi-tofu-pilot/verify.sh` STATIC tier green (see below).

**Phase 2 — executor (harness + Matt):**
7. Matt: create the UDM local admin `tofu` with Network admin rights and an API key, and store it in 1Password as `unifi-tofu` / field `api-key`. This is a one-time bootstrap credential, the documented exception to "no UI-only config".
8. Harness (cluster-ops): `clusters/pi-k3s/tofu-controller/` (HelmRelease v0.17.0, branch planner off, nodeAffinity off pi3) and `clusters/pi-k3s/iac-unifi/`. The latter holds an ExternalSecret `unifi-tofu` → Secret, a `Terraform` CR (`sourceRef` flux-system GitRepository, `path: ./infra/unifi`, `approvePlan: ""`, `interval: 1h`, runner env from the Secret), and a Flux `Alert` on the Terraform kind to the existing ntfy/Discord provider. Wire them into `infrastructure.yaml` with `dependsOn: external-secrets-config`. Regenerate the two maps.

**Phase 3 — adopt:**
9. Merge → controller plans → Matt reads the plan. It must be imports only.
10. Approve PR: `approvePlan: plan-main-<sha8>` → merge → apply. Confirm via the unifi MCP that the object IDs and fields are unchanged.

**Phase 4 — prove drift detection can fire (positive control):**
11. In the UI, change the description or name suffix on **one ALLOW** policy (harmless). Within one interval, expect a held plan and an ntfy alert. Revert in the UI and confirm the plan clears. Record the timings in the spec.

## 10. Acceptance criteria (EARS) · [O]

- **Ubiquitous:** The 4 groups and 20 zone policies shall be declared in `infra/unifi/`, and the managed set shall contain no `predefined` policy.
- **Event-driven:** When `infra/unifi/` changes on `main`, tofu-controller shall produce a plan and hold it until `approvePlan` names that plan.
- **Event-driven:** When the first plan is computed, it shall be `24 import, 0 add, 0 change, 0 destroy`.
- **State-driven:** While a managed object differs from code, a drift plan shall be pending and one alert shall have fired.
- **Unwanted:** If `approvePlan: auto` appears, or the plan would destroy or replace an ALLOW policy or `fw-dns-infra`, then the change shall be rejected.
- **Unwanted:** If `fw-dns-infra` lacks `192.168.1.48/28` or `192.168.1.70`, then `tofu plan` shall fail.
- **Safeguard:** If a client can reach `@8.8.8.8:53` after any apply, or a pod's external resolution breaks (`source-controller` shows `server misbehaving`), then roll back via break-glass. The SKILL.md verify steps apply, including the exit-node trap.

## 11. Verification — `verify.sh`

**STATIC (offline, gates the PR):**
- `tofu fmt -check` and `tofu validate` on `infra/unifi/` (skipped if `tofu` is absent).
- No `api_key =` literal or secret-looking value in `infra/unifi/`.
- No `approvePlan: auto` in `clusters/pi-k3s/iac-unifi/`.
- `fw-dns-infra` members in code include both invariant entries.
- No import ID for a `predefined` policy.
- Spec self-consistency.

**LIVE (human, laptop):** the Phase 3 import-only plan, the Phase 4 drift control, and the SKILL.md DNS checks (bypass times out, `@192.168.1.55` resolves, `source-controller` clean).

## 12. Open questions

1. **Network application version** (Phase 0). Every provider risk keys off whether this is Network 11.
2. **Mint vs reuse:** is a dedicated `tofu` UDM admin and API key (recommended) OK, or reuse the shared `unifi` item?
3. **State backend:** the K8s Secret default (recommended, since the state is reconstructible and secret-free for this scope), or a QNAP S3 bucket? If the QNAP exposes S3 (QuObjects), it would outlive a cluster rebuild.
4. **Is the ×4 zone fan-out intended?** Each intent covers Internal→{Internal, External, Hotspot, Vpn}, presumably inherited from the legacy→zone migration. Internal→External is the copy that stops public-resolver bypass. Two things to settle: whether **Internal→Gateway** (the UDM's own `:53`) should be blocked too, and whether the fan-out should be narrowed. Both belong in a *follow-up* PR, never in the adopt PR.
5. **Plan visibility:** is a held plan readable only from the laptop good enough, or should the branch planner be enabled now?
