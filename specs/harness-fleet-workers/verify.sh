#!/usr/bin/env bash
# verify.sh — deterministic acceptance gate for specs/harness-fleet-workers.
# §10 acceptance criteria + §8 safeguards compiled to runnable assertions: exit 0 = acceptable.
#
# PRESENCE-GATED (the ralph contract): runs after EVERY task and must pass, so a check for a
# not-yet-written file is PEND, never FAIL. STRICT=1 (ralph's final pass) turns every pend into a
# failure — presence-gating can verify "correct if present" but can NEVER verify "done".
#
# STATIC tier only. It reads committed YAML and never touches a cluster, so it cannot prove the
# pull secret works, that Flux reconciles, or that a Job schedules. Those are §11's LIVE tier and a
# human's call after deploy — the same split specs/harness-egress-allowlist documents.
#
# bash 3.2 (AGENTS.md): no mapfile, no readarray, no associative arrays. This gate is most likely
# to be run from the laptop.
set -uo pipefail
R="${REPO_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
D="$R/clusters/pi-k3s/harness-fleet"
fail=0
ok(){   echo "  PASS  $1"; }
no(){   echo "  FAIL  $1" >&2; fail=1; }
pend(){
  if [ "${STRICT:-0}" = 1 ]; then no "$1 — still unbuilt at the final check (STRICT)"; else
    echo "  pend  $1 (not built yet)"; fi
}

echo "VERIFY specs/harness-fleet-workers  (REPO_ROOT=$R)"

# has_kind <kind> — is there a file in $D declaring this kind? Prints the first path, or nothing.
has_kind() {
  [ -d "$D" ] || return 1
  grep -l "^kind:[[:space:]]*$1[[:space:]]*$" "$D"/*.yaml 2>/dev/null | head -1
}

# ---------- AC-1: the namespace ----------
NS="$(has_kind Namespace)"
if [ -z "$NS" ]; then
  pend "AC-1: the harness-fleet Namespace"
elif grep -qE '^[[:space:]]+name:[[:space:]]*harness-fleet[[:space:]]*$' "$NS"; then
  ok "AC-1: the Namespace is harness-fleet"
else
  no "AC-1: a Namespace exists but is not named harness-fleet — the dispatcher renders into a namespace it is told, and the sibling 'harness' namespace holds the coordinator (spec §3)"
fi

# ---------- AC-2: the default ServiceAccount carries the pull secret ----------
# THE load-bearing check. The rendered Job carries no imagePullSecrets and no serviceAccountName,
# so a pod runs as `default` and only that account can supply the credential. If this is wrong,
# every dispatched run dies at ImagePullBackOff with nothing in the Job to explain why.
SA_DEFAULT=""
if [ -d "$D" ]; then
  for f in "$D"/*.yaml; do
    [ -f "$f" ] || continue
    grep -q "^kind:[[:space:]]*ServiceAccount" "$f" || continue
    grep -qE '^[[:space:]]+name:[[:space:]]*default[[:space:]]*$' "$f" || continue
    SA_DEFAULT="$f"; break
  done
fi
if [ -z "$SA_DEFAULT" ]; then
  pend "AC-2: the patched default ServiceAccount"
elif ! grep -q 'imagePullSecrets' "$SA_DEFAULT"; then
  no "AC-2: the default ServiceAccount declares no imagePullSecrets — the Job body will never name one, so this is the only place the credential can come from (spec §3)"
elif ! grep -q 'ghcr-pull-secret' "$SA_DEFAULT"; then
  no "AC-2: the default ServiceAccount's imagePullSecrets does not reference ghcr-pull-secret"
else
  ok "AC-2: the default ServiceAccount carries ghcr-pull-secret"
fi

# ---------- AC-3: the GHCR pull secret, from the EXISTING cluster identity ----------
GHCR=""
if [ -d "$D" ]; then
  for f in "$D"/*.yaml; do
    [ -f "$f" ] || continue
    grep -q "^kind:[[:space:]]*ExternalSecret" "$f" || continue
    grep -q 'ghcr-pull-secret' "$f" || continue
    GHCR="$f"; break
  done
fi
if [ -z "$GHCR" ]; then
  pend "AC-3: the ghcr-pull-secret ExternalSecret"
elif ! grep -q 'dockerconfigjson' "$GHCR"; then
  no "AC-3: the pull secret is not typed kubernetes.io/dockerconfigjson, so kubelet will not use it"
elif ! grep -q 'ghcr-read-token' "$GHCR"; then
  no "AC-3: the pull secret does not come from the existing ghcr-read-token item. One 1Password item is the whole cluster's pull identity (clusters/pi-k3s/harness/external-secret-ghcr.yaml) — a second is a second thing to rotate"
else
  ok "AC-3: ghcr-pull-secret is materialised from the existing ghcr-read-token"
fi

# ---------- AC-4/5/6: the dispatcher's identity and its bounds ----------
ROLE="$(has_kind Role)"
CROLE="$(has_kind ClusterRole)"
SA_DISP=""
if [ -d "$D" ]; then
  for f in "$D"/*.yaml; do
    [ -f "$f" ] || continue
    grep -q "^kind:[[:space:]]*ServiceAccount" "$f" || continue
    grep -qE '^[[:space:]]+name:[[:space:]]*default[[:space:]]*$' "$f" && continue
    SA_DISP="$f"; break
  done
fi
[ -n "$SA_DISP" ] && ok "AC-4: the dispatcher has its own ServiceAccount" \
                  || pend "AC-4: the dispatcher ServiceAccount"

if [ -n "$CROLE" ]; then
  no "AC-5: a ClusterRole was declared. A dispatcher that can create Jobs cluster-wide can create Jobs in kube-system; fleet-dispatch.md scopes this to ONE namespace (spec §8)"
elif [ -z "$ROLE" ]; then
  pend "AC-5: the dispatcher Role"
else
  rmiss=""
  grep -q 'batch' "$ROLE" || rmiss="$rmiss batch"
  grep -q 'jobs'  "$ROLE" || rmiss="$rmiss jobs"
  # Both YAML styles. verbs: ["create", "get"] is as valid as a block sequence of `- create`,
  # and a class of [[:space:]-] matches only the second — which reported a CORRECT Role as
  # missing every verb. Delimit on "not a word character" instead, which also stops `get`
  # matching inside `widget`.
  for v in create get list watch delete; do
    grep -qE "(^|[^A-Za-z0-9_-])$v([^A-Za-z0-9_-]|$)" "$ROLE" || rmiss="$rmiss verb:$v"
  done
  if [ -n "$rmiss" ]; then
    no "AC-5: the Role does not grant Job management —$rmiss"
  elif grep -qE '^[[:space:]]*-?[[:space:]]*"?secrets"?[[:space:]]*$' "$ROLE"; then
    no "AC-5: the Role grants a verb on secrets. A component that launches workers does not need to READ the credentials they receive, and the worker secrets here include a PAT that can push code (spec §8)"
  else
    ok "AC-5: a namespaced Role grants Job management and nothing on secrets"
  fi
fi

RB="$(has_kind RoleBinding)"
if [ -z "$RB" ]; then
  pend "AC-6: the RoleBinding"
elif grep -q 'ServiceAccount' "$RB" && grep -q 'Role' "$RB"; then
  ok "AC-6: the Role is bound to a ServiceAccount"
else
  no "AC-6: the RoleBinding does not bind a Role to a ServiceAccount"
fi

# ---------- AC-7: the concurrency cap ----------
RQ="$(has_kind ResourceQuota)"
if [ -z "$RQ" ]; then
  pend "AC-7: the ResourceQuota"
elif ! grep -q 'count/jobs.batch' "$RQ"; then
  no "AC-7: the quota does not cap count/jobs.batch. backoffLimit 0 stops a Job retrying; nothing stops a dispatcher creating a hundred of them"
else
  n="$(grep 'count/jobs.batch' "$RQ" | sed -E 's/.*:[[:space:]]*"?([0-9]+)"?.*/\1/' | head -1)"
  case "$n" in
    ''|*[!0-9]*) no "AC-7: count/jobs.batch has no readable integer cap" ;;
    *) if [ "$n" -le 2 ] && [ "$n" -ge 1 ]; then
         ok "AC-7: count/jobs.batch is capped at $n"
       else
         no "AC-7: count/jobs.batch is $n; fleet-dispatch.md names a concurrency cap of 1-2"
       fi ;;
  esac
fi

# ---------- AC-8/9: per-strategy worker credentials ----------
wmiss=""
for s in build-converge build-codex; do
  found=""
  if [ -d "$D" ]; then
    for f in "$D"/*.yaml; do
      [ -f "$f" ] || continue
      grep -q "harness-worker-$s" "$f" && { found="$f"; break; }
    done
  fi
  [ -n "$found" ] || wmiss="$wmiss $s"
done
if [ -n "$wmiss" ]; then
  pend "AC-8: worker secrets for:$wmiss"
else
  ok "AC-8: every named strategy has its own worker secret"
fi

# AC-9 is an ABSENCE, so it is only meaningful once the files it scans exist — otherwise it passes
# for free against an empty directory, which is the shape of a check that never fires.
if [ -n "$wmiss" ]; then
  pend "AC-9: no worker secret carries the dispatch API token"
elif _bad=""; for f in "$D"/*.yaml; do
       [ -f "$f" ] || continue
       grep -q 'harness-worker-' "$f" || continue
       grep -q 'HARNESS_API_TOKEN' "$f" && _bad="$_bad $(basename "$f")"
     done; [ -n "$_bad" ]; then
  no "AC-9: a worker secret carries the dispatch API token. The outcome PAT may push a branch and open a PR and may NEVER launch compute — a worker that can start more workers turns one compromise into a fleet (spec §8)"
else
  ok "AC-9: no worker secret carries a token that can launch compute"
fi

# ---------- AC-10: nothing inlined ----------
if [ ! -d "$D" ]; then
  pend "AC-10: no inlined secret values"
elif grep -rqE '^[[:space:]]*stringData:' "$D" 2>/dev/null; then
  no "AC-10: a manifest uses stringData — secrets come from 1Password through ExternalSecrets, never inline (AGENTS.md)"
elif grep -rqE '^[[:space:]]*(password|token|apiKey|key):[[:space:]]*[A-Za-z0-9+/]{16,}' "$D" 2>/dev/null; then
  no "AC-10: a manifest appears to inline a credential value"
else
  ok "AC-10: no manifest inlines a secret value"
fi

# ---------- AC-11: everything is actually applied ----------
K="$D/kustomization.yaml"
if [ ! -f "$K" ]; then
  pend "AC-11: kustomization.yaml"
else
  kmiss=""
  for f in "$D"/*.yaml; do
    [ -f "$f" ] || continue
    b="$(basename "$f")"
    [ "$b" = "kustomization.yaml" ] && continue
    grep -q "$b" "$K" || kmiss="$kmiss $b"
  done
  if [ -n "$kmiss" ]; then
    no "AC-11: kustomization.yaml does not list:$kmiss — a manifest Flux never applies is a manifest that does not exist, and it looks identical in review"
  else
    ok "AC-11: kustomization.yaml lists every resource in the directory"
  fi
fi

# ---------- AC-12: the runbook says what is inert, and why ----------
RM="$D/README.md"
if [ ! -f "$RM" ]; then
  pend "AC-12: the runbook"
elif ! grep -qiE 'inert|not.*deploy|nothing to deploy|not yet' "$RM"; then
  no "AC-12: the runbook does not say these resources are inert. A reader who finds an empty namespace needs to know it is waiting rather than broken"
elif ! grep -qiE 'dispatcher\.py|not packaged|no image' "$RM"; then
  no "AC-12: the runbook does not name WHY — dispatcher.py and api.py are in no image, so there is nothing to deploy here yet"
else
  ok "AC-12: the runbook records what is inert and what unblocks it"
fi

echo
[ "$fail" = 0 ] && echo "VERIFY: PASS" || echo "VERIFY: FAIL"
exit "$fail"
