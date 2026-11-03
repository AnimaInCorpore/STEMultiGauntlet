# Biggest bottleneck: the running game

2026-11-03. Production code baseline `4e5a85c`, unchanged installed executable.
Pinned Hatari `2.6.1-devel`, built 2026-10-20, STE, 14 MB ST RAM, cycle-exact and
compatible CPU, fast-forward, TOS 2.06 DE. Sound output is disabled in Hatari;
the game's sound player and interrupts still execute. This is the single-machine
attract demo, without MIDI traffic.

**The graphics pipeline is the first target.** In the densest measured horde,
sprite drawing/preparation takes 24.8% of total machine time, restoration/copies
and pending tiles 16.8%, sprite snapshots 7.3%, and matching/damage cells 4.9%.
Together these disjoint buckets take 53.8%. The copy bucket also includes
background synchronization, so this is not a claim that sprite pixels alone
consume that time. Native game instructions take another 23.5%.

The largest individual renderer routine is `mo_prep_draw`, at **12.8% of machine
time**. The native game's monster-loop/probe region is similarly expensive.
There is no single measured routine whose removal would supply the required
fourfold picture-rate improvement.

Follow-up: the user permits equivalent algorithm replacements. An isolated
[monster movement state-machine prototype](native-monster-prototype.md) saves
8.1–9.7% of that kernel's sampled CPU time, with 29,774 exact routine comparisons.
It is not integrated and has no measured whole-game FPS gain.

## Actual picture cadence

These windows use the runtime's `vbl_count`, not Hatari's boot VBL number or
reference-board frame index. The old October 28 Hatari window no longer selects
the same part of the demo after the October 29 object-list changes. Screenshots
confirm that VBLs 2050–2150 contain the growing, moving ghost horde.

| Runtime VBL window | Pictures/s displayed | Completed logic ticks/s | Median / longest observed flip interval |
|---|---:|---:|---:|
| 1000–1500, lighter demo | 30.7 | 58.7 | 1 / 13 VBLs |
| 1500–2000, approaching horde | 19.6 | 55.6 | 2 / 14 VBLs |
| 1950–2150, horde | 6.5 | 31.25 | 6 / 17 VBLs |
| **2050–2150, densest sample** | **4.0** | **16.5** | **13 / 17 VBLs** |

In the densest two-second window, eight pictures are displayed and 33 logic
ticks complete. The seven complete flip intervals wholly within the window
are **12–17 VBLs: 240–340 ms**, all longer than the three-VBL / 60 ms heavy-play
objective. The median is 260 ms. These are nominal 50 Hz rates derived from
emulated counters, not host execution speed.

Only eight picture intervals are sampled here; this is a bounded worst-scene
investigation, not full-game statistics. Completed pictures, displayed pictures,
and started renderer calls are separate observations. The broader horde window
contains 26 displayed pictures and 125 completed logic ticks in four seconds.

## Where the time goes in the densest sample

All percentages use the entire profiled machine interval as their denominator,
including native game work, interrupts, bus stalls and waits. Routine attribution
is exclusive: called helpers have their own rows.

| Cost | Share |
|---|---:|
| Sprite drawing, image lookup, baking and prepared-stream construction | 24.8% |
| Native game instructions, all routines | 23.5% |
| Restoration, copies, pending tiles and their damage notification | 16.8% |
| Sprite snapshots and their helpers | 7.3% |
| Sprite matching and damage-cell bookkeeping | 4.9% |
| Other rendering/runtime, sound, borders, input and waits | 22.7% |

The largest individual renderer costs are:

* `mo_prep_draw`: 12.77% (about 256k cycles per completed picture, including its
  Blitter stalls).
* `mo_snapshot`: 7.21% (about 144k cycles per completed picture).
* `blit_go_split`: 6.71% (about 134k cycles per completed picture).
* `pend_apply`: 5.22% (about 105k cycles per completed picture).

The monster loop `$808E–$8413` and probe region `$8F38–$924F` account for 12.82%
of total machine time, or about 55% of the native-game bucket. They are a real
logic target, but eliminating all native game instructions would still leave
more than three quarters of this fixed workload.

Two specific findings affect the next experiment:

1. **Snapshots are repeated.** The profile executes `mo_snapshot` 19 times for
   eight started pictures; the wider horde window has 47 for 26. `render_frame`
   retries its snapshot whenever `rf_vbls` changes during construction, up to
   three attempts. This mechanism is visible in the current code and call
   counts. Determine how many retries correspond to actual video-input changes
   before changing it: a VBL alone can occur while the game is held, but game
   tasks and interrupts also mutate state. Comparing only `frames_done` would
   need proof, especially around the queue-yield path. No retry has been removed
   by this audit.
2. **Pool capacity is not the immediate cause.** There are zero `mo_flush`
   entries in both horde profiles. The densest sample makes six image bakes
   and 27 prepared streams while drawing 418 prepared strips. The 14 MB work
   should move repeated preparation and dispatch out of the hot path, rather
   than merely enlarging the existing pool.

The two-instruction `frame_ready` spin consumes 3.45% in the densest sample,
against about 24% in the lighter sample. Its large light-scene profile rank is
waiting for display synchronization, not evidence that it causes the horde's
long gaps. Do not equate all `render_frame` entry hits with picture calls: that
label is also the spin-loop target. The audit counts picture starts after it.

## A separate scene-transition stall

The 2250–2750 survey also finds a **98-VBL gap, from VBL 2481 to 2579**: about
1.96 seconds without a new picture. That window averages 25.3 pictures/s, which
hides the pause.

A focused profile at 2490–2570 lies inside that gap: no pictures finish and only
two logic ticks complete. Costs differ from the horde: native game work 28.3%,
`pf_tile_draw` 17.4%, `al_char` 12.0%, and `mo_bake` 8.8%. The game is building
the next maze/page while graphics are reconstructed. This needs a transition
working-set/preparation strategy as well as the heavy-play sprite optimization.
The figures describe a mixed transition interval; they do not isolate a single
palette or tile invalidation as its sole cause.

## What to implement first

Prototype **resident build-time sprite programs, shift masks and pre-coloured
images**, using the approved high-memory asset arena. Pair this with a smaller
object-entry path and investigate the snapshot retries. Measure them separately
and together against these exact windows. The current row loop is the largest
individual renderer target, and the complete sprite draw/preparation group is
the largest named functional bucket in the densest sample.

Retain restoration correctness and separately profile `pend_apply`'s queued
updates before proposing a sparse-copy rewrite. The earlier simulator audit's
small duplicate-copy ceiling does not mean all restoration or pending tile work
is cheap, nor does this profile establish that merging damage would save it.

Then add deadline-aware scheduling and verify actual flips against the three-VBL
objective, with exact game progression and MIDI determinism. The observed 4 FPS
needs more than 4x higher presentation throughput to reach 16.7 FPS. Faster
drawing and different logic/picture scheduling both matter; no speedup is
claimed until an implemented comparison demonstrates it.

## Method, checks and reproduction

[`bottleneck_audit.py`](../tools/bottleneck_audit.py) copies the existing executable
into a private directory and sets debugger breakpoints. It does not patch
emulated code, write runtime counters, rebuild the game, or replace the installed
program. At each `vbl_video` entry it observes `frame_ready`: the immediately
following code displays that pending picture. The profiler counts every CPU
instruction in the selected window, with Blitter stalls charged by Hatari.
Per-VBL trace breakpoints use `:noinit` so they cannot reset the profile.

The sum of instruction-profile cycles equals the independent `CycleCounter`
difference exactly. All VBL observations in each window are present. Clean
repeat runs of the two horde windows and the transition window reproduce the
same counters and total cycles; all 101 overlapping VBL observations in the two
horde windows also match exactly, including their cycle counters. The private
executable is byte-identical to the installed one, and its embedded runtime
matches `build/gauntlet/runtime.bin`.

Executable SHA-256:
`b53118ddb9dc377f17de165d0b4a91f172ef45e497bd7781b3b1a97d002718b9`.

```sh
venv/bin/python games/gauntlet/tools/bottleneck_audit.py --start 1000 --stop 1500
venv/bin/python games/gauntlet/tools/bottleneck_audit.py --start 1950 --stop 2150
venv/bin/python games/gauntlet/tools/bottleneck_audit.py --start 2050 --stop 2150
venv/bin/python games/gauntlet/tools/bottleneck_audit.py --start 2250 --stop 2750
venv/bin/python games/gauntlet/tools/bottleneck_audit.py --start 2490 --stop 2570
```

Supply a matching `--map` if profiling a different `--prg`. The current script's
spin-loop/picture-start attribution assumes the unchanged production entry
sequence. Reports contain hashes, raw profiler output, screenshots, actual
VBL/flip observations and separate logic/picture counters under ignored
`build/gauntlet/bottleneck_*`. Final checked reports use `_final` directories.
This is performance evidence only: the audit does not add new reference pixel,
logic lock-step, MIDI, or border-event correctness coverage.
