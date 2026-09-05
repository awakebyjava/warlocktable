"""The table's grid: one constant, and the code that draws it.

EVERY number here comes from display-image-specifications.md, which is the
authority. Nothing in this package may hardcode a copy of them -- the whole
reason recipes are stored (spec section 11) is so that if PITCH is ever
re-measured, changing it here and re-rendering makes every custom map correct
again. A copied constant somewhere else would silently survive that edit and
quietly stay wrong.
"""

from __future__ import annotations

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
LINE_WIDTH = 2
LINE_OPACITY = 0.25
LINE_RGB = (255, 255, 255)


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
