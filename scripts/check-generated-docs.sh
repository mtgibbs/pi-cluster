#!/usr/bin/env bash
# check-generated-docs.sh — fail if any generated doc has drifted from the
# manifests it's derived from. The enforcement side of the "generated, so it
# can't rot" property: CI runs this so stale docs/secrets-map.md or
# docs/domain-map.md can never merge. Locally, run it before pushing.
#
# On drift, each generator prints the exact `--inject` command to fix it.
# Add a new generated doc? Add its --check line here (one place).
set -euo pipefail
cd "$(dirname "$0")/.."

fail=0
run() { echo "→ $*"; "$@" || fail=1; }

run node scripts/gen-secrets-graph.mjs clusters        --check docs/secrets-map.md
run node scripts/gen-domain-map.mjs   clusters/pi-k3s   --check docs/domain-map.md

if [ "$fail" -ne 0 ]; then
  echo "generated docs are stale — run the --inject command(s) above and commit." >&2
  exit 1
fi
echo "all generated docs up to date."
