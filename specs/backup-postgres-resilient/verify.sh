#!/usr/bin/env bash
# Static gate for specs/backup-postgres-resilient (§11). Offline, deterministic.
# Exit 0 only if the resilient postgres-backup manifest meets the §10 contract.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# Optional $1 = a candidate manifest to gate before it lands; default = the repo file.
MANIFEST="${1:-$ROOT/clusters/pi-k3s/backup-jobs/postgres-backup-cronjob.yaml}"
[ -f "$MANIFEST" ] || { echo "manifest missing: $MANIFEST"; exit 2; }

exec python3 - "$MANIFEST" <<'PY'
import re, sys
path = sys.argv[1]
src = open(path).read()
fails = []
def chk(name, cond):
    print(("  ok   - " if cond else "  FAIL - ") + name)
    if not cond:
        fails.append(name)

# 1. valid manifest, CronJob named postgres-backup
ok_yaml = False
try:
    import yaml
    d = yaml.safe_load(src)
    ok_yaml = d.get("kind") == "CronJob" and d.get("metadata", {}).get("name") == "postgres-backup"
except ImportError:
    ok_yaml = ("kind: CronJob" in src) and ("name: postgres-backup" in src)
except Exception:
    ok_yaml = False
chk("valid manifest, CronJob 'postgres-backup'", ok_yaml)

chk("uses pg_isready (reachability gate A1-A3)", "pg_isready" in src)
chk("immich host referenced (A1)", "immich-postgresql.immich.svc.cluster.local" in src)
chk("n8n host referenced, NOT dropped (A1)", "n8n-postgresql.n8n.svc.cluster.local" in src)
chk("logs SKIP for unreachable target (A3)", re.search(r"SKIP", src, re.I) is not None)
chk("pg_dump carries connect_timeout=10 (A7)", "connect_timeout=10" in src)
chk("no bash indirect expansion ${!...} — BusyBox ash (Norms §7)", "${!" not in src)
chk("no bash here-string <<< — BusyBox ash (Norms §7)", "<<<" not in src)
chk("no script-wide 'set -e' — explicit per-target handling required (§4, A4)",
    re.search(r"(?m)^\s*set -e", src) is None)
chk("explicit non-zero exit on reachable failure (A4)",
    re.search(r"exit\s+1|exit\s+\$|exit\s+\"\$", src) is not None)
chk("DB_PASSWORD env retained (A6)", "DB_PASSWORD" in src)
chk("N8N_DB_PASSWORD env retained (A6)", "N8N_DB_PASSWORD" in src)
chk("immich-db-password secret retained", "immich-db-password" in src)
chk("n8n-db-password secret retained", "n8n-db-password" in src)
chk("NAS dated postgres path intact (BACKUP_DATE + postgres)",
    ("BACKUP_DATE" in src) and ("postgres" in src))
chk("installs postgresql16-client", "postgresql16-client" in src)

pgs = re.findall(r"PGPASSWORD=\S*", src)
chk("no inline literal PGPASSWORD (var-only, A6)",
    len(pgs) > 0 and all(re.match(r'PGPASSWORD=["\']?\$', p) for p in pgs))

print()
if fails:
    print("VERIFY FAIL (%d failed)" % len(fails))
    sys.exit(1)
print("VERIFY PASS")
sys.exit(0)
PY
