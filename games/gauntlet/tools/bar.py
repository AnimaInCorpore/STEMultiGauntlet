"""The status bar below the maze: the arcade's side panel (alphanumerics columns 30-41) laid out again in a bar of
40 x 4 characters, BAR_LINES lines under the picture's 240 (src/render.s draws it into its own image, BIMG; the
borders' Timer B switches the display to it: engine/rt/borders.s BD_VSWITCH).

The panel (rows 0-29, 12 columns): the logo (rows 0-2), "LEVEL n" (row 4), then a block of five rows per player p
(p = 0-3: warrior, valkyrie, wizard, elf) from row 5 + 5 p: the name (small letters, columns 35-39), "SCORE HEALTH",
the values (the score right-aligned at column 35, the health at 41), the inventory or "INSERT COIN", a blank row.

The bar: two bands of two players (1 | 2 over 3 | 4), each player's values and inventory rows whole (12 characters)
at the bar's left or right edge, its name next to them towards the middle, "LEVEL n" in the middle of the first band.
The middle of the second band's lower row is free (later: the MIDI link's state).

    cells() -> [(bar line, bar column, panel row, arcade column)]
"""

BAR_LINES = 36
ROW_Y = (1, 9, 19, 27)               # the bar's four character rows (lines)
BAR_W = 40


def cells():
    out = []
    for band in range(2):
        ya, yb = ROW_Y[2 * band], ROW_Y[2 * band + 1]
        for side in range(2):
            p = 2 * band + side
            r = 5 + 5 * p
            c0 = 0 if side == 0 else BAR_W - 12
            for i in range(12):
                out.append((ya, c0 + i, r + 2, 30 + i))            # the values
                out.append((yb, c0 + i, r + 3, 30 + i))            # the inventory / INSERT COIN
            n0 = 13 if side == 0 else BAR_W - 12 - 6
            for i in range(5):
                out.append((ya, n0 + i, r, 35 + i))                # the name
        if band == 0:
            for i in range(12):
                out.append((yb, 14 + i, 4, 30 + i))                # LEVEL n
    return out


def table():
    """bar_map.bin: per cell its word in the alphanumerics (row * 128 + column * 2) and its byte in the bar image
    (line * 160 + (column >> 1) * 8 + (column & 1)), big-endian words; BAR_N = the cells"""
    import struct
    out = bytearray()
    for y, k, r, c in cells():
        out += struct.pack(">HH", r * 128 + c * 2, y * 160 + (k >> 1) * 8 + (k & 1))
    return bytes(out)
