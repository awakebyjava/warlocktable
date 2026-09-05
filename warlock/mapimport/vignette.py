"""The dark vignette bleed -- what fills the frame where the map does not.

Source maps are rarely 16:9, so something has to occupy the gutters. Pasting
the map on flat black leaves a hard bright/dark seam running down the frame,
right where it sits in the players' peripheral vision, and it reads as a
mistake rather than a choice.

Instead the gutters get a heavily blurred, darkened copy of the map itself,
with the map's own edge feathered into it. The map appears to fade off into
darkness. It suits the table, and it keeps emitted light lowest at exactly
the frame edges nearest people's faces.

TWO PERFORMANCE TRICKS, both load-bearing on a Pi 4:

  * A large-radius Gaussian over 8 megapixels is slow. Blur a small copy with
    a proportionally smaller radius and scale it up. For a blur this heavy the
    result is indistinguishable, and it is roughly sixty times faster.

  * Generating a radial gradient pixel by pixel in Python is 8 million
    iterations. Generate it at 160x90 and upscale bicubically -- a smooth
    gradient is exactly the thing that survives upscaling perfectly.
"""

from __future__ import annotations

from typing import Optional, Tuple

from PIL import Image, ImageFilter

from . import grid

# How far the map's edge dissolves into the bleed, in output pixels.
FEATHER_PX = 120

# The bleed is this fraction of the map's own brightness before the radial
# darkening is applied on top. Deliberately heavy: this is background for a
# background.
BLEED_LEVEL = 0.28

# How dark the frame corners go relative to the frame centre.
EDGE_FALLOFF = 0.45

# Working size for the blur. Small enough to be fast, large enough that
# upscaling does not introduce visible blocking.
_BLUR_W = 480


def _cover(image: Image.Image, frame: Tuple[int, int]) -> Image.Image:
    """Scale-and-crop `image` so it fills `frame` completely."""
    fw, fh = frame
    sw, sh = image.size
    if sw <= 0 or sh <= 0:
        return Image.new("RGB", frame, (0, 0, 0))

    scale = max(fw / float(sw), fh / float(sh))
    new = (max(1, int(round(sw * scale))), max(1, int(round(sh * scale))))
    out = image.resize(new, Image.BICUBIC)
    left = (new[0] - fw) // 2
    top = (new[1] - fh) // 2
    return out.crop((left, top, left + fw, top + fh))


def _radial_mask(frame: Tuple[int, int], falloff: float) -> Image.Image:
    """An 'L' mask: bright in the centre, dark at the corners.

    Built at 160x90 and upscaled. Anything smooth upscales cleanly, and doing
    it this way turns 8 million Python iterations into 14 thousand.
    """
    small_w, small_h = 160, 90
    mask = Image.new("L", (small_w, small_h))
    px = mask.load()

    cx = (small_w - 1) / 2.0
    cy = (small_h - 1) / 2.0
    # Normalise by the corner distance so the falloff reaches exactly the
    # stated level at the corners regardless of aspect.
    max_d = (cx * cx + cy * cy) ** 0.5 or 1.0

    for y in range(small_h):
        dy = (y - cy) / max_d
        for x in range(small_w):
            dx = (x - cx) / max_d
            d = (dx * dx + dy * dy) ** 0.5
            # Squared falloff: gentle across the middle, decisive at the edge,
            # which is where the light actually needs pulling down.
            v = 1.0 - falloff * (d * d)
            px[x, y] = int(round(max(0.0, min(1.0, v)) * 255))

    return mask.resize(frame, Image.BICUBIC)


def background(source: Image.Image,
               frame: Tuple[int, int] = grid.FRAME,
               level: float = BLEED_LEVEL,
               falloff: float = EDGE_FALLOFF) -> Image.Image:
    """The blurred, darkened bleed that fills the whole frame."""
    fw, fh = frame

    # Blur small, then upscale. Radius is scaled to match, so the visual
    # result is the same as a radius-90 blur at full size.
    small_h = max(1, int(round(_BLUR_W * fh / float(fw))))
    small = _cover(source.convert("RGB"), (_BLUR_W, small_h))
    small = small.filter(ImageFilter.GaussianBlur(radius=_BLUR_W / 40.0))
    out = small.resize(frame, Image.BICUBIC)

    # Darken uniformly, then again towards the edges.
    black = Image.new("RGB", frame, (0, 0, 0))
    out = Image.blend(black, out, max(0.0, min(1.0, level)))
    return Image.composite(out, black, _radial_mask(frame, falloff))


def feather(layer: Image.Image, radius: int = FEATHER_PX) -> Image.Image:
    """Soften an RGBA layer's edges INWARD.

    Blurring the alpha channel alone would spread the map outward into the
    gutter as a smear. Multiplying the blurred alpha by the original confines
    the softening to pixels the map already covered, so the edge dissolves
    rather than bleeding.
    """
    if radius <= 0:
        return layer

    rgba = layer.convert("RGBA")
    alpha = rgba.getchannel("A")
    softened = alpha.filter(ImageFilter.GaussianBlur(radius=radius / 2.0))
    # ImageChops.multiply is (a*b)/255, i.e. exactly the product we want.
    from PIL import ImageChops
    rgba.putalpha(ImageChops.multiply(softened, alpha))
    return rgba


def compose(map_layer: Image.Image,
            source: Image.Image,
            frame: Tuple[int, int] = grid.FRAME,
            feather_px: int = FEATHER_PX,
            plain_black: bool = False) -> Image.Image:
    """Put the placed map over its bleed. Returns RGB, frame-sized.

    `plain_black=True` is the escape hatch for anyone who wants a hard edge
    rather than the bleed.
    """
    if plain_black:
        base = Image.new("RGB", frame, (0, 0, 0))
        soft = map_layer.convert("RGBA")
    else:
        base = background(source, frame)
        soft = feather(map_layer, feather_px)

    out = base.convert("RGBA")
    out = Image.alpha_composite(out, soft)
    return out.convert("RGB")
