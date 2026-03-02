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

## Diagnostic Discipline (MANDATORY)

1. **Prove the server path first.** Check pod health, logs, and upstream deps BEFORE suggesting client-side causes.
2. **Cached success is not proof.** DNS caches, stale metrics, and HTTP caches can mask failures. Use tools that bypass caches.
3. **Check every layer.** One green light doesn't prove the layers behind it are healthy.

## Quick Diagnostics

### Router: MCP Tools (USE FIRST)

| Operation | MCP Tool |
| :--- | :--- |
| Cluster health (nodes, resources, problem pods) | `get_cluster_health` |
| Pod logs | `get_pod_logs(namespace, pod)` |
| Describe resource (deploy, pod, svc, etc.) | `describe_resource(kind, namespace, name)` |
| PVC status | `get_pvcs(namespace)` |
| DNS diagnostics | `diagnose_dns(domain)` — see dns-ops skill |
| DNS status | `get_dns_status` |
| Flux sync status | `get_flux_status` |
| Certificate status | `get_certificate_status` |
| Ingress status | `get_ingress_status` |
| Secret sync status | `get_secrets_status` |
| Backup job status | `get_backup_status` |
| Job logs | `get_job_logs(namespace, job)` |
| Network connectivity test | `test_pod_connectivity(sourceNode, target)` |
| HTTP connectivity test | `curl_ingress(url)` |

### cluster-ops: kubectl Fallback

```bash
export KUBECONFIG=~/dev/pi-cluster/kubeconfig

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

**MCP first:**
- `get_cluster_health` — shows problem pods across all namespaces
- `get_pod_logs(namespace, pod)` — supports container selection, previous logs, time filtering
- `describe_resource(kind="pod", namespace, name)` — full spec and status

**kubectl fallback (cluster-ops):**
```bash
kubectl get pods -n <namespace>
kubectl describe pod <name> -n <namespace>
kubectl logs <name> -n <namespace>
kubectl logs <name> -n <namespace> --previous
```

Common states:
- **Pending**: Resource constraints, node selector, PVC issues
- **CrashLoopBackOff**: App error, check logs
- **ImagePullBackOff**: Registry auth, image doesn't exist
- **ContainerCreating**: Volume mount issues, init containers

### 2. Service Connectivity

**MCP first:**
- `get_ingress_status` — hosts, TLS, backend health
- `curl_ingress(url)` — test HTTP(S) from within cluster
- `test_pod_connectivity(sourceNode, target)` — ping + port check
- `describe_resource(kind="service", namespace)` — list services or inspect one

**kubectl fallback (cluster-ops):**
```bash
kubectl get svc -n <namespace>
kubectl get endpoints -n <namespace>
kubectl run -it --rm debug --image=busybox --restart=Never -- wget -qO- http://<service>.<namespace>:port
```

### 3. DNS Issues

**STOP — Load the dns-ops skill instead:** `.claude/skills/dns-ops/SKILL.md`

It has a mandatory troubleshooting runbook with MCP-first diagnostic flow using `diagnose_dns`.

Quick MCP check: `diagnose_dns(domain)` tests Pi-hole + both Unbounds + DNSSEC in one call.

### 4. Storage Issues

**MCP first:**
- `get_pvcs(namespace)` — PVC status, capacity, storage class, bound volume

**kubectl fallback (cluster-ops):**
```bash
kubectl get pvc -A
kubectl describe pvc <name> -n <namespace>
kubectl get pv
kubectl logs -n kube-system deploy/local-path-provisioner
```

### 5. Resource Pressure

**MCP first:**
- `get_cluster_health` — node resource usage and allocatable capacity

**kubectl fallback (cluster-ops):**
```bash
kubectl top nodes
kubectl describe node pi-k3s | grep -A 10 "Allocated resources"
kubectl top pods -A --sort-by=memory
kubectl top pods -A --sort-by=cpu
```

### 6. Network

**MCP first:**
- `get_node_networking(node)` — interfaces, addresses, routes, routing rules
- `get_iptables_rules(node)` — firewall/routing debug
- `get_conntrack_entries(node)` — connection tracking debug
- `test_pod_connectivity(sourceNode, target)` — reachability test
- `curl_ingress(url)` — HTTP-level test

**kubectl fallback (cluster-ops):**
```bash
kubectl get networkpolicies -A
# K3s uses Flannel — generally permissive
```

## Common Issues & Solutions

### Pod Pending - Insufficient Resources
Use `get_cluster_health` to check node capacity and allocated resources.
Solution: Reduce resource requests or remove low-priority pods.

### CrashLoopBackOff
Use `get_pod_logs(namespace, pod, previous=true)` for crashed container logs.
Common causes: missing config/secrets, port conflicts (hostNetwork), failing health checks.

### PVC Stuck Pending
Use `get_pvcs` to check status and `describe_resource(kind="pod", namespace, name)` for events.
Common causes: StorageClass doesn't exist (use `local-path`), disk space exhausted, PV already bound.

### Service Unreachable
Use `describe_resource(kind="service", namespace, name)` and check endpoints.
No endpoints = selector doesn't match pod labels.

### Ingress Not Working
Use `get_ingress_status` for all ingress config, then `curl_ingress(url)` to test connectivity.
Check cert status with `get_certificate_status` if TLS errors.

## Pi-Specific Considerations

- **8GB RAM limit**: Monitor memory closely, Prometheus can be hungry
- **hostNetwork on Pi-hole**: Port 80 unavailable for ingress, uses 443 only
- **ARM64 architecture**: Ensure all images support linux/arm64
- **SD card I/O**: Can be slow, affects PVC performance
- **Single node**: No redundancy, pod eviction = downtime
