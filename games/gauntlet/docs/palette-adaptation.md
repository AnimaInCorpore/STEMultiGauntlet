# Bounded palette fitting, 2026-11-05

The full-width Gauntlet renderer uses STEArcade's bounded source-RGB fitter by
default. The shared `engine/palette_quantize.py` and `.js` were copied from
STEArcade commit `d02b567`. The renderer itself remains this branch's scene,
status-bar and resident-sprite implementation.

## Colour policy

Fit the original RGB values before snapping palette colours to the STE grid.
Compress sprite and tile counts separately with exponent 0.75; apply the 8x
sprite preference afterwards. The OKLab chroma preference is
`1 + C² / (C² + 0.1²)`, below 2x. Input RGB saturation is unchanged. The fitter
uses 40 deterministic starts and checker-aware refinement.

The scene lookup retains Gauntlet's previous hue preference: lightness weighs
half as much as each chroma axis (equivalently the shared mapper's hue weight
2). This matters for neutral text and skeleton shades: the demo's default
lightness preference could choose a flesh tone at similar brightness. The
shared `map_palette` adapter applies the same constrained-pair selection to
the fitted colours with that explicit port preference; the default fitter
and other callers keep their original metric.

Fifteen ordinary slots include true black and the four exact player anchors:
red `#ff0000`, blue `#0088ff`, yellow `#ffff00`, green `#00ff00`. Slot 15 remains
reserved for the existing raster band and gameplay pulse. The title's fitted
palette, flat map, checker map and score table are byte-identical to DB15 mode.
The separate status-bar colours and tables are also unchanged.

Gameplay checker pairs have an OKLab lightness difference at most 0.12 and a
chroma-plane distance at most 0.08. A pair's linear-light mix must beat the
nearest flat colour by more than 0.012. Text uses the flat table. The preserved
title retains its earlier checker policy. The existing source-relative checker
phase, flips, scrolling, colour freezes and cache epochs are unchanged.

The palette is fitted to the original RGB histogram. The renderer's existing
IRGB-to-RGB444 decoding still selects its 4,096-entry build-time lookup; no
colour fitting or extra table banks are introduced into the drawing loop.

## Training and rebuilds

`ref/colour_training.py` records the full-width port view, including playfield
behind the removed side panel. It retains small RGB histograms in
`docs/colour_training.json`; no ROMs or frame images enter git. Each scenario
contributes its mean picture before the sprite/tile compression. Attract play
and one-, three- and four-player mazes in levels 1, 2, 5 and 9 are sampled.

The first adaptation used STEArcade's narrower sampled-play histogram. Visual
comparison found that its fixed bright green anchor did not preserve the elf's
darker green shades. The broader training includes those sprites and fixes an
additional identity colours: `#006600` from the dominant sampled cloak RGB
`(0,101,6)`, neutral sprite grey `#888888` from `(135,135,135)`, and wall orange
`#cc6633` from `(203,101,50)`. Red monsters still greatly outnumber green player
pixels even in these samples; the extra anchors keep the elf green, grey
sprites neutral and the walls orange. Black plus the seven anchors leave seven
automatically fitted colours, inside the same 15-colour budget. These are
curated samples, not whole-game colour-quality coverage.

Ordinary `tools/build.py` builds use the new palette. Palette options, source
files and training counts invalidate stale renderer assets. Resident inputs
record their conversion-table signature; a changed palette recollects checked
images and rebuilds `SPRITES.DAT`. A subsequent unchanged build reuses them.
Keep the rebuilt program and pack together.

```sh
venv/bin/python games/gauntlet/tools/build.py
GAUNTLET_PALETTE=db15 venv/bin/python games/gauntlet/tools/build.py
GAUNTLET_PALETTE=scenes venv/bin/python games/gauntlet/tools/build.py
GAUNTLET_DITHER=0 venv/bin/python games/gauntlet/tools/build.py
```

`GAUNTLET_DITHER=0` keeps the default fitted palette and selects flat colours.
The DB15/scenes alternatives retain their earlier contrast-weight setting.
Node.js is needed to fit a new palette; all fitting caches are private build
outputs. Regenerate training with `venv/bin/python games/gauntlet/ref/colour_training.py`.

## Validation

`tools/palette_test.py` checks preserved title/HUD tables, all four anchors,
reserved-slot exclusion, checker bounds and minimum gain, flat text and the
no-dither option. `engine/palette_quantize_test.py` checks the shared fitter's
fixed anchors, sparse input, checker choices and cache replay.

Native rendering comparisons, resident/fallback checks and pinned Hatari
measurements are retained privately in `build/gauntlet/palette_adaptation/`.
They test colour conversion and pixel correctness, rather than establishing
whole-game palette quality or a speedup. The earlier heavy-play cadence target
remains unmet.

Final-palette checks:

- Recollection: 3,467 reference pictures and 335 sprite-fixture pictures match.
- Resident build: 740 attract/gameplay pictures match, including 250 consecutive
  pictures each in level 5 (three players) and level 9 (two players).
- Sprite suite: 335 edge, shift, flip, overlap, shadow, guard and 64 KiB crossing
  pictures match; 2,947 generated resident draws execute.
- Forced empty resident directory: 40 pictures match through the dynamic path,
  with zero resident draws and ten cache misses.
- All 6,064 generated variants execute correctly on random backgrounds,
  including 6,016 source and 491 destination 64 KiB crossings. Their longest
  pass is 128 bus cycles. The complete sprite suite's longest is 256; no shared
  passes or passes over 256 occur.
- The 958,362 bytes of generated drawing code and the complete mask/pass-stream
  region match the saved DB15 pack byte for byte. Only colour data/directory
  contents differ. The new pack is 1,609,432 bytes at `$400000`.
- Normal and MIDI programs rebuild; runtime ends are `$1F414A` / `$1F5198`,
  below the fixed screen buffers at `$200000`. An unchanged normal build reuses
  the checked resident inputs and pack. Live MIDI gameplay was not rerun.

Pinned Hatari, 14 MB STE, 8 MHz, cycle-exact/compatible CPU, sound output off;
the same completed logic ticks 2129–2162 bound each short release-build sample:

| Measure | Saved DB15 | New palette |
|---|---:|---:|
| Elapsed VBLs | 89 | 86 |
| Logic ticks/s | 18.54 | 19.19 |
| Displayed pictures in the half-open window | 8 | 7 |
| Displayed pictures/s | 4.49 | 4.07 |
| Longest complete flip gap | 15 VBLs | 14 VBLs |
| Complete gaps over 3 VBLs | 7/7 | 6/6 |

The picture count changes by one in this short window; these numbers do not
establish a general throughput change. Separate DEBUG runs record no additional
late top-border, palette-on, bottom-border or palette-off events inside the
matched window. Earlier startup totals are not zero: saved DB15 has 1 late top
and 2 late palette-on events; the final palette has 3 and 2. No whole-game
border-timing claim is made.

`comparison.png` and `compare_*.png` show arcade RGB in the port's view, native
DB15 output and native fitted output. The private preview checks both native
index images against the independent reference and verifies flat text. The
arcade column leaves the relocated status bar blank. The runtime LUT deliberately
retains RGB444 rounding, and the port retains its opaque-black sprite shadows.
