# Retro Dumping Hardware — Buy List (researched 2026-07-01)

Task 2 of `docs/game-preservation.md`. Scope: hardware for dumping **our own** carts/discs.
Prices checked July 2026 unless marked [unverified] or [estimate].

## 1. Open Source Cartridge Reader (OSCR / "Sanni cart reader") — assembled

The one device that covers NES/SNES/N64/Genesis/GB/GBC/GBA. Two real options for pre-assembled units:

| Option | Seller | Price | Covers | Caveats |
| :--- | :--- | :--- | :--- | :--- |
| **OSCR V3-ALTER, assembled ("Build Service")** | [savethehero.builders](https://savethehero.builders/products/open-source-cartridge-reader-v3-alter-build-service) (ships from Japan, FedEx) | **¥24,300 (~US$155–170)** + shipping | Base: SNES/SFC, Genesis/MD, N64, GB/GBC/GBA | NES needs adapter (below). In stock; every unit dump-tested in all slots. Options: SA1/N64-EEPROM+RTC +$19–28, USB-C Mega +$48 |
| **OSCR HW5 Rev5, assembled** | eBay sellers / [Davis Store on Tindie](https://www.tindie.com/products/devdavisnunez/sanni-open-source-cartridge-reader-oscr-hw5-rev5/) | **~$210–295** (listings observed at $209.95–$295, firmware 15.4, VSelect+RTC, 32GB SD) | **NES/FC, SNES/SFC, SMS, N64 (+ Controller Pak), Genesis/MD, GB/GBC/GBA — all native slots** | Small-batch sellers; verify listing includes VSelect. HW5 is the current mainline hardware (dev is at Rev 8; HW7 is future for now) |

**STHB adapters** (for the V3-ALTER route): NES ¥3,100 (~$20), Famicom ¥3,100, Sega Master System
¥3,100, PC-Engine/TG16 ¥4,300, NGP/WonderSwan PCB-only ¥1,400 each — all in stock.

Notes: STHB's "V5 of 7 slots" is still **in development** — their shipping product is V3-ALTER.
[Bonzo's Retro Shop](https://bonzosretro.shop/products/sanni-cart-reader-v5) sells HW5 **kits only**
(~$15/pc parts, currently sold out) — not a pre-assembled option. RetroStage and Epilogue do **not**
sell OSCR units.

## 2. GBxCart RW v1.4 Pro (insideGadgets)

- **Price:** **$33 USD** direct from [shop.insidegadgets.com](https://shop.insidegadgets.com/product/gbxcart-rw/)
  (ships from Australia; includes clear GBA-shell case)
- **Covers:** GB / GBC / GBA — ROM dump, save backup/restore, flash-cart writing. Driven by
  Lesserkuma's **[FlashGBX](https://github.com/lesserkuma/FlashGBX)** (best-in-class GB dumping
  software; also verifies against No-Intro).
- **US resellers:** [Retro Game Repair Shop](https://retrogamerepairshop.com/products/gbxcart-rw-gameboy-gbc-gba-cart-reader-writer-flasher)
  — **currently sold out**; Retro Modding and ZedLabz list it ~$40–45 [unverified].
- **GBFlash** (open-source community design, also FlashGBX-supported) exists via AliExpress/Tindie
  small sellers — pricing/availability [unverified]; GBxCart is the safer buy.

## 3. Retrode 2 — still sold, but skip it

- [Stone Age Gamer](https://stoneagegamer.com/retrode-2.html): **$99.99**, stock spotty; DragonBox
  (EU): **€65 / ~$85**. Adapters (N64, GB, Master System) **$39.99 each**.
- Base unit = SNES + Genesis only; **cannot dump SA-1 SNES games** (Super Mario RPG, Kirby Super
  Star). A Retrode 3 is reportedly in development.
- **Verdict:** fully redundant with an OSCR at a worse price-per-system. Not recommended.

## 4. Epilogue GB Operator

- **$49.99** at [epilogue.co](https://www.epilogue.co/product/gb-operator) — GB/GBC/GBA. Polished
  app (plays carts on PC/Steam Deck too, dumps ROMs+saves).
- **Availability caveat:** shipping paused at time of check — "**Ships on July 15th**" (2026). Also
  stocked at Micro Center [price unverified].
- Verdict: nice-to-have for the kids/UX; the OSCR or GBxCart already covers dumping.

## 5. Disc ripping (PS1/PS2 → Redump-quality)

- **Buy: LG WH16NS40** (internal SATA Blu-ray drive) — the Redump community's standard workhorse.
  Flash it with **ASUS BW-16D1HT 3.02 firmware** (or RibShark's newer **OmniDrive** custom
  firmware), then dump with **redumper** (current Redump-preferred CLI tool).
  - Bonus: with the 3.02/OmniDrive firmware the *same drive* raw-reads **GameCube/Wii and
    Xbox/360** discs — so it doubles as the optional GC/Wii ripper.
  - **Price [estimate]:** getting scarce as the optical market contracts. Newegg's remaining
    listing is a marketplace seller at an inflated **$219**; Amazon bundle listings historically
    **~$100–150** — check Amazon/eBay for a sane price, and confirm it's a real WH16NS40 (SVC code
    NS40/NS50).
  - It's an internal drive: add a **USB 3.0 SATA enclosure/dock (~$15–25)** for laptop use.
- **ASUS BW-16D1HT** itself: discontinued-ish, price-jacked (~$130+ on eBay). Buy the LG and flash it.
- **GameCube/Wii — $0:** homebrewed Wii + **CleanRip** produces Redump-verifiable dumps. (The
  flashed LG above is the no-Wii-needed alternative.)

## 6. DS game cards — $0, no purchase

Current best practice is unchanged: **homebrewed 3DS + GodMode9** (also handles DSi-enhanced
carts), or homebrewed DSi + GodMode9i. Per [dumping.guide](https://dumping.guide/carts/nintendo/ds),
no additional hardware is required. No mainstream new USB NDS dumper exists (GBxCart does **not**
do DS). If a 3DS isn't already in the house, a used one is the "purchase."

---

## Recommended minimal kit

| Item | Price |
| :--- | :--- |
| OSCR **HW5 Rev5 assembled** (eBay/Tindie) — NES+SNES+N64+Genesis+SMS+GB/GBC/GBA in one box, no adapters needed | ~$230 |
| LG **WH16NS40** + USB 3.0 SATA enclosure (flash 3.02/OmniDrive) — PS1/PS2 (+GC/Wii/Xbox raw) | ~$120–175 [estimate] |
| DS: existing 3DS + GodMode9; GC/Wii: existing Wii + CleanRip | $0 |
| **Total** | **~$350–405** |

Budget variant: STHB V3-ALTER (~$165) + NES adapter (~$20) ≈ **$185** for the cart side → total
~$305–360, at the cost of Japan shipping and V3-era hardware.

## Nice-to-have tier

- **GB Operator** ($49.99, ships 7/15) — plug-and-play GB family UX for the family/Steam Deck.
- **GBxCart RW** ($33 direct) — dedicated GB station + FlashGBX's superior save handling; cheap
  enough to add anyway.
- **STHB PCE/TG16 adapter** (¥4,300) and **SMS adapter** (¥3,100) if the collection grows those
  directions (V3-ALTER route only; HW5 has SMS native).
- **Second flashed LG drive** as a cold spare — these are only getting scarcer.

## Sources

[STHB build service](https://savethehero.builders/products/open-source-cartridge-reader-v3-alter-build-service) ·
[STHB build-service collection](https://savethehero.builders/collections/build-service) ·
[sanni/cartreader GitHub](https://github.com/sanni/cartreader/) ·
[insideGadgets shop](https://shop.insidegadgets.com/product/gbxcart-rw/) ·
[FlashGBX](https://github.com/lesserkuma/FlashGBX) ·
[Stone Age Gamer Retrode 2](https://stoneagegamer.com/retrode-2.html) ·
[Epilogue GB Operator](https://www.epilogue.co/product/gb-operator) ·
[Redump wiki — compatible LG/ASUS drives](http://wiki.redump.org/index.php?title=Compatible_LG/ASUS_Optical_Drives) ·
[dumping.guide DS](https://dumping.guide/carts/nintendo/ds) ·
[Tindie OSCR HW5](https://www.tindie.com/products/devdavisnunez/sanni-open-source-cartridge-reader-oscr-hw5-rev5/) ·
[Bonzo's Retro Shop](https://bonzosretro.shop/products/sanni-cart-reader-v5)
