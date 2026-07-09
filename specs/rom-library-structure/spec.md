# Spec: ROM Library Folder Structure + Organizer Script

> **This spec follows the REASONS Canvas** (`specs/TEMPLATE.md`). Acceptance criteria are
> §10; the deterministic gate is §11 (`verify.sh`). Norms §7 and Safeguards §8 are always-on.

- **Status:** Planned v0.1 (slugs verified against RomM docs' generated platform registry, 2026-07-09)
- **Owner:** Matt (spec authored by Claude, orchestrator; executor: qwen3-coder via ralph loop)
- **Constitution:** `specs/constitution.md` (+ `/CLAUDE.md` Core Mandates)
- **Touches:** `docs/rom-library-structure.md` (new), `scripts/rom-organize.sh` (new) — NOTHING else

---

## 1. Why · [R]

The game-preservation initiative (`docs/game-preservation.md`, Task 4) needs a canonical NAS
folder layout for the ROM library so that RomM (already live at `romm.lab.mtgibbs.dev`, v4.9.2)
scans and binds platforms correctly, and a helper script that takes a directory of freshly
dumped files (from the OSCR / GBxCart / disc-rip workflow) and files them into that layout
with clean names. Without this, dumps pile up ad-hoc and RomM either mis-binds or misses them.

## 2. Outcomes (Definition of Done) · [R]

1. A durable doc (`docs/rom-library-structure.md`) defines the library layout and platform
   slugs, so any human or agent files ROMs the same way.
2. A standalone organizer script (`scripts/rom-organize.sh`) moves dumped files from a source
   dir into the library layout: validated, sanitized, collision-safe, with a `--dry-run` mode.
3. `specs/rom-library-structure/verify.sh` passes (it exercises the script against fixtures).

## 3. Entities · [E]

**CLI contract (exact):**

```
scripts/rom-organize.sh --platform <slug> --source <dir> --library <dir> [--dry-run]
```

- `--platform` — one of the 12 slugs in §6.2. The platform is ALWAYS explicit; never inferred
  from extension (`.bin` is Genesis or PS1, `.iso` is PS2/GC/Wii — inference is ambiguous).
- `--source` — flat directory of freshly dumped files (no recursion into subdirectories).
- `--library` — the library ROOT (the dir that contains/will contain `roms/`).
- `--dry-run` — print what would happen; move nothing.

**Output grammar (exact, one line per file, no colors):**

```
MOVED: <src> -> <dest>
PLANNED: <src> -> <dest>        (dry-run only)
SKIPPED: <src> (<reason>)       reasons: bad-extension | exists | orphan-bin | missing-bin
SUMMARY moved=<n> planned=<n> skipped=<n>
```

**Exit codes:** `0` = clean (nothing skipped) · `1` = bad invocation (unknown option/slug,
missing `--source`/`--library` dir) · `2` = run completed but ≥1 file SKIPPED. Dry-run uses
the same codes for what WOULD happen.

**Filename sanitization (exact, in this order, applied to the destination basename):**

1. Replace every `_` with a space.
2. Delete these characters: `: * ? " < > | \`
3. Collapse runs of spaces to a single space.
4. Trim leading/trailing spaces from the name (before the extension).
5. Lowercase the extension only (`Metroid.GBA` → `Metroid.gba`). Title case is preserved.

Region/revision tags like `(USA)`, `(World)`, `(Rev 1)`, `[!]` are kept verbatim — RomM
parses them (both `()` and `[]`). Canonical No-Intro renaming against DAT files is **NOT**
this script's job (that's game-preservation Task 14).

## 4. Approach · [A]

Pure **bash + coreutils** (`awk`/`sed`/`grep`/`tr`/`mv`), single file, no dependencies — the
execution containers have **no python, ruby, jq, or node guaranteed** (verified absent in the
harness container 2026-07-09). Same shape as the repo's other operational bash:
`scripts/ralph-qwen.sh` (strict mode, small functions, explicit exit codes).

Rejected approaches: python implementation (interpreter not guaranteed where verify.sh runs);
extension-based platform inference (ambiguous, see §3); rewriting cue files to sanitized bin
names (violates the never-modify-content safeguard, §8).

## 5. Scope · [S — boundary]

### In scope
- `docs/rom-library-structure.md` — new doc (T1).
- `scripts/rom-organize.sh` — new script (T2).

### Out of scope — do NOT touch
- Anything under `clusters/` (no manifests, no RomM deployment changes, no backup CronJobs).
- No NFS mounts, no NAS access, no network calls — the script only touches the two
  directories passed as arguments.
- No DAT/No-Intro/Redump verification or checksum manifests (Task 14, separate spec).
- No BIOS-file handling in the script (the doc describes the `bios/` tree; the script only
  organizes ROMs).
- `docs/game-preservation.md`, `CLAUDE.md`, existing scripts — read-only.

## 6. Prior decisions / facts the implementer must know · [S — system fit]

### 6.1 Library layout (RomM "Structure A" — the recommended layout)

The QNAP share `/share/cluster/games` is mounted into RomM as `/romm/library`. On-disk law:

```
library/
├─ roms/<platform-slug>/<Game File>              # single-file games, loose
├─ roms/<platform-slug>/<Game Name>/<files>      # multi-file games (cue/bin, multi-disc)
└─ bios/<platform-slug>/<firmware files>         # optional, only firmware-needing platforms
```

- Multi-disc titles share ONE game folder: RomM's own example is
  `roms/ps/game_5/{game_5_cd_1.iso, game_5_cd_2.iso}`.
- Source: RomM docs "Folder Structure" page (rommapp/docs `docs/getting-started/folder-structure.md`).

### 6.2 Platform slugs + allowed extensions (verified 2026-07-09)

Slugs come from RomM's generated supported-platforms registry (rommapp/docs
`docs/resources/snippets/supported-platforms.md`). The folder name MUST match the slug.

| Platform | Folder slug | Allowed extensions (lowercase) |
| :--- | :--- | :--- |
| Nintendo Entertainment System | `nes` | `.nes` |
| Super Nintendo | `snes` | `.sfc` `.smc` |
| Nintendo 64 | `n64` | `.z64` `.n64` `.v64` |
| Game Boy | `gb` | `.gb` |
| Game Boy Color | `gbc` | `.gbc` |
| Game Boy Advance | `gba` | `.gba` |
| Nintendo DS | `nds` | `.nds` |
| Sega Mega Drive/Genesis | `genesis` | `.md` `.gen` `.bin` |
| PlayStation | `psx` | `.cue` `.bin` `.chd` |
| PlayStation 2 | `ps2` | `.iso` `.chd` |
| Nintendo GameCube | `ngc` | `.rvz` `.iso` |
| Wii | `wii` | `.rvz` `.iso` `.wbfs` |

(Note: an older RomM docs example shows `ps/`; the generated registry table says `psx` for
PlayStation — use `psx`. If the live 4.9.2 scan ever fails to bind it, the remap is
`system.platforms` in RomM's `config.yml` — a LIVE-tier concern, not this script's.)

### 6.3 The cue/bin trap (PS1) — read carefully

A `.cue` file references its `.bin` file(s) BY NAME inside its content, as lines like:

```
FILE "Final Fantasy VII (USA) (Disc 1).bin" BINARY
```

Therefore, for `--platform psx`:

- For each `.cue` in source: parse its `FILE "..."` lines to find its bins.
- The game gets a folder: `roms/psx/<game-name>/` where `<game-name>` = the cue's basename,
  sanitized (§3), with `.cue` dropped and a trailing ` (Disc <digits>)` tag removed — so
  Disc 1 and Disc 2 of the same game land in the SAME folder.
- **Read and remember the cue's FILE list BEFORE moving the cue** — once the cue has moved,
  its old path is gone and the bin list with it.
- **Move the `.cue` and its referenced `.bin` files with their ORIGINAL basenames unchanged**
  (no sanitization of these filenames — renaming a bin breaks the cue's internal reference;
  never rewrite the cue's content). Only the FOLDER name is sanitized.
- A `.cue` whose referenced bin is missing from source → `SKIPPED: ... (missing-bin)`, cue
  stays put.
- A `.bin` in source referenced by no cue → `SKIPPED: ... (orphan-bin)`, stays put.
- A `.chd` is self-contained → moves loose and sanitized like a cart file.

### 6.4 Everything else

- Non-psx platforms: every regular file in source with a valid extension moves loose to
  `roms/<slug>/<sanitized name>`; invalid extension → `SKIPPED: ... (bad-extension)`.
- Dumps come from: OSCR (NES/SNES/N64/Genesis carts), GBxCart (GB/GBC/GBA), CleanRip
  (GC/Wii → `.rvz`/`.iso`), PC drive (PS1 → `.bin/.cue`, PS2 → `.iso`). See
  `docs/dumper-hardware.md`.

## 7. Norms · [N]

- Bash strict mode: `set -uo pipefail`. Quote EVERY expansion — fixture filenames contain
  spaces, parentheses, and brackets by design. No `eval`.
- Shebang `#!/usr/bin/env bash`; file is executable (`chmod +x`).
- Output exactly the §3 grammar — it's machine-parseable and log-friendly. No ANSI colors.
- `mkdir -p` destination dirs just-in-time; check `[ -e "$dest" ]` explicitly before moving
  (do not rely on `mv -n`, whose skip is silent).
- Errors go to stderr; the per-file MOVED/PLANNED/SKIPPED lines go to stdout.
- Unknown platform slug error message must list the 12 supported slugs (self-documenting).
- Doc (`docs/rom-library-structure.md`) matches house doc style: title, short intro, the
  layout tree, the §6.2 table verbatim, naming rules, a "How to file new dumps" section
  pointing at `scripts/rom-organize.sh`, and a note that DAT-based canonical renaming is
  deferred to game-preservation Task 14.

## 8. Safeguards · [S — non-negotiable]

- **Never destroy data.** No `rm`. Never overwrite an existing destination (collision →
  `SKIPPED (exists)`). A skipped source file stays exactly where it was.
- **Never modify file contents.** Moves only. In particular never rewrite a cue.
- **Touch only the given paths.** No hardcoded NAS paths (`/share/cluster`, `storage.lab`),
  no network commands (`curl`/`wget`/`ssh`), no paths outside `--source`/`--library`.
- **Idempotent.** Re-running after a clean run (empty source) exits 0 and changes nothing.
- Each safeguard is asserted by §11's verify.sh.

## 9. Task breakdown · [O]

- **T1 — the doc.** Write `docs/rom-library-structure.md` per §7's doc norm, carrying §6.1's
  layout and §6.2's table. No other files.
- **T2 — the script.** Implement `scripts/rom-organize.sh` per §3 contract, §6.3/6.4 rules,
  §7 norms, §8 safeguards. No other files.

(Sequential: T1 then T2. Tasks are in `tasks.txt` for the ralph loop.)

## 10. Acceptance criteria (EARS) · [O]

1. **Ubiquitous** — The doc shall exist at `docs/rom-library-structure.md` and contain the
   `library/roms/` Structure-A pattern, all 12 slugs of §6.2, the `bios/` tree, the
   multi-disc one-folder rule, and the Task-14 DAT deferral note.
2. **Ubiquitous** — The script shall exist at `scripts/rom-organize.sh`, be executable, pass
   `bash -n`, and invoke no interpreter beyond bash + coreutils (no python/node/ruby/perl/jq).
3. **Event-driven** — When run on cart files with valid extensions, the script shall move each
   to `<library>/roms/<slug>/<sanitized name>` per §3's sanitization rules.
4. **Event-driven** — When run with `--dry-run`, the script shall print `PLANNED:` lines and
   move nothing (source unchanged, library untouched).
5. **Unwanted** — If a file's extension is not allowed for the platform, then the script shall
   leave it in place, print `SKIPPED: ... (bad-extension)`, and exit 2.
6. **Unwanted** — If a destination already exists, then the script shall not overwrite it,
   shall leave the source file in place, print `SKIPPED: ... (exists)`, and exit 2.
7. **Event-driven** — When `--platform psx` is given cue/bin sets, the script shall place each
   cue + its referenced bins (original basenames unchanged) into one sanitized, disc-tag-free
   game folder — both discs of a game in the SAME folder.
8. **Unwanted** — If a cue's referenced bin is absent (`missing-bin`) or a bin is referenced by
   no cue (`orphan-bin`), then the script shall leave those files in place, print the reason,
   and exit 2.
9. **Unwanted** — If the platform slug is unknown, then the script shall exit 1, move nothing,
   and print an error listing the supported slugs.
10. **Ubiquitous** — The script shall end output with the `SUMMARY moved= planned= skipped=`
    line and use exit codes exactly as §3 defines (0 clean / 1 invocation / 2 skips).

## 11. Verification (the harness)

`specs/rom-library-structure/verify.sh` — pure bash + coreutils, runs offline from the repo
root, builds throwaway fixture trees under `mktemp -d`, and compiles every §10 criterion into
an assertion. Exit 0 = acceptable. **The loop runs it; the model never self-certifies.**

- STATIC tier (gates every loop iteration): everything above — doc greps, `bash -n`,
  dependency/safeguard greps, and full behavioral fixture runs of the script.
- LIVE tier (post-merge, human): copy a real dump batch to the NAS via the script, RomM
  rescan binds all 12 platform folders (incl. `psx`), covers show up. NOT gated in the loop.
- Note: verify.sh skips the script's behavioral checks with a visible `PEND` line while
  `scripts/rom-organize.sh` does not exist yet (so T1 can pass before T2 starts). Once the
  file exists, ALL behavioral checks are enforced.

## 11b. Loop execution

Run via `scripts/ralph-qwen.sh specs/rom-library-structure` from inside a dedicated worktree
on a throwaway branch (per `specs/constitution.md` git discipline). `tasks.txt` has 2 tasks;
one per iteration, fresh context, verify-gated, retry-with-feedback.

## 12. Open questions

- **OQ1 (non-blocking, LIVE tier):** confirm the live RomM 4.9.2 instance binds the `psx`
  folder name on first scan (registry says `psx`; an older docs example said `ps`). If not:
  `config.yml` `system.platforms` remap. Does not affect the script's correctness.

## Two-way sync rule

Spec is the source of intent. If review changes behavior (e.g. a sanitization rule), fix this
spec first, then the code. If code is refactored without behavior change, sync the fact back
here. The §6.2 table is duplicated into the T1 doc deliberately (doc = operator-facing); a
change to one MUST be made in both.
