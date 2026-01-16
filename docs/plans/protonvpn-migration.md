# Plan: Migrate from Mullvad to Proton VPN

## Why
Mullvad removed port forwarding in 2023. Without it, qBittorrent can only make outbound connections, severely limiting peer discovery and download speeds for torrents with few seeders.

Proton VPN supports port forwarding via NAT-PMP, which Gluetun has built-in support for.

## Prerequisites
- Proton VPN account with **Plus plan or higher** (port forwarding requires paid tier)
- OpenVPN credentials from Proton (username/password)

## Steps

### 1. Get Proton VPN Credentials
1. Log into https://account.protonvpn.com
2. Go to **Downloads** → **OpenVPN configuration files**
3. Note your **OpenVPN/IKEv2 username** and **password** (these are different from your login credentials)

### 2. Save Credentials to 1Password
Create a new item in the `pi-cluster` vault:
- **Name**: `protonvpn-credentials`
- **Fields**:
  - `OPENVPN_USER`: Your OpenVPN username
  - `OPENVPN_PASSWORD`: Your OpenVPN password

### 3. Update ExternalSecret
Edit `/clusters/pi-k3s/media/external-secret.yaml`:

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: vpn-credentials
  namespace: media
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword
  target:
    name: protonvpn-credentials
    creationPolicy: Owner
  data:
    - secretKey: OPENVPN_USER
      remoteRef:
        key: protonvpn-credentials
        property: OPENVPN_USER
    - secretKey: OPENVPN_PASSWORD
      remoteRef:
        key: protonvpn-credentials
        property: OPENVPN_PASSWORD
```

### 4. Update qBittorrent Deployment
Edit `/clusters/pi-k3s/media/qbittorrent.yaml` - replace Gluetun container config:

```yaml
- name: gluetun
  image: qmcgaw/gluetun:latest
  securityContext:
    capabilities:
      add:
        - NET_ADMIN
  env:
    - name: VPN_SERVICE_PROVIDER
      value: protonvpn
    - name: VPN_TYPE
      value: openvpn
    - name: OPENVPN_USER
      valueFrom:
        secretKeyRef:
          name: protonvpn-credentials
          key: OPENVPN_USER
    - name: OPENVPN_PASSWORD
      valueFrom:
        secretKeyRef:
          name: protonvpn-credentials
          key: OPENVPN_PASSWORD
    - name: SERVER_COUNTRIES
      value: "United States"
    - name: FREE_ONLY
      value: "off"
    # Enable port forwarding via NAT-PMP
    - name: VPN_PORT_FORWARDING
      value: "on"
    - name: VPN_PORT_FORWARDING_PROVIDER
      value: protonvpn
  ports:
    - containerPort: 8080
      name: qbit-web
  resources:
    requests:
      memory: "64Mi"
      cpu: "50m"
    limits:
      memory: "256Mi"
      cpu: "200m"
```

### 5. Configure qBittorrent to Use Forwarded Port
Gluetun will automatically get a forwarded port from Proton. You can either:

**Option A: Manual** - Check Gluetun logs for the port, set it in qBittorrent settings

**Option B: Automatic** - Gluetun can update qBittorrent's listening port automatically:
```yaml
env:
  # Add to Gluetun container
  - name: UPDATER_PERIOD
    value: "5m"
  - name: QBITTORRENT_SERVER
    value: "127.0.0.1"
  - name: QBITTORRENT_PORT
    value: "8080"
```

### 6. Deploy and Test
```bash
# Commit and push
git add -A && git commit -m "feat: switch from Mullvad to Proton VPN for port forwarding" && git push

# Reconcile
flux reconcile source git flux-system
flux reconcile kustomization media

# Check VPN status
kubectl logs -n media deployment/qbittorrent -c gluetun --tail=20

# Look for: "Port forwarded: XXXXX"
```

### 7. Verify Port Forwarding
```bash
# Check the forwarded port
kubectl exec -n media deployment/qbittorrent -c gluetun -- wget -qO- http://127.0.0.1:8000/v1/openvpn/portforwarded

# Test connectivity (from outside)
# The port should be reachable from the internet
```

## Rollback
If Proton VPN doesn't work, revert to Mullvad:
```bash
git revert HEAD
git push
flux reconcile source git flux-system
flux reconcile kustomization media
```

## Cleanup (After Successful Migration)
- Remove `mullvad-credentials` from 1Password (optional, keep as backup)
- Update ARCHITECTURE.md to reflect Proton VPN usage

## References
- [Gluetun Proton VPN Setup](https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/protonvpn.md)
- [Proton VPN Port Forwarding](https://protonvpn.com/support/port-forwarding/)
- [Gluetun Port Forwarding](https://github.com/qdm12/gluetun-wiki/blob/main/setup/options/port-forwarding.md)

## Estimated Time
~30 minutes including testing
