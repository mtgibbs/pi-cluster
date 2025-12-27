# Pi Worker Node Setup Guide

This guide documents how to prepare a fresh Raspberry Pi (3 or newer) to join the K3s cluster as a worker node.

## Prerequisites

- Raspberry Pi with Pi OS Lite 64-bit installed
- Network connectivity (static IP or DHCP reservation recommended)
- SSH access enabled
- User account created (e.g., `mtgibbs`)

## Step 1: SSH Key Setup

On the Pi, add your public key:

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo 'YOUR_PUBLIC_KEY_HERE' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

## Step 2: Enable cgroups

K3s requires cgroups for container resource management.

```bash
sudo sed -i 's/$/ cgroup_memory=1 cgroup_enable=memory/' /boot/firmware/cmdline.txt
```

Verify:
```bash
cat /boot/firmware/cmdline.txt
# Should end with: cgroup_memory=1 cgroup_enable=memory
```

## Step 3: Disable Swap

K3s/Kubernetes doesn't work well with swap enabled.

```bash
# Disable zram swap (Pi OS default)
sudo systemctl mask systemd-zram-setup@zram0.service

# Disable dphys-swapfile if present
sudo systemctl disable --now dphys-swapfile 2>/dev/null || true

# Turn off swap immediately
sudo swapoff -a
```

Verify:
```bash
free -h | grep -i swap
# Should show: Swap: 0B 0B 0B
```

## Step 4: Reboot

```bash
sudo reboot
```

## Step 5: Join K3s Cluster

Get the join token from the master node (Pi 5 at 192.168.1.55):

```bash
# On master node
sudo cat /var/lib/rancher/k3s/server/node-token
```

Install k3s agent on the worker:

```bash
curl -sfL https://get.k3s.io | K3S_URL=https://192.168.1.55:6443 K3S_TOKEN=<TOKEN> sh -
```

## Step 6: Verify

On your workstation:

```bash
kubectl get nodes
# Should show the new worker node
```

## Current Cluster Nodes

| Role | Hostname | IP | Hardware |
|------|----------|-----|----------|
| Master | pi-k3s | 192.168.1.55 | Pi 5 (8GB) |
| Worker | pi3-worker-1 | 192.168.1.53 | Pi 3 (1GB) |
| Worker | pi3-worker-2 | 192.168.1.51 | Pi 3 (1GB) |

## Troubleshooting

### Check k3s agent status
```bash
sudo systemctl status k3s-agent
sudo journalctl -u k3s-agent -f
```

### Node not showing in cluster
- Verify network connectivity to master (ping 192.168.1.55)
- Check firewall isn't blocking port 6443
- Verify token is correct
- Check k3s-agent logs for errors
