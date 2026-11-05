"""Retain original-RGB colour counts for the full-width scene renderer.

    venv/bin/python games/gauntlet/ref/colour_training.py [--out FILE]

Attract play plus one-, three- and four-player mazes in levels 1, 2, 5 and 9.
Each scenario contributes its mean picture, so a longer recording cannot dominate.
The separate HUD and title palette are not trained here. This is curated sampling,
not whole-game visual coverage; no ROM images or snapshots are written to docs.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "tools"), str(HERE.parents[2] / "engine")]
from assets import panel_shown
from render_test import scenario, arc_mode
from video import Video

JOBS = [(0, 0, 3600, 500, 60), (1, 1, 2200, 1100, 30), (10, 2, 2200, 1100, 30),
        (12, 5, 2200, 1100, 30), (19, 9, 2200, 1100, 30)]
PLAYERS = [[255, 0, 0], [0, 136, 255], [255, 255, 0], [0, 255, 0]]
# The elf's most frequent sampled cloak colour is (0,101,6). The bright player
# anchor alone cannot preserve it: red monsters outweigh the green player pixels.
KEY_SHADES = [[0, 102, 0], [136, 136, 136], [204, 102, 51]]
ANCHOR_NOTES = "Four original player anchors plus sampled identity colours snapped to STE: elf cloak (0,101,6) -> #006600; neutral sprite grey (135,135,135) -> #888888; playfield wall orange (203,101,50) -> #cc6633. Unconstrained sampled fits lost green, tinted neutral sprites brown, or made the walls muddy."


def record(job):
    seed, level, frames, first, every = job
    video = Video()
    layers, samples = [Counter(), Counter()], 0
    for frame, m in scenario(seed, level, frames):
        if frame < first or (frame - first) % every:
            continue
        vram, xs = m.vram(), m.xscroll
        panel = panel_shown(vram)
        shift = 88 if panel and arc_mode(m) else 0
        alpha = video.alpha
        if panel:
            def cut(v):
                pix, mask = alpha(v)
                mask = mask & (np.arange(mask.shape[1]) < 232)
                if shift:
                    pix = np.concatenate((np.zeros_like(pix[:, :shift]), pix[:, :-shift]), axis=1)
                    mask = np.concatenate((np.zeros_like(mask[:, :shift]), mask[:, :-shift]), axis=1)
                return pix, mask
            video.alpha = cut
        try:
            ys = int.from_bytes(vram[0x5F6E:0x5F70], "big")
            raw = video.render_raw(vram, xs - shift, ys)
        finally:
            video.alpha = alpha
        x0 = 0 if panel else 8
        raw = raw[:, x0:x0 + 320]
        rgb = video.pens(m.palette()).copy()
        rgb[0x101:0x200:16] = 0       # the port's opaque-black motion-object shadow pen
        pixels = rgb[raw]
        sprite = (raw >= 0x100) & (raw < 0x200)
        for hist, mask in zip(layers, (sprite, ~sprite)):
            colors, counts = np.unique(pixels[mask], axis=0, return_counts=True)
            hist.update({tuple(map(int, c)): int(n) for c, n in zip(colors, counts)})
        samples += 1
    print("seed %d level %d: %d colour samples" % (seed, level, samples), flush=True)
    return layers, samples


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=HERE.parent / "docs/colour_training.json")
    args = ap.parse_args()
    Video.black_shadow = True
    total, scenarios = [Counter(), Counter()], []
    for job in JOBS:
        layers, samples = record(job)
        for merged, hist in zip(total, layers):
            for color, n in hist.items():
                merged[color] += n / samples
        scenarios.append(dict(zip(("seed", "level", "frames", "first", "every"), job), samples=samples))
    doc = dict(policy="Bounded original-RGB OKLab fit; counts power .75, sprite priority 8x after compression, chroma bonus below 2x; constrained checker pairs",
               source="ref/colour_training.py: full-width port view; attract and one/three/four-player sampled mazes; 2026-11-05",
               coverage="Curated samples, not whole-game palette coverage; title and HUD kept separately; lookup covers RGB444.",
               normalization="Each scenario contributes one mean picture before merging; both layers use its sample count.",
               fixed=PLAYERS + KEY_SHADES, anchor_notes=ANCHOR_NOTES, scenarios=scenarios,
               histograms=[[[list(c), round(n, 6)] for c, n in sorted(h.items())] for h in total])
    args.out.write_text(json.dumps(doc, indent=2) + "\n")
    print(args.out)


if __name__ == "__main__":
    main()
