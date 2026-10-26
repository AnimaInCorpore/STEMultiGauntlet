"""The renderer's data (build/gauntlet/, never committed: ROM-derived), for src/render.s.

    palette.bin      16 STE colour words (docs/palette.json, ref/palette_fit.py)
    palette_rgb.bin  the 16 colours as RGB bytes
    irgb_map.bin     65536 bytes: an IRGB_4444 palette word -> the nearest of the 16 in Oklab (its RGB as MAME decodes it)
    tile_px.bin      8192 tiles x 32 bytes (gfx 0, the playfield's and the motion objects' 8x8 tiles): 8 rows of 8
                     pixels, two a byte (the first in the high nibble)
    tile_pens.bin    8192 words: bit p set when the tile has a pixel p
    tile_masks.bin   8192 x 8 rows x 2 bytes: the pixels that are neither 0 nor 1 (drawn by a motion object), the
                     pixels 1 (its shadow); bit 7 the first pixel
    char_rows.bin    1024 alphanumerics x 8 rows x 2 bytes: the pixels 0-3 and 4-7, 2 bits each (the first highest)
    char_pens.bin    1024 bytes: bit p set when the character has a pixel p
    char_blank.bin   1024 bytes: 1 when every pixel of the character is 0
    nz4.bin          256 bytes: per byte of four 2-bit pixels, the pixels not 0 (bit 3 the first)
    bitrev.bin       256 bytes: a byte's bits reversed (a mirrored mask)
    sprite_code.s    the motion objects' draw routine (render.s includes it)
    bar_map.bin      the status bar's cells (tools/bar.py): their word in the alphanumerics, their byte in the bar
    bar.i            BAR_N (the cells), BAR_LINES
    ir4.bin          256 bytes: [I << 4 | C] = the 4-bit channel of an IRGB pen's intensity I and channel C
    scene_cols.bin   SCENE_N x 16 STE words: the scene palettes (docs/scenes.json, ref/scene_palettes.py; 0: the
                     general one, docs/palette.json)
    scene_idx.bin    SCENE_N x 4096 bytes: an RGB_444 colour -> the nearest of the palette's 16 in Oklab
    scene_err.bin    SCENE_N x 4096 bytes: that distance (Oklab x 400, at most 255): render.s scene_pick's score
    scenes.i         SCENE_N
    scene_panel.bin  SCENE_N bytes: 1 when the palette was fitted to scenes with the side panel up (play), else 0
    bar_cols.bin     16 STE words: the status bar's own palette (docs/scenes.json "bar"; the Timer B loads it at line 240)
    bar_idx.bin      4096 bytes: an RGB_444 colour -> the nearest of the bar's 16
    bar_sp.bin       8 x 16 longs: [x][c] the plane bits of colour c at pixel x of a byte (plane k in byte k: movep)
"""
from pathlib import Path
import json
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[2] / "engine")]
from paths import build_dir

DOCS = HERE.parent / "docs"


def oklab(c):
    c = np.asarray(c, float) / 255
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929], [0.2119034982, 0.6806995451, 0.1073969566],
                   [0.0883024619, 0.2817188376, 0.6299787005]])
    m2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468], [1.9779984951, -2.4285922050, 0.4505937099],
                   [0.0259707400, 0.7827717716, -0.8086757660]])
    return np.cbrt(lin @ m1.T) @ m2.T


def irgb_rgb(words):
    w = np.asarray(words, np.int64)
    i = ((w >> 12) & 15) * 0x11
    rgb = np.stack([(w >> 8) & 15, (w >> 4) & 15, w & 15], axis=1) * 0x11
    return ((i[:, None] * rgb) >> 8).astype(np.int64)


def palette():
    """-> (the 16 colours [16, 3], the 65536-entry IRGB map, the 16 STE words)"""
    doc = json.loads((DOCS / "palette.json").read_text())
    colours = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for c in doc["colours"]], np.uint8)
    assert len(colours) == 16 and not colours[0].any() and not (colours % 17).any()
    rgb = irgb_rgb(np.arange(65536))
    key = (rgb[:, 0] << 16) | (rgb[:, 1] << 8) | rgb[:, 2]
    u, inv = np.unique(key, return_inverse=True)
    ur = np.stack([(u >> 16) & 255, (u >> 8) & 255, u & 255], axis=1)
    near = ((oklab(ur)[:, None] - oklab(colours)[None]) ** 2).sum(2).argmin(1).astype(np.uint8)
    mapping = near[inv.ravel()]
    regs = []
    for r, g, b in colours // 17:
        conv = lambda n: ((int(n) >> 1) & 7) | ((int(n) & 1) << 3)
        regs.append((conv(r) << 8) | (conv(g) << 4) | conv(b))
    return colours, mapping, np.array(regs, ">u2")


def ste_word(c):
    conv = lambda n: ((int(n) >> 1) & 7) | ((int(n) & 1) << 3)
    r, g, b = (int(v) // 17 for v in c)
    return (conv(r) << 8) | (conv(g) << 4) | conv(b)


def ir4():
    """[I << 4 | C] -> the 4-bit channel of MAME's IRGB decoding (I * C, both 4 bits as 8, >> 8), rounded"""
    return bytes(min(15, int(round(((i * 0x11) * (c * 0x11) >> 8) / 17))) for i in range(16) for c in range(16))


def scene_palettes():
    """[[16 RGB]]: docs/scenes.json's palettes with samples (the first the start's)"""
    doc = json.loads((DOCS / "scenes.json").read_text())
    return [np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for c in p["colours"]])
            for p in doc["palettes"] if p["samples"]]


def scene_tables(dest):
    pals = scene_palettes()
    grid = np.array([[r, g, b] for r in range(16) for g in range(16) for b in range(16)]) * 17
    lab = oklab(grid)
    cols, idx, err = bytearray(), bytearray(), bytearray()
    for pal in pals:
        d = np.sqrt(((lab[:, None] - oklab(pal)[None]) ** 2).sum(2))
        idx += d.argmin(1).astype(np.uint8).tobytes()
        err += np.minimum(255, np.round(d.min(1) * 400)).astype(np.uint8).tobytes()
        cols += np.array([ste_word(c) for c in pal], ">u2").tobytes()
    (dest / "ir4.bin").write_bytes(ir4())
    (dest / "scene_cols.bin").write_bytes(bytes(cols))
    (dest / "scene_idx.bin").write_bytes(bytes(idx))
    (dest / "scene_err.bin").write_bytes(bytes(err))
    (dest / "scenes.i").write_text("SCENE_N = %d\n" % len(pals))
    doc = json.loads((DOCS / "scenes.json").read_text())
    (dest / "scene_panel.bin").write_bytes(bytes(int(bool(p.get("panel"))) for p in doc["palettes"] if p["samples"]))
    doc = json.loads((DOCS / "scenes.json").read_text())
    bar_pal = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for c in doc["bar"]["colours"]])
    d = np.sqrt(((lab[:, None] - oklab(bar_pal)[None]) ** 2).sum(2))
    (dest / "bar_idx.bin").write_bytes(d.argmin(1).astype(np.uint8).tobytes())
    (dest / "bar_cols.bin").write_bytes(np.array([ste_word(c) for c in bar_pal], ">u2").tobytes())
    sp = bytearray()
    for x in range(8):
        for c in range(16):
            sp += bytes((((c >> k) & 1) << (7 - x)) for k in range(4))
    (dest / "bar_sp.bin").write_bytes(bytes(sp))


def sprite_code():
    return ""


def build():
    from video import Video
    dest = build_dir("gauntlet")
    v = Video()
    colours, mapping, regs = palette()
    (dest / "palette_rgb.bin").write_bytes(colours.tobytes())
    (dest / "irgb_map.bin").write_bytes(mapping.tobytes())
    (dest / "palette.bin").write_bytes(regs.tobytes())
    t = v.tiles.astype(np.uint8)                                          # [8192, 8, 8]
    (dest / "tile_px.bin").write_bytes(((t[..., ::2] << 4) | t[..., 1::2]).tobytes())
    pens = np.zeros(len(t), np.int64)
    for p in range(16):
        pens |= (t == p).any((1, 2)).astype(np.int64) << p
    (dest / "tile_pens.bin").write_bytes(pens.astype(">u2").tobytes())
    weights = 1 << np.arange(7, -1, -1)
    opaque = ((t > 1) * weights).sum(2)
    shadow = ((t == 1) * weights).sum(2)
    (dest / "tile_masks.bin").write_bytes(np.stack([opaque, shadow], 2).astype(np.uint8).tobytes())
    c = v.chars.astype(np.uint8)                                          # [1024, 8, 8], 0-3
    rows = np.stack([(c[..., 0] << 6) | (c[..., 1] << 4) | (c[..., 2] << 2) | c[..., 3],
                     (c[..., 4] << 6) | (c[..., 5] << 4) | (c[..., 6] << 2) | c[..., 7]], 2)
    (dest / "char_rows.bin").write_bytes(rows.astype(np.uint8).tobytes())
    (dest / "char_pens.bin").write_bytes(bytes(sum(int((ch == v).any()) << v for v in range(4)) for ch in c))
    (dest / "char_blank.bin").write_bytes(bytes(int(not ch.any()) for ch in c))
    (dest / "nz4.bin").write_bytes(bytes(sum(int((b >> (6 - 2 * i)) & 3 != 0) << (3 - i) for i in range(4))
                                         for b in range(256)))
    (dest / "bitrev.bin").write_bytes(bytes(int("{:08b}".format(b)[::-1], 2) for b in range(256)))
    (dest / "sprite_code.s").write_text(sprite_code())
    scene_tables(dest)
    import bar
    (dest / "bar_map.bin").write_bytes(bar.table())
    (dest / "bar.i").write_text("BAR_N = %d\nBAR_LINES = %d\n" % (len(bar.cells()), bar.BAR_LINES))
    print("renderer assets: %s" % dest, flush=True)


PANEL_COLS = range(29, 40)          # (the arcade's columns 29-39: the STE's x 232-319; render.s panel_open)


def panel_shown(vram):
    """the side panel is up (its characters all opaque, rows 0-29): it goes to the status bar, the playfield shows
    under its place"""
    d = np.frombuffer(bytes(vram[0x5000:0x5000 + 64 * 31 * 2]), ">u2").reshape(31, 64)
    return bool((d[:30, PANEL_COLS.start:PANEL_COLS.stop] & 0x8000).all())


class Oracle:
    """the reference picture through the fixed palette: [240, 320] colour indices (the arcade's x 0-319; while the
    panel is up, no alphanumerics right of the maze: x 232-), and the status bar ([BAR_LINES, 320])"""

    def __init__(self):
        from video import Video
        dest = build_dir("gauntlet")
        self.mapping = np.frombuffer((dest / "irgb_map.bin").read_bytes(), np.uint8)
        self.rgb = np.frombuffer((dest / "palette_rgb.bin").read_bytes(), np.uint8).reshape(16, 3)
        self.video = Video()

    def indices(self, raw, palette_ram, pen_map=None):
        """pens -> STE colours: through pen_map (768 bytes, the STE's own: the scene it chose) when given, else the
        general palette's IRGB table"""
        if pen_map is not None:
            return np.frombuffer(bytes(pen_map), np.uint8)[raw]
        pens = np.frombuffer(bytes(palette_ram[:0x800]), ">u2").astype(np.int64)
        return self.mapping[pens[raw]]

    def picture(self, m):
        return self.picture_raw(m.vram(), m.palette(), m.xscroll)

    def picture_raw(self, vram, palette, xscroll, pen_map=None):
        vram = bytes(vram)
        ys = (vram[0x5F6E] << 8) | vram[0x5F6F]
        if panel_shown(vram):
            alpha = self.video.alpha
            self.video.alpha = lambda v: (lambda p: (p[0], np.where(np.arange(p[1].shape[1]) < 232, p[1], False)))(
                alpha(v))
            try:
                raw = self.video.render_raw(vram, xscroll, ys)
            finally:
                self.video.alpha = alpha
        else:
            raw = self.video.render_raw(vram, xscroll, ys)
        x0 = 0 if panel_shown(vram) else 8                                  # (render.s view_check: centred then)
        return self.indices(raw, palette, pen_map)[:, x0:x0 + 320]

    def bar(self, vram, palette, pen_map=None, bar_map=None):
        """the status bar: [BAR_LINES, 320] colour indices (in the bar's own palette when bar_map, the STE's 256 text
        pens' bar colours, is given)"""
        import bar
        out = np.zeros((bar.BAR_LINES, 320), np.uint8)
        if not panel_shown(vram):
            return out
        apix, _ = self.video.alpha(bytes(vram))
        idx = self.indices(apix, palette, bar_map if bar_map is not None else pen_map)
        for y, k, r, c in bar.cells():
            out[y:y + 8, 8 * k:8 * k + 8] = idx[8 * r:8 * r + 8, 8 * c:8 * c + 8]
        return out


if __name__ == "__main__":
    build()
