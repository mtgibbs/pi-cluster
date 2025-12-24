#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VALUES_TPL="$PROJECT_ROOT/clusters/pi-k3s/monitoring/kube-prometheus-values.yaml.tpl"
KUBECONFIG="$PROJECT_ROOT/kubeconfig"

echo "==> Deploying monitoring stack..."

# Ensure signed in to 1Password
if ! op account get > /dev/null 2>&1; then
    echo "==> Signing in to 1Password..."
    eval $(op signin)
fi

# Ensure helm repo is added
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts 2>/dev/null || true
helm repo update > /dev/null

# Inject secrets and deploy
echo "==> Injecting secrets from 1Password and deploying..."
op inject -i "$VALUES_TPL" | \
    KUBECONFIG="$KUBECONFIG" helm upgrade --install kube-prometheus prometheus-community/kube-prometheus-stack \
        --namespace monitoring \
        --create-namespace \
        --wait \
        -f -

echo "==> Monitoring stack deployed successfully!"
echo ""
echo "Grafana: http://192.168.1.55:30030"
echo "Username: admin"
echo "Password: (from 1Password pi-cluster/grafana)"
