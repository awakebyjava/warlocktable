"""Brightness, contrast, and the measurement that makes them honest.

display-image-specifications.md section 3 is blunt about this being "the
instruction most likely to be skipped and most likely to ruin the result".
The screen faces upward into people's faces for hours in a dim room. A bright
map is a lamp pointed at the players.

The problem with a brightness slider is that it will be judged by eye, on an
iPad, in a lit room -- which is exactly the condition under which a too-bright
image looks fine. So this module measures, and the tool reports a number.

All statistics come from PIL's own histogram, which is computed in C over the
whole image. No numpy: keeping the Pi's dependency list at `python3-pil`
alone is a hard requirement of the spec, and a 256-bin histogram is all any
of this needs anyway.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Sequence

from PIL import Image, ImageEnhance

# A pixel at or above this is "near-white". The display spec calls out large
# white or near-white areas as the specific thing that is blinding on an
# upward-facing panel, so it is reported separately from the mean -- an image
# can have a perfectly respectable average and still have a searing highlight.
NEAR_WHITE = 230

# Used only when the reference backgrounds cannot be measured (a fresh
# install, or a laptop with no artwork). The real figure is measured from the
# artwork actually present and stored in config.
#
# MEASURED from the shipped five, 2026-09-05:
#
#     swamp     20.45      forest    24.31      island   24.10
#     mountain  29.30      plains    49.64      mean --> 29.56
#
# and near-white content across all five is exactly 0.000%. That is a very
# dark house style -- an ordinary photograph or a downloaded battle map runs
# a mean of 110-140, so four to five times brighter. Expect the brightness
# warning to fire on nearly every upload. That is not the warning being
# oversensitive; it is the gap being real.
FALLBACK_TARGET = 29.6

# The brightest of the shipped five (plains, 49.64). What auto-brightness
# aims at, so a map stays readable. See house_levels().
FALLBACK_CEILING = 49.6


def _histogram(image: Image.Image) -> List[int]:
    return image.convert("L").histogram()


def mean_luminance(image: Image.Image) -> float:
    """Mean luminance, 0-255."""
    hist = _histogram(image)
    total = sum(hist)
    if not total:
        return 0.0
    return sum(i * n for i, n in enumerate(hist)) / float(total)


def near_white_fraction(image: Image.Image, threshold: int = NEAR_WHITE) -> float:
    """Fraction of pixels at or above `threshold`, 0.0-1.0."""
    hist = _histogram(image)
    total = sum(hist)
    if not total:
        return 0.0
    return sum(hist[threshold:]) / float(total)


def measure(image: Image.Image) -> Dict[str, float]:
    """Everything the panel needs to say something true about brightness."""
    hist = _histogram(image)
    total = sum(hist) or 1

    cumulative = 0
    p50 = p95 = 255
    for i, n in enumerate(hist):
        cumulative += n
        if p50 == 255 and cumulative >= total * 0.50:
            p50 = i
        if cumulative >= total * 0.95:
            p95 = i
            break

    return {
        "mean": sum(i * n for i, n in enumerate(hist)) / float(total),
        "median": float(p50),
        "p95": float(p95),
        "near_white": sum(hist[NEAR_WHITE:]) / float(total),
    }


def house_levels(background_paths: Sequence[str],
                 limit: int = 12) -> Optional[Dict[str, float]]:
    """Mean and ceiling luminance of the artwork already on this table.

    TWO NUMBERS, USED FOR DIFFERENT THINGS, and the distinction is the whole
    point of this function:

      "mean"    the house average. What the WARNING is measured against --
                the question it answers is "is this brighter than what you
                normally sit around for four hours".

      "ceiling" the brightest background already in use. What the auto
                brightness DEFAULT aims at.

    Targeting the mean for the default was the obvious thing to do and it was
    wrong. The existing backgrounds are atmospheric texture; they are meant to
    be barely-there. A battle map has to be READ -- players need to see the
    walls and doors they are moving miniatures between. Pulling a map down to
    the average of five ambient backgrounds makes it unreadable.

    The ceiling keeps the default honest without making it unusable: it is as
    bright as the brightest thing already accepted on this table, so it cannot
    drift outside the house style, but it leaves a map legible.
    """
    values = _measure_backgrounds(background_paths, limit)
    if not values:
        return None
    return {"mean": sum(values) / float(len(values)),
            "ceiling": max(values),
            "count": float(len(values))}


def house_target(background_paths: Sequence[str],
                 limit: int = 12) -> Optional[float]:
    """Mean luminance of the existing backgrounds -- the house style, measured.

    This is the whole trick: rather than inventing a threshold, ask what the
    artwork already on this table actually looks like, and hold new uploads
    to the same standard. Returns None if nothing could be measured, so the
    caller can decide whether to fall back or simply not warn.

    Only the plain artwork is measured. The `_grid` variants are the same
    images with white lines drawn over them, which would drag the average up
    by a hair and, worse, make the target depend on how many gridded variants
    happen to be on disk.
    """
    values = _measure_backgrounds(background_paths, limit)
    if not values:
        return None
    return sum(values) / float(len(values))


def _measure_backgrounds(background_paths: Sequence[str],
                         limit: int = 12) -> List[float]:
    seen = []
    for base_dir in background_paths:
        if not os.path.isdir(base_dir):
            continue
        for fn in sorted(os.listdir(base_dir)):
            if fn.startswith("."):
                continue
            stem, ext = os.path.splitext(fn)
            if ext.lower() not in (".png", ".jpg", ".jpeg"):
                continue
            low = stem.lower()
            if low.endswith("_grid") or low.endswith("_hex"):
                continue
            try:
                with Image.open(os.path.join(base_dir, fn)) as im:
                    # Measuring a thumbnail rather than 8 megapixels: the mean
                    # of a box-filtered reduction is the mean of the original,
                    # and this keeps a first run on the Pi to a second or two.
                    seen.append(mean_luminance(im.resize((256, 144), Image.BOX)))
            except Exception:          # noqa: BLE001 - a bad file is not fatal
                continue
            if len(seen) >= limit:
                break

    return seen


def suggest_brightness(image: Image.Image,
                       target: float,
                       lo: float = 0.15,
                       hi: float = 1.5) -> float:
    """Brightness multiplier that lands `image` near `target` mean luminance.

    The default the editor opens with, so the slider starts correct and exists
    for taste rather than rescue.

    A straight ratio, then clamped. Brightness in PIL is a linear multiply, so
    for anything not already clipping the ratio is very close to exact -- and
    where it is not, the user has a slider and a preview.
    """
    current = mean_luminance(image)
    if current <= 0.5:
        return 1.0
    return max(lo, min(hi, target / current))


def apply(image: Image.Image,
          brightness: float = 1.0,
          contrast: float = 1.0) -> Image.Image:
    """Apply brightness then contrast.

    Order matters and is deliberate: pulling brightness down flattens an
    image, and contrast is how the depth comes back. Doing it the other way
    round darkens the contrast boost along with everything else, which is not
    what the sliders appear to promise.
    """
    out = image
    if abs(brightness - 1.0) > 1e-3:
        out = ImageEnhance.Brightness(out).enhance(brightness)
    if abs(contrast - 1.0) > 1e-3:
        out = ImageEnhance.Contrast(out).enhance(contrast)
    return out


def warning_for(image: Image.Image, target: Optional[float]) -> Optional[str]:
    """A sentence to show the user, or None if there is nothing to say.

    Never blocks. It is a warning with a real number attached; the GM decides.
    """
    if not target or target <= 0:
        return None

    stats = measure(image)
    over = (stats["mean"] - target) / target

    if over > 0.15:
        msg = ("This map is %d%% brighter than your existing backgrounds. "
               "It will be noticeably brighter in the room."
               % int(round(over * 100)))
        if stats["near_white"] > 0.02:
            msg += (" %.1f%% of it is near-white, which is the part that is "
                    "genuinely blinding on an upward-facing screen."
                    % (stats["near_white"] * 100.0))
        return msg

    if stats["near_white"] > 0.05:
        return ("%.1f%% of this map is near-white. On a screen that points up "
                "at the players, large pale areas are the thing that hurts."
                % (stats["near_white"] * 100.0))

    return None
