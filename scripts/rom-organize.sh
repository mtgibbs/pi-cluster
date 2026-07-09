#!/usr/bin/env bash
# rom-organize.sh — file ROM dumps into the library layout.
#
# Usage:
#   scripts/rom-organize.sh --platform <slug> --source <dir> --library <dir> [--dry-run]
#
# See docs/rom-library-structure.md for the library folder layout and platform slugs.
set -uo pipefail

# Supported slugs (exact match required; duplicates for aliases are not allowed)
SUPPORTED_SLUGS="nes snes n64 gb gbc gba nds genesis psx ps2 ngc wii"

usage(){ cat <<EOF
Usage: $(basename "$0") --platform <slug> --source <dir> --library <dir> [--dry-run]

Options:
  --platform <slug>   One of: $SUPPORTED_SLUGS
  --source <dir>      Flat directory of freshly dumped files (no recursion)
  --library <dir>     Library root (contains/will contain roms/ and bios/)
  --dry-run           Print what would happen; move nothing

Exit codes:
  0  Clean (no skips)
  1  Bad invocation (unknown option/slug, missing dirs)
  2  Completed but ≥1 file skipped
EOF
}

# --- argument parsing ---
platform=""; source_dir=""; library_dir=""; dry_run=0

while [ $# -gt 0 ]; do
  case "$1" in
    --platform) platform="$2"; shift 2 ;;
    --source) source_dir="$2"; shift 2 ;;
    --library) library_dir="$2"; shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
  esac
done

# --- validation ---
[ -n "$platform" ] || { echo "Missing --platform" >&2; usage >&2; exit 1; }
[ -n "$source_dir" ] || { echo "Missing --source" >&2; usage >&2; exit 1; }
[ -n "$library_dir" ] || { echo "Missing --library" >&2; usage >&2; exit 1; }

found=0
for s in $SUPPORTED_SLUGS; do [ "$platform" = "$s" ] && found=1; done
[ "$found" = "1" ] || { echo "Unknown platform slug: $platform" >&2; echo "Supported: $SUPPORTED_SLUGS" >&2; exit 1; }

[ -d "$source_dir" ] || { echo "Source dir does not exist: $source_dir" >&2; exit 1; }
[ -d "$library_dir" ] || { echo "Library dir does not exist: $library_dir" >&2; exit 1; }

# --- platform-specific allowed extensions ---
case "$platform" in
  nes) ALLOWED_EXTS="nes" ;;
  snes) ALLOWED_EXTS="sfc smc" ;;
  n64) ALLOWED_EXTS="z64 n64 v64" ;;
  gb) ALLOWED_EXTS="gb" ;;
  gbc) ALLOWED_EXTS="gbc" ;;
  gba) ALLOWED_EXTS="gba" ;;
  nds) ALLOWED_EXTS="nds" ;;
  genesis) ALLOWED_EXTS="md gen bin" ;;
  psx) ALLOWED_EXTS="cue bin chd" ;;
  ps2) ALLOWED_EXTS="iso chd" ;;
  ngc) ALLOWED_EXTS="rvz iso" ;;
  wii) ALLOWED_EXTS="rvz iso wbfs" ;;
esac

# --- sanitization function ---
sanitize_name(){
  local name="$1"
  # Replace _ with space
  name="${name//_/ }"
  # Delete : * ? " < > | \ and keep space
  name="${name//[:*?\"<>|\\]/}"
  # Lowercase extension only (before space collapse)
  local base="${name%.*}"
  local ext="${name##*.}"
  if [ "$base" = "$ext" ]; then
    # No extension
    :
  else
    ext="$(echo "$ext" | tr '[:upper:]' '[:lower:]')"
    name="$base.$ext"
  fi
  # Collapse runs of spaces to single space
  name="$(echo "$name" | tr -s ' ')"
  # Trim leading/trailing spaces
  name="$(echo "$name" | sed 's/^ *//;s/ *$//')"
  echo "$name"
}

# --- platform extension check ---
is_allowed_ext(){
  local file="$1"
  local ext="${file##*.}"
  ext="$(echo "$ext" | tr '[:upper:]' '[:lower:]')"
  for e in $ALLOWED_EXTS; do [ "$ext" = "$e" ] && return 0; done
  return 1
}

# --- platform extension check (inline helper for early skip) ---
check_allowed(){
  local file="$1"
  local ext="${file##*.}"
  ext="$(echo "$ext" | tr '[:upper:]' '[:lower:]')"
  case "$platform" in
    nes) [ "$ext" = "nes" ] && return 0 ;;
    snes) case "$ext" in sfc|smc) return 0 ;; esac ;;
    n64) case "$ext" in z64|n64|v64) return 0 ;; esac ;;
    gb) [ "$ext" = "gb" ] && return 0 ;;
    gbc) [ "$ext" = "gbc" ] && return 0 ;;
    gba) [ "$ext" = "gba" ] && return 0 ;;
    nds) [ "$ext" = "nds" ] && return 0 ;;
    genesis) case "$ext" in md|gen|bin) return 0 ;; esac ;;
    psx) case "$ext" in cue|bin|chd) return 0 ;; esac ;;
    ps2) case "$ext" in iso|chd) return 0 ;; esac ;;
    ngc) case "$ext" in rvz|iso) return 0 ;; esac ;;
    wii) case "$ext" in rvz|iso|wbfs) return 0 ;; esac ;;
  esac
  return 1
}

# --- psx cue parsing: extract bin refs ---
parse_cue_bins(){
  local cue_file="$1"
  # One bin per LINE — bin names contain spaces, so a space-joined list is
  # ambiguous and word-splitting it mangles every multi-word filename.
  local bins=""
  while IFS= read -r line || [ -n "$line" ]; do
    if [[ "$line" =~ FILE[[:space:]]+\"([^\"]+)\" ]]; then
      bins="$bins${BASH_REMATCH[1]}"$'\n'
    fi
  done < "$cue_file"
  printf '%s' "$bins"
}

# --- psx cue disc-tag strip for folder name ---
strip_disc_tag(){
  local name="$1"
  # Remove trailing (Disc N) or (Disc N of M) before extension
  echo "$name" | sed -E 's/[(]Disc[[:space:]]+[0-9]+[[:space:]]*(of[[:space:]]+[0-9]+)?[)]$//'
}

# --- counters ---
moved=0
planned=0
skipped=0

# --- track cue->bins for psx (to catch orphan bins) ---
declare -A cue_bins_map

if [ "$platform" = "psx" ]; then
  for cue in "$source_dir"/*.cue; do
    [ -f "$cue" ] || continue
    cue_name="$(basename "$cue")"
    cue_bins_map["$cue_name"]="$(parse_cue_bins "$cue")"
  done
fi

# --- main loop ---
for src in "$source_dir"/*; do
  [ -f "$src" ] || continue
  src_name="$(basename "$src")"
  src_ext="${src_name##*.}"

  # Extension check (case-insensitive)
  src_ext_lower="$(echo "$src_ext" | tr '[:upper:]' '[:lower:]')"
  allowed=0
  for e in $ALLOWED_EXTS; do [ "$src_ext_lower" = "$e" ] && allowed=1; done

  if [ "$allowed" = "0" ]; then
    echo "SKIPPED: $src_name (bad-extension)"
    skipped=$((skipped + 1))
    continue
  fi

  # PS1 cue handling
  if [ "$platform" = "psx" ] && [ "$src_ext_lower" = "cue" ]; then
    bins_ref="${cue_bins_map[$src_name]:-}"
    if [ -z "$bins_ref" ]; then
      echo "SKIPPED: $src_name (missing-bin)"
      skipped=$((skipped + 1))
      continue
    fi

    missing_bin=0
    while IFS= read -r b; do
      [ -z "$b" ] && continue
      if [ ! -f "$source_dir/$b" ]; then
        missing_bin=1
        break
      fi
    done <<< "$bins_ref"

    if [ "$missing_bin" = "1" ]; then
      echo "SKIPPED: $src_name (missing-bin)"
      skipped=$((skipped + 1))
      continue
    fi

    # Folder name = cue TITLE (extension dropped) sanitized, disc tag stripped.
    # strip_disc_tag is end-anchored, so the .cue must come off first; strip
    # the tag before the space-trim so no trailing gap is left behind.
    folder_name="$(sanitize_name "$src_name")"
    folder_name="$(strip_disc_tag "${folder_name%.cue}")"
    folder_name="$(echo "$folder_name" | sed 's/ *$//')"
    dest_dir="$library_dir/roms/$platform/$folder_name"

    if [ "$dry_run" = "1" ]; then
      echo "PLANNED: $src -> $dest_dir/"
      while IFS= read -r b; do
        [ -z "$b" ] && continue
        echo "PLANNED: $source_dir/$b -> $dest_dir/$b"
        planned=$((planned + 1))
      done <<< "$bins_ref"
      planned=$((planned + 1))
    else
      mkdir -p "$dest_dir"
      while IFS= read -r b; do
        [ -z "$b" ] && continue
        dest="$dest_dir/$b"
        if [ -e "$dest" ]; then
          echo "SKIPPED: $b (exists)"
          skipped=$((skipped + 1))
        else
          mv "$source_dir/$b" "$dest"
          echo "MOVED: $source_dir/$b -> $dest"
          moved=$((moved + 1))
        fi
      done <<< "$bins_ref"
      dest_cue="$dest_dir/$src_name"
      if [ -e "$dest_cue" ]; then
        echo "SKIPPED: $src_name (exists)"
        skipped=$((skipped + 1))
      else
        mv "$src" "$dest_cue"
        echo "MOVED: $src -> $dest_cue"
        moved=$((moved + 1))
      fi
    fi
    continue
  fi

  # Loose single-file move. On cue/bin platforms a .bin NEVER moves alone —
  # cue processing above moves referenced bins; leftovers are judged by the
  # orphan-bin check at the end.
  if [ "$platform" = "psx" ]; then
    case "$src_name" in *.bin) continue ;; esac
  fi
  dest_name="$(sanitize_name "$src_name")"
  dest="$library_dir/roms/$platform/$dest_name"

  if [ -e "$dest" ]; then
    echo "SKIPPED: $src_name (exists)"
    skipped=$((skipped + 1))
    continue
  fi

  if [ "$dry_run" = "1" ]; then
    echo "PLANNED: $src -> $dest"
    planned=$((planned + 1))
  else
    mkdir -p "$(dirname "$dest")"
    mv "$src" "$dest"
    echo "MOVED: $src -> $dest"
    moved=$((moved + 1))
  fi
done

# PSX orphan bin check - look for .bin/.chd that weren't moved by cue processing
# Note: cue processing already moved the bins that belong to cues, so we only need to check what's left
if [ "$platform" = "psx" ]; then
  for bin in "$source_dir"/*.bin "$source_dir"/*.chd; do
    [ -f "$bin" ] || continue
    bin_name="$(basename "$bin")"
    # Check if this bin was referenced in any cue (and thus already processed/moved)
    # We check the source dir - if file still exists and wasn't in cue_bins_map, it's orphan
    found_cue=0
    for cue in "${!cue_bins_map[@]}"; do
      if printf '%s' "${cue_bins_map[$cue]}" | grep -qxF "$bin_name"; then
        found_cue=1
        break
      fi
    done
    if [ "$found_cue" = "0" ]; then
      if [ "$dry_run" = "1" ]; then
        echo "PLANNED: $bin_name -> (orphan-bin)"
      else
        echo "SKIPPED: $bin_name (orphan-bin)"
        skipped=$((skipped + 1))
      fi
    fi
  done
fi

 echo "SUMMARY moved=$moved planned=$planned skipped=$skipped"

if [ "$skipped" -gt 0 ]; then exit 2; fi
exit 0
