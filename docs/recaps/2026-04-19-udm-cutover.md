# Session Recap - April 19, 2026

## UDM Pro Max Cutover & Post-Cutover Systems Check

### Executive Summary

Completed Phase 1 of the rack upgrade plan: swapped the UniFi Cloud Key Gen1 + existing router for the UDM Pro Max. DHCP handed back the same IP leases to all four Pi nodes, so no GitOps changes were required. A post-cutover systems check confirmed all cluster services healthy within ~5 minutes of network restoration. Two non-blocking artifacts logged (stale network-unreachable warnings and a brief mtgibbs-site ImagePullBackOff). Tailscale exit-node recovered fully from a 5-minute rough window. One MCP tool discrepancy identified for follow-up filing.

This is a partial rack upgrade. The QNAP NAS and Pi rack migration remain pending.

---

## Cutover Summary

### What Changed

- **Removed**: Cloud Key Gen1 (192.168.1.30, firmware 6.1.71) + previous router/gateway
- **Added**: UDM Pro Max (acting as gateway + UniFi controller)
- **Gateway IP**: 192.168.1.1 (unchanged)

### What Did Not Change

- Node IPs: All four Pi nodes retained their leases post-swap
  - pi-k3s: 192.168.1.55
  - pi5-worker-1: 192.168.1.56
  - pi5-worker-2: 192.168.1.57
  - pi3-worker-2: 192.168.1.51
- No Flux manifests required updating (no hardcoded gateway or controller IPs in GitOps)

---

## Post-Cutover Systems Check

### Cluster

- 4/4 nodes Ready (pi-k3s, pi5-worker-1, pi5-worker-2, pi3-worker-2)
- 105 pods running, 0 problem pods at time of check
- Flux synced to commit `e4d5e65`

### GitOps (Flux)

- 27/27 Kustomizations: Ready
- 7/7 HelmReleases: Ready
- No drift, no reconciliation errors

### DNS

- `diagnose_dns` clean: Pi-hole primary, Pi-hole secondary, Unbound primary, Unbound secondary all healthy
- DNSSEC validation passing

### Certificates

- 25/25 certificates Ready
- None expiring in the near term

### Ingress

- 24/24 ingresses with valid TLS

### Backups

All 6 CronJobs show successful last runs (Sunday 2026-04-19):

| Job | Namespace | Status |
|:----|:----------|:-------|
| pvc-backup | backup-jobs | Succeeded |
| postgres-backup | backup-jobs | Succeeded |
| media-backup | backup-jobs | Succeeded |
| git-mirror | backup-jobs | Succeeded |
| unifi-backup | backup-jobs | Succeeded |
| worker2-backup | backup-jobs | Succeeded |

### Media Services

- Jellyfin: healthy
- Immich: healthy

### Tailscale

- Connector CR `pi-cluster-exit`: `ConnectorReady: True`, ObservedGeneration matches Generation
- Subnet routes for 192.168.1.55/32 and 192.168.1.56/32 confirmed active in Tailscale admin
- Exit-node approval persisted through the cutover (no re-approval required)
- User verified phone tunneling through exit node post-swap

---

## Cutover Artifacts (Non-Blocking)

### Stale "Network Unreachable" Warnings

During the brief network-down window, some pods logged connection errors against .55/.56/.57. These will age out of logs naturally. No action required.

### mtgibbs-site: ImagePullBackOff (Recovered)

The `mtgibbs-site` deployment hit ImagePullBackOff while ghcr.io was unreachable during the swap. Recovered automatically once network restored. 33 restarts logged. User noted this deployment is a testbed — no action required.

### Tailscale Exit-Node: 5-Minute Rough Window

The `pi-cluster-exit` Connector pod logged DERP timeouts and DNS bootstrap failures between approximately 18:32–18:37 UTC, corresponding to the network transition. Fully recovered without intervention. This is expected behavior for any Tailscale node that loses its upstream route briefly.

---

## Finding: MCP Tool Discrepancy (Tailscale Status)

`mcp__homelab__get_tailscale_status` reports `pi-cluster-exit` connector as `ready: false`. However, `kubectl describe connector.tailscale.com pi-cluster-exit` shows:

```
Status:
  Conditions:
    Reason: ConnectorReady
    Status: True
  ObservedGeneration: <matches Generation>
```

The MCP tool appears to be reading a stale or incorrect field from the Connector CRD status. The cluster-side truth is healthy. This should be filed as a bug against the pi-cluster-mcp repo.

- **Action**: Open issue against `mtgibbs/pi-cluster-mcp` for incorrect `ready` field reporting on Tailscale Connector resources.

---

## Open Questions

### UniFi Controller URL

The CK Gen1 at 192.168.1.30 served as the UniFi controller. The UDM Pro Max includes a built-in controller. It is not yet confirmed whether:

- The CK Gen1 has been fully retired and decommissioned
- The `unifi-backup` CronJob's controller target has been updated to the UDM Pro Max's address
- The go-unifi-mcp local stdio transport has been reconfigured to point at the new controller

The UniFi backup CronJob and go-unifi-mcp both had the CK Gen1 (`192.168.1.30:8443`) as their controller endpoint. If the CK Gen1 is now retired, these need to be updated.

- **Action**: Confirm UDM Pro Max controller URL and update `unifi-backup` CronJob manifest and go-unifi-mcp auth config accordingly.

---

## What's Next (Remaining Rack Cutover Phases)

The cutover plan has three remaining phases:

- [ ] **QNAP NAS arrival and setup** - Replace temporary Synology with QNAP TS-435XeU (1U 4-bay). Migrate PVC backup target, media NFS mount, and postgres backup paths. Update Synology-specific SCP flags (`-O`) if QNAP uses a different SCP implementation.
- [ ] **Pi rack migration** - Move Pi worker nodes (workers first, master last) into the rack chassis. Verify nodes rejoin cluster cleanly after physical move. Check that static lease reservations in UDM Pro Max DHCP match prior assignments.
- [ ] **UniFi controller consolidation** - Confirm CK Gen1 retirement. Update unifi-backup CronJob and go-unifi-mcp config to target UDM Pro Max controller. Verify go-unifi-mcp auth flow against UDM Pro Max API (UDM Pro Max uses `/api/auth/login`, not the classic `/api/login` used by CK Gen1 — confirm compatibility).
- [ ] **Post-migration validation** - Run full `diagnose_dns`, certificate check, backup trigger, and Tailscale exit-node smoke test after each physical migration step.

---

## Relevant Commits

No GitOps commits were required for this session. The cutover was transparent to Flux.

Most recent commit at time of cutover: `e4d5e65` - chore: disable qBittorrent and update UniFi backup skill docs

---

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
