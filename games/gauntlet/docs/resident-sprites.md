# Resident sprite programs, 2026-11-03

The 14 MB development build now loads prepared sprite programs and colours from
`SPRITES.DAT`. This implements the first step of the [R-Type review](rtype-performance-review.md).
The measured heavy scene improves from **4.0 to 4.49 displayed pictures/s**;
the **16.7 pictures/s heavy-play target is still unmet**. Native game routines
have not been replaced in this change.

## Runtime and assets

`tools/resident_sprites.py` collects exact baked images and checker colour maps
from independently checked reference scenarios and the sprite fixtures. It
prepares opaque masks, aligned source words, mask-group row order, all 16 shifts,
and generated 68000 routines. The shared `engine/sprite_programs.py` from
STEArcade supplies the 16-pixel pass geometry; wider rows extend that geometry.
All planes run in one HOP 2 / OP 3 copy pass, with opaque pixels in the end
masks. Source addresses advance in pass order; only changed registers are
written. Full destination addresses support 64 KB crossings. Priority remains
the original object order; row reordering stays inside an object.

The current working set has 379 image/colour pairs, 273 shapes, 3,412 shared
routines and 958,362 bytes of code. The complete indexed pack is **1,610,560
bytes**, starting at `$400000`; the low runtime and fixed screen buffers keep
their addresses. Pack offsets are relative to the pack base. A later HDD cache
can use indexed blocks, but no streaming or DMA disk I/O is implemented here.

The loader reads the matching file through GEMDOS before taking over the
machine. It checks available ST RAM (including 1 MB of space above the pack for
TOS and its temporary stack), the read length and the build signature.
`GAUNTLET.PRG` and `SPRITES.DAT` must stay together. Unknown image/colour pairs
use the existing dynamic bake/prepared-row path. Partial band draws use the
resident image's original row-order words. `MO_PREP=0`, `MO_BLACKSH=0` and
`MO_ORDER` select their existing paths. `-D RESIDENT=0` builds the standalone
low-memory control without the pack requirement.

Snapshot retries now use `game_serial`, incremented at **every game-to-renderer
yield**, including queue yields. Display-only VBLs no longer invalidate an
unchanged object snapshot. `frames_done` alone would miss queue work and is not
used for this purpose. `-D SNAP_EPOCH=0` restores the old invalidation for comparison.

## Fixed-workload renderer measurements

Musashi instruction cycles **plus Blitter bus cycles**, seed 0, reference
pictures 2400–2649, every picture checked; first 30 excluded from the warm mean:

| Renderer | Warm mean cycles/picture |
|---|---:|
| Original prepared-row path | 358,194 |
| Resident, natural row order | 308,975 |
| Resident, grouped mask order | 308,947 |

The resident path saves **13.75% of total renderer cycles**. The drawing phase
falls from 132,389 CPU + 29,633 bus cycles to 88,279 CPU + 24,496 bus cycles,
about **30.4%**. Grouping versus natural order is effectively neutral in time
(28 cycles/picture); grouping reduces the pack by 12,732 bytes, so it is retained.
This is an executed comparison of both fully prepared variants, not an estimate
based on mask counts. These render-only figures exclude native game work and
display interrupts and must not be reported as whole-machine FPS.

## Pinned Hatari: matched heavy game states

STE, 14 MB, 8 MHz, cycle-exact/compatible CPU, TOS 2.06 DE; pinned Hatari
2.6.1-devel built 2026-10-20. Attract demo, no MIDI traffic. Emulator sound
output is disabled; the game's sound processing still runs. Debugger windows
are bounded by completed logic ticks **2129–2162**, at idle-game VBLs. Different
renderers reach these states at different VBL numbers.

| Build | Window, VBLs | Displayed pictures/s | Logic ticks/s | Longest complete flip gap |
|---|---|---:|---:|---:|
| Installed original | 2050–2150 | 4.00 | 16.50 | 17 VBLs |
| Resident, old snapshot retries | 2004–2094 | 4.44 | 18.33 | 14 VBLs |
| Resident + yield epoch, default | 2004–2093 | **4.49** | **18.54** | 15 VBLs |
| Optional deadline prototype | 2302–2429 | 6.30 | 12.99 | 11 VBLs |

The default completes the same 33 ticks in 89 rather than 100 VBLs. Eight
pictures are displayed in each default/control sample; this is a small bounded
sample. The epoch change reduces snapshot entries from 19 to 18 in the matched
resident window, so its isolated gain is small here. The default's remaining
machine-time buckets are approximately native game 26.3%, restoration/copies
19%, sprite drawing 17.2%, snapshots 8.1%, and matching/cells 5%.

`src/cadence.s`, enabled explicitly with `-D PIC_VBLS=3`, estimates remaining
render time and the next logic batch with a free-running Timer D. It can defer
starting game work at existing safe yields; it cannot preempt a long game
routine. It counts actual presentation gaps and misses. It improves the dense
sample's graphics at a considerable logic-speed cost and still misses almost
every three-VBL deadline there. It remains **off by default**, including MIDI
builds. Broad-window averages also change which game states fall in the window;
use matching ticks when comparing the horde.

## Correctness and timing checks

* All 379 pack entries at all 16 shifts: **6,064 pixel-exact cases**, randomized
  backgrounds, transparent holes, 6,016 forced source and 491 destination
  boundary-crossing passes. All **110,384 passes** use HOP 2 / OP 3, four planes,
  and short HOG transfers; maximum observed bus cost **128 cycles**.
* Sprite fixtures: **335 pictures exact**, including edge cases and 459 objects
  spanning 64 KB boundaries; resident drawing is explicitly required by the test.
* Consecutive attract pictures: **3,200 exact** (400–3599, every picture).
  Multiplayer reference scenarios: seed 12 / level 5 and seed 14 / level 9,
  **900 exact pictures each**. These use the existing independent reference's
  black-shadow/colour-mapping policy.
* Forced empty resident directory: **250 exact pictures**, zero generated draws
  and 49 misses, exercising the dynamic fallback.
* Injected snapshot changes: display-only VBL, game yield and queue yield, both
  invalidation modes. Changed records are retaken and final pixels match; the
  yield epoch avoids only the display-only retry.
* Original/patched program comparison: **3,600 attract VBLs** and **4,000 seed
  12 / level 5 VBLs** equal in live state, sound commands and damage marks. This
  uses `PortModel`; it does not validate the optional live interrupt scheduler.
* Optional scheduler: **1,025 executed 68000 cases**, deadline admission,
  guaranteed admission of a needed new state, counter/timer wraps, presentation
  miss accounting and foreground register preservation.
* Production loader: matching pack loaded byte for byte and runtime moved;
  missing, short and wrong-build files rejected; insufficient RAM and missing
  stack headroom rejected before disk I/O. The simulator now supplies TOS's
  `phystop` value for this check.

Border timing was checked in the pinned emulator with `DEBUG=1`. In VBLs
1500–4000, both the old renderer and resident default record 3 fallback arms,
0 late top/on/off events and 3 late bottom events. Thus this is **not a clean
border-timing result**; the old path also has those misses. The baseline's late
PC log includes native `$409D8`. The optional scheduler records 4 fallback arms,
1 late top, 1 late on and 6 late bottom events in that window and is not enabled.
Short generated passes do not fix every source of interrupt latency.

Both normal and MIDI programs assemble within the fixed low-memory limit.
A new four-machine live MIDI comparison could not run on the installed pinned
Hatari: it rejects `--midi-net-in` / `--midi-net-out`. The earlier MIDI results
remain historical; this change has **compile coverage, not a new live lockstep
verification**. The scheduling prototype must not be enabled for network play
without that check.

## Reproduction

Build normally with `venv/bin/python games/gauntlet/tools/build.py`. On a fresh
checkout the first build collects the attract/fixture and two multiplayer
working sets; generated inputs, code and assets remain private under `build/`.
Recollection is incremental. Delete `build/gauntlet/resident_inputs.json` to
rebuild the collected set from scratch.

```sh
venv/bin/python games/gauntlet/tools/resident_sprites.py check
venv/bin/python games/gauntlet/tools/sprite_test.py --require-resident
venv/bin/python games/gauntlet/tools/render_test.py --seed 0 --first 400 --frames 3600 --every 1 --nobuild --require-resident
venv/bin/python games/gauntlet/tools/snapshot_test.py --epoch 1
venv/bin/python games/gauntlet/tools/cadence_test.py
venv/bin/python games/gauntlet/tools/loader_test.py
venv/bin/python games/gauntlet/tools/bottleneck_audit.py --ticks --start 2129 --stop 2162
```

For row-order comparisons, build the pack with `build --order natural` or
`build --order mask`, then rebuild the harness/runtime before measuring. Every
pack change requires a matching program build. Private raw reports are in
`build/gauntlet/resident_*`; the default mask pack's SHA-256 is
`414ee3dd52dc995d3471c09352e368b25aae06223d70283bef655e41bbddabf3`.

The next performance work needs to reduce per-picture work substantially:
restoration/pending-tile synchronization and the remaining sprite setup/draw
cost, alongside native monster work. The separate long transition stall also
remains. Increasing RAM and adjusting admission alone have not supplied the
roughly fourfold throughput still needed in the densest scene.
