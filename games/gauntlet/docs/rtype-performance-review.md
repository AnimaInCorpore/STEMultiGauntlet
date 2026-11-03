# What Gauntlet can learn from R-Type

Implemented follow-up: [resident sprite programs and snapshot epochs](resident-sprites.md).
The investigation below records the baseline before those changes.

2026-11-03. Gauntlet baseline `4e5a85c`; sibling STEArcade checkout `140c09a`.
This is an investigation, with a new executable renderer audit. No game runtime,
rendering policy, scheduler or installed executable was changed. No optimization
prototype or new Hatari rate is claimed here.

**Development target updated by the user, 2026-11-03: 14 MB ST RAM.** Speed comes
first; memory reduction follows later, potentially through HDD loading of prepared
assets. The measurements below describe the unchanged renderer and its existing
low-memory layout. The recommendations now use the larger development budget.

Follow-up: [the complete running game's bottleneck profile](bottleneck-audit.md)
measures actual flips and native logic in pinned Hatari. Its densest horde sample
displays 4 pictures/s; sprite drawing/preparation is the largest named graphics
group. Use that report for live-game cadence; the simulator figures below isolate
renderer work on supplied reference states.

**Graphics cadence is an explicit objective too.** R-Type's stated goal is steady
25 pictures/s. Its newer heavy-scene policy (`src/rtype.s`, user decision
2026-11-02) is `PIC_VBLS=3`: target a new picture every three PAL fields, about
16.7 pictures/s, letting the game slow when required. Apply that goal and heavy-play
cadence to Gauntlet, retaining its own 60 Hz logic target where it fits and exact
MIDI lockstep progression under overload. The current Gauntlet scheduler does
not guarantee this. A new picture every two fields is 40 ms; every three fields
is 60 ms. Those budgets include logic, renderer, sound, border/input interrupts,
and MIDI when enabled. Renderer optimization and deadline-aware scheduling both
need measurement. Report flip-interval distributions, worst gaps and deadline
misses; an average FPS alone does not establish playable cadence.

The useful transfer is R-Type's **prepared object drawing and small per-object
runtime**, rather than its background renderer. Gauntlet already has a
hardware-scrolled clean playfield, incoming-strip synchronization, prepared sprite
masks and unchanged-object retention. Its remaining cost is predominantly CPU
work. A substantial improvement needs several parts of that work addressed
together; a direct R-Type transplant does not establish a 2x route.

## What actually changed in R-Type

The relevant current implementation is `games/rtype/src/stage.s` and
`games/rtype/tools/stage_sprites.py`, rather than only the older shared
`engine/rt/m72render.s`.

* The native emitters produce one object-definition record instead of expanding
  all of its component sprites. At build time those components become one cropped
  image. Its opaque pieces are packed in drawing order, with generated routines
  and mask/control streams for all 16 shifts. The compiler handles small pieces,
  17–32-pixel pieces and wider opaque runs, and shares code/streams by content.
* `st_sprites` holds fixed Blitter registers and register pointers across objects.
  `st_obj2` uses a direct definition lookup and a last-colouring cache. Generated
  drawing has both low-word destination and whole-address variants for 64 KB
  crossings.
* Frequently used images are coloured at build time. **R-Type now targets 14 MB**;
  its README records a 5.9 MB executable with all stages' pre-coloured sprites.
  Gauntlet now adopts that development memory target too. R-Type has no sound;
  Gauntlet keeps sound and MIDI, so its measured workload still differs.
* R-Type's later investigations are useful negative evidence. Its fully prepared
  secondary-layer prototype changes stage-3 renderer cost by +0.68% or −0.67%,
  depending on picture cadence. Damage merging saves only 0.63% over the longer
  stage-5 sample and does not improve Hatari picture rate. Window-only late
  refresh saves 0.8–2.5% in the executed samples. Preparation and bookkeeping
  must be charged, including cold use.
* Native logic replacements helped translated V30 code in early play: 16–23%
  fewer logic cycles, with much smaller later-stage gains. Gauntlet already runs
  its original 68010 program natively. There is no comparable translation
  overhead to remove.

Source reports in the sibling checkout: `games/rtype/README.md`,
`docs/renderer-audit.md`, `docs/prepared-layer-prototype.md`,
`docs/route1-results.md`, `docs/native-results.md` and
`docs/later-native-results.md` beneath `games/rtype/`.

## Fresh Gauntlet measurements

[`rtype_audit.py`](../tools/rtype_audit.py) executes the production renderer in
the existing Musashi harness, instruction by instruction. CPU and Blitter bus
cycles are separate. Every picture, including warm-up, is compared with
`assets.Oracle`; the first 30 pictures are excluded from each steady-state mean.
Initialization and cold-inclusive means are recorded separately. Preparation
that occurs after warm-up remains charged.

The ordinary `render_test.py --profile` accumulator also contains initialization
and the first cold picture, while its final cycle mean excludes the first
picture. Its short-run routine percentages therefore do not describe that mean.
The new audit avoids that mismatch without changing the existing test.

Cycles below are thousands per picture, rounded. Preparation includes
`mo_bake`, `mo_prep` and the `pr_*` helpers. Snapshot and prepared drawing are
exclusive routine attribution; preparation and whole draw-phase totals must not
be added together. Counts include a small harness return overhead.

| Window | Checked / measured | Total | CPU / bus | Snapshot CPU | Preparation CPU | Prepared drawing CPU / bus | Palette phase CPU |
|---|---:|---:|---:|---:|---:|---:|---:|
| Attract horde, seed 0, frames 2400–2649, every frame | 250 / 220 | 358.2k | 313.4k / 44.8k | 58.5k | 30.2k | 37.2k / 29.4k | 26.1k |
| Horde, frames 2400–2699, every third frame | 100 / 70 | 435.3k | 379.7k / 55.6k | 44.8k | 61.3k | 42.4k / 33.7k | 32.7k |
| Seed 12, level 5, frames 1300–3997, every third frame | 900 / 870 | 255.1k | 226.5k / 28.6k | 44.5k | 35.1k | 20.3k / 15.4k | 33.5k |
| Seed 14, level 9, same frame range/cadence | 900 / 870 | 296.1k | 234.3k / 61.9k | 28.6k | 23.7k | 38.4k / 29.7k | 28.4k |

The two horde rows have different measured tick windows and cache histories;
they are workload samples, **not a controlled cadence A/B comparison**. Short
consecutive controls for seeds 12 and 14 add 150 pictures each. In total:
**2,450 pictures checked, zero differing pictures**. These include 550
consecutive pictures across three windows. Observed Blitter passes were all HOG,
at most 256 bus cycles. This is sample verification, not full-game coverage,
an all-shifts/edges certification, or a check of interrupt timing.

No measured interval flushed the object pool. The longer level-5 run reached
322,648 bytes in the 395,264-byte pool, level 9 reached 197,060 bytes. Enlarging
the pool would not eliminate preparation in these samples: new images and
shifts still have to be prepared. The longer samples' cold-inclusive means are
266.5k and 300.1k; the consecutive horde's is 394.8k.

This harness supplies arcade reference states. It does **not** execute native
Gauntlet logic alongside rendering, VBLs, MIDI, sound interrupts, the flip wait
or the starvation scheduler. These cycle totals cannot be converted directly
to pictures/s or logic ticks/s. In particular, the README's older Hatari horde
profile predates the October 29 object-list restructuring.

## Highest-value work to prototype

1. **Separate sprite shape preparation from colour baking; compile common shapes.**
   `mo_bake` stores masks and pixels together, and clears the 16 prepared-stream
   pointers for each new coloured image. Yet with `MO_BLACKSH=1`, opacity comes
   from ROM tile masks and does not depend on the chosen colour mapping. The
   prepared stream's masks, pass types, source offsets and destination offsets
   can be identified by shape independently of palette epochs. Keep coloured
   plane data in a separate store, share geometry/shift streams, and generate
   drawing routines at build time. With 14 MB, also pre-colour the recorded
   shape/colour-mapping combinations and keep them resident. Measure the complete
   footprint before expanding the prepared set; retain the existing exact fallback
   for other colourings, shapes and partial bands.

   Port R-Type's `sprite_code`/`sprite_streams` approach with Gauntlet's 448-byte
   stride and its 8–64-pixel objects. Test natural row order against the complete
   reordered-source preparation, including left-aligned pieces and NFSR. The
   old `MO_ORDER` experiment was slower; that result is not a measurement of
   generated drawing. Do not split every row into 16-pixel pieces unconditionally:
   extra pass starts may outweigh cheaper reads. Hold fixed Blitter setup across
   objects, and change only registers whose values differ.

   This addresses two measured costs, preparation and interpreted dispatch.
   Even eliminating **all** current preparation CPU and `mo_prep_draw` CPU would
   remove only 18.8%, 21.7% and 21.0% of total renderer cycles in the consecutive
   horde, long level-5 and long level-9 samples. Those are optimistic attribution
   ceilings for those CPU buckets, not predicted savings or a ceiling on a
   redesigned renderer. Bus transfers and the other work remain.

2. **Make the object path smaller alongside generated drawing.**
   In the consecutive horde, `mo_snapshot` alone costs 58.5k; the matching phase
   another 24.3k, the object checksum about 9.5k, plus placement, cells, image
   lookup and strip dispatch. A compiler alone leaves these costs intact.
   R-Type's direct definition/colouring entry is the useful model: cache a
   shape/last-image entry, keep live fields in registers, and avoid deriving the
   same code/size/flip/palette key in each helper. Explore updating the checksum
   while emitting records, rather than traversing them again in `pic_same`.
   Measure the extra register pressure and fallback cost.

   Preserve Gauntlet's band-list priority, general merged-chain path and
   unchanged-object retention. R-Type's flat object-list format cannot simply
   replace them. Moving preparation into every logic tick could be worse than
   doing it only for pictures; prefer eliminating repeated work, not relocating
   it to the more frequent loop.

3. **Reduce unchanged-state scanning and palette maintenance.**
   The palette phase still costs 26–34k per picture in these samples;
   `pal_look` alone costs about 10.5k. R-Type's cached palette identities and
   deliberate invalidation are relevant. Test cheaper exact comparisons or
   writer-driven versioning, preserving the current blackout, scene, text blink
   and already-approved colour-freeze behavior. Charge any writer hook to game
   logic. Do not silently freeze more effects. The same principle may help
   repeated object snapshots, but an 8 KB compare plus copy has a cost too.

4. **Profile and optimize the native monster loop separately.**
   The existing Hatari investigation identifies `$808E–$8412` and its four maze
   probes as the largest logic target in the dense horde. Use R-Type's method:
   fuse hot operations, avoid repeated address calculation, preserve writes and
   flags, and compare against the independent original program. Gauntlet needs
   tighter 68000 code, not a translation-to-native conversion. New profiles must
   precede a speed claim; this renderer audit does not remeasure that loop.

## Lower priority and constraints

* **Duplicate damage copying is a small target.** The audit counts exact
  destination words copied more than once *within `mo_restore`*. Their ideal
  read/write bus cost is 5.9k (1.64%), 2.1k (0.83%) and 0.55k (0.19%) in the
  three main samples. These ceilings exclude construction, splitting and CPU
  savings. They do not measure sparse restoration, copies in other phases or
  future-coverage rejection. Sparse restoration remains unprototyped here.
  Removing the entire restoration phase would still remove only 10.1%, 11.8%
  and 21.7%, and would break the picture. A generic damage-union rewrite is a
  poor first bet for a large overall gain.
* **Extend the memory map explicitly for 14 MB.** Existing production link maps leave
  49,256 bytes before the fixed `$200000` screen buffers in the single-machine
  build, 26,874 in the network build. These are limits of the current placement,
  not limits on the newly approved prepared asset set. Reserve a separate high
  ST-RAM asset arena, initially within `$400000–$DFFFFF`, and extend the loader to
  populate it. Keep the low runtime and existing buffers at their current addresses
  for controlled measurements. Simply raising `RUNTIME_LIMIT` would overlap the
  screens; embedded prepared assets need their own placement/loading path. The
  headroom numbers describe existing maps, not a new production rebuild.
* **Keep guard restoration.** R-Type's scene-specific choice never to erase some
  guard rows conflicts with this repository's restoration contract. Gauntlet's
  ring positions can scroll into view. Likewise, preserve aligned-side clipping,
  transparent holes, band order, the status-bar split, sound and MIDI behavior.
* **Scheduling is not a renderer speedup.** R-Type's game-speed-first picture
  scheduling was subsequently supplemented by its three-field heavy-scene
  picture deadline. Gauntlet already tested changing `STARVE`, with a
  logic/picture tradeoff; it needs an explicit displayed-picture deadline too.
  Compare tick rates and actual flip intervals, and verify MIDI determinism.
  Changing the scheduler cannot establish that a renderer optimization works.

Recommended first controlled experiment: **resident build-time shape programs,
mask streams and pre-coloured images, with a lean per-object entry**. Compare components
separately and together, at fixed buffer addresses, including cold preparation,
fallbacks, startup cost and total 14 MB memory use. Then run all edge/shift/hole/64 KB cases,
consecutive reference pictures and the pinned Hatari replay with border counters.
Broader logic changes additionally require independent logic lock-step and MIDI
determinism checks. Until those execute, a substantial speedup is a testable
direction, not a demonstrated result.

## Resident assets first, HDD loading later

The user's proposed reference is `../stedaimakaimura/dma_test.s`, inspected for
this review. Its active path hooks TOS's `hdv_rw` vector at `$476` while reading
`data_filename`, obtains logical sector size with `Getbpb`, and uses the AHDI
`PUN_INFO` at `$516` to derive a physical device and file-start sector. It then
reads directly through ACSI DMA, or IDE PIO. The ACSI example issues a 255-sector
READ(6) and waits for completion. This demonstrates finding a file on disk and
accessing it directly; it is not yet an asynchronous game asset cache. Recording
one starting sector also does not provide a fragmented file's full extent map.

Gauntlet already inherited [`engine/rt/hdd.s`](../../../engine/rt/hdd.s), which
adapts this idea into `hdd_open`, `hdd_read` and `hdd_poll`, with extent mapping,
timeouts and bounded transfer requests. Its ACSI path uses DMA; IDE copies data
with the CPU and must be budgeted separately. The driver requires a TOS/AHDI
discovery phase **before takeover**, then polling in the main loop; its VBL macro
only updates timeout ticks. The current Gauntlet loader disables interrupts and
overwrites TOS without that discovery phase, so integrating it needs a deliberate
loader change. The driver is not included in Gauntlet's runtime, and this checkout
does not contain the `engine/hdd_test.py` and `tools/hddtest.*` tests mentioned in
its comments; those exist in the sibling STEArcade checkout. No HDD integration
or new driver validation has been done in this investigation.

Use the same asset format for both phases:

1. **14 MB resident build.** Store prepared shape programs, 16-shift mask streams
   and pre-coloured pixel data in indexed blocks. Use stable asset IDs and
   block-relative offsets, with a small explicit relocation list for absolute
   code/data addresses. Load the prepared working set at startup into high ST RAM.
   Keep code and metadata that dispatch to an asset resident. This removes disk
   latency from the first speed experiment and makes actual working-set size
   measurable.
2. **Smaller-memory streaming build, later.** Load the directory once, use the
   same blocks in a bounded cache, and prefetch groups at level/scene transitions
   and before animation use. Sector-align the blocks and satisfy the existing
   driver's 32 KB file/scan-buffer discovery requirements. Start with the shared
   driver after bringing over its focused tests; validate with actual emulated
   ACSI/IDE disk images. A GEMDOS host folder alone does not supply a physical disk
   extent mapping.
3. **Exact misses and safe replacement.** Draw a missing asset with the current
   renderer while its block is pending. Publish it only after the complete load
   and any relocation, and pin blocks referenced by the current draw until it
   finishes. Keep request order/cache state out of native game logic and MIDI
   checksums; independently timed disk completion must not change lockstep play.

Disk streaming reduces resident storage; it is not itself a drawing speedup.
Measure command/setup CPU time, IDE copy time, ACSI/Blitter bus contention,
fallback pictures and border/MIDI timing. Do not wait for a transfer inside a
border or VBL handler. The initial resident implementation can establish the
speed gain before choosing cache size, prefetch distance and transfer sizes.

## Reproduction

Run once without `--nobuild` to assemble the current production render harness:

```sh
venv/bin/python games/gauntlet/tools/rtype_audit.py --seed 0 --first 2400 --frames 2650
venv/bin/python games/gauntlet/tools/rtype_audit.py --seed 0 --first 2400 --frames 2700 --every 3 --nobuild
venv/bin/python games/gauntlet/tools/rtype_audit.py --seed 12 --level 5 --first 1300 --frames 4000 --every 3 --nobuild
venv/bin/python games/gauntlet/tools/rtype_audit.py --seed 14 --level 9 --first 1300 --frames 4000 --every 3 --nobuild
```

For the short consecutive controls, use the last two commands with `--frames
1450 --every 1`. JSON reports, hashes, per-picture costs, pass checks and call
counts stay under ignored `build/gauntlet/rtype_audit_*.json`. Raw ROM-derived
images and snapshots are not added to source control.
