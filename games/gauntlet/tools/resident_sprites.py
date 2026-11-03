"""Collect and build resident, pre-coloured sprite programs for the 14 MB target.

    python games/gauntlet/tools/resident_sprites.py collect --seed 0 --frames 3600 --fixtures
    python games/gauntlet/tools/resident_sprites.py collect --seed 12 --level 5 --frames 4000
    python games/gauntlet/tools/resident_sprites.py build --order mask

The generated SPRITES.DAT is ROM-derived and private. Every offset in the pack is
relative to its base, including code/stream/source records. Unknown image/colour
pairs retain the ordinary runtime bake/draw path. Partial band draws use the same
pre-coloured image's original row-order words; whole strips use compiled pieces.
"""
import argparse
import base64
import hashlib
import json
import re
import random
import struct
import subprocess
import sys

import numpy as np
from machine68k import Register as R

import render_test as RT
from paths import VASM, VLINK, build_dir
from sprite_programs import pass_of as pass16

BASE = 0x400000
LIMIT = 0xD00000
STRIDE = 448
IMG_HDR = 72
TAG = 0x5253
BUILD = build_dir("gauntlet")


class Collector:
    def __init__(self, entries):
        self.entries = entries
        self.draws = 0

    def bind(self, h):
        pc = h.sym["mo_object"]
        target = h.sym["mo_image"]
        while True:
            size, text = h.sim.cpu.disassemble(pc)
            nums = re.findall(r"\$([0-9a-fA-F]+)", text)
            if text.startswith("bsr") and nums and int(nums[-1], 16) == target:
                return_pc = pc + size
                break
            if text == "rts":
                raise RuntimeError("cannot locate mo_image return")
            pc += size

        def observe(pc):
            if pc != return_pc:
                return
            mem, sy, cpu = h.sim.mem, h.sym, h.sim.cpu
            rec, image = cpu.r_reg(R.A6), cpu.r_reg(R.A0)
            code = (mem.r16(rec) & 0x7FFF) ^ 0x800
            size = mem.r16(rec + 4) & 0x7F
            strip = mem.r16(sy["ob_strip"])
            pal = mem.r16(sy["ob_pal"])
            mapping = bytes(mem.r_block(sy["pen_pab"] + 256 + 16 * pal, 16))
            key = code | (size << 16) | (strip << 23)
            ident = "%08x:%s" % (key, mapping.hex())
            self.draws += 1
            if ident in self.entries:
                self.entries[ident]["uses"] += 1
                return
            rows, sw = mem.r16(image), mem.r16(image + 2)
            masks = [mem.r32(image + IMG_HDR + 4 * y) for y in range(rows)]
            ndata = sum(m != 0 for m in masks) * sw * 8
            raw = bytes(mem.r_block(image, IMG_HDR + 8 * rows + ndata))
            # The baseline image has zero pointers here; strip out any lazy preparation.
            raw = raw[:6] + bytes(IMG_HDR - 6) + raw[IMG_HDR:]
            self.entries[ident] = dict(key=key, mapping=mapping.hex(),
                                       image=base64.b64encode(raw).decode(), uses=1)

        h.observer = observe


def collect(args):
    path = BUILD / "resident_inputs.json"
    entries = json.loads(path.read_text())["entries"] if path.exists() else {}
    collector = Collector(entries)
    prg = RT.build_harness(["RESIDENT=0"])
    RT.reference_mode([])
    h = RT.Harness(prg)
    collector.bind(h)
    import assets
    oracle = assets.Oracle()
    checked = 0
    for f, m in RT.scenario(args.seed, args.level, args.frames):
        if f < args.first or (f - args.first) % args.every:
            continue
        v, pal, xs = m.vram(), m.palette(), m.xscroll
        arc = RT.arc_mode(m)
        h.sim.mem.w8(h.sym["arc_view"], 255 if arc else 0)
        h.put_raw(v, pal, xs)
        h.draw()
        pm = h.pen_map()
        want = np.vstack((oracle.picture_raw(v, pal, xs, pm, h.pen_pab(), arc),
                          oracle.bar(v, pal, pm, h.bar_pmap())))
        assert np.array_equal(np.vstack((h.picture(), h.bar())), want), "baseline picture differs at %d" % f
        checked += 1
        if checked % 200 == 0:
            print("collected %d checked pictures, %d image/colour pairs" % (checked, len(entries)), flush=True)
    if args.fixtures:
        import sprite_test
        original, argv = RT.Harness, sys.argv

        class Observed(original):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                collector.bind(self)

        try:
            RT.Harness = Observed
            sys.argv = ["sprite_test.py", "--nobuild"]
            assert sprite_test.main() == 0
        finally:
            RT.Harness, sys.argv = original, argv
    path.write_text(json.dumps(dict(entries=entries), separators=(",", ":")) + "\n")
    print("%d draws collected; %d pairs, %s" % (collector.draws, len(entries), path), flush=True)


def decode_image(raw):
    rows, sw, tw = struct.unpack_from(">HHH", raw)
    masks = list(struct.unpack_from(">%dI" % rows, raw, IMG_HDR))
    pix = np.zeros((rows, 32), np.uint8)
    p = IMG_HDR + 8 * rows
    for y, mask in enumerate(masks):
        if not mask:
            continue
        words = struct.unpack_from(">%dH" % (4 * sw), raw, p)
        p += sw * 8
        for x in range(sw * 16):
            pix[y, x] = sum(((words[plane * sw + x // 16] >> (15 - x % 16)) & 1) << plane for plane in range(4))
    assert p == len(raw)
    return masks, pix


def pieces_of(masks, order):
    pieces = []
    for y, mask in enumerate(masks):
        if not mask:
            continue
        left = 32 - mask.bit_length()
        right = 32 - ((mask & -mask).bit_length() - 1)
        width = right - left
        nw = 1 if width <= 16 else 2
        aligned = mask << left >> (32 - 16 * nw)
        pieces.append((y, left, width, nw, aligned))
    if order == "mask":
        groups = {}
        for p in pieces:
            groups.setdefault((p[3], p[4], p[1] & 15, p[2]), []).append(p)
        pieces = [p for group in groups.values() for p in group]
    return pieces


def pass_of(piece, shift):
    y, left, width, nw, mask = piece
    k = (shift + left) & 15
    xc = nw + int(k + width > 16 * nw)
    if nw == 1:
        # Shared Time Pilot/stefastbobs2 geometry; extend it below for Gauntlet's wider rows.
        _, e1, e3, xc, _, ctl = pass16(mask, k)
        words = [e1] if xc == 1 else [e1, e3]
    else:
        m = mask << (16 * (xc - nw)) >> k
        words = [(m >> (16 * (xc - 1 - j))) & 0xFFFF for j in range(xc)]
        ctl = 0xC000 | (0x40 if xc > nw else 0) | k
    dst = y * STRIDE + ((shift + left) >> 4) * 8
    # Four planes, copy operation. A partial mask adds a destination read.
    bus = 16 * (nw + xc + sum(w != 0xFFFF for w in words))
    assert bus <= 256
    return dst, xc, 2 - 8 * (xc - 1), words, ctl


def program(pieces, shift):
    body, stream = [], bytearray()
    prev_dst, prev_xc, prev_dyi, prev_ctl = 0, None, None, None
    prev_masks = [None, None, None]
    for piece in pieces:
        dst, xc, dyi, masks, ctl = pass_of(piece, shift)
        delta = dst - prev_dst
        assert -32768 <= delta <= 32767
        if delta:
            body.append("\tlea %d(a3),a3" % delta)
        body.append("\tmove.l a3,(a4)")
        if xc != prev_xc:
            body.append("\tmove.w #%d,$ffff8a36.w" % xc)
        if dyi != prev_dyi:
            body.append("\tmove.w #%d,$ffff8a30.w" % dyi)
        for slot, mask in zip(([0] if xc == 1 else [0, 2] if xc == 2 else [0, 1, 2]), masks):
            if prev_masks[slot] != mask:
                body.append("\tmove.w (a0)+,%s" % ("(a1)" if slot == 0 else "(a6)" if slot == 2 else "$ffff8a2a.w"))
                stream += struct.pack(">H", mask)
                prev_masks[slot] = mask
        body.append("\tmove.w d1,(a5)")
        if ctl != prev_ctl:
            body.append("\tmove.w (a0)+,(a2)")
            stream += struct.pack(">H", ctl)
        else:
            body.append("\tmove.b d2,(a2)")
        prev_dst, prev_xc, prev_dyi, prev_ctl = dst, xc, dyi, ctl
    body.append("\trts")
    return tuple(body), bytes(stream)


def source_words(pieces, pixels):
    words = []
    for y, left, width, nw, mask in pieces:
        row = list(pixels[y, left:left + width]) + [0] * (16 * nw - width)
        for plane in range(4):
            for j in range(nw):
                words.append(sum(((int(row[16 * j + x]) >> plane) & 1) << (15 - x) for x in range(16)))
    return struct.pack(">%dH" % len(words), *words)


def hash_slot(key, mapping, cap):
    return (key ^ (key >> 8) ^ int.from_bytes(mapping[:4], "big")) & (cap - 1)


def build(args):
    inputs = BUILD / "resident_inputs.json"
    entries = list(json.loads(inputs.read_text())["entries"].values())
    entries.sort(key=lambda e: (e["key"], e["mapping"]))
    cap = 256
    while cap < 2 * len(entries):
        cap *= 2
    routines, streams, shapes, assets = {}, {}, {}, []
    for e in entries:
        raw = base64.b64decode(e["image"])
        masks, pixels = decode_image(raw)
        shape = tuple(masks)
        if shape not in shapes:
            pcs = pieces_of(masks, args.order)
            variants = []
            for shift in range(16):
                code, stream = program(pcs, shift)
                label = routines.setdefault(code, "rs_code_%d" % len(routines))
                streams.setdefault(stream, None)
                variants.append((label, stream))
            shapes[shape] = pcs, variants
        pcs, variants = shapes[shape]
        assets.append((e, raw, variants, source_words(pcs, pixels)))
    source = "\tsection text,code\n" + "\n".join(label + ":\n" + "\n".join(code) for code, label in routines.items()) + "\n"
    (BUILD / "resident_code.s").write_text(source)
    subprocess.run([VASM, "-Fvobj", "-quiet", "-m68000", "-o", str(BUILD / "resident_code.o"),
                    str(BUILD / "resident_code.s")], check=True)
    subprocess.run([VLINK, "-b", "rawbin1", "-Ttext", "0", "-M" + str(BUILD / "resident_code.map"),
                    "-o", str(BUILD / "resident_code.bin"), str(BUILD / "resident_code.o")], check=True)
    code_offsets = {}
    for line in (BUILD / "resident_code.map").read_text().splitlines():
        m = re.match(r"\s+0x([0-9a-f]+) (rs_code_\d+):", line)
        if m:
            code_offsets[m[2]] = int(m[1], 16)
    pack = bytearray(32 + cap * 32)
    for i in range(cap):
        struct.pack_into(">I", pack, 32 + 32 * i, 0xFFFFFFFF)

    def append(data):
        pack.extend(bytes(-len(pack) % 4))
        off = len(pack)
        pack.extend(data)
        return off

    code_base = append((BUILD / "resident_code.bin").read_bytes())
    for stream in streams:
        streams[stream] = append(stream)
    sources, max_probe = {}, 0
    for e, raw, variants, words in assets:
        if words not in sources:
            sources[words] = append(words)
        records = append(b"".join(struct.pack(">III", code_base + code_offsets[label], streams[stream], sources[words])
                                   for label, stream in variants))
        image = bytearray(raw)
        struct.pack_into(">H", image, 6, TAG)
        for s in range(16):
            struct.pack_into(">I", image, 8 + 4 * s, records + 12 * s)
        off = append(image)
        mapping = bytes.fromhex(e["mapping"])
        slot, probes = hash_slot(e["key"], mapping, cap), 1
        while struct.unpack_from(">I", pack, 32 + 32 * slot)[0] != 0xFFFFFFFF:
            slot = (slot + 1) & (cap - 1)
            probes += 1
        max_probe = max(max_probe, probes)
        struct.pack_into(">I16sI", pack, 32 + 32 * slot, e["key"], mapping, off)
    pack.extend(bytes(-len(pack) % 4))
    assert BASE + len(pack) <= LIMIT, "resident pack exceeds high-memory arena"
    signature = int.from_bytes(hashlib.sha256(pack[32:]).digest()[:4], "big")
    struct.pack_into(">8I", pack, 0, int.from_bytes(b"RS14", "big"), len(pack), cap, 32, 1,
                     int(args.order == "mask"), signature, len(entries))
    (BUILD / "SPRITES.DAT").write_bytes(pack)
    (BUILD / "resident.i").write_text("; generated by resident_sprites.py; offsets in SPRITES.DAT are base-relative\n" +
        "RS_BASE = $%x\nRS_BYTES = %d\nRS_CAP_MASK = %d\nRS_SIGNATURE = $%08x\nRS_TAG = $%x\n" %
        (BASE, len(pack), cap - 1, signature, TAG))
    summary = dict(order=args.order, pairs=len(assets), shapes=len(shapes), routines=len(routines),
                   code_bytes=(BUILD / "resident_code.bin").stat().st_size, pack_bytes=len(pack),
                   cap=cap, max_probe=max_probe, stream_bytes=sum(len(s) for s in streams),
                   unique_sources=len(sources), sha256=hashlib.sha256(pack).hexdigest())
    (BUILD / "resident_report.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


def check_programs():
    """Execute all pack variants on random background; oracle applies original pixels/masks directly."""
    pack = (BUILD / "SPRITES.DAT").read_bytes()
    _, size, cap, directory, version, order, _, count = struct.unpack_from(">8I", pack)
    assert version == 1 and size == len(pack)
    h = RT.Harness(BUILD / "render_test.prg")
    mem, cpu, b = h.sim.mem, h.sim.cpu, h.sim.blitter
    state = dict(passes=0, maximum_bus=0, source_crossings=0, destination_crossings=0, lo=0, hi=0)
    original = b.run

    def observe():
        xc, yc = b.reg16(0xA36), b.reg16(0xA38)
        assert (b.sim.io[0xA3A], b.sim.io[0xA3B], yc) == (2, 3, 4), (cpu.r_pc(), xc, yc, list(b.sim.io[0xA3A:0xA3E]))
        assert b.sim.io[0xA3C] & 0x40
        assert b.reg16(0xA20) == b.reg16(0xA22) == 2
        reads = (xc + bool(b.sim.io[0xA3D] & 0x80) - bool(b.sim.io[0xA3D] & 0x40)) * yc * 2
        src, dst = b.reg32(0xA24), b.reg32(0xA32)
        assert state["lo"] <= src and src + reads <= state["hi"], "prepared source over-read"
        state["source_crossings"] += src >> 16 != (src + reads - 1) >> 16
        state["destination_crossings"] += dst >> 16 != (dst + 8 * xc - 1) >> 16
        before = b.cycles
        original()
        bus = b.cycles - before
        assert bus <= 256
        state["passes"] += 1
        state["maximum_bus"] = max(state["maximum_bus"], bus)

    b.run = observe
    rng = random.Random(0x52533134)
    cases = 0
    for slot in range(cap):
        key, image = struct.unpack_from(">I16xI", pack, directory + 32 * slot)
        if key == 0xFFFFFFFF:
            continue
        rows, sw = struct.unpack_from(">HH", pack, image)
        masks = struct.unpack_from(">%dI" % rows, pack, image + IMG_HDR)
        rawsize = IMG_HDR + 8 * rows + sum(m != 0 for m in masks) * sw * 8
        masks, pixels = decode_image(pack[image:image + rawsize])
        pcs = pieces_of(masks, "mask" if order else "natural")
        native_size = sum(p[3] * 8 for p in pcs)
        for shift in range(16):
            record = struct.unpack_from(">I", pack, image + 8 + 4 * shift)[0]
            code, stream, source = struct.unpack_from(">III", pack, record)
            # Force source and destination across 64 KB boundaries independently of layout luck.
            source_addr, destination = 0x70FFFC, 0x80FFF8
            mem.w_block(source_addr, pack[source:source + native_size])
            state["lo"], state["hi"] = source_addr, source_addr + native_size
            background = rng.randbytes(rows * STRIDE + 64)
            want = bytearray(background)
            for y, mask in enumerate(masks):
                for x in range(32):
                    if not mask & (1 << (31 - x)):
                        continue
                    for plane in range(4):
                        off = y * STRIDE + ((x + shift) // 16) * 8 + 2 * plane
                        bit = 1 << (15 - (x + shift) % 16)
                        word = int.from_bytes(want[off:off + 2], "big")
                        word = (word | bit) if pixels[y, x] & (1 << plane) else (word & ~bit)
                        want[off:off + 2] = word.to_bytes(2, "big")
            mem.w_block(destination, background)
            for off, val in ((0xA20, 2), (0xA22, 2), (0xA2E, 8), (0xA3A, 0x0203)):
                mem.w16(0xFF8000 + off, val)
                h.sim.on_access("W", 1, 0xFF8000 + off, val)
            mem.w32(0xFF8A24, source_addr)
            h.sim.on_access("W", 2, 0xFF8A24, source_addr)
            for reg, val in [(R.A0, BASE + stream), (R.A1, 0xFF8A28), (R.A2, 0xFF8A3C),
                             (R.A3, destination), (R.A4, 0xFF8A32), (R.A5, 0xFF8A38),
                             (R.A6, 0xFF8A2C), (R.D1, 4), (R.D2, 0xC0), (R.A7, 0x8FFFFC)]:
                cpu.w_reg(reg, val)
            mem.w32(0x8FFFFC, h.sym["sim_wait"])
            cpu.w_pc(BASE + code)
            stop, _ = h.run_to_stop()
            assert stop == "sim_wait"
            got = bytes(mem.r_block(destination, len(want)))
            if got != want:
                first = next(i for i, (a, b_) in enumerate(zip(got, want)) if a != b_)
                raise AssertionError("key %08x shift %d differs at byte %d" % (key, shift, first))
            cases += 1
            if cases % 1024 == 0:
                print("native piece cases checked: %d" % cases, flush=True)
    assert cases == count * 16 and state["source_crossings"] and state["destination_crossings"]
    report = dict(cases=cases, **{k: v for k, v in state.items() if k not in ("lo", "hi")})
    (BUILD / "resident_focused.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--seed", type=int, default=0)
    c.add_argument("--level", type=int, default=0)
    c.add_argument("--frames", type=int, default=3600)
    c.add_argument("--first", type=int, default=400)
    c.add_argument("--every", type=int, default=3)
    c.add_argument("--fixtures", action="store_true")
    b = sub.add_parser("build")
    b.add_argument("--order", choices=("mask", "natural"), default="mask")
    sub.add_parser("check")
    args = ap.parse_args()
    if args.command == "collect":
        if args.every < 1:
            ap.error("every must be positive")
        collect(args)
    elif args.command == "build":
        build(args)
    else:
        check_programs()


if __name__ == "__main__":
    main()
