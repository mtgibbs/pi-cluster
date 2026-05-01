#!/bin/sh
# QNAP NFS Readiness Check
#
# Run this BEFORE attempting another cutover. Probes QNAP from inside
# the cluster (via a one-off pod) to verify NFS services are healthy
# and exports are correctly configured.
#
# Usage:
#   sh migration/qnap-readiness-check.sh
#
# Pass criteria — ALL must be present:
#   - showmount -e returns at least one /cluster export
#   - rpcinfo lists portmapper (100000), mountd (100005), nfs (100003)
#   - lockd (100021) and statd (100024) are EITHER listed OR you're committed
#     to using `nolock` mount option in every PV
#   - DNS storage.lab.mtgibbs.dev resolves to QNAP IP

set -e
QNAP_HOST="${1:-storage.lab.mtgibbs.dev}"
QNAP_IP="${QNAP_HOST}"

echo "=== DNS resolution ==="
kubectl run readiness-dns --image=alpine:3.19 --rm -it --restart=Never -n default -- \
  sh -c "apk add -q bind-tools && nslookup $QNAP_HOST 2>&1 | tail -10"

echo ""
echo "=== showmount -e (what's exported?) ==="
kubectl run readiness-showmount --image=alpine:3.19 --rm -it --restart=Never -n default --overrides='{"spec":{"hostNetwork":true}}' -- \
  sh -c "apk add -q nfs-utils && showmount -e $QNAP_HOST 2>&1"

echo ""
echo "=== rpcinfo (NFS service health) ==="
kubectl run readiness-rpcinfo --image=alpine:3.19 --rm -it --restart=Never -n default --overrides='{"spec":{"hostNetwork":true}}' -- \
  sh -c "apk add -q nfs-utils && rpcinfo -p $QNAP_HOST 2>&1"

echo ""
echo "=== Done. Check output:"
echo "  - DNS must show $QNAP_HOST → 192.168.1.61 (QNAP)"
echo "  - showmount must list /cluster (or whatever export name you've configured)"
echo "  - rpcinfo must list at minimum: portmapper, mountd, nfs"
echo "  - lockd + statd present = locking works (no nolock needed)"
echo "  - lockd + statd missing = use 'nolock' in all PV mountOptions"
