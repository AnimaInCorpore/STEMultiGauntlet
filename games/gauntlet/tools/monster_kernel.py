"""Isolated exact replacement for the monster direction/probe kernel ($81FA-$82C5).

Partially evaluate its eight direction states: eliminate direction arithmetic and
branches whose outcomes are known, retaining collision-probe order and arithmetic.
No production binary or patch table is changed. Generated code stays in build/.

    venv/bin/python games/gauntlet/tools/monster_kernel.py --synthetic 2000 --frames 3000

All registers, CCR bits, continuation PC and live RAM must match the original
kernel, executed independently on a 68000. The only permitted memory difference
is the dead JSR/BSR return address four bytes below the entry SP.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys

import numpy as np
from machine68k import CPUType, Machine, Register as R

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
from paths import ROOT, VASM, build_dir
from patch import ste_addr

BASE = 0x600000
ENTRY = 0x81FA
EXITS = {0x82C6, 0x833A}
AREAS = [(0x3F0000, 0x6000), (0x3D0000, 0x2400), (0x3E0000, 0x800)]
PROBES = [0x8F38, 0x9006, 0x90D2, 0x9192]
COORD = [("add", "sub", "d5"), ("sub", "add", "d5"), ("sub", "add", "d4"), ("add", "sub", "d4")]


def generate():
    nodes = {}

    def target(stage, incoming):
        if stage == 4:
            key = (stage, incoming)
        else:
            if stage == 0:
                v = (incoming + 0x400) & 0x1C00
            elif stage == 1:
                v = (incoming - 0x1000) & 0xFFFF
            elif stage == 2:
                v = (incoming - 0x800) & 0x1C00
            else:
                v = (incoming + 0x1000) & 0x1C00
            if v >= 0xC00:
                return target(stage + 1, v)
            key = (stage, v)
        if key not in nodes:
            nodes[key] = "n%d" % len(nodes)
        return nodes[key]

    starts = [target(0, d * 0x400) for d in range(8)]
    lines = ["\torg $%x" % BASE, "entry:", "\tmove.w (a6,d2.w),d6", "\tand.w #$1c00,d6",
             "\tmove.w #$80,d7", "\tmove.w #$7c0,d3", "\tjmp dispatch(pc,d6.w)", "dispatch:"]
    for i, lab in enumerate(starts):
        lines += ["\tbra.w " + lab]
        if i != 7:
            # Extra RAM buys a direct dispatch with no eight-bit index shift.
            lines += ["\tdcb.b 1020,0"]
    emitted = set()
    while len(emitted) < len(nodes):
        key = next(k for k in nodes if k not in emitted)
        emitted.add(key)
        stage, v = key
        lab = nodes[key]
        lines.append(lab + ":")
        if stage == 4:
            # Reproduce X as well as NZVC, including the $FC00 + $400 carry.
            lines += ["\tmove.w #$%04x,d6" % v, "\tadd.w #$400,d6", "\tand.w #$1c00,d6", "\tjmp $82c6.l"]
        else:
            success = target(stage + 1, v)
            collision = target(stage + 1, (2 * v - 0x400) & 0xFFFF)
            forward, backward, reg = COORD[stage]
            lines += ["\tmove.w #$%04x,d6" % v, "\t%s.w d7,%s" % (forward, reg),
                      "\tjsr $%x.l" % PROBES[stage], "\tbmi.w " + success,
                      "\t%s.w d7,%s" % (backward, reg), "\tadd.w d6,d6", "\tsub.w #$400,d6",
                      "\tmove.w (a3,d1.w),d0", "\tand.w #$f,d0", "\tcmp.w #$c,d0",
                      "\tbge.w player_hit", "\tbra.w " + collision]
    lines += ["player_hit:", "\tjmp $833a.l"]
    return "\n".join(lines) + "\n", len(nodes)


class Check:
    def __init__(self, binary):
        self.m = Machine(CPUType.M68000, 16384)
        self.cpu, self.mem = self.m.cpu, self.m.mem
        self.mem.w_block(0, (build_dir("gauntlet") / "program.bin").read_bytes())
        self.mem.w_block(BASE, binary)
        self.original_entry = bytes(self.mem.r_block(ENTRY, 6))
        self.cpu.pulse_reset()
        self.rows = []

    def run(self, regs, sr, areas, pc):
        self.mem.w_block(ENTRY, b"\x4e\xf9" + BASE.to_bytes(4, "big") if pc == BASE else self.original_entry)
        for addr, data in areas:
            self.mem.w_block(addr, data)
        self.cpu.w_sr(sr)
        for i, v in enumerate(regs):
            self.cpu.w_reg(R(i), v)
        # Charge the actual replacement JMP, not only the generated body.
        self.cpu.w_pc(ENTRY)
        cycles = insns = 0
        while self.cpu.r_pc() not in EXITS:
            cycles += self.cpu.execute(1).cycles
            insns += 1
            if insns > 4000:
                raise RuntimeError("kernel failed to return: %x" % self.cpu.r_pc())
        return dict(regs=[self.cpu.r_reg(R(i)) for i in range(16)], sr=self.cpu.r_sr(),
                    pc=self.cpu.r_pc(), cycles=cycles, instructions=insns,
                    areas=[bytes(self.mem.r_block(a, len(d))) for a, d in areas])

    def check(self, regs, sr, areas, label):
        a = self.run(regs, sr, areas, ENTRY)
        b = self.run(regs, sr, areas, BASE)
        for field in ("regs", "sr", "pc"):
            if a[field] != b[field]:
                raise AssertionError("%s: %s differs: %s / %s" % (label, field, a[field], b[field]))
        for i, (addr, data) in enumerate(areas):
            x, y = bytearray(a["areas"][i]), bytearray(b["areas"][i])
            for p in range(regs[15] - 4, regs[15]):
                if addr <= p < addr + len(data):
                    x[p - addr] = y[p - addr] = 0
            if x != y:
                raise AssertionError("%s: live RAM differs at $%x" % (label, addr))
        self.rows.append(dict(label=label, original=a["cycles"], native=b["cycles"],
                              original_instructions=a["instructions"], native_instructions=b["instructions"],
                              exit=a["pc"], direction=(int.from_bytes(areas[0][1][0x4046 + (regs[2] & 0xFFFF):
                                                                                0x4048 + (regs[2] & 0xFFFF)], "big") >> 10) & 7))


def synthetic(check, count):
    rnd = random.Random(0x81FA)
    for case in range(count):
        regs = [rnd.getrandbits(32) for _ in range(16)]
        index = rnd.choice([0, 2, 0x3E, 0x7E, 0x80, 0x7BE, 0x7C0, 0x7FE, rnd.randrange(1024) * 2])
        regs[2] = (rnd.getrandbits(16) << 16) | index
        regs[4] = (regs[4] & 0xFFFF0000) | rnd.choice([0, 0x7FFF, 0x8000, 0xF000, rnd.randrange(65536)])
        regs[5] = (regs[5] & 0xFFFF0000) | rnd.choice([0, 0x7FFF, 0x8000, 0xF080, rnd.randrange(65536)])
        regs[10:16] = [0x3F2000, 0x3F2800, 0x3F3000, 0x3F3800, 0x3F4046, 0x3F4E00]
        vram = bytearray(rnd.randbytes(0x6000))
        # Include empty, ordinary and negative/wall collision cells, and player nibbles.
        for i in range(1024):
            vram[0x2000 + 2 * i:0x2002 + 2 * i] = rnd.choice([0, 0, 1, 0x8000, 0xFFFF]).to_bytes(2, "big")
        o = 0x4046 + index
        w = rnd.randrange(65536) & ~0x1C00 | (case % 8) << 10
        vram[o:o + 2] = w.to_bytes(2, "big")
        areas = [(0x3F0000, bytes(vram)), (0x3D0000, bytes(0x2400)), (0x3E0000, bytes(0x800))]
        check.check(regs, 0x2300 | rnd.randrange(32), areas, "synthetic:%d" % case)


def reference(check, frames, seed, every):
    from stemodel import PortModel
    from cover import Player
    model = PortModel(patched=False)
    rnd = random.Random(seed)
    players = [Player(rnd, k, 300 + 50 * k) for k in range(1 if seed < 10 else rnd.randint(2, 4))] if seed else []
    seen = sampled = 0

    def entry(pc):
        nonlocal seen, sampled
        seen += 1
        if seen % every:
            return
        regs = [model.cpu.get(i) for i in range(16)]
        regs = [ste_addr(v) if i >= 8 and ste_addr(v) is not None else v for i, v in enumerate(regs)]
        areas = [(0x3F0000, model.window_bytes("vram")),
                 (0x3D0000, model.window_bytes("ram") + model.window_bytes("eeprom")),
                 (0x3E0000, model.window_bytes("palette"))]
        check.check(regs, model.cpu.sr, areas, "seed%d:frame%d:call%d" % (seed, model.frame, seen))
        sampled += 1

    model.cpu.hook(ENTRY, entry)
    for f in range(frames):
        for p in players:
            if p.coin(f) and not p.coin(f - 1):
                model.sound.coin(p.k)
            model.inputs[p.k] = 0xFFFF & ~p.joy(f)
        model.step()
        if f and f % 1000 == 0:
            print("reference seed %d frame %d: %d/%d kernel calls checked" % (seed, f, sampled, seen), flush=True)
    return dict(seed=seed, frames=frames, observed_calls=seen, sampled_calls=sampled)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--synthetic", type=int, default=2000)
    ap.add_argument("--frames", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--every", type=int, default=20)
    ap.add_argument("--nobuild", action="store_true")
    args = ap.parse_args()
    if args.synthetic < 0 or args.frames < 0 or args.every < 1:
        ap.error("invalid case counts")
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ref"))
    out = build_dir("gauntlet") / "monster_kernel"
    out.mkdir(exist_ok=True)
    source, nodes = generate()
    binary = out / "kernel.bin"
    if args.nobuild:
        assert (out / "kernel.s").read_text() == source, "stale generated kernel; run without --nobuild"
    else:
        (out / "kernel.s").write_text(source)
        subprocess.run([VASM, "-Fbin", "-quiet", "-m68000", "-o", str(binary), str(out / "kernel.s")], check=True)
    check = Check(binary.read_bytes())
    synthetic(check, args.synthetic)
    observed = reference(check, args.frames, args.seed, args.every) if args.frames else None
    summary = {}
    for group, rows in [("synthetic", check.rows[:args.synthetic]), ("reference", check.rows[args.synthetic:])]:
        old, new = sum(r["original"] for r in rows), sum(r["native"] for r in rows)
        summary[group] = dict(cases=len(rows), original_mean=old / len(rows) if rows else 0,
                              native_mean=new / len(rows) if rows else 0,
                              saving_percent=100 * (old - new) / old if old else 0,
                              slower=sum(r["native"] > r["original"] for r in rows),
                              exits=dict(Counter(hex(r["exit"]) for r in rows)),
                              directions=dict(Counter(r["direction"] for r in rows)))
    report = dict(arguments=vars(args), nodes=nodes, native_bytes=binary.stat().st_size,
                  source_sha256=hashlib.sha256(source.encode()).hexdigest(), reference=observed,
                  summary=summary, cases=check.rows)
    dest = out / ("seed%d_%d.json" % (args.seed, args.frames))
    dest.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, indent=2))
    print(dest)


if __name__ == "__main__":
    main()
