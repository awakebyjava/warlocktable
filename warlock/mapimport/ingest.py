"""Getting an arbitrary uploaded file to a normalised RGB image.

Everything downstream assumes 8-bit sRGB RGB, the right way up, of a sane
size. This module is what makes that true, and it is where the format-specific
unpleasantness is allowed to live.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Dict, Optional, Tuple

from PIL import Image, ImageOps

from .errors import ImageTooLargeError, UnsupportedImageError

# Beyond this on either axis we refuse BEFORE decoding. A 25000 x 25000 PNG
# decodes to about 1.9 GB, which on a 4 GB Pi means the OOM killer, and the
# process it kills might be the one running the table. A refusal is a much
# better failure than a dead service mid-session.
MAX_DIMENSION = 16000

# And a cap on TOTAL pixels, which is the number that actually predicts
# memory: 16000 x 16000 is within the dimension cap above but is 256
# megapixels, about 768 MB decoded.
#
# 80 MP also sits below Pillow's own decompression-bomb threshold (~179 MP),
# which matters for the reason found in testing: Pillow raises
# DecompressionBombError from Image.open BEFORE we can read .size, so an
# image between the two limits would be refused with "could not be read as an
# image" instead of a message explaining that it is too big. Keeping our cap
# strictly below Pillow's means our message is always the one the user sees.
#
# For scale: a 48 MP iPhone photo is well inside this, and so is any battle
# map anyone actually distributes.
MAX_PIXELS = 80 * 1000 * 1000

MAX_UPLOAD_BYTES = 80 * 1024 * 1024

# The editor works on this, not the full-resolution image, so sliders stay
# responsive on a Pi 4 no matter how large the upload was.
PROXY_W = 960
PROXY_H = 540

HEIF_EXTENSIONS = (".heic", ".heif", ".hif")
DIRECT_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif")


class Source(object):
    """A normalised upload, ready for the editor."""

    __slots__ = ("path", "proxy_path", "width", "height",
                 "original_name", "converted_from")

    def __init__(self, path, proxy_path, width, height,
                 original_name, converted_from=None):
        self.path = path
        self.proxy_path = proxy_path
        self.width = width
        self.height = height
        self.original_name = original_name
        self.converted_from = converted_from

    @property
    def size(self) -> Tuple[int, int]:
        return (self.width, self.height)

    def to_dict(self) -> Dict:
        return {"width": self.width, "height": self.height,
                "original_name": self.original_name,
                "converted_from": self.converted_from}


# --- HEIC ------------------------------------------------------------------

def _looks_like_heif(path: str) -> bool:
    """Sniff the container rather than trusting the extension.

    Phones and messaging apps rename things freely, and a .jpg that is really
    a HEIC would otherwise fail with a confusing decode error rather than
    being routed to the converter.
    """
    if path.lower().endswith(HEIF_EXTENSIONS):
        return True
    try:
        with open(path, "rb") as fh:
            head = fh.read(16)
    except OSError:
        return False
    # ISO-BMFF: [4-byte size]"ftyp"[4-byte brand]
    return head[4:8] == b"ftyp" and head[8:12] in (
        b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heim", b"heis")


def heif_available() -> bool:
    return shutil.which("heif-convert") is not None


def _convert_heif(path: str, workdir: str) -> str:
    """HEIC -> PNG via the libheif CLI. Returns the new path.

    Shelling out rather than importing pillow-heif is a deliberate dependency
    decision (spec section 5): wheel availability for pillow-heif on Bullseye
    / Python 3.9 / ARM is not guaranteed, and this project has already been
    burned once by a package that tried to build from source on the Pi. A
    subprocess has no Python dependency surface at all, and the codebase
    already shells out to feh and xrandr.
    """
    if not heif_available():
        raise UnsupportedImageError(
            "This looks like an iPhone HEIC image, but the converter is not "
            "installed. On the table, run:  sudo apt install libheif-examples")

    out = os.path.join(workdir, "heif-decoded.png")
    try:
        proc = subprocess.run(
            ["heif-convert", path, out],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
    except subprocess.TimeoutExpired:
        raise UnsupportedImageError(
            "Converting this HEIC image took too long and was stopped.")
    except OSError as exc:
        raise UnsupportedImageError("Could not run heif-convert: %s" % exc)

    # heif-convert may append a suffix when the file holds several images,
    # so accept the first thing it actually produced.
    if not os.path.exists(out):
        produced = sorted(f for f in os.listdir(workdir)
                          if f.startswith("heif-decoded"))
        if produced:
            out = os.path.join(workdir, produced[0])
        else:
            raise UnsupportedImageError(_heif_failure(proc))

    return out


def _heif_failure(proc) -> str:
    """Why heif-convert refused, said usefully.

    The distinction that matters: the converter being ABSENT and the
    converter being TOO OLD are completely different problems with completely
    different fixes, and an earlier version of this reported the second as the
    first -- telling someone to install a package they had already installed.

    MEASURED ON THE TABLE, 2026-09-05. Bullseye ships libheif 1.11.0 (2020).
    A photo from a current iPhone is a HEIC containing:

        tmap  an ISO 21496-1 HDR gain map   (iOS 18 HDR photos)
        grid  the picture as HEVC tiles assembled into a grid
        grpl  entity grouping tying the HDR pair together

    plus the brands MiHB / MiHE / MiPr. libheif only learned `tmap` in 1.18,
    so 1.11 parses the container, meets metadata it has no model for, and
    fails with "Metadata not correctly assigned to image".

    There is no code fix for this. Older HEICs still decode fine on 1.11, so
    this is not "HEIC is unsupported" -- it is this file being newer than the
    decoder. The routes out are all on the phone or the OS, so the message
    names them.
    """
    detail = (proc.stderr or b"").decode("utf-8", "replace").strip()
    if not detail:
        detail = (proc.stdout or b"").decode("utf-8", "replace").strip()

    too_new = ("Metadata not correctly assigned" in detail
               or "Unsupported feature" in detail
               or "No 'ftyp' box" in detail
               or "Unspecified" in detail)

    if too_new:
        return ("This photo is in a newer HEIC format than the table can "
                "read (its decoder is libheif 1.11, from 2020; iPhone HDR "
                "photos need 1.18 or later). Easiest fixes, in order: "
                "upload it from an iPhone or iPad through this page, which "
                "usually converts to JPEG on the way; or take a screenshot "
                "of the photo and upload that; or set "
                "Settings > Camera > Formats > Most Compatible on the phone "
                "so new photos are JPEG. "
                "Ordinary JPEG and PNG maps are unaffected.")

    return ("Could not read this HEIC image.%s"
            % (" " + detail if detail else ""))


# --- the main path ---------------------------------------------------------

def _check_dimensions(path: str) -> Tuple[int, int]:
    """Read the header only, and refuse before any decode happens.

    Image.open is lazy -- it parses the header and leaves the pixels alone
    until .load(). So .size here costs nothing and is the whole point: the
    cap has to be enforced before the memory is committed, not after.
    """
    # Pillow's own bomb guard fires inside Image.open, before .size can be
    # read. Lift it for the header read ONLY, so that our own limits below --
    # which are stricter, and have messages worth showing someone -- are what
    # actually decides. It is restored immediately, so the later decode still
    # has Pillow's protection behind ours.
    previous = Image.MAX_IMAGE_PIXELS
    try:
        Image.MAX_IMAGE_PIXELS = None
        with Image.open(path) as im:
            w, h = im.size
    except Exception as exc:           # noqa: BLE001
        raise UnsupportedImageError(
            "This file could not be read as an image (%s)."
            % type(exc).__name__)
    finally:
        Image.MAX_IMAGE_PIXELS = previous

    if w > MAX_DIMENSION or h > MAX_DIMENSION:
        raise ImageTooLargeError(
            "This image is %d x %d pixels. The limit is %d on either side -- "
            "anything larger risks running the table out of memory."
            % (w, h, MAX_DIMENSION))

    if w * h > MAX_PIXELS:
        raise ImageTooLargeError(
            "This image is %d x %d, which is %.0f megapixels. The limit is "
            "%d MP -- anything larger risks running the table out of memory. "
            "Scale it down and upload it again."
            % (w, h, (w * h) / 1e6, MAX_PIXELS // 1000000))

    return w, h


def normalise(image: Image.Image) -> Image.Image:
    """Right way up, 8-bit RGB, no alpha, no metadata.

    exif_transpose FIRST and unconditionally. iPhone photographs are very
    often stored rotated with an orientation tag rather than rotated in the
    pixels, and every viewer honours it -- so a map that looked correct on the
    phone arrives here on its side. Skip this and the user is left fighting
    the rotation slider to fix something that was never actually rotated.
    """
    out = ImageOps.exif_transpose(image)

    if out.mode in ("RGBA", "LA", "PA") or (
            out.mode == "P" and "transparency" in out.info):
        # Flatten onto black rather than white: this table's artwork is dark,
        # and a white matte would be the single brightest thing on screen.
        out = out.convert("RGBA")
        flat = Image.new("RGBA", out.size, (0, 0, 0, 255))
        out = Image.alpha_composite(flat, out)

    if out.mode != "RGB":
        out = out.convert("RGB")

    # A fresh image with no info dict: strips EXIF, GPS and colour profiles.
    # A map photographed at home should not carry the house's coordinates
    # into a file that later gets shared.
    clean = Image.new("RGB", out.size)
    clean.paste(out)
    return clean


def make_proxy(image: Image.Image,
               width: int = PROXY_W, height: int = PROXY_H) -> Image.Image:
    """A small copy for the editor. Aspect preserved, fits within the box."""
    proxy = image.copy()
    # thumbnail() is in-place, preserves aspect, and picks a good filter
    # chain for large reductions.
    proxy.thumbnail((width, height), Image.LANCZOS)
    return proxy


def ingest(upload_path: str, workdir: str) -> Source:
    """Take an uploaded file to a normalised PNG plus a proxy.

    `workdir` is a scratch directory owned by the caller; everything this
    function writes lands in it.
    """
    if not os.path.isfile(upload_path):
        raise UnsupportedImageError("The uploaded file is missing.")

    size_bytes = os.path.getsize(upload_path)
    if size_bytes > MAX_UPLOAD_BYTES:
        raise ImageTooLargeError(
            "This file is %.0f MB. The limit is %d MB."
            % (size_bytes / (1024.0 * 1024.0),
               MAX_UPLOAD_BYTES // (1024 * 1024)))
    if size_bytes == 0:
        raise UnsupportedImageError("The uploaded file is empty.")

    original_name = os.path.basename(upload_path)
    converted_from = None

    decode_path = upload_path
    if _looks_like_heif(upload_path):
        decode_path = _convert_heif(upload_path, workdir)
        converted_from = "heic"

    width, height = _check_dimensions(decode_path)

    try:
        with Image.open(decode_path) as raw:
            raw.load()
            image = normalise(raw)
    except (ImageTooLargeError, UnsupportedImageError):
        raise
    except Exception as exc:           # noqa: BLE001
        raise UnsupportedImageError(
            "This image could not be decoded (%s)." % type(exc).__name__)

    normalised_path = os.path.join(workdir, "source.png")
    image.save(normalised_path, "PNG")

    proxy_path = os.path.join(workdir, "proxy.png")
    make_proxy(image).save(proxy_path, "PNG")

    return Source(path=normalised_path,
                  proxy_path=proxy_path,
                  width=image.size[0],
                  height=image.size[1],
                  original_name=original_name,
                  converted_from=converted_from)
