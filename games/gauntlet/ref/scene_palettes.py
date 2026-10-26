"""A 16-colour STE palette per scene (docs/scenes.json; tools/assets.py makes the run-time tables, src/render.s picks
the scene by the arcade palette's signature).

    venv/bin/python games/gauntlet/ref/scene_palettes.py [--frames N]      -> docs/scenes.json

The samples: the reference board (tools/machine.py through tools/render_test.py's scenario) in the attract mode
(seed 0: the demo play, the title, the high-score and "score per coin" pages, the monster pages; every 10th frame of
one cycle) and in play (one player at random, the levels of ref/palette_fit.py LEVELS; frames 800.., every 20th).
For each sample its palette RAM (pens $000-$2FF) and the histogram of its picture's colours (the arcade's 336 x 240,
so the panel's text counts as the status bar's).

* The effect pens: pens that change while almost nothing else does (at most 8 pens of $100-$2FF between two
  samples): colour cycling (the playfield's flickering and pulsing pens, the text's).  They are left out of the
  signature, and the run-time applies their changes only every few pictures.
* The signature of a palette: over pens $100-$2FF (the objects' and the playfield's), the effect pens skipped, the
  brightness nibble masked (fades that only scale it keep the scene): h = rol(h, 5) ^ (pen & $0FFF), from 0, 32 bits.
* A scene: the samples of one signature, kept when at least MIN_SAMPLES show it (fades and page changes in between
  are not scenes).  Its palette: ref/palette_fit.py's weighted k-means in Oklab over its pictures' colours (black is
  colour 0; the panel's four player colours kept when the panel is up in the scene).  Scenes with equal palettes are
  merged (one entry, several signatures).

Reported: per scene its samples, its error (mean absolute per channel, 0-255) with its palette and with the general
fixed palette (docs/palette.json).
"""
import argparse
import collections
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "tools"), str(HERE.parents[2] / "engine")]

import palette_fit as PF

K = 10                               # (the palettes)
K_DOWN = 3                           # (of them for pictures with the side panel down: the title, the tables; render.s
                                     #  picks only palettes of the picture's kind)
OBJECT_WEIGHT = 8                    # (an object's pixel weighs as 8 others: the players and the monsters matter most)
BAND = 15                            # (the title logo's colour band: its own colour, rewritten every line by the Timer B)


def band_pixels(raw):
    """the title logo's band pixels: object pen $100 + (i >> 3) * 16 + 2 + (i & 7) on line 161 + i (render.s BAND_TOP)"""
    p = raw.astype(np.int64) - 0x100
    i = (p >> 4) * 8 + (p & 15) - 2
    ys = np.arange(raw.shape[0])[:, None]
    return (p >= 0) & (p < 0x90) & ((p & 15) >= 2) & ((p & 15) <= 9) & (ys == 161 + i)
SIG_LO, SIG_HI = 0x100, 0x300


def signature(pal, effect):
    """the run-time signature (src/render.s scene_sig): rol 5, eor the pen's word & $0FFF"""
    h = 0
    for p in range(SIG_LO, SIG_HI):
        if p in effect:
            continue
        h = ((h << 5) | (h >> 27)) & 0xFFFFFFFF
        h ^= int(pal[p]) & 0x0FFF
    return h


def sample_job(seed, level, frames, first, every):
    """[(palette words [768], {rgb key: pixels}, panel up)] of a scenario"""
    from render_test import scenario
    from video import Video
    from assets import panel_shown
    import bar
    video = Video()
    out = []
    for f, m in scenario(seed, level, frames):
        if f < first or f % every:
            continue
        vram = m.vram()
        ys = (int(vram[0x5F6E]) << 8) | int(vram[0x5F6F])
        raw = video.render_raw(vram, m.xscroll, ys)
        pens = np.frombuffer(bytes(m.palette()[:0x600]), ">u2").astype(np.int64)
        rgb = PF.irgb_rgb(pens[raw.ravel()])
        key = (rgb[:, 0] << 16) | (rgb[:, 1] << 8) | rgb[:, 2]
        w = np.where((raw.ravel() >= 0x100) & (raw.ravel() < 0x200), OBJECT_WEIGHT, 1)   # (the objects count more)
        if not panel_shown(vram):                                          # (the band: shown by its own colour)
            w = np.where(band_pixels(raw).ravel(), 0, w)
        u, inv = np.unique(key, return_inverse=True)
        c = np.bincount(inv.ravel(), weights=w)
        bar_h = {}
        if panel_shown(vram):                                              # (the status bar's cells: their colours)
            apix, _ = video.alpha(bytes(vram))
            cells = np.concatenate([apix[8 * r:8 * r + 8, 8 * col:8 * col + 8].ravel() for _, _, r, col in bar.cells()])
            brgb = PF.irgb_rgb(pens[cells])
            bkey = (brgb[:, 0] << 16) | (brgb[:, 1] << 8) | brgb[:, 2]
            bu, bc = np.unique(bkey, return_counts=True)
            bar_h = dict(zip(bu.tolist(), bc.tolist()))
        out.append((pens, dict(zip(u.tolist(), c.tolist())), panel_shown(vram), bar_h))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=3000)
    args = ap.parse_args()
    from multiprocessing import Pool
    import pickle
    from paths import build_dir
    jobs = [(0, 0, 14000, 300, 10)] + [(1 + (lv % 5), lv, args.frames, 800, 20) for lv in PF.LEVELS]
    cache = build_dir("gauntlet") / ("scene_samples_%d_w%d_bar_band.pkl" % (args.frames, OBJECT_WEIGHT))
    if cache.exists():
        runs = pickle.loads(cache.read_bytes())
    else:
        with Pool(8) as p:
            runs = p.starmap(sample_job, jobs)
        cache.write_bytes(pickle.dumps(runs))
    # the effect pens
    effect = set()
    for run in runs:
        for (a, _, _, _), (b, _, _, _) in zip(run, run[1:]):
            d = np.nonzero(a[SIG_LO:SIG_HI] != b[SIG_LO:SIG_HI])[0]
            if 0 < len(d) <= 8:
                effect.update(int(SIG_LO + x) for x in d)
    print("effect pens:", " ".join("%03X" % p for p in sorted(effect)))
    # the palettes: K that together fit the samples (each sample weighs the same: its colours' shares ** 0.5)
    samples = [(h, panel) for run in runs for _, h, panel, _ in run]
    samples = [(h, panel) for h, panel in samples if any(k for k in h)]
    keys = sorted({k for h, _ in samples for k in h if k})
    col = {k: i for i, k in enumerate(keys)}
    W = np.zeros((len(samples), len(keys)), np.float32)
    for i, (h, _) in enumerate(samples):
        tot = sum(n for k, n in h.items() if k)
        for k, n in h.items():
            if k:
                W[i, col[k]] = (n / tot) ** PF.WEIGHT_POWER
    lab = PF.oklab(PF.key_rgb(keys))
    panels = np.array([p for _, p in samples])

    def dist(pal):
        return np.sqrt(((lab[:, None] - PF.oklab(np.asarray(pal))[None]) ** 2).sum(2).min(1)).astype(np.float32)

    def fit_of(rows):
        """a palette for the samples rows: black, then 15 fitted colours (the status bar has a palette of its own); with
        the side panel down (the title) 14 and colour 15 left for the logo's band (BAND, black here)"""
        h = collections.Counter(dict(zip(keys, W[rows].sum(0).tolist())))
        h = collections.Counter({k: v for k, v in h.items() if v > 0})
        panel = panels[rows].mean() > 0.5
        n = 15 if panel else 14
        fixed = np.zeros((0, 3), int)
        own = np.unique(PF.ste_snap(PF.key_rgb(list(h))), axis=0)
        own = own[own.sum(1) > 0]
        both = np.unique(np.vstack([own, fixed]), axis=0)
        if len(both) <= n:
            cols = both.tolist() + [[0, 0, 0]] * (n - len(both))
        else:
            cols = PF.fit(h, n, starts=8, fixed=fixed)
        return np.array([[0, 0, 0]] + cols + [[0, 0, 0]] * (15 - n)), panel

    general = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)]
                        for c in json.loads((HERE.parent / "docs" / "palette.json").read_text())["colours"]])
    gen_err = W @ dist(general) / W.sum(1)

    def errs_of(pals, kinds):
        """[sample, palette]: a palette of the other kind is never a sample's"""
        e = np.stack([W @ dist(p) for p in pals], 1) / W.sum(1)[:, None]
        e[panels[:, None] != np.array(kinds)[None, :]] = np.inf
        return e

    down = np.nonzero(~panels)[0]
    pals, kinds = [general, fit_of(down)[0]], [True, False]                # (the seeds of either kind)
    print("K  2: mean error %.2f" % errs_of(pals, kinds).min(1).mean())
    rich = (W > 0).sum(1) >= 8                                            # (seeds: pictures with content)
    while len(pals) < K:
        kind = sum(1 for k in kinds if not k) >= K_DOWN                   # (the kind still short of palettes)
        errs = errs_of(pals, kinds).min(1)
        worst = int(np.where(rich & (panels == kind), errs, -1).argmax())
        near = np.nonzero(((W > 0) == (W[worst] > 0)).all(1) & (panels == kind))[0]   # (the same colours)
        pals.append(fit_of(near)[0])
        kinds.append(kind)
        errs = errs_of(pals, kinds)
        print("K %2d: mean error %.2f, worst sample %.2f" % (len(pals), errs.min(1).mean(), errs.min(1).max()))
    for it in range(4):                                                    # (assigned, fitted again)
        errs = errs_of(pals, kinds)
        a = errs.argmin(1)
        new_pals = []
        for j in range(len(pals)):
            rows = np.nonzero(a == j)[0]
            new_pals.append(fit_of(rows)[0] if len(rows) else pals[j])
        pals = new_pals
        errs = errs_of(pals, kinds)
        print("round %d: mean error %.2f (the general palette %.2f), worst sample %.2f" % (
            it + 1, errs.min(1).mean(), gen_err.mean(), errs.min(1).max()))
    a = errs.argmin(1)
    out = []
    for j, pal in enumerate(pals):
        rows = np.nonzero(a == j)[0]
        out.append(dict(colours=PF.hexes(pal), samples=int(len(rows)),
                        panel=bool(kinds[j]),
                        error=round(float(errs[rows, j].mean()), 4) if len(rows) else None,
                        error_general=round(float(gen_err[rows].mean()), 4) if len(rows) else None))
        print("palette %2d: %4d samples, error %s (general %s): %s" % (
            j, len(rows), out[-1]["error"], out[-1]["error_general"], " ".join(out[-1]["colours"])))
    # the status bar's palette (the panel's cells; its own 16 colours from the Timer B's split at line 240)
    bh = collections.Counter()
    for run in runs:
        for _, _, _, b in run:
            tot = sum(b.values())
            for k, n in b.items():
                if k:
                    bh[k] += (n / tot) ** PF.WEIGHT_POWER
    own = np.unique(PF.ste_snap(PF.key_rgb(list(bh))), axis=0)
    own = own[own.sum(1) > 0]
    if len(own) <= 15:
        bar_pal = np.vstack([[[0, 0, 0]], own, [[0, 0, 0]] * (15 - len(own))])
    else:
        bar_pal = np.array([[0, 0, 0]] + PF.fit(bh, 15, starts=8, fixed=np.array(PF.PLAYERS)))
    be, _ = PF.error(bh, bar_pal)
    print("the status bar: %d colours (%d distinct), error %.2f: %s" % (len(bar_pal), len(own), be,
                                                                        " ".join(PF.hexes(bar_pal))))
    result = {"name": "Gauntlet scene palettes (src/render.s scene_*)",
              "origin": "ref/scene_palettes.py: the attract mode (seed 0, 14000 frames, every 10th) and play in "
                        "levels %s (%d frames, every 20th): %d palettes that together fit the samples (Oklab "
                        "distance weighted by the colours' shares ** %.1f)" % (PF.LEVELS, args.frames, K,
                                                                               PF.WEIGHT_POWER),
              "effect_pens": sorted(effect), "palettes": out,
              "bar": {"colours": PF.hexes(bar_pal), "error": round(float(be), 2)}}
    (HERE.parent / "docs" / "scenes.json").write_text(json.dumps(result, indent=1) + "\n")


if __name__ == "__main__":
    main()
