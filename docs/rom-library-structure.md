# ROM Library Folder Structure

**Status:** v0.1 (2026-07-09) · **Owner:** Matt · **Orchestrator:** Claude

> This doc is the canonical reference for the NAS ROM library layout. Use it to file new dumps
> correctly and ensure RomM scans and binds platforms without errors.

---

## 1. Overview

The ROM library lives on the QNAP share `/share/cluster/games`, mounted into RomM as
`/romm/library`. The folder layout follows **RomM "Structure A"** — the recommended layout for
single- and multi-file games, plus an optional `bios/` tree for firmware.

```
library/
├─ roms/<platform-slug>/<Game File>              # single-file games, loose
├─ roms/<platform-slug>/<Game Name>/<files>      # multi-file games (cue/bin, multi-disc)
└─ bios/<platform-slug>/<firmware files>         # optional, only firmware-needing platforms
```

The library root is mounted into RomM at `/romm/library`, so the full path is `/romm/library/roms/<platform>/…`.

- **Multi-disc titles share ONE game folder.** RomM's example: `roms/psx/game_5/{game_5_cd_1.iso, game_5_cd_2.iso}`.
- **Never rename `.bin` files inside a cue/bin pair.** A `.cue` file references its `.bin` BY NAME
  in its content, so renaming breaks the reference. Only the **folder name** is sanitized.

---

## 2. Platform slugs + allowed extensions

Slugs come from RomM's generated supported-platforms registry (verified 2026-07-09). The folder
name MUST match the slug exactly.

| Platform | Folder slug | Allowed extensions |
| :--- | :--- | :--- |
| Nintendo Entertainment System | `nes` | `.nes` |
| Super Nintendo | `snes` | `.sfc`, `.smc` |
| Nintendo 64 | `n64` | `.z64`, `.n64`, `.v64` |
| Game Boy | `gb` | `.gb` |
| Game Boy Color | `gbc` | `.gbc` |
| Game Boy Advance | `gba` | `.gba` |
| Nintendo DS | `nds` | `.nds` |
| Sega Mega Drive/Genesis | `genesis` | `.md`, `.gen`, `.bin` |
| PlayStation | `psx` | `.cue`, `.bin`, `.chd` |
| PlayStation 2 | `ps2` | `.iso`, `.chd` |
| Nintendo GameCube | `ngc` | `.rvz`, `.iso` |
| Wii | `wii` | `.rvz`, `.iso`, `.wbfs` |

---

## 3. Naming rules

Apply these rules to **the folder name** (and loose filename for cart dumps), not to file contents:

1. Replace every `_` with a space.
2. Delete these characters: `: * ? " < > | \`
3. Collapse runs of spaces to a single space.
4. Trim leading/trailing spaces from the name (before the extension).
5. Lowercase the extension only (`Metroid.GBA` → `Metroid.gba`). Title case is preserved.

Region/revision tags like `(USA)`, `(World)`, `(Rev 1)`, `[!]` are kept verbatim — RomM parses
them (both `()` and `[]`). Canonical No-Intro renaming against DAT files is **NOT** this script's
job (that's game-preservation Task 14).

**PS1 cue/bin exception:** For `.cue` files, the **folder name** is sanitized (disc tag stripped),
but the `.cue` and its referenced `.bin` files keep their **original basenames unchanged**. The
cue's internal `FILE "..."` reference must match the actual filenames on disk.

---

## 4. Multi-disc rule

All discs for a single game title go in **one folder**. Example for a 2-disc PS1 game:

```
roms/psx/Final Fantasy VII (USA)/
├─ Final Fantasy VII (USA) (Disc 1).cue
├─ Final Fantasy VII (USA) (Disc 1).bin
├─ Final Fantasy VII (USA) (Disc 2).cue
└─ Final Fantasy VII (USA) (Disc 2).bin
```

The folder name is the game title (disc tags like ` (Disc 1)` are stripped from the folder name).

---

## 5. BIOS / firmware tree

Some platforms (PS1, PS2, Nintendo, etc.) require firmware files to boot. Place them in:

```
bios/<platform-slug>/<firmware files>
```

Only add these if you know you need them (e.g. PS1 BIOS `scph1001.bin`). RomM will warn if a
platform is missing required firmware.

---

## 6. How to file new dumps

1. Dump your game(s) to a **flat directory** (no subdirectories).
2. Run the ROM organizer script:

   ```bash
   scripts/rom-organize.sh --platform <slug> --source <dump-dir> --library <library-root>
   ```

   Use `--dry-run` first to preview moves without touching anything.

3. Scan RomM's library folder (`/romm/library`) to bind new games.

See `scripts/rom-organize.sh --help` for full usage.

---

## 7. DAT-renaming deferred to Task 14

This doc and the `rom-organize.sh` script **do not** perform canonical No-Intro/Redump DAT
renaming. They accept the dump filenames as-is (after the sanitization rules above). DAT-based
renaming is a separate workflow (game-preservation Task 14) and should be run **after** files
are filed into the library structure.

---

*Last updated 2026-07-09. Sync changes to `specs/rom-library-structure/spec.md`.*
