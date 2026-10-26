# STEGauntlet

Atari Games' **Gauntlet** (1985) on the **Atari STE**, aimed at fast play and, in the end, networked play over the
MIDI ports in the spirit of MIDI-Maze: up to four STEs linked in a MIDI ring, every player with a full screen of
their own.

![Gauntlet on the STE (Hatari): the full-screen maze with the status bar below it](games/gauntlet/docs/screenshot.png)

**Note: this project is AI-assisted.** Much of its code and documentation was written by AI coding agents (Claude
Code) under the author's direction. Correctness is checked by testing rather than trust: the patched program runs
against the original, and the STE's pictures are compared with a reference renderer pixel for pixel.

## Status

- **Playable on one STE**, 1-4 players (keyboard, two joysticks, two Jaguar pads / PowerPads), with music, effects
  and speech. It started as the Gauntlet port of [STEArcade](https://github.com/AnimaInCorpore/STEArcade) (imported
  2026-10-26 from commit `0ba04dc`).
- **Full-screen layout:** the top and bottom borders are open (276 lines, as in stefastbobs2). The maze fills the
  whole 320 pixels and the arcade's 240 lines and scrolls in hardware. The arcade's side panel moved into a status
  bar in the bottom border: a separate static image that a Timer B raster split switches to (video address and
  palette) at line 240.
- **The game sees the wider screen too:** 24 small patches to the arcade program widen its own screen bounds by
  88 pixels. Players can walk across the whole picture, monsters stay alive there, generators and magic act on
  everything shown, and the camera centres the players in 320 pixels.
- **Speed:** the game logic runs at the arcade's 60 frames a second. Pictures (Hatari): about 27 a second in light
  play, 20 with a message box up; large ghost hordes drop well below 25.
- **Networking:** not in the game yet. The emulator side is ready: the F030Arcade Hatari can link instances over
  emulated MIDI cables (see [Testing a MIDI ring](#testing-a-midi-ring-in-hatari)).

| | |
|---|---|
| Machine | Atari STE, 8 MHz, **4 MB**, no accelerator (the program takes the whole machine: **Esc resets** the STE) |
| Picture | 320 x 276, 16 colours: maze in lines 0-239, status bar in lines 240-275 |
| Game | the arcade's own 68010 program, run natively on the 68000 and patched in place (nothing is translated) |

## How it works

The arcade's main CPU is a 68010, so its program runs on the STE's 68000 at its own addresses, with only the memory
areas the STE lacks moved and the I/O replaced by calls into a runtime. The 6502 sound board is modelled: the sound
commands drive a player on the YM2149 and the DMA sound, which also plays the speech. The picture is drawn by a
Blitter renderer: a hardware-scrolled ring of the playfield, motion objects baked into short HOG Blitter passes, and
the alphanumerics on top. [games/gauntlet/README.md](games/gauntlet/README.md) documents the port in detail.

The status bar shows each player's score, health and inventory (or INSERT COIN), the class names and the level:
players 1 and 2 in the upper band, 3 and 4 in the lower one. Its layout is a small table in
[tools/bar.py](games/gauntlet/tools/bar.py). On the title and high-score screens the text uses the whole picture and
the bar is empty.

## Building

The ROM set is not part of the repository. Put MAME's `gauntlet` set (rev 14, MAME's file names) at
`assets/gauntlet.zip`; [games/gauntlet/docs/rom_manifest.json](games/gauntlet/docs/rom_manifest.json) lists the 20
files with their checksums. The build verifies the archive, unpacks it to `assets/extracted/` and embeds everything
in the program: no ROM files are needed at run time.

Needed:

- Python 3 with `numpy`, `pillow` and `machine68k` in `venv/` (on Windows: MSYS2's mingw64 Python, for example
  `C:/msys64/mingw64/bin/python3.exe -m venv --system-site-packages venv`)
- vasm and vlink: taken from `C:/Arbeit/F030Arcade/third_party/` on Windows, or set `VASM` and `VLINK`
- the tests' reference board compiles MAME's 68010 core once: a C++ compiler (`c++`, or set `CXX`)

```bash
venv/bin/python games/gauntlet/tools/build.py
```

That writes `run/gauntlet/GAUNTLET.PRG`. Options: `--sim` builds the variant the simulator tests use;
`-D SHOWFPS=1` shows the picture rate of the last second in the middle of the status bar.

The patcher starts from coverage data of the original program in `build/gauntlet/` (`cover_*.pkl`). If it is
missing, make it first (about 10 minutes):

```bash
venv/bin/python games/gauntlet/ref/cover.py -1 420
```

```bash
for s in 0 1 2 3 4 11 12 13 14 15; do venv/bin/python games/gauntlet/ref/cover.py $s 15000; done
```

## Running

In Hatari (the pinned F030Arcade build), from PowerShell; this waits 30 seconds and saves a screenshot to
`run/gauntlet/shot.png`:

```bash
powershell -ExecutionPolicy Bypass -File tools/windows/run.ps1 -Game gauntlet -Prg GAUNTLET.PRG -Wait 30 -Keep
```

On a real STE, start `GAUNTLET.PRG` from the desktop.

| | Keyboard | Joystick / pad |
|---|---|---|
| Coin (players 1-4) | 5 / 6 / 7 / 8 | Option (Jaguar pad) |
| Move | arrow keys | stick / pad |
| Fire | Space, Control, Z | fire button, pad A |
| Magic, start (after a coin) | Alternate, X | pad B / C |
| Reset the STE | Esc | |

Joystick port 1 plays player 1, joystick port 0 (the mouse port) player 2. Jaguar pad A plays player 1, pad B player 2.

## Testing

```bash
venv/bin/python games/gauntlet/tools/render_test.py --seed 1 --level 5
```

```bash
venv/bin/python games/gauntlet/tools/sprite_test.py
```

```bash
venv/bin/python games/gauntlet/tools/logic_test.py 8000 --seed 12
```

- `render_test.py`: the STE's pictures and status bar, drawn by the real renderer in a simulator, against the
  reference renderer, pixel for pixel. Scenarios: the attract mode (seed 0) or random play (seeds 1-19, 1-4
  players), in any level. `--profile` breaks the cost of a picture down by routine.
- `sprite_test.py`: motion objects at every screen edge, all 16 shifts, transparent holes, shadows and 64 KB crossings.
- `logic_test.py`: the patched program against the original, frame for frame.

The sound tests and the checks of the reference board against MAME 0.289 are listed in the
[game README](games/gauntlet/README.md).

## Testing a MIDI ring in Hatari

The F030Arcade Hatari (branch `midi-net` of its `third_party/hatari`) can connect instances with emulated MIDI
cables over TCP:

```
--midi-net-in  [host:]port   MIDI IN: the one connection accepted on this port
--midi-net-out host:port     MIDI OUT: a connection to the next machine's MIDI IN
```

The bytes travel raw at an emulated 31250 bit/s; a cable that is not connected yet loses what is sent, and
connections are retried by themselves, so the instances can start in any order. Run the instances at normal speed
(no fast forward). To start 2-4 instances already cabled as a ring (machine k's MIDI OUT to machine k+1's MIDI IN),
each in its own folder `run/midiring/<k>/`:

```bash
powershell -ExecutionPolicy Bypass -File tools/windows/midiring.ps1 -Count 4
```

## Networked play: the plan

Every STE runs the whole game for all players; only the joystick inputs travel around the MIDI ring
(deterministic lockstep, as MIDI-Maze does):

1. Each game tick, every machine sends a short packet (machine id, tick number, its input) along the ring. Each
   machine forwards the packets of the others and drops its own when it comes back.
2. A machine runs tick N only when the inputs of all players for tick N are in, with an input delay of 2-3 ticks to
   hide the latency (about 5 ms around a ring of four; the traffic is about 1 KB/s of MIDI's 3 KB/s).
3. The game's ticks are then driven by the agreed inputs, never dropped or delivered mid-frame as the single-machine
   runtime does today. Coins and starts are inputs too; machine 1 sends the DIP settings and the high scores at the
   start. A checksum of the game's state now and then detects a machine that went out of step.
4. Later: a view of its own per player. The arcade keeps all players on one shared screen, so this needs changes to
   the game's own logic.

## Repository layout

```
games/gauntlet/     the port: src/ (68000 runtime and renderer), tools/ (build, patcher, assets, tests),
                    ref/ (coverage, MAME comparisons), docs/ (screenshot, palette, ROM manifest)
engine/             shared Python modules (68010 and 6502 cores from MAME, sound chips, simulator) and
                    engine/rt/ (shared 68000 runtime: borders, IKBD, Jaguar pads)
tools/              Hatari helpers (windows/run.ps1, windows/midiring.ps1, hatari.sh)
docs/               the renderer and porting notes inherited from STEArcade
assets/             the ROM archive (not in git)
build/, run/        generated data and the program (not in git)
```

[AGENTS.md](AGENTS.md) holds the renderer rules every change must follow.

## Credits

Gauntlet © 1985 Atari Games. The game title and logo are trademarks of their owners; the screenshot shows the
original game's graphics. This project is not affiliated with or endorsed by them.

Based on STEArcade by Sascha Springer. The Blitter sprite method comes from stefastbobs2; the reference board uses
MAME's 68010 and 6502 cores.
