#!/usr/bin/env bash
# diagnose-orphans.sh — deterministic safe/unsafe verdict for orphaned SABnzbd
# download folders. READ-ONLY. Never deletes anything, never calls a mutating
# API. Built + tested live 2026-07-11 against 45 real orphaned folders (17 from
# SABnzbd's own "Orphaned jobs" tab in /downloads/incomplete/, plus ~28 stale
# _UNPACK_/_FAILED_ dirs the orphan-sweep CronJob's age-based scan also covers
# in /downloads/complete/usenet/) — 45/45 resolved, 0 ambiguous.
#
# Why this exists: SABnzbd's own "orphaned jobs" UI just means "I don't
# recognize this folder in my own queue/history" — it says NOTHING about
# whether the content is safe to delete. Radarr/Sonarr use hardlinks
# (`copyUsingHardlinks: true` — verify per-instance via
# `servarr_call radarr GET /api/v3/config/mediamanagement`), so an
# already-imported release's orphan folder and its library copy may share an
# inode — but folders that were NEVER the source of a successful import don't
# have that safety net, and naive age/name-based heuristics can't tell the
# difference. This script cross-references Radarr/Sonarr's own history +
# current hasFile state — the source of truth — instead of guessing from the
# folder name alone.
#
# Usage:
#   bash .claude/skills/servarr-ops/diagnose-orphans.sh < folder-names.txt
# (one folder name per line, e.g. from `kubectl exec -n media
# deployment/sabnzbd -- sh -c 'ls -1 /downloads/incomplete/;
# ls -1 /downloads/complete/usenet/'` — ignore the "books" entry, that's
# LazyLibrarian's category, not a *arr download)
#
# Requires: `servarr_call` (source api-key-helper.sh first — sibling file),
# `jq`. On first run, fetches + caches Radarr/Sonarr history+library state to
# /tmp/*.json (re-run with a fresh /tmp if the library has changed since).
#
# NOT currently runnable by the `oc ops` local-model agent: it needs
# kubectl (to enumerate folders — no MCP equivalent for listing NFS download
# dir contents) and Radarr/Sonarr's raw REST API (history/movie/episode
# endpoints — the mcp-homelab tools ops.md has access to only expose
# queue/history summaries, not this level of cross-referencing). This is a
# Claude/cluster-ops-tier diagnostic for now; revisit if mcp-homelab grows
# the right primitives.
#
# Verdict categories (leftmost column):
#   SAFE (radarr)   — matched a Radarr history record (any event type) by exact
#                      sourceTitle; either this release WAS imported at some
#                      point (dup/stale leftover), or the movie has hasFile=true
#                      via a DIFFERENT release (superseded grab).
#   SAFE (sonarr)    — same, via Sonarr history + per-episode hasFile.
#   SAFE (sonarr*)   — no history record at all (grabbed outside Sonarr's own
#                      tracking — seen with old/manually-added NZBs), but the
#                      season/episode number was parsed directly from the
#                      folder name and that specific episode independently
#                      confirms hasFile=true.
#   DO-NOT-TOUCH     — no confirmed import AND hasFile=false. This folder may
#                      be the only copy. Needs a human, full stop.
#   AMBIGUOUS        — couldn't resolve via any path above. Needs a human.
#
# The actual deletion is deliberately NOT part of this script — verdicts here
# inform a human decision (SABnzbd's own "delete (including files)" button),
# they don't trigger one.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RADARR_HIST=/tmp/radarr-hist.json
SONARR_HIST=/tmp/sonarr-hist.json
RADARR_MOVIES=/tmp/radarr-movies.json
SONARR_SERIES=/tmp/sonarr-series.json

fetch_if_missing() {
  local file="$1" svc="$2" path="$3"
  [ -f "$file" ] && return 0
  bash -c "source '$HERE/api-key-helper.sh' && servarr_call '$svc' GET '$path'" > "$file" 2>/dev/null \
    || { echo "diagnose-orphans: failed to fetch $svc $path" >&2; echo "{}" > "$file"; }
}

fetch_if_missing "$RADARR_HIST" radarr "/api/v3/history?pageSize=5000"
fetch_if_missing "$SONARR_HIST" sonarr "/api/v3/history?pageSize=5000"
fetch_if_missing "$RADARR_MOVIES" radarr "/api/v3/movie"
fetch_if_missing "$SONARR_SERIES" sonarr "/api/v3/series"

verdict_one() {
  raw="$1"
  clean=$(echo "$raw" | sed -E 's/^_UNPACK_//; s/^_FAILED_//; s/\.[0-9]+$//')

  # Try Radarr match first — ANY event type (grabbed, downloadFailed, etc.), not just "grabbed"
  r=$(jq --arg t "$clean" '[.records[] | select(.sourceTitle == $t)] | .[0]' "$RADARR_HIST")
  if [ "$r" != "null" ]; then
    dlid=$(echo "$r" | jq -r '.downloadId')
    movieId=$(echo "$r" | jq -r '.movieId')
    imported=$(jq --arg d "$dlid" '[.records[] | select(.downloadId == $d and .eventType == "downloadFolderImported")] | length > 0' "$RADARR_HIST")
    hasFile=$(jq --arg id "$movieId" '.[] | select(.id == ($id|tonumber)) | .hasFile' "$RADARR_MOVIES")
    title=$(jq --arg id "$movieId" '.[] | select(.id == ($id|tonumber)) | .title' "$RADARR_MOVIES")
    if [ "$imported" = "true" ]; then
      echo "SAFE (radarr)   | $raw | this exact release WAS imported at some point ($title) — dup or stale post-import leftover"
    elif [ "$hasFile" = "true" ]; then
      echo "SAFE (radarr)   | $raw | never imported, but $title has a confirmed different working file — superseded grab"
    else
      echo "DO-NOT-TOUCH    | $raw | never imported, $title hasFile=false — may be the only copy, needs a human"
    fi
    return
  fi

  # Try Sonarr match — ANY event type
  r=$(jq --arg t "$clean" '[.records[] | select(.sourceTitle == $t)] | .[0]' "$SONARR_HIST")
  if [ "$r" != "null" ]; then
    dlid=$(echo "$r" | jq -r '.downloadId')
    epId=$(echo "$r" | jq -r '.episodeId')
    seriesId=$(echo "$r" | jq -r '.seriesId')
    imported=$(jq --arg d "$dlid" '[.records[] | select(.downloadId == $d and .eventType == "downloadFolderImported")] | length > 0' "$SONARR_HIST")
    epfile="/tmp/sonarr-ep-${seriesId}.json"
    fetch_if_missing "$epfile" sonarr "/api/v3/episode?seriesId=${seriesId}"
    hasFile=$(jq --arg id "$epId" '.[] | select(.id == ($id|tonumber)) | .hasFile' "$epfile")
    epTitle=$(jq --arg id "$epId" '.[] | select(.id == ($id|tonumber)) | "S\(.seasonNumber)E\(.episodeNumber) \(.title)"' "$epfile")
    if [ "$imported" = "true" ]; then
      echo "SAFE (sonarr)   | $raw | this exact release WAS imported at some point ($epTitle) — dup or stale post-import leftover"
    elif [ "$hasFile" = "true" ]; then
      echo "SAFE (sonarr)   | $raw | never imported, but $epTitle has a confirmed different working file — superseded grab"
    elif [ "$hasFile" = "false" ]; then
      echo "DO-NOT-TOUCH    | $raw | never imported, $epTitle hasFile=false — may be the only copy, needs a human"
    else
      echo "AMBIGUOUS       | $raw | matched a Sonarr record but couldn't resolve episode hasFile ($epTitle) — needs a human"
    fi
    return
  fi

  # Fallback: no history record at all (grabbed outside Sonarr's own tracking —
  # seen for real with older/manually-added NZBs). Parse SxxEyy directly from
  # the name and check that specific episode's hasFile — doesn't need history,
  # just a season/episode number and a series title match.
  se=$(echo "$clean" | grep -oE 'S[0-9]{2}E[0-9]{2}' | head -1)
  if [ -n "$se" ]; then
    season=$((10#$(echo "$se" | sed -E 's/S([0-9]{2})E.*/\1/')))
    episode=$((10#$(echo "$se" | sed -E 's/S[0-9]{2}E([0-9]{2})/\1/')))
    prefix=$(echo "$clean" | sed -E "s/\.?${se}.*//" | tr '.' ' ')
    # Normalize to alphanumeric-only before comparing — series titles often
    # carry punctuation (colons, etc.) that folder names never do.
    seriesId=$(jq -r --arg p "$prefix" '
      ($p | ascii_downcase | gsub("[^a-z0-9]"; "")) as $pc |
      [.[] | select(.title as $t | ($t | ascii_downcase | gsub("[^a-z0-9]"; "")) as $tc | ($pc | contains($tc)) or ($tc | contains($pc)))] | .[0].id // empty
    ' "$SONARR_SERIES")
    if [ -n "$seriesId" ]; then
      epfile="/tmp/sonarr-ep-${seriesId}.json"
      fetch_if_missing "$epfile" sonarr "/api/v3/episode?seriesId=${seriesId}"
      seriesTitle=$(jq -r --arg id "$seriesId" '.[] | select(.id == ($id|tonumber)) | .title' "$SONARR_SERIES")
      hasFile=$(jq --arg s "$season" --arg e "$episode" '.[] | select(.seasonNumber == ($s|tonumber) and .episodeNumber == ($e|tonumber)) | .hasFile' "$epfile")
      if [ "$hasFile" = "true" ]; then
        echo "SAFE (sonarr*)  | $raw | no history record, but $seriesTitle S${season}E${episode} confirmed hasFile=true by direct lookup — safe"
      elif [ "$hasFile" = "false" ]; then
        echo "DO-NOT-TOUCH    | $raw | no history record, $seriesTitle S${season}E${episode} hasFile=false — may be the only copy, needs a human"
      else
        echo "AMBIGUOUS       | $raw | parsed $seriesTitle S${season}E${episode} but couldn't resolve hasFile — needs a human"
      fi
      return
    fi
  fi

  echo "AMBIGUOUS       | $raw | no matching history record AND couldn't resolve a series/episode directly — needs a human"
}

while IFS= read -r line; do
  [ -z "$line" ] && continue
  [ "$line" = "books" ] && continue
  verdict_one "$line"
done
