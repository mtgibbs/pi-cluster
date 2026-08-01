# Pattern: streaming crash / stall diagnosis

**When:** "Jellyfin dropped mid-movie", "Infuse stalls", "playback buffers then dies", "media is slow".

**History (read before concluding):** this has bitten us repeatedly and the root cause has usually
NOT been the server — `nconnect=1` reduced but didn't cure it; the strongest signal has pointed at
**Infuse/Apple TV (client) with zero server-side trace**. The 15-min library scan also caused mid-movie
drops via disk-seek contention (moved to daily 4am). Full state: `docs/incidents/` streaming handoff +
`[[media-services]]`.

## Layers (each independent — fan out one worker per layer)

| # | Layer | Tool(s) | Healthy verdict | Red flags |
|---|---|---|---|---|
| 1 | Jellyfin pod + logs | `get_media_status`, `get_pod_logs jellyfin` | Running; **no** transcode/IO errors at the crash timestamp | ffmpeg abort, "IO error", OOM, restart |
| 2 | NFS mount / NAS health | `test_pod_connectivity`, `touch_nas_path` | mount responsive, low latency | stale mount, slow `touch`, RAID rebuild/scrub running |
| 3 | Storage load timing | correlate crash time vs. **library scan** (daily 4am) + backup CronJobs | crash not during a scan/backup window | crash lines up with scan/backup → seek contention |
| 4 | Network path | `get_conntrack_entries`, `get_node_networking` | stable conntrack, no nconnect thrash | conntrack churn, MTU/retransmit signs |
| 5 | **Client (don't skip)** | which app/device? Infuse/AppleTV vs. web vs. Jellyfin-native | reproduces across clients | **only** one client (Infuse/AppleTV) fails while others are fine → client-side |

## Discipline for THIS scenario

- **Prove the server path (layers 1–4) before touching the client** — but weight layer 5 heavily, because
  history says the culprit is often the client with **no server trace at all**. "No server error" is a
  *finding*, not a dead end — it actively points at the client/network.
- **QNAP "pool 95% full" is thick-provisioning, not real usage** (~37% actual). Don't blame storage-full
  for slow reads — judge by Volume "Used Capacity", not pool free-space.
- A crash with a totally clean server trace across layers 1–4 is the signature of a client/transport issue.

## Synthesis

Line the crash timestamp up across layers. Server error at that time → fix the server layer. Clean server
+ single-client failure → client (Infuse/AppleTV) or its transport. Clean server + crash-during-4am →
scan/backup contention. Escalate to `cluster-ops` only if a server-side change is the fix.
