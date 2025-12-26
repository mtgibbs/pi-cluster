---
name: k8s-troubleshooting
description: Diagnose and fix Kubernetes cluster issues on Pi K3s. Use when investigating pod failures, resource issues, networking problems, DNS issues, or general cluster health concerns.
allowed-tools: Bash, Read, Grep, Glob
---

# Kubernetes Troubleshooting

## When to Use This Skill

Use this skill when:
- Pods are failing, crashing, or stuck pending
- Services are unreachable
- DNS resolution isn't working
- Resource pressure (CPU/memory) issues
- PVCs not binding
- General cluster health concerns

## Environment

```bash
export KUBECONFIG=~/dev/pi-cluster/kubeconfig
```

## Quick Diagnostics

```bash
# Cluster overview
kubectl get nodes -o wide
kubectl top nodes
kubectl get pods -A | grep -v Running | grep -v Completed

# Recent problems
kubectl get events -A --field-selector type!=Normal --sort-by='.lastTimestamp' | head -30

# Resource pressure
kubectl top pods -A --sort-by=memory | head -20
```

## Investigation Framework

### 1. Pod Issues

```bash
# Check pod status
kubectl get pods -n <namespace>
kubectl describe pod <name> -n <namespace>
kubectl logs <name> -n <namespace>
kubectl logs <name> -n <namespace> --previous  # Crashed container

# Common states:
# - Pending: Resource constraints, node selector, PVC issues
# - CrashLoopBackOff: App error, check logs
# - ImagePullBackOff: Registry auth, image doesn't exist
# - ContainerCreating: Volume mount issues, init containers
```

### 2. Service Connectivity

```bash
# Check service endpoints
kubectl get svc -n <namespace>
kubectl get endpoints -n <namespace>

# Test from within cluster
kubectl run -it --rm debug --image=busybox --restart=Never -- wget -qO- http://<service>.<namespace>:port

# Check ingress
kubectl get ingress -A
kubectl describe ingress <name> -n <namespace>
```

### 3. DNS Issues

```bash
# Test DNS from Pi-hole
dig @192.168.1.55 google.com

# Test cluster DNS
kubectl run -it --rm dns-test --image=busybox --restart=Never -- nslookup kubernetes.default

# Check CoreDNS (k3s uses embedded)
kubectl logs -n kube-system -l k8s-app=kube-dns

# Check Pi-hole pod
kubectl logs -n pihole deploy/pihole | tail -50

# Check Unbound
kubectl logs -n pihole deploy/unbound | tail -50
```

### 4. Storage Issues

```bash
# Check PVCs
kubectl get pvc -A
kubectl describe pvc <name> -n <namespace>

# Check PVs
kubectl get pv

# K3s local-path provisioner
kubectl logs -n kube-system deploy/local-path-provisioner

# Check disk space on Pi
# (SSH to Pi): df -h
```

### 5. Resource Pressure

```bash
# Node resources (Pi has 8GB RAM)
kubectl top nodes
kubectl describe node pi-k3s | grep -A 10 "Allocated resources"

# Pod resources
kubectl top pods -A --sort-by=memory
kubectl top pods -A --sort-by=cpu

# Resource limits vs actual
kubectl get pods -A -o custom-columns="NAMESPACE:.metadata.namespace,NAME:.metadata.name,MEM_REQ:.spec.containers[*].resources.requests.memory,MEM_LIM:.spec.containers[*].resources.limits.memory"
```

### 6. Network Policies

```bash
# Check network policies
kubectl get networkpolicies -A

# K3s uses Flannel by default - generally permissive
```

## Common Issues & Solutions

### Pod Pending - Insufficient Resources
```bash
# Check node capacity
kubectl describe node pi-k3s | grep -A 5 "Allocated resources"

# Solution: Reduce resource requests or remove low-priority pods
```

### CrashLoopBackOff
```bash
# Get logs from crashed container
kubectl logs <pod> -n <namespace> --previous

# Common causes:
# - Missing config/secrets
# - Port already in use (hostNetwork conflicts)
# - Health check failing
```

### PVC Stuck Pending
```bash
# Check events
kubectl describe pvc <name> -n <namespace>

# Common causes:
# - StorageClass doesn't exist (use local-path)
# - Disk space exhausted
# - PV already bound to another PVC
```

### Service Unreachable
```bash
# Verify endpoints exist
kubectl get endpoints <service> -n <namespace>

# No endpoints = selector doesn't match pod labels
kubectl get pods -n <namespace> --show-labels
```

### Ingress Not Working
```bash
# Check ingress controller
kubectl get pods -n ingress-nginx

# Verify ingress config
kubectl describe ingress <name> -n <namespace>

# Check nginx config
kubectl exec -n ingress-nginx deploy/ingress-nginx-controller -- cat /etc/nginx/nginx.conf | grep -A 5 "<hostname>"
```

## Pi-Specific Considerations

- **8GB RAM limit**: Monitor memory closely, Prometheus can be hungry
- **hostNetwork on Pi-hole**: Port 80 unavailable for ingress, uses 443 only
- **ARM64 architecture**: Ensure all images support linux/arm64
- **SD card I/O**: Can be slow, affects PVC performance
- **Single node**: No redundancy, pod eviction = downtime
