"""Measure the current renderer's opportunities suggested by STEArcade R-Type.

No runtime changes. Every supplied picture is checked against the existing independent
oracle. CPU instructions and Blitter bus cycles are counted separately, including all
preparation in the measured interval. Initialization and warm-up are reported separately.
This harness does not execute game logic, interrupts, flip waits or the real scheduler.

Example:
    venv/bin/python games/gauntlet/tools/rtype_audit.py --seed 0 --first 2400 --frames 2650
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np

import render_test as RT
import assets
from paths import ROOT, build_dir


PHASES = set("render_frame pal_update alpha_update view_check bar_update pf_update pic_same "
             "text_only ovl_build ovl_classify mo_match ring_validate tr_restore mo_restore "
             "ovl_restore_old pend_apply mo_draw alpha_transparent ovl_draw ovl_save render_done".split())


class Audit(RT.Harness):
    def __init__(self, prg):
        self.phase = "initialization"
        self.cpu_cost = Counter()
        self.bus_cost = Counter()
        self.routine_cpu = Counter()
        self.routine_bus = Counter()
        self.calls = Counter()
        self.passes = Counter()
        self.max_pass = 0
        self.long_passes = 0
        self.shared_passes = 0
        self.restore_seen = set()
        self.duplicate_restore_bus = 0
        super().__init__(prg)
        self.phase_entries = {self.sym[n]: n for n in PHASES}
        self.entry_names = {a: n for a, n in self.plabs}
        self.initialization_cycles = sum(self.cpu_cost.values()) + sum(self.bus_cost.values())
        original = self.sim.blitter.run

        def run_blitter():
            b = self.sim.blitter
            start = b.cycles
            io = self.sim.io
            self.passes[(self.phase, io[0xA3A] & 3, io[0xA3B] & 15)] += 1
            self.shared_passes += not bool(io[0xA3C] & 0x40)
            if self.phase == "mo_restore":
                # Optimistic bus-only ceiling for duplicate copies within this restoration.
                # All copies restore the same clean torus at a fixed ring address.
                dst = b.reg32(0xA32) & 0xFFFFFE
                xc, yc = b.reg16(0xA36), b.reg16(0xA38)
                dx, dy = b.s16(b.reg16(0xA2E)), b.s16(b.reg16(0xA30))
                for _ in range(yc):
                    for x in range(xc):
                        mask = b.reg16(0xA28 if x == 0 else 0xA2C if x == xc - 1 else 0xA2A)
                        assert mask == 0xFFFF and io[0xA3A:0xA3C] == bytes((2, 3))
                        addr = dst & 0xFFFFFF
                        if addr in self.restore_seen:
                            self.duplicate_restore_bus += 8  # one source read and one destination write
                        self.restore_seen.add(addr)
                        dst += dy if x == xc - 1 else dx
            original()
            cycles = b.cycles - start
            self.max_pass = max(self.max_pass, cycles)
            self.long_passes += cycles > 256

        self.sim.blitter.run = run_blitter

    def reset_counts(self):
        for c in (self.cpu_cost, self.bus_cost, self.routine_cpu, self.routine_bus, self.calls, self.passes):
            c.clear()
        self.restore_seen.clear()
        self.duplicate_restore_bus = 0
        self.max_pass = self.long_passes = self.shared_passes = 0

    def run_to_stop(self):
        sim, cpu = self.sim, self.sim.cpu
        used = 0
        while used < 2_000_000_000:
            pc = cpu.r_pc()
            if hasattr(self, "phase_entries"):
                if pc in self.phase_entries:
                    self.phase = self.phase_entries[pc]
                if pc in self.entry_names:
                    self.calls[self.entry_names[pc]] += 1
            label = "rs_generated" if 0x400000 <= pc < 0xD00000 else self.plabs[self.bisect.bisect_right(self.paddr, pc) - 1][1]
            r = cpu.execute(1)
            bus = sim.blitter.cycles
            self.cpu_cost[self.phase] += r.cycles
            self.bus_cost[self.phase] += bus
            self.routine_cpu[label] += r.cycles
            self.routine_bus[label] += bus
            used += r.cycles + bus
            sim.blitter.cycles = 0
            pc = cpu.r_pc()
            if pc in self.stops:
                return self.stops[pc], used
            if pc == self.TRAP1:
                sim.gemdos()
            if pc == 0x600:
                raise RuntimeError("exception: %s" % sim.log)
        raise RuntimeError("68000 budget exceeded at %06x" % cpu.r_pc())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--level", type=int, default=0)
    ap.add_argument("--first", type=int, default=2400)
    ap.add_argument("--frames", type=int, default=2650, help="exclusive scenario end frame")
    ap.add_argument("--every", type=int, default=1)
    ap.add_argument("--warmup", type=int, default=30, help="checked pictures excluded from steady-state totals")
    ap.add_argument("--nobuild", action="store_true")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if args.every < 1 or args.warmup < 0 or args.frames <= args.first:
        ap.error("require every >= 1, warmup >= 0 and frames > first")
    RT.reference_mode([])
    prg = build_dir("gauntlet") / "render_test.prg" if args.nobuild else RT.build_harness()
    h = Audit(prg)
    oracle = assets.Oracle()
    rows = []
    for f, m in RT.scenario(args.seed, args.level, args.frames):
        if f < args.first or (f - args.first) % args.every:
            continue
        h.reset_counts()
        vram, pal, xs = m.vram(), m.palette(), m.xscroll
        arc = RT.arc_mode(m)
        h.sim.mem.w8(h.sym["arc_view"], 0xFF if arc else 0)
        h.put_raw(vram, pal, xs)
        cycles = h.draw()
        got = np.vstack((h.picture(), h.bar()))
        pm = h.pen_map()
        want = np.vstack((oracle.picture_raw(vram, pal, xs, pm, h.pen_pab(), arc),
                          oracle.bar(vram, pal, pm, h.bar_pmap())))
        row = dict(frame=f, cpu=sum(h.cpu_cost.values()), bus=sum(h.bus_cost.values()),
                   draw_cycles=cycles, differing_pixels=int(np.count_nonzero(got != want)),
                   phases={n: dict(cpu=h.cpu_cost[n], bus=h.bus_cost[n])
                           for n in sorted(h.cpu_cost.keys() | h.bus_cost.keys())},
                   routines={n: dict(cpu=h.routine_cpu[n], bus=h.routine_bus[n])
                             for n in sorted(h.routine_cpu.keys() | h.routine_bus.keys())},
                   calls=dict(h.calls), duplicate_restore_bus=h.duplicate_restore_bus,
                   max_pass_bus=h.max_pass, over_256_passes=h.long_passes,
                   shared_passes=h.shared_passes,
                   passes={"%s:%d:%d" % k: v for k, v in sorted(h.passes.items())},
                   objects=h.sim.mem.r16(h.sym["mo_n"]),
                   chain_entries=h.sim.mem.r16(h.sym["mo_count"]),
                   pool_bytes=h.sim.mem.r32(h.sym["mo_pool"]) - 0x35F800)
        rows.append(row)
        if len(rows) % 30 == 0:
            print("checked %d pictures, last frame %d" % (len(rows), f), flush=True)
    measured = rows[args.warmup:]
    if not measured:
        ap.error("no pictures after warm-up")
    phases = {}
    for n in sorted({n for r in measured for n in r["phases"]}):
        phases[n] = {k: float(np.mean([r["phases"].get(n, {}).get(k, 0) for r in measured]))
                     for k in ("cpu", "bus")}
    total = float(np.mean([r["cpu"] + r["bus"] for r in measured]))
    summary = dict(checked=len(rows), measured=len(measured),
                   differing_pictures=sum(r["differing_pixels"] != 0 for r in rows),
                   initialization_cycles=h.initialization_cycles, mean_cycles=total,
                   cold_inclusive_mean_cycles=float(np.mean([r["cpu"] + r["bus"] for r in rows])),
                   median_cycles=float(np.median([r["cpu"] + r["bus"] for r in measured])),
                   phases=phases,
                   duplicate_restore_bus=float(np.mean([r["duplicate_restore_bus"] for r in measured])),
                   mean_objects=float(np.mean([r["objects"] for r in measured])),
                   mean_chain_entries=float(np.mean([r["chain_entries"] for r in measured])),
                   calls_per_picture={n: float(np.mean([r["calls"].get(n, 0) for r in measured]))
                                      for n in ("mo_flush", "mo_bake", "mo_prep", "mo_image", "mo_object")},
                   max_pass_bus=max(r["max_pass_bus"] for r in rows),
                   over_256_passes=sum(r["over_256_passes"] for r in rows),
                   shared_passes=sum(r["shared_passes"] for r in rows))
    out = args.out or build_dir("gauntlet") / ("rtype_audit_s%d_l%d_f%d_e%d.json" %
                                               (args.seed, args.level, args.first, args.every))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dict(arguments={k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
                                  renderer_sha256=hashlib.sha256((ROOT / "games/gauntlet/src/render.s").read_bytes()).hexdigest(),
                                  harness_sha256=hashlib.sha256(prg.read_bytes()).hexdigest(),
                                  summary=summary, pictures=rows), indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    print(out)
    return int(summary["differing_pictures"] != 0)


if __name__ == "__main__":
    raise SystemExit(main())
