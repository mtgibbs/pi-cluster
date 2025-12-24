#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=========================================="
echo "  Pi-Cluster Full Deployment"
echo "=========================================="
echo ""

# Deploy Pi-hole stack first (DNS)
"$SCRIPT_DIR/deploy-pihole.sh"

echo ""
echo "=========================================="
echo ""

# Deploy monitoring stack
"$SCRIPT_DIR/deploy-monitoring.sh"

echo ""
echo "=========================================="
echo "  Deployment Complete!"
echo "=========================================="
echo ""
echo "Services:"
echo "  - Pi-hole Admin: http://192.168.1.55/admin"
echo "  - Grafana:       http://192.168.1.55:30030"
echo "  - DNS Server:    192.168.1.55"
echo ""
echo "Passwords are stored in 1Password vault 'pi-cluster'"
