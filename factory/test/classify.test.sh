#!/usr/bin/env bash
# Unit tests for factory/classify.sh on synthetic diffs from a throwaway git repo.
#   bash factory/test/classify.test.sh
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
CLASSIFY="$HERE/../classify.sh"
pass=0; fail=0

repo=$(mktemp -d)
trap 'rm -rf "$repo"' EXIT
cd "$repo"
git init -q -b main . && git config user.email t@t && git config user.name t
mkdir -p src/tools src/clients src/__tests__ docs .github/workflows
cat > src/tools/storage.ts <<'EOF'
export const getPvcs = {
  name: 'get_pvcs',
  readOnly: true,
  handler: async () => { const m = /x/.exec('x'); return m; },
};
EOF
cat > src/tools/index.ts <<'EOF'
export function allowed(tool, scope) {
  return !(scope === 'readonly' && !tool.readOnly);
}
EOF
echo "export const c = 1;" > src/clients/pihole.ts
cat > src/__tests__/pihole.test.ts <<'EOF'
import { it, expect } from 'vitest';
it('polls the primary', () => { expect(1).toBe(1); });
it('polls the secondary', () => { expect(2).toBe(2); });
EOF
echo '{"name":"x"}' > package.json
echo "# Docs" > docs/readme.md
echo "on: push" > .github/workflows/ci.yaml
git add -A && git commit -qm base
BASE=$(git rev-parse HEAD)

# expect <name> <class|exit2> [classify args...] — runs after the caller mutated the tree
expect() {
  local name=$1 want=$2; shift 2
  local out rc got
  out=$(git add -A && git diff --cached --no-renames -U1000000 "$BASE" | bash "$CLASSIFY" "$@" 2>&1); rc=$?
  if [ "$want" = exit2 ]; then got=$([ $rc -eq 2 ] && echo exit2 || echo "rc=$rc")
  else got=$(echo "$out" | sed -n 's/^class=//p' | head -1); fi
  if [ "$got" = "$want" ]; then pass=$((pass+1)); echo "  PASS  $name ($want)"
  else fail=$((fail+1)); echo "  FAIL  $name: want $want, got '$got'"; echo "$out" | sed 's/^/        /'; fi
  git reset -q --hard "$BASE"; git clean -qfd
}

echo "classify.sh"
echo "more" >> docs/readme.md;                                      expect "docs only" A
sed -i.bak 's/get_pvcs/get_pvcs_v2/' src/tools/storage.ts; rm -f src/tools/storage.ts.bak
                                                                     expect "read-only tool file (regex .exec is not exec)" A
cat > src/tools/restart.ts <<'EOF'
export const restart = { name: 'restart', readOnly: false, handler: async () => 1 };
EOF
                                                                     expect "new tool file with readOnly: false" B
cat > src/tools/nodeinfo.ts <<'EOF'
import { execOnNode } from '../utils/debug-agent.js';
export const t = { name: 'node_info', readOnly: true, handler: async () => execOnNode('n', ['uname']) };
EOF
                                                                     expect "tool file that calls execOnNode" B
echo "export const d = 2;" >> src/clients/pihole.ts;                expect "client change" B
sed -i.bak 's/scope === .readonly. \&\& //' src/tools/index.ts; rm -f src/tools/index.ts.bak
                                                                     expect "registry change touching readOnly scope" B
echo '{"name":"y"}' > package.json;                                  expect "package.json" C
echo "on: pull_request" > .github/workflows/ci.yaml;                 expect ".github workflow" C
git rm -q src/__tests__/pihole.test.ts;                              expect "test file deleted" C
sed -i.bak "s/^it('polls the secondary'/it.skip('polls the secondary'/" src/__tests__/pihole.test.ts; rm -f src/__tests__/*.bak
                                                                     expect "test .skip added" C
sed -i.bak "/polls the secondary/d" src/__tests__/pihole.test.ts; rm -f src/__tests__/*.bak
                                                                     expect "test case removed" C
echo "it('polls both', () => {});" >> src/__tests__/pihole.test.ts;  expect "test added" A
echo "more" >> docs/readme.md; echo "export const e = 3;" >> src/clients/pihole.ts
                                                                     expect "docs + client = highest wins" B
echo "export const e = 3;" >> src/clients/pihole.ts; echo '{}' > package.json
                                                                     expect "client + package.json" C
mkdir -p specs/x && echo 'exit 0' > specs/x/verify.sh;              expect "spec files only" A
mkdir -p specs/x && echo 'exit 0' > specs/x/verify.sh;              expect "tampered verify.sh" C --tampered "blob abc != def"
mkdir -p k8s && echo "kind: ClusterRole" > k8s/clusterrole.yaml;    expect "RBAC manifest" C
                                                                     expect "empty diff" exit2
echo "not a diff" | bash "$CLASSIFY" >/dev/null 2>&1; rc=$?
if [ $rc -eq 2 ]; then pass=$((pass+1)); echo "  PASS  garbage input (exit2)"; else fail=$((fail+1)); echo "  FAIL  garbage input rc=$rc"; fi

echo "classify.sh: $pass passed, $fail failed"
[ $fail -eq 0 ]
