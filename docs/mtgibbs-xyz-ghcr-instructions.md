# Instructions: Add GHCR Publishing to mtgibbs.xyz

## Context

The mtgibbs.xyz repository contains a Next.js personal website. It currently deploys to Heroku via GitHub Actions. We need to **add** GHCR (GitHub Container Registry) publishing to enable Flux GitOps auto-deployment to a Kubernetes cluster.

**Important details:**
- Repository: https://github.com/mtgibbs/mtgibbs.xyz
- Branch: `mater` (not master - this is intentional)
- Current workflow: `.github/workflows/deploy.yml` - builds and pushes to Heroku
- Existing Dockerfile: Multi-stage Next.js build using `node:16-alpine`

## Requirements

1. **Build multi-architecture Docker images** (linux/amd64 AND linux/arm64)
   - ARM64 is required because the Kubernetes cluster runs on Raspberry Pi

2. **Push images to GitHub Container Registry**
   - Registry: `ghcr.io/mtgibbs/mtgibbs.xyz`

3. **Tag images with timestamps** (YYYYMMDDHHmmss format)
   - Flux ImagePolicy uses numeric sorting to find the newest tag
   - Example: `20260104153022`

4. **Keep the existing Heroku deployment**
   - Don't remove the Heroku push, just add GHCR push alongside it

## Implementation Options

### Option 1: Add GHCR job to existing workflow (Recommended)

Modify `.github/workflows/deploy.yml` to add a new job that runs in parallel with the Heroku job.

The GHCR job should:
1. Use `docker/setup-qemu-action@v3` for ARM64 emulation
2. Use `docker/setup-buildx-action@v3` for multi-platform builds
3. Use `docker/login-action@v3` with `${{ secrets.GITHUB_TOKEN }}` for GHCR auth
4. Use `docker/metadata-action@v5` to generate tags
5. Use `docker/build-push-action@v5` with `platforms: linux/amd64,linux/arm64`

### Option 2: Create separate workflow file

Create a new file `.github/workflows/ghcr.yml`:

```yaml
name: Build and Push to GHCR

on:
  push:
    branches:
      - mater

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up QEMU
        uses: docker/setup-qemu-action@v3

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            type=sha,prefix=
            type=raw,value={{date 'YYYYMMDDHHmmss'}}
            type=raw,value=latest

      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          platforms: linux/amd64,linux/arm64
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

## Key Technical Details

- **GITHUB_TOKEN** has automatic `packages:write` permission - no new secrets needed
- **Timestamp tags** (YYYYMMDDHHmmss) are critical - Flux ImagePolicy uses numeric sorting
- **Multi-platform build** is essential - the Pi cluster uses ARM64
- **GHA cache** (`cache-from: type=gha`) speeds up subsequent builds significantly

## Verification After Merge

1. Push to `mater` branch to trigger the workflow
2. Check Actions tab for successful build
3. Verify image appears at: https://github.com/users/mtgibbs/packages/container/mtgibbs.xyz
4. Verify multi-arch manifest:
   ```bash
   docker manifest inspect ghcr.io/mtgibbs/mtgibbs.xyz:latest
   ```
   Should show both `linux/amd64` and `linux/arm64` platforms

## Optional: Make Package Public

After the first successful build, you can make the package public to avoid needing imagePullSecrets in Kubernetes:

1. Go to https://github.com/users/mtgibbs/packages/container/mtgibbs.xyz/settings
2. Scroll to "Danger Zone"
3. Click "Change visibility" and select "Public"

This is optional - the cluster will also work with private images if you add an imagePullSecret.
