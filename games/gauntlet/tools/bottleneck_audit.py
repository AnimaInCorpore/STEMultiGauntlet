"""Profile an unchanged Gauntlet executable in pinned Hatari, with actual flip gaps.

    venv/bin/python games/gauntlet/tools/bottleneck_audit.py --start 2250 --stop 2750

Windows are the game's own vbl_count, not wall-clock time or Hatari boot VBLs.
The debugger observes the existing counters; no emulated code/data is patched.
Raw output and a private executable copy stay under build/gauntlet/bottleneck_*.
"""
import argparse
import bisect
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[3]


def symbols(path):
    syms, code = {}, []
    section = None
    for line in path.read_text().splitlines():
        if line.startswith("Symbols of "):
            section = line.split()[2].rstrip(":")
        m = re.match(r"\s+0x([0-9a-f]+) (\S+): .*reloc", line)
        if m:
            addr, name = int(m[1], 16), m[2]
            syms[name] = addr
            if section == ".text" and not name.startswith(".") and "$" not in name:
                code.append((addr, name))
    return syms, sorted(code)


def cost_group(name):
    if name == "game":
        return "native game"
    if name in {"mo_draw", "mo_object", "mo_image", "mo_flush", "mo_bake", "mo_prep", "mo_prep_draw",
                "mo_strip_draw", "mo_strip_shadow", "shadow_fast"} or name.startswith("pr_"):
        return "sprite drawing and preparation"
    if name in {"mo_snapshot", "mo_bands", "mo_lists_set", "mo_retarget", "mo_recs_kept", "mo_ram_same",
                "mo_ram_copy", "mo_front_walk", "mo_general", "mo_place_memo", "mo_place", "mo_lines", "mo_record"}:
        return "sprite snapshots"
    if name == "mo_match" or name.startswith("mk_"):
        return "sprite matching and damage cells"
    if name in {"ring_validate", "copy_rect_s", "copy_rect", "copy_cols", "copy_piece", "mo_restore", "mo_rect",
                "dmg_add", "ovl_restore_old", "rect_minus", "copy_rect_m", "pend_apply", "touch", "bd_pieces",
                "bd_lines", "bd_lines_d"} or name.startswith("blit_go"):
        return "restoration, copies and pending tiles"
    return "other runtime and rendering"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", type=int, default=2250)
    ap.add_argument("--stop", type=int, default=2750)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--prg", type=Path, default=ROOT / "run/gauntlet/GAUNTLET.PRG")
    ap.add_argument("--map", type=Path, default=ROOT / "build/gauntlet/gauntlet_rt.map")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if args.start < 1 or args.stop <= args.start:
        ap.error("require 0 < start < stop")
    out = (args.out or ROOT / ("build/gauntlet/bottleneck_%d_%d" % (args.start, args.stop))).resolve()
    out.mkdir(parents=True, exist_ok=True)
    syms, labels = symbols(args.map)
    exe = out / "GAUNTLET.PRG"
    shutil.copy2(args.prg, exe)
    shutil.copy2(args.map, out / "runtime.map")
    for name in ("profile.txt", "summary.json", "done.bin", "start.bin", "stop.bin"):
        (out / name).unlink(missing_ok=True)

    def cmdfile(name, lines):
        p = out / name
        p.write_text("\n".join(lines) + "\n")
        return p

    def value(name, width="l"):
        return "'($%x).%s'" % (syms[name], width)

    tick_line = "echo AUDIT_TICK %s %s %s %s %s %s 'CycleCounter'\\n" % (
        value("vbl_count"), value("frames_done"), value("pictures"),
        value("frame_ready", "b"), value("in_game", "b"), value("starving", "b"))
    tick = cmdfile("tick.ini", [tick_line])
    stop = cmdfile("stop.ini", [
        tick_line,
        "savebin %s $%x #24" % (out / "stop.bin", syms["vbl_count"]),
        "savebin %s $3c1000 #80" % (out / "crash.bin"),
        "screenshot " + str(out / "stop.png"),
        "profile save " + str(out / "profile.txt"),
        "profile off",
        "savebin %s $%x #4" % (out / "done.bin", syms["vbl_count"]),
        "quit",
    ])
    cond = "pc = $%x && ($%x).l" % (syms["vbl_video"], syms["vbl_count"])
    start = cmdfile("start.ini", [
        tick_line,
        "savebin %s $%x #24" % (out / "start.bin", syms["vbl_count"]),
        "screenshot " + str(out / "start.png"),
        "profile on",
        "b pc = $%x :quiet :noinit :file %s" % (syms["vbl_video"], tick),
        "b %s = #%d :once :quiet :trace :file %s" % (cond, args.stop, stop),
    ])
    init = cmdfile("init.ini", ["b %s = #%d :once :quiet :trace :file %s" % (cond, args.start, start)])
    hatari = Path(os.environ.get("HATARI", str(Path.home() / "Work/F030Arcade/third_party/hatari/build/src/hatari")))
    tos = Path(os.environ.get("TOS", str(Path.home() / "Work/F030Arcade/third_party/tos/tos206de.img")))
    command = [str(hatari), "--machine", "ste", "--memsize", "14", "--tos", str(tos),
               "--fast-boot", "true", "--cpu-exact", "true", "--compatible", "true",
               "--sound", "off", "--fast-forward", "true", "--confirm-quit", "off",
               "--statusbar", "false", "--borders", "true", "--log-file", str(out / "hatari.log"),
               "--parse", str(init), str(exe)]
    with (out / "debug.log").open("w") as log:
        proc = subprocess.Popen(command, cwd=out, stdout=log, stderr=subprocess.STDOUT,
                                env=dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy"))
        try:
            started = last_update = time.monotonic()
            while proc.poll() is None:
                if time.monotonic() - started > args.timeout:
                    raise RuntimeError("Hatari timeout; see " + str(out / "debug.log"))
                if time.monotonic() - last_update >= 30:
                    print("Hatari running, %.0f seconds; %s" % (time.monotonic() - started, out), flush=True)
                    last_update = time.monotonic()
                time.sleep(0.25)
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
    if proc.returncode or not (out / "done.bin").exists():
        raise RuntimeError("Hatari did not finish the window; see " + str(out / "debug.log"))

    ticks = {}
    debug_log = (out / "debug.log").read_text()
    assert "not found." not in debug_log and "Expression ERROR" not in debug_log, "debugger command failed"
    for m in re.finditer(r"^AUDIT_TICK ((?:\$[0-9a-f]+\s*){7})", debug_log, re.M):
        vals = [int(x, 16) for x in re.findall(r"\$([0-9a-f]+)", m[1])]
        ticks[vals[0]] = dict(zip(("vbl", "logic", "pictures", "ready", "in_game", "starving", "cycles"), vals))
    if set(ticks) != set(range(args.start, args.stop + 1)):
        raise RuntimeError("missing VBL observations: %s" % sorted(set(range(args.start, args.stop + 1)) - ticks.keys()))
    ordered = [ticks[k] for k in sorted(ticks)]
    first, last = ordered[0], ordered[-1]
    # A ready picture is displayed by the immediately following vbl_video instructions.
    flips = [r["vbl"] for r in ordered if r["ready"]]
    gaps = np.diff(flips)
    costs, counts = Counter(), Counter()
    addrlist = [a for a, _ in labels]
    instructions = []
    for line in (out / "profile.txt").read_text().splitlines():
        m = re.match(r"\$?([0-9a-fA-F]+)\s.*% \((\d+), (\d+), \d+, \d+\)$", line)
        if not m:
            continue
        pc, count, cycles = int(m[1], 16), int(m[2]), int(m[3])
        idx = bisect.bisect_right(addrlist, pc) - 1
        routine = "game" if pc < 0x50000 else labels[idx][1] if idx >= 0 else "other"
        costs[routine] += cycles
        counts[routine] += count
        instructions.append(dict(pc=pc, count=count, cycles=cycles, routine=routine, disassembly=line))
    total = sum(costs.values())
    assert total > 0, "empty instruction profile"
    elapsed = (last["cycles"] - first["cycles"]) & 0xFFFFFFFF
    assert total == elapsed, "profile reset, missed cycles or saturated instruction counters"
    by_pc = {r["pc"]: r for r in instructions}
    grouped = Counter()
    for name, cycles in costs.items():
        grouped[cost_group(name)] += cycles
    secs = (args.stop - args.start) / 50
    logic = last["logic"] - first["logic"]
    pictures = last["pictures"] - first["pictures"]
    game = [r for r in instructions if r["pc"] < 0x50000]
    pages = Counter()
    for r in game:
        pages[r["pc"] & ~255] += r["cycles"]
    summary = dict(window=[args.start, args.stop], nominal_seconds=secs, logic_ticks=logic,
                   logic_ticks_per_second=logic / secs, completed_pictures=pictures,
                   completed_pictures_per_second=pictures / secs,
                   displayed_pictures_in_half_open_window=sum(r["ready"] != 0 for r in ordered[:-1]),
                   displayed_pictures_per_second=sum(r["ready"] != 0 for r in ordered[:-1]) / secs,
                   flip_intervals_vbl=dict(min=int(gaps.min()), median=float(np.median(gaps)),
                                           p90=float(np.percentile(gaps, 90)), max=int(gaps.max()),
                                           over_three=int((gaps > 3).sum()), count=len(gaps)) if len(gaps) else {},
                   total_profile_cycles=total,
                   elapsed_counter_cycles=elapsed,
                   # The unchanged production render_frame begins with a six-byte TST and a two-byte BNE.
                   # Repeated hits of that entry are spin-loop iterations, not picture calls.
                   flip_wait_cycles=sum(by_pc.get(syms["render_frame"] + off, {}).get("cycles", 0) for off in (0, 6)),
                   started_pictures_after_wait=by_pc.get(syms["render_frame"] + 8, {}).get("count", 0),
                   entry_instruction_counts={name: by_pc.get(syms[name], {}).get("count", 0)
                                             for name in ("mo_snapshot", "mo_match", "mo_draw", "mo_prep_draw",
                                                          "mo_bake", "mo_prep", "mo_flush")},
                   groups=[dict(name=k, cycles=v, percent=100 * v / total) for k, v in grouped.most_common()],
                   monster_loop_and_probes_cycles=sum(r["cycles"] for r in instructions
                                                      if 0x808E <= r["pc"] < 0x8414 or 0x8F38 <= r["pc"] < 0x9250),
                   routines=[dict(name=k, cycles=v, percent=100 * v / total,
                                  instructions=counts[k],
                                  per_completed_picture=v / pictures if pictures else None)
                             for k, v in costs.most_common()],
                   hot_game_pages=[dict(address=hex(k), cycles=v, percent=100 * v / total)
                                   for k, v in pages.most_common(15)],
                   hot_instructions=sorted(instructions, key=lambda r: -r["cycles"])[:30])
    report = dict(command=command, executable_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
                  map_sha256=hashlib.sha256(args.map.read_bytes()).hexdigest(),
                  summary=summary, observations=ordered)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("routines", "hot_instructions")}, indent=2))
    for r in summary["routines"][:15]:
        print("%-24s %5.1f%% %8.0f cycles/picture" % (r["name"], r["percent"], r["per_completed_picture"] or 0))
    print(out / "summary.json")


if __name__ == "__main__":
    main()
