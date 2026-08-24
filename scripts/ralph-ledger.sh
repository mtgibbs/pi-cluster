#!/usr/bin/env bash
# ralph-ledger.sh — sidecar helper for task ledgering. SOURCED, not executed.
# Functions: ledger_dir, ledger_key, ledger_file, ledger_record, ledger_resume_index
# CLI: ledger_key | ledger_record <task> <commit> <attempt> <gate-output> | ledger_resume_index <tasks.txt> <gate-output> | forget <task>
set -uo pipefail

ledger_dir() {
  local dir
  dir="${RALPH_LEDGER_DIR:-${HOME:-/nonexistent}/.harness/ledger}"
  printf '%s' "$dir"
}

ledger_key() {
  local project slug
  project="$(git remote -v 2>/dev/null | awk '/^origin.*\(push\)/{gsub(/\.git$/,"",$2);print $2}' | head -1)"
  if [ -z "$project" ]; then
    project="$(git rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null)"
  fi
  if [ -z "$project" ]; then
    return 0
  fi
  project="$(printf '%s' "$project" | sed 's|[^a-zA-Z0-9_-]|-|g')"
  slug="$(printf '%s' "${SPEC_DIR:-specs}" | sed 's|^/||' | sed 's|/|-|g')"
  printf '%s' "${project}__${slug}"
}

ledger_file() {
  local key file
  key="$(ledger_key)" || return 0
  [ -n "$key" ] || return 0
  file="$(ledger_dir)/$key.tsv"
  printf '%s' "$file"
}

ledger_record() {
  local task commit attempt gate_output row checks
  task="$1"; commit="$2"; attempt="$3"; shift 3; gate_output="$*"
  checks="$(printf '%s\n' "$gate_output" | awk '{
    t=toupper($1)
    if(t=="PASS"||t=="OK")print $2
  }' | paste -sd ',' -)"
  [ -n "$checks" ] || return 0
  row="$(printf '%s\t%s\t%s\t%s\t%s\t%s' "$task" "$commit" "$attempt" "1" "1" "$checks")"
  local file dir tmp
  file="$(ledger_file)" || return 0
  dir="$(dirname "$file")"
  mkdir -p "$dir" 2>/dev/null || return 0
  tmp="$(mktemp)" 2>/dev/null || return 0
  [ -f "$file" ] && cat "$file" > "$tmp" 2>/dev/null
  printf '%s\n' "$row" >> "$tmp" 2>/dev/null || { rm -f "$tmp"; return 0; }
  mv "$tmp" "$file" 2>/dev/null || rm -f "$tmp"
  return 0
}

ledger_resume_index() {
  local tasks_file gate_output idx line task commit attempt status checks pass_names
  tasks_file="$1"; shift; gate_output="$*"
  local key file
  key="$(ledger_key)" || return 0
  file="$(ledger_dir)/$key.tsv" 2>/dev/null || return 0
  [ -f "$file" ] || { printf '%s' "0"; return 0; }
  idx=0
  while IFS='\t' read -r task commit attempt status checks pass_names; do
    idx=$((idx + 1))
    [ "$status" = "1" ] || continue
    if ! git merge-base --is-ancestor "$commit" HEAD 2>/dev/null; then
      printf '%s' "$idx"; return 0
    fi
    local current_passes
    current_passes="$(printf '%s\n' "$gate_output" | awk '{
      t=toupper($1); if(t=="PASS"||t=="OK")print $2
    }' | sort -u | tr '\n' ',' | sed 's/,$//')"
    [ "$checks" = "$current_passes" ] || { printf '%s' "$idx"; return 0; }
  done < "$file"
  printf '%s' "0"
}

ledger_cli() {
  local cmd
  cmd="${1:-}"; shift || true
  case "$cmd" in
    ledger_key) ledger_key ;;
    ledger_file) ledger_file ;;
    ledger_record)
      local task commit attempt gate_output
      task="$1"; shift || true
      commit="$1"; shift || true
      attempt="$1"; shift || true
      gate_output="$*"
      ledger_record "$task" "$commit" "$attempt" "$gate_output"
      ;;
    ledger_resume_index)
      local tasks_file gate_output
      tasks_file="$1"; shift || true
      gate_output="$*"
      ledger_resume_index "$tasks_file" "$gate_output"
      ;;
    forget)
      local task key file tmp
      task="$1"; shift || true
      key="$(ledger_key)" || return 0
      file="$(ledger_dir)/$key.tsv" 2>/dev/null || return 0
      [ -f "$file" ] || return 0
      tmp="$(mktemp)" 2>/dev/null || return 0
      awk -F'\t' -v t="$task" '$1!=t' "$file" > "$tmp" 2>/dev/null && mv "$tmp" "$file" 2>/dev/null
      rm -f "$tmp" 2>/dev/null
      ;;
    "")
       local key file
       key="$(ledger_key)" || return 0
       file="$(ledger_dir)/$key.tsv" 2>/dev/null || return 0
       [ -f "$file" ] || { printf '%s\n' "no ledger"; return 0; }
       awk -F'\t' '{printf "%s\n",$1}' "$file"
       ;;
     clear)
       local key file
       key="$(ledger_key)" || return 0
       file="$(ledger_dir)/$key.tsv" 2>/dev/null || return 0
       [ -f "$file" ] || return 0
       rm -f "$file" 2>/dev/null
       ;;
    *)
    printf '%s\n' "usage: $0 [ledger_key|ledger_file|ledger_record <task> <commit> <attempt> <gate-output>|ledger_resume_index <tasks.txt> <gate-output>|forget <task>|clear]" >&2
    exit 2
    ;;
  esac
  return 0
}

if [ "${0:-}" = "${BASH_SOURCE[0]:-}" ]; then
  ledger_cli "$@"
fi
