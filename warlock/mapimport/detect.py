"""Estimating a map's own grid pitch and phase.

READ SECTION 2 OF THE SPEC BEFORE CHANGING ANYTHING HERE.

This module's output is a *starting guess for the sliders*, nothing more. It
does not gate anything, disable anything, or choose anything. If it is wrong,
the user moves a slider and no harm was done; if it refuses to answer, the
sliders simply start at a neutral value. That is why it is allowed to be a
heuristic rather than something rigorous -- the cost of it being wrong was
designed down to almost nothing.

The corollary matters more: it must never be *confidently* wrong in a way that
looks authoritative. Hence `confidence`, and hence the conservative thresholds.

NO NUMPY. Keeping the Pi's dependency list at `python3-pil` alone is a hard
requirement (spec section 5), so the heavy per-pixel work is pushed into PIL's
C implementations -- filtering, and `resize` to a single row/column, which is
a box average and therefore exactly the axis projection this needs. What is
left in Python is a few thousand floats.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageChops, ImageFilter

from . import grid

# Target length for the 1-D signal the autocorrelation runs over.
#
# NOTE THAT THIS IS NOT AN IMAGE SIZE. An earlier version resized the IMAGE to
# 1200 px wide before projecting, and it was wrong in a way worth recording:
# grid lines are 2 px at 25% opacity, and box-downscaling 3840 -> 1200
# attenuates them while shifting each one by a different sub-pixel amount.
# Every third line happened to land better than its neighbours, so the
# autocorrelation locked onto a beat at 3x the true pitch and reported 323 px
# for a 107.85 px grid -- confidently, which is the one thing this module must
# never be.
#
# Projecting at FULL resolution avoids it entirely: summing a whole column
# preserves a thin line's contribution exactly. Only afterwards is the 1-D
# signal box-decimated, which is safe because by then the lines are already
# integrated into it.
TARGET_SAMPLES = 1600

# A grid finer than this in working pixels cannot be told apart from texture.
MIN_PITCH = 8

# Confidence bands.
HIGH = "high"
LOW = "low"
FAILED = "failed"

# Normalised autocorrelation peak needed before we will claim anything.
_PEAK_HIGH = 0.30
_PEAK_LOW = 0.16

# X and Y pitch must agree within this to be called square.
_AGREE = 0.02


class Detection(object):
    """What detection thinks, and how much it believes itself."""

    __slots__ = ("pitch", "pitch_x", "pitch_y", "offset_x", "offset_y",
                 "confidence", "message")

    def __init__(self, pitch=None, pitch_x=None, pitch_y=None,
                 offset_x=0.0, offset_y=0.0,
                 confidence=FAILED, message=""):
        self.pitch = pitch
        self.pitch_x = pitch_x
        self.pitch_y = pitch_y
        self.offset_x = offset_x
        self.offset_y = offset_y
        self.confidence = confidence
        self.message = message

    @property
    def found(self) -> bool:
        return self.pitch is not None and self.confidence != FAILED

    def to_dict(self) -> Dict:
        return {"pitch": self.pitch, "pitch_x": self.pitch_x,
                "pitch_y": self.pitch_y, "offset_x": self.offset_x,
                "offset_y": self.offset_y, "confidence": self.confidence,
                "message": self.message}

    def __repr__(self):
        return "Detection(%s px, %s)" % (
            None if self.pitch is None else round(self.pitch, 2),
            self.confidence)


# --- signal helpers --------------------------------------------------------

def _projection(edges: Image.Image, axis: int) -> List[float]:
    """Collapse an edge image to one axis.

    axis=0 -> one value per column (finds vertical lines)
    axis=1 -> one value per row    (finds horizontal lines)

    `resize` to a single row or column with BOX is a true mean over the other
    axis, computed in C. Doing this in Python would be millions of iterations.
    """
    w, h = edges.size
    if axis == 0:
        strip = edges.resize((w, 1), Image.BOX)
    else:
        strip = edges.resize((1, h), Image.BOX)
    # tobytes() on an 'L' image is the raw samples, and unlike getdata() it is
    # not deprecated on new Pillow while still existing on 8.1.
    return [float(v) for v in strip.tobytes()]


def _decimate(signal: List[float], target: int = TARGET_SAMPLES) -> Tuple[List[float], float]:
    """Box-average a 1-D signal down to about `target` samples.

    Returns the signal and the factor its indices were divided by, so a lag
    measured on it can be converted back to source pixels.

    Safe in a way that downscaling the image is not: the grid lines have
    already been integrated into this signal, so averaging neighbouring
    samples is a genuine low-pass rather than a resampling that can drop or
    displace a 2 px feature.
    """
    n = len(signal)
    if n <= target * 2:
        return signal, 1.0

    factor = int(n // target)
    if factor < 2:
        return signal, 1.0

    out = []
    for i in range(0, n - factor + 1, factor):
        out.append(sum(signal[i:i + factor]) / float(factor))
    return out, float(factor)


def _detrend(signal: List[float], window: int = 51) -> List[float]:
    """Remove slow variation so only periodic structure survives.

    Artwork brightens and darkens across a map; that trend would otherwise
    dominate the autocorrelation and swamp the grid entirely. A moving-average
    subtraction is crude but is the right kind of crude here -- we care only
    about whether something repeats, not about its absolute level.
    """
    n = len(signal)
    if n < window * 2:
        mean = sum(signal) / float(n or 1)
        return [v - mean for v in signal]

    half = window // 2
    # Running sum, so this stays O(n) rather than O(n * window).
    out = []
    total = sum(signal[:half + 1])
    count = half + 1
    for i in range(n):
        if i > half:
            total -= signal[i - half - 1]
            count -= 1
        if i + half < n:
            total += signal[i + half]
            count += 1
        out.append(signal[i] - total / float(count))
    return out


def _autocorrelate(signal: List[float], min_lag: int, max_lag: int) -> List[float]:
    """Normalised autocorrelation over a lag range. Index 0 is `min_lag`."""
    n = len(signal)
    energy = sum(v * v for v in signal)
    if energy <= 0:
        return []

    out = []
    for lag in range(min_lag, max_lag + 1):
        acc = 0.0
        # Step through the overlap; on a long signal a stride keeps this
        # quick without changing the shape of the result.
        stride = 1 if n - lag < 4000 else 2
        count = 0
        for i in range(0, n - lag, stride):
            acc += signal[i] * signal[i + lag]
            count += 1
        # Normalise by the overlap length so short lags are not favoured.
        out.append(acc / float(count) if count else 0.0)

    peak = max(out) if out else 0.0
    scale = energy / float(n)
    if scale <= 0:
        return []
    return [v / scale for v in out]


def _best_pitch(signal: List[float], max_lag: int) -> Tuple[Optional[float], float]:
    """Fundamental period of `signal`, and the strength of the evidence."""
    if max_lag <= MIN_PITCH:
        return None, 0.0

    corr = _autocorrelate(signal, MIN_PITCH, max_lag)
    if not corr:
        return None, 0.0

    best_i = max(range(len(corr)), key=lambda i: corr[i])
    best = corr[best_i]
    if best <= 0:
        return None, 0.0

    # Prefer the SMALLEST lag that is nearly as good as the best. A signal
    # with period p correlates just as well at 2p and 3p, and picking a
    # harmonic would scale the map to half or a third of its true size --
    # a large, obvious error produced with total confidence.
    chosen = best_i
    for i in range(len(corr)):
        if corr[i] >= best * 0.90:
            # Require a genuine local maximum, so we do not latch onto the
            # shoulder of the real peak.
            left = corr[i - 1] if i > 0 else 0.0
            right = corr[i + 1] if i + 1 < len(corr) else 0.0
            if corr[i] >= left and corr[i] >= right:
                chosen = i
                break

    lag = chosen + MIN_PITCH

    # Parabolic interpolation against the two neighbours for sub-pixel pitch.
    # Worth doing: a half-pixel error at a 60 px pitch is nearly a whole
    # square of drift across a 35-square map.
    if 0 < chosen < len(corr) - 1:
        y0, y1, y2 = corr[chosen - 1], corr[chosen], corr[chosen + 1]
        denom = (y0 - 2 * y1 + y2)
        if abs(denom) > 1e-9:
            shift = 0.5 * (y0 - y2) / denom
            if -1.0 < shift < 1.0:
                return lag + shift, best
    return float(lag), best


def _best_phase(signal: List[float], pitch: float) -> float:
    """Where the first grid line sits, 0 <= offset < pitch.

    Pitch alone puts the squares the right SIZE; phase puts them in the right
    PLACE. A map whose rooms sit half a square off the table's grid has every
    miniature standing wrong, and that is a phase error, not a pitch error.
    """
    if pitch < 2:
        return 0.0

    n = len(signal)
    steps = max(8, min(int(round(pitch)), 240))
    best_off, best_score = 0.0, None

    for s in range(steps):
        off = pitch * s / float(steps)
        score = 0.0
        i = 0
        while True:
            x = int(round(off + i * pitch))
            if x >= n:
                break
            score += signal[x]
            i += 1
        if i:
            score /= float(i)
        if best_score is None or score > best_score:
            best_score, best_off = score, off

    return best_off


# --- the entry point -------------------------------------------------------

def detect(image: Image.Image) -> Detection:
    """Estimate the pitch and phase of a grid printed on `image`.

    Never raises. A failure to detect is an ordinary outcome, not an error --
    plenty of perfectly good maps have no grid at all.
    """
    try:
        return _detect(image)
    except Exception as exc:           # noqa: BLE001
        return Detection(confidence=FAILED,
                         message="Grid detection could not run (%s). Set the "
                                 "scale manually, or enter the map's width in "
                                 "squares." % type(exc).__name__)


def _detect(image: Image.Image) -> Detection:
    src_w, src_h = image.size
    if src_w < 64 or src_h < 64:
        return Detection(confidence=FAILED, message="This image is too small "
                                                    "to detect a grid in.")

    grey = image.convert("L")
    w, h = grey.size

    # Directional differences rather than FIND_EDGES: a horizontal difference
    # responds to VERTICAL lines and ignores horizontal ones, so the two axes
    # are measured independently instead of each polluting the other.
    #
    # Done at FULL resolution -- see the note on TARGET_SAMPLES. These are
    # C-level crops and a subtract, so the cost is small even at 8 megapixels,
    # and the projection that follows is a C-level box average.
    dx = ImageChops.difference(grey.crop((1, 0, w, h)), grey.crop((0, 0, w - 1, h)))
    dy = ImageChops.difference(grey.crop((0, 1, w, h)), grey.crop((0, 0, w, h - 1)))

    raw_x = _projection(dx, axis=0)
    raw_y = _projection(dy, axis=1)

    # Only now is it safe to shorten the signals.
    sig_x, dec_x = _decimate(raw_x)
    sig_y, dec_y = _decimate(raw_y)

    sig_x = _detrend(sig_x)
    sig_y = _detrend(sig_y)

    # A grid we cannot see at least four repeats of is not a grid we can trust.
    max_lag_x = max(MIN_PITCH + 1, len(sig_x) // 4)
    max_lag_y = max(MIN_PITCH + 1, len(sig_y) // 4)

    pitch_x, score_x = _best_pitch(sig_x, max_lag_x)
    pitch_y, score_y = _best_pitch(sig_y, max_lag_y)

    if pitch_x is None and pitch_y is None:
        return Detection(confidence=FAILED, message=_FAIL_MSG)

    # Back to source-image pixels. Each axis was decimated independently, so
    # each carries its own factor.
    src_px = None if pitch_x is None else pitch_x * dec_x
    src_py = None if pitch_y is None else pitch_y * dec_y
    score = max(score_x, score_y)

    # AGREEMENT BETWEEN THE AXES IS REQUIRED, not merely rewarded.
    #
    # This is the guard against the second failure found in testing: plain
    # artwork with no grid at all was returning a plausible-looking pitch with
    # "low" confidence, because texture always repeats at *some* period and a
    # single axis can always be talked into a peak. Artwork is very unlikely
    # to repeat at the SAME period both horizontally and vertically; a square
    # grid does so by definition. Requiring both axes to agree turns "usually
    # right" into "quiet when unsure", which is the behaviour section 2 asks
    # for.
    if not (src_px and src_py):
        return Detection(confidence=FAILED, message=_FAIL_MSG)

    if abs(src_px - src_py) / max(src_px, src_py) > _AGREE:
        return Detection(confidence=FAILED, message=_FAIL_MSG)

    pitch = (src_px + src_py) / 2.0

    if score < _PEAK_LOW or pitch < MIN_PITCH:
        return Detection(confidence=FAILED, message=_FAIL_MSG)

    confidence = HIGH if score >= _PEAK_HIGH else LOW

    off_x = _best_phase(sig_x, pitch / dec_x) * dec_x
    off_y = _best_phase(sig_y, pitch / dec_y) * dec_y

    if confidence == HIGH:
        message = ("Detected a %d px grid; scaled to match the table."
                   % int(round(pitch)))
    else:
        message = ("Grid detection was uncertain (best guess %d px). Check the "
                   "alignment before saving." % int(round(pitch)))

    return Detection(pitch=pitch, pitch_x=src_px, pitch_y=src_py,
                     offset_x=off_x, offset_y=off_y,
                     confidence=confidence, message=message)


_FAIL_MSG = ("No grid detected. Set the scale manually, or enter the map's "
             "width in squares.")


def squares_from_pitch(src_width: int, pitch: Optional[float]) -> Optional[float]:
    """How many squares wide the map is, if a pitch was found."""
    if not pitch or pitch <= 0:
        return None
    return src_width / float(pitch)
