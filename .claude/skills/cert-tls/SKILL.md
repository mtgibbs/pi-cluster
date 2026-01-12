---
name: cert-tls
description: Expert knowledge for TLS/SSL operations. Use when configuring certificates, debugging cert-manager, or managing Ingress TLS.
allowed-tools: Bash, Read, Grep, Glob, Edit, Write
---

# TLS & Certificate Operations

## Architecture
- **Issuer**: Let's Encrypt (Production & Staging)
- **Challenge**: DNS-01 via Cloudflare API
- **Domain**: `*.lab.mtgibbs.dev` (Wildcard)

## Configuration

### Components
- **Namespace**: `cert-manager`
- **ClusterIssuers**: `letsencrypt-prod`, `letsencrypt-staging`
- **Secret**: `cloudflare-api-token` (Synced from 1Password)

### Cloudflare Setup
- **Token Permissions**: Zone:DNS:Edit
- **Zone Resources**: Include `mtgibbs.dev`
- **DNS Record**: A record `*.lab` -> `192.168.1.55` (Proxy OFF/Grey Cloud)

### Ingress Annotations
For internal HTTPS services (like Unifi) that need re-encryption:
```yaml
annotations:
  nginx.ingress.kubernetes.io/backend-protocol: "HTTPS"
  nginx.ingress.kubernetes.io/proxy-ssl-verify: "false"
```

## Troubleshooting

### Debug Flow
1. **Check Certificate Resource**:
   ```bash
   kubectl get certificate -n <namespace>
   kubectl describe certificate <name> -n <namespace>
   ```
   Look for "Ready" status or error messages.

2. **Check Challenge**:
   ```bash
   kubectl get challengerequest -A
   ```

3. **Check Cert-Manager Logs**:
   ```bash
   kubectl logs -n cert-manager -l app=cert-manager
   ```

### Common Issues
- **"403 Forbidden"**: Cloudflare API token has wrong permissions.
- **"Waiting for DNS propagation"**: Normal, but if stuck >10m, check Cloudflare logs.
