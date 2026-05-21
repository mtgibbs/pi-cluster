# Session Recap — 2026-04-27

Two parallel tracks worked simultaneously: completing QNAP Phase 1 storage prep, and bringing the Beelink GTR9 Pro from bare metal to a hardened, Docker-ready Ansible-managed host.

---

## QNAP Track: Phase 1 Storage Prep

### What Was Done

- Created `cluster` shared folder on DataVol1 via QNAP MCP (RW token).
- Created full subdirectory tree: `media/{video,downloads,music,books}`, `photos`, `calendar`, `backups`.
- Enabled NFS service (v3 + v4 + v4.1) and SSH service on QNAP.
- Volume expanded from 3.52 TB to 16.36 TB (thick volume LVM-style resize on Storage Pool 1).
- Created `cluster-backup` user (uid 1001, group `everyone`, no admin) via QTS web UI.
- Permissions: `mtgibbs` and `cluster-backup` have RW on `cluster` share.
- QNAP MCP servers (`qnap-ro`, `qnap-rw`) wired into project-scoped `.mcp.json` with env var token references (not literal values).

### Current Blocker

Phase 1d is the gate: NFS export rules for the `cluster` share must be configured in the QTS web UI. This is not exposed via the QNAP MCP API and requires a manual UI step.

Until NFS exports are configured, the cluster cannot mount the QNAP share and the rsync cannot begin.

### Phase Status

| Phase | Description | Status |
|---|---|---|
| 0 | QNAP pool + volume created | Done |
| 1a | `cluster` shared folder + full subdir tree | Done (2026-04-27) |
| 1b | NFS service (v3/v4/v4.1) + SSH enabled | Done |
| 1c | `cluster-backup` user created | Done |
| 1d | NFS export rules in QTS UI | **Blocked — next manual step** |
| 1e | Mount test from cluster | Not started |
| 2 | Initial rsync Synology → QNAP | Not started |
| 3 | `storage.lab.mtgibbs.dev` DNS + new PV manifests | Not started |
| 4 | Maintenance window: scale down, final rsync, flip DNS, apply new PVs | Not started |
| 5 | Verify + Synology read-only for rollback week | Not started |
| 6 | Retire Synology | Not started |

### NFS Export Config (for Phase 1d)

Try CIDR `192.168.1.0/24` first. Fall back to per-IP (`192.168.1.55`, `.56`, `.57`, `.51`) if QTS rejects CIDR, matching the Synology pattern.

Settings:
- Privilege: Read/Write
- Squash: **No mapping** (preserves client UIDs — no all_squash, no root_squash)
- Security: sys
- Async: enabled
- Allow non-privileged ports: enabled
- Allow users to access mounted subfolders: enabled

---

## Beelink Track: Physical Bring-Up to Docker-Ready

### Hardware (Actual, Corrected)

- **Model:** Beelink GTR9 Pro
- **IP:** `192.168.1.70` (static DHCP reservation on UDM Pro Max)
- **CPU:** AMD Ryzen AI Max+ 395
- **RAM:** 128 GB unified (BIOS-allocated: 30 GB system / ~96 GB GPU VRAM — left as-is)
- **Storage:** 1x Crucial P310 2 TB NVMe — single drive, not dual as the handoff doc assumed
- **GPU:** AMD Radeon 8050S/8060S (Strix Halo iGPU)
- **NIC:** Dual 10GbE, one active: `enp197s0`
- **Kernel:** 7.0.0-14-generic

### OS: Ubuntu 26.04 LTS (Resolute)

The user's ISO was Ubuntu 26.04 (Resolute), NOT 24.04 as the handoff doc assumed. All references to 24.04 are incorrect.

### Install Decisions

| Decision | Value | Rationale |
|---|---|---|
| Filesystem | LVM on single NVMe | Flexibility for future model volume growth |
| Snaps | None | Minimized attack surface |
| Third-party drivers | Enabled | AMD GPU firmwares |
| Server variant | Base server (not minimized) | Ansible needs standard toolchain available |
| GitHub key import | Skipped | Explicit 1P-vaulted key is the security model |

### OS Configuration

- **Hostname:** `beelink-ai`
- **User:** `mtgibbs`, NOPASSWD sudo (required for Ansible non-interactive; tradeoff acknowledged)
- **SSH key:** Generated in 1Password (vault: `pi-cluster`, item: `beelink-ai SSH`). 1Password SSH agent serves the key.
- **`~/.ssh/config` Host block:** Pins `IdentityFile` + `IdentitiesOnly yes` for `beelink-ai` — solves "too many auth failures" caused by 1Password serving all available keys.
- **Password auth:** Disabled
- **Root login:** Disabled
- **SSH lockdown via drop-in:** `/etc/ssh/sshd_config.d/01-hardening.conf` — Ubuntu loads `sshd_config.d/*.conf` before the main config; `01-` wins over `50-cloud-init.conf` (first-match-wins).
- **fail2ban:** Watching sshd

### Ansible Repo

Separate repo: `~/dev/beelink-ansible/` — NOT a subfolder of `pi-cluster`. Vision: `pi-cluster` eventually becomes a homelab umbrella with submodules.

Two commits shipped today:

| Commit | Content |
|---|---|
| `383f765` | Initial scaffold: `00-bootstrap`, `10-hardening`, inventory, `ansible.cfg`, `group_vars/all.yml` |
| `be7cbc4` | `20-docker`: Docker Engine CE 29.4.1 + Compose plugin v5.1.3 |

### Ansible Stages Applied

| Stage | Playbook | Status |
|---|---|---|
| Bootstrap | `00-bootstrap.yml` | Applied — apt upgrade, base packages, timezone `America/New_York` |
| Hardening | `10-hardening.yml` | Applied — UFW (LAN-only), unattended-upgrades, fail2ban, SSH lockdown |
| Docker | `20-docker.yml` | Applied — Docker CE + Compose from official apt repo |

### Docker: `noble` Repo Pin (Gotcha)

Docker's upstream apt repo does not yet publish packages for Ubuntu 26.04 (`resolute`). The `20-docker` role pins the apt repo to `noble`. The `noble` Docker packages are forward-compatible with `resolute`'s kernel. Do not change this to `resolute` until Docker upstream adds the distro.

### Rebuild From Scratch

1. Fresh Ubuntu 26.04 Server install:
   - LVM filesystem, base server variant (not minimized)
   - OpenSSH server enabled during install
   - No snaps, third-party drivers enabled
   - No GitHub key import during install
2. After first boot, add `mtgibbs` to sudoers with NOPASSWD: `echo 'mtgibbs ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/mtgibbs`
3. Extract public key from 1Password (vault: `pi-cluster`, item: `beelink-ai SSH`) and add to `~/.ssh/authorized_keys` on the host.
4. On dev machine: ensure `~/.ssh/config` has a `Host beelink-ai` block with `IdentityFile` pointing to the extracted key and `IdentitiesOnly yes`.
5. Save `~/.ssh/beelink-ai.pub` on dev machine (extract via `ssh-keyscan` or 1Password export).
6. Clone `beelink-ansible`: `git clone git@github.com:mtgibbs/beelink-ansible.git ~/dev/beelink-ansible`
7. Run: `ansible-playbook playbooks/site.yml`

---

## Key Decisions

**QNAP NFS squash: "No mapping"** — matches Synology exactly. UIDs preserved client-to-server; no anonymous-identity NFS user needed.

**NFS export: try CIDR first** — simpler than per-IP; fall back to per-IP if QTS rejects it.

**Beelink: Docker Compose, NOT k3s** — failure isolation from Pi cluster is the priority. If Flux pushes a bad manifest, inference must keep serving.

**Separate `beelink-ansible` repo** — not a subfolder of `pi-cluster`. Future plan: homelab umbrella repo with submodules.

**Memory allocation: 30 GB system / 96 GB GPU, leave as-is** — adequate for planned services; can revisit BIOS allocation if pressure emerges later.

**LVM on Beelink** — single NVMe, LVM for future model storage flexibility.

**SSH key: 1Password agent + per-host IdentityFile pin** — solves multi-key auth failures from 1Password agent offering all keys to every host.

**GitHub key import skipped** — security model requires 1Password access to SSH in. Explicit vault-based key only.

**NOPASSWD sudo** — required for non-interactive Ansible; acknowledged tradeoff.

**Docker apt repo pinned to `noble`** — Docker upstream lags 26.04 (`resolute`); `noble` packages forward-compatible.

**VLANs deferred** — flat `192.168.1.0/24` on UDM Pro Max for v1. VLANs are a v2 project.

**SOPS+age rejected** — web Claude's handoff doc proposed it. Rejected in favor of existing 1Password + ExternalSecrets pattern from `pi-cluster`.

**SSH lockdown via drop-in file** — `sshd_config.d/01-hardening.conf` wins over `50-cloud-init.conf` (Ubuntu first-match-wins ordering); avoids editing the main `sshd_config` file directly.

---

## What Remains

### QNAP (blocking data migration)

- [ ] Configure NFS export rules on `cluster` share in QTS web UI (Phase 1d)
- [ ] `showmount -e 192.168.1.61` test from cluster + test mount + write test
- [ ] Initial rsync Synology → QNAP (background, expected hours)
- [ ] Add `storage.lab.mtgibbs.dev` to Pi-hole local DNS
- [ ] Prep new PV manifests (env-var DNS name, new paths)
- [ ] Maintenance window: scale apps down, final rsync, flip DNS, apply new PVs
- [ ] Verify, then retire Synology

### Beelink (next Ansible stages)

- [ ] `30-tailscale.yml` — Tailscale install + auth from 1Password
- [ ] `40-rocm.yml` — AMD ROCm 6.x for Strix Halo (kernel modules, render/video group memberships)
- [ ] LiteLLM + Ollama Compose stack (Phase 0 step 6 per `docs/beelink-ai-stack.md`)
- [ ] Pull models: `qwen3.5:35b-a3b`, `qwen3-coder:30b-a3b`, `gemma3:27b`, `qwen3.5:9b`, `nomic-embed-text`
- [ ] Pi-hole local DNS: `ai.lab.mtgibbs.dev` → `192.168.1.70`
- [ ] Verify LiteLLM reachable from Pi cluster

### Pi Cluster (after Beelink LiteLLM is live)

- [ ] Phase 3: n8n — verify SQLite vs Postgres, migrate if needed
- [ ] Phase 4: signal-cli + Signal workflow
- [ ] Phase 5: Home Assistant + MCP servers
- [ ] Phase 6: Proactive flows

### Decisions Still Pending

- Bot mailbox provider (Cloudflare Email Routing on `lab.mtgibbs.dev` vs new domain)
- Signal phone number (new SIM, Google Voice, other)
- Authelia/SSO deployment scope
- Backup target for Beelink config + n8n Postgres (likely QNAP `/cluster/backups/` once migration completes)
