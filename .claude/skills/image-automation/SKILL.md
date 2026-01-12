---
name: image-automation
description: Expert knowledge for Flux Image Automation. Use when configuring auto-deploys, debugging image scanners, or updating GitHub credentials.
allowed-tools: Bash, Read, Grep, Glob, Edit, Write
---

# Flux Image Automation

## Purpose
Automatically update deployment manifests in git when new images are pushed to GHCR (e.g., `mtgibbs.xyz` personal site).

## Architecture
1. **ImageRepository**: Scans registry (every 5m).
2. **ImagePolicy**: Selects newest tag based on timestamp (`^[0-9]{14}$`).
3. **ImageUpdateAutomation**: Commits change to git and pushes.

## Configuration

### GitHub Token (PAT)
Flux needs **write access** to the repo. The default deploy key is often read-only.
- **Token**: Fine-grained PAT
- **Permissions**: Contents (Read/Write), Administration (Read/Write)
- **Secret**: `flux-github-pat` (Synced from 1Password)
- **Expiration**: 90 days (Rotate via 1Password)

### Manifest Marker
Deployment YAMLs must have the comment marker to be eligible for updates:
```yaml
image: ghcr.io/mtgibbs/mtgibbs.xyz:20260104084623 # {"$imagepolicy": "flux-system:mtgibbs-site"}
```

## Troubleshooting

### Check Status
```bash
# Check if image was seen
flux get image repository mtgibbs-site

# Check if policy selected new tag
flux get image policy mtgibbs-site

# Check if commit was pushed
flux get image update mtgibbs-site
```

### Common Issues
- **"authentication required"**: PAT expired or missing permissions.
- **No update happening**: Check if the marker comment in `deployment.yaml` matches the policy name exactly.
