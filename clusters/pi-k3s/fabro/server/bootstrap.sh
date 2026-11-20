#!/bin/sh
# Fabro bootstrap — runs in the `bootstrap` container on EVERY pod start (statefulset.yaml).
#
# Fabro keeps provider keys, the GitHub token and its sandbox "environments" in its own SQLite
# database and only accepts them through its API against a running server. This script is what
# makes a from-scratch rebuild (empty PVC) come up configured with no UI or CLI step:
#
#   1. wait for the server's unauthenticated health endpoint
#   2. write every key of the `fabro-vault-seed` Secret into Fabro's vault
#      (POST /api/v1/secrets — the call `fabro secret set` makes; it creates or overwrites)
#   3. create-or-replace one environment per /etc/fabro/environment-<id>.json
#   4. mark itself ready (the container's readinessProbe), then idle
#
# Every step overwrites, so re-running against an already-configured database changes nothing.
# Git wins: an environment edited in the UI is put back on the next pod start, and the ConfigMap
# holding these files is name-hashed (kustomization.yaml), so editing any of them rolls the pod.
#
# There is no image pre-pull step, on purpose: Fabro's Docker provider pulls an environment's image
# itself the first time a run needs it (measured — see ../README.md). The sidecar's image store is
# an emptyDir, so the first run after each pod restart pays for that pull.
#
# SECRETS. This script must never print one: no `set -x`, no curl -v, response bodies are never
# echoed. Nothing secret is ever on a command line either — the dev token goes into a header file
# and vault values into a request-body file, both written by the shell's builtin `printf` on a
# memory-backed emptyDir, and curl reads them with `@file`.
#
# Tools: the curlimages/curl image — busybox sh, sed, grep, curl. No jq, hence the two small sed
# expressions below.
set -eu
umask 077

SERVER=http://127.0.0.1:32276
SEED_DIR=/run/secrets/fabro-vault-seed
CONF_DIR=/etc/fabro
WORK="${HOME:?HOME must be a writable scratch dir}"
READY="${WORK}/ready"
AUTH="${WORK}/auth.header"
BODY="${WORK}/request.json"
RESP="${WORK}/response.body"
HDRS="${WORK}/response.headers"

log() { echo "bootstrap: $*"; }
die() { log "ERROR: $*"; exit 1; }

# The kubelet restarts this container when it exits non-zero; that is the retry loop.
trap 'exit 0' TERM INT
rm -f "$READY"
: "${FABRO_DEV_TOKEN:?FABRO_DEV_TOKEN is not set (Secret fabro-server-env)}"
printf 'Authorization: Bearer %s\n' "$FABRO_DEV_TOKEN" > "$AUTH"

# api METHOD PATH [BODY_FILE] [IF_MATCH] -> sets STATUS (HTTP code; 000 = no response) and ETAG.
api() {
  method=$1; path=$2; body=${3:-}; ifmatch=${4:-}
  set -- -sS -o "$RESP" -D "$HDRS" -w '%{http_code}' --max-time 30 -X "$method" -H "@${AUTH}"
  [ -n "$body" ] && set -- "$@" -H 'Content-Type: application/json' --data-binary "@${body}"
  [ -n "$ifmatch" ] && set -- "$@" -H "If-Match: ${ifmatch}"
  STATUS=$(curl "$@" "${SERVER}${path}" 2>/dev/null) || STATUS=000
  ETAG=$(tr -d '\r' < "$HDRS" 2>/dev/null | sed -n 's/^[Ee][Tt][Aa][Gg]: *//p' | head -n 1)
}

# --- 1. wait for the server -------------------------------------------------------------------
log "waiting for ${SERVER}/health"
i=0
until curl -fsS -o /dev/null --max-time 3 "${SERVER}/health" 2>/dev/null; do
  i=$((i + 1))
  [ "$i" -le 150 ] || die "server not healthy after 5 minutes"
  sleep 2
done
log "server is healthy"

# --- 2. vault secrets --------------------------------------------------------------------------
# Each file in the seed dir is one vault secret: file name = secret name, content = value.
n=0
for f in "$SEED_DIR"/*; do
  [ -f "$f" ] || continue
  name=$(basename "$f")
  [ -s "$f" ] || die "vault seed ${name} is empty"
  if LC_ALL=C grep -q '[[:cntrl:]]' "$f" || [ "$(wc -l < "$f")" -ne 0 ]; then
    die "vault seed ${name} contains a newline or control character"
  fi
  # JSON-escape the only two characters that need it in a single-line value.
  value=$(sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' "$f")
  printf '{"name":"%s","value":"%s","type":"token"}' "$name" "$value" > "$BODY"
  unset value
  api POST /api/v1/secrets "$BODY"
  rm -f "$BODY" "$RESP"
  [ "$STATUS" = 200 ] || die "vault secret ${name}: store returned HTTP ${STATUS}"
  log "vault secret ${name}: set"
  n=$((n + 1))
done
[ "$n" -gt 0 ] || die "no vault seeds found in ${SEED_DIR}"

# --- 3. environments ---------------------------------------------------------------------------
# environment-<id>.json holds the definition WITHOUT its id (the API's replace shape); the id is
# the file name. Creating needs the id in the body, so it is spliced into the opening brace.
for f in "$CONF_DIR"/environment-*.json; do
  [ -f "$f" ] || continue
  id=$(basename "$f" .json); id=${id#environment-}
  [ "$(head -n 1 "$f")" = "{" ] || die "${f}: first line must be exactly '{'"

  api GET "/api/v1/environments/${id}"
  case "$STATUS" in
    200)
      [ -n "$ETAG" ] || die "environment ${id}: no ETag on GET"
      api PUT "/api/v1/environments/${id}" "$f" "$ETAG"
      [ "$STATUS" = 200 ] || die "environment ${id}: replace returned HTTP ${STATUS}"
      log "environment ${id}: replaced from Git"
      ;;
    404)
      sed "1s/^{\$/{\"id\": \"${id}\",/" "$f" > "$BODY"
      api POST /api/v1/environments "$BODY"
      [ "$STATUS" = 201 ] || die "environment ${id}: create returned HTTP ${STATUS}"
      log "environment ${id}: created"
      ;;
    *)
      die "environment ${id}: lookup returned HTTP ${STATUS}"
      ;;
  esac
done
rm -f "$BODY" "$RESP" "$HDRS"

# --- 4. done -----------------------------------------------------------------------------------
touch "$READY"
log "done; idling (re-runs on the next pod start)"
while :; do
  sleep 3600 &
  wait $!
done
