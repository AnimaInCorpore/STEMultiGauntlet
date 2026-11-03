# Exact monster movement replacement: first prototype

2026-11-03. The user permits replacing game routines with different algorithms
when their result is identical. The original instruction sequence is not a
constraint. This prototype applies that permission to the movement/probe kernel
at `$81FA–$82C5`, inside the hot native monster loop.

**Result:** the replacement saves 8.1–9.7% of this kernel's CPU cycles on sampled
states from independent original gameplay, including its entry JMP. All 29,774
compared cases agree on all registers, the complete SR/CCR, continuation PC and
live RAM. This is a small local optimization, not an overall FPS improvement.
The replacement is isolated; the production patcher, renderer, scheduler and
installed executable are unchanged.

## Different approach

The original code rotates an eight-way direction through four probe stages,
repeatedly adding, masking and comparing direction bits. Collision results can
change the next direction, so simply replacing it with a fixed direction order
would be wrong.

[`monster_kernel.py`](../tools/monster_kernel.py) partially evaluates that state
machine at build time. The generator follows all eight entry directions and
both collision outcomes, generating 21 reachable states. Direction arithmetic
and branches with known outcomes disappear; the original collision probes,
their order, candidate coordinates and player-hit decisions remain. A sparse
dispatch table trades about 7 KB of padding for avoiding a run-time index shift.
Total generated code and padding: **7,888 bytes**, placed at `$600000` in the
private 14 MB test machine.

The terminal paths still execute the original final addition and mask, preserving
the extend flag as well as NZVC, including the `$FC00 + $0400` wrap. Collision
paths retain arithmetic whose flags or register values matter. The result
continues at exactly `$82C6` or `$833A`, as the original does.

The test enters the replacement through an actual six-byte absolute JMP at
`$81FA`, and charges that instruction. Timing only the generated body would
overstate the saving.

## Equivalence checks and CPU measurements

Both versions execute on an emulated **68000**. Captured gameplay states come
from the independent original program in `PortModel(patched=False)`, using the
MAME 68010 reference core. Every tenth entry to the kernel is sampled; its
registers and RAM are copied to the separate 68000 test machine. Original code
and replacement then run independently from identical inputs.

| Source | Original frames traversed | Kernel cases compared | Original mean cycles | Replacement mean cycles | Saving |
|---|---:|---:|---:|---:|---:|
| Synthetic boundaries and random states | — | 4,000 | 585.19 | 539.91 | 7.74% |
| Attract, seed 0 | 9,000 | 199 | 499.36 | 450.69 | 9.75% |
| Multiplayer, seed 12 | 6,000 | 6,516 | 474.10 | 435.33 | 8.18% |
| Single player, seed 4 | 6,000 | 19,059 | 480.97 | 441.90 | 8.12% |

All comparisons pass. Synthetic cases balance all eight directions, vary initial
CCR bits and register high words, and include grid boundaries, signed coordinate
extremes, word wraps, empty/ordinary/negative collision cells and player nibbles.
There are 96 synthetic player-hit continuations and five in sampled seed-4 play.
All eight directions also occur in the sampled multiplayer and single-player
states. Most paths improve, but 91 synthetic cases and three sampled seed-4 cases
are slower; these costs are included in the means.

The complete input RAM regions are compared after execution. The sole allowed
memory difference is the **dead return-address slot four bytes below the entry
SP**, because a generated JSR returns to a different code address than an
original BSR. The SP, live stack, every other compared RAM byte, all sixteen
registers, SR and exit PC must agree. This exclusion is narrower than the
existing whole-game logic test's dead-stack exclusion.

These are **25,774 original-game kernel snapshots**, plus 4,000 synthetic cases.
They are not 21,000 frames of the *modified* game in full lock-step: only the
original game advances between snapshots. There is no claim of full-game,
interrupt-interleaving, MIDI, or picture-equivalence certification for a patched
game. The isolated CPU timing does not include STE video/Blitter bus contention
and is not a pinned-Hatari picture-rate result.

## Implication for further work

The user-authorized algorithm replacement is practical and can be checked at
strict routine boundaries. This first kernel is only part of the native game's
time. Its local saving does not address the larger sprite drawing/preparation
and restoration buckets identified in [the running-game profile](bottleneck-audit.md).
Keep it as a measured candidate, alongside broader changes to monster iteration
and collision indexing. Preserve object update order, wrap semantics and RNG;
changing those would change gameplay even if a picture initially looked alike.

Before production integration, validate complete modified-game progression under
the runtime's interrupt schedule, including heavy frames, deaths, restarts and
multiplayer, then measure the effect in pinned Hatari. Loader/patcher integration
and that validation have not been performed. The current raw program has not
been overwritten by this experiment.

## Reproduction

```sh
venv/bin/python games/gauntlet/tools/monster_kernel.py --synthetic 4000 --frames 9000 --seed 0 --every 10
venv/bin/python games/gauntlet/tools/monster_kernel.py --synthetic 0 --frames 6000 --seed 12 --every 10 --nobuild
venv/bin/python games/gauntlet/tools/monster_kernel.py --synthetic 0 --frames 6000 --seed 4 --every 10 --nobuild
```

Generated source/binary and per-case JSON reports stay under ignored
`build/gauntlet/monster_kernel/`. No reference snapshots or ROM data are committed.
