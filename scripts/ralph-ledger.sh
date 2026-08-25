# shellcheck shell=bash
# ralph-ledger.sh — track completed tasks across runs. SOURCED or CLI.
#
# WHY: the loop cannot remember what tasks already passed; every run rebuilds the whole queue.
# This helper appends one line per completed task to a sidecar ledger, and supports skipping
# leading tasks that prove they are still green (ancestry + verdict).
#
# Writes, per spec, to ${RALPH_LEDGER_DIR:-$HOME/.harness/ledger}/$(ledger_key).tsv:
#   task-label<TAB>commit<TAB>epoch<TAB>attempt<TAB>n_pass<TAB>comma,separated,pass-names
#
# Best-effort contract: an unwritable dir or missing file never fails the loop. All functions
# return 0 and print nothing on stderr. If the ledger is unavailable, no task is skipped.

ledger_dir() {
  printf '%s\n' "${RALPH_LEDGER_DIR:-$HOME/.harness/ledger}"
}

ledger_key() {
  local project slug toplevel
  project="$(git config --get remote.origin.url 2>/dev/null)"
  if [ -n "$project" ]; then
    project="$(basename "$project")"
    project="${project%.git}"
  else
    toplevel="$(git rev-parse --show-toplevel 2>/dev/null)"
    if [ -n "$toplevel" ]; then
      project="$(basename "$toplevel")"
    else
      project="unknown"
    fi
  fi
  slug="${SPEC_DIR%/}"
  slug="${slug//\//-}"
  printf '%s__%s\n' "$project" "$slug"
}

ledger_file() {
  local dir key
  dir="$(ledger_dir)"
  key="$(ledger_key)"
  printf '%s/%s.tsv\n' "$dir" "$key"
}

ledger_record() {
  local task_label commit attempt gate_output dir file line verdict name pass_names n_pass
  task_label="$1"
  commit="$2"
  attempt="$3"
  gate_output="$4"

  dir="$(ledger_dir)"
  file="$(ledger_file)"

  : > /dev/null 2>&1 || true

  mkdir -p "$dir" 2>/dev/null || return 0

  n_pass=0
  pass_names=""

  while IFS= read -r line; do
    verdict="$(printf '%s' "$line" | awk '{ t=toupper($1); if(t=="PASS"||t=="OK")print"PASS";else if(t=="FAIL")print"FAIL";else if(t=="PEND"||t=="PENDING")print"PEND";else print"" }')"
    [ "$verdict" = "PASS" ] || continue
    name="$(printf '%s' "$line" | awk '{ print $2 }')"
    [ -n "$name" ] || continue
    if [ -z "$pass_names" ]; then
      pass_names="$name"
    else
      pass_names="$pass_names,$name"
    fi
    n_pass=$((n_pass + 1))
  done <<EOF
$gate_output
EOF

  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$task_label" "$commit" "$(date +%s)" "$attempt" "$n_pass" "$pass_names" >> "$file" 2>/dev/null || return 0
  return 0
}

ledger_resume_index() {
  local tasks_file gate_file ledger_path line label commit epoch attempt n_pass pass_names
  local row_label row_commit row_pass_names row_n_pass i count found
  tasks_file="$1"
  gate_file="$2"

  ledger_path="$(ledger_file)"

  [ -f "$tasks_file" ] 2>/dev/null || { printf '0\n'; return 0; }
  [ -f "$ledger_path" ] 2>/dev/null || { printf '0\n'; return 0; }
  [ -r "$ledger_path" ] 2>/dev/null || { printf '0\n'; return 0; }
  [ -w "$ledger_path" ] 2>/dev/null || { printf '0\n'; return 0; }

  count=0
  while IFS= read -r line || [ -n "$line" ]; do
    label="${line%%:*}"

    [ -n "$label" ] || { printf '0\n'; return 0; }

    found=""
    while IFS= read -r row_line; do
      row_label="$(printf '%s' "$row_line" | awk -F'\t' '{ print $1 }')"
      [ "$row_label" = "$label" ] || continue
      commit="$(printf '%s' "$row_line" | awk -F'\t' '{ print $2 }')"
      epoch="$(printf '%s' "$row_line" | awk -F'\t' '{ print $3 }')"
      attempt="$(printf '%s' "$row_line" | awk -F'\t' '{ print $4 }')"
      n_pass="$(printf '%s' "$row_line" | awk -F'\t' '{ print $5 }')"
      pass_names="$(printf '%s' "$row_line" | awk -F'\t' '{ print $6 }')"

      found=1
      break
    done < "$ledger_path"

    [ -n "$found" ] || { printf '0\n'; return 0; }

    git merge-base --is-ancestor "$commit" HEAD 2>/dev/null || { printf '0\n'; return 0; }

    if [ -n "$pass_names" ]; then
      i=1
      while [ -n "$pass_names" ]; do
        row_commit="$(printf '%s' "$pass_names" | awk -F',' '{ print $1 }')"
        pass_names="$(printf '%s' "$pass_names" | awk -F',' '{ $1=""; print substr($0,2) }')"

        [ -n "$row_commit" ] || continue

        if ! grep -qE "^[[:space:]]*(PASS|ok)[[:space:]]+${row_commit}[[:space:]]" "$gate_file" 2>/dev/null; then
          printf '0\n'
          return 0
        fi
      done
    fi

    count=$((count + 1))
  done < "$tasks_file"

  printf '%s\n' "$count"
  return 0
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  case "${1:-list}" in
    list)
      file="$(ledger_file)"
      if [ -f "$file" ] && [ -r "$file" ]; then
        cat "$file"
      else
        printf 'No ledger yet.\n'
      fi
      exit 0
      ;;
    forget)
      if [ -z "${2:-}" ]; then
        printf 'Usage: ralph-ledger.sh forget <task-label>\n' >&2
        exit 1
      fi
      task="$2"
      file="$(ledger_file)"
      if [ -f "$file" ] && [ -r "$file" ] && [ -w "$file" ]; then
        tmpfile="$(mktemp 2>/dev/null)"
        if [ -n "$tmpfile" ]; then
          grep -v "^${task}	" "$file" > "$tmpfile" 2>/dev/null || true
          mv "$tmpfile" "$file" 2>/dev/null || rm -f "$tmpfile"
        fi
      fi
      exit 0
      ;;
    clear)
      file="$(ledger_file)"
      if [ -f "$file" ] && [ -w "$file" ]; then
        : > "$file" 2>/dev/null || true
      fi
      exit 0
      ;;
    *)
      printf 'Usage: ralph-ledger.sh [list|forget <task>|clear]\n' >&2
      exit 1
      ;;
  esac
fi

return 0
