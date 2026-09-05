"""The table's grid: one constant, and the code that draws it.

EVERY number here comes from display-image-specifications.md, which is the
authority. Nothing in this package may hardcode a copy of them -- the whole
reason recipes are stored (spec section 11) is so that if PITCH is ever
re-measured, changing it here and re-rendering makes every custom map correct
again. A copied constant somewhere else would silently survive that edit and
quietly stay wrong.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

from PIL import Image, ImageDraw

# --- the measurements ------------------------------------------------------

# Pixels per 5 ft square (one medium base). Settled against real miniatures on
# the real table, 2026-08-21.
#
# This is NOT the 80.68 the panel dimensions imply. xrandr reports the panel;
# the TV is recessed into the tabletop, so the visible area is smaller than
# the panel itself. The display density is a property of THIS INSTALLATION,
# not of the television. See the spec, section 4.
PITCH = 107.85

# The output frame. Exactly this, always -- 4096x2160 is DCI 4K at 17:9 and
# would letterbox or stretch, which turns square grid cells into rectangles
# and makes miniatures sit wrong.
FRAME_W = 3840
FRAME_H = 2160
FRAME = (FRAME_W, FRAME_H)

# Overscan safe box, centred: 5% in on every edge. Televisions crop a few
# percent and this panel has not been tested for it. Advisory in the editor,
# not enforced -- backgrounds may bleed, but map content should stay inside.
SAFE_W = 3456
SAFE_H = 1944
SAFE = (SAFE_W, SAFE_H)

# Grid line appearance. Thin and low-contrast on purpose: at table distance a
# heavy grid dominates the art beneath it.
#
# MEASURED off the shipped forest_3840x2160_grid.png: 2 px lines at exactly
# 0.25 alpha, white, starting at x=0. Match it rather than invent something.
LINE_WIDTH = 2
LINE_OPACITY = 0.25
LINE_RGB = (255, 255, 255)

# Black lines, for maps that are pale enough that white disappears into them.
#
# Deliberately carried at a HIGHER opacity than white. The artwork here is
# dark by house rule, and darkening something already dark is far less visible
# than lightening it -- 0.25 black on a mid-tone map barely reads, where 0.25
# white is clear. This is a perceptual asymmetry, not a preference.
LINE_RGB_BLACK = (0, 0, 0)
LINE_OPACITY_BLACK = 0.35

# --- hexes -----------------------------------------------------------------
#
# MEASURED off the shipped forest_3840x2160_hex.png, the same way. The house
# convention is FLAT-TOP hexes in offset columns, and the hex is exactly one
# square across: its flat-to-flat height is PITCH, so a hex is 5 ft just as a
# square is.
#
#     flat-to-flat (vertical)      107.85   = PITCH = 5 ft
#     circumradius R               62.267   = PITCH / sqrt(3)
#     column spacing               93.401   = 1.5 * R
#     odd columns offset down by   53.925   = PITCH / 2
#
# Checked against the file: the overlay's horizontal period over two columns
# measures 187 px where 3R predicts 186.80.
HEX_R = PITCH / math.sqrt(3.0)
HEX_COL_SPACING = 1.5 * HEX_R
HEX_ROW_SPACING = PITCH

SQUARE = "square"
HEX = "hex"
NONE = "none"
STYLES = (NONE, SQUARE, HEX)

WHITE = "white"
BLACK = "black"


def colour_for(name: str) -> Tuple[Tuple[int, int, int], float]:
    """(rgb, opacity) for a named line colour."""
    if (name or WHITE).lower() == BLACK:
        return LINE_RGB_BLACK, LINE_OPACITY_BLACK
    return LINE_RGB, LINE_OPACITY


def safe_box() -> Tuple[int, int, int, int]:
    """The safe area as (left, top, right, bottom) in frame pixels."""
    left = (FRAME_W - SAFE_W) // 2
    top = (FRAME_H - SAFE_H) // 2
    return (left, top, left + SAFE_W, top + SAFE_H)


def line_at(i: int, offset: float = 0.0) -> int:
    """Where grid line `i` falls, in pixels.

    Computed as round(i * PITCH) from the origin every time, NEVER by stepping
    a rounded integer. Stepping 108 accumulates about a square and a half of
    drift across the full width -- which is invisible in code review and very
    visible when a miniature at the far edge sits a whole square off.
    """
    return int(round(i * PITCH + offset))


def squares_across(width: int = FRAME_W) -> float:
    """How many 5 ft squares fit across `width` pixels. ~35.6 on this table."""
    return width / PITCH


def squares_down(height: int = FRAME_H) -> float:
    """How many 5 ft squares fit down `height` pixels. ~20.0 on this table."""
    return height / PITCH


def feet_per_square(scale: float = 1.0) -> float:
    """Real-world size of a square when the map is shown at `scale`.

    5.0 at true scale. Anything else means the map was scaled down to fit
    (spec section 8.4) and miniature bases will not match the squares -- which
    is a legitimate choice for travel and exploration maps, but one the user
    must have made knowingly.
    """
    return 5.0 / scale if scale else 5.0


def draw(image: Image.Image,
         pitch: float = PITCH,
         offset_x: float = 0.0,
         offset_y: float = 0.0,
         width: int = LINE_WIDTH,
         opacity: float = LINE_OPACITY,
         rgb: Tuple[int, int, int] = LINE_RGB) -> Image.Image:
    """Return a copy of `image` with the grid drawn over it.

    `offset_x` / `offset_y` shift the grid's *phase* -- where the first line
    falls. Pitch alone is not enough: a map whose rooms sit half a square off
    the table's grid puts every miniature in the wrong place, and phase is
    what fixes that.

    Drawn onto a separate transparent layer and composited, rather than
    straight onto the artwork, so `opacity` is a true alpha blend. Drawing
    semi-transparent lines directly with ImageDraw would not blend -- it would
    just paint a flat colour.
    """
    if pitch <= 0:
        raise ValueError("grid pitch must be positive, got %r" % (pitch,))

    base = image.convert("RGBA")
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    pen = ImageDraw.Draw(layer)
    colour = (rgb[0], rgb[1], rgb[2], int(round(max(0.0, min(1.0, opacity)) * 255)))

    w, h = base.size

    # Start at the lowest line index that is still on-screen, so a negative
    # offset (grid phase shifted left/up) does not simply lose its first line.
    i = int((-offset_x) // pitch)
    while True:
        x = int(round(i * pitch + offset_x))
        if x > w:
            break
        if x >= 0:
            pen.line([(x, 0), (x, h)], fill=colour, width=width)
        i += 1

    j = int((-offset_y) // pitch)
    while True:
        y = int(round(j * pitch + offset_y))
        if y > h:
            break
        if y >= 0:
            pen.line([(0, y), (w, y)], fill=colour, width=width)
        j += 1

    return Image.alpha_composite(base, layer).convert("RGB")


def draw_hex(image: Image.Image,
             pitch: float = PITCH,
             offset_x: float = 0.0,
             offset_y: float = 0.0,
             width: int = LINE_WIDTH,
             opacity: float = LINE_OPACITY,
             rgb: Tuple[int, int, int] = LINE_RGB) -> Image.Image:
    """Return a copy of `image` with a flat-top hex grid drawn over it.

    `pitch` is the hex's flat-to-flat height, so it means the same thing it
    does for squares: one 5 ft space. Passing a scaled pitch draws a scaled
    grid, which is how the proxy preview stays honest.

    Each hexagon is stroked as a closed polygon, so neighbours redraw their
    shared edges. That is fine and is why this composites through a layer
    rather than blending: ImageDraw WRITES pixel values, it does not blend
    them, so an edge drawn twice is not twice as opaque. Blend once, at the
    end, exactly as the square grid does.
    """
    if pitch <= 0:
        raise ValueError("hex pitch must be positive, got %r" % (pitch,))

    base = image.convert("RGBA")
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    pen = ImageDraw.Draw(layer)
    colour = (rgb[0], rgb[1], rgb[2],
              int(round(max(0.0, min(1.0, opacity)) * 255)))

    w, h = base.size
    scale = pitch / PITCH
    r = HEX_R * scale
    col = HEX_COL_SPACING * scale
    row = HEX_ROW_SPACING * scale

    # Flat-top: vertices at 0, 60, 120, 180, 240, 300 degrees.
    unit = [(math.cos(math.radians(a)) * r, math.sin(math.radians(a)) * r)
            for a in range(0, 360, 60)]

    # Start a column early and finish one late so partial hexes at the edges
    # are drawn rather than leaving a bare margin.
    i0 = int(math.floor((-offset_x - r) / col)) - 1
    i1 = int(math.ceil((w - offset_x + r) / col)) + 1
    for i in range(i0, i1 + 1):
        cx = offset_x + i * col
        stagger = (row / 2.0) if (i % 2) else 0.0
        j0 = int(math.floor((-offset_y - stagger - r) / row)) - 1
        j1 = int(math.ceil((h - offset_y - stagger + r) / row)) + 1
        for j in range(j0, j1 + 1):
            cy = offset_y + stagger + j * row
            pts = [(cx + dx, cy + dy) for dx, dy in unit]
            pen.line(pts + [pts[0]], fill=colour, width=width, joint="curve")

    return Image.alpha_composite(base, layer).convert("RGB")


def draw_overlay(image: Image.Image,
                 style: str = SQUARE,
                 colour: str = WHITE,
                 pitch: float = PITCH,
                 offset_x: float = 0.0,
                 offset_y: float = 0.0,
                 width: int = LINE_WIDTH) -> Image.Image:
    """Draw whichever overlay the map asked for. The one entry point callers
    should use, so a new style is a change here and nowhere else."""
    style = (style or NONE).lower()
    if style == NONE:
        return image.convert("RGB")

    rgb, opacity = colour_for(colour)
    fn = draw_hex if style == HEX else draw
    return fn(image, pitch=pitch, offset_x=offset_x, offset_y=offset_y,
              width=width, opacity=opacity, rgb=rgb)


def draw_safe_area(image: Image.Image,
                   rgb: Tuple[int, int, int] = (255, 96, 96),
                   opacity: float = 0.5) -> Image.Image:
    """Outline the overscan safe box. For the editor preview only.

    Never call this on anything that gets published -- it is a guide, not part
    of the artwork.
    """
    base = image.convert("RGBA")
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    pen = ImageDraw.Draw(layer)

    # The box is defined against the full frame; scale it to whatever size we
    # are actually drawing on, so this works on the 960x540 proxy too.
    sx = base.size[0] / float(FRAME_W)
    sy = base.size[1] / float(FRAME_H)
    left, top, right, bottom = safe_box()
    box = [left * sx, top * sy, right * sx - 1, bottom * sy - 1]

    alpha = int(round(max(0.0, min(1.0, opacity)) * 255))
    pen.rectangle(box, outline=(rgb[0], rgb[1], rgb[2], alpha), width=2)
    return Image.alpha_composite(base, layer).convert("RGB")
