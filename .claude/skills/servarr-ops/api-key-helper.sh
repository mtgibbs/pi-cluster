#!/usr/bin/env bash
# Source this file: `source .claude/skills/servarr-ops/api-key-helper.sh`
#
# IMPORTANT: source under bash, not zsh. Reading positional args inside
# a sourced function under zsh can drop them silently. If you're in zsh,
# wrap calls as: `bash -c 'source ... && servarr_call ...'`
#
# Provides:
#   servarr_call <service> <method> <path> [curl-args...]
#     <service>  = sonarr | radarr | prowlarr | lidarr | bazarr | sabnzbd | jellyfin | jellyseerr
#     <method>   = GET | POST | PUT | DELETE
#     <path>     = path starting with /, e.g. /api/v3/queue
#
# Auth:
#   - Servarr stack reads API key from 1Password vault `pi-cluster`,
#     item `<service>.lab.mtgibbs.dev`, field `api-key`.
#   - SABnzbd's API takes ?apikey=<key> instead of a header.
#
# Example (bash):
#   source .claude/skills/servarr-ops/api-key-helper.sh
#   servarr_call radarr GET /api/v3/movie | jq '.[].title'
#
# Example (zsh — wrap in bash):
#   bash -c 'source .claude/skills/servarr-ops/api-key-helper.sh && \
#            servarr_call radarr GET /api/v3/movie' | jq '.[].title'

servarr_call() {
  if [ "$#" -lt 3 ]; then
    echo "usage: servarr_call <svc> <method> <path> [curl-args...]" >&2
    return 2
  fi
  svc="$1"; method="$2"; reqpath="$3"; shift 3
  host="${svc}.lab.mtgibbs.dev"

  key="$(op read "op://pi-cluster/${host}/api-key" 2>/dev/null)"
  if [ -z "$key" ]; then
    echo "servarr_call: failed to read API key for ${host} from 1Password" >&2
    return 1
  fi

  case "$svc" in
    sabnzbd)
      sep="?"; case "$reqpath" in *\?*) sep="&";; esac
      curl -sS --fail-with-body -X "$method" \
        "https://${host}${reqpath}${sep}apikey=${key}" "$@"
      ;;
    *)
      curl -sS --fail-with-body -X "$method" \
        -H "X-Api-Key: $key" \
        -H "Content-Type: application/json" \
        "https://${host}${reqpath}" "$@"
      ;;
  esac
}

# Convenience: dump the wanted-missing list for a service
servarr_wanted() {
  case "$1" in
    radarr)
      servarr_call radarr GET /api/v3/movie \
        | jq '[.[] | select(.monitored and (.hasFile|not))]'
      ;;
    sonarr)
      servarr_call sonarr GET '/api/v3/wanted/missing?pageSize=500&includeSeries=true'
      ;;
    *)
      echo "servarr_wanted: only sonarr|radarr supported, got '$1'" >&2
      return 2
      ;;
  esac
}
