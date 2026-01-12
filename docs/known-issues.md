# Known Issues

### Immich High CPU Usage
- **Issue**: Immich causing ~2 CPU cores usage on Pi 5 due to ML job retry loop
- **Cause**: Machine learning disabled but jobs still queued and retrying
- **Impact**: High CPU usage, no functional issues
- **Resolution**: Deferred - ML features not needed, workaround is acceptable

### Dead Pi-hole Blocklists
- **Issue**: Two dead blocklists (IDs 19, 28) in Pi-hole database
- **Cause**: Manually added via web UI (not in GitOps ConfigMap)
- **Impact**: Warning logs, no blocking issues (~900k domains still active)
- **Resolution**: Deferred - not affecting DNS blocking functionality

### NFS UID/GID Mapping
- **Issue**: Files created on NFS volumes have incorrect ownership (uid=0, gid=0 instead of uid=568)
- **Cause**: Synology NFS no_root_squash setting vs application UID expectations
- **Impact**: Minimal - applications can read/write, but file ownership is incorrect
- **Resolution**: Deferred - functional workaround exists, proper fix requires Synology NFS reconfiguration
