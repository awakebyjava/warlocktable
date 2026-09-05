"""Pan, scale and rotation -- composed into ONE resample.

The single most important thing in this file is that scale and rotation are
never applied as separate steps. Each resample softens the image a little, and
a map is looked at from two feet away where that softening is plainly visible.
So we build one affine matrix and apply it once.

Second most important: PIL's affine transform point-samples through the
filter kernel. It does not area-average, so shrinking a 6000 px map straight
to 3840 aliases badly -- fine detail turns into shimmer, which the display
spec specifically warns about as the thing that moires on this panel. The fix
is an integer box pre-reduction (section `_prereduce`), which is a true
average and costs almost nothing.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

from PIL import Image

from . import grid


class Transform(object):
    """Where the map sits in the frame.

    pan_x / pan_y  offset of the MAP's centre from the FRAME's centre, in
                   output pixels. (0, 0) centres the map.
    scale          output pixels per source pixel. 1.0 = pixel for pixel.
    rotation       degrees, clockwise positive.

    Deliberately a plain object with plain floats: it is written to a recipe
    as JSON and read back months later, so it must not depend on anything
    clever surviving a round trip.
    """

    __slots__ = ("pan_x", "pan_y", "scale", "rotation")

    def __init__(self, pan_x=0.0, pan_y=0.0, scale=1.0, rotation=0.0):
        self.pan_x = float(pan_x)
        self.pan_y = float(pan_y)
        self.scale = float(scale)
        self.rotation = float(rotation)

    # --- serialisation ----------------------------------------------------

    def to_dict(self) -> dict:
        return {"pan_x": self.pan_x, "pan_y": self.pan_y,
                "scale": self.scale, "rotation": self.rotation}

    @classmethod
    def from_dict(cls, raw: Optional[dict]) -> "Transform":
        raw = raw or {}
        return cls(raw.get("pan_x", 0.0), raw.get("pan_y", 0.0),
                   raw.get("scale", 1.0), raw.get("rotation", 0.0))

    def replace(self, **kw) -> "Transform":
        """A copy with some fields changed. The editor adjusts one slider at
        a time, and mutating shared state is how undo stops working."""
        d = self.to_dict()
        d.update(kw)
        return Transform(**d)

    def __repr__(self):
        return ("Transform(pan=%.1f,%.1f scale=%.4f rot=%.2f)"
                % (self.pan_x, self.pan_y, self.scale, self.rotation))


# --- fitting ---------------------------------------------------------------

def fit_scale(src_size: Tuple[int, int],
              frame: Tuple[int, int] = grid.FRAME,
              cover: bool = False) -> float:
    """Scale that fits the source inside the frame (or covers it).

    `cover=True` is what the vignette background uses -- it must fill the
    frame with no gaps. `cover=False` is the editor's default starting point
    for a map with no detectable grid: show the whole thing.
    """
    sw, sh = src_size
    if sw <= 0 or sh <= 0:
        return 1.0
    sx = frame[0] / float(sw)
    sy = frame[1] / float(sh)
    return max(sx, sy) if cover else min(sx, sy)


def scale_for_squares(src_width: int, squares_across: float) -> float:
    """Scale that makes a map of known width land on the table's grid.

    The most reliable path in the whole tool, and the one to reach for
    whenever the map's size in squares is known: it is exact arithmetic
    rather than an estimate from image analysis.
    """
    if src_width <= 0 or squares_across <= 0:
        return 1.0
    return (squares_across * grid.PITCH) / float(src_width)


def scale_for_pitch(detected_pitch: float) -> float:
    """Scale that turns a map's own grid pitch into the table's."""
    if detected_pitch <= 0:
        return 1.0
    return grid.PITCH / float(detected_pitch)


def squares_covered(src_size: Tuple[int, int], scale: float) -> Tuple[float, float]:
    """How many table squares the map spans at this scale."""
    return (src_size[0] * scale / grid.PITCH,
            src_size[1] * scale / grid.PITCH)


# --- the resample ----------------------------------------------------------

def _prereduce(image: Image.Image, scale: float) -> Tuple[Image.Image, float]:
    """Box-average down by an integer factor before the affine transform.

    Returns the reduced image and the scale still left to apply.

    Why this exists: Image.transform samples the source through a small
    kernel. Ask it to shrink by 4x and it reads roughly every fourth pixel,
    so three quarters of the detail does not contribute at all -- which is
    exactly the fine high-contrast repeating detail that the display spec
    says shimmers and moires on this panel.

    Image.reduce is a true box average over every pixel, so nothing is
    discarded. Doing the integer part here and leaving the fractional
    remainder to the affine keeps this "one resample" in the sense that
    matters: only one *interpolating* pass.
    """
    if scale >= 0.5 or scale <= 0:
        return image, scale
    factor = int(1.0 / scale)          # >= 2 given the guard above
    # Never reduce a dimension away entirely on an extreme zoom-out.
    factor = max(1, min(factor, image.size[0] // 2, image.size[1] // 2))
    if factor < 2:
        return image, scale
    reduced = image.reduce(factor)
    return reduced, scale * factor


def render(image: Image.Image,
           tf: Transform,
           frame: Tuple[int, int] = grid.FRAME,
           resample: int = Image.BICUBIC) -> Image.Image:
    """Place `image` into a `frame`-sized RGBA canvas per `tf`. One resample.

    Areas the map does not cover come back fully transparent, so the caller
    can composite over whatever background it likes -- which is how the
    vignette bleed gets underneath it.

    Uses Image.BICUBIC rather than Image.Resampling.BICUBIC: the enum is
    Pillow 9.1+, and the Pi has 8.1.
    """
    src = image.convert("RGBA")
    src, scale = _prereduce(src, tf.scale)

    sw, sh = src.size
    fw, fh = frame

    if scale <= 0:
        return Image.new("RGBA", frame, (0, 0, 0, 0))

    theta = math.radians(tf.rotation)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)

    # PIL's AFFINE maps OUTPUT coordinates back to INPUT coordinates:
    #     x_src = a*x_dst + b*y_dst + c
    #     y_src = d*x_dst + e*y_dst + f
    # so this is the inverse of the placement we actually want. Forward is
    #     dst = R(theta) * scale * (src - src_centre) + frame_centre + pan
    # and inverting gives the matrix below.
    a = cos_t / scale
    b = sin_t / scale
    d = -sin_t / scale
    e = cos_t / scale

    # Where the map's centre lands in the output frame.
    cx = fw / 2.0 + tf.pan_x
    cy = fh / 2.0 + tf.pan_y

    c = sw / 2.0 - (a * cx + b * cy)
    f = sh / 2.0 - (d * cx + e * cy)

    return src.transform(frame, Image.AFFINE, (a, b, c, d, e, f),
                         resample=resample, fillcolor=(0, 0, 0, 0))


def grid_phase(tf: Transform,
               src_size: Tuple[int, int],
               map_grid_origin: Tuple[float, float] = (0.0, 0.0)) -> Tuple[float, float]:
    """Where the map's own grid origin lands in the output frame.

    Used to align the table's drawn grid to a map that already has one, so the
    two coincide instead of sitting a fraction of a square apart. Returns the
    offset to hand to grid.draw(), wrapped into one pitch.

    Rotation is ignored here on purpose: a drawn grid only stays axis-aligned
    at multiples of 90 degrees, and at any other angle there is no single
    phase that could be correct. The editor's job is to get the map square to
    the frame; this reports the phase once it is.
    """
    sw, sh = src_size
    ox, oy = map_grid_origin
    scale = tf.scale

    x = (ox - sw / 2.0) * scale + grid.FRAME_W / 2.0 + tf.pan_x
    y = (oy - sh / 2.0) * scale + grid.FRAME_H / 2.0 + tf.pan_y

    return (x % grid.PITCH, y % grid.PITCH)
