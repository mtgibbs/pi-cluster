---
description: Quick cluster health check - nodes, pods, resources
allowed-tools: Bash(KUBECONFIG=~/dev/pi-cluster/kubeconfig kubectl:*)
---

# Cluster Health Check

Quick overview of K3s cluster health.

## Checks to Run

1. **Node status**:
   ```bash
   KUBECONFIG=~/dev/pi-cluster/kubeconfig kubectl get nodes -o wide
   ```

2. **Resource usage**:
   ```bash
   KUBECONFIG=~/dev/pi-cluster/kubeconfig kubectl top nodes
   ```

3. **Non-running pods**:
   ```bash
   KUBECONFIG=~/dev/pi-cluster/kubeconfig kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded
   ```

4. **Recent events** (warnings/errors only):
   ```bash
   KUBECONFIG=~/dev/pi-cluster/kubeconfig kubectl get events -A --field-selector type!=Normal --sort-by='.lastTimestamp' | tail -20
   ```

5. **PVC status**:
   ```bash
   KUBECONFIG=~/dev/pi-cluster/kubeconfig kubectl get pvc -A
   ```

6. **ExternalSecrets sync**:
   ```bash
   KUBECONFIG=~/dev/pi-cluster/kubeconfig kubectl get externalsecrets -A
   ```

## Output Format

Provide a health summary:

| Component | Status | Details |
|-----------|--------|---------|
| Node | OK/WARN/CRIT | Memory %, CPU % |
| Pods | OK/WARN | X running, Y issues |
| PVCs | OK/WARN | X bound, Y pending |
| Secrets | OK/WARN | X synced, Y failed |
| Events | OK/WARN | Recent warnings |

**Overall**: GREEN / YELLOW / RED

**Action needed**: List any issues requiring attention
