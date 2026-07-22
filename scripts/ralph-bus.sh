# shellcheck shell=bash
# ralph-bus.sh — best-effort Matrix bus narration for ralph loops. SOURCED, not executed.
#
# WHY THIS EXISTS: ralph-status.sh answers "what is this agent doing right now" as a LEVEL,
# read from a file. It cannot answer "who said what, when" — a discrete event with a sender
# and a moment. Those are different shapes of data and a file poll can't carry the second
# one: poll every second and two messages inside one tick become one, or none.
#
# The pulse dashboard needs the second shape. Today it draws bonds between agents from
# `bond = m.act * o.act` (harness-console/index.html) — two agents both being busy at the
# same time. That LOOKS like communication without being any of it. This emits the real
# thing, so the bonds can eventually be drawn from messages that actually happened.
#
# Contract — posts to #tasks, one thread per loop. Root message is "task: <slug>" per the
# convention in docs/agent-bus.md; its event id is the correlation key every later post in
# the loop replies to. Transitions ONLY — start, task passed, stopped, done. Deliberately
# NOT per attempt: a loop retrying three times on four tasks would otherwise put a dozen
# near-identical lines in the room, and a channel nobody can skim is a channel nobody reads.
#
# BEST-EFFORT, same discipline as ralph-status.sh: every call is guarded and time-bounded.
# A down homeserver, an expired token, a missing CLI, or no jq can never fail the loop or
# stall it for more than AB_MAX_TIME. The loop is the product; this is commentary on it.
#
#   RALPH_BUS=off        disable entirely
#   RALPH_BUS_ROOM=...   default: tasks

RALPH_BUS_ROOM="${RALPH_BUS_ROOM:-tasks}"

# bus_init — call once, after hb_init (it reuses HB_* for context).
bus_init() {
  BUS_OK=0; BUS_THREAD=""
  local why=""
  if [ "${RALPH_BUS:-on}" != "on" ]; then why="RALPH_BUS=off"; else
    # Find the CLI. Do NOT trust BASH_SOURCE alone: sourced through a relative path it can
    # yield a bare filename, dirname collapses to ".", and you get "./agent-bus" — which
    # doesn't exist, so narration silently never posts. That failure mode is invisible
    # (this whole file is designed not to complain), so it would have looked like "the
    # dashboard just doesn't move." Found exactly that way in testing. ROOT is set by every
    # ralph loop and is the dependable anchor; the others are fallbacks.
    local c
    for c in "${RALPH_BUS_CLI:-}" \
             "$(dirname "${BASH_SOURCE[0]:-$0}")/agent-bus" \
             "${ROOT:-}/scripts/agent-bus" \
             "$(command -v agent-bus 2>/dev/null)"; do
      [ -n "$c" ] && [ -x "$c" ] && { BUS_CLI="$c"; break; }
    done
    if   [ -z "${BUS_CLI:-}" ];                then why="agent-bus CLI not found"
    elif ! command -v jq >/dev/null 2>&1;      then why="jq missing"
    # No credential at all → every post would be a slow failing no-op. Check once here
    # rather than eating a timeout per transition. MATRIX_TOKEN is how the harness
    # containers get it (beelink-ansible 50-ai-stack.yml); AGENT_BUS_IDENTITY covers the
    # laptop, where the CLI falls back to Keychain/1Password.
    elif [ -z "${MATRIX_TOKEN:-}" ] && [ -z "${AGENT_BUS_IDENTITY:-}" ]; then why="no MATRIX_TOKEN / AGENT_BUS_IDENTITY"
    else BUS_OK=1; fi
  fi
  # One line, once. Silent failure is the right behaviour for a POST mid-loop; silent
  # never-started is not — that's how you end up staring at a still dashboard.
  [ "$BUS_OK" = 1 ] && echo "bus: narrating to #${RALPH_BUS_ROOM} as ${AGENT_BUS_IDENTITY:-\$MATRIX_TOKEN}" >&2 \
                    || echo "bus: narration off ($why)" >&2
  return 0
}

# _bus_post <text> [--thread <id>] — prints the new event id, or nothing. Never fails.
_bus_post() {
  [ "${BUS_OK:-0}" = 1 ] || return 0
  local out
  out="$(AB_MAX_TIME="${RALPH_BUS_TIMEOUT:-10}" "$BUS_CLI" post "$RALPH_BUS_ROOM" "$@" 2>/dev/null)" || return 0
  printf '%s' "${out#posted: }"
}

# bus_open [slug] — start the loop's thread. Everything after this replies into it.
bus_open() {
  [ "${BUS_OK:-0}" = 1 ] || return 0
  local slug="${1:-${HB_SPEC:-run}}" branch
  # ralph-status.sh recomputes the branch inside hb_write and never exports it, so read it
  # here rather than referencing an HB_BRANCH that doesn't exist.
  branch="$(git -C "${HB_ROOT:-${ROOT:-.}}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
  BUS_THREAD="$(_bus_post "task: ${slug} — ${HB_AGENT:-${RALPH_AGENT:-agent}} starting ${HB_TOTAL:-?} task(s) in ${HB_REPO:-?} on ${branch}")"
}

# bus_say <text> — one line into the loop's thread (falls back to the room if the root
# post didn't land, so a transient failure at start doesn't mute the whole run).
bus_say() {
  [ "${BUS_OK:-0}" = 1 ] || return 0
  if [ -n "${BUS_THREAD:-}" ]; then
    _bus_post "$1" --thread "$BUS_THREAD" >/dev/null
  else
    _bus_post "$1" >/dev/null
  fi
}
