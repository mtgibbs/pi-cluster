# Session Recap — 2026-04-30

Migration cutover: Synology → QNAP for all cluster NFS storage and backup targets. Migration is complete. Synology remains online read-only for ~1 week as rollback, then will be repurposed.

---

## What Was Completed

- All 8 NFS PersistentVolumes now point at QNAP via `storage.lab.mtgibbs.dev` (192.168.1.61).
- All 6 backup CronJobs updated to `cluster-backup` user and `/share/cluster/backups` path on QNAP.
- `coredns-custom` ConfigMap placed under Flux management; forwards `lab.mtgibbs.dev` to Pi-hole.
- DNS naming split finalized: `qnap.lab.mtgibbs.dev` (ingress, LE cert) + `qnap-mcp.lab.mtgibbs.dev` (direct, MCP).
- Sonarr, Radarr, SABnzbd, Immich, Jellyfin, and Postgres backup all validated on QNAP.

---

## Commits (from 8d94afb)

| Hash | Subject |
|---|---|
| `3f6d65c` | feat(dns): flip storage.lab.mtgibbs.dev to QNAP (.61) |
| `3766582` | feat(storage): point NFS PVs at QNAP via storage.lab.mtgibbs.dev |
| `4fd3ce2` | refactor(backup): point CronJobs at QNAP via cluster-backup user |
| `e3ad202` | fix(immich): drop nfsvers=4 from immich-library PV |
| `d4eddf6` | feat(coredns): bring coredns-custom under Flux management |

---

## Key Decisions

**DNS naming split: `qnap.lab` vs `qnap-mcp.lab`**
Mirrors the existing `nas.lab.mtgibbs.dev` (Synology DSM via ingress) pattern. Admin UI traffic goes through ingress and gets a Let's Encrypt cert. MCP traffic goes direct to the appliance on its native port. Different protocols require different DNS paths.

**`coredns-custom` is permanent infrastructure**
CoreDNS was forwarding all queries (including `lab.mtgibbs.dev`) to 1.1.1.1/8.8.8.8 via its default `custom.override` block. This caused cluster pods to receive public wildcard answers (`*.lab.mtgibbs.dev` resolves publicly) instead of the real Pi-hole entries. Added a `lab.mtgibbs.dev.server` block in `coredns-custom` ConfigMap that forwards local-domain queries to Pi-hole. This is not migration-specific — it is a permanent correctness fix now under Flux at `clusters/pi-k3s/coredns-custom/`.

**cluster-backup user must be in administrators group on QNAP**
QNAP's SSH access control list in QTS only allows users in the administrators group. Public key managed via QTS UI (Edit User Properties → SSH Public Keys); survives firmware updates.

**Synology retained read-only for ~1 week**
Rollback safety. User leaning toward repurposing as backup-of-backup once the window passes.

---

## Gotchas

**UDM sending DNS to .51 instead of .55**
UDM Pro Max DHCP server had a stale or misconfigured DNS pointer (.51 rather than .55 / Pi-hole). Cluster clients were querying directly through to Cloudflare and getting the public wildcard. Fixed in UniFi UI. See also the CoreDNS issue above — both were needed.

**Pi-hole/Flux race on ConfigMap restart**
After pushing a Pi-hole ConfigMap update, restarting pods immediately races against Flux propagation. Pods came up with the old ConfigMap. Correct sequence: push → trigger Flux reconcile → wait for Flux to confirm sync → restart pods. Hit this twice.

**QNAP NFSv4 sub-path mounts fail for immich**
The immich PV had `nfsvers=4` explicitly set and could not mount `/share/cluster/photos`. Other PVs work because their export paths align with what QNAP exposes at v4. Fix: remove `nfsvers=4` from the immich PV so it negotiates v3 by default.

**rsync `--numeric-ids` UID drift**
Synology `mtgibbs` is uid 1026; QNAP `mtgibbs` is uid 1000. Files migrated via rsync retain their Synology UIDs. The `cluster-backup` user (uid 1001 on QNAP) could not write into directories owned by uid 1026. Fix: `chown -R` the relevant trees. Affected `/share/cluster/backups/`. Media and photos paths were unaffected because pod UIDs matched the migrated UIDs.

**QNAP firmware update mid-session**
QNAP updated its firmware during the session, which regenerated the MCP server's transport from SSE to streamable HTTP. `.mcp.json` had to switch `type: sse` → `type: http`.

**Claude Code MCP for QNAP non-functional**
Even with a confirmed-valid token and `transport=http`, Claude Code's MCP client would not connect to the QNAP MCP server. `curl` with the same token succeeds. Pivoted to direct kubectl and QTS UI for the rest of the session. Left as an open issue.

**Token leaks (3 occurrences)**
The QNAP RW MCP token leaked into chat three times via different mechanisms: env-var expansion at add-time, `claude mcp get` echoing the resolved value, etc. Token rotated each time. Be paranoid about commands that echo credentials.

---

## Files Modified

- `clusters/pi-k3s/pihole/pihole-custom-dns.yaml` — `storage.lab.mtgibbs.dev` flipped from .60 → .61
- `clusters/pi-k3s/storage/` — PV manifests pointing at QNAP (8 PVs)
- `clusters/pi-k3s/backup-jobs/` — CronJobs updated to cluster-backup user + QNAP paths
- `clusters/pi-k3s/coredns-custom/` — new Flux-managed directory; ConfigMap for lab.mtgibbs.dev forwarding
- `clusters/pi-k3s/external-services/qnap.yaml` — Endpoints + Service + Ingress for QNAP admin UI

---

## Next Steps

- [ ] Synology retirement — leave RO ~1 week, then decide repurpose (backup-of-backup likely)
- [ ] Update `mcp-homelab` `touch_nas_path` — still hardcodes `/volume1/cluster/...` Synology paths; needs path update + key swap to QNAP
- [ ] Bring backup-of-backup workflow online once Synology repurpose is decided
- [ ] Investigate Claude Code QNAP MCP connection failure (curl works, Claude Code does not)
- [ ] Resume Beelink AI stack next session (Tailscale + ROCm stages)
