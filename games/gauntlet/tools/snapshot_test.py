"""Interrupt-style snapshot invalidation: display-only VBLs versus game/queue yields.

    python games/gauntlet/tools/snapshot_test.py --epoch 1
    python games/gauntlet/tools/snapshot_test.py --epoch 0

Inject after a record has already been emitted. A changed game record must be
retaken; a display-only VBL must not invalidate the epoch-based snapshot. The
final picture is compared with the independent pixel renderer in both modes.
"""
import argparse
import json

import numpy as np

import assets
import render_test as RT
from sprite_test import put_objects
from paths import build_dir


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--epoch", type=int, choices=(0, 1), default=1)
    args = ap.parse_args()
    prg = RT.build_harness(["SNAP_EPOCH=%d" % args.epoch])
    RT.reference_mode([])
    h = RT.Harness(prg)
    oracle = assets.Oracle()
    for _, m in RT.scenario(1, 2, 1200):
        pass
    palette, xs = m.palette(), m.xscroll
    ys = int.from_bytes(m.vram()[0x5F6E:0x5F70], "big")
    base = put_objects(m.vram(), [(436, 3, 3, 2, 0, 80, 60), (764, 2, 2, 0, 1, 150, 100)], xs, ys)
    mem, sy = h.sim.mem, h.sym
    rows = []
    for kind in ("display_only", "game_yield", "queue_yield"):
        # Settle both rings, palette selection and overlay classification before observing snapshots.
        h.observer = None
        for _ in range(4):
            h.put_raw(base, palette, xs)
            h.draw()
        state = dict(calls=0, injected=False)
        expected = bytearray(base)

        def observe(pc):
            if pc == sy["mo_snapshot"]:
                state["calls"] += 1
            if not state["injected"] and sy["mo_snapshot"] <= pc < sy["mo_bands"] and mem.r16(sy["mo_n"]) >= 1:
                state["injected"] = True
                mem.w32(sy["rf_vbls"], mem.r32(sy["rf_vbls"]) + 1)
                if kind != "display_only":
                    # Record one is already in the output list. Change its source code behind that snapshot.
                    expected[0x2002:0x2004] = (445 ^ 0x800).to_bytes(2, "big")
                    mem.w16(h.map["ARC_VRAM"] + 0x2002, 445 ^ 0x800)
                    mem.w32(sy["game_serial"], mem.r32(sy["game_serial"]) + 1)

        h.observer = observe
        h.put_raw(base, palette, xs)
        cycles = h.draw()
        h.observer = None
        assert state["injected"]
        want_calls = 1 if args.epoch and kind == "display_only" else 2
        assert state["calls"] == want_calls, (kind, state)
        want = oracle.picture_raw(expected, palette, xs, h.pen_map(), h.pen_pab())
        assert np.array_equal(h.picture(), want), kind + " retained stale records"
        rows.append(dict(kind=kind, snapshots=state["calls"], cycles=cycles))
    dest = build_dir("gauntlet") / ("snapshot_epoch%d.json" % args.epoch)
    dest.write_text(json.dumps(rows, indent=2) + "\n")
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
