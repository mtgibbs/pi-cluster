# Session Recap - January 16, 2026

## Usenet Integration & Proton VPN Migration

### Executive Summary

Completed a major enhancement to the media automation stack by integrating Usenet as the primary download method, with torrents as fallback. This session involved migrating from Mullvad VPN to Proton VPN (for port forwarding support), deploying SABnzbd as the Usenet downloader, and configuring a tiered download strategy where Usenet (via Newshosting) is attempted first before falling back to torrents.

### Completed Work

#### 1. Proton VPN Migration

**What**: Migrated from Mullvad to Proton VPN for the qBittorrent/Gluetun setup

**Why**:
- Mullvad deprecated port forwarding, causing poor torrent connectivity
- DHT/PeX/LSD were blocked, limiting peer discovery to tracker announces only
- Proton VPN supports dynamic port forwarding with NATPMP

**How**:
- Created `protonvpn-credentials` ExternalSecret mapping to 1Password vault
  - `OPENVPN_USER` from `protonvpn-credentials/username`
  - `OPENVPN_PASSWORD` from `protonvpn-credentials/credential`
- Updated `qbittorrent.yaml` to use Proton VPN server: `VPN_SERVICE_PROVIDER=protonvpn`
- Added auto-port-update script via `VPN_PORT_FORWARDING_UP_COMMAND`:
  ```bash
  /bin/sh -c 'wget --tries=10 --timeout=5 --waitretry=5 --post-data="{\"listen_port\": $(cat /tmp/gluetun/forwarded_port)}" --header="Content-Type: application/json" --user=$QBIT_USER --password=$QBIT_PASS http://localhost:8080/api/v2/app/setPreferences || echo "Failed to update qBittorrent port"'
  ```
- Disabled Gluetun's built-in firewall (`FIREWALL=off`) to allow UDP tracker traffic
- Result: DHT, PeX, and Local Peer Discovery now functional

**Trade-offs**:
- Some public trackers still block VPN IPs, but DHT/PeX compensate
- Gained dynamic port forwarding at the cost of firewall automation

**Files Modified**:
- `clusters/pi-k3s/media/external-secret.yaml` - added protonvpn-credentials ExternalSecret
- `clusters/pi-k3s/media/qbittorrent.yaml` - updated VPN config, added port update command

**Relevant Commits**:
- `5e78e2f` - feat: switch from Mullvad to Proton VPN for port forwarding
- `fbed69a` - feat: auto-update qBittorrent listening port on VPN port change
- `ebbeffd` - fix: disable Gluetun firewall to allow tracker UDP traffic

---

#### 2. SABnzbd Deployment

**What**: Deployed SABnzbd as the Usenet downloader for the media automation stack

**Why**:
- Usenet provides faster, more reliable downloads than torrents
- Better availability for older/rare content
- No reliance on seeders
- Higher priority than torrents in the download strategy

**How**:
- Created new deployment manifest `clusters/pi-k3s/media/sabnzbd.yaml`:
  - Image: `linuxserver/sabnzbd:latest`
  - Namespace: `media`
  - Resources: 128Mi-1Gi memory, 100m-1000m CPU
  - PUID/PGID: 1029/100 (matches NFS permissions)
- Created `sabnzbd-config` PVC (10Gi, local-path) for persistent configuration
- Mounted existing `media-downloads` PVC at `/downloads`
- Created Ingress at `sabnzbd.lab.mtgibbs.dev` with Let's Encrypt TLS
- Created `newshosting-credentials` ExternalSecret mapping to 1Password:
  - `username`, `password`, `server`, `ssl-port`
- Fixed hostname whitelist issue in SABnzbd config to allow Ingress access
- Created download folder structure:
  - `/downloads/incomplete` - temporary download location
  - `/downloads/complete/usenet` - completed Usenet downloads
- Created categories in SABnzbd:
  - `tv-sonarr` - for Sonarr requests
  - `radarr` - for Radarr requests

**Files Modified**:
- `clusters/pi-k3s/media/sabnzbd.yaml` - new deployment, service, ingress
- `clusters/pi-k3s/media/config-pvcs.yaml` - added sabnzbd-config PVC
- `clusters/pi-k3s/media/external-secret.yaml` - added newshosting-credentials
- `clusters/pi-k3s/media/kustomization.yaml` - added sabnzbd.yaml resource

**Relevant Commit**:
- `daf7303` - feat: add SABnzbd for Usenet downloads

---

#### 3. NZBGeek Indexer Integration

**What**: Added NZBGeek as the primary indexer in Prowlarr with highest priority

**Why**:
- User purchased 5-year NZBGeek plan for reliable Usenet indexing
- Need high-quality NZB files for SABnzbd to download
- Usenet should be tried before falling back to torrents

**How**:
- Added NZBGeek indexer to Prowlarr with Priority 1 (highest)
- Set existing torrent indexers to Priority 25 (lower)
- Prowlarr auto-synced indexer to Sonarr and Radarr
- Configured SABnzbd as default download client in Sonarr/Radarr
- Tested with "Alien" movie - successfully grabbed from NZBGeek and downloaded via SABnzbd

**Result**:
- Jellyseerr requests now flow: Jellyseerr → Sonarr/Radarr → Prowlarr (tries NZBGeek first) → SABnzbd (Usenet) or qBittorrent (torrent fallback)

---

### Architecture Changes

The media automation stack now has a two-tier download strategy:

```
┌─────────────┐
│ Jellyseerr  │  User requests media
└──────┬──────┘
       │
       ▼
┌─────────────────────┐
│  Sonarr / Radarr    │  Monitors for availability
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│     Prowlarr        │  Searches indexers
│                     │
│  Priority 1:        │  ┌──────────────┐
│  • NZBGeek (Usenet) │─▶│  NZBGeek     │
│                     │  └──────────────┘
│  Priority 25:       │  ┌──────────────┐
│  • 1337x (torrent)  │─▶│  Torrent     │
│  • ThePirateBay     │  │  Indexers    │
│  • YTS, etc.        │  └──────────────┘
└──────┬──────────────┘
       │
       ├─────────────────────────────────────────────────┐
       │                                                 │
       ▼ (Usenet download)                              ▼ (Torrent download)
┌──────────────────┐                              ┌────────────────────┐
│     SABnzbd      │                              │   qBittorrent      │
│                  │                              │                    │
│ • Newshosting    │                              │  ┌──────────────┐  │
│ • Port 563 (SSL) │                              │  │   Gluetun    │  │
│ • Direct connect │                              │  │  (Proton VPN)│  │
│   (no VPN)       │                              │  │              │  │
│                  │                              │  │ • Port fwd   │  │
│ Downloads to:    │                              │  │ • DHT/PeX    │  │
│ /downloads/      │                              │  │ • Firewall   │  │
│ complete/usenet  │                              │  │   disabled   │  │
└────────┬─────────┘                              │  └──────────────┘  │
         │                                        │                    │
         │                                        │ Downloads to:      │
         │                                        │ /downloads/        │
         │                                        │ complete/torrents  │
         │                                        └──────────┬─────────┘
         │                                                   │
         └───────────────────────┬───────────────────────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │   Sonarr / Radarr      │
                    │   Post-processing      │
                    └────────┬───────────────┘
                             │
                             ▼
                    ┌────────────────────────┐
                    │      Jellyfin          │
                    │   /media/movies        │
                    │   /media/tv            │
                    └────────────────────────┘
```

**Key Decision**: Usenet (via NZBGeek + SABnzbd) is now the primary download method, with torrents (via multiple indexers + qBittorrent + Proton VPN) as fallback.

---

### Key Decisions

#### Decision: Use Newshosting as Usenet Provider
**Why**:
- User's existing provider with good retention (4000+ days)
- Reliable SSL connections on port 563
- No additional signup needed

**How**:
- Stored credentials in 1Password `pi-cluster` vault
- Created ExternalSecret to inject into SABnzbd pod
- Configured connection in SABnzbd UI

**Trade-offs**:
- Single provider means no fill server redundancy
- Acceptable for personal use given NZBGeek's quality

---

#### Decision: Disable Gluetun Firewall for qBittorrent
**Why**:
- Gluetun's firewall was blocking UDP tracker traffic
- DHT, PeX, and Local Peer Discovery require UDP
- Some trackers only announce on UDP

**How**:
- Set `FIREWALL=off` in qbittorrent.yaml
- Rely on Kubernetes NetworkPolicies instead (if needed later)

**Trade-offs**:
- Lost automatic firewall kill-switch
- Gained full P2P functionality
- Risk mitigated by VPN connection enforcement

---

#### Decision: SABnzbd Runs Without VPN
**Why**:
- Usenet downloads are encrypted via SSL/TLS
- No P2P exposure (direct connection to Newshosting)
- Simplifies deployment (no Gluetun sidecar needed)

**How**:
- Deployed SABnzbd as standalone deployment
- Configured SSL port 563 in server settings

**Trade-offs**:
- ISP can see Newshosting connection (but not content)
- Faster performance without VPN overhead
- Acceptable risk for encrypted Usenet traffic

---

### Testing & Validation

1. **Proton VPN Port Forwarding**:
   - Verified forwarded port appears in `/tmp/gluetun/forwarded_port`
   - Confirmed auto-update script successfully updates qBittorrent listening port
   - Validated DHT/PeX connections in qBittorrent logs

2. **SABnzbd Connectivity**:
   - Successfully connected to Newshosting SSL server
   - Downloaded test NZB from NZBGeek
   - Verified file extraction and post-processing

3. **End-to-End Media Request**:
   - Searched for "Alien" in Jellyseerr
   - Radarr found release on NZBGeek (priority 1)
   - SABnzbd downloaded via Newshosting
   - File extracted to `/downloads/complete/usenet/radarr/`
   - Radarr imported to Jellyfin library

4. **Ingress & TLS**:
   - Confirmed `sabnzbd.lab.mtgibbs.dev` accessible via HTTPS
   - Let's Encrypt certificate issued successfully
   - Fixed hostname whitelist to allow Ingress host

---

### Configuration Artifacts

#### 1Password Vault Structure
```
pi-cluster/
├── protonvpn-credentials
│   ├── username      → OpenVPN username
│   └── credential    → OpenVPN password
├── newshosting
│   ├── username      → NNTP username
│   ├── password      → NNTP password
│   ├── server        → news.newshosting.com
│   └── ssl-port      → 563
└── qbit.lab.mtgibbs.dev
    ├── username      → qBittorrent Web UI user
    └── password      → qBittorrent Web UI pass
```

#### Directory Structure on media-downloads PVC
```
/downloads/
├── incomplete/           # SABnzbd temp downloads
├── complete/
│   ├── usenet/          # SABnzbd completed downloads
│   │   ├── tv-sonarr/   # Sonarr category
│   │   └── radarr/      # Radarr category
│   └── torrents/        # qBittorrent completed downloads
```

---

### Lessons Learned

1. **VPN Port Forwarding Complexity**:
   - Mullvad's deprecation of port forwarding forced migration
   - Proton VPN's NATPMP implementation works well but required custom script
   - Future consideration: Monitor for VPN provider policy changes

2. **Firewall vs. Functionality Trade-off**:
   - Gluetun's firewall blocked legitimate UDP traffic
   - Sometimes security controls need tuning for functionality
   - Better to rely on VPN enforcement than overly restrictive firewall

3. **Usenet Superiority for Media Automation**:
   - Consistently faster than torrents
   - Better availability for older content
   - No seeder dependency
   - Worth the subscription cost for quality of service

4. **ExternalSecrets Best Practices**:
   - Always use 1Password field paths (`item/field-name`)
   - Map to appropriate Kubernetes secret keys (`username`, `password`)
   - Test secret sync before deploying dependent applications

---

### Next Steps

- [ ] Monitor SABnzbd download performance and completion rates
- [ ] Consider adding a fill server to Newshosting for redundancy
- [ ] Document SABnzbd category configuration in media-services skill
- [ ] Evaluate need for SABnzbd resource limit adjustments under load
- [ ] Test failure scenario: what happens when Usenet download fails (verify torrent fallback)
- [ ] Consider NetworkPolicy for qBittorrent now that Gluetun firewall is disabled

---

### Files Modified This Session

```
modified:   clusters/pi-k3s/media/external-secret.yaml
modified:   clusters/pi-k3s/media/config-pvcs.yaml
modified:   clusters/pi-k3s/media/qbittorrent.yaml
modified:   clusters/pi-k3s/media/kustomization.yaml
new file:   clusters/pi-k3s/media/sabnzbd.yaml
new file:   docs/plans/protonvpn-migration.md
```

### Commit History

```
daf7303 feat: add SABnzbd for Usenet downloads
ebbeffd fix: disable Gluetun firewall to allow tracker UDP traffic
88125b1 fix: read port from file instead of argument
882c466 fix: use wget instead of curl for qBittorrent port update
fbed69a feat: auto-update qBittorrent listening port on VPN port change
d9b2014 fix: use correct 1Password field names (username/credential)
5851dea fix: use correct 1Password field names for protonvpn-credentials
8ca37f9 fix: correct 1Password reference format for protonvpn-credentials
5e78e2f feat: switch from Mullvad to Proton VPN for port forwarding
722df69 docs: add Proton VPN migration plan
```

---

### Summary

This session represented a significant evolution of the media automation stack. The migration from Mullvad to Proton VPN resolved port forwarding limitations, and the integration of SABnzbd with Newshosting established Usenet as the primary download method. The two-tier approach (Usenet first, torrents as fallback) provides both speed and reliability, while the ExternalSecrets integration maintains security best practices by keeping credentials in 1Password. The stack is now production-ready with fast, reliable media acquisition capability.
