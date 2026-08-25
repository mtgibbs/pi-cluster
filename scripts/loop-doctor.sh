#!/usr/bin/env bash
# loop-doctor.sh — read the harness's own telemetry and name the fault.
#
# Five telemetry channels already exist and each one works; nothing consumed them together, so
# the signals they carry were never read. Three failed attempts in the 2026-08-18 corpus had
# three DIFFERENT root causes — executor produced nothing, watchdog kill, and a missing
# gitignored config — each decidable from the first ~200 bytes of the transcript, and a human
# still had to cat five directories to tell them apart. All three are harness faults wearing a
# model-fault costume, which is why re-rolling never fixed them.
#
#   scripts/loop-doctor.sh                       one line per run, newest first
#   scripts/loop-doctor.sh --json                one object per run (spec §3.2 schema)
#   scripts/loop-doctor.sh --ledger runs.jsonl   append-only corpus that outlives the cull
#
# STRICTLY READ-ONLY (spec §8.1). It never runs a loop, never invokes a gate, never writes into
# a worktree, and never touches the network. It is meant to run INSIDE the harness it measures,
# so the reader must never invoke the measured — the same recursion hazard loop-report names.
#
# bash 3.2 (macOS ships it): no associative arrays, no `mapfile`, no `${x^^}`. The gate greps
# this file's raw text for the associative-array builtin, so naming it even in a comment trips
# the check — which is correct behaviour on its part, and worth leaving that way.
set -uo pipefail

STALE_S_DEFAULT=120     # the documented collector liveness rule (spec §6)
STILLBORN_B=512         # the literal the loop's own stillborn guard uses — not invented here
KILL_MARKER='Killed: 9'
PERM_MARKER='permission requested:'

usage() {
  cat >&2 <<'EOF'
usage: loop-doctor.sh [--status-dir DIR] [--log-dir DIR] [--json] [--ledger FILE]
                      [--now EPOCH] [--stale-s N]

  --status-dir DIR   heartbeat JSONs      (default: $RALPH_STATUS_DIR, else ~/.harness/status)
  --log-dir DIR      per-attempt logs     (default: $RALPH_LOG_DIR,    else ~/.harness/logs)
  --json             one JSON object per run instead of the human table
  --ledger FILE      append each row to FILE, one per line; idempotent by run_id
  --now EPOCH        inject the clock (staleness becomes deterministic under test)
  --stale-s N        seconds before a running heartbeat is called dead (default 120)

Exit: 0 ok · 1 usage/unreadable default · 2 an EXPLICITLY named directory is unreadable
EOF
}

SDIR=""; LDIR=""; SDIR_EXPLICIT=0; LDIR_EXPLICIT=0
JSON=0; LEDGER=""; NOW=""; STALE_S="$STALE_S_DEFAULT"

while [ $# -gt 0 ]; do
  case "$1" in
    --status-dir) SDIR="${2:-}"; SDIR_EXPLICIT=1; shift 2 ;;
    --log-dir)    LDIR="${2:-}"; LDIR_EXPLICIT=1; shift 2 ;;
    --json)       JSON=1; shift ;;
    --ledger)     LEDGER="${2:-}"; shift 2 ;;
    --now)        NOW="${2:-}"; shift 2 ;;
    --stale-s)    STALE_S="${2:-}"; shift 2 ;;
    -h|--help)    usage; exit 1 ;;
    *)            echo "loop-doctor: unrecognised argument '$1'" >&2; usage; exit 1 ;;
  esac
done

[ -n "$NOW" ] || NOW="$(date +%s 2>/dev/null || echo 0)"
[ -n "$SDIR" ] || SDIR="${RALPH_STATUS_DIR:-$HOME/.harness/status}"
[ -n "$LDIR" ] || LDIR="${RALPH_LOG_DIR:-$HOME/.harness/logs}"

# AC2b OUTRANKS AC2. An explicitly named directory that cannot be read is an operator error
# worth its own exit code (2); an unreadable DEFAULT just means "nothing to report here, and you
# probably meant to pass a flag" (1, with usage). The two overlap on the first case and only
# precedence decides — stating that is what this spec's own gate exists to pin down.
if [ "$SDIR_EXPLICIT" = 1 ] && [ ! -d "$SDIR" ]; then
  echo "loop-doctor: --status-dir '$SDIR' is not a readable directory" >&2; exit 2; fi
if [ "$LDIR_EXPLICIT" = 1 ] && [ ! -d "$LDIR" ]; then
  echo "loop-doctor: --log-dir '$LDIR' is not a readable directory" >&2; exit 2; fi
if [ ! -d "$SDIR" ] && [ ! -d "$LDIR" ]; then
  echo "loop-doctor: neither default directory is readable ($SDIR, $LDIR)" >&2; usage; exit 1; fi

command -v jq >/dev/null 2>&1 || { echo "loop-doctor: jq is required" >&2; exit 1; }

# Strip ANSI and cap length. Evidence names a MARKER; it never carries transcript payload —
# transcripts hold API keys and prompts, and a report that leaks them is a report you cannot
# paste into a ticket (spec §8, AC14).
clean() {
  printf '%s' "${1:-}" \
    | sed -e 's/'"$(printf '\033')"'\[[0-9;]*[a-zA-Z]//g' -e 's/[[:cntrl:]]//g' \
    | cut -c1-120
}

# Both layouts. The stores grew a per-spec level; before that they were flat, and an operator
# may point either flag at either shape. Search rather than assume — a reader that only
# understands today's layout goes blind on the corpus it was built to explain.
run_ids=""
if [ -d "$SDIR" ]; then
  for f in $(find "$SDIR" -type f -name '*.json' 2>/dev/null); do
    b="$(basename "$f" .json)"
    case "$b" in [a-z0-9]*-[0-9]*) run_ids="$run_ids $b" ;; esac
  done
fi
if [ -d "$LDIR" ]; then
  for d in $(find "$LDIR" -mindepth 1 -maxdepth 3 -type d 2>/dev/null); do
    b="$(basename "$d")"
    case "$b" in [a-z0-9]*-[0-9]*) run_ids="$run_ids $b" ;; esac
  done
fi
run_ids="$(printf '%s\n' $run_ids | sort -u)"

hb_path()  { find "$SDIR" -type f -name "$1.json" 2>/dev/null | head -1; }
log_path() { find "$LDIR" -mindepth 1 -maxdepth 3 -type d -name "$1" 2>/dev/null | head -1; }

rows=""
for rid in $run_ids; do
  [ -n "$rid" ] || continue
  hb="$(hb_path "$rid")"; ld="$(log_path "$rid")"
  unparsed=0

  # ---- heartbeat. A file that exists but will not parse STILL yields a row: run_id comes from
  # the FILENAME, which is readable independently of the contents. Counted, never fatal, never
  # hidden — telemetry drift must degrade the report, not silently blind it.
  agent=null; repo=null; spec=null; branch=null; phase=null
  ti=null; tt=null; att=null; maxa=null; vp=null; started=null; updated=null
  if [ -n "$hb" ] && [ -f "$hb" ]; then
    if jq -e . "$hb" >/dev/null 2>&1; then
      agent="$(jq -c '.agent//null'       "$hb")"; repo="$(jq -c '.repo//null'    "$hb")"
      spec="$(jq -c '.spec//null'         "$hb")"; branch="$(jq -c '.branch//null' "$hb")"
      phase="$(jq -c '.phase//null'       "$hb")"; ti="$(jq -c '.task_index//null' "$hb")"
      tt="$(jq -c '.total_tasks//null'    "$hb")"; att="$(jq -c '.attempt//null'   "$hb")"
      maxa="$(jq -c '.max_attempts//null' "$hb")"
      # `//` would turn a legitimate `false` into null. verify_pass has three meanings and
      # false is one of them: null = not yet verified, and it is NEVER the same as false.
      vp="$(jq -c 'if has("verify_pass") then .verify_pass else null end' "$hb")"
      started="$(jq -c '.started//null'   "$hb")"; updated="$(jq -c '.updated//null' "$hb")"
    else
      unparsed=$((unparsed + 1))
    fi
  fi
  [ "$agent" = "null" ] && agent="\"${rid%%-*}\""

  # ---- logs
  attempts=0; diffs=0; bytes_last=null; last_base=""; best=-1
  if [ -n "$ld" ] && [ -d "$ld" ]; then
    for p in "$ld"/*; do
      [ -f "$p" ] || continue
      b="$(basename "$p")"
      case "$b" in
        T*-attempt*.log)
          attempts=$((attempts + 1))
          t="${b#T}"; t="${t%%-*}"; a="${b#*-attempt}"; a="${a%.log}"
          case "$t$a" in *[!0-9]*) ;; *) k=$((t * 1000 + a))
            [ "$k" -gt "$best" ] && { best="$k"; last_base="${b%.log}"; } ;;
          esac ;;
        T*-attempt*.diff) diffs=$((diffs + 1)) ;;
        *) unparsed=$((unparsed + 1)) ;;
      esac
    done
    [ -n "$last_base" ] && bytes_last="$(wc -c < "$ld/$last_base.log" 2>/dev/null | tr -d ' ')"
    [ -n "${bytes_last:-}" ] || bytes_last=null
  fi

  # ---- derived clock
  duration=null; stale=null
  if [ "$started" != "null" ] && [ "$updated" != "null" ]; then duration=$((updated - started)); fi
  if [ "$updated" != "null" ]; then stale=$((NOW - updated)); fi

  # ---- classify. ORDER MATTERS and is the whole design: `dead` outranks every log-shape rule
  # because a killed loop cannot update its own file, so its last transcript is describing a
  # moment that has already passed. First match wins; nothing below is consulted after a hit.
  ph="$(printf '%s' "$phase" | tr -d '"')"
  fault=""; evidence=""
  lastlog=""; [ -n "$last_base" ] && lastlog="$ld/$last_base.log"

  if [ "$ph" = "running" ] || [ "$ph" = "verifying" ]; then
    if [ "$stale" != "null" ] && [ "$stale" -gt "$STALE_S" ]; then
      fault="dead"; evidence="heartbeat stale ${stale}s (phase=$ph)"
    else
      fault="running"; evidence="heartbeat fresh ${stale}s"
    fi
  elif [ "$ph" = "done" ]; then
    fault="done"; evidence="phase=done"
  fi

  if [ -z "$fault" ] && [ -n "$lastlog" ] && [ -f "$lastlog" ]; then
    m="$(grep -m1 -F "$KILL_MARKER" "$lastlog" 2>/dev/null)"
    if [ -n "$m" ]; then fault="watchdog-kill"; evidence="$(clean "$m")"; fi
  fi
  if [ -z "$fault" ] && [ -n "$lastlog" ] && [ -f "$lastlog" ] && [ ! -f "$ld/$last_base.diff" ]; then
    m="$(grep -m1 -F "$PERM_MARKER" "$lastlog" 2>/dev/null)"
    if [ -n "$m" ]; then fault="permission-blocked"; evidence="$(clean "$m")"; fi
  fi
  if [ -z "$fault" ] && [ "$bytes_last" != "null" ] && [ "$bytes_last" -lt "$STILLBORN_B" ]; then
    fault="executor-stillborn"; evidence="${bytes_last}B transcript, no kill marker"
  fi
  if [ -z "$fault" ] && [ -n "$last_base" ] && [ -f "$ld/$last_base.diff" ]; then
    fault="verify-fail"; evidence="$last_base.diff present"
  fi
  if [ -z "$fault" ] && [ "$bytes_last" != "null" ] && [ "$bytes_last" -ge "$STILLBORN_B" ] \
     && [ ! -f "$ld/$last_base.diff" ] && { [ "$ph" = "stopped" ] || [ "$ph" = "failed" ]; }; then
    fault="no-op"; evidence="log ${bytes_last}B, no .diff"
  fi
  if [ -z "$fault" ]; then
    # A classification that cannot cite is reported as unknown, never guessed — and it still
    # says what it looked for, so the gap is actionable rather than merely blank.
    fault="unknown"
    evidence="no rule matched (phase=${ph:-none}, logs=${attempts}, diffs=${diffs})"
  fi

  row="$(jq -nc \
    --arg rid "$rid" --argjson agent "$agent" --argjson repo "$repo" --argjson spec "$spec" \
    --argjson branch "$branch" --argjson ti "$ti" --argjson tt "$tt" --argjson att "$att" \
    --argjson maxa "$maxa" --argjson phase "$phase" --argjson vp "$vp" \
    --argjson started "$started" --argjson updated "$updated" --argjson duration "$duration" \
    --argjson stale "$stale" --arg fault "$fault" --arg ev "$evidence" \
    --argjson seen "$attempts" --argjson bl "$bytes_last" --argjson ds "$diffs" \
    --argjson up "$unparsed" \
    '{run_id:$rid,agent:$agent,repo:$repo,spec:$spec,branch:$branch,
      task_index:$ti,total_tasks:$tt,attempt:$att,max_attempts:$maxa,
      phase:$phase,verify_pass:$vp,started:$started,updated:$updated,
      duration_s:$duration,stale_s:$stale,fault:$fault,evidence:$ev,
      attempts_seen:$seen,bytes_last:$bl,diffs_seen:$ds,unparsed:$up}')"
  # Sort key: newest heartbeat first. A run with no heartbeat has nothing to sort BY, so it
  # sinks rather than being given a fabricated timestamp that would read as real.
  sk="$updated"; [ "$sk" = "null" ] && sk=0
  rows="$rows$sk	$row
"
done

ordered="$(printf '%s' "$rows" | grep -v '^$' | sort -rn -k1,1 | cut -f2-)"

if [ "$JSON" = 1 ]; then
  printf '%s\n' "$ordered" | grep -v '^$'
else
  printf '%s\n' "$ordered" | grep -v '^$' | while IFS= read -r r; do
    printf '%s\n' "$r" | jq -r '
      (if .unparsed > 0 then "  (unparsed: \(.unparsed))" else "" end) as $u |
      "\(.run_id)  \(.repo // "?")  \(.spec // "?")  phase=\(.phase // "none")  " +
      "fault=\(.fault)  \(.evidence)\($u)"'
  done
fi

# Append-only corpus. The artifact stores are culled on a timer, so without this no question of
# the form "is strategy A better than B" or "did this get worse after that change" can be asked
# at all. Idempotent by run_id: re-running a scan must not double-count history.
if [ -n "$LEDGER" ]; then
  touch "$LEDGER" 2>/dev/null || { echo "loop-doctor: cannot write ledger '$LEDGER'" >&2; exit 1; }
  printf '%s\n' "$ordered" | grep -v '^$' | while IFS= read -r r; do
    rid="$(printf '%s' "$r" | jq -r .run_id)"
    grep -q "\"run_id\":\"$rid\"" "$LEDGER" 2>/dev/null || printf '%s\n' "$r" >> "$LEDGER"
  done
fi

exit 0
