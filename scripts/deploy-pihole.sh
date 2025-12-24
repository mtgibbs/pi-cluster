#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PIHOLE_DIR="$PROJECT_ROOT/clusters/pi-k3s/pihole"
KUBECONFIG="$PROJECT_ROOT/kubeconfig"

export KUBECONFIG

echo "==> Deploying Pi-hole stack..."

# Ensure signed in to 1Password
if ! op account get > /dev/null 2>&1; then
    echo "==> Signing in to 1Password..."
    eval $(op signin)
fi

# Create namespace if it doesn't exist
kubectl create namespace pihole 2>/dev/null || true

# Create pihole-secret from 1Password
echo "==> Creating pihole-secret from 1Password..."
kubectl create secret generic pihole-secret \
    --namespace=pihole \
    --from-literal=WEBPASSWORD="$(op read 'op://pi-cluster/pihole/password')" \
    --dry-run=client -o yaml | kubectl apply -f -

# Deploy Unbound
echo "==> Deploying Unbound..."
kubectl apply -f "$PIHOLE_DIR/unbound-configmap.yaml"
kubectl apply -f "$PIHOLE_DIR/unbound-deployment.yaml"

# Deploy Pi-hole
echo "==> Deploying Pi-hole..."
kubectl apply -f "$PIHOLE_DIR/pihole-pvc.yaml"
kubectl apply -f "$PIHOLE_DIR/pihole-deployment.yaml"
kubectl apply -f "$PIHOLE_DIR/pihole-service.yaml"

# Deploy Pi-hole exporter (for Prometheus metrics)
echo "==> Deploying Pi-hole exporter..."
kubectl apply -f "$PIHOLE_DIR/pihole-exporter.yaml"

# Wait for pods to be ready
echo "==> Waiting for pods to be ready..."
kubectl -n pihole wait --for=condition=ready pod -l app=unbound --timeout=120s
kubectl -n pihole wait --for=condition=ready pod -l app=pihole --timeout=120s

echo "==> Pi-hole stack deployed successfully!"
echo ""
echo "Pi-hole Admin: http://192.168.1.55/admin"
echo "DNS Server: 192.168.1.55"
echo "Password: (from 1Password pi-cluster/pihole)"
