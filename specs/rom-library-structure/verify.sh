#!/usr/bin/env bash
# verify.sh — deterministic acceptance gate for specs/rom-library-structure.
# §10 acceptance criteria compiled into runnable assertions: exit 0 = acceptable.
#
# STATIC tier only, fully offline, pure bash + coreutils (the execution container has no
# python/ruby/jq/node). Builds throwaway fixture trees in mktemp -d and runs the organizer
# against them. Run from the repo root:  bash specs/rom-library-structure/verify.sh
#
# While scripts/rom-organize.sh does not exist yet (T1 phase), behavioral checks print a
# PEND line and are skipped so the doc task can land first. Once the file exists they all gate.
set -uo pipefail

DOC="${DOC:-docs/rom-library-structure.md}"
ORG="${ORG:-scripts/rom-organize.sh}"
fail=0
ok(){ echo "  PASS  $1"; }
no(){ echo "  FAIL  $1" >&2; fail=1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# ───────────────────────────── T1 — the doc (AC#1) ─────────────────────────────
if [ ! -f "$DOC" ]; then
  no "doc-exists ($DOC missing)"
else
  ok "doc-exists"
  grep -q 'library/roms/' "$DOC" && ok "doc:structure-a-path" || no "doc:structure-a-path (library/roms/ not mentioned)"
  grep -q 'bios/' "$DOC" && ok "doc:bios-tree" || no "doc:bios-tree"
  for slug in nes snes n64 gb gbc gba nds genesis psx ps2 ngc wii; do
    grep -q "\`$slug\`" "$DOC" && ok "doc:slug:$slug" || no "doc:slug:$slug (missing \`$slug\`)"
  done
  grep -qi 'disc' "$DOC" && ok "doc:multi-disc-rule" || no "doc:multi-disc-rule"
  grep -q 'rom-organize.sh' "$DOC" && ok "doc:points-at-script" || no "doc:points-at-script"
  grep -qi 'DAT' "$DOC" && grep -q 'Task 14' "$DOC" && ok "doc:dat-deferral" || no "doc:dat-deferral (No-Intro/Redump DAT renaming deferred to Task 14)"
fi

# ─────────────────────────── T2 — the organizer script ─────────────────────────
if [ ! -f "$ORG" ]; then
  echo "  PEND  $ORG not present yet (T2 pending) — behavioral checks skipped"
else
  # AC#2 — form: executable, syntactically valid, bash+coreutils only
  # (stat, not test -x: worktrees can sit on noexec mounts where test -x lies)
  stat -c %A "$ORG" | grep -q x && ok "script:executable" || no "script:executable (chmod +x)"
  bash -n "$ORG" 2>/dev/null && ok "script:bash-syntax" || no "script:bash-syntax (bash -n fails)"
  head -1 "$ORG" | grep -qE '^#!/(usr/bin/env )?bash|^#!/bin/bash' && ok "script:bash-shebang" || no "script:bash-shebang"
  if grep -vE '^[[:space:]]*#' "$ORG" | grep -qE '\b(python3?|node|ruby|perl|jq)\b'; then
    no "script:no-foreign-interpreters (found python/node/ruby/perl/jq)"
  else ok "script:no-foreign-interpreters"; fi
  # §8 safeguards: no deletion, no network, no hardcoded NAS paths
  if grep -vE '^[[:space:]]*#' "$ORG" | grep -qE '(^|[;&|[:space:]])rm[[:space:]]'; then
    no "script:never-deletes (found rm)"
  else ok "script:never-deletes"; fi
  if grep -vE '^[[:space:]]*#' "$ORG" | grep -qE '\b(curl|wget|ssh|scp|rsync)\b'; then
    no "script:no-network"
  else ok "script:no-network"; fi
  if grep -qE '/share/cluster|storage\.lab' "$ORG"; then
    no "script:no-hardcoded-nas-paths"
  else ok "script:no-hardcoded-nas-paths"; fi

  run_org(){ bash "$ORG" "$@"; }   # invoked via bash so a lost +x bit can't mask behavior

  # AC#9 — unknown slug: exit 1, lists supported slugs, moves nothing
  mkdir -p "$TMP/u/src" "$TMP/u/lib"; : > "$TMP/u/src/x.gb"
  out="$(run_org --platform atari9999 --source "$TMP/u/src" --library "$TMP/u/lib" 2>&1)"; rc=$?
  [ "$rc" -eq 1 ] && ok "unknown-slug:exit-1" || no "unknown-slug:exit-1 (got $rc)"
  printf '%s' "$out" | grep -q 'psx' && ok "unknown-slug:lists-supported" || no "unknown-slug:lists-supported (error should list the 12 slugs)"
  [ -f "$TMP/u/src/x.gb" ] && [ ! -e "$TMP/u/lib/roms" ] && ok "unknown-slug:nothing-moved" || no "unknown-slug:nothing-moved"

  # AC#3/#5/#10 — cart happy path + sanitization + bad extension
  mkdir -p "$TMP/a/src" "$TMP/a/lib"
  : > "$TMP/a/src/Super Mario Land (World) (Rev 1).gb"
  : > "$TMP/a/src/Wario_Land  (USA).gb"
  : > "$TMP/a/src/notes.txt"
  out="$(run_org --platform gb --source "$TMP/a/src" --library "$TMP/a/lib" 2>&1)"; rc=$?
  [ "$rc" -eq 2 ] && ok "carts:exit-2-on-skip" || no "carts:exit-2-on-skip (got $rc)"
  [ -f "$TMP/a/lib/roms/gb/Super Mario Land (World) (Rev 1).gb" ] && ok "carts:clean-name-moved" || no "carts:clean-name-moved"
  [ -f "$TMP/a/lib/roms/gb/Wario Land (USA).gb" ] && ok "carts:sanitized (_ -> space, collapse spaces)" || no "carts:sanitized (want 'roms/gb/Wario Land (USA).gb')"
  [ ! -e "$TMP/a/src/Super Mario Land (World) (Rev 1).gb" ] && ok "carts:source-cleared" || no "carts:source-cleared"
  [ -f "$TMP/a/src/notes.txt" ] && [ ! -e "$TMP/a/lib/roms/gb/notes.txt" ] && ok "carts:bad-ext-stays" || no "carts:bad-ext-stays"
  printf '%s' "$out" | grep -q 'SKIPPED: .*notes.txt (bad-extension)' && ok "carts:bad-ext-reason" || no "carts:bad-ext-reason"
  printf '%s' "$out" | grep -qE 'SUMMARY moved=2 planned=0 skipped=1' && ok "carts:summary-line" || no "carts:summary-line (want 'SUMMARY moved=2 planned=0 skipped=1')"

  # sanitization: uppercase extension lowered, double space collapsed (AC#3)
  mkdir -p "$TMP/s/src" "$TMP/s/lib"
  : > "$TMP/s/src/Metroid  Fusion (USA).GBA"
  run_org --platform gba --source "$TMP/s/src" --library "$TMP/s/lib" >/dev/null 2>&1; rc=$?
  [ "$rc" -eq 0 ] && ok "sanitize:exit-0-clean" || no "sanitize:exit-0-clean (got $rc)"
  [ -f "$TMP/s/lib/roms/gba/Metroid Fusion (USA).gba" ] && ok "sanitize:ext-lower+space-collapse" || no "sanitize:ext-lower+space-collapse (want 'Metroid Fusion (USA).gba')"

  # AC#4 — dry run moves nothing, prints PLANNED
  mkdir -p "$TMP/d/src" "$TMP/d/lib"
  : > "$TMP/d/src/Tetris (World).gb"
  out="$(run_org --platform gb --source "$TMP/d/src" --library "$TMP/d/lib" --dry-run 2>&1)"; rc=$?
  [ "$rc" -eq 0 ] && ok "dry-run:exit-0" || no "dry-run:exit-0 (got $rc)"
  printf '%s' "$out" | grep -q 'PLANNED: ' && ok "dry-run:planned-lines" || no "dry-run:planned-lines"
  [ -f "$TMP/d/src/Tetris (World).gb" ] && ok "dry-run:source-untouched" || no "dry-run:source-untouched"
  [ ! -e "$TMP/d/lib/roms/gb/Tetris (World).gb" ] && ok "dry-run:nothing-moved" || no "dry-run:nothing-moved"

  # AC#6 — collision: never overwrite, source preserved
  mkdir -p "$TMP/c/src" "$TMP/c/lib/roms/gb"
  echo new > "$TMP/c/src/Kirby (USA).gb"
  echo old > "$TMP/c/lib/roms/gb/Kirby (USA).gb"
  out="$(run_org --platform gb --source "$TMP/c/src" --library "$TMP/c/lib" 2>&1)"; rc=$?
  [ "$rc" -eq 2 ] && ok "collision:exit-2" || no "collision:exit-2 (got $rc)"
  [ "$(cat "$TMP/c/lib/roms/gb/Kirby (USA).gb")" = "old" ] && ok "collision:dest-unchanged" || no "collision:dest-unchanged (OVERWROTE!)"
  [ -f "$TMP/c/src/Kirby (USA).gb" ] && ok "collision:source-preserved" || no "collision:source-preserved"
  printf '%s' "$out" | grep -q '(exists)' && ok "collision:reason" || no "collision:reason"

  # AC#7/#8 — psx cue/bin: one disc-tag-free folder, original basenames, orphan + missing bins
  mkdir -p "$TMP/p/src" "$TMP/p/lib"
  printf 'FILE "Final Fantasy VII (USA) (Disc 1).bin" BINARY\n  TRACK 01 MODE2/2352\n' > "$TMP/p/src/Final Fantasy VII (USA) (Disc 1).cue"
  : > "$TMP/p/src/Final Fantasy VII (USA) (Disc 1).bin"
  printf 'FILE "Final Fantasy VII (USA) (Disc 2).bin" BINARY\n  TRACK 01 MODE2/2352\n' > "$TMP/p/src/Final Fantasy VII (USA) (Disc 2).cue"
  : > "$TMP/p/src/Final Fantasy VII (USA) (Disc 2).bin"
  printf 'FILE "Ghost Game (USA).bin" BINARY\n' > "$TMP/p/src/Ghost Game (USA).cue"
  : > "$TMP/p/src/Random Game (USA).bin"
  out="$(run_org --platform psx --source "$TMP/p/src" --library "$TMP/p/lib" 2>&1)"; rc=$?
  [ "$rc" -eq 2 ] && ok "psx:exit-2-on-skips" || no "psx:exit-2-on-skips (got $rc)"
  d="$TMP/p/lib/roms/psx/Final Fantasy VII (USA)"
  [ -f "$d/Final Fantasy VII (USA) (Disc 1).cue" ] && [ -f "$d/Final Fantasy VII (USA) (Disc 1).bin" ] \
    && ok "psx:disc1-in-game-folder" || no "psx:disc1-in-game-folder (want '$d/')"
  [ -f "$d/Final Fantasy VII (USA) (Disc 2).cue" ] && [ -f "$d/Final Fantasy VII (USA) (Disc 2).bin" ] \
    && ok "psx:disc2-same-folder" || no "psx:disc2-same-folder (both discs share ONE folder)"
  [ -f "$TMP/p/src/Ghost Game (USA).cue" ] && ok "psx:missing-bin-cue-stays" || no "psx:missing-bin-cue-stays"
  printf '%s' "$out" | grep -q '(missing-bin)' && ok "psx:missing-bin-reason" || no "psx:missing-bin-reason"
  [ -f "$TMP/p/src/Random Game (USA).bin" ] && ok "psx:orphan-bin-stays" || no "psx:orphan-bin-stays"
  printf '%s' "$out" | grep -q '(orphan-bin)' && ok "psx:orphan-bin-reason" || no "psx:orphan-bin-reason"

  # wii loose single-file (AC#3 on a disc platform)
  mkdir -p "$TMP/w/src" "$TMP/w/lib"
  : > "$TMP/w/src/Wii Sports (USA).rvz"
  run_org --platform wii --source "$TMP/w/src" --library "$TMP/w/lib" >/dev/null 2>&1; rc=$?
  [ "$rc" -eq 0 ] && [ -f "$TMP/w/lib/roms/wii/Wii Sports (USA).rvz" ] && ok "wii:loose-rvz" || no "wii:loose-rvz"

  # §8 — idempotent: empty source exits 0 (AC#10)
  mkdir -p "$TMP/e/src" "$TMP/e/lib"
  run_org --platform gb --source "$TMP/e/src" --library "$TMP/e/lib" >/dev/null 2>&1; rc=$?
  [ "$rc" -eq 0 ] && ok "idempotent:empty-source-exit-0" || no "idempotent:empty-source-exit-0 (got $rc)"
fi

echo
if [ "$fail" = 0 ]; then echo "VERIFY: PASS"; else echo "VERIFY: FAIL"; exit 1; fi

# --- LIVE tier (post-merge, human — NOT gated here) ---------------------------------
#   - Run the script on a real dump batch against the NAS library share
#   - RomM rescan binds all 12 platform folders (watch psx vs ps, spec §12 OQ1)
#   - Covers/metadata populate; browser play works for a cart title
