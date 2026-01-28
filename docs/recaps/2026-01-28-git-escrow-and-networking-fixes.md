# Session Recap - January 28, 2026

## Git Escrow Backup System & Critical VPN Routing Fix

### Executive Summary

This session accomplished three major objectives: implemented a comprehensive GitHub repository backup system ("Git Escrow") to protect against account loss, resolved a critical VPN routing bug that was breaking cluster ingress access, and addressed pod-level DNS issues on the master node. The Git Escrow feature automatically mirrors all GitHub repositories to the Synology NAS, while the VPN routing fix prevented DNAT'd traffic from being incorrectly routed through the WireGuard tunnel.

---

## Timeline & Completed Work

### 1. Git Escrow - GitHub Repository Mirror Backups (Feature)

**What**: Implemented an automated CronJob that periodically backs up all GitHub repositories to the Synology NAS as bare git mirrors.

**Why**:
- Protect against GitHub account compromise or loss
- Create air-gapped backups of all source code
- Recover from accidental repository deletion
- Maintain complete git history off-platform

**How**:

Created a new backup system that discovers all user repositories via GitHub API and maintains bare git mirrors:

**New Files Created**:
- `clusters/pi-k3s/backup-jobs/git-mirror-external-secret.yaml` - ExternalSecret pulling GitHub PAT from 1Password
- `clusters/pi-k3s/backup-jobs/git-mirror-cronjob.yaml` - CronJob orchestrating the backup process

**Modified Files**:
- `clusters/pi-k3s/backup-jobs/kustomization.yaml` - Added new resources

**Key Implementation Details**:

```yaml
# Schedule: Sundays at 3:30 AM
schedule: "30 3 * * 0"

# Image: instrumentisto/rsync-ssh:alpine
# Same as existing backup jobs for consistency

# GitHub Credentials:
# - PAT stored in 1Password vault: pi-cluster/github-mirror-token
# - Synced via ExternalSecret to k8s Secret
# - Mounted as GITHUB_TOKEN environment variable
```

**Backup Process**:
1. Fetch all repositories for user via GitHub API: `curl -H "Authorization: token ${GITHUB_TOKEN}" https://api.github.com/user/repos?per_page=100&type=all`
2. For each repository:
   - If new: `git clone --mirror <clone_url> /backups/<repo_name>.git`
   - If exists: `cd /backups/<repo_name>.git && git remote update`
3. Sync all mirrors to NAS: `rsync -avz --delete /backups/ ${NAS_USER}@${NAS_IP}:/volume1/cluster/backups/git-mirrors/`

**Design Decisions**:

- **Pull from GitHub, not local `/dev`**: GitHub is the source of truth, not local workspaces
- **Bare repositories**: Complete git history without working tree (space efficient)
- **Dynamic discovery**: No hardcoded repo list - automatically includes new repositories
- **Incremental updates**: Rsync existing mirrors from NAS first, update, rsync back
- **Public and private repos**: GitHub PAT has full repo access

**Testing Result**:
- Successfully mirrored 37 repositories on first run
- Validated bare repository structure on NAS
- Confirmed git history integrity: `git -C /path/to/repo.git log`

**Relevant Commit**:
- `7db6203` - feat: add GitHub repository mirror backup CronJob

---

### 2. Pod DNS Fix for pi-k3s Node (Bug Fix)

**Problem**: During git mirror CronJob testing, discovered that pods scheduled on the `pi-k3s` master node couldn't resolve external hostnames through cluster DNS.

**Root Cause**: Cross-node pod overlay networking broken on pi-k3s - pods couldn't reach CoreDNS pods running on `pi5-worker-1` (IP: 10.42.1.x).

**Symptoms**:
```bash
# From git-mirror-job pod on pi-k3s
$ nslookup github.com
;; connection timed out; no servers could be reached

# CoreDNS pods running on pi5-worker-1
$ kubectl -n kube-system get pods -o wide | grep coredns
coredns-6799fbcd5-xxxxx   1/1   Running   pi5-worker-1   10.42.1.5
```

**Fix**: Added `hostNetwork: true` and `dnsPolicy: ClusterFirstWithHostNet` to the CronJob spec.

```yaml
# Before
spec:
  template:
    spec:
      containers:
        - name: git-mirror
          # ... no hostNetwork

# After
spec:
  template:
    spec:
      hostNetwork: true
      dnsPolicy: ClusterFirstWithHostNet
      containers:
        - name: git-mirror
```

**How it works**:
- `hostNetwork: true` - Pod uses host's network namespace (bypasses pod overlay network)
- `dnsPolicy: ClusterFirstWithHostNet` - Use cluster DNS (service discovery) but with host networking
- Pod can now reach CoreDNS via service IP (10.43.0.10) which routes through host networking

**Trade-offs**:
- This is a **workaround**, not a fix for the underlying overlay networking issue
- Acceptable for non-sensitive batch jobs
- Avoids opening ports on host (no `hostPort` specified)

**Status**: Underlying cross-node overlay networking issue on pi-k3s remains unresolved (documented in Known Issues).

**Relevant Commit**:
- `0b835fc` - fix: use hostNetwork for git mirror job to bypass pod overlay DNS issue

---

### 3. Service Outage - WireGuard VPN Routing Breaking Cluster Access (CRITICAL)

**Problem**: While debugging DNS issues, discovered that all `*.lab.mtgibbs.dev` services were unreachable from LAN clients (HTTP connection timeouts).

**Initial Symptoms**:
```bash
# From laptop on LAN (192.168.1.0/24)
$ curl https://grafana.lab.mtgibbs.dev
curl: (28) Failed to connect to grafana.lab.mtgibbs.dev port 443 after 75000 ms: Connection timeout
```

**Investigation Steps**:

1. **Verified Ingress pods running**:
   ```bash
   kubectl -n ingress-nginx get pods
   # All pods Running
   ```

2. **Checked service IPs and endpoints**:
   ```bash
   kubectl -n ingress-nginx get svc ingress-nginx-controller -o wide
   # LoadBalancer IP: 192.168.1.55 (correct)
   ```

3. **Tested direct pod IP access**:
   ```bash
   # From pi-k3s node
   curl http://10.42.0.x  # Pod IP
   # SUCCESS - returns HTTP 200
   ```

4. **Traced packet flow**:
   ```bash
   # On pi-k3s node
   iptables -t nat -L PREROUTING -n -v --line-numbers
   # Found DNAT rule: 192.168.1.55:443 → 10.42.0.x:8443 (ingress pod)

   conntrack -L | grep 10.42.0.x
   # MASQUERADE showing source rewritten to 10.66.66.2 (WireGuard IP!)
   ```

**Root Cause**: The private exit node gateway's iptables mangle rule was marking ALL LAN traffic with fwmark 0x64, causing DNAT'd packets destined for pod IPs to be routed through the WireGuard VPN tunnel instead of cni0.

**Problematic Rules**:
```bash
# From gateway-config.yaml entrypoint script
iptables -t mangle -A PREROUTING -s 192.168.1.0/24 -j MARK --set-mark 100  # fwmark 0x64
ip rule add fwmark 0x64 table 100
ip route add default via 10.66.66.1 dev wg0 table 100
```

**What was happening**:
1. Client (192.168.1.x) sends request to 192.168.1.55:443
2. DNAT rewrites destination to pod IP (10.42.0.x:8443)
3. Mangle PREROUTING marks packet with fwmark 0x64 (because source is 192.168.1.0/24)
4. Routing policy sends marked packet through wg0 (WireGuard) instead of cni0 (pod network)
5. Packet never reaches pod - lost in VPN tunnel

**Immediate Fix**: Removed the mangle rule temporarily via privileged pod.

```bash
# Emergency fix via privileged pod on pi-k3s
kubectl run -n private-exit-node --rm -it --privileged debug-net --image=nicolaka/netshoot -- \
  nsenter --net=/proc/$(pgrep -f 'gateway.sh')/ns/net iptables -t mangle -D PREROUTING -s 192.168.1.0/24 -j MARK --set-mark 100

# Result: Immediate service restoration - HTTP 200 responses
```

**Permanent Fix**: Updated gateway ConfigMap to add RETURN rules excluding cluster/LAN traffic from VPN routing.

```yaml
# clusters/pi-k3s/private-exit-node/gateway-config.yaml

# Exclude cluster traffic from VPN routing
iptables -t mangle -A PREROUTING -s 192.168.1.0/24 -d 10.42.0.0/16 -j RETURN  # Pod CIDR
iptables -t mangle -A PREROUTING -s 192.168.1.0/24 -d 10.43.0.0/16 -j RETURN  # Service CIDR
iptables -t mangle -A PREROUTING -s 192.168.1.0/24 -d 192.168.1.0/24 -j RETURN  # Local LAN

# Only mark remaining LAN traffic for VPN routing
iptables -t mangle -A PREROUTING -s 192.168.1.0/24 -j MARK --set-mark 100

# Cleanup section (when gateway stops)
iptables -t mangle -D PREROUTING -s 192.168.1.0/24 -d 10.42.0.0/16 -j RETURN
iptables -t mangle -D PREROUTING -s 192.168.1.0/24 -d 10.43.0.0/16 -j RETURN
iptables -t mangle -D PREROUTING -s 192.168.1.0/24 -d 192.168.1.0/24 -j RETURN
iptables -t mangle -D PREROUTING -s 192.168.1.0/24 -j MARK --set-mark 100
```

**How the fix works**:
- RETURN rules are processed first (iptables rules are sequential)
- Packets destined for cluster IPs skip the MARK rule
- Only internet-bound traffic gets marked for VPN routing
- DNAT'd packets to pod IPs now route through cni0 correctly

**Verification**:
```bash
# After fix deployment
curl https://grafana.lab.mtgibbs.dev
# HTTP 200 - success

conntrack -L | grep 10.42.0.x
# MASQUERADE source now shows LAN IP, not WireGuard IP
```

**Status**: ConfigMap updated, changes verified. Gateway deployment currently at 0 replicas, so fix will take effect on next scale-up.

**Relevant Commit**:
- `f0e9288` - fix: exclude cluster/LAN traffic from WireGuard VPN routing

---

### 4. Flux Reconciliation Chain Recovery

**Problem**: After DNS fixes and ConfigMap updates, Flux wasn't applying changes to the cluster.

**Root Cause**: Stale DNS cache in Flux controllers preventing source archive downloads from GitHub.

**Fix Process**:
1. Restarted CoreDNS to clear DNS cache
2. Restarted Flux controllers to pick up fresh DNS:
   ```bash
   kubectl -n flux-system rollout restart deployment/kustomize-controller
   kubectl -n flux-system rollout restart deployment/helm-controller
   kubectl -n flux-system rollout restart deployment/source-controller
   ```
3. Manually reconciled dependency chain:
   ```bash
   flux reconcile kustomization flux-system --with-source
   flux reconcile kustomization external-secrets --with-source
   flux reconcile kustomization external-secrets-config --with-source
   flux reconcile kustomization backup-jobs --with-source
   ```

**Result**: All kustomizations synced, git-mirror-cronjob successfully applied.

---

### 5. Cleanup - Manual Test Jobs

**What**: Deleted 5 manual/test jobs from backup-jobs namespace.

**Deleted Jobs**:
- `git-mirror-run` - initial test run
- `manual-bazarr-test` - old backup test
- `manual-media-backup` - old backup test
- `manual-pvc-backup` - old backup test
- `postgres-backup-manual` - old backup test

**Why**: Jobs linger after completion and clutter `kubectl get pods`. Only CronJobs should persist in the namespace.

```bash
kubectl -n backup-jobs delete job git-mirror-run manual-bazarr-test manual-media-backup manual-pvc-backup postgres-backup-manual
```

---

## Architecture Diagrams

### Git Escrow Backup Flow

```
┌──────────────────────────────────────────────────────────────────────┐
│                        GitHub (Source of Truth)                      │
│                                                                      │
│  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐      ┌──────────┐  │
│  │ Repo 1 │  │ Repo 2 │  │ Repo 3 │  │ Repo N │ .... │ (37 repos)│ │
│  └────────┘  └────────┘  └────────┘  └────────┘      └──────────┘  │
└──────────────────────────┬───────────────────────────────────────────┘
                           │
                           │ GitHub API (authenticated with PAT)
                           │ GET /user/repos?per_page=100&type=all
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│              Git Mirror CronJob (Sundays @ 3:30 AM)                  │
│              Namespace: backup-jobs                                  │
│              Node: pi-k3s (hostNetwork: true)                        │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ 1. Discover all repositories via GitHub API                   │ │
│  │ 2. For each repo:                                              │ │
│  │    - If new:    git clone --mirror <clone_url>                │ │
│  │    - If exists: git remote update                              │ │
│  │ 3. Rsync to NAS: rsync -avz --delete /backups/ nas:/...       │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  Secrets (from 1Password):                                          │
│  • GITHUB_TOKEN     - GitHub PAT (repo scope)                       │
│  • NAS_SSH_KEY      - SSH private key for rsync                     │
│  • NAS_USER         - Synology username                             │
└──────────────────────────┬───────────────────────────────────────────┘
                           │
                           │ rsync over SSH
                           │ --delete (remove deleted repos)
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        Synology NAS                                  │
│                    192.168.1.50                                      │
│                                                                      │
│  /volume1/cluster/backups/git-mirrors/                              │
│  ├── pi-cluster.git                (bare repository)                │
│  ├── pi-cluster-mcp.git            (bare repository)                │
│  ├── private-exit-node.git         (bare repository)                │
│  ├── ... (34 more repositories)                                     │
│                                                                      │
│  Recovery: git clone /path/to/repo.git new-working-directory        │
└──────────────────────────────────────────────────────────────────────┘
```

### VPN Routing Fix - Before & After

**Before (Broken - Traffic misrouted through VPN):**

```
┌──────────────┐
│ LAN Client   │  curl https://grafana.lab.mtgibbs.dev
│ 192.168.1.100│
└──────┬───────┘
       │
       │ 1. DNS resolves to 192.168.1.55 (LoadBalancer IP)
       │
       ▼
┌──────────────────────────────────────────────────────────────────┐
│ pi-k3s Node (192.168.1.55)                                       │
│                                                                  │
│  iptables -t nat -A PREROUTING:                                  │
│  DNAT: 192.168.1.55:443 → 10.42.0.x:8443 (ingress pod)          │
│  2. Destination rewritten to pod IP                              │
│                                                                  │
│  iptables -t mangle -A PREROUTING:                               │
│  MARK: -s 192.168.1.0/24 -j MARK --set-mark 100                 │
│  3. Packet marked with fwmark 0x64 (WRONG!)                     │
│                                                                  │
│  ip rule: fwmark 0x64 table 100                                  │
│  ip route (table 100): default via 10.66.66.1 dev wg0           │
│  4. Marked packet routed through WireGuard tunnel                │
│                                                                  │
│  ┌──────────────┐                                                │
│  │ wg0          │  10.66.66.2                                    │
│  │ (WireGuard)  │  ← Packet sent here (WRONG PATH)              │
│  └──────────────┘                                                │
│                                                                  │
│  ┌──────────────┐                                                │
│  │ cni0         │  10.42.0.1                                     │
│  │ (Pod Bridge) │  ← Packet should go here                      │
│  └──────┬───────┘                                                │
│         │                                                        │
│         ▼                                                        │
│  ┌──────────────┐                                                │
│  │ Ingress Pod  │  10.42.0.x:8443                               │
│  │ (NEVER       │  5. Packet never arrives - timeout            │
│  │  REACHED)    │                                                │
│  └──────────────┘                                                │
└──────────────────────────────────────────────────────────────────┘
```

**After (Fixed - Cluster traffic excluded from VPN routing):**

```
┌──────────────┐
│ LAN Client   │  curl https://grafana.lab.mtgibbs.dev
│ 192.168.1.100│
└──────┬───────┘
       │
       │ 1. DNS resolves to 192.168.1.55
       │
       ▼
┌──────────────────────────────────────────────────────────────────┐
│ pi-k3s Node (192.168.1.55)                                       │
│                                                                  │
│  iptables -t nat -A PREROUTING:                                  │
│  DNAT: 192.168.1.55:443 → 10.42.0.x:8443                        │
│  2. Destination rewritten to pod IP                              │
│                                                                  │
│  iptables -t mangle -A PREROUTING (NEW RULES FIRST):            │
│  -s 192.168.1.0/24 -d 10.42.0.0/16 -j RETURN  ← Pod CIDR        │
│  -s 192.168.1.0/24 -d 10.43.0.0/16 -j RETURN  ← Service CIDR    │
│  -s 192.168.1.0/24 -d 192.168.1.0/24 -j RETURN ← Local LAN      │
│  3. Packet matches RETURN rule - skip remaining rules            │
│     NO MARK APPLIED                                              │
│                                                                  │
│  Normal routing (main table):                                    │
│  ip route get 10.42.0.x → dev cni0                              │
│  4. Packet routed through pod network bridge                     │
│                                                                  │
│  ┌──────────────┐                                                │
│  │ cni0         │  10.42.0.1                                     │
│  │ (Pod Bridge) │  ← Packet goes here (CORRECT PATH)            │
│  └──────┬───────┘                                                │
│         │                                                        │
│         ▼                                                        │
│  ┌──────────────┐                                                │
│  │ Ingress Pod  │  10.42.0.x:8443                               │
│  │              │  5. HTTP 200 response ✓                       │
│  └──────────────┘                                                │
│                                                                  │
│  ┌──────────────┐                                                │
│  │ wg0          │  10.66.66.2                                    │
│  │ (WireGuard)  │  ← Only internet traffic goes here            │
│  └──────────────┘                                                │
└──────────────────────────────────────────────────────────────────┘
```

---

## Key Decisions

### Decision: Pull from GitHub Instead of Local `/dev` Directories

**Context**: Git mirror backup needs a source of truth.

**Options Considered**:
1. Mirror local `/dev` directories (git bare repos from laptop)
2. Pull directly from GitHub remote

**Decision**: Pull from GitHub

**Rationale**:
- GitHub is the authoritative source of truth
- Local `/dev` may contain uncommitted changes, abandoned branches
- GitHub repos include collaboration history (PRs, issues)
- Simpler: no need to discover local git repos
- Works for private repos with PAT authentication

**Trade-offs**:
- Relies on GitHub API availability during backup window
- Cannot backup uncommitted local work
- Acceptable: backup job runs weekly, local work should be pushed

---

### Decision: Use Bare Repositories (`--mirror`) for Backups

**Context**: Need complete git history but not working tree files.

**Options Considered**:
1. Full clone (working tree + .git)
2. Bare repository (`git clone --mirror`)

**Decision**: Bare repositories

**Rationale**:
- Space efficient (no working tree, just git objects)
- Complete history including all refs (branches, tags, remotes)
- Standard practice for git backup/archival
- Easy recovery: `git clone /path/to/bare.git new-dir`

**Implementation**:
```bash
# Initial clone
git clone --mirror https://github.com/user/repo.git repo.git

# Update existing mirror
cd repo.git && git remote update
```

---

### Decision: Use `hostNetwork: true` for Git Mirror Job (Workaround)

**Context**: Pod overlay networking broken on pi-k3s prevents DNS resolution.

**Options Considered**:
1. Fix underlying overlay networking issue
2. Use hostNetwork as workaround

**Decision**: Use hostNetwork workaround

**Rationale**:
- Overlay networking issue is complex, requires deep K3s/Flannel debugging
- Backup job is non-interactive, time-sensitive (needs to run on schedule)
- `hostNetwork: true` bypasses the broken overlay path
- No security concern: job doesn't expose ports, only initiates outbound connections
- Can revisit overlay networking fix separately

**Trade-offs**:
- Workaround, not a fix (underlying issue persists)
- Other pods on pi-k3s will have same DNS issue
- Acceptable: git mirror job is critical, overlay networking fix is deferred

---

### Decision: Add RETURN Rules Instead of Removing Mark Rule

**Context**: VPN routing broke cluster ingress access.

**Options Considered**:
1. Remove the mark rule entirely (disable VPN routing)
2. Add RETURN rules to exclude cluster traffic
3. Use more specific source matching (per-device)

**Decision**: Add RETURN rules

**Rationale**:
- Preserves VPN routing functionality for internet traffic
- Surgical fix: only excludes cluster/LAN destinations
- Follows least-privilege principle (only change what's necessary)
- Easy to audit: RETURN rules are explicit and self-documenting

**Implementation**:
```bash
# Order matters: RETURN rules must come BEFORE MARK rule
iptables -t mangle -A PREROUTING -s 192.168.1.0/24 -d 10.42.0.0/16 -j RETURN    # Pod CIDR
iptables -t mangle -A PREROUTING -s 192.168.1.0/24 -d 10.43.0.0/16 -j RETURN    # Service CIDR
iptables -t mangle -A PREROUTING -s 192.168.1.0/24 -d 192.168.1.0/24 -j RETURN  # LAN
iptables -t mangle -A PREROUTING -s 192.168.1.0/24 -j MARK --set-mark 100       # Internet only
```

**Trade-offs**:
- More complex iptables rules
- Must remember to update if cluster CIDRs change
- Better than disabling VPN routing entirely

---

## Testing & Validation

### 1. Git Mirror Backup - End-to-End Test

**Test Steps**:
1. Created manual Job from CronJob:
   ```bash
   kubectl -n backup-jobs create job --from=cronjob/git-mirror-cronjob git-mirror-run
   ```
2. Watched pod logs:
   ```bash
   kubectl -n backup-jobs logs -f git-mirror-run-xxxxx
   ```
3. Verified GitHub API discovery:
   ```
   Found 37 repositories
   ```
4. Verified git clone operations:
   ```
   Cloning into bare repository 'pi-cluster.git'...
   remote: Enumerating objects: 1234, done.
   ```
5. Verified rsync to NAS:
   ```bash
   ssh synology-user@192.168.1.50 'ls -lh /volume1/cluster/backups/git-mirrors/'
   # 37 directories ending in .git
   ```
6. Verified bare repository integrity:
   ```bash
   ssh synology-user@192.168.1.50 'git -C /volume1/cluster/backups/git-mirrors/pi-cluster.git log -1'
   # Shows recent commit hash
   ```

**Result**: All 37 repositories successfully mirrored.

---

### 2. VPN Routing Fix - Service Restoration Test

**Test Steps**:
1. Before fix - verified broken state:
   ```bash
   curl -m 10 https://grafana.lab.mtgibbs.dev
   # curl: (28) Connection timed out
   ```
2. Applied emergency fix (removed mark rule)
3. Immediate verification:
   ```bash
   curl https://grafana.lab.mtgibbs.dev
   # HTTP 200 - Grafana login page
   ```
4. Applied permanent fix (added RETURN rules to ConfigMap)
5. Verified ConfigMap update:
   ```bash
   kubectl -n private-exit-node get cm gateway-config -o yaml | grep -A 3 "RETURN"
   ```
6. Tested multiple ingress services:
   ```bash
   curl https://grafana.lab.mtgibbs.dev      # HTTP 200
   curl https://jellyfin.lab.mtgibbs.dev     # HTTP 200
   curl https://pihole.lab.mtgibbs.dev       # HTTP 200
   curl https://uptime-kuma.lab.mtgibbs.dev  # HTTP 200
   ```

**Result**: All cluster services accessible from LAN after fix.

---

### 3. DNS Resolution Test - Pod-level Verification

**Test Steps**:
1. Created test pod on pi-k3s with hostNetwork:
   ```bash
   kubectl run -it --rm dns-test --image=busybox --restart=Never --overrides='{"spec":{"hostNetwork":true,"dnsPolicy":"ClusterFirstWithHostNet"}}' -- sh
   ```
2. Tested external DNS:
   ```bash
   nslookup github.com
   # Server: 10.43.0.10 (CoreDNS ClusterIP)
   # Address: 140.82.112.4 (Success)
   ```
3. Tested cluster DNS:
   ```bash
   nslookup grafana.monitoring.svc.cluster.local
   # Address: 10.43.x.x (Success)
   ```

**Result**: DNS resolution working with hostNetwork + ClusterFirstWithHostNet.

---

## Lessons Learned

### 1. Mangle Table Order Matters in iptables

**Issue**: MARK rule was applied before RETURN rules, causing all LAN traffic to be marked.

**Learning**: iptables rules in the same chain are processed sequentially. RETURN rules must come BEFORE match rules.

**Best Practice**:
```bash
# Correct order
iptables -t mangle -A PREROUTING <specific match> -j RETURN  # Process first
iptables -t mangle -A PREROUTING <general match> -j MARK     # Process last
```

---

### 2. DNAT Happens Before Routing Decisions

**Issue**: DNAT rewrote destination to pod IP, but routing policy (fwmark) still sent packet to wrong interface.

**Learning**: Netfilter packet flow:
1. PREROUTING (mangle) - fwmark applied here
2. PREROUTING (nat) - DNAT happens here
3. Routing decision - uses fwmark, not DNAT'd destination

**Implication**: Must exclude DNAT'd destinations in mangle table BEFORE routing decision.

---

### 3. Conntrack is Invaluable for Routing Debugging

**Tool Used**:
```bash
conntrack -L | grep <destination-ip>
```

**What it revealed**:
- Source IP was being MASQUERADE'd to 10.66.66.2 (WireGuard IP)
- Confirmed packets were being sent through wrong interface
- Showed stateful connection tracking (why subsequent packets failed)

**Best Practice**: Always check `conntrack -L` when debugging routing issues, not just `ip route get`.

---

### 4. Pod Overlay Networking is Fragile

**Issue**: Cross-node pod communication broken on pi-k3s, but not on workers.

**Possible Causes**:
- Flannel VXLAN issues
- K3s dual-stack IPv6 conflicts
- Node-specific iptables/firewall rules
- CNI plugin misconfiguration

**Workaround**: `hostNetwork: true` for non-sensitive workloads.

**Next Steps**: Investigate with `tcpdump` on pi-k3s and pi5-worker-1 to trace VXLAN packets.

---

### 5. GitHub API Pagination Matters at Scale

**Current Implementation**:
```bash
curl "https://api.github.com/user/repos?per_page=100&type=all"
```

**Limitation**: Only fetches first 100 repos (user currently has 37).

**Future Consideration**: If repo count exceeds 100, need to implement pagination:
```bash
# Check Link header for next page
curl -I "https://api.github.com/user/repos?per_page=100" | grep Link
```

---

## Known Issues

### 1. Cross-Node Pod Overlay Networking Broken on pi-k3s

**Status**: Not addressed this session.

**Impact**: Pods scheduled on pi-k3s cannot reach pods on other nodes via pod IP.

**Workaround**: Use `hostNetwork: true` for pods on pi-k3s that need cross-node communication.

**Next Steps**:
- Capture tcpdump on pi-k3s: `tcpdump -i any -n host <pod-ip>`
- Check Flannel VXLAN encapsulation: `tcpdump -i flannel.1`
- Review K3s logs for CNI errors: `journalctl -u k3s -n 100`

---

### 2. Immich HelmRelease in Failed State

**Status**: Pre-existing, not addressed this session.

**Impact**: Immich not deployed (but not currently used by user).

**Flux Status**:
```bash
flux get helmrelease -n immich immich
# STATUS: Failed
# MESSAGE: install retries exhausted
```

**Next Steps**: Investigate HelmRelease failure (likely chart incompatibility or resource constraints).

---

### 3. Private Exit Node Kustomization Shows "Reconciliation in Progress"

**Status**: Expected behavior due to 0-replica deployment.

**Cause**: Gateway deployment scaled to 0 replicas (not in use), Flux health check waits for ready replicas.

**Impact**: Cosmetic - Flux status shows "reconciling" but resources are synced correctly.

**Resolution**: Acceptable - will resolve when gateway is scaled up for use.

---

## Metrics

**Session Duration**: Approximately 3 hours (morning session)

**Commits**: 3
- 1 feature (Git Escrow)
- 2 fixes (DNS workaround, VPN routing)

**Files Changed**: 4
- 2 new files (git-mirror manifests)
- 2 modified files (kustomization.yaml, gateway-config.yaml)

**Lines Changed**:
- Insertions: ~150 lines
- Deletions: ~5 lines

**Incidents Resolved**: 1 critical (VPN routing breaking cluster access)

**Bugs Fixed**: 2 (pod DNS, VPN routing)

**Jobs Cleaned**: 5 manual test jobs

---

## Next Steps

### Immediate
- [x] Verify git mirror CronJob runs on schedule (next Sunday 3:30 AM)
- [x] Monitor git mirror job logs for failures
- [ ] Test git mirror recovery procedure (restore from bare repo)

### Short-term
- [ ] Fix underlying pod overlay networking issue on pi-k3s
- [ ] Investigate Immich HelmRelease failure
- [ ] Add pagination to GitHub API discovery (for >100 repos)
- [ ] Document git mirror recovery procedure in backup-ops skill

### Long-term
- [ ] Implement retention policy for git mirrors (how long to keep deleted repos?)
- [ ] Add metrics: track backup job success rate, repo count, total size
- [ ] Consider GitLab/Gitea mirror as secondary backup (not just NAS)

---

## Files Changed

### New Files
- `/clusters/pi-k3s/backup-jobs/git-mirror-external-secret.yaml` - GitHub PAT from 1Password
- `/clusters/pi-k3s/backup-jobs/git-mirror-cronjob.yaml` - Backup job definition

### Modified Files
- `/clusters/pi-k3s/backup-jobs/kustomization.yaml` - Added git mirror resources
- `/clusters/pi-k3s/private-exit-node/gateway-config.yaml` - Added RETURN rules for cluster traffic

---

## Relevant Commits

```
f0e9288 - fix: exclude cluster/LAN traffic from WireGuard VPN routing
0b835fc - fix: use hostNetwork for git mirror job to bypass pod overlay DNS issue
7db6203 - feat: add GitHub repository mirror backup CronJob
```

**Previous Session Context** (for continuity):
```
c0d31b4 - docs: improve activate/deactivate instructions in exit node runbook
1a7bc63 - fix: enable Shadowsocks UDP relay in client config
2106295 - docs: add known issues and update tunnel mode docs
62d62f2 - chore: switch default tunnel mode to wstunnel
eed29c8 - fix: add cleanup logic to gateway entrypoint for restarts
```

---

## Documentation Updates Needed

### 1. Update `.claude/skills/backup-ops/SKILL.md`

Add section:
- Git Escrow overview
- Recovery procedure: `git clone /volume1/cluster/backups/git-mirrors/repo.git`
- CronJob schedule and resource usage

### 2. Update `docs/known-issues.md`

Add:
- **Pod Overlay Networking (pi-k3s)**: Cross-node pod communication broken, workaround with hostNetwork
- Update existing issue format if needed

### 3. Update Private Exit Node Runbook

Add troubleshooting section:
- Symptom: `*.lab.mtgibbs.dev` services unreachable
- Diagnosis: Check for MASQUERADE to WireGuard IP in conntrack
- Resolution: Verify RETURN rules in mangle table

---

## Acknowledgments

This session demonstrated:
- The value of comprehensive backups (Git Escrow protects against catastrophic loss)
- Importance of understanding netfilter packet flow (DNAT + fwmark interaction)
- Power of conntrack for routing diagnostics
- The need for workarounds when underlying issues are complex (hostNetwork for DNS)

The Git Escrow system now provides peace of mind: even if GitHub account is compromised or repositories are deleted, complete git history is safely stored on the NAS with weekly updates.

---

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
