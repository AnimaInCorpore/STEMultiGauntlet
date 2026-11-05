"""Palette contracts for the scene renderer (no ROMs or native assets rewritten).

    venv/bin/python games/gauntlet/tools/palette_test.py

The title and HUD must remain byte-identical to DB15 mode; ordinary scenes must
keep player/key-colour anchors, reserve slot 15, and use only bounded checker pairs. Text
uses the separate flat table. GAUNTLET_DITHER=0 changes mapping, not the palette.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import tempfile

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assets
import palette_quantize as pq


@contextmanager
def options(**values):
    old = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def rgb_words(words):
    w = np.asarray(words, np.uint16)
    n = np.stack([(w >> 8) & 15, (w >> 4) & 15, w & 15], axis=-1)
    return (((n & 7) << 1) | (n >> 3)) * 17


def main():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        paths = {}
        for name, policy, dither in (("new", "bounded", ".25"), ("flat", "bounded", "0"),
                                      ("old", "db15", ".25")):
            dest = paths[name] = root / name
            dest.mkdir()
            with options(GAUNTLET_PALETTE=policy, GAUNTLET_DITHER=dither):
                assets.scene_tables(dest)
        for name in ("bar_cols.bin", "bar_idx.bin", "bar_sp.bin", "ir4.bin", "ir4s.bin", "scene_panel.bin"):
            assert (paths["new"] / name).read_bytes() == (paths["old"] / name).read_bytes(), name
        for name, stride in (("scene_cols.bin", 32), ("scene_idx.bin", 4096),
                              ("scene_pab.bin", 4096), ("scene_err.bin", 4096)):
            a, b = [(paths[k] / name).read_bytes() for k in ("new", "old")]
            for scene in assets.TITLE_SCENES:
                assert a[scene * stride:(scene + 1) * stride] == b[scene * stride:(scene + 1) * stride], name
        assert (paths["new"] / "scene_cols.bin").read_bytes() == (paths["flat"] / "scene_cols.bin").read_bytes()
        pals = rgb_words(np.frombuffer((paths["new"] / "scene_cols.bin").read_bytes(), ">u2").reshape(-1, 16))
        pairs = np.frombuffer((paths["new"] / "scene_pab.bin").read_bytes(), np.uint8).reshape(-1, 4096)
        flat = np.frombuffer((paths["new"] / "scene_idx.bin").read_bytes(), np.uint8).reshape(-1, 4096)
        off = np.frombuffer((paths["flat"] / "scene_pab.bin").read_bytes(), np.uint8).reshape(-1, 4096)
        anchors = json.loads((assets.DOCS / "colour_training.json").read_text())["fixed"]
        grid = np.array([[r, g, b] for r in range(16) for g in range(16) for b in range(16)]) * 17
        mixed = 0
        for i, pal in enumerate(pals):
            if i in assets.TITLE_SCENES:
                continue
            assert not pal[0].any() and not pal[15].any()
            assert all(np.any(np.all(pal[:15] == c, axis=1)) for c in anchors)
            assert np.array_equal(flat[i], pq.flat_map(pal[:15], grid, hue_weight=2))
            # Neutral text and skeleton ramps must not acquire the skin orange
            # that a lightness-dominated metric selected in the first preview.
            grey = np.arange(16) * 0x111
            mapped_grey = pal[flat[i, grey]]
            assert np.all(mapped_grey.max(1) - mapped_grey.min(1) <= 34)
            assert np.array_equal(off[i], flat[i] * 17)
            assert np.all(pairs[i] >> 4 < 15) and np.all((pairs[i] & 15) < 15) and np.all(flat[i] < 15)
            lab = pq.oklab(pal)
            a, b = pairs[i] >> 4, pairs[i] & 15
            used = a != b
            assert np.all(np.abs(lab[a, 0] - lab[b, 0]) <= .12 + 1e-9)
            assert np.all(np.linalg.norm(lab[a, 1:] - lab[b, 1:], axis=1) <= .08 + 1e-9)
            # Every mixed entry must beat the flat text choice by the shared
            # fitter's minimum gain, evaluated as a linear-light mixture.
            linear = np.where(pal / 255 <= .04045, pal / 255 / 12.92,
                              ((pal / 255 + .055) / 1.055) ** 2.4)
            mix = (linear[a] + linear[b]) / 2
            mixed_rgb = np.where(mix <= .0031308, mix * 12.92,
                                 1.055 * mix ** (1 / 2.4) - .055) * 255
            scale = np.array([1, 2, 2])
            flat_error = np.linalg.norm((pq.oklab(grid) - lab[flat[i]]) * scale, axis=1)
            mix_error = np.linalg.norm((pq.oklab(grid) - pq.oklab(mixed_rgb)) * scale, axis=1)
            assert np.all(mix_error[used] + .012 < flat_error[used] + 1e-9)
            mixed += int(used.sum())
        assert mixed, "constrained checkers were never selected"
    print("PASS: title/HUD preserved; player/key-colour anchors; slot 15 reserved; bounded checkers; flat text and no-dither")


if __name__ == "__main__":
    main()
